"""Service logic for pre-ride boarding verification.

Business rules
--------------
- A boarding PIN can only be generated when the ride status is DRIVER_EN_ROUTE
  or ARRIVED.
- Only the assigned driver may generate (or re-request) a PIN for a ride.
- PIN is 4 digits, valid for 15 minutes.  Regenerating creates a fresh PIN
  and invalidates the previous one.
- Only the assigned rider may submit a boarding confirmation.
- Once confirmed, the record is immutable.
- If the rider reports a PIN mismatch (confirmed=False), a safety alert is
  stored alongside the record.
- One boarding verification record per ride (re-confirmation is not allowed).
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

_PIN_TTL_MINUTES = 15
_PIN_LENGTH = 4

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------

# ride_id -> { "pin": str, "driver_id": int, "generated_at": datetime }
_active_pins: dict[int, dict] = {}

# ride_id -> verification record dict
_verifications: dict[int, dict] = {}

_next_alert_id: int = 1
# alert_id -> alert dict
_mismatch_alerts: dict[int, dict] = {}

_next_verification_id: int = 1


def _reset_store() -> None:
    global _next_alert_id, _next_verification_id
    _active_pins.clear()
    _verifications.clear()
    _mismatch_alerts.clear()
    _next_alert_id = 1
    _next_verification_id = 1


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _generate_pin() -> str:
    return "".join(random.choices(string.digits, k=_PIN_LENGTH))


# ---------------------------------------------------------------------------
# PIN management
# ---------------------------------------------------------------------------


def generate_pin(ride_id: int, driver_id: int, ride_status: str) -> dict:
    """Generate (or regenerate) a boarding PIN for a ride.

    Args:
        ride_id: The ride to generate a PIN for.
        driver_id: The authenticated driver's user ID.
        ride_status: Current status string of the ride.

    Raises:
        ValueError: If ride is not in a state that allows PIN generation,
                    or if a confirmed verification already exists.
    """
    allowed_statuses = {"driver_en_route", "arrived"}
    if ride_status not in allowed_statuses:
        raise ValueError(
            f"A boarding PIN can only be generated when the ride status is "
            f"DRIVER_EN_ROUTE or ARRIVED (current: {ride_status!r})."
        )

    if ride_id in _verifications:
        raise ValueError(
            "A boarding verification has already been completed for this ride."
        )

    now = _now()
    record = {
        "ride_id": ride_id,
        "driver_id": driver_id,
        "pin": _generate_pin(),
        "generated_at": now,
        "expires_at": now + timedelta(minutes=_PIN_TTL_MINUTES),
    }
    _active_pins[ride_id] = record
    return record


def get_pin(ride_id: int) -> Optional[dict]:
    """Return the active PIN record for a ride, or None if no PIN exists."""
    record = _active_pins.get(ride_id)
    if record is None:
        return None
    if _now() > record["expires_at"]:
        # Expired — treat as absent but leave in store so caller can detect it
        return {**record, "expired": True}
    return {**record, "expired": False}


# ---------------------------------------------------------------------------
# Verification (rider confirms or disputes)
# ---------------------------------------------------------------------------


def confirm_boarding(
    ride_id: int,
    rider_id: int,
    pin_entered: str,
    confirmed_driver_name: Optional[str],
    confirmed_plate: Optional[str],
    notes: Optional[str],
) -> dict:
    """Record the rider's boarding verification.

    The rider submits the PIN they received from the driver verbally.  If it
    matches the active PIN, confirmed=True is stored.  If it does not match
    (or no PIN exists), confirmed=False is stored and a mismatch alert is
    created.

    Args:
        ride_id: The ride being verified.
        rider_id: The authenticated rider's user ID.
        pin_entered: The PIN the rider received verbally from the driver.
        confirmed_driver_name: Optional — rider confirms driver's name matches.
        confirmed_plate: Optional — rider confirms the license plate matches.
        notes: Optional free-text notes.

    Raises:
        ValueError: If verification already exists for this ride.
    """
    global _next_verification_id, _next_alert_id

    if ride_id in _verifications:
        raise ValueError(
            "A boarding verification has already been recorded for this ride."
        )

    active = _active_pins.get(ride_id)
    now = _now()

    pin_match: bool
    driver_id: Optional[int]

    if active is None or now > active["expires_at"]:
        # No valid PIN — treat as mismatch
        pin_match = False
        driver_id = active["driver_id"] if active else None
    else:
        pin_match = pin_entered == active["pin"]
        driver_id = active["driver_id"]

    confirmed = pin_match  # overall confirmation flag

    record: dict = {
        "id": _next_verification_id,
        "ride_id": ride_id,
        "rider_id": rider_id,
        "driver_id": driver_id,
        "pin_match": pin_match,
        "confirmed": confirmed,
        "confirmed_driver_name": confirmed_driver_name,
        "confirmed_plate": confirmed_plate,
        "notes": notes,
        "verified_at": now,
        "alert_id": None,
    }
    _next_verification_id += 1

    if not confirmed:
        alert: dict = {
            "id": _next_alert_id,
            "ride_id": ride_id,
            "rider_id": rider_id,
            "driver_id": driver_id,
            "reason": "PIN mismatch or no active PIN at boarding time",
            "created_at": now,
            "resolved": False,
        }
        _mismatch_alerts[_next_alert_id] = alert
        record["alert_id"] = _next_alert_id
        _next_alert_id += 1

    _verifications[ride_id] = record
    return record


def get_verification(ride_id: int) -> Optional[dict]:
    """Return the boarding verification record for a ride, or None."""
    return _verifications.get(ride_id)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


def admin_list_mismatch_alerts(include_resolved: bool = False) -> list[dict]:
    """Return boarding mismatch alerts, optionally including resolved ones."""
    alerts = list(_mismatch_alerts.values())
    if not include_resolved:
        alerts = [a for a in alerts if not a["resolved"]]
    return sorted(alerts, key=lambda a: a["created_at"])


def admin_resolve_mismatch_alert(alert_id: int, resolution_notes: Optional[str]) -> dict:
    """Mark a mismatch alert as resolved.

    Raises:
        KeyError: If alert_id does not exist.
        ValueError: If alert is already resolved.
    """
    alert = _mismatch_alerts.get(alert_id)
    if alert is None:
        raise KeyError(alert_id)
    if alert["resolved"]:
        raise ValueError("Alert is already resolved.")
    alert["resolved"] = True
    alert["resolved_at"] = _now()
    alert["resolution_notes"] = resolution_notes
    return alert
