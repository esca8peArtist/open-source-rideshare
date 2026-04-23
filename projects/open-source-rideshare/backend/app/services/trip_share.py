from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

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
        "first_viewed_at": None,
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


def mark_first_view(token: str) -> int | None:
    """Record the first time a share link is viewed.

    Returns the rider_id if this is the first view (so the caller can notify
    the rider), or None if the link was already viewed before.
    """
    for record in _links.values():
        if record["token"] == token and record.get("is_active"):
            if record["first_viewed_at"] is None:
                record["first_viewed_at"] = datetime.now(tz=timezone.utc)
                return record["rider_id"]
            return None
    return None


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


async def get_trip_share_live_view(db: "AsyncSession", token: str) -> dict:
    """Return a public TripShareView dict backed by real DB data.

    Raises LookupError if the token does not exist.
    Raises ValueError("expired") if the link is revoked or expired.

    Driver/vehicle fields fall back to None when:
    - No ride record exists for the ride_id stored in the link, OR
    - The ride has no assigned driver yet, OR
    - The driver has not yet submitted a GPS location update.

    ETA is estimated as haversine distance from the driver's current position
    to the dropoff point at an assumed urban speed of 25 km/h.
    """
    from geoalchemy2.functions import ST_X, ST_Y
    from sqlalchemy import select

    from app.models.driver import DriverProfile
    from app.models.ride import Ride
    from app.models.user import User
    from app.services.driver_location import haversine_m

    link = get_link_by_token(token)

    now = datetime.now(tz=timezone.utc)
    if not link["is_active"] or link["expires_at"] <= now:
        raise ValueError("expired")

    ride_id = link["ride_id"]

    driver_first_name: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_color: str | None = None
    vehicle_plate: str | None = None
    pickup_address: str | None = None
    dropoff_address: str | None = None
    status = "unknown"
    driver_lat: float | None = None
    driver_lng: float | None = None
    eta_minutes: int | None = None

    ride_result = await db.execute(
        select(
            Ride.driver_id,
            Ride.status,
            Ride.pickup_address,
            Ride.dropoff_address,
            ST_Y(Ride.dropoff_location).label("dropoff_lat"),
            ST_X(Ride.dropoff_location).label("dropoff_lng"),
        ).where(Ride.id == ride_id)
    )
    ride_row = ride_result.one_or_none()

    if ride_row is not None:
        status = ride_row.status.value if ride_row.status else "unknown"
        pickup_address = ride_row.pickup_address
        dropoff_address = ride_row.dropoff_address

        if ride_row.driver_id is not None:
            name_result = await db.execute(
                select(User.name).where(User.id == ride_row.driver_id)
            )
            raw_name = name_result.scalar_one_or_none()
            if raw_name:
                driver_first_name = raw_name.split()[0]

            profile_result = await db.execute(
                select(
                    DriverProfile.vehicle_make,
                    DriverProfile.vehicle_model,
                    DriverProfile.vehicle_color,
                    DriverProfile.license_plate,
                    ST_Y(DriverProfile.current_location).label("lat"),
                    ST_X(DriverProfile.current_location).label("lng"),
                ).where(DriverProfile.user_id == ride_row.driver_id)
            )
            profile_row = profile_result.one_or_none()
            if profile_row is not None:
                vehicle_make = profile_row.vehicle_make
                vehicle_model = profile_row.vehicle_model
                vehicle_color = profile_row.vehicle_color
                vehicle_plate = profile_row.license_plate
                lat = float(profile_row.lat) if profile_row.lat is not None else None
                lng = float(profile_row.lng) if profile_row.lng is not None else None
                driver_lat = lat
                driver_lng = lng

                if (
                    lat is not None
                    and lng is not None
                    and ride_row.dropoff_lat is not None
                    and ride_row.dropoff_lng is not None
                ):
                    dist_m = haversine_m(
                        lat, lng,
                        float(ride_row.dropoff_lat),
                        float(ride_row.dropoff_lng),
                    )
                    # 25 km/h urban speed estimate
                    eta_minutes = max(1, round(dist_m / (25_000 / 60)))

    return {
        "token": link["token"],
        "ride_id": ride_id,
        "status": status,
        "driver_first_name": driver_first_name,
        "vehicle_make": vehicle_make,
        "vehicle_model": vehicle_model,
        "vehicle_color": vehicle_color,
        "vehicle_plate": vehicle_plate,
        "pickup_address": pickup_address,
        "dropoff_address": dropoff_address,
        "driver_lat": driver_lat,
        "driver_lng": driver_lng,
        "eta_minutes": eta_minutes,
        "expires_at": link["expires_at"],
    }


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
