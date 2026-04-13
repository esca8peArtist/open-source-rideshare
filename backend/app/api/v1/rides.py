import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from geoalchemy2.functions import ST_MakePoint
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_driver
from app.api.rate_limit import RateLimit
from app.config import settings
from app.db.database import get_db
from app.models.driver import DriverProfile
from app.models.ride import Ride, RideStatus
from app.models.user import User
from app.schemas.ride import (
    CancelRequest,
    CancelResponse,
    FareEstimateRequest,
    FareEstimateResponse,
    GeocodeRequest,
    GeocodeResponse,
    ReverseGeocodeRequest,
    ReverseGeocodeResponse,
    RideReceiptResponse,
    RideRequest,
    RideRatingRequest,
    RideResponse,
    ScheduleRideRequest,
)
from app.schemas.eta import DriverETAResponse, DriverLocationResponse, TripETAResponse
from app.schemas.feedback import (
    DisputeCreate,
    DisputeResponse,
    FeedbackCreate,
    FeedbackResponse,
)
from app.services.cancellation import evaluate_cancellation
from app.services.payments import create_cancellation_payment_intent
from app.services.geocoding import GeocodingError, geocode, reverse_geocode
from app.services.service_areas import validate_ride_locations
from app.services.matching import get_matching_engine, get_redis
from app.services.pricing import calculate_fare, calculate_fare_breakdown
from app.services.demand_pricing import get_demand_info, record_demand
from app.services.promos import redeem_promo, validate_promo
from app.services.routing import RoutingError, get_multi_stop_route, get_route
from app.services.saved_locations import get_saved_location
from app.services.scheduling import check_overlap, validate_schedule_time

router = APIRouter(prefix="/rides", tags=["rides"])


async def _resolve_saved_location(
    db: AsyncSession, user_id: int, saved_id: int | None, point, address: str | None, field_name: str
):
    """Resolve a saved location ID to (LocationPoint, address).

    If a saved_location_id is provided, fetch the saved location and build a
    LocationPoint + address from it.  Otherwise, require that point and address
    are already present on the request.
    """
    from app.schemas.ride import LocationPoint

    if saved_id is not None:
        loc = await get_saved_location(db, user_id, saved_id)
        if not loc:
            raise HTTPException(
                status_code=404,
                detail=f"Saved location {saved_id} not found for {field_name}",
            )
        return LocationPoint(lat=loc.lat, lng=loc.lng), loc.address
    if point is None:
        raise HTTPException(
            status_code=422,
            detail=f"Either {field_name} or {field_name}_saved_location_id is required",
        )
    return point, address

_ride_request_limit = RateLimit(
    settings.rate_limit_ride_request, settings.rate_limit_ride_request_window, key_prefix="ride_request",
)


