"""Driver accountability escalation service.

Implements a three-strike progressive warning system tied to
DriverPerformanceAlert events.  When an escalation-triggering alert fires
(high_no_show, low_score, high_cancellation), this service:

  1st offence  → DRIVER_PERFORMANCE_WARNING notification, level = warning
  2nd offence  → DRIVER_PERFORMANCE_FINAL_WARNING notification, level = final_warning
  3rd+ offence → auto-suspend driver + DRIVER_AUTO_SUSPENDED notification, level = suspended

The warning counter resets to 1 (not 0) when a new alert fires more than
RESET_WINDOW_DAYS days after the last warning — a long clean streak earns
a fresh start, but the new offence still counts.

Admins can manually reset a driver's escalation state via
``reset_escalation()`` after coaching or review.

Escalation-triggering alert types
----------------------------------
- high_no_show       — no-show rate > 10 %
- low_score          — composite performance score < 60
- high_cancellation  — cancellation rate > 20 %
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_escalation import RESET_WINDOW_DAYS, DriverEscalation

logger = logging.getLogger(__name__)

# Alert types that trigger the escalation pipeline
ESCALATION_TRIGGER_TYPES = frozenset(["high_no_show", "low_score", "high_cancellation"])

# Mapping of warning_count → escalation_level string
_LEVEL_BY_COUNT = {
    1: "warning",
    2: "final_warning",
}
# warning_count >= 3 → "suspended"
_AUTO_SUSPEND_THRESHOLD = 3


async def _get_or_create(db: AsyncSession, driver_id: int) -> DriverEscalation:
    """Fetch or create the escalation row for a driver."""
    result = await db.execute(
        select(DriverEscalation).where(DriverEscalation.driver_id == driver_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        record = DriverEscalation(driver_id=driver_id)
        db.add(record)
        await db.flush()
        await db.refresh(record)
    return record


async def check_and_escalate(
    driver_id: int,
    alert_type: str,
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Evaluate the alert and advance the escalation state if applicable.

    Returns a dict describing the action taken, or None if the alert type
    is not an escalation trigger.

    Side effects:
    - Updates DriverEscalation row
    - Sends push/SMS notification to the driver
    - Auto-suspends the driver on the 3rd+ offence (calls suspend_driver)
    """
    if alert_type not in ESCALATION_TRIGGER_TYPES:
        return None

    if now is None:
        now = datetime.now(timezone.utc)

    record = await _get_or_create(db, driver_id)

    # Determine effective warning count — reset streak if driver has been clean
    # for more than RESET_WINDOW_DAYS since the last warning
    if record.last_warning_at is not None:
        days_since_last = (now - record.last_warning_at).days
        if days_since_last > RESET_WINDOW_DAYS:
            # Fresh streak — but the new offence still counts as 1
            record.warning_count = 0
            logger.info(
                "Escalation streak reset for driver %d — %d days since last warning",
                driver_id,
                days_since_last,
            )

    record.warning_count += 1
    record.last_trigger_type = alert_type
    record.last_warning_at = now

    action: str
    if record.warning_count >= _AUTO_SUSPEND_THRESHOLD:
        record.escalation_level = "suspended"
        record.auto_suspended_at = now
        action = "auto_suspended"
        await _auto_suspend(driver_id, record.warning_count, db)
    else:
        record.escalation_level = _LEVEL_BY_COUNT.get(record.warning_count, "warning")
        action = record.escalation_level

    await db.commit()
    await db.refresh(record)

    logger.info(
        "Driver %d escalation: alert_type=%s count=%d level=%s action=%s",
        driver_id,
        alert_type,
        record.warning_count,
        record.escalation_level,
        action,
    )

    # Fire-and-forget notification to the driver
    await _notify_driver(driver_id, action, alert_type, record.warning_count, db)

    return {
        "driver_id": driver_id,
        "action": action,
        "warning_count": record.warning_count,
        "escalation_level": record.escalation_level,
        "alert_type": alert_type,
    }


async def _auto_suspend(driver_id: int, warning_count: int, db: AsyncSession) -> None:
    """Auto-suspend the driver's account via the onboarding service."""
    try:
        from sqlalchemy import select as sa_select
        from app.models.driver import DriverProfile
        from app.services.driver_onboarding import suspend_driver

        result = await db.execute(
            sa_select(DriverProfile).where(DriverProfile.user_id == driver_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            logger.warning(
                "Cannot auto-suspend driver %d — DriverProfile not found", driver_id
            )
            return

        reason = (
            f"Automatic suspension after {warning_count} performance escalation strikes. "
            "Contact support to appeal."
        )
        # Use system user ID 0 to mark this as an automated action
        await suspend_driver(
            driver_profile_id=profile.id,
            reason=reason,
            admin_user_id=0,
            db=db,
        )
        logger.info("Auto-suspended driver %d (profile %d)", driver_id, profile.id)
    except Exception:
        logger.exception(
            "Failed to auto-suspend driver %d — manual review required", driver_id
        )


async def _notify_driver(
    driver_id: int,
    action: str,
    alert_type: str,
    warning_count: int,
    db: AsyncSession,
) -> None:
    """Send the appropriate escalation notification to the driver."""
    try:
        from app.services.notification_events import (
            notify_driver_performance_warning,
            notify_driver_performance_final_warning,
            notify_driver_auto_suspended,
        )

        if action == "warning":
            await notify_driver_performance_warning(
                db,
                driver_id=driver_id,
                alert_type=alert_type,
                warning_count=warning_count,
            )
        elif action == "final_warning":
            await notify_driver_performance_final_warning(
                db,
                driver_id=driver_id,
                alert_type=alert_type,
                warning_count=warning_count,
            )
        elif action == "auto_suspended":
            await notify_driver_auto_suspended(
                db,
                driver_id=driver_id,
                alert_type=alert_type,
                warning_count=warning_count,
            )
    except Exception:
        logger.exception(
            "Failed to send escalation notification to driver %d (action=%s)",
            driver_id,
            action,
        )


async def get_escalation_status(
    db: AsyncSession,
    driver_id: int,
) -> DriverEscalation | None:
    """Return the escalation record for a driver, or None if no record exists."""
    result = await db.execute(
        select(DriverEscalation).where(DriverEscalation.driver_id == driver_id)
    )
    return result.scalar_one_or_none()


async def reset_escalation(
    db: AsyncSession,
    driver_id: int,
    admin_id: int,
    note: str | None = None,
    *,
    now: datetime | None = None,
) -> DriverEscalation:
    """Admin resets a driver's escalation state after coaching or review.

    Clears warning_count and level back to zero/none.  Does NOT
    automatically reinstate a suspended driver — use the onboarding
    activate endpoint for that.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    record = await _get_or_create(db, driver_id)
    record.warning_count = 0
    record.escalation_level = "none"
    record.last_trigger_type = None
    record.admin_reset_note = note
    record.reset_by = admin_id
    record.last_reset_at = now

    await db.commit()
    await db.refresh(record)

    logger.info(
        "Escalation reset for driver %d by admin %d — note: %s",
        driver_id,
        admin_id,
        note or "(none)",
    )
    return record
