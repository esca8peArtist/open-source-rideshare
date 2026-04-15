"""Corporate Guest Pass endpoints.

Member endpoints (any active employee of the account):
  POST   /corporate/accounts/me/guest-passes                    — create pass → 201
  GET    /corporate/accounts/me/guest-passes                    — list passes
  GET    /corporate/accounts/me/guest-passes/{pass_id}          — get pass
  PATCH  /corporate/accounts/me/guest-passes/{pass_id}          — update pass
  DELETE /corporate/accounts/me/guest-passes/{pass_id}          — revoke pass

Public endpoints (no auth required):
  GET    /guest-pass/{token}                                     — validate token

Platform-admin endpoints:
  GET    /admin/corporate/guest-passes                           — list all passes
  GET    /admin/corporate/accounts/{account_id}/guest-passes     — list by account
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_guest_pass import GuestPassStatus
from app.models.user import User
from app.schemas.corporate_guest_pass import (
    GuestPassCreate,
    GuestPassResponse,
    GuestPassUpdate,
    GuestPassValidationResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_guest_pass import (
    create_guest_pass,
    get_guest_pass,
    get_guest_pass_rides,
    list_guest_passes,
    revoke_guest_pass,
    update_guest_pass,
    use_guest_pass,
    validate_guest_pass_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-guest-pass"])


# ---------------------------------------------------------------------------
# Internal helper: resolve the calling user's account_id
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the account_id for the authenticated user.

    Raises HTTP 404 if the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Member: create a guest pass
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/guest-passes",
    response_model=GuestPassResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a new guest pass (employee)",
)
async def create_my_guest_pass(
    data: GuestPassCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Issue a new guest pass for the authenticated employee's corporate account.

    The guest pass contains a unique token the recipient can use to book a ride
    charged to the corporate account without a corporate login.

    ``valid_until`` must be a future datetime.  ``max_uses`` (if provided) must
    be a positive integer; omit for unlimited uses.
    """
    account_id = await _resolve_account_id(db, user.id)
    guest_pass = await create_guest_pass(db, account_id, user.id, data)
    await db.commit()
    await db.refresh(guest_pass)
    return GuestPassResponse.model_validate(guest_pass)


# ---------------------------------------------------------------------------
# Member: list guest passes
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/guest-passes",
    response_model=list[GuestPassResponse],
    summary="List guest passes for own corporate account",
)
async def list_my_guest_passes(
    status_filter: GuestPassStatus | None = Query(
        None, alias="status", description="Filter by pass status."
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return guest passes issued under the authenticated employee's account.

    Optionally filter by status: ``active``, ``exhausted``, ``expired``,
    or ``revoked``.
    """
    account_id = await _resolve_account_id(db, user.id)
    passes = await list_guest_passes(
        db, account_id, status_filter=status_filter, skip=skip, limit=limit
    )
    return [GuestPassResponse.model_validate(p) for p in passes]


# ---------------------------------------------------------------------------
# Member: get a guest pass by ID
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/guest-passes/{pass_id}",
    response_model=GuestPassResponse,
    summary="Get a guest pass by ID",
)
async def get_my_guest_pass(
    pass_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single guest pass belonging to the authenticated employee's account."""
    account_id = await _resolve_account_id(db, user.id)
    guest_pass = await get_guest_pass(db, pass_id, account_id)
    return GuestPassResponse.model_validate(guest_pass)


# ---------------------------------------------------------------------------
# Member: update a guest pass
# ---------------------------------------------------------------------------


@router.patch(
    "/corporate/accounts/me/guest-passes/{pass_id}",
    response_model=GuestPassResponse,
    summary="Update a guest pass",
)
async def update_my_guest_pass(
    pass_id: uuid.UUID,
    data: GuestPassUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update label, budget, expiry, or other fields on an active guest pass.

    Cannot update a pass that is revoked or exhausted.  Only non-null fields
    in the request body are applied.
    """
    account_id = await _resolve_account_id(db, user.id)
    guest_pass = await update_guest_pass(db, pass_id, account_id, data)
    await db.commit()
    await db.refresh(guest_pass)
    return GuestPassResponse.model_validate(guest_pass)


# ---------------------------------------------------------------------------
# Member: revoke a guest pass
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/guest-passes/{pass_id}",
    response_model=GuestPassResponse,
    summary="Revoke a guest pass",
)
async def revoke_my_guest_pass(
    pass_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a guest pass, preventing any further use.

    The pass is not deleted — its history and all linked ride records are
    retained.  Returns the updated pass with ``status=revoked``.
    """
    account_id = await _resolve_account_id(db, user.id)
    guest_pass = await revoke_guest_pass(db, pass_id, account_id, user.id)
    await db.commit()
    await db.refresh(guest_pass)
    return GuestPassResponse.model_validate(guest_pass)


# ---------------------------------------------------------------------------
# Public: validate a guest pass token
# ---------------------------------------------------------------------------


@router.get(
    "/guest-pass/{token}",
    response_model=GuestPassValidationResponse,
    summary="Validate a guest pass token (public, no auth)",
)
async def validate_token(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Check whether a guest pass token is valid and may be used to book a ride.

    This endpoint requires no authentication.  It never returns a 404 for
    unrecognised tokens — instead it returns ``is_valid: false`` with a
    human-readable ``reason``.

    A valid response includes the pass label, per-ride budget cap, and the
    corporate account name — enough information for the guest to confirm they
    have the right token before starting a booking.
    """
    result = await validate_guest_pass_token(db, token)
    return GuestPassValidationResponse(**result)


# ---------------------------------------------------------------------------
# Platform admin: list all guest passes
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/guest-passes",
    response_model=list[GuestPassResponse],
    summary="Admin: list all guest passes across all accounts",
)
async def admin_list_all_guest_passes(
    status_filter: GuestPassStatus | None = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all guest passes across the platform.

    Optionally filter by status.  Intended for platform administrators only.
    """
    from sqlalchemy import select as sa_select
    from app.models.corporate_guest_pass import CorporateGuestPass

    q = sa_select(CorporateGuestPass)
    if status_filter is not None:
        q = q.where(CorporateGuestPass.status == status_filter)
    q = q.order_by(CorporateGuestPass.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(q)
    passes = list(result.scalars().all())
    return [GuestPassResponse.model_validate(p) for p in passes]


# ---------------------------------------------------------------------------
# Platform admin: list guest passes for a specific account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/guest-passes",
    response_model=list[GuestPassResponse],
    summary="Admin: list guest passes for a specific corporate account",
)
async def admin_list_account_guest_passes(
    account_id: int,
    status_filter: GuestPassStatus | None = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all guest passes for a specific corporate account.

    Intended for platform administrators to audit or manage passes on behalf
    of an account.
    """
    passes = await list_guest_passes(
        db, account_id, status_filter=status_filter, skip=skip, limit=limit
    )
    return [GuestPassResponse.model_validate(p) for p in passes]
