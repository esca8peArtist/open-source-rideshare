"""Service layer for Corporate Shuttle Pass Management.

Enterprise accounts define pass types (ride count, validity, price) and issue
passes to individual employees.  Employees redeem passes against shuttle
bookings; each redemption decrements rides_used and appends a usage record.

Public functions
----------------
create_pass_type        — create a new pass type (409-dup-name).
get_pass_type           — fetch one pass type (404 if missing).
list_pass_types         — list pass types for an account (is_active filter).
update_pass_type        — update a pass type (409-name-collision).
deactivate_pass_type    — soft-deactivate a pass type (409-if-inactive).
issue_pass              — issue a pass to a member (404-type; 409-type-inactive).
get_pass                — fetch one pass (404 if missing or wrong account).
list_member_passes      — list passes for a member (is_active filter).
redeem_pass             — record a ride redemption (409-no-rides/expired/inactive).
get_account_pass_summary — aggregate stats for a corporate account.
list_all_platform       — platform-admin cross-account listing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_shuttle_pass import (
    CorporateShuttlePass,
    CorporateShuttlePassType,
    CorporateShuttlePassUsage,
)
from app.schemas.corporate_shuttle_pass import (
    PassResponse,
    PassSummaryResponse,
    PassTypeResponse,
    PassUsageResponse,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_pass_type(row: CorporateShuttlePassType) -> PassTypeResponse:
    return PassTypeResponse.model_validate(row)


def _to_pass(row: CorporateShuttlePass) -> PassResponse:
    return PassResponse.from_orm_pass(row)


def _to_usage(row: CorporateShuttlePassUsage) -> PassUsageResponse:
    return PassUsageResponse.model_validate(row)


def _is_expired(row: CorporateShuttlePass) -> bool:
    """Return True if the pass has an expiry date that has passed."""
    if row.expires_at is None:
        return False
    return datetime.now(tz=timezone.utc) > row.expires_at


# ---------------------------------------------------------------------------
# Pass Type CRUD
# ---------------------------------------------------------------------------


async def create_pass_type(
    db: AsyncSession,
    account_id: int,
    name: str,
    ride_count: int,
    created_by_id: Optional[int] = None,
    description: Optional[str] = None,
    validity_days: Optional[int] = None,
    price_usd: Optional[Decimal] = None,
    notes: Optional[str] = None,
) -> PassTypeResponse:
    """Create a new shuttle pass type for an account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        name: Human-readable name (unique within the account).
        ride_count: Number of rides in the pass (≥ 1).
        created_by_id: User ID of the admin creating the type (nullable).
        description: Optional description.
        validity_days: Days from issue until expiry (None = no expiry).
        price_usd: Nominal price for accounting (nullable).
        notes: Optional notes.

    Returns:
        ``PassTypeResponse`` for the created type.

    Raises:
        HTTPException 409: A pass type with this name already exists for the
            account.
    """
    # Duplicate name guard
    dup_stmt = select(CorporateShuttlePassType).where(
        CorporateShuttlePassType.account_id == account_id,
        CorporateShuttlePassType.name == name,
    )
    if (await db.execute(dup_stmt)).scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A pass type named '{name}' already exists for this account.",
        )

    row = CorporateShuttlePassType(
        account_id=account_id,
        name=name,
        description=description,
        ride_count=ride_count,
        validity_days=validity_days,
        price_usd=price_usd,
        notes=notes,
        is_active=True,
        created_by_id=created_by_id,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return _to_pass_type(row)


async def get_pass_type(
    db: AsyncSession,
    type_id: uuid.UUID,
    account_id: int,
) -> PassTypeResponse:
    """Fetch a pass type by ID.

    Args:
        db: Async SQLAlchemy session.
        type_id: UUID of the pass type.
        account_id: Corporate account ID for ownership verification.

    Returns:
        ``PassTypeResponse``.

    Raises:
        HTTPException 404: Pass type not found or belongs to a different account.
    """
    stmt = select(CorporateShuttlePassType).where(
        CorporateShuttlePassType.id == type_id,
        CorporateShuttlePassType.account_id == account_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shuttle pass type not found.",
        )
    return _to_pass_type(row)


async def list_pass_types(
    db: AsyncSession,
    account_id: int,
    is_active: Optional[bool] = None,
) -> List[PassTypeResponse]:
    """List all pass types for an account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        is_active: Optional is_active filter (None = return all).

    Returns:
        List of ``PassTypeResponse`` ordered by name ascending.
    """
    stmt = select(CorporateShuttlePassType).where(
        CorporateShuttlePassType.account_id == account_id,
    )
    if is_active is not None:
        stmt = stmt.where(CorporateShuttlePassType.is_active == is_active)
    stmt = stmt.order_by(CorporateShuttlePassType.name)
    result = await db.execute(stmt)
    return [_to_pass_type(r) for r in result.scalars().all()]


async def update_pass_type(
    db: AsyncSession,
    type_id: uuid.UUID,
    account_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    ride_count: Optional[int] = None,
    validity_days: Optional[int] = None,
    price_usd: Optional[Decimal] = None,
    notes: Optional[str] = None,
) -> PassTypeResponse:
    """Update a shuttle pass type.

    Only provided (non-None) fields are updated.

    Args:
        db: Async SQLAlchemy session.
        type_id: UUID of the pass type.
        account_id: Corporate account ID.
        name: New name (409 if duplicate).
        description: New description.
        ride_count: New ride count (≥ 1).
        validity_days: New validity window (days).
        price_usd: New price.
        notes: New notes.

    Returns:
        Updated ``PassTypeResponse``.

    Raises:
        HTTPException 404: Pass type not found.
        HTTPException 409: New name collides with an existing type.
    """
    stmt = select(CorporateShuttlePassType).where(
        CorporateShuttlePassType.id == type_id,
        CorporateShuttlePassType.account_id == account_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shuttle pass type not found.",
        )

    if name is not None and name != row.name:
        dup_stmt = select(CorporateShuttlePassType).where(
            CorporateShuttlePassType.account_id == account_id,
            CorporateShuttlePassType.name == name,
            CorporateShuttlePassType.id != type_id,
        )
        if (await db.execute(dup_stmt)).scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A pass type named '{name}' already exists for this account.",
            )
        row.name = name

    if description is not None:
        row.description = description
    if ride_count is not None:
        row.ride_count = ride_count
    if validity_days is not None:
        row.validity_days = validity_days
    if price_usd is not None:
        row.price_usd = price_usd
    if notes is not None:
        row.notes = notes

    await db.flush()
    await db.refresh(row)
    return _to_pass_type(row)


async def deactivate_pass_type(
    db: AsyncSession,
    type_id: uuid.UUID,
    account_id: int,
) -> PassTypeResponse:
    """Soft-deactivate a shuttle pass type.

    Deactivated types can no longer be issued to new employees.

    Args:
        db: Async SQLAlchemy session.
        type_id: UUID of the pass type.
        account_id: Corporate account ID.

    Returns:
        Updated ``PassTypeResponse`` with is_active=False.

    Raises:
        HTTPException 404: Pass type not found.
        HTTPException 409: Pass type is already inactive.
    """
    stmt = select(CorporateShuttlePassType).where(
        CorporateShuttlePassType.id == type_id,
        CorporateShuttlePassType.account_id == account_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shuttle pass type not found.",
        )
    if not row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shuttle pass type is already inactive.",
        )

    row.is_active = False
    await db.flush()
    await db.refresh(row)
    return _to_pass_type(row)


# ---------------------------------------------------------------------------
# Pass issuance
# ---------------------------------------------------------------------------


async def issue_pass(
    db: AsyncSession,
    pass_type_id: uuid.UUID,
    account_id: int,
    member_id: int,
    issued_by_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> PassResponse:
    """Issue a shuttle pass to a member.

    The pass copies ``ride_count`` from the pass type at the time of issuance.
    ``expires_at`` is computed from ``validity_days`` (if set).

    Args:
        db: Async SQLAlchemy session.
        pass_type_id: UUID of the pass type to issue.
        account_id: Corporate account ID.
        member_id: User ID of the recipient.
        issued_by_id: User ID of the admin issuing the pass (nullable).
        notes: Optional notes for this pass instance.

    Returns:
        ``PassResponse`` for the newly issued pass.

    Raises:
        HTTPException 404: Pass type not found or belongs to a different account.
        HTTPException 409: Pass type is inactive.
    """
    # Load and validate the pass type
    type_stmt = select(CorporateShuttlePassType).where(
        CorporateShuttlePassType.id == pass_type_id,
        CorporateShuttlePassType.account_id == account_id,
    )
    pass_type = (await db.execute(type_stmt)).scalar_one_or_none()
    if pass_type is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shuttle pass type not found.",
        )
    if not pass_type.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot issue a pass from an inactive pass type.",
        )

    now = datetime.now(tz=timezone.utc)
    expires_at: Optional[datetime] = None
    if pass_type.validity_days is not None:
        expires_at = now + timedelta(days=pass_type.validity_days)

    row = CorporateShuttlePass(
        pass_type_id=pass_type_id,
        account_id=account_id,
        member_id=member_id,
        rides_total=pass_type.ride_count,
        rides_used=0,
        issued_at=now,
        expires_at=expires_at,
        is_active=True,
        issued_by_id=issued_by_id,
        notes=notes,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return _to_pass(row)


# ---------------------------------------------------------------------------
# Pass read operations
# ---------------------------------------------------------------------------


async def get_pass(
    db: AsyncSession,
    pass_id: uuid.UUID,
    account_id: int,
) -> PassResponse:
    """Fetch a single issued pass by ID.

    Args:
        db: Async SQLAlchemy session.
        pass_id: UUID of the pass.
        account_id: Corporate account ID for ownership verification.

    Returns:
        ``PassResponse``.

    Raises:
        HTTPException 404: Pass not found or belongs to a different account.
    """
    stmt = select(CorporateShuttlePass).where(
        CorporateShuttlePass.id == pass_id,
        CorporateShuttlePass.account_id == account_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shuttle pass not found.",
        )
    return _to_pass(row)


async def list_member_passes(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    is_active: Optional[bool] = None,
) -> List[PassResponse]:
    """List all passes issued to a member within an account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        member_id: User ID of the member.
        is_active: Optional is_active filter (None = all passes).

    Returns:
        List of ``PassResponse`` ordered by issued_at descending.
    """
    stmt = select(CorporateShuttlePass).where(
        CorporateShuttlePass.account_id == account_id,
        CorporateShuttlePass.member_id == member_id,
    )
    if is_active is not None:
        stmt = stmt.where(CorporateShuttlePass.is_active == is_active)
    stmt = stmt.order_by(CorporateShuttlePass.issued_at.desc())
    result = await db.execute(stmt)
    return [_to_pass(r) for r in result.scalars().all()]


# ---------------------------------------------------------------------------
# Pass redemption
# ---------------------------------------------------------------------------


async def redeem_pass(
    db: AsyncSession,
    pass_id: uuid.UUID,
    account_id: int,
    member_id: int,
    booking_id: Optional[uuid.UUID] = None,
) -> PassUsageResponse:
    """Record a ride redemption against a shuttle pass.

    Increments rides_used on the pass and appends a CorporateShuttlePassUsage
    record.

    Args:
        db: Async SQLAlchemy session.
        pass_id: UUID of the pass to redeem.
        account_id: Corporate account ID.
        member_id: User ID of the member redeeming (must match pass.member_id).
        booking_id: Optional UUID of the shuttle booking being paid for.

    Returns:
        ``PassUsageResponse`` for the created usage record.

    Raises:
        HTTPException 404: Pass not found or belongs to a different account.
        HTTPException 409: Pass is inactive.
        HTTPException 409: Pass is expired.
        HTTPException 409: Pass belongs to a different member.
        HTTPException 409: No rides remaining on this pass.
    """
    stmt = select(CorporateShuttlePass).where(
        CorporateShuttlePass.id == pass_id,
        CorporateShuttlePass.account_id == account_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shuttle pass not found.",
        )
    if not row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shuttle pass is not active.",
        )
    if row.member_id != member_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shuttle pass belongs to a different member.",
        )
    if _is_expired(row):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shuttle pass has expired.",
        )
    rides_remaining = row.rides_total - row.rides_used
    if rides_remaining <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No rides remaining on this shuttle pass.",
        )

    row.rides_used += 1
    new_remaining = row.rides_total - row.rides_used

    usage = CorporateShuttlePassUsage(
        pass_id=pass_id,
        account_id=account_id,
        member_id=member_id,
        booking_id=booking_id,
        redeemed_at=datetime.now(tz=timezone.utc),
        rides_remaining_after=new_remaining,
    )
    db.add(usage)
    await db.flush()
    await db.refresh(usage)
    return _to_usage(usage)


# ---------------------------------------------------------------------------
# Summary / analytics
# ---------------------------------------------------------------------------


async def get_account_pass_summary(
    db: AsyncSession,
    account_id: int,
) -> PassSummaryResponse:
    """Return aggregate shuttle pass statistics for a corporate account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.

    Returns:
        ``PassSummaryResponse``.
    """
    now = datetime.now(tz=timezone.utc)

    # Pass type counts
    type_total_stmt = select(func.count()).where(
        CorporateShuttlePassType.account_id == account_id
    )
    total_pass_types = (await db.execute(type_total_stmt)).scalar_one()

    type_active_stmt = select(func.count()).where(
        CorporateShuttlePassType.account_id == account_id,
        CorporateShuttlePassType.is_active == True,
    )
    active_pass_types = (await db.execute(type_active_stmt)).scalar_one()

    # Pass counts and ride totals
    passes_stmt = select(
        func.count().label("total"),
        func.sum(CorporateShuttlePass.rides_total).label("rides_total"),
        func.sum(CorporateShuttlePass.rides_used).label("rides_used"),
    ).where(CorporateShuttlePass.account_id == account_id)
    pass_agg = (await db.execute(passes_stmt)).one()
    total_passes_issued = pass_agg.total or 0
    total_rides_issued = int(pass_agg.rides_total or 0)
    total_rides_used = int(pass_agg.rides_used or 0)

    # Active passes
    active_passes_stmt = select(func.count()).where(
        CorporateShuttlePass.account_id == account_id,
        CorporateShuttlePass.is_active == True,
    )
    active_passes = (await db.execute(active_passes_stmt)).scalar_one()

    # Expired passes: expires_at is set and <= now
    expired_stmt = select(func.count()).where(
        CorporateShuttlePass.account_id == account_id,
        CorporateShuttlePass.expires_at != None,
        CorporateShuttlePass.expires_at <= now,
    )
    expired_passes = (await db.execute(expired_stmt)).scalar_one()

    return PassSummaryResponse(
        account_id=account_id,
        total_pass_types=total_pass_types,
        active_pass_types=active_pass_types,
        total_passes_issued=total_passes_issued,
        active_passes=active_passes,
        expired_passes=expired_passes,
        total_rides_issued=total_rides_issued,
        total_rides_used=total_rides_used,
        total_rides_remaining=total_rides_issued - total_rides_used,
    )


# ---------------------------------------------------------------------------
# Platform-admin
# ---------------------------------------------------------------------------


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
    is_active: Optional[bool] = None,
) -> List[PassResponse]:
    """Return all issued passes across all accounts (platform-admin).

    Args:
        db: Async SQLAlchemy session.
        account_id: Optional filter by corporate account ID.
        is_active: Optional is_active filter.

    Returns:
        List of ``PassResponse`` ordered by account_id then issued_at descending.
    """
    stmt = select(CorporateShuttlePass)
    if account_id is not None:
        stmt = stmt.where(CorporateShuttlePass.account_id == account_id)
    if is_active is not None:
        stmt = stmt.where(CorporateShuttlePass.is_active == is_active)
    stmt = stmt.order_by(
        CorporateShuttlePass.account_id,
        CorporateShuttlePass.issued_at.desc(),
    )
    result = await db.execute(stmt)
    return [_to_pass(r) for r in result.scalars().all()]
