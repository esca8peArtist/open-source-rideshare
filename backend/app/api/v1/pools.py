"""Ride pooling (shared rides) API endpoints.

Allows riders to request shared rides at a discount, and drivers to
manage pool pickups and dropoffs.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from geoalchemy2.functions import ST_MakePoint
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.deps import get_current_user, require_driver
from app.db.database import get_db
from app.models.driver import DriverProfile
from app.models.pool import LegStatus, PoolLeg, PoolStatus, RidePool
from app.models.ride import Ride, RideStatus
from app.models.user import User
from app.schemas.pool import (
    PoolEstimateRequest,
    PoolEstimateResponse,
    PoolLegResponse,
    PoolLegStatusUpdate,
    PoolResponse,
    PoolRideRequest,
    PoolRideResponse,
)
from app.services.pool_matching import (
    DISCOUNT_BY_RIDERS,
    PoolMatchingService,
    calculate_pool_fare,
)
from app.services.pricing import calculate_fare
from app.services.routing import RoutingError, get_route

router = APIRouter(prefix="/pools", tags=["pools"])


@router.post("/estimate", response_model=PoolEstimateResponse)
async def estimate_pool_fare(
    req: PoolEstimateRequest,
    user: User = Depends(get_current_user),
):
    """Estimate fare for a pool ride vs solo ride."""
    try:
        route = await get_route(
            req.pickup.lat, req.pickup.lng,
            req.dropoff.lat, req.dropoff.lng,
        )
    except RoutingError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not calculate route",
        )

    # Show savings assuming 2 riders (most common pool size)
    discount = DISCOUNT_BY_RIDERS[2]
    solo_fare, pool_fare, savings = calculate_pool_fare(
        route["distance_km"], route["duration_min"], discount,
    )
    return PoolEstimateResponse(
        solo_fare=solo_fare,
        pool_fare=pool_fare,
        discount_percent=discount,
        savings=savings,
        distance_km=round(route["distance_km"], 2),
        duration_min=round(route["duration_min"], 2),
    )


@router.post("/request", response_model=PoolRideResponse)
async def request_pool_ride(
    req: PoolRideRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Request a shared (pool) ride.

    Tries to match with an existing forming pool. If none found,
    creates a new pool and waits for other riders.
    """
    # Calculate route for this rider
    try:
        route = await get_route(
            req.pickup.lat, req.pickup.lng,
            req.dropoff.lat, req.dropoff.lng,
        )
    except RoutingError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not calculate route",
        )

    distance_km = route["distance_km"]
    duration_min = route["duration_min"]
    estimated_fare = calculate_fare(distance_km, duration_min)

    # Create the ride record
    ride = Ride(
        rider_id=user.id,
        status=RideStatus.REQUESTED,
        pickup_location=ST_MakePoint(req.pickup.lng, req.pickup.lat, srid=4326),
        dropoff_location=ST_MakePoint(req.dropoff.lng, req.dropoff.lat, srid=4326),
        pickup_address=req.pickup_address,
        dropoff_address=req.dropoff_address,
        estimated_fare=estimated_fare,
        distance_km=distance_km,
        duration_min=duration_min,
        is_pool=True,
    )
    db.add(ride)
    await db.flush()

    # Store lat/lng for pool matching (transient, not persisted as columns)
    ride._pickup_lat = req.pickup.lat
    ride._pickup_lng = req.pickup.lng
    ride._dropoff_lat = req.dropoff.lat
    ride._dropoff_lng = req.dropoff.lng

    pool_service = PoolMatchingService(db)

    # Try to find a compatible existing pool
    candidates = await pool_service.find_compatible_pools(
        req.pickup.lat, req.pickup.lng,
        req.dropoff.lat, req.dropoff.lng,
        distance_km,
    )

    if candidates:
        # Join best matching pool
        best = candidates[0]
        pool = await pool_service.get_pool(best.pool_id)
        if pool is None:
            raise HTTPException(status_code=500, detail="Pool not found")

        active_legs = [l for l in pool.legs if l.status != LegStatus.CANCELLED]
        pickup_order = len(active_legs) + 1
        dropoff_order = pickup_order  # Simplified: same order as pickup

        leg = await pool_service.add_rider_to_pool(
            pool, ride,
            pickup_order=pickup_order,
            dropoff_order=dropoff_order,
            detour_km=best.detour_km,
        )
        discount = leg.fare_discount_percent
        riders_in_pool = len(active_legs) + 1
    else:
        # Create a new pool
        pool = await pool_service.create_pool()
        leg = await pool_service.add_rider_to_pool(
            pool, ride,
            pickup_order=1,
            dropoff_order=1,
        )
        discount = leg.fare_discount_percent
        riders_in_pool = 1

    await db.commit()

    solo_fare, pool_fare, _ = calculate_pool_fare(distance_km, duration_min, discount)

    return PoolRideResponse(
        ride_id=ride.id,
        pool_id=pool.id,
        status=pool.status.value,
        estimated_fare=solo_fare,
        pool_fare=pool_fare,
        discount_percent=discount,
        pickup_address=req.pickup_address,
        dropoff_address=req.dropoff_address,
        riders_in_pool=riders_in_pool,
        max_riders=pool.max_riders,
    )


