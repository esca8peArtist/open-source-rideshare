from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus
from app.models.waypoint import RideWaypoint, WaypointStatus

MAX_WAYPOINTS = 3

# Statuses where waypoints can be added/modified
_MODIFIABLE_STATUSES = {
    RideStatus.REQUESTED,
    RideStatus.MATCHED,
    RideStatus.DRIVER_EN_ROUTE,
    RideStatus.ARRIVED,
}

# Valid status transitions for waypoints
_VALID_TRANSITIONS = {
    WaypointStatus.PENDING: {WaypointStatus.ARRIVED, WaypointStatus.SKIPPED},
    WaypointStatus.ARRIVED: {WaypointStatus.DEPARTED, WaypointStatus.SKIPPED},
    WaypointStatus.DEPARTED: set(),
    WaypointStatus.SKIPPED: set(),
}


class WaypointError(Exception):
    pass


async def get_ride_for_waypoint_ops(
    db: AsyncSession, ride_id: int, user_id: int
) -> Ride:
    """Fetch ride and verify the user is the rider."""
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        raise WaypointError("Ride not found")
    if ride.rider_id != user_id:
        raise WaypointError("Not authorized")
    return ride


async def get_waypoints(db: AsyncSession, ride_id: int) -> list[RideWaypoint]:
    """Get all waypoints for a ride, ordered by position."""
    result = await db.execute(
        select(RideWaypoint)
        .where(RideWaypoint.ride_id == ride_id)
        .order_by(RideWaypoint.order)
    )
    return list(result.scalars().all())


async def add_waypoint(
    db: AsyncSession,
    ride_id: int,
    user_id: int,
    address: str,
    lat: float,
    lng: float,
    wait_time_minutes: int = 3,
    notes: str | None = None,
) -> RideWaypoint:
    """Add a waypoint to a ride. Rider only, ride must be in modifiable status."""
    ride = await get_ride_for_waypoint_ops(db, ride_id, user_id)

    if ride.status not in _MODIFIABLE_STATUSES:
        raise WaypointError(
            f"Cannot add waypoints when ride is {ride.status.value}"
        )

    existing = await get_waypoints(db, ride_id)
    if len(existing) >= MAX_WAYPOINTS:
        raise WaypointError(f"Maximum {MAX_WAYPOINTS} waypoints per ride")

    new_order = len(existing) + 1

    waypoint = RideWaypoint(
        ride_id=ride_id,
        order=new_order,
        address=address,
        lat=lat,
        lng=lng,
        wait_time_minutes=wait_time_minutes,
        notes=notes,
        status=WaypointStatus.PENDING,
    )
    db.add(waypoint)
    await db.commit()
    await db.refresh(waypoint)
    return waypoint


async def add_waypoints_bulk(
    db: AsyncSession,
    ride_id: int,
    user_id: int,
    waypoints_data: list[dict],
) -> list[RideWaypoint]:
    """Add multiple waypoints at once (used during ride creation)."""
    ride = await get_ride_for_waypoint_ops(db, ride_id, user_id)

    if ride.status not in _MODIFIABLE_STATUSES:
        raise WaypointError(
            f"Cannot add waypoints when ride is {ride.status.value}"
        )

    if len(waypoints_data) > MAX_WAYPOINTS:
        raise WaypointError(f"Maximum {MAX_WAYPOINTS} waypoints per ride")

    existing = await get_waypoints(db, ride_id)
    if len(existing) + len(waypoints_data) > MAX_WAYPOINTS:
        raise WaypointError(
            f"Maximum {MAX_WAYPOINTS} waypoints per ride "
            f"({len(existing)} existing)"
        )

    created = []
    for i, wp_data in enumerate(waypoints_data, start=len(existing) + 1):
        wp = RideWaypoint(
            ride_id=ride_id,
            order=i,
            address=wp_data["address"],
            lat=wp_data["lat"],
            lng=wp_data["lng"],
            wait_time_minutes=wp_data.get("wait_time_minutes", 3),
            notes=wp_data.get("notes"),
            status=WaypointStatus.PENDING,
        )
        db.add(wp)
        created.append(wp)

    await db.commit()
    for wp in created:
        await db.refresh(wp)
    return created


