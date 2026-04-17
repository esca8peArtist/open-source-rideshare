"""Service layer for the Corporate Employee Invitation feature.

Admins issue invitation tokens to prospective employees by email.  The
invitee presents the token (via a link) to accept — this creates a
BusinessAccountMember row linking their user account to the corporate account.

Public surface
--------------
create_invitation(db, account_id, invited_by_id, data)
create_bulk_invitations(db, account_id, invited_by_id, items, expires_at=None)
get_invitation(db, invite_id, account_id)
list_invitations(db, account_id, status_filter=None, skip=0, limit=50)
revoke_invitation(db, invite_id, account_id, revoked_by_id)
validate_invitation_token(db, token_str)       — public, no auth
accept_invitation(db, token_str, accepting_user_id)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccount, BusinessAccountMember, MemberRole
from app.models.corporate_employee_invitation import (
    CorporateEmployeeInvitation,
    InvitationRole,
    InvitationStatus,
)
from app.models.user import User
from app.schemas.corporate_employee_invitation import BulkInvitationItem, InvitationCreate
from app.services import corporate_member_onboarding as _onboarding_svc

_DEFAULT_EXPIRY_DAYS = 7


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(tz=timezone.utc)


async def _require_account_admin(
    db: AsyncSession, account_id: int, user_id: int
) -> None:
    """Raise HTTP 403 if the user is not an active admin of the account."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.role == MemberRole.ADMIN,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have admin access to this corporate account.",
        )


async def _fetch_invitation(
    db: AsyncSession,
    invite_id: uuid.UUID,
    account_id: int,
) -> CorporateEmployeeInvitation | None:
    """Return the invitation if it belongs to account_id, else None."""
    result = await db.execute(
        select(CorporateEmployeeInvitation).where(
            CorporateEmployeeInvitation.id == invite_id,
            CorporateEmployeeInvitation.account_id == account_id,
        )
    )
    return result.scalar_one_or_none()


async def _fetch_by_token(
    db: AsyncSession,
    token: uuid.UUID,
) -> CorporateEmployeeInvitation | None:
    """Return the invitation matching the given token, or None."""
    result = await db.execute(
        select(CorporateEmployeeInvitation).where(
            CorporateEmployeeInvitation.token == token
        )
    )
    return result.scalar_one_or_none()


def _map_role(inv_role: InvitationRole) -> MemberRole:
    """Convert InvitationRole to the MemberRole used by BusinessAccountMember."""
    return MemberRole.ADMIN if inv_role == InvitationRole.ADMIN else MemberRole.MEMBER


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_invitation(
    db: AsyncSession,
    account_id: int,
    invited_by_id: int,
    data: InvitationCreate,
) -> CorporateEmployeeInvitation:
    """Create a new employee invitation for a corporate account.

    The caller must be an admin of the account.  The token is auto-generated.
    expires_at defaults to 7 days from now when omitted in the payload.

    Guards:
    - Only account admins can create invitations.
    - Only one pending invitation per email+account at a time.

    Args:
        db: Database session.
        account_id: Corporate account issuing the invitation.
        invited_by_id: User ID of the admin sending the invitation.
        data: Validated creation payload.

    Returns:
        The newly created CorporateEmployeeInvitation.

    Raises:
        HTTPException 403: Caller is not an account admin.
        HTTPException 409: A pending invitation for this email already exists.
    """
    await _require_account_admin(db, account_id, invited_by_id)

    now = _now_utc()

    # Guard: no duplicate pending invitation for same email+account
    existing_result = await db.execute(
        select(CorporateEmployeeInvitation).where(
            CorporateEmployeeInvitation.account_id == account_id,
            CorporateEmployeeInvitation.email == data.email.lower(),
            CorporateEmployeeInvitation.status == InvitationStatus.PENDING,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A pending invitation for this email address already exists. "
                "Revoke it before sending a new one."
            ),
        )

    expires_at = (
        data.expires_at
        if data.expires_at is not None
        else now + timedelta(days=_DEFAULT_EXPIRY_DAYS)
    )
    # Ensure timezone-aware
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    invitation = CorporateEmployeeInvitation(
        account_id=account_id,
        email=data.email.lower(),
        invited_by_id=invited_by_id,
        role=data.role,
        message=data.message,
        expires_at=expires_at,
        status=InvitationStatus.PENDING,
    )

    db.add(invitation)
    await db.flush()
    return invitation


