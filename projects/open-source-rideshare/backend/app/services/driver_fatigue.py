"""Service logic for driver fatigue monitoring.

Business rules
--------------
- Rolling 24h window: only events with recorded_at >= (now - 24h) count.
- Active hours are computed by pairing RIDE_STARTED / RIDE_ENDED events
  chronologically.  An unpaired RIDE_STARTED (driver is currently on a ride)
  contributes hours up to now.
- Status thresholds:
    < 8h  → NORMAL
    8–10h → WARNING  (can still accept rides; warned in response)
    ≥ 10h → LIMIT_REACHED (blocked from new rides)
- Rest requirement: 6 consecutive hours with no active ride before fatigue
  resets.  A driver at LIMIT_REACHED who has been idle ≥ 6h since their last
  RIDE_ENDED event is back to NORMAL.
- Admin reset: clears all in-memory log entries for that driver, allowing
  manual override (e.g. after data loss or verified rest period).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.schemas.driver_fatigue import FatigueAlert, FatigueStatus, FatigueStatusLevel

# ---------------------------------------------------------------------------
# In-memory store (same pattern as other services in this project)
# ---------------------------------------------------------------------------

# driver_id -> list of event dicts:
#   { "ride_id": int, "event_type": "RIDE_STARTED"|"RIDE_ENDED", "recorded_at": datetime }
_fatigue_logs: dict[int, list[dict]] = {}

# driver_id -> driver name (populated when log_ride_event is called)
_driver_names: dict[int, str] = {}

_WINDOW_HOURS = 24
_WARNING_THRESHOLD = 8.0
_LIMIT_THRESHOLD = 10.0
_REST_REQUIRED_HOURS = 6.0


def _reset_store() -> None:
    """Clear all in-memory state.  Used in tests."""
    _fatigue_logs.clear()
    _driver_names.clear()


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def _window_start() -> datetime:
    return _now() - timedelta(hours=_WINDOW_HOURS)


def _events_in_window(driver_id: int) -> list[dict]:
    """Return events for the driver within the rolling 24h window, oldest first."""
    cutoff = _window_start()
    events = _fatigue_logs.get(driver_id, [])
    return sorted(
        [e for e in events if e["recorded_at"] >= cutoff],
        key=lambda e: e["recorded_at"],
    )


def _compute_active_hours(events: list[dict]) -> float:
    """Sum active driving durations by pairing RIDE_STARTED/RIDE_ENDED per ride_id.

    Each ride_id is paired independently so concurrent or back-to-back events
    from different rides are handled correctly.  An unpaired RIDE_STARTED
    (driver is currently mid-ride) is counted up to now.
    """
    now = _now()
    total_seconds = 0.0

    # Group events by ride_id and compute per-ride duration
    starts: dict[int, datetime] = {}
    ended_rides: set[int] = set()

    for event in events:
        ride_id = event["ride_id"]
        if event["event_type"] == "RIDE_STARTED":
            if ride_id not in starts:
                starts[ride_id] = event["recorded_at"]
        elif event["event_type"] == "RIDE_ENDED":
            if ride_id in starts and ride_id not in ended_rides:
                total_seconds += (event["recorded_at"] - starts[ride_id]).total_seconds()
                ended_rides.add(ride_id)

    # Any ride that was started but not yet ended — count up to now
    for ride_id, start_time in starts.items():
        if ride_id not in ended_rides:
            total_seconds += (now - start_time).total_seconds()

    return total_seconds / 3600.0


def _last_ride_ended_at(driver_id: int) -> Optional[datetime]:
    """Return the most recent RIDE_ENDED timestamp for this driver (across all history)."""
    events = _fatigue_logs.get(driver_id, [])
    ended = [e["recorded_at"] for e in events if e["event_type"] == "RIDE_ENDED"]
    return max(ended) if ended else None


def _has_rested(driver_id: int) -> bool:
    """True if the driver has had ≥ REST_REQUIRED_HOURS with no active rides."""
    last_ended = _last_ride_ended_at(driver_id)
    if last_ended is None:
        return True  # No rides ever → trivially rested
    idle_hours = (_now() - last_ended).total_seconds() / 3600.0
    # Also check there is no pending (unended) RIDE_STARTED after last_ended
    events = _fatigue_logs.get(driver_id, [])
    pending = any(
        e["event_type"] == "RIDE_STARTED" and e["recorded_at"] > last_ended
        for e in events
    )
    if pending:
        return False
    return idle_hours >= _REST_REQUIRED_HOURS


def _rest_hours_still_needed(driver_id: int) -> Optional[float]:
    """Hours of rest still required.  Returns None if not at LIMIT_REACHED."""
    last_ended = _last_ride_ended_at(driver_id)
    if last_ended is None:
        return None
    elapsed = (_now() - last_ended).total_seconds() / 3600.0
    remaining = _REST_REQUIRED_HOURS - elapsed
    if remaining <= 0:
        return None
    return round(remaining, 1)


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


def log_ride_event(
    driver_id: int,
    ride_id: int,
    event_type: str,
    driver_name: str = "Unknown Driver",
    db=None,  # reserved for DB persistence in production
) -> dict:
    """Record a fatigue event for a driver.

    Parameters
    ----------
    driver_id:   User ID of the driver.
    ride_id:     Ride being started or ended.
    event_type:  "RIDE_STARTED" or "RIDE_ENDED".
    driver_name: Display name — stored for admin alerts.
    db:          SQLAlchemy session (reserved; currently only in-memory).

    Returns the recorded event dict.
    """
    if event_type not in ("RIDE_STARTED", "RIDE_ENDED"):
        raise ValueError(f"Unknown event_type: {event_type!r}")

    event = {
        "ride_id": ride_id,
        "event_type": event_type,
        "recorded_at": _now(),
    }
    _fatigue_logs.setdefault(driver_id, []).append(event)
    _driver_names[driver_id] = driver_name
    return event


def compute_fatigue_status(driver_id: int, db=None) -> FatigueStatus:
    """Calculate and return the current fatigue status for a driver.

    Parameters
    ----------
    driver_id: User ID of the driver.
    db:        SQLAlchemy session (reserved; currently only in-memory).
    """
    # If the driver has rested sufficiently the window effectively resets
    if _has_rested(driver_id):
        events_in_window = _events_in_window(driver_id)
        active_hours = _compute_active_hours(events_in_window)
        # After rest, hours from before the rest still count in the 24h window
        # but the status is reset to NORMAL if they've rested ≥ 6h
        # Recompute after determining rest clears the LIMIT state
        # (Per business rules: "fatigue resets to NORMAL" after 6h rest)
        # We still show actual hours but status is NORMAL
        rides_today = len(events_in_window)
        return FatigueStatus(
            driver_id=driver_id,
            status=FatigueStatusLevel.NORMAL,
            active_hours_last_24h=round(active_hours, 1),
            rides_today=rides_today,
            rest_hours_needed=None,
            message="Active hours are within safe limits.",
        )

    events_in_window = _events_in_window(driver_id)
    active_hours = _compute_active_hours(events_in_window)
    rides_today = len(events_in_window)
    hours_display = round(active_hours, 1)

    if active_hours >= _LIMIT_THRESHOLD:
        rest_needed = _rest_hours_still_needed(driver_id)
        return FatigueStatus(
            driver_id=driver_id,
            status=FatigueStatusLevel.LIMIT_REACHED,
            active_hours_last_24h=hours_display,
            rides_today=rides_today,
            rest_hours_needed=rest_needed,
            message=(
                f"You have reached the maximum active driving limit of "
                f"{_LIMIT_THRESHOLD:.0f} hours. You must rest for "
                f"{_REST_REQUIRED_HOURS:.0f} consecutive hours before accepting new rides."
            ),
        )

    if active_hours >= _WARNING_THRESHOLD:
        return FatigueStatus(
            driver_id=driver_id,
            status=FatigueStatusLevel.WARNING,
            active_hours_last_24h=hours_display,
            rides_today=rides_today,
            rest_hours_needed=None,
            message=(
                f"You have been active for {hours_display} hours. "
                f"Consider taking a break — you will be blocked from new rides at "
                f"{_LIMIT_THRESHOLD:.0f} hours."
            ),
        )

    return FatigueStatus(
        driver_id=driver_id,
        status=FatigueStatusLevel.NORMAL,
        active_hours_last_24h=hours_display,
        rides_today=rides_today,
        rest_hours_needed=None,
        message="Active hours are within safe limits.",
    )


def get_all_warnings(db=None) -> list[FatigueAlert]:
    """Return fatigue alerts for all drivers currently at WARNING or LIMIT_REACHED.

    Parameters
    ----------
    db: SQLAlchemy session (reserved; currently only in-memory).
    """
    alerts: list[FatigueAlert] = []
    for driver_id in list(_fatigue_logs.keys()):
        status = compute_fatigue_status(driver_id)
        if status.status in (FatigueStatusLevel.WARNING, FatigueStatusLevel.LIMIT_REACHED):
            alerts.append(
                FatigueAlert(
                    driver_id=driver_id,
                    driver_name=_driver_names.get(driver_id, "Unknown Driver"),
                    status=status.status,
                    active_hours_last_24h=status.active_hours_last_24h,
                    last_ride_ended_at=_last_ride_ended_at(driver_id),
                )
            )
    return alerts


def reset_driver_fatigue(driver_id: int, db=None) -> None:
    """Admin-only: clear all fatigue log entries for a driver.

    This is a manual override for cases such as verified rest period or
    data loss on first ride of the day.

    Parameters
    ----------
    driver_id: User ID of the driver to reset.
    db:        SQLAlchemy session (reserved; currently only in-memory).
    """
    _fatigue_logs.pop(driver_id, None)
