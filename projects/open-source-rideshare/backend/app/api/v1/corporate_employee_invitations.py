"""Corporate Employee Invitation API endpoints.

Admins issue email-based invitation tokens to onboard employees into the
corporate account.  The invitee validates the token and accepts it —
creating their membership automatically without further admin action.

Member endpoints (any active account member):
  GET    /corporate/accounts/me/invitations                  — list invitations
  GET    /corporate/accounts/me/invitations/{invite_id}      — get invitation

Member endpoints (account admin required):
  POST   /corporate/accounts/me/invitations                  — create invitation
  DELETE /corporate/accounts/me/invitations/{invite_id}      — revoke invitation

Public endpoints (no auth required):
  GET    /corporate/invitations/{token}                       — validate token

Authenticated user endpoints:
  POST   /corporate/invitations/{token}/accept                — accept invitation

Platform-admin endpoints:
  GET    /admin/corporate/invitations                         — list all invitations
  GET    /admin/corporate/accounts/{account_id}/invitations   — list by account
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate import BusinessAccountMember
from app.models.corporate_employee_invitation import InvitationStatus
from app.models.user import User
from app.schemas.corporate_employee_invitation import (
    BulkInvitationItemResult,
    BulkInvitationRequest,
    BulkInvitationResponse,
    InvitationCreate,
    InvitationListResponse,
    InvitationResponse,
    InvitationValidationResponse,
)
from app.services.corporate_employee_invitation import (
    accept_invitation,
    create_bulk_invitations,
    create_invitation,
    get_invitation,
    list_invitations,
    revoke_invitation,
    validate_invitation_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-employee-invitations"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_member_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the corporate account ID the user belongs to.

    Raises HTTP 404 if the user is not an active member of any account.
    """
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return membership.account_id