async def create_bulk_invitations(
    db: AsyncSession,
    account_id: int,
    invited_by_id: int,
    items: list[BulkInvitationItem],
    expires_at: datetime | None = None,
) -> list[dict]:
    """Create multiple employee invitations in a single operation.

    Admin access is verified once upfront.  Each item is then processed
    independently — per-item failures (duplicate pending, email already an
    active member of this account) are recorded as "skipped" entries rather
    than aborting the entire batch.

    Args:
        db: Database session.
        account_id: Corporate account issuing the invitations.
        invited_by_id: User ID of the admin sending the invitations.
        items: List of BulkInvitationItem entries (1–100).
        expires_at: Optional shared expiry; defaults to 7 days from now.

    Returns:
        List of dicts with keys: email, role, status, reason, invitation.
        ``status`` is one of "created" | "skipped" | "error".

    Raises:
        HTTPException 403: Caller is not an account admin.
    """
    await _require_account_admin(db, account_id, invited_by_id)

    now = _now_utc()
    shared_expires_at = (
        expires_at if expires_at is not None else now + timedelta(days=_DEFAULT_EXPIRY_DAYS)
    )
    if shared_expires_at.tzinfo is None:
        shared_expires_at = shared_expires_at.replace(tzinfo=timezone.utc)

    results: list[dict] = []

    for item in items:
        email_lower = item.email.lower()

        # Guard: duplicate pending invitation for same email+account
        existing_pending = await db.execute(
            select(CorporateEmployeeInvitation).where(
                CorporateEmployeeInvitation.account_id == account_id,
                CorporateEmployeeInvitation.email == email_lower,
                CorporateEmployeeInvitation.status == InvitationStatus.PENDING,
            )
        )
        if existing_pending.scalar_one_or_none() is not None:
            results.append(
                {
                    "email": email_lower,
                    "role": item.role,
                    "status": "skipped",
                    "reason": "A pending invitation for this email already exists.",
                    "invitation": None,
                }
            )
            continue

        # Guard: email is already an active member of this account
        already_member = await db.execute(
            select(BusinessAccountMember)
            .join(User, User.id == BusinessAccountMember.user_id)
            .where(
                BusinessAccountMember.account_id == account_id,
                BusinessAccountMember.is_active.is_(True),
                User.email == email_lower,
            )
        )
        if already_member.scalar_one_or_none() is not None:
            results.append(
                {
                    "email": email_lower,
                    "role": item.role,
                    "status": "skipped",
                    "reason": "This email address is already an active member of the account.",
                    "invitation": None,
                }
            )
            continue

        try:
            invitation = CorporateEmployeeInvitation(
                account_id=account_id,
                email=email_lower,
                invited_by_id=invited_by_id,
                role=item.role,
                message=item.message,
                expires_at=shared_expires_at,
                status=InvitationStatus.PENDING,
            )
            db.add(invitation)
            await db.flush()
            results.append(
                {
                    "email": email_lower,
                    "role": item.role,
                    "status": "created",
                    "reason": None,
                    "invitation": invitation,
                }
            )
        except Exception as exc:  # pragma: no cover
            results.append(
                {
                    "email": email_lower,
                    "role": item.role,
                    "status": "error",
                    "reason": str(exc),
                    "invitation": None,
                }
            )

    return results


async def get_invitation(
    db: AsyncSession,
    invite_id: uuid.UUID,
    account_id: int,
) -> CorporateEmployeeInvitation:
    """Return an invitation scoped to the given account.

    Args:
        db: Database session.
        invite_id: UUID of the invitation.
        account_id: Corporate account identifier (for scoping).

    Returns:
        The CorporateEmployeeInvitation.

    Raises:
        HTTPException 404: If not found or not belonging to account_id.
    """
    invitation = await _fetch_invitation(db, invite_id, account_id)
    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found.",
        )
    return invitation


async def list_invitations(
    db: AsyncSession,
    account_id: int,
    status_filter: Optional[InvitationStatus] = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[CorporateEmployeeInvitation], int]:
    """Return invitations for a corporate account with an overall count.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        status_filter: Optional status to filter by.
        skip: Pagination offset.
        limit: Maximum number of results.

    Returns:
        Tuple of (list of invitations ordered by created_at desc, total count).
    """
    base_where = [CorporateEmployeeInvitation.account_id == account_id]
    if status_filter is not None:
        base_where.append(CorporateEmployeeInvitation.status == status_filter)

    count_result = await db.execute(
        select(func.count(CorporateEmployeeInvitation.id)).where(*base_where)
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        select(CorporateEmployeeInvitation)
        .where(*base_where)
        .order_by(CorporateEmployeeInvitation.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(rows_result.scalars().all()), total


async def revoke_invitation(
    db: AsyncSession,
    invite_id: uuid.UUID,
    account_id: int,
    revoked_by_id: int,
) -> CorporateEmployeeInvitation:
    """Revoke a pending invitation, preventing acceptance.

    The caller must be an admin of the account.

    Args:
        db: Database session.
        invite_id: UUID of the invitation.
        account_id: Corporate account identifier.
        revoked_by_id: User ID of the admin performing the revocation.

    Returns:
        The revoked CorporateEmployeeInvitation.

    Raises:
        HTTPException 403: Caller is not an account admin.
        HTTPException 404: If not found.
        HTTPException 409: If already revoked or accepted.
    """
    await _require_account_admin(db, account_id, revoked_by_id)

    invitation = await _fetch_invitation(db, invite_id, account_id)
    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found.",
        )

    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot revoke an invitation with status '{invitation.status.value}'.",
        )

    invitation.status = InvitationStatus.REVOKED
    invitation.revoked_at = _now_utc()
    invitation.revoked_by_id = revoked_by_id

    await db.flush()
    return invitation


