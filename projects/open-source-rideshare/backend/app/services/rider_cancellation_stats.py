"""Rider cancellation statistics service.

Two public functions:
  - record_rider_cancellation  — called after a rider cancels; upserts the stats row
  - get_rider_cancel_stats     — returns the stats row for a rider (or None)

The update logic is intentionally simple (single upsert) to avoid any chance
of blocking the cancel endpoint.  Callers should use fire-and-forget:

    try:
        await record_rider_cancellation(db, ...)
    except Exception:
        logger.warning("Failed to update rider cancel stats", exc_info=True)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import CancellationCategory
from app.models.rider_cancellation_stats import RiderCancellationStats

logger = logging.getLogger(__name__)


async def record_rider_cancellation(
    db: AsyncSession,
    rider_id: int,
    had_fee: bool,
    in_grace_period: bool,
    category: CancellationCategory | None,
) -> RiderCancellationStats:
    """Upsert the cancellation stats row for *rider_id*.

    Creates the row on first cancel.  The ``total_rides_requested`` counter
    is NOT touched here — it is incremented via ``increment_ride_requested``
    when a ride is first created.

    Returns the updated stats row.
    """
    result = await db.execute(
        select(RiderCancellationStats).where(RiderCancellationStats.rider_id == rider_id)
    )
    stats = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if stats is None:
        stats = RiderCancellationStats(
            rider_id=rider_id,
            total_rides_requested=1,  # at least the current ride
            total_cancellations=1,
            cancellations_in_grace_period=1 if in_grace_period else 0,
            cancellations_with_fee=1 if had_fee else 0,
            cancellation_rate=1.0,  # 1/1; will improve with more rides
            last_cancel_at=now,
            last_cancel_category=category,
        )
        db.add(stats)
    else:
        stats.total_cancellations += 1
        if in_grace_period:
            stats.cancellations_in_grace_period += 1
        if had_fee:
            stats.cancellations_with_fee += 1
        if stats.total_rides_requested > 0:
            stats.cancellation_rate = round(stats.total_cancellations / stats.total_rides_requested, 4)
        stats.last_cancel_at = now
        stats.last_cancel_category = category

    await db.commit()
    await db.refresh(stats)
    return stats


async def increment_ride_requested(db: AsyncSession, rider_id: int) -> None:
    """Increment the total_rides_requested counter when a new ride is created.

    Safe to call fire-and-forget — any failure is logged but does not
    propagate to the caller.
    """
    result = await db.execute(
        select(RiderCancellationStats).where(RiderCancellationStats.rider_id == rider_id)
    )
    stats = result.scalar_one_or_none()

    if stats is None:
        stats = RiderCancellationStats(
            rider_id=rider_id,
            total_rides_requested=1,
        )
        db.add(stats)
    else:
        stats.total_rides_requested += 1
        if stats.total_rides_requested > 0:
            stats.cancellation_rate = round(stats.total_cancellations / stats.total_rides_requested, 4)

    await db.commit()


async def get_rider_cancel_stats(
    db: AsyncSession, rider_id: int
) -> RiderCancellationStats | None:
    """Return the stats row for *rider_id*, or None if no rides have been requested."""
    result = await db.execute(
        select(RiderCancellationStats).where(RiderCancellationStats.rider_id == rider_id)
    )
    return result.scalar_one_or_none()
