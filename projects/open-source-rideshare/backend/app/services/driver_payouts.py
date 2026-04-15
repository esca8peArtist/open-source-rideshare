"""Service layer for the driver payout / disbursement feature.

Drivers earn fares minus a platform commission (15 % standard, or 0 % when on
a flat-fee subscription plan).  This service calculates pending earnings and
manages the full payout lifecycle: pending -> processing -> completed | failed.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_payout import DriverPayout, DriverPayoutMethod, DriverPayoutStatus
from app.models.ride import Ride, RideStatus
from app.schemas.driver_payout import PayoutStatsResponse
from app.services.driver_subscriptions import get_driver_commission_pct

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _decimal(value) -> Decimal:
    """Coerce a raw DB value (float/Decimal/None) to a rounded Decimal."""
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Earnings calculation
# ---------------------------------------------------------------------------


async def calculate_pending_earnings(
    db: AsyncSession,
    driver_id: int,
    period_start: date,
    period_end: date,
) -> dict:
    """Calculate unpaid earnings for a driver over a given period.

    Returns a dict with keys:
        gross_usd, platform_fee_usd, net_usd, ride_count, commission_pct
    """
    # Fetch completed rides in the period that are not already covered by a
    # completed or pending payout.  We exclude rides whose completed_at date
    # falls within the period of any existing non-failed payout for this driver.
    existing_payout_query = select(DriverPayout).where(
        DriverPayout.driver_id == driver_id,
        DriverPayout.status.in_([
            DriverPayoutStatus.pending,
            DriverPayoutStatus.processing,
            DriverPayoutStatus.completed,
        ]),
        DriverPayout.period_start <= period_end,
        DriverPayout.period_end >= period_start,
    )
    existing_result = await db.execute(existing_payout_query)
    existing_payouts = existing_result.scalars().all()

    # Build a set of (start, end) date ranges already covered
    covered_ranges: list[tuple[date, date]] = [
        (p.period_start, p.period_end) for p in existing_payouts
    ]

    # For simplicity: if any payout covers an overlapping range, rides in that
    # range are already "paid".  We query all completed rides and exclude ones
    # whose completed_at date falls within any covered payout period.
    ride_query = (
        select(
            func.coalesce(func.sum(Ride.actual_fare), 0).label("gross"),
            func.count(Ride.id).label("ride_count"),
        )
        .where(
            Ride.driver_id == driver_id,
            Ride.status == RideStatus.COMPLETED,
            Ride.actual_fare.is_not(None),
            func.date(Ride.completed_at) >= period_start,
            func.date(Ride.completed_at) <= period_end,
        )
    )
    ride_result = await db.execute(ride_query)
    row = ride_result.one()
    gross = _decimal(row.gross)
    ride_count = int(row.ride_count)

    # Subtract rides already covered by existing payouts (overlap check per ride)
    if covered_ranges:
        covered_ride_query = (
            select(
                func.coalesce(func.sum(Ride.actual_fare), 0).label("covered_gross"),
                func.count(Ride.id).label("covered_count"),
            )
            .where(
                Ride.driver_id == driver_id,
                Ride.status == RideStatus.COMPLETED,
                Ride.actual_fare.is_not(None),
                func.date(Ride.completed_at) >= period_start,
                func.date(Ride.completed_at) <= period_end,
            )
        )
        # Add overlapping range exclusions using OR clauses
        from sqlalchemy import or_
        overlap_clauses = [
            and_(
                func.date(Ride.completed_at) >= start,
                func.date(Ride.completed_at) <= end,
            )
            for start, end in covered_ranges
        ]
        covered_ride_query = covered_ride_query.where(or_(*overlap_clauses))
        covered_result = await db.execute(covered_ride_query)
        covered_row = covered_result.one()
        covered_gross = _decimal(covered_row.covered_gross)
        covered_count = int(covered_row.covered_count)
        gross = gross - covered_gross
        ride_count = ride_count - covered_count

    commission_pct = await get_driver_commission_pct(db, driver_id)
    platform_fee = (gross * Decimal(str(commission_pct)) / Decimal("100")).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )
    net = (gross - platform_fee).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    return {
        "gross_usd": gross,
        "platform_fee_usd": platform_fee,
        "net_usd": net,
        "ride_count": ride_count,
        "commission_pct": commission_pct,
    }


# ---------------------------------------------------------------------------
# Payout lifecycle
# ---------------------------------------------------------------------------


async def request_payout(
    db: AsyncSession,
    driver_id: int,
    period_start: date,
    period_end: date,
    method: DriverPayoutMethod = DriverPayoutMethod.stripe_transfer,
) -> DriverPayout:
    """Create a pending payout for a driver.

    Raises HTTPException 400 if:
    - Net earnings are zero or negative.
    - An overlapping pending/processing payout already exists.
    """
    # Check for overlapping pending/processing payout
    overlap_result = await db.execute(
        select(DriverPayout).where(
            DriverPayout.driver_id == driver_id,
            DriverPayout.status.in_([
                DriverPayoutStatus.pending,
                DriverPayoutStatus.processing,
            ]),
            DriverPayout.period_start <= period_end,
            DriverPayout.period_end >= period_start,
        )
    )
    if overlap_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=400,
            detail="An overlapping pending or processing payout already exists for this period.",
        )

    earnings = await calculate_pending_earnings(db, driver_id, period_start, period_end)

    if earnings["net_usd"] <= Decimal("0"):
        raise HTTPException(
            status_code=400,
            detail="No earnings to pay out for this period.",
        )

    payout = DriverPayout(
        driver_id=driver_id,
        amount_usd=earnings["gross_usd"],
        platform_fee_usd=earnings["platform_fee_usd"],
        net_payout_usd=earnings["net_usd"],
        status=DriverPayoutStatus.pending,
        method=method,
        period_start=period_start,
        period_end=period_end,
    )
    db.add(payout)
    await db.flush()
    await db.refresh(payout)

    logger.info(
        "Payout requested for driver %d: gross=$%.2f fee=$%.2f net=$%.2f (%s to %s)",
        driver_id,
        earnings["gross_usd"],
        earnings["platform_fee_usd"],
        earnings["net_usd"],
        period_start,
        period_end,
    )
    return payout


async def process_payout(
    db: AsyncSession,
    payout_id: int,
    admin_notes: str | None = None,
) -> DriverPayout:
    """Mark a payout as processing then completed.

    Raises HTTPException 404 if not found; 400 if not in pending status.
    """
    payout = await get_payout(db, payout_id)
    if payout.status != DriverPayoutStatus.pending:
        raise HTTPException(
            status_code=400,
            detail=f"Payout is not pending (current status: {payout.status.value}).",
        )

    payout.status = DriverPayoutStatus.processing
    if admin_notes:
        payout.notes = admin_notes
    await db.flush()

    payout.status = DriverPayoutStatus.completed
    payout.processed_at = _now()
    await db.flush()
    await db.refresh(payout)

    logger.info("Payout %d processed to completion.", payout_id)
    return payout


async def fail_payout(
    db: AsyncSession,
    payout_id: int,
    reason: str,
) -> DriverPayout:
    """Mark a payout as failed.

    Raises HTTPException 404 if not found; 400 if already completed or failed.
    """
    payout = await get_payout(db, payout_id)
    if payout.status in (DriverPayoutStatus.completed, DriverPayoutStatus.failed):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot fail a payout with status: {payout.status.value}.",
        )

    payout.status = DriverPayoutStatus.failed
    payout.failed_reason = reason
    await db.flush()
    await db.refresh(payout)

    logger.info("Payout %d marked failed: %s", payout_id, reason)
    return payout


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


async def get_payout(db: AsyncSession, payout_id: int) -> DriverPayout:
    """Return a single payout or raise HTTPException 404."""
    result = await db.execute(
        select(DriverPayout).where(DriverPayout.id == payout_id)
    )
    payout = result.scalar_one_or_none()
    if payout is None:
        raise HTTPException(status_code=404, detail="Payout not found.")
    return payout


async def get_driver_payouts(
    db: AsyncSession,
    driver_id: int,
    skip: int = 0,
    limit: int = 20,
) -> list[DriverPayout]:
    """Return paginated payout history for a driver, newest first."""
    result = await db.execute(
        select(DriverPayout)
        .where(DriverPayout.driver_id == driver_id)
        .order_by(DriverPayout.requested_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_all_payouts(
    db: AsyncSession,
    status_filter: DriverPayoutStatus | None = None,
    skip: int = 0,
    limit: int = 20,
) -> list[DriverPayout]:
    """Admin: return all payouts, optionally filtered by status, newest first."""
    query = (
        select(DriverPayout)
        .order_by(DriverPayout.requested_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if status_filter is not None:
        query = query.where(DriverPayout.status == status_filter)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_payout_stats(db: AsyncSession) -> PayoutStatsResponse:
    """Admin: aggregate payout statistics."""
    pending_result = await db.execute(
        select(
            func.count(DriverPayout.id).label("cnt"),
            func.coalesce(func.sum(DriverPayout.net_payout_usd), 0).label("total"),
        ).where(
            DriverPayout.status.in_([
                DriverPayoutStatus.pending,
                DriverPayoutStatus.processing,
            ])
        )
    )
    pending_row = pending_result.one()

    completed_result = await db.execute(
        select(
            func.count(DriverPayout.id).label("cnt"),
            func.coalesce(func.sum(DriverPayout.net_payout_usd), 0).label("total"),
        ).where(DriverPayout.status == DriverPayoutStatus.completed)
    )
    completed_row = completed_result.one()

    failed_result = await db.execute(
        select(func.count(DriverPayout.id)).where(
            DriverPayout.status == DriverPayoutStatus.failed
        )
    )
    failed_count = int(failed_result.scalar() or 0)

    # Average across all completed payouts
    total_completed_usd = _decimal(completed_row.total)
    completed_count = int(completed_row.cnt)
    avg_payout = (
        (total_completed_usd / Decimal(str(completed_count))).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
        if completed_count > 0
        else Decimal("0.00")
    )

    return PayoutStatsResponse(
        total_pending_usd=_decimal(pending_row.total),
        total_completed_usd=total_completed_usd,
        pending_count=int(pending_row.cnt),
        completed_count=completed_count,
        failed_count=failed_count,
        avg_payout_usd=avg_payout,
    )