async def validate_invitation_token(
    db: AsyncSession,
    token_str: str,
) -> dict:
    """Validate an invitation token and return its usability.

    This is a public endpoint — it must never raise a 404 for unknown tokens;
    it always returns a dict describing validity.

    Args:
        db: Database session.
        token_str: String representation of the invitation token UUID.

    Returns:
        Dict with keys: is_valid, reason, email, role, account_name, expires_at.
    """

    def _invalid(reason: str) -> dict:
        return {
            "is_valid": False,
            "reason": reason,
            "email": None,
            "role": None,
            "account_name": None,
            "expires_at": None,
        }

    try:
        token_uuid = uuid.UUID(token_str)
    except (ValueError, AttributeError):
        return _invalid("Invalid token format.")

    invitation = await _fetch_by_token(db, token_uuid)
    if invitation is None:
        return _invalid("Token not found.")

    if invitation.status == InvitationStatus.REVOKED:
        return _invalid("This invitation has been revoked.")

    if invitation.status == InvitationStatus.ACCEPTED:
        return _invalid("This invitation has already been accepted.")

    now = _now_utc()
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if now > expires_at:
        return _invalid("This invitation has expired.")

    # Fetch account name for display
    account_result = await db.execute(
        select(BusinessAccount).where(BusinessAccount.id == invitation.account_id)
    )
    account = account_result.scalar_one_or_none()
    account_name = account.name if account is not None else None

    return {
        "is_valid": True,
        "reason": None,
        "email": invitation.email,
        "role": invitation.role,
        "account_name": account_name,
        "expires_at": invitation.expires_at,
    }


async def accept_invitation(
    db: AsyncSession,
    token_str: str,
    accepting_user_id: int,
) -> CorporateEmployeeInvitation:
    """Accept an invitation and add the user to the corporate account.

    Creates a BusinessAccountMember row using the role specified in the
    invitation.  If the user is already a member of *any* active account,
    raises 409 (a user may only belong to one corporate account).

    Args:
        db: Database session.
        token_str: String representation of the invitation token UUID.
        accepting_user_id: ID of the authenticated user accepting the invite.

    Returns:
        The accepted CorporateEmployeeInvitation.

    Raises:
        HTTPException 400: Token is not valid (expired, revoked, already accepted,
            bad format).
        HTTPException 409: User already belongs to a corporate account.
    """
    validation = await validate_invitation_token(db, token_str)
    if not validation["is_valid"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=validation["reason"] or "Invitation is not valid.",
        )

    token_uuid = uuid.UUID(token_str)
    invitation = await _fetch_by_token(db, token_uuid)
    # Guaranteed non-None (is_valid was True)

    # Guard: user must not already be an active member of any account
    existing_member_result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.user_id == accepting_user_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    existing_member = existing_member_result.scalar_one_or_none()
    if existing_member is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already a member of a corporate account.",
        )

    # Create the membership
    member = BusinessAccountMember(
        account_id=invitation.account_id,
        user_id=accepting_user_id,
        role=_map_role(invitation.role),
        is_active=True,
    )
    db.add(member)

    # Mark invitation as accepted
    now = _now_utc()
    invitation.status = InvitationStatus.ACCEPTED
    invitation.accepted_at = now
    invitation.accepted_by_id = accepting_user_id

    await db.flush()

    # Auto-create an onboarding record for the new member.  If one already
    # exists (idempotent re-acceptance guard), we silently ignore the 409.
    try:
        await _onboarding_svc.create_onboarding(
            db=db,
            account_id=invitation.account_id,
            member_id=accepting_user_id,
            created_by_id=None,
            invitation_id=invitation.id,
        )
    except HTTPException as exc:
        if exc.status_code != status.HTTP_409_CONFLICT:
            raise

    return invitation
