"""Service area management and geofence validation.

Cooperatives define polygon boundaries for their operating areas.
Ride requests are validated against active service areas — both pickup
and dropoff must fall within at least one active area.
"""

from geoalchemy2.functions import ST_Contains, ST_GeomFromText, ST_MakePoint
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service_area import ServiceArea


def _polygon_wkt(coordinates: list[list[float]]) -> str:
    """Convert a list of [lng, lat] pairs to a WKT POLYGON string.

    Coordinates must form a closed ring (first == last).
    GeoJSON convention: [longitude, latitude].
    """
    if coordinates[0] != coordinates[-1]:
        coordinates = [*coordinates, coordinates[0]]
    ring = ", ".join(f"{lng} {lat}" for lng, lat in coordinates)
    return f"SRID=4326;POLYGON(({ring}))"


async def create_service_area(
    db: AsyncSession,
    name: str,
    coordinates: list[list[float]],
    description: str | None = None,
) -> ServiceArea:
    """Create a new service area from a polygon.

    Args:
        name: Human-readable area name (e.g. "Downtown Portland").
        coordinates: List of [lng, lat] pairs forming the boundary polygon.
        description: Optional description.
    """
    wkt = _polygon_wkt(coordinates)
    area = ServiceArea(
        name=name,
        description=description,
        boundary=ST_GeomFromText(wkt),
        is_active=True,
    )
    db.add(area)
    await db.flush()
    return area


async def update_service_area(
    db: AsyncSession,
    area_id: int,
    name: str | None = None,
    coordinates: list[list[float]] | None = None,
    description: str | None = None,
    is_active: bool | None = None,
) -> ServiceArea | None:
    """Update an existing service area. Returns None if not found."""
    result = await db.execute(select(ServiceArea).where(ServiceArea.id == area_id))
    area = result.scalar_one_or_none()
    if not area:
        return None

    if name is not None:
        area.name = name
    if description is not None:
        area.description = description
    if is_active is not None:
        area.is_active = is_active
    if coordinates is not None:
        area.boundary = ST_GeomFromText(_polygon_wkt(coordinates))

    await db.flush()
    return area


async def delete_service_area(db: AsyncSession, area_id: int) -> bool:
    """Delete a service area. Returns True if deleted, False if not found."""
    result = await db.execute(select(ServiceArea).where(ServiceArea.id == area_id))
    area = result.scalar_one_or_none()
    if not area:
        return False
    await db.delete(area)
    await db.flush()
    return True


async def list_service_areas(
    db: AsyncSession, active_only: bool = False
) -> list[ServiceArea]:
    """List all service areas, optionally filtering to active only."""
    query = select(ServiceArea).order_by(ServiceArea.name)
    if active_only:
        query = query.where(ServiceArea.is_active.is_(True))
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_service_area(db: AsyncSession, area_id: int) -> ServiceArea | None:
    result = await db.execute(select(ServiceArea).where(ServiceArea.id == area_id))
    return result.scalar_one_or_none()


async def point_in_service_area(
    db: AsyncSession, lat: float, lng: float
) -> bool:
    """Check if a point falls within any active service area."""
    point = ST_MakePoint(lng, lat, 4326)
    result = await db.execute(
        select(ServiceArea.id)
        .where(
            ServiceArea.is_active.is_(True),
            ST_Contains(ServiceArea.boundary, point),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def validate_ride_locations(
    db: AsyncSession,
    pickup_lat: float,
    pickup_lng: float,
    dropoff_lat: float,
    dropoff_lng: float,
) -> dict:
    """Validate that both pickup and dropoff are within active service areas.

    Returns a dict with:
        valid: bool
        pickup_covered: bool
        dropoff_covered: bool
        message: str (only if invalid)
    """
    # If no active service areas exist, allow all rides (cooperative hasn't set up geofencing yet)
    area_count = await db.execute(
        select(ServiceArea.id).where(ServiceArea.is_active.is_(True)).limit(1)
    )
    if area_count.scalar_one_or_none() is None:
        return {"valid": True, "pickup_covered": True, "dropoff_covered": True}

    pickup_ok = await point_in_service_area(db, pickup_lat, pickup_lng)
    dropoff_ok = await point_in_service_area(db, dropoff_lat, dropoff_lng)

    if pickup_ok and dropoff_ok:
        return {"valid": True, "pickup_covered": True, "dropoff_covered": True}

    parts = []
    if not pickup_ok:
        parts.append("Pickup location is outside our service area")
    if not dropoff_ok:
        parts.append("Dropoff location is outside our service area")

    return {
        "valid": False,
        "pickup_covered": pickup_ok,
        "dropoff_covered": dropoff_ok,
        "message": ". ".join(parts),
    }