async def update_waypoint(
    db: AsyncSession,
    ride_id: int,
    waypoint_id: int,
    user_id: int,
    update_data: dict,
) -> RideWaypoint:
    """Update waypoint details (address, coordinates, wait time, notes).

    Only allowed when the ride is in a modifiable status and the waypoint
    is still pending.
    """
    ride = await get_ride_for_waypoint_ops(db, ride_id, user_id)

    if ride.status not in _MODIFIABLE_STATUSES:
        raise WaypointError(
            f"Cannot update waypoints when ride is {ride.status.value}"
        )

    result = await db.execute(
        select(RideWaypoint).where(
            RideWaypoint.id == waypoint_id,
            RideWaypoint.ride_id == ride_id,
        )
    )
    waypoint = result.scalar_one_or_none()
    if not waypoint:
        raise WaypointError("Waypoint not found")

    if waypoint.status != WaypointStatus.PENDING:
        raise WaypointError("Can only update pending waypoints")

    for field in ("address", "lat", "lng", "wait_time_minutes", "notes"):
        if field in update_data and update_data[field] is not None:
            setattr(waypoint, field, update_data[field])

    await db.commit()
    await db.refresh(waypoint)
    return waypoint


async def remove_waypoint(
    db: AsyncSession,
    ride_id: int,
    waypoint_id: int,
    user_id: int,
) -> None:
    """Remove a waypoint and reorder remaining ones."""
    ride = await get_ride_for_waypoint_ops(db, ride_id, user_id)

    if ride.status not in _MODIFIABLE_STATUSES:
        raise WaypointError(
            f"Cannot remove waypoints when ride is {ride.status.value}"
        )

    result = await db.execute(
        select(RideWaypoint).where(
            RideWaypoint.id == waypoint_id,
            RideWaypoint.ride_id == ride_id,
        )
    )
    waypoint = result.scalar_one_or_none()
    if not waypoint:
        raise WaypointError("Waypoint not found")

    if waypoint.status != WaypointStatus.PENDING:
        raise WaypointError("Can only remove pending waypoints")

    removed_order = waypoint.order
    await db.delete(waypoint)

    # Reorder remaining waypoints
    remaining = await db.execute(
        select(RideWaypoint)
        .where(
            RideWaypoint.ride_id == ride_id,
            RideWaypoint.order > removed_order,
        )
        .order_by(RideWaypoint.order)
    )
    for wp in remaining.scalars().all():
        wp.order -= 1

    await db.commit()


async def update_waypoint_status(
    db: AsyncSession,
    ride_id: int,
    waypoint_id: int,
    new_status: WaypointStatus,
) -> RideWaypoint:
    """Update waypoint status (arrived, departed, skipped). Used by driver."""
    result = await db.execute(
        select(RideWaypoint).where(
            RideWaypoint.id == waypoint_id,
            RideWaypoint.ride_id == ride_id,
        )
    )
    waypoint = result.scalar_one_or_none()
    if not waypoint:
        raise WaypointError("Waypoint not found")

    if new_status not in _VALID_TRANSITIONS.get(waypoint.status, set()):
        raise WaypointError(
            f"Cannot transition from {waypoint.status.value} to {new_status.value}"
        )

    waypoint.status = new_status
    now = datetime.now(timezone.utc)

    if new_status == WaypointStatus.ARRIVED:
        waypoint.actual_arrival_at = now
    elif new_status == WaypointStatus.DEPARTED:
        waypoint.departed_at = now

    await db.commit()
    await db.refresh(waypoint)
    return waypoint


async def get_next_pending_waypoint(
    db: AsyncSession, ride_id: int
) -> RideWaypoint | None:
    """Get the next pending waypoint in order for a ride."""
    result = await db.execute(
        select(RideWaypoint)
        .where(
            RideWaypoint.ride_id == ride_id,
            RideWaypoint.status == WaypointStatus.PENDING,
        )
        .order_by(RideWaypoint.order)
        .limit(1)
    )
    return result.scalar_one_or_none()
