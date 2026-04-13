"""Background dispatch scheduler for scheduled rides with retry logic.

Runs as an asyncio task during the application lifecycle. Every
`dispatch_check_interval_seconds` it:
1. Queries for SCHEDULED rides within the dispatch window → transitions to REQUESTED
2. Retries matching for REQUESTED rides with no driver (exponential backoff, max retries)

Flow per ride (initial dispatch):
1. Query rides with status=SCHEDULED and scheduled_for within dispatch window
2. Update status to REQUESTED, set requested_at
3. Trigger matching (find drivers, send offers)
4. Notify rider via WebSocket that their ride is now active

Flow per ride (retry):
1. Query REQUESTED rides with driver_id IS NULL and retry_count < max_retries
2. Check backoff interval elapsed since last_retry_at
3. Re-attempt matching
4. Increment retry count, update last_retry_at
5. If max retries exhausted, notify rider matching_failed
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import settings
from app.models.ride import Ride, RideStatus
from app.services.scheduling import is_ready_for_dispatch

logger = logging.getLogger(__name__)

_scheduler_task: asyncio.Task | None = None


async def dispatch_due_rides(*, now: datetime | None = None) -> int:
    """Find and dispatch all SCHEDULED rides that are within the dispatch window.

    Returns the number of rides dispatched.
    """
    from app.api.websocket import notify_ride_status, send_ride_offer
    from app.db.database import async_session
    from app.services.matching import get_matching_engine

    if now is None:
        now = datetime.now(timezone.utc)

    dispatched = 0

    async with async_session() as db:
        result = await db.execute(
            select(Ride).where(
                Ride.status == RideStatus.SCHEDULED,
                Ride.scheduled_for.isnot(None),
            )
        )
        rides = result.scalars().all()

        for ride in rides:
            if not is_ready_for_dispatch(ride.scheduled_for, now=now):
                continue

            # Transition to REQUESTED
            ride.status = RideStatus.REQUESTED
            ride.requested_at = now
            await db.commit()
            await db.refresh(ride)
            dispatched += 1

            logger.info(
                "Dispatched scheduled ride %d (was scheduled for %s)",
                ride.id,
                ride.scheduled_for,
            )

            # Notify rider that their scheduled ride is now active
            await notify_ride_status(ride.rider_id, ride.id, "dispatched")

            # Trigger matching
            try:
                engine = await get_matching_engine()
                candidates = await engine.find_candidates(
                    ride.pickup_location, ride.pickup_location, db,
                )
                if not candidates:
                    await notify_ride_status(ride.rider_id, ride.id, "no_drivers")
                    continue

                matched = await engine.match_ride(ride, 0, 0, db)
                if not matched:
                    await notify_ride_status(ride.rider_id, ride.id, "no_drivers")
                    continue

                await send_ride_offer(
                    matched.user_id,
                    ride.id,
                    ride.pickup_address,
                    ride.dropoff_address,
                    ride.estimated_fare,
                    matched.distance_km,
                )

                ride.driver_id = matched.user_id
                ride.status = RideStatus.MATCHED
                ride.matched_at = datetime.now(timezone.utc)
                await db.commit()

                await engine.set_driver_busy(matched.user_id)
                await notify_ride_status(
                    ride.rider_id,
                    ride.id,
                    "matched",
                    driver_distance_km=round(matched.distance_km, 2),
                )
            except Exception:
                logger.exception(
                    "Failed to match dispatched ride %d — ride remains REQUESTED",
                    ride.id,
                )

    return dispatched


def _retry_delay(retry_count: int) -> float:
    """Calculate backoff delay in seconds for the given retry attempt."""
    base = settings.dispatch_retry_interval_seconds
    backoff = settings.dispatch_retry_backoff
    return base * (backoff ** retry_count)


async def retry_unmatched_rides(*, now: datetime | None = None) -> int:
    """Retry matching for REQUESTED rides that have no driver assigned.

    Uses exponential backoff based on retry count. After max retries,
    notifies the rider that matching has failed.

    Returns the number of rides retried this cycle.
    """
    from app.api.websocket import notify_ride_status, send_ride_offer
    from app.db.database import async_session
    from app.services.matching import get_matching_engine

    if now is None:
        now = datetime.now(timezone.utc)

    retried = 0
    max_retries = settings.dispatch_max_retries

    async with async_session() as db:
        result = await db.execute(
            select(Ride).where(
                Ride.status == RideStatus.REQUESTED,
                Ride.driver_id.is_(None),
            )
        )
        rides = result.scalars().all()

        for ride in rides:
            # Check if max retries exhausted
            if ride.dispatch_retry_count >= max_retries:
                ride.status = RideStatus.CANCELLED
                ride.cancelled_at = now
                ride.cancellation_reason = "No drivers available after maximum retry attempts"
                await db.commit()
                await notify_ride_status(ride.rider_id, ride.id, "matching_failed")
                logger.info(
                    "Ride %d cancelled after %d retries — no drivers found",
                    ride.id,
                    ride.dispatch_retry_count,
                )
                continue

            # Check backoff interval — is it time for the next retry?
            delay = _retry_delay(ride.dispatch_retry_count)
            check_time = ride.last_retry_at or ride.requested_at
            if check_time and (now - check_time).total_seconds() < delay:
                continue

            # Attempt matching
            retried += 1
            ride.dispatch_retry_count += 1
            ride.last_retry_at = now
            await db.commit()

            logger.info(
                "Retry %d/%d for ride %d",
                ride.dispatch_retry_count,
                max_retries,
                ride.id,
            )

            try:
                engine = await get_matching_engine()
                candidates = await engine.find_candidates(
                    ride.pickup_location, ride.pickup_location, db,
                )
                if not candidates:
                    await notify_ride_status(
                        ride.rider_id, ride.id, "retry_no_drivers",
                        retry=ride.dispatch_retry_count,
                        max_retries=max_retries,
                    )
                    continue

                matched = await engine.match_ride(ride, 0, 0, db)
                if not matched:
                    await notify_ride_status(
                        ride.rider_id, ride.id, "retry_no_drivers",
                        retry=ride.dispatch_retry_count,
                        max_retries=max_retries,
                    )
                    continue

                # Guard against race condition: rider may have cancelled while
                # we were matching. Re-check status before committing the match.
                if ride.status != RideStatus.REQUESTED:
                    logger.info(
                        "Ride %d status changed to %s during retry match — skipping",
                        ride.id,
                        ride.status.value,
                    )
                    continue

                await send_ride_offer(
                    matched.user_id,
                    ride.id,
                    ride.pickup_address,
                    ride.dropoff_address,
                    ride.estimated_fare,
                    matched.distance_km,
                )

                ride.driver_id = matched.user_id
                ride.status = RideStatus.MATCHED
                ride.matched_at = now
                await db.commit()

                await engine.set_driver_busy(matched.user_id)
                await notify_ride_status(
                    ride.rider_id,
                    ride.id,
                    "matched",
                    driver_distance_km=round(matched.distance_km, 2),
                )

                logger.info(
                    "Retry matched ride %d to driver user_id=%d on attempt %d",
                    ride.id,
                    matched.user_id,
                    ride.dispatch_retry_count,
                )
            except Exception:
                logger.exception(
                    "Retry matching failed for ride %d (attempt %d) — will retry later",
                    ride.id,
                    ride.dispatch_retry_count,
                )

    return retried


async def generate_recurring_rides() -> int:
    """Generate scheduled rides from active recurring ride templates.

    Returns the number of rides generated.
    """
    from app.db.database import async_session
    from app.services.recurring_rides import generate_rides_from_recurring

    async with async_session() as db:
        try:
            return await generate_rides_from_recurring(db)
        except Exception:
            logger.exception("Recurring ride generation failed")
            return 0


async def send_scheduled_ride_reminders(*, now: datetime | None = None) -> int:
    """Send push + SMS reminders for upcoming scheduled rides.

    Two reminder windows:
    - T-60min: ride is 10–65 minutes away and no 1-hour reminder sent yet.
      (Upper bound 65 keeps a 5-minute grace above the nominal 60-minute mark.)
    - T-15min: ride is 0–20 minutes away and no 15-minute reminder sent yet.
      (Upper bound 20 keeps a 5-minute grace above the nominal 15-minute mark.)

    Reminders are idempotent — each field is set once and the row is never
    re-queried for that reminder type.

    Returns the number of reminders sent.
    """
    from app.db.database import async_session
    from app.models.user import User
    from app.services.notifications import NotificationType, send_ride_notification

    if now is None:
        now = datetime.now(timezone.utc)

    sent = 0

    async with async_session() as db:
        result = await db.execute(
            select(Ride).where(
                Ride.status == RideStatus.SCHEDULED,
                Ride.scheduled_for.isnot(None),
            )
        )
        rides = result.scalars().all()

        for ride in rides:
            scheduled_for = ride.scheduled_for
            if scheduled_for.tzinfo is None:
                scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)

            minutes_until = (scheduled_for - now).total_seconds() / 60

            # T-60min reminder (> 20 min away so it doesn't overlap with 15-min window)
            if 20 < minutes_until <= 65 and ride.reminder_1hr_sent_at is None:
                user_result = await db.execute(select(User).where(User.id == ride.rider_id))
                rider = user_result.scalar_one_or_none()
                phone = rider.phone if rider else None

                pickup_time = scheduled_for.strftime("%-I:%M %p")
                try:
                    await send_ride_notification(
                        user_id=ride.rider_id,
                        type=NotificationType.RIDE_REMINDER,
                        ride_id=ride.id,
                        db=db,
                        phone=phone,
                        pickup_time=pickup_time,
                        pickup_address=ride.pickup_address,
                    )
                except Exception:
                    logger.exception("Failed to send 1hr reminder for ride %d", ride.id)
                else:
                    ride.reminder_1hr_sent_at = now
                    await db.commit()
                    sent += 1
                    logger.info("Sent 1hr reminder for ride %d (%.0f min away)", ride.id, minutes_until)

            # T-15min reminder
            elif 0 <= minutes_until <= 20 and ride.reminder_15min_sent_at is None:
                user_result = await db.execute(select(User).where(User.id == ride.rider_id))
                rider = user_result.scalar_one_or_none()
                phone = rider.phone if rider else None

                pickup_time = scheduled_for.strftime("%-I:%M %p")
                try:
                    await send_ride_notification(
                        user_id=ride.rider_id,
                        type=NotificationType.RIDE_REMINDER,
                        ride_id=ride.id,
                        db=db,
                        phone=phone,
                        pickup_time=pickup_time,
                        pickup_address=ride.pickup_address,
                    )
                except Exception:
                    logger.exception("Failed to send 15min reminder for ride %d", ride.id)
                else:
                    ride.reminder_15min_sent_at = now
                    await db.commit()
                    sent += 1
                    logger.info(
                        "Sent 15min reminder for ride %d (%.0f min away)", ride.id, minutes_until
                    )

    return sent


async def _scheduler_loop() -> None:
    """Run the dispatch check on a fixed interval until cancelled."""
    interval = settings.dispatch_check_interval_seconds
    logger.info("Dispatch scheduler started (interval=%ds)", interval)

    while True:
        # Generate rides from recurring templates first
        try:
            gen_count = await generate_recurring_rides()
            if gen_count:
                logger.info("Generated %d ride(s) from recurring templates", gen_count)
        except Exception:
            logger.exception("Recurring ride generation cycle failed")

        try:
            reminded = await send_scheduled_ride_reminders()
            if reminded:
                logger.info("Reminder cycle complete: %d reminder(s) sent", reminded)
        except Exception:
            logger.exception("Reminder cycle failed")

        try:
            count = await dispatch_due_rides()
            if count:
                logger.info("Dispatch cycle complete: %d ride(s) dispatched", count)
        except Exception:
            logger.exception("Dispatch scheduler cycle failed")

        try:
            retried = await retry_unmatched_rides()
            if retried:
                logger.info("Retry cycle complete: %d ride(s) retried", retried)
        except Exception:
            logger.exception("Retry cycle failed")

        await asyncio.sleep(interval)


def start_scheduler() -> asyncio.Task:
    """Start the background dispatch scheduler. Call from app startup."""
    global _scheduler_task
    if _scheduler_task is not None and not _scheduler_task.done():
        logger.warning("Dispatch scheduler already running")
        return _scheduler_task

    _scheduler_task = asyncio.create_task(_scheduler_loop(), name="dispatch_scheduler")
    return _scheduler_task


async def stop_scheduler() -> None:
    """Stop the background dispatch scheduler. Call from app shutdown."""
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        return

    _scheduler_task.cancel()
    try:
        await _scheduler_task
    except asyncio.CancelledError:
        pass
    _scheduler_task = None
    logger.info("Dispatch scheduler stopped")
