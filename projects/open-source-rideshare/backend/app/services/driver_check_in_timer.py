"""Service logic for the driver safety check-in timer.

Business rules:
- A driver may have at most one ACTIVE timer at a time.  Starting a second
  timer while one is active raises ValueError.
- duration_minutes must be between 5 and 120 (enforced by schema; service
  re-validates for safety).
- Confirming a timer that is not ACTIVE raises LookupError.
- Cancelling a timer that is not ACTIVE raises LookupError.
- get_active_timer returns None if no ACTIVE timer exists for the driver.
- expire_if_due marks an ACTIVE timer as EXPIRED (and sets
  expired_notified_at) when its expires_at is in the past.  In production
  a background task would call this; here it is triggered lazily by GET.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# In-memory store (same pattern as rider check-in timer)
# ---------------------------------------------------------------------------

_next_id: int = 1
_timers: dict[int, dict] = {}  # timer_id -> record


def _reset_store() -> None:
    global _next_id
    _next_id = 1
    _timers.clear()


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _minutes_remaining(record: dict) -> Optional[float]:
    if record["status"] != "active":
        return None
    delta = (record["expires_at"] - _now()).total_seconds()
    return max(0.0, round(delta / 60, 2))


def _enrich(record: dict) -> dict:
    """Return record with minutes_remaining computed."""
    return {**record, "minutes_remaining": _minutes_remaining(record)}


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


def start_timer(driver_id: int, duration_minutes: int, notes: Optional[str] = None) -> dict:
    """Start a new check-in timer for the driver.

    Raises:
        ValueError: if the driver already has an ACTIVE timer, or if
                    duration_minutes is outside the allowed range [5, 120].
    """
    global _next_id

    if not (5 <= duration_minutes <= 120):
        raise ValueError("duration_minutes must be between 5 and 120")

    for rec in _timers.values():
        if rec["driver_id"] == driver_id and rec["status"] == "active":
            raise ValueError(
                "You already have an active check-in timer.  "
                "Confirm, cancel, or wait for it to expire before starting a new one."
            )

    now = _now()
    record: dict = {
        "id": _next_id,
        "driver_id": driver_id,
        "duration_minutes": duration_minutes,
        "status": "active",
        "notes": notes,
        "started_at": now,
        "expires_at": now + timedelta(minutes=duration_minutes),
        "confirmed_at": None,
        "cancelled_at": None,
        "expired_notified_at": None,
    }
    _timers[_next_id] = record
    _next_id += 1
    return _enrich(record)


def get_active_timer(driver_id: int) -> Optional[dict]:
    """Return the ACTIVE timer for the driver (lazily expiring it if due), or None."""
    for rec in _timers.values():
        if rec["driver_id"] == driver_id and rec["status"] == "active":
            _maybe_expire(rec)
            if rec["status"] == "active":
                return _enrich(rec)
    return None


def get_timer_by_id(driver_id: int, timer_id: int) -> Optional[dict]:
    """Return a specific timer by ID, 404-safe (None if not found / wrong owner)."""
    rec = _timers.get(timer_id)
    if rec is None or rec["driver_id"] != driver_id:
        return None
    return _enrich(rec)


def confirm_timer(driver_id: int) -> dict:
    """Confirm the driver is safe — transitions ACTIVE → CONFIRMED.

    Raises:
        LookupError: if no ACTIVE timer exists for this driver.
    """
    for rec in _timers.values():
        if rec["driver_id"] == driver_id and rec["status"] == "active":
            _maybe_expire(rec)
            if rec["status"] != "active":
                raise LookupError("No active check-in timer found.")
            rec["status"] = "confirmed"
            rec["confirmed_at"] = _now()
            return _enrich(rec)
    raise LookupError("No active check-in timer found.")


def cancel_timer(driver_id: int) -> dict:
    """Cancel the driver's active timer — transitions ACTIVE → CANCELLED.

    Raises:
        LookupError: if no ACTIVE timer exists for this driver.
    """
    for rec in _timers.values():
        if rec["driver_id"] == driver_id and rec["status"] == "active":
            rec["status"] = "cancelled"
            rec["cancelled_at"] = _now()
            return _enrich(rec)
    raise LookupError("No active check-in timer found.")


def expire_if_due(driver_id: int) -> Optional[dict]:
    """Explicitly expire any overdue ACTIVE timer for the driver.

    Returns the expired record (with expired_notified_at set) or None.
    In production a background task would call _notify_emergency_contacts here.
    """
    for rec in _timers.values():
        if rec["driver_id"] == driver_id and rec["status"] == "active":
            if _maybe_expire(rec):
                return _enrich(rec)
    return None


def _maybe_expire(rec: dict) -> bool:
    """If the timer's expires_at is in the past, mark it EXPIRED and return True."""
    if rec["status"] != "active":
        return False
    if _now() >= rec["expires_at"]:
        rec["status"] = "expired"
        rec["expired_notified_at"] = _now()
        # Production: fire-and-forget notification to emergency contacts here.
        return True
    return False


def list_timers(driver_id: int, skip: int = 0, limit: int = 20) -> list[dict]:
    """Return all timers for the driver (newest first), paginated."""
    results = [
        _enrich(rec) for rec in _timers.values() if rec["driver_id"] == driver_id
    ]
    results.sort(key=lambda r: r["started_at"], reverse=True)
    return results[skip : skip + limit]
