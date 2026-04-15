"""Service layer for the Corporate Guest Pass feature.

Corporate employees issue limited-use booking tokens (guest passes) to
non-employees.  Guests present the token at booking time — no corporate
login is required.  The resulting ride is billed to the issuing account.

Public surface
--------------
create_guest_pass(db, account_id, employee_id, data)
get_guest_pass(db, pass_id, account_id)
list_guest_passes(db, account_id, status_filter=None, skip=0, limit=50)
update_guest_pass(db, pass_id, account_id, data)
revoke_guest_pass(db, pass_id, account_id, revoked_by_id)
validate_guest_pass_token(db, token_str)
use_guest_pass(db, token_str, ride_id)
get_guest_pass_rides(db, pass_id, account_id)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccount
from app.models.corporate_guest_pass import CorporateGuestPass, GuestPassStatus
from app.models.ride import Ride
from app.schemas.corporate_guest_pass import GuestPassCreate, GuestPassUpdate


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(tz=timezone.utc)


async def _fetch_guest_pass(
    db: AsyncSession,
    pass_id: uuid.UUID,
    account_id: int,
) -> CorporateGuestPass | None:
    """Return the guest pass if it belongs to account_id, else None."""
    result = await db.execute(
        select(CorporateGuestPass).where(
            CorporateGuestPass.id == pass_id,
            CorporateGuestPass.account_id == account_id,
        )
    )
    return result.scalar_one_or_none()


async def _fetch_pass_by_token(
    db: AsyncSession,
    token: uuid.UUID,
) -> CorporateGuestPass | None:
    """Return the guest pass matching the given token, or None."""
    result = await db.execute(
        select(CorporateGuestPass).where(CorporateGuestPass.token == token)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_guest_pass(
    db: AsyncSession,
    account_id: int,
    employee_id: int,
    data: GuestPassCreate,
) -> CorporateGuestPass:
    """Create a new guest pass for the given corporate account.

    The token is auto-generated.  If max_uses is set, uses_remaining is
    initialised to the same value.  valid_from defaults to now when omitted.

    Args:
        db: Database session.
        account_id: Corporate account the pass belongs to.
        employee_id: ID of the employee issuing the pass.
        data: Validated creation payload.

    Returns:
        The newly created CorporateGuestPass.

    Raises:
        HTTPException 400: If valid_until is not in the future.
    """
    now = _now_utc()

    valid_from = data.valid_from if data.valid_from is not None else now

    guest_pass = CorporateGuestPass(
        account_id=account_id,
        created_by_employee_id=employee_id,
        label=data.label,
        max_uses=data.max_uses,
        uses_remaining=data.max_uses,  # None when unlimited
        max_ride_budget_usd=data.max_ride_budget_usd,
        trip_purpose_id=data.trip_purpose_id,
        cost_center_id=data.cost_center_id,
        valid_from=valid_from,
        valid_until=data.valid_until,
        status=GuestPassStatus.ACTIVE,
    )

    db.add(guest_pass)
    await db.flush()
    return guest_pass


async def get_guest_pass(
    db: AsyncSession,
    pass_id: uuid.UUID,
    account_id: int,
) -> CorporateGuestPass:
    """Return a guest pass scoped to the given account.

    Args:
        db: Database session.
        pass_id: UUID of the guest pass.
        account_id: Corporate account identifier (for scoping).

    Returns:
        The CorporateGuestPass.

    Raises:
        HTTPException 404: If not found or not belonging to account_id.
    """
    guest_pass = await _fetch_guest_pass(db, pass_id, account_id)
    if guest_pass is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guest pass not found.",
        )
    return guest_pass


async def list_guest_passes(
    db: AsyncSession,
    account_id: int,
    status_filter: Optional[GuestPassStatus] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[CorporateGuestPass]:
    """Return guest passes for a corporate account.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        status_filter: Optional status to filter by.
        skip: Pagination offset.
        limit: Maximum number of results.

    Returns:
        List of CorporateGuestPass ordered by created_at descending.
    """
    q = select(CorporateGuestPass).where(
        CorporateGuestPass.account_id == account_id
    )
    if status_filter is not None:
        q = q.where(CorporateGuestPass.status == status_filter)
    q = q.order_by(CorporateGuestPass.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(q)
    return list(result.scalars().all())


async def update_guest_pass(
    db: AsyncSession,
    pass_id: uuid.UUID,
    account_id: int,
    data: GuestPassUpdate,
) -> CorporateGuestPass:
    """Update a guest pass.

    Only non-None fields in the payload are applied.  Cannot update passes
    that are revoked or exhausted.

    Args:
        db: Database session.
        pass_id: UUID of the guest pass.
        account_id: Corporate account identifier.
        data: Validated update payload.

    Returns:
        The updated CorporateGuestPass.

    Raises:
        HTTPException 404: If not found.
        HTTPException 409: If the pass is revoked or exhausted.
    """
    guest_pass = await _fetch_guest_pass(db, pass_id, account_id)
    if guest_pass is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guest pass not found.",
        )

    if guest_pass.status in (GuestPassStatus.REVOKED, GuestPassStatus.EXHAUSTED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot update a guest pass with status '{guest_pass.status.value}'.",
        )

    if data.label is not None:
        guest_pass.label = data.label
    if data.max_uses is not None:
        guest_pass.max_uses = data.max_uses
    if data.max_ride_budget_usd is not None:
        guest_pass.max_ride_budget_usd = data.max_ride_budget_usd
    if data.valid_until is not None:
        guest_pass.valid_until = data.valid_until
    if data.trip_purpose_id is not None:
        guest_pass.trip_purpose_id = data.trip_purpose_id
    if data.cost_center_id is not None:
        guest_pass.cost_center_id = data.cost_center_id

    await db.flush()
    return guest_pass


async def revoke_guest_pass(
    db: AsyncSession,
    pass_id: uuid.UUID,
    account_id: int,
    revoked_by_id: int,
) -> CorporateGuestPass:
    """Revoke a guest pass, preventing any further use.

    Args:
        db: Database session.
        pass_id: UUID of the guest pass.
        account_id: Corporate account identifier.
        revoked_by_id: User ID of the employee performing the revocation.

    Returns:
        The revoked CorporateGuestPass.

    Raises:
        HTTPException 404: If not found.
        HTTPException 409: If already revoked.
    """
    guest_pass = await _fetch_guest_pass(db, pass_id, account_id)
    if guest_pass is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guest pass not found.",
        )

    if guest_pass.status == GuestPassStatus.REVOKED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Guest pass is already revoked.",
        )

    guest_pass.status = GuestPassStatus.REVOKED
    guest_pass.revoked_at = _now_utc()
    guest_pass.revoked_by_id = revoked_by_id

    await db.flush()
    return guest_pass


async def validate_guest_pass_token(
    db: AsyncSession,
    token_str: str,
) -> dict:
    """Validate a guest pass token and return its usability.

    This is a public endpoint — it must never raise a 404 for unknown tokens;
    it always returns a dict describing validity.

    Args:
        db: Database session.
        token_str: String representation of the guest pass token UUID.

    Returns:
        Dict with keys: is_valid, reason, label, max_ride_budget_usd, account_name.
    """
    # Attempt to parse the token as a UUID
    try:
        token_uuid = uuid.UUID(token_str)
    except (ValueError, AttributeError):
        return {
            "is_valid": False,
            "reason": "Invalid token format.",
            "label": None,
            "max_ride_budget_usd": None,
            "account_name": None,
        }

    guest_pass = await _fetch_pass_by_token(db, token_uuid)

    if guest_pass is None:
        return {
            "is_valid": False,
            "reason": "Token not found.",
            "label": None,
            "max_ride_budget_usd": None,
            "account_name": None,
        }

    now = _now_utc()

    # Check status first
    if guest_pass.status == GuestPassStatus.REVOKED:
        return {
            "is_valid": False,
            "reason": "This guest pass has been revoked.",
            "label": guest_pass.label,
            "max_ride_budget_usd": guest_pass.max_ride_budget_usd,
            "account_name": None,
        }

    if guest_pass.status == GuestPassStatus.EXHAUSTED:
        return {
            "is_valid": False,
            "reason": "This guest pass has no uses remaining.",
            "label": guest_pass.label,
            "max_ride_budget_usd": guest_pass.max_ride_budget_usd,
            "account_name": None,
        }

    # Normalise valid_from and valid_until for comparison
    valid_from = guest_pass.valid_from
    if valid_from.tzinfo is None:
        valid_from = valid_from.replace(tzinfo=timezone.utc)

    valid_until = guest_pass.valid_until
    if valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=timezone.utc)

    if now < valid_from:
        return {
            "is_valid": False,
            "reason": "This guest pass is not yet valid.",
            "label": guest_pass.label,
            "max_ride_budget_usd": guest_pass.max_ride_budget_usd,
            "account_name": None,
        }

    if now > valid_until:
        return {
            "is_valid": False,
            "reason": "This guest pass has expired.",
            "label": guest_pass.label,
            "max_ride_budget_usd": guest_pass.max_ride_budget_usd,
            "account_name": None,
        }

    # Fetch account name for display
    account_result = await db.execute(
        select(BusinessAccount).where(BusinessAccount.id == guest_pass.account_id)
    )
    account = account_result.scalar_one_or_none()
    account_name = account.name if account is not None else None

    return {
        "is_valid": True,
        "reason": None,
        "label": guest_pass.label,
        "max_ride_budget_usd": guest_pass.max_ride_budget_usd,
        "account_name": account_name,
    }


async def use_guest_pass(
    db: AsyncSession,
    token_str: str,
    ride_id: int,
) -> CorporateGuestPass:
    """Consume one use of a guest pass, linking it to a ride.

    Decrements uses_remaining.  When uses_remaining reaches 0, the status
    is automatically set to EXHAUSTED.

    Args:
        db: Database session.
        token_str: String representation of the guest pass token UUID.
        ride_id: The ride being booked with this pass.

    Returns:
        The updated CorporateGuestPass.

    Raises:
        HTTPException 400: If the pass is not valid (revoked, exhausted, expired,
            invalid token, or not yet valid).
    """
    validation = await validate_guest_pass_token(db, token_str)
    if not validation["is_valid"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=validation["reason"] or "Guest pass is not valid.",
        )

    token_uuid = uuid.UUID(token_str)
    guest_pass = await _fetch_pass_by_token(db, token_uuid)
    # guest_pass is guaranteed non-None here (is_valid was True)

    # Link the ride to this pass
    ride_result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = ride_result.scalar_one_or_none()
    if ride is not None:
        ride.guest_pass_id = guest_pass.id

    # Decrement uses_remaining if limited
    if guest_pass.uses_remaining is not None:
        guest_pass.uses_remaining -= 1
        if guest_pass.uses_remaining <= 0:
            guest_pass.status = GuestPassStatus.EXHAUSTED
            guest_pass.uses_remaining = 0

    await db.flush()
    return guest_pass


async def get_guest_pass_rides(
    db: AsyncSession,
    pass_id: uuid.UUID,
    account_id: int,
) -> list[int]:
    """Return ride IDs linked to the given guest pass.

    Args:
        db: Database session.
        pass_id: UUID of the guest pass.
        account_id: Corporate account identifier (for scoping).

    Returns:
        List of ride IDs (integers) linked to this pass.

    Raises:
        HTTPException 404: If the pass is not found for this account.
    """
    guest_pass = await _fetch_guest_pass(db, pass_id, account_id)
    if guest_pass is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guest pass not found.",
        )

    result = await db.execute(
        select(Ride.id).where(Ride.guest_pass_id == pass_id)
    )
    return list(result.scalars().all())
