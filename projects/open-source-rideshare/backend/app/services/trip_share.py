from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# In-memory store (same pattern as other rider safety services)
# ---------------------------------------------------------------------------

_next_id: int = 1
_links: dict[int, dict] = {}  # link_id -> record


def _reset_store() -> None:
    global _next_id
    _next_id = 1
    _links.clear()


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


def create_trip_share_link(rider_id: int, ride_id: int) -> dict:
    """Create a new trip share link for the given rider+ride.

    If an active link already exists for this rider+ride, it is revoked first
    so that only one active link exists per ride at any time.

    Returns the newly created record dict.
    """
    global _next_id

    # Revoke any existing active link for this rider+ride
    for record in _links.values():
        if record["rider_id"] == rider_id and record["ride_id"] == ride_id and record["is_active"]:
            record["is_active"] = False

    token = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)
    expires_at = now + timedelta(hours=24)
    share_url = f"/api/v1/trip-share/{token}"

    record: dict = {
        "id": _next_id,
        "token": token,
        "ride_id": ride_id,
        "rider_id": rider_id,
        "share_url": share_url,
        "is_active": True,
        "expires_at": expires_at,
        "created_at": now,
    }
    _links[_next_id] = record
    _next_id += 1
    return record


def get_active_link_for_ride(rider_id: int, ride_id: int) -> dict | None:
    """Return the active, non-expired link for this rider+ride, or None."""
    now = datetime.now(tz=timezone.utc)
    for record in _links.values():
        if (
            record["rider_id"] == rider_id
            and record["ride_id"] == ride_id
            and record["is_active"]
            and record["expires_at"] > now
        ):
            return record
    return None


def revoke_trip_share_link(rider_id: int, ride_id: int) -> None:
    """Revoke the active share link for this rider+ride.

    Raises:
        LookupError: if no active link exists.
    """
    for record in _links.values():
        if record["rider_id"] == rider_id and record["ride_id"] == ride_id and record["is_active"]:
            record["is_active"] = False
            return
    raise LookupError("No active share link found for this ride")


def list_trip_share_links(
    rider_id: int | None = None,
    is_active: bool | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[dict]:
    """Return a filtered, paginated list of share links, newest-first."""
    results = []
    for record in _links.values():
        if rider_id is not None and record["rider_id"] != rider_id:
            continue
        if is_active is not None and record["is_active"] != is_active:
            continue
        results.append(record)
    results.sort(key=lambda r: r["created_at"], reverse=True)
    return results[skip : skip + limit]


def get_link_by_token(token: str) -> dict:
    """Return the record for the given token.

    Raises:
        LookupError: if no record with this token exists.
    """
    for record in _links.values():
        if record["token"] == token:
            return record
    raise LookupError("Share link not found")


def admin_revoke_by_token(token: str) -> None:
    """Revoke a share link by token regardless of rider ownership.

    Raises:
        LookupError: if no record with this token exists.
    """
    for record in _links.values():
        if record["token"] == token:
            record["is_active"] = False
            return
    raise LookupError("Share link not found")


def get_trip_share_view(token: str) -> dict:
    """Return a public-facing view for the given share token.

    Raises:
        LookupError: if the token does not exist.
        ValueError("expired"): if the link is revoked or expired.

    Returns a TripShareView-compatible dict with realistic stub ride data.
    """
    link = None
    for record in _links.values():
        if record["token"] == token:
            link = record
            break

    if link is None:
        raise LookupError("Share link not found")

    now = datetime.now(tz=timezone.utc)
    if not link["is_active"] or link["expires_at"] <= now:
        raise ValueError("expired")

    return {
        "token": link["token"],
        "ride_id": link["ride_id"],
        "status": "IN_PROGRESS",
        "driver_first_name": "Alex",
        "vehicle_make": "Toyota",
        "vehicle_model": "Camry",
        "vehicle_color": "Silver",
        "vehicle_plate": "XYZ123",
        "pickup_address": "123 Main St",
        "dropoff_address": "456 Oak Ave",
        "driver_lat": 37.7749,
        "driver_lng": -122.4194,
        "eta_minutes": 8,
        "expires_at": link["expires_at"],
    }