@router.get("/{pool_id}", response_model=PoolResponse)
async def get_pool(
    pool_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get pool details with all legs."""
    result = await db.execute(
        select(RidePool)
        .options(joinedload(RidePool.legs).joinedload(PoolLeg.ride))
        .where(RidePool.id == pool_id)
    )
    pool = result.unique().scalar_one_or_none()
    if not pool:
        raise HTTPException(status_code=404, detail="Pool not found")

    # Build leg responses
    legs = []
    for leg in pool.legs:
        ride = leg.ride
        legs.append(PoolLegResponse(
            id=leg.id,
            ride_id=leg.ride_id,
            rider_name=None,  # Privacy: don't expose names until matched
            pickup_address=ride.pickup_address if ride else "",
            dropoff_address=ride.dropoff_address if ride else "",
            pickup_order=leg.pickup_order,
            dropoff_order=leg.dropoff_order,
            fare_discount_percent=leg.fare_discount_percent,
            status=leg.status.value,
            picked_up_at=leg.picked_up_at,
            dropped_off_at=leg.dropped_off_at,
        ))

    active_legs = [l for l in pool.legs if l.status != LegStatus.CANCELLED]

    return PoolResponse(
        id=pool.id,
        status=pool.status.value,
        max_riders=pool.max_riders,
        current_riders=len(active_legs),
        driver_name=None,
        total_distance_km=pool.total_distance_km,
        total_duration_min=pool.total_duration_min,
        legs=legs,
        created_at=pool.created_at,
        matched_at=pool.matched_at,
        started_at=pool.started_at,
        completed_at=pool.completed_at,
    )


@router.post("/{pool_id}/cancel")
async def cancel_pool_ride(
    pool_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel your leg in a pool ride."""
    # Find the user's leg in this pool
    result = await db.execute(
        select(PoolLeg)
        .join(Ride, PoolLeg.ride_id == Ride.id)
        .where(PoolLeg.pool_id == pool_id, Ride.rider_id == user.id)
        .where(PoolLeg.status == LegStatus.WAITING_PICKUP)
    )
    leg = result.scalar_one_or_none()
    if not leg:
        raise HTTPException(status_code=404, detail="No active pool leg found for this user")

    pool_service = PoolMatchingService(db)
    await pool_service.remove_rider_from_pool(leg)

    # Also cancel the underlying ride
    ride = await db.get(Ride, leg.ride_id)
    if ride:
        ride.status = RideStatus.CANCELLED
        ride.cancellation_reason = "Pool ride cancelled by rider"

    await db.commit()
    return {"detail": "Pool ride cancelled", "pool_id": pool_id}


@router.post("/{pool_id}/pickup", status_code=200)
async def pickup_pool_rider(
    pool_id: int,
    body: PoolLegStatusUpdate,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Driver marks a pool rider as picked up."""
    leg = await db.get(PoolLeg, body.leg_id)
    if not leg or leg.pool_id != pool_id:
        raise HTTPException(status_code=404, detail="Pool leg not found")
    if leg.status != LegStatus.WAITING_PICKUP:
        raise HTTPException(status_code=400, detail="Rider not waiting for pickup")

    # Verify driver is assigned to this pool
    pool = await db.get(RidePool, pool_id)
    if not pool or pool.driver_id != driver.id:
        raise HTTPException(status_code=403, detail="Not assigned to this pool")

    pool_service = PoolMatchingService(db)
    await pool_service.pickup_rider(leg)

    # Update the underlying ride status
    ride = await db.get(Ride, leg.ride_id)
    if ride:
        ride.status = RideStatus.IN_PROGRESS

    await db.commit()
    return {"detail": "Rider picked up", "leg_id": leg.id, "pool_id": pool_id}


@router.post("/{pool_id}/dropoff", status_code=200)
async def dropoff_pool_rider(
    pool_id: int,
    body: PoolLegStatusUpdate,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Driver marks a pool rider as dropped off."""
    leg = await db.get(PoolLeg, body.leg_id)
    if not leg or leg.pool_id != pool_id:
        raise HTTPException(status_code=404, detail="Pool leg not found")
    if leg.status != LegStatus.PICKED_UP:
        raise HTTPException(status_code=400, detail="Rider not picked up yet")

    pool = await db.get(RidePool, pool_id)
    if not pool or pool.driver_id != driver.id:
        raise HTTPException(status_code=403, detail="Not assigned to this pool")

    pool_service = PoolMatchingService(db)
    await pool_service.dropoff_rider(leg)

    # Complete the underlying ride and apply pool discount to fare
    ride = await db.get(Ride, leg.ride_id)
    if ride:
        ride.status = RideStatus.COMPLETED
        if ride.estimated_fare and leg.fare_discount_percent:
            ride.actual_fare = round(
                ride.estimated_fare * (1 - leg.fare_discount_percent / 100), 2
            )

    await db.commit()
    return {
        "detail": "Rider dropped off",
        "leg_id": leg.id,
        "pool_id": pool_id,
        "pool_status": pool.status.value if pool else None,
    }
