"""Service layer for Corporate Trip Purpose Codes.

Corporate account admins define purpose codes (e.g. "CLIENT_MEETING").
Employees tag their rides with a purpose code.  Analytics break down
corporate spend by purpose.

Public surface
--------------
create_purpose(db, account_id, data)
get_purpose(db, account_id, purpose_id)
list_purposes(db, account_id, include_inactive=False)
update_purpose(db, account_id, purpose_id, data)
deactivate_purpose(db, account_id, purpose_id)
set_ride_purpose(db, ride_id, user_id, purpose_id, notes)
get_purpose_spend_analytics(db, account_id, start_date=None, end_date=None)
list_ride_purposes_for_account(db, ride_id, account_id)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_trip_purpose import CorporateTripPurpose
from app.models.ride import Ride, RideStatus
from app.schemas.corporate_trip_purpose import (
    CorporateTripPurposeCreate,
    CorporateTripPurposeUpdate,
    TripPurposeSpendItem,
    TripPurposeSpendResponse,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _require_account_admin(
    db: AsyncSession, account_id: int, user_id: int
) -> BusinessAccountMember:
    """Raise HTTP 403 when the user is not an active admin of the account."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.role == MemberRole.ADMIN,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have admin access to this corporate account.",
        )
    return member


async def _require_account_member(
    db: AsyncSession, account_id: int, user_id: int
) -> BusinessAccountMember:
    """Raise HTTP 403 when the user is not an active member of the account."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not an active member of this corporate account.",
        )
    return member


def _safe_avg(total: Decimal, count: int) -> Decimal | None:
    """Return average rounded to 2 d.p., or None if count is zero."""
    if count == 0:
        return None
    return (total / count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_purpose(
    db: AsyncSession,
    account_id: int,
    data: CorporateTripPurposeCreate,
) -> tuple[CorporateTripPurpose, None] | tuple[None, HTTPException]:
    """Create a new trip purpose code for a corporate account.

    The code is normalised to uppercase before storage.  Duplicate codes
    within the same account return a 409 Conflict error.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        data: Validated creation payload.

    Returns:
        Tuple of (purpose, None) on success, or (None, HTTPException) on conflict.
    """
    normalised_code = data.code.upper().strip()

    # Check for duplicate code within account
    existing = await db.execute(
        select(CorporateTripPurpose).where(
            CorporateTripPurpose.account_id == account_id,
            CorporateTripPurpose.code == normalised_code,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return None, HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A purpose code '{normalised_code}' already exists for this account.",
        )

    purpose = CorporateTripPurpose(
        account_id=account_id,
        code=normalised_code,
        label=data.label,
        is_active=True,
        requires_notes=data.requires_notes,
    )
    db.add(purpose)
    await db.flush()
    return purpose, None


async def get_purpose(
    db: AsyncSession,
    account_id: int,
    purpose_id: int,
) -> CorporateTripPurpose | None:
    """Fetch a single purpose code belonging to account_id.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        purpose_id: Purpose code identifier.

    Returns:
        CorporateTripPurpose if found, None otherwise.
    """
    result = await db.execute(
        select(CorporateTripPurpose).where(
            CorporateTripPurpose.id == purpose_id,
            CorporateTripPurpose.account_id == account_id,
        )
    )
    return result.scalar_one_or_none()


async def list_purposes(
    db: AsyncSession,
    account_id: int,
    include_inactive: bool = False,
) -> list[CorporateTripPurpose]:
    """Return purpose codes for a corporate account.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        include_inactive: When False (default) only active purposes are returned.

    Returns:
        List of CorporateTripPurpose ordered by code ascending.
    """
    q = select(CorporateTripPurpose).where(
        CorporateTripPurpose.account_id == account_id
    )
    if not include_inactive:
        q = q.where(CorporateTripPurpose.is_active.is_(True))
    q = q.order_by(CorporateTripPurpose.code)

    result = await db.execute(q)
    return list(result.scalars().all())


async def update_purpose(
    db: AsyncSession,
    account_id: int,
    purpose_id: int,
    data: CorporateTripPurposeUpdate,
) -> tuple[CorporateTripPurpose, None] | tuple[None, HTTPException]:
    """Update label, is_active, or requires_notes on an existing purpose.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        purpose_id: Purpose code identifier.
        data: Validated update payload (only non-None fields applied).

    Returns:
        Tuple of (purpose, None) on success, or (None, HTTPException) on 404.
    """
    purpose = await get_purpose(db, account_id, purpose_id)
    if purpose is None:
        return None, HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip purpose not found.",
        )

    if data.label is not None:
        purpose.label = data.label
    if data.is_active is not None:
        purpose.is_active = data.is_active
    if data.requires_notes is not None:
        purpose.requires_notes = data.requires_notes

    await db.flush()
    return purpose, None


async def deactivate_purpose(
    db: AsyncSession,
    account_id: int,
    purpose_id: int,
) -> tuple[CorporateTripPurpose, None] | tuple[None, HTTPException]:
    """Set is_active=False on a purpose code without deleting it.

    Rides that already reference this purpose retain their tag.  The purpose
    is simply no longer assignable to new rides.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        purpose_id: Purpose code identifier.

    Returns:
        Tuple of (purpose, None) on success, or (None, HTTPException) on 404.
    """
    purpose = await get_purpose(db, account_id, purpose_id)
    if purpose is None:
        return None, HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip purpose not found.",
        )

    purpose.is_active = False
    await db.flush()
    return purpose, None


async def set_ride_purpose(
    db: AsyncSession,
    ride_id: int,
    user_id: int,
    purpose_id: int | None,
    notes: str | None,
) -> tuple[Ride, None] | tuple[None, HTTPException]:
    """Tag (or clear) a corporate ride with a trip purpose.

    Validates that:
    - The ride belongs to the requesting user.
    - When purpose_id is given, the purpose belongs to the ride's corporate account.
    - When purpose.requires_notes is True, notes must be non-empty.

    Args:
        db: Database session.
        ride_id: Ride identifier.
        user_id: Authenticated rider's user ID.
        purpose_id: Purpose to assign, or None to clear the tag.
        notes: Optional notes for the trip.

    Returns:
        Tuple of (ride, None) on success, or (None, HTTPException) on error.
    """
    # Fetch ride and verify ownership
    ride_result = await db.execute(
        select(Ride).where(Ride.id == ride_id)
    )
    ride = ride_result.scalar_one_or_none()
    if ride is None:
        return None, HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found.",
        )
    if ride.rider_id != user_id:
        return None, HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to tag this ride.",
        )

    if purpose_id is None:
        # Clear the tag
        ride.trip_purpose_id = None
        ride.trip_notes = None
        await db.flush()
        return ride, None

    # Validate purpose exists and belongs to the ride's corporate account
    if ride.corporate_account_id is None:
        return None, HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This ride is not associated with a corporate account.",
        )

    purpose = await get_purpose(db, ride.corporate_account_id, purpose_id)
    if purpose is None or not purpose.is_active:
        return None, HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Trip purpose not found or not active for this corporate account.",
        )

    # Enforce notes requirement
    if purpose.requires_notes and not (notes and notes.strip()):
        return None, HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Notes are required when using this trip purpose.",
        )

    ride.trip_purpose_id = purpose_id
    ride.trip_notes = notes
    await db.flush()
    return ride, None


async def get_purpose_spend_analytics(
    db: AsyncSession,
    account_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> TripPurposeSpendResponse:
    """Return spend grouped by trip purpose for a corporate account.

    All completed rides for the account are grouped by trip_purpose_id.
    Rides without a purpose tag are counted in the untagged bucket.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        start_date: Optional inclusive start of the analysis window.
        end_date: Optional inclusive end of the analysis window.

    Returns:
        TripPurposeSpendResponse with per-purpose items and untagged totals.
    """
    base_filters = [
        Ride.corporate_account_id == account_id,
        Ride.actual_fare.is_not(None),
        Ride.completed_at.is_not(None),
    ]
    if start_date is not None:
        base_filters.append(func.date(Ride.completed_at) >= start_date)
    if end_date is not None:
        base_filters.append(func.date(Ride.completed_at) <= end_date)

    # Aggregate by trip_purpose_id (None = untagged)
    agg_result = await db.execute(
        select(
            Ride.trip_purpose_id.label("purpose_id"),
            func.count(Ride.id).label("ride_count"),
            func.coalesce(func.sum(Ride.actual_fare), 0).label("total_spend"),
        )
        .where(*base_filters)
        .group_by(Ride.trip_purpose_id)
    )
    agg_rows = agg_result.all()

    # Separate tagged vs untagged
    tagged_rows = [r for r in agg_rows if r.purpose_id is not None]
    untagged_rows = [r for r in agg_rows if r.purpose_id is None]

    untagged_ride_count = sum(r.ride_count for r in untagged_rows)
    untagged_total = Decimal(str(sum(r.total_spend for r in untagged_rows)))

    # Fetch purpose metadata for tagged rows
    items: list[TripPurposeSpendItem] = []
    if tagged_rows:
        purpose_ids = [r.purpose_id for r in tagged_rows]
        purposes_result = await db.execute(
            select(CorporateTripPurpose).where(
                CorporateTripPurpose.id.in_(purpose_ids)
            )
        )
        purpose_map = {p.id: p for p in purposes_result.scalars().all()}

        for row in tagged_rows:
            purpose = purpose_map.get(row.purpose_id)
            if purpose is None:
                continue
            ride_count = row.ride_count or 0
            total_usd = Decimal(str(row.total_spend or 0))
            items.append(
                TripPurposeSpendItem(
                    purpose_id=row.purpose_id,
                    code=purpose.code,
                    label=purpose.label,
                    ride_count=ride_count,
                    total_usd=total_usd,
                    avg_usd=_safe_avg(total_usd, ride_count),
                )
            )

    # Sort by total_usd descending for convenience
    items.sort(key=lambda x: x.total_usd, reverse=True)

    return TripPurposeSpendResponse(
        account_id=account_id,
        items=items,
        untagged_ride_count=untagged_ride_count,
        untagged_total_usd=untagged_total,
    )


async def list_ride_purposes_for_account(
    db: AsyncSession,
    ride_id: int,
    account_id: int,
) -> CorporateTripPurpose | None:
    """Return the purpose tagged on a specific ride, scoped to an account.

    Args:
        db: Database session.
        ride_id: Ride identifier.
        account_id: Corporate account identifier (used to scope the lookup).

    Returns:
        CorporateTripPurpose if the ride is tagged and belongs to the account,
        None otherwise.
    """
    ride_result = await db.execute(
        select(Ride).where(
            Ride.id == ride_id,
            Ride.corporate_account_id == account_id,
        )
    )
    ride = ride_result.scalar_one_or_none()
    if ride is None or ride.trip_purpose_id is None:
        return None

    return await get_purpose(db, account_id, ride.trip_purpose_id)
