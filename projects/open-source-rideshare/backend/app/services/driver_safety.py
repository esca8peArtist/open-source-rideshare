"""Driver emergency safety service.

Implements panic button feature for drivers on the cooperative rideshare
platform.  Mirrors the rider panic system in rider_safety.py.

Panic Button:
    Drivers can trigger a panic alert during an active ride.  Alerts are
    visible to admins immediately, sorted oldest-first (most urgent first).
    Only one ACTIVE alert is permitted per ride.  Cancelling within 30
    seconds marks the alert FALSE_ALARM; after 30 seconds it becomes
    RESOLVED.

All storage uses the same in-memory dict pattern as the rest of this
codebase.  A production implementation would replace stores with async
SQLAlchemy queries.

Public API:
    trigger_driver_panic(db, driver_id, ride_id, rider_id, location_lat, location_lng) -> dict
    get_driver_panic_alert(db, driver_id, alert_id) -> dict | None
    cancel_driver_panic_alert(db, driver_id, alert_id) -> dict
    admin_list_active_driver_panic_alerts(db, skip, limit) -> tuple[int, list[dict]]
    admin_resolve_driver_panic_alert(db, alert_id, admin_id, resolution_notes) -> dict
    list_driver_panic_alerts(db, driver_id) -> list[dict]
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.driver_safety import DriverPanicAlertStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

_driver_panic_alerts: dict[str, dict] = {}

# Seconds within which a cancel is considered FALSE_ALARM
FALSE_ALARM_WINDOW_SECONDS = 30


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


def _reset_store() -> None:
    """Clear all in-memory state.  For use in tests only."""
    _driver_panic_alerts.clear()


# ---------------------------------------------------------------------------
# Panic alert operations
# ---------------------------------------------------------------------------


async def trigger_driver_panic(
    db: AsyncSession,
    driver_id: int,
    ride_id: int,
    rider_id: int,
    location_lat: Optional[float] = None,
    location_lng: Optional[float] = None,
) -> dict:
    """Trigger a panic alert for the given active ride.

    Only one ACTIVE panic alert is permitted per ride.  If an alert already
    exists for this ride, raises ValueError.

    Args:
        db:          Async database session (unused in this implementation).
        driver_id:   ID of the driver triggering the alert.
        ride_id:     ID of the active ride.
        rider_id:    ID of the rider on the active ride.
        location_lat: Driver's latitude at trigger time (optional).
        location_lng: Driver's longitude at trigger time (optional).

    Returns:
        The newly created panic alert as a dict.

    Raises:
        ValueError: If there is already an ACTIVE panic alert for this ride.
    """
    existing = [
        a for a in _driver_panic_alerts.values()
        if a["ride_id"] == ride_id and a["status"] == DriverPanicAlertStatus.ACTIVE
    ]
    if existing:
        raise ValueError(f"An active driver panic alert already exists for ride {ride_id}.")

    alert_id = _new_id()
    now = _utc_now()
    alert = {
        "id": alert_id,
        "ride_id": ride_id,
        "driver_id": driver_id,
        "rider_id": rider_id,
        "triggered_at": now,
        "location_lat": location_lat,
        "location_lng": location_lng,
        "status": DriverPanicAlertStatus.ACTIVE,
        "resolved_at": None,
        "resolved_by": None,
        "resolution_notes": None,
    }
    _driver_panic_alerts[alert_id] = alert
    logger.warning(
        "DRIVER PANIC ALERT triggered — driver=%s ride=%s alert=%s",
        driver_id, ride_id, alert_id,
    )
    return dict(alert)


async def get_driver_panic_alert(
    db: AsyncSession,
    driver_id: int,
    alert_id: str,
) -> Optional[dict]:
    """Retrieve a driver panic alert owned by the given driver.

    Returns None if the alert does not exist or belongs to a different driver.
    Callers should raise HTTP 404 in either case — do not leak existence.
    """
    alert = _driver_panic_alerts.get(alert_id)
    if alert is None or alert["driver_id"] != driver_id:
        return None
    return dict(alert)


async def cancel_driver_panic_alert(
    db: AsyncSession,
    driver_id: int,
    alert_id: str,
) -> dict:
    """Cancel a driver panic alert.

    If cancelled within FALSE_ALARM_WINDOW_SECONDS of trigger, the status
    is set to FALSE_ALARM; otherwise it is set to RESOLVED.

    Raises:
        PermissionError: If alert does not exist or belongs to another driver.
        ValueError:      If alert is not ACTIVE.
    """
    alert = _driver_panic_alerts.get(alert_id)
    if alert is None or alert["driver_id"] != driver_id:
        raise PermissionError(f"Driver panic alert {alert_id} not found.")

    if alert["status"] != DriverPanicAlertStatus.ACTIVE:
        raise ValueError(
            f"Cannot cancel alert in status '{alert['status'].value}'. "
            "Only ACTIVE alerts can be cancelled."
        )

    now = _utc_now()
    elapsed = (now - alert["triggered_at"]).total_seconds()
    new_status = (
        DriverPanicAlertStatus.FALSE_ALARM
        if elapsed <= FALSE_ALARM_WINDOW_SECONDS
        else DriverPanicAlertStatus.RESOLVED
    )
    alert["status"] = new_status
    alert["resolved_at"] = now
    logger.info(
        "Driver panic alert %s cancelled as %s by driver %s (%.1fs after trigger)",
        alert_id, new_status.value, driver_id, elapsed,
    )
    return dict(alert)


async def admin_list_active_driver_panic_alerts(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
) -> tuple[int, list[dict]]:
    """List all ACTIVE driver panic alerts, sorted oldest-first (most urgent).

    Returns:
        (total, items) — total ACTIVE count and the requested page.
    """
    active = [
        a for a in _driver_panic_alerts.values()
        if a["status"] == DriverPanicAlertStatus.ACTIVE
    ]
    active.sort(key=lambda a: a["triggered_at"])
    total = len(active)
    page = active[skip: skip + limit]
    return total, [dict(a) for a in page]


async def admin_resolve_driver_panic_alert(
    db: AsyncSession,
    alert_id: str,
    admin_id: int,
    resolution_notes: Optional[str] = None,
) -> dict:
    """Admin resolves a driver panic alert with optional notes.

    Raises:
        KeyError:   If the alert does not exist.
        ValueError: If the alert is not ACTIVE.
    """
    alert = _driver_panic_alerts.get(alert_id)
    if alert is None:
        raise KeyError(f"Driver panic alert {alert_id} not found.")

    if alert["status"] != DriverPanicAlertStatus.ACTIVE:
        raise ValueError(
            f"Alert is already in status '{alert['status'].value}'. "
            "Only ACTIVE alerts can be resolved."
        )

    now = _utc_now()
    alert["status"] = DriverPanicAlertStatus.RESOLVED
    alert["resolved_at"] = now
    alert["resolved_by"] = admin_id
    alert["resolution_notes"] = resolution_notes
    logger.info("Admin %s resolved driver panic alert %s", admin_id, alert_id)
    return dict(alert)


async def list_driver_panic_alerts(
    db: AsyncSession,
    driver_id: int,
) -> list[dict]:
    """Return all panic alerts for a driver across all statuses, newest-first.

    Used by safety incident history endpoints.
    """
    alerts = [a for a in _driver_panic_alerts.values() if a["driver_id"] == driver_id]
    alerts.sort(key=lambda a: a["triggered_at"], reverse=True)
    return [dict(a) for a in alerts]


async def admin_list_all_driver_panic_alerts(
    db: AsyncSession,
    period_start: Optional[datetime] = None,
) -> list[dict]:
    """Return all driver panic alerts across all drivers, optionally filtered by period.

    Args:
        db:           Async database session (unused — in-memory store).
        period_start: If provided, only alerts triggered at or after this time are returned.

    Returns:
        List of alert dicts (copies).
    """
    alerts = list(_driver_panic_alerts.values())
    if period_start is not None:
        alerts = [a for a in alerts if a["triggered_at"] >= period_start]
    return [dict(a) for a in alerts]
