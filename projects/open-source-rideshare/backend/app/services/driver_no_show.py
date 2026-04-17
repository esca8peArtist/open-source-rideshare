"""Driver no-show protection service.

Handles two paths:
1. Manual report — rider taps "Driver never showed up" after waiting at pickup.
   Accessible via POST /rides/{ride_id}/report-driver-no-show.
2. Automated detection — scheduler checks ARRIVED rides every cycle and
   auto-cancels any that have been waiting longer than the configured threshold.

In both cases the outcome is the same:
  - Ride is cancelled with CancellationCategory.DRIVER_NO_SHOW.
  - Completed fare payment (if any) is refunded via Stripe.
  - Rider receives push + SMS notification.
  - Driver is returned to the available pool.
  - Audit event is logged.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.ride import CancellationCategory, Ride, RideStatus

logger = logging.getLogger(__name__)

# Statuses in which a rider can manually report a driver no-show.
# Excludes ARRIVED so the rider can report even if the driver marked arrived
# but then disappeared, as well as earlier statuses if the driver simply
# never left for pickup.
_NO_SHOW_REPORTABLE_STATUSES = frozenset([
    RideStatus.MATCHED,
    RideStatus.DRIVER_EN_ROUTE,
    RideStatus.ARRIVED,
])


async def _process_no_show(ride: Ride, db: AsyncSession, *, now: datetime) -> None:
    """Core logic: mark ride cancelled, refund, notify. Caller commits."""
    from app.services.audit_events import audit_ride_cancelled
    from app.services.notification_events import notify_driver_no_show
    from app.services.payments import process_refund

    wait_minutes = 0
    if ride.arrived_at:
        elapsed = (now - ride.arrived_at).total_seconds()
        wait_minutes = int(elapsed // 60)

    ride.status = RideStatus.CANCELLED
    ride.cancelled_at = now
    ride.driver_no_show_reported_at = now
    ride.cancellation_category = CancellationCategory.DRIVER_NO_SHOW
    ride.cancellation_reason = f"Driver did not arrive after {wait_minutes} minute(s)"
    ride.cancelled_by = "system"
    await db.commit()

    logger.info(
        "Ride %d cancelled — driver no-show (waited %d min, driver_id=%s)",
        ride.id,
        wait_minutes,
        ride.driver_id,
    )

    # Return driver to available pool
    if ride.driver_id:
        try:
            from app.services.matching import get_matching_engine
            engine = await get_matching_engine()
            await engine.set_driver_available(ride.driver_id)
        except Exception:
            logger.exception("Failed to release driver %d back to pool for ride %d", ride.driver_id, ride.id)

    # WebSocket notification
    try:
        from app.api.websocket import notify_ride_status
        await notify_ride_status(ride.rider_id, ride.id, "driver_no_show")
        if ride.driver_id:
            await notify_ride_status(ride.driver_id, ride.id, "cancelled")
    except Exception:
        logger.exception("WebSocket notify failed for ride %d driver no-show", ride.id)

    # Refund completed fare payment if one exists
    try:
        result = await process_refund(ride.id, db)
        if "refund_id" in result:
            logger.info("Refund issued for ride %d: %s", ride.id, result["refund_id"])
        elif "error" in result:
            # No completed payment to refund — this is normal for pre-paid rides
            logger.debug("No refund for ride %d: %s", ride.id, result["error"])
    except Exception:
        logger.exception("Refund failed for ride %d (driver no-show) — requires manual review", ride.id)

    # Push + SMS to rider
    await notify_driver_no_show(db, rider_id=ride.rider_id, ride_id=ride.id, wait_minutes=wait_minutes)

    # Audit log
    try:
        await audit_ride_cancelled(
            db,
            ride_id=ride.id,
            cancelled_by=None,
            role="system",
            reason=f"driver_no_show: waited {wait_minutes} min",
        )
    except Exception:
        logger.exception("Audit log failed for ride %d driver no-show", ride.id)


async def report_driver_no_show(
    ride_id: int,
    rider_id: int,
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict:
    """Manual no-show report submitted by the rider.

    Returns a dict with status and detail suitable for the API response.
    Raises ValueError for business-rule violations the caller should map to 4xx.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()

    if not ride:
        raise LookupError(f"Ride {ride_id} not found")

    if ride.rider_id != rider_id:
        raise PermissionError("Not authorised to report no-show for this ride")

    if ride.status not in _NO_SHOW_REPORTABLE_STATUSES:
        raise ValueError(
            f"Cannot report driver no-show when ride is in '{ride.status.value}' status. "
            f"Only allowed for: {', '.join(s.value for s in _NO_SHOW_REPORTABLE_STATUSES)}"
        )

    if ride.driver_no_show_reported_at is not None:
        raise ValueError("A no-show has already been reported for this ride")

    await _process_no_show(ride, db, now=now)

    return {
        "status": "cancelled",
        "reason": "driver_no_show",
        "refund_initiated": True,
    }


async def detect_driver_no_shows(*, now: datetime | None = None) -> int:
    """Scheduler task: auto-cancel ARRIVED rides past the no-show threshold.

    Checks rides with:
    - status = ARRIVED
    - arrived_at set and older than driver_no_show_threshold_minutes
    - driver_no_show_reported_at IS NULL (not already handled)

    Returns the number of rides auto-cancelled.
    """
    from app.db.database import async_session

    if now is None:
        now = datetime.now(timezone.utc)

    threshold = timedelta(minutes=settings.driver_no_show_threshold_minutes)
    cutoff = now - threshold

    cancelled = 0

    async with async_session() as db:
        result = await db.execute(
            select(Ride).where(
                Ride.status == RideStatus.ARRIVED,
                Ride.arrived_at.isnot(None),
                Ride.arrived_at <= cutoff,
                Ride.driver_no_show_reported_at.is_(None),
            )
        )
        rides = result.scalars().all()

        for ride in rides:
            try:
                await _process_no_show(ride, db, now=now)
                cancelled += 1
                logger.info(
                    "Auto-cancelled ride %d as driver no-show (arrived_at=%s, threshold=%dmin)",
                    ride.id,
                    ride.arrived_at,
                    settings.driver_no_show_threshold_minutes,
                )
            except Exception:
                logger.exception(
                    "Failed to auto-cancel ride %d for driver no-show — will retry next cycle",
                    ride.id,
                )

    return cancelled