@router.post("/estimate", response_model=FareEstimateResponse)
async def estimate_fare(
    req: FareEstimateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.schemas.ride import FareBreakdownResponse

    # Resolve saved locations if provided
    pickup, _ = await _resolve_saved_location(db, user.id, req.pickup_saved_location_id, req.pickup, None, "pickup")
    dropoff, _ = await _resolve_saved_location(db, user.id, req.dropoff_saved_location_id, req.dropoff, None, "dropoff")

    # Validate locations are within service area
    geo_check = await validate_ride_locations(
        db, pickup.lat, pickup.lng, dropoff.lat, dropoff.lng
    )
    if not geo_check["valid"]:
        raise HTTPException(status_code=422, detail=geo_check["message"])

    # Route calculation — multi-stop if waypoints provided
    wp_coords = [(wp.lat, wp.lng) for wp in (req.waypoints or [])]
    try:
        if wp_coords:
            route = await get_multi_stop_route(
                pickup.lat, pickup.lng, dropoff.lat, dropoff.lng, wp_coords
            )
            # Add estimated wait time at waypoints to total duration
            wait_minutes = sum(wp.wait_time_minutes for wp in req.waypoints)
            route["duration_min"] += wait_minutes
        else:
            route = await get_route(pickup.lat, pickup.lng, dropoff.lat, dropoff.lng)
    except RoutingError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Get demand pricing info for pickup location
    from app.schemas.ride import DemandInfoSummary

    demand_summary = None
    try:
        redis_client = await get_redis()
        demand = await get_demand_info(redis_client, pickup.lat, pickup.lng)
        bd = calculate_fare_breakdown(
            route["distance_km"],
            route["duration_min"],
            demand_multiplier=demand.multiplier,
            demand_label=demand.explanation,
        )
        demand_summary = DemandInfoSummary(
            multiplier=demand.multiplier,
            is_elevated=demand.is_elevated,
            explanation=demand.explanation,
        )
    except Exception:
        # Fall back to standard pricing if Redis is unavailable
        bd = calculate_fare_breakdown(route["distance_km"], route["duration_min"])

    # Validate promo code if provided
    promo_discount = 0.0
    promo_code_str = None
    if req.promo_code:
        validation = await validate_promo(req.promo_code, user.id, bd.total, db)
        if validation.valid:
            promo_discount = validation.discount
            promo_code_str = req.promo_code.upper().strip()

    final_fare = round(bd.total - promo_discount, 2)

    return FareEstimateResponse(
        estimated_fare=bd.total,
        distance_km=round(route["distance_km"], 2),
        duration_min=round(route["duration_min"], 1),
        breakdown=FareBreakdownResponse(
            base=bd.base,
            distance=bd.distance,
            time=bd.time,
            multiplier=bd.multiplier,
            multiplier_label=bd.multiplier_label,
            demand_multiplier=bd.demand_multiplier,
            demand_label=bd.demand_label,
            subtotal=bd.subtotal,
            platform_fee=bd.platform_fee,
            total=bd.total,
        ),
        demand_info=demand_summary,
        promo_discount=promo_discount,
        final_fare=final_fare,
        promo_code=promo_code_str,
    )


@router.post("/request", response_model=RideResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(_ride_request_limit)])
async def request_ride(
    req: RideRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Resolve saved locations if provided
    pickup, pickup_address = await _resolve_saved_location(
        db, user.id, req.pickup_saved_location_id, req.pickup, req.pickup_address, "pickup"
    )
    dropoff, dropoff_address = await _resolve_saved_location(
        db, user.id, req.dropoff_saved_location_id, req.dropoff, req.dropoff_address, "dropoff"
    )
    if not pickup_address:
        raise HTTPException(status_code=422, detail="pickup_address is required when not using a saved location")
    if not dropoff_address:
        raise HTTPException(status_code=422, detail="dropoff_address is required when not using a saved location")

    # Validate locations are within service area
    geo_check = await validate_ride_locations(
        db, pickup.lat, pickup.lng, dropoff.lat, dropoff.lng
    )
    if not geo_check["valid"]:
        raise HTTPException(status_code=422, detail=geo_check["message"])

    # Validate waypoint count
    waypoint_inputs = req.waypoints or []
    if len(waypoint_inputs) > 3:
        raise HTTPException(status_code=422, detail="Maximum 3 waypoints allowed")

    # Route calculation — multi-stop if waypoints provided
    wp_coords = [(wp.lat, wp.lng) for wp in waypoint_inputs]
    try:
        if wp_coords:
            route = await get_multi_stop_route(
                pickup.lat, pickup.lng, dropoff.lat, dropoff.lng, wp_coords
            )
            wait_minutes = sum(wp.wait_time_minutes for wp in waypoint_inputs)
            route["duration_min"] += wait_minutes
        else:
            route = await get_route(pickup.lat, pickup.lng, dropoff.lat, dropoff.lng)
    except RoutingError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Record demand and calculate fare with demand multiplier
    try:
        redis_client = await get_redis()
        await record_demand(redis_client, pickup.lat, pickup.lng)
        demand = await get_demand_info(redis_client, pickup.lat, pickup.lng)
        bd = calculate_fare_breakdown(
            route["distance_km"],
            route["duration_min"],
            demand_multiplier=demand.multiplier,
            demand_label=demand.explanation,
        )
        fare = bd.total
    except Exception:
        fare = calculate_fare(route["distance_km"], route["duration_min"])

    # Validate and apply promo code if provided
    promo_discount = 0.0
    promo_code_id = None
    if req.promo_code:
        validation = await validate_promo(req.promo_code, user.id, fare, db)
        if validation.valid:
            promo_discount = validation.discount
            promo_code_id = validation.promo_code_id

    ride = Ride(
        rider_id=user.id,
        status=RideStatus.REQUESTED,
        pickup_location=ST_MakePoint(pickup.lng, pickup.lat, 4326),
        dropoff_location=ST_MakePoint(dropoff.lng, dropoff.lat, 4326),
        pickup_address=pickup_address,
        dropoff_address=dropoff_address,
        estimated_fare=round(fare - promo_discount, 2),
        distance_km=round(route["distance_km"], 2),
        duration_min=round(route["duration_min"], 1),
        promo_code_id=promo_code_id,
        promo_discount=promo_discount,
        accessibility_required=req.accessibility_required,
    )
    db.add(ride)
    await db.commit()
    await db.refresh(ride)

    # Create waypoints if provided
    if waypoint_inputs:
        from app.services.waypoints import add_waypoints_bulk
        await add_waypoints_bulk(
            db,
            ride.id,
            user.id,
            [wp.model_dump() for wp in waypoint_inputs],
        )

    # Record promo redemption if a promo was applied
    if promo_code_id:
        await redeem_promo(promo_code_id, user.id, ride.id, promo_discount, db)
        await db.commit()

    from app.services.audit_events import audit_ride_requested
    await audit_ride_requested(
        db, ride_id=ride.id, rider_id=user.id,
        pickup=ride.pickup_address, dropoff=ride.dropoff_address,
    )

    background_tasks.add_task(
        _match_ride_background,
        ride.id,
        user.id,
        pickup.lat,
        pickup.lng,
        ride.pickup_address,
        ride.dropoff_address,
        ride.estimated_fare,
        req.accessibility_required,
    )

    return RideResponse(
        id=ride.id,
        status=ride.status.value,
        pickup_address=ride.pickup_address,
        dropoff_address=ride.dropoff_address,
        estimated_fare=ride.estimated_fare,
        requested_at=ride.requested_at,
    )


async def _match_ride_background(
    ride_id: int,
    rider_user_id: int,
    pickup_lat: float,
    pickup_lng: float,
    pickup_address: str,
    dropoff_address: str,
    estimated_fare: float,
    accessibility_required: bool = False,
) -> None:
    from app.api.websocket import notify_ride_status, send_ride_offer
    from app.db.database import async_session

    engine = await get_matching_engine()

    async with async_session() as db:
        result = await db.execute(select(Ride).where(Ride.id == ride_id))
        ride = result.scalar_one_or_none()
        if not ride or ride.status != RideStatus.REQUESTED:
            return

        candidates = await engine.find_candidates(
            pickup_lat, pickup_lng, db, accessibility_required=accessibility_required
        )
        if not candidates:
            await notify_ride_status(rider_user_id, ride_id, "no_drivers")
            return

        matched = await engine.match_ride(
            ride, pickup_lat, pickup_lng, db, accessibility_required=accessibility_required
        )
        if not matched:
            await notify_ride_status(rider_user_id, ride_id, "no_drivers")
            return

        await send_ride_offer(
            matched.user_id, ride_id, pickup_address,
            dropoff_address, estimated_fare, matched.distance_km,
        )

        ride.driver_id = matched.user_id
        ride.status = RideStatus.MATCHED
        ride.matched_at = datetime.now(timezone.utc)
        await db.commit()

        await engine.set_driver_busy(matched.user_id)

        # Include ETA in the matched notification
        eta_data: dict = {"driver_distance_km": round(matched.distance_km, 2)}
        try:
            from app.services.eta import estimate_driver_eta

            eta = await estimate_driver_eta(
                engine.redis, matched.user_id, pickup_lat, pickup_lng
            )
            if eta:
                eta_data["eta_minutes"] = eta.eta_minutes
                eta_data["driver_lat"] = eta.driver_lat
                eta_data["driver_lng"] = eta.driver_lng
        except Exception:
            pass  # ETA is best-effort on match notification

        await notify_ride_status(rider_user_id, ride_id, "matched", **eta_data)

        # Send SMS/email notification
        from app.services.notification_events import notify_ride_matched
        await notify_ride_matched(
            db, rider_id=rider_user_id, ride_id=ride_id,
            eta_minutes=eta_data.get("eta_minutes"),
        )

        from app.services.audit_events import audit_ride_matched
        await audit_ride_matched(
            db, ride_id=ride_id, driver_id=matched.user_id, rider_id=rider_user_id,
        )


@router.post("/schedule", response_model=RideResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(_ride_request_limit)])
async def schedule_ride(
    req: ScheduleRideRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Schedule a ride for a future time."""
    # Validate the schedule time
    validation = validate_schedule_time(req.scheduled_for)
    if not validation.valid:
        raise HTTPException(status_code=422, detail=validation.reason)

    # Check for overlapping scheduled rides by this rider
    existing_q = await db.execute(
        select(Ride.scheduled_for).where(
            Ride.rider_id == user.id,
            Ride.status == RideStatus.SCHEDULED,
            Ride.scheduled_for.isnot(None),
        )
    )
    existing_times = [row[0] for row in existing_q.all()]
    overlap = check_overlap(req.scheduled_for, existing_times)
    if not overlap.valid:
        raise HTTPException(status_code=409, detail=overlap.reason)

    # Validate locations are within service area
    geo_check = await validate_ride_locations(
        db, req.pickup.lat, req.pickup.lng, req.dropoff.lat, req.dropoff.lng
    )
    if not geo_check["valid"]:
        raise HTTPException(status_code=422, detail=geo_check["message"])

    # Get route and fare estimate
    try:
        route = await get_route(req.pickup.lat, req.pickup.lng, req.dropoff.lat, req.dropoff.lng)
    except RoutingError as e:
        raise HTTPException(status_code=422, detail=str(e))

    fare = calculate_fare(route["distance_km"], route["duration_min"])

    ride = Ride(
        rider_id=user.id,
        status=RideStatus.SCHEDULED,
        pickup_location=ST_MakePoint(req.pickup.lng, req.pickup.lat, 4326),
        dropoff_location=ST_MakePoint(req.dropoff.lng, req.dropoff.lat, 4326),
        pickup_address=req.pickup_address,
        dropoff_address=req.dropoff_address,
        estimated_fare=round(fare, 2),
        distance_km=round(route["distance_km"], 2),
        duration_min=round(route["duration_min"], 1),
        scheduled_for=req.scheduled_for,
        accessibility_required=req.accessibility_required,
    )
    db.add(ride)
    await db.commit()
    await db.refresh(ride)

    return RideResponse(
        id=ride.id,
        status=ride.status.value,
        pickup_address=ride.pickup_address,
        dropoff_address=ride.dropoff_address,
        estimated_fare=ride.estimated_fare,
        scheduled_for=ride.scheduled_for,
        requested_at=ride.requested_at,
    )


@router.get("/scheduled", response_model=list[RideResponse])
async def list_scheduled_rides(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all upcoming scheduled rides for the current user."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Ride).where(
            Ride.rider_id == user.id,
            Ride.status == RideStatus.SCHEDULED,
            Ride.scheduled_for > now,
        ).order_by(Ride.scheduled_for.asc())
    )
    rides = result.scalars().all()
    return [
        RideResponse(
            id=r.id,
            status=r.status.value,
            pickup_address=r.pickup_address,
            dropoff_address=r.dropoff_address,
            estimated_fare=r.estimated_fare,
            scheduled_for=r.scheduled_for,
            requested_at=r.requested_at,
        )
        for r in rides
    ]


@router.delete("/scheduled/{ride_id}", status_code=status.HTTP_200_OK)
async def cancel_scheduled_ride(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a scheduled ride (always free — no driver has been matched)."""
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.rider_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if ride.status != RideStatus.SCHEDULED:
        raise HTTPException(status_code=409, detail="Only scheduled rides can be cancelled this way")

    ride.status = RideStatus.CANCELLED
    ride.cancelled_at = datetime.now(timezone.utc)
    ride.cancellation_reason = "Cancelled by rider before dispatch"
    await db.commit()

    return {"status": "cancelled", "cancellation_fee": 0.0}


@router.get("/history", response_model=list[RideResponse])
async def ride_history(
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import or_

    query = select(Ride).where(
        or_(Ride.rider_id == user.id, Ride.driver_id == user.id)
    )
    if status:
        query = query.where(Ride.status == RideStatus(status))
    query = query.order_by(Ride.requested_at.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    rides = result.scalars().all()
    return [
        RideResponse(
            id=r.id,
            status=r.status.value,
            pickup_address=r.pickup_address,
            dropoff_address=r.dropoff_address,
            estimated_fare=r.estimated_fare,
            actual_fare=r.actual_fare,
            scheduled_for=r.scheduled_for,
            requested_at=r.requested_at,
            matched_at=r.matched_at,
            started_at=r.started_at,
            completed_at=r.completed_at,
        )
        for r in rides
    ]


@router.get("/{ride_id}", response_model=RideResponse)
async def get_ride(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.rider_id != user.id and ride.driver_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    return RideResponse(
        id=ride.id,
        status=ride.status.value,
        pickup_address=ride.pickup_address,
        dropoff_address=ride.dropoff_address,
        estimated_fare=ride.estimated_fare,
        actual_fare=ride.actual_fare,
        scheduled_for=ride.scheduled_for,
        requested_at=ride.requested_at,
        matched_at=ride.matched_at,
        started_at=ride.started_at,
        completed_at=ride.completed_at,
    )


@router.get("/{ride_id}/eta", response_model=DriverETAResponse)
async def get_driver_eta(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current ETA for the matched driver to reach the pickup.

    Available when ride status is MATCHED, DRIVER_EN_ROUTE, or ARRIVED.
    Both the rider and the assigned driver can query this endpoint.
    """
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.rider_id != user.id and ride.driver_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if ride.status not in (
        RideStatus.MATCHED,
        RideStatus.DRIVER_EN_ROUTE,
        RideStatus.ARRIVED,
    ):
        raise HTTPException(
            status_code=409,
            detail="ETA is only available when a driver has been matched",
        )

    if not ride.driver_id:
        raise HTTPException(status_code=409, detail="No driver assigned")

    from app.services.eta import estimate_driver_eta
    from geoalchemy2.functions import ST_X, ST_Y

    # Extract pickup coordinates from PostGIS point
    coord_result = await db.execute(
        select(
            ST_Y(Ride.pickup_location).label("lat"),
            ST_X(Ride.pickup_location).label("lng"),
        ).where(Ride.id == ride_id)
    )
    coords = coord_result.one()
    pickup_lat, pickup_lng = float(coords.lat), float(coords.lng)

    try:
        redis_client = await get_redis()
        eta = await estimate_driver_eta(
            redis_client, ride.driver_id, pickup_lat, pickup_lng
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="ETA service temporarily unavailable",
        )

    if eta is None:
        raise HTTPException(
            status_code=404,
            detail="Driver location not available",
        )

    return DriverETAResponse(
        eta_minutes=eta.eta_minutes,
        distance_km=eta.distance_km,
        driver_location=DriverLocationResponse(
            lat=eta.driver_lat, lng=eta.driver_lng
        ),
        source=eta.source,
    )


@router.get("/{ride_id}/trip-eta", response_model=TripETAResponse)
async def get_trip_eta(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the full trip ETA: driver→pickup + pickup→dropoff.

    Available when ride status is MATCHED or DRIVER_EN_ROUTE.
    """
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.rider_id != user.id and ride.driver_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if ride.status not in (RideStatus.MATCHED, RideStatus.DRIVER_EN_ROUTE):
        raise HTTPException(
            status_code=409,
            detail="Trip ETA is only available when a driver is en route or matched",
        )

    if not ride.driver_id:
        raise HTTPException(status_code=409, detail="No driver assigned")

    from app.services.eta import estimate_trip_eta
    from geoalchemy2.functions import ST_X, ST_Y

    coord_result = await db.execute(
        select(
            ST_Y(Ride.pickup_location).label("plat"),
            ST_X(Ride.pickup_location).label("plng"),
            ST_Y(Ride.dropoff_location).label("dlat"),
            ST_X(Ride.dropoff_location).label("dlng"),
        ).where(Ride.id == ride_id)
    )
    coords = coord_result.one()
    pickup_lat, pickup_lng = float(coords.plat), float(coords.plng)
    dropoff_lat, dropoff_lng = float(coords.dlat), float(coords.dlng)

    try:
        redis_client = await get_redis()
        trip_eta = await estimate_trip_eta(
            redis_client,
            ride.driver_id,
            pickup_lat,
            pickup_lng,
            dropoff_lat,
            dropoff_lng,
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="ETA service temporarily unavailable",
        )

    if trip_eta is None:
        raise HTTPException(
            status_code=404,
            detail="Driver location not available",
        )

    return TripETAResponse(
        pickup_eta_minutes=trip_eta.pickup_eta_minutes,
        pickup_distance_km=trip_eta.pickup_distance_km,
        trip_duration_minutes=trip_eta.trip_duration_minutes,
        trip_distance_km=trip_eta.trip_distance_km,
        total_minutes=trip_eta.total_minutes,
        driver_location=DriverLocationResponse(
            lat=trip_eta.driver_lat, lng=trip_eta.driver_lng
        ),
        source=trip_eta.source,
    )


@router.post("/{ride_id}/accept", response_model=RideResponse)
async def accept_ride(
    ride_id: int,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.status != RideStatus.REQUESTED:
        raise HTTPException(status_code=409, detail="Ride is no longer available")

    ride.driver_id = driver.id
    ride.driver_id = driver.id
    ride.status = RideStatus.MATCHED
    ride.matched_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(ride)

    engine = await get_matching_engine()
    await engine.set_driver_busy(driver.id)

    from app.api.websocket import notify_ride_status
    await notify_ride_status(ride.rider_id, ride.id, "matched")

    from app.services.notification_events import notify_ride_matched
    await notify_ride_matched(db, rider_id=ride.rider_id, ride_id=ride.id)

    return RideResponse(
        id=ride.id,
        status=ride.status.value,
        pickup_address=ride.pickup_address,
        dropoff_address=ride.dropoff_address,
        estimated_fare=ride.estimated_fare,
        requested_at=ride.requested_at,
        matched_at=ride.matched_at,
    )


@router.post("/{ride_id}/en-route")
async def driver_en_route(
    ride_id: int,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride or ride.driver_id != driver.id:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.status != RideStatus.MATCHED:
        raise HTTPException(status_code=409, detail="Can only go en-route from matched state")

    ride.status = RideStatus.DRIVER_EN_ROUTE
    await db.commit()

    from app.api.websocket import notify_ride_status

    # Include ETA in the en-route notification
    eta_extras: dict = {}
    try:
        from app.services.eta import estimate_driver_eta
        from geoalchemy2.functions import ST_X, ST_Y

        coord_result = await db.execute(
            select(
                ST_Y(Ride.pickup_location).label("lat"),
                ST_X(Ride.pickup_location).label("lng"),
            ).where(Ride.id == ride_id)
        )
        coords = coord_result.one()
        redis_client = await get_redis()
        eta = await estimate_driver_eta(
            redis_client, driver.id, float(coords.lat), float(coords.lng)
        )
        if eta:
            eta_extras["eta_minutes"] = eta.eta_minutes
            eta_extras["driver_distance_km"] = eta.distance_km
            eta_extras["driver_lat"] = eta.driver_lat
            eta_extras["driver_lng"] = eta.driver_lng
    except Exception:
        pass  # ETA is best-effort

    await notify_ride_status(ride.rider_id, ride.id, "driver_en_route", **eta_extras)

    from app.services.notification_events import notify_driver_en_route
    await notify_driver_en_route(
        db, rider_id=ride.rider_id, ride_id=ride.id,
        eta_minutes=eta_extras.get("eta_minutes"),
    )

    return {"status": "driver_en_route"}


@router.post("/{ride_id}/arrived")
async def driver_arrived(
    ride_id: int,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride or ride.driver_id != driver.id:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.status != RideStatus.DRIVER_EN_ROUTE:
        raise HTTPException(status_code=409, detail="Must be en-route before arriving")

    ride.status = RideStatus.ARRIVED
    await db.commit()

    from app.api.websocket import notify_ride_status
    await notify_ride_status(ride.rider_id, ride.id, "arrived")

    from app.services.notification_events import notify_driver_arrived
    await notify_driver_arrived(db, rider_id=ride.rider_id, ride_id=ride.id)

    return {"status": "arrived"}


@router.post("/{ride_id}/start")
async def start_ride(
    ride_id: int,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride or ride.driver_id != driver.id:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.status not in (RideStatus.MATCHED, RideStatus.ARRIVED):
        raise HTTPException(status_code=409, detail="Cannot start ride in current state")

    ride.status = RideStatus.IN_PROGRESS
    ride.started_at = datetime.now(timezone.utc)
    await db.commit()

    from app.api.websocket import notify_ride_status
    await notify_ride_status(ride.rider_id, ride.id, "in_progress")

    return {"status": "in_progress"}


@router.post("/{ride_id}/complete")
async def complete_ride(
    ride_id: int,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride or ride.driver_id != driver.id:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.status != RideStatus.IN_PROGRESS:
        raise HTTPException(status_code=409, detail="Ride is not in progress")

    ride.status = RideStatus.COMPLETED
    ride.completed_at = datetime.now(timezone.utc)
    ride.actual_fare = ride.estimated_fare

    # Increment driver's total_trips
    profile_result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == driver.id)
    )
    profile = profile_result.scalar_one_or_none()
    if profile:
        profile.total_trips += 1

    await db.commit()

    engine = await get_matching_engine()
    await engine.set_driver_available(driver.id)

    from app.api.websocket import notify_ride_status
    await notify_ride_status(ride.rider_id, ride.id, "completed", fare=ride.actual_fare)

    from app.services.notification_events import notify_ride_completed
    await notify_ride_completed(db, rider_id=ride.rider_id, ride_id=ride.id, fare=ride.actual_fare)

    from app.services.audit_events import audit_ride_completed
    await audit_ride_completed(
        db, ride_id=ride.id, driver_id=driver.id,
        rider_id=ride.rider_id, fare=ride.actual_fare,
    )

    return {"status": "completed", "fare": ride.actual_fare}


@router.post("/{ride_id}/cancel", response_model=CancelResponse)
async def cancel_ride(
    ride_id: int,
    req: CancelRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.rider_id != user.id and ride.driver_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    cancelled_by = "rider" if user.id == ride.rider_id else "driver"
    was_retrying = ride.status == RideStatus.REQUESTED and ride.dispatch_retry_count > 0
    policy = evaluate_cancellation(
        ride_status=ride.status,
        cancelled_by=cancelled_by,
        estimated_fare=ride.estimated_fare,
        matched_at=ride.matched_at,
        dispatch_retry_count=ride.dispatch_retry_count,
    )

    if not policy.allowed:
        raise HTTPException(status_code=409, detail=policy.reason)

    ride.status = RideStatus.CANCELLED
    ride.cancelled_at = datetime.now(timezone.utc)
    ride.cancellation_reason = req.reason
    await db.commit()

    from app.api.websocket import notify_ride_status
    cancel_extra: dict = {}
    if was_retrying:
        cancel_extra["cancelled_during_retry"] = True
        cancel_extra["retry_attempt"] = ride.dispatch_retry_count
    if ride.driver_id:
        engine = await get_matching_engine()
        await engine.set_driver_available(ride.driver_id)
        await notify_ride_status(ride.driver_id, ride.id, "cancelled", **cancel_extra)
    if user.id != ride.rider_id:
        await notify_ride_status(ride.rider_id, ride.id, "cancelled", **cancel_extra)

    # Send SMS/email cancellation notifications
    from app.services.notification_events import notify_ride_cancelled
    if ride.driver_id and user.id != ride.driver_id:
        await notify_ride_cancelled(db, user_id=ride.driver_id, ride_id=ride.id, cancelled_by=cancelled_by)
    if user.id != ride.rider_id:
        await notify_ride_cancelled(db, user_id=ride.rider_id, ride_id=ride.id, cancelled_by=cancelled_by)

    from app.services.audit_events import audit_ride_cancelled
    await audit_ride_cancelled(
        db, ride_id=ride.id, cancelled_by=user.id,
        role=cancelled_by, reason=req.reason,
    )

    # Create a payment intent for the cancellation fee if applicable
    payment_result: dict = {}
    if policy.fee > 0:
        try:
            payment_result = await create_cancellation_payment_intent(
                ride_id=ride.id,
                rider_id=ride.rider_id,
                driver_id=ride.driver_id,
                cancellation_fee=policy.fee,
                db=db,
            )
        except Exception:
            # Payment creation failed — ride is still cancelled, fee is owed
            # but we can't charge right now. Log and return fee info without payment.
            import logging
            logging.getLogger(__name__).error(
                "Failed to create cancellation payment intent for ride %d", ride.id, exc_info=True,
            )

    return CancelResponse(
        status="cancelled",
        cancellation_fee=policy.fee,
        fee_reason=policy.reason,
        payment_required=payment_result.get("payment_required", False),
        payment_intent_client_secret=payment_result.get("client_secret"),
        payment_intent_id=payment_result.get("payment_intent_id"),
    )


@router.post("/{ride_id}/rate")
async def rate_ride(
    ride_id: int,
    req: RideRatingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride or ride.status != RideStatus.COMPLETED:
        raise HTTPException(status_code=404, detail="Completed ride not found")

    if user.id == ride.rider_id:
        ride.driver_rating = req.rating
        ride.tip_amount = req.tip_amount

        if ride.driver_id:
            from app.services.ratings import update_driver_rating_avg
            await update_driver_rating_avg(ride.driver_id, db)

    elif user.id == ride.driver_id:
        ride.rider_rating = req.rating
    else:
        raise HTTPException(status_code=403, detail="Not authorized")

    await db.commit()

    # Notify the rated user
    from app.services.notification_events import notify_rating_received
    rated_user_id = ride.driver_id if user.id == ride.rider_id else ride.rider_id
    if rated_user_id:
        await notify_rating_received(db, user_id=rated_user_id, ride_id=ride.id, rating=req.rating)

    return {"status": "rated"}


@router.get("/{ride_id}/receipt", response_model=RideReceiptResponse)
async def get_receipt(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a detailed receipt for a completed ride."""
    from app.services.receipts import generate_receipt

    receipt = await generate_receipt(ride_id, user.id, db)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not available — ride not found or not completed")
    return RideReceiptResponse(**receipt)


@router.post("/{ride_id}/feedback", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    ride_id: int,
    req: FeedbackCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit feedback for a completed ride (rider or driver)."""
    from app.services.feedback import submit_feedback as _submit

    # Determine role
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    if user.id == ride.rider_id:
        role = "rider"
    elif user.id == ride.driver_id:
        role = "driver"
    else:
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        feedback = await _submit(
            ride_id=ride_id,
            user_id=user.id,
            role=role,
            rating=req.rating,
            comment=req.comment,
            categories=req.categories,
            tip_amount=req.tip_amount,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    return FeedbackResponse(
        id=feedback.id,
        ride_id=feedback.ride_id,
        user_id=feedback.user_id,
        role=feedback.role,
        rating=feedback.rating,
        comment=feedback.comment,
        categories=feedback.categories.split(",") if feedback.categories else None,
        created_at=feedback.created_at,
    )


@router.get("/{ride_id}/feedback", response_model=list[FeedbackResponse])
async def get_ride_feedback(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all feedback for a ride. Only ride participants can view."""
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.rider_id != user.id and ride.driver_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    from app.services.feedback import get_ride_feedback as _get_feedback

    items = await _get_feedback(ride_id, db)
    return [
        FeedbackResponse(
            id=f.id,
            ride_id=f.ride_id,
            user_id=f.user_id,
            role=f.role,
            rating=f.rating,
            comment=f.comment,
            categories=f.categories.split(",") if f.categories else None,
            created_at=f.created_at,
        )
        for f in items
    ]


@router.post("/{ride_id}/dispute", response_model=DisputeResponse, status_code=status.HTTP_201_CREATED)
async def file_dispute(
    ride_id: int,
    req: DisputeCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """File a dispute on a completed or cancelled ride."""
    from app.services.disputes import file_dispute as _file

    try:
        dispute = await _file(
            ride_id=ride_id,
            user_id=user.id,
            dispute_type=req.dispute_type,
            description=req.description,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    from app.services.audit_events import audit_dispute_filed
    await audit_dispute_filed(
        db, dispute_id=dispute.id, ride_id=ride_id,
        filed_by=user.id, dispute_type=dispute.dispute_type.value,
    )

    return DisputeResponse(
        id=dispute.id,
        ride_id=dispute.ride_id,
        filed_by=dispute.filed_by,
        dispute_type=dispute.dispute_type.value,
        status=dispute.status.value,
        description=dispute.description,
        resolution_notes=dispute.resolution_notes,
        resolved_by=dispute.resolved_by,
        refund_amount=dispute.refund_amount,
        created_at=dispute.created_at,
        updated_at=dispute.updated_at,
        resolved_at=dispute.resolved_at,
    )


@router.get("/{ride_id}/disputes", response_model=list[DisputeResponse])
async def get_ride_disputes(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get disputes for a ride. Only ride participants can view."""
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.rider_id != user.id and ride.driver_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    from app.services.disputes import list_disputes

    # Get all disputes for this ride (no status filter, no pagination — ride-scoped)
    from app.models.feedback import Dispute
    disp_result = await db.execute(
        select(Dispute).where(Dispute.ride_id == ride_id).order_by(Dispute.created_at.desc())
    )
    disputes = disp_result.scalars().all()

    return [
        DisputeResponse(
            id=d.id,
            ride_id=d.ride_id,
            filed_by=d.filed_by,
            dispute_type=d.dispute_type.value,
            status=d.status.value,
            description=d.description,
            resolution_notes=d.resolution_notes,
            resolved_by=d.resolved_by,
            refund_amount=d.refund_amount,
            created_at=d.created_at,
            updated_at=d.updated_at,
            resolved_at=d.resolved_at,
        )
        for d in disputes
    ]


@router.post("/geocode", response_model=GeocodeResponse)
async def geocode_address(
    req: GeocodeRequest,
    _user: User = Depends(get_current_user),
):
    try:
        result = await geocode(req.address)
    except GeocodingError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return GeocodeResponse(**result)


@router.post("/reverse-geocode", response_model=ReverseGeocodeResponse)
async def reverse_geocode_location(
    req: ReverseGeocodeRequest,
    _user: User = Depends(get_current_user),
):
    try:
        result = await reverse_geocode(req.lat, req.lng)
    except GeocodingError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return ReverseGeocodeResponse(
        display_name=result["display_name"],
        short_address=result["short_address"],
    )