# ---------------------------------------------------------------------------
# Member: create an invitation (admin only — enforced in service)
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new employee invitation (account admin)",
)
async def create_my_invitation(
    data: InvitationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Invite a prospective employee to join the corporate account.

    Only account admins may create invitations.  A shareable token is
    generated automatically — the invitee uses it at
    ``POST /corporate/invitations/{token}/accept``.

    ``expires_at`` defaults to 7 days from now when omitted.

    Only one pending invitation per email address is allowed per account.
    Revoke the existing invite before resending to the same address.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    invitation = await create_invitation(db, account_id, current_user.id, data)
    await db.commit()
    await db.refresh(invitation)
    return InvitationResponse.model_validate(invitation)


# ---------------------------------------------------------------------------
# Member: bulk create invitations (admin only — declared before /{invite_id})
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/invitations/bulk",
    response_model=BulkInvitationResponse,
    status_code=status.HTTP_200_OK,
    summary="Bulk-create employee invitations (account admin)",
)
async def create_bulk_my_invitations(
    data: BulkInvitationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Invite up to 100 prospective employees in a single request.

    Only account admins may use this endpoint.  Each item is processed
    independently — duplicate emails or emails already belonging to an active
    member are recorded as ``skipped`` entries rather than aborting the batch.

    A shared ``expires_at`` may be provided; it defaults to 7 days from now.

    Returns a summary with per-item results and aggregate counts.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    raw_results = await create_bulk_invitations(
        db,
        account_id,
        current_user.id,
        data.invitations,
        expires_at=data.expires_at,
    )
    await db.commit()

    # Refresh created invitations so all DB-generated fields are populated
    item_results: list[BulkInvitationItemResult] = []
    for r in raw_results:
        inv_resp = None
        if r["status"] == "created" and r["invitation"] is not None:
            await db.refresh(r["invitation"])
            inv_resp = InvitationResponse.model_validate(r["invitation"])
        item_results.append(
            BulkInvitationItemResult(
                email=r["email"],
                role=r["role"],
                status=r["status"],
                reason=r["reason"],
                invitation=inv_resp,
            )
        )

    total_created = sum(1 for r in item_results if r.status == "created")
    total_skipped = sum(1 for r in item_results if r.status == "skipped")
    total_errors = sum(1 for r in item_results if r.status == "error")

    return BulkInvitationResponse(
        total_requested=len(item_results),
        total_created=total_created,
        total_skipped=total_skipped,
        total_errors=total_errors,
        results=item_results,
    )


# ---------------------------------------------------------------------------
# Member: list invitations
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/invitations",
    response_model=InvitationListResponse,
    summary="List invitations for own corporate account",
)
async def list_my_invitations(
    status_filter: InvitationStatus | None = Query(
        None, alias="status", description="Filter by invitation status."
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return invitations for the authenticated member's corporate account.

    Optionally filter by status: ``pending``, ``accepted``, ``revoked``, or
    ``expired``.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    items, total = await list_invitations(
        db, account_id, status_filter=status_filter, skip=skip, limit=limit
    )
    return InvitationListResponse(
        items=[InvitationResponse.model_validate(i) for i in items],
        total=total,
        skip=skip,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Member: get a single invitation
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/invitations/{invite_id}",
    response_model=InvitationResponse,
    summary="Get a single invitation",
)
async def get_my_invitation(
    invite_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a specific invitation scoped to the caller's corporate account."""
    account_id = await _get_member_account_id(db, current_user.id)
    invitation = await get_invitation(db, invite_id, account_id)
    return InvitationResponse.model_validate(invitation)


# ---------------------------------------------------------------------------
# Member: revoke an invitation (admin only — enforced in service)
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/invitations/{invite_id}",
    response_model=InvitationResponse,
    summary="Revoke a pending invitation (account admin)",
)
async def revoke_my_invitation(
    invite_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke a pending invitation, preventing future acceptance.

    Only account admins may revoke invitations.  Already-accepted or
    already-revoked invitations cannot be revoked again.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    invitation = await revoke_invitation(db, invite_id, account_id, current_user.id)
    await db.commit()
    await db.refresh(invitation)
    return InvitationResponse.model_validate(invitation)


# ---------------------------------------------------------------------------
# Public: validate an invitation token
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/invitations/{token}",
    response_model=InvitationValidationResponse,
    summary="Validate an invitation token (public)",
)
async def validate_token(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Return whether the given invitation token is valid and claimable.

    This endpoint is public and requires no authentication.  It never
    returns 404 — it always returns a JSON body with ``is_valid`` and a
    human-readable ``reason`` when invalid.
    """
    result = await validate_invitation_token(db, token)
    return InvitationValidationResponse(**result)


# ---------------------------------------------------------------------------
# Authenticated: accept an invitation
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/invitations/{token}/accept",
    response_model=InvitationResponse,
    status_code=status.HTTP_200_OK,
    summary="Accept an invitation (authenticated user)",
)
async def accept_my_invitation(
    token: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accept a corporate account invitation as the authenticated user.

    On success, the user is added to the corporate account with the role
    specified in the invitation.  The invitation is marked as accepted.

    Returns 400 if the token is expired, revoked, or already accepted.
    Returns 409 if the user already belongs to a corporate account.
    """
    invitation = await accept_invitation(db, token, current_user.id)
    await db.commit()
    await db.refresh(invitation)
    return InvitationResponse.model_validate(invitation)


# ---------------------------------------------------------------------------
# Platform-admin: list all invitations
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/invitations",
    response_model=InvitationListResponse,
    summary="[Admin] List all corporate invitations",
    dependencies=[Depends(require_admin)],
)
async def admin_list_all_invitations(
    status_filter: InvitationStatus | None = Query(
        None, alias="status", description="Filter by invitation status."
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Return all corporate employee invitations across all accounts.

    Optionally filter by status.
    """
    from sqlalchemy import select as sa_select
    from app.models.corporate_employee_invitation import CorporateEmployeeInvitation
    from sqlalchemy import func

    base_where = []
    if status_filter is not None:
        base_where.append(CorporateEmployeeInvitation.status == status_filter)

    count_result = await db.execute(
        sa_select(func.count(CorporateEmployeeInvitation.id)).where(*base_where)
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        sa_select(CorporateEmployeeInvitation)
        .where(*base_where)
        .order_by(CorporateEmployeeInvitation.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    items = list(rows_result.scalars().all())
    return InvitationListResponse(
        items=[InvitationResponse.model_validate(i) for i in items],
        total=total,
        skip=skip,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Platform-admin: list invitations for a specific account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/invitations",
    response_model=InvitationListResponse,
    summary="[Admin] List invitations for a specific corporate account",
    dependencies=[Depends(require_admin)],
)
async def admin_list_account_invitations(
    account_id: int,
    status_filter: InvitationStatus | None = Query(
        None, alias="status", description="Filter by invitation status."
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Return corporate employee invitations for a specific account.

    Optionally filter by status.
    """
    items, total = await list_invitations(
        db, account_id, status_filter=status_filter, skip=skip, limit=limit
    )
    return InvitationListResponse(
        items=[InvitationResponse.model_validate(i) for i in items],
        total=total,
        skip=skip,
        limit=limit,
    )
