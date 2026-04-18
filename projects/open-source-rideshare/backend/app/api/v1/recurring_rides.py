"""API endpoints for recurring rides.

Allows riders to create, manage, and cancel recurring ride schedules
(e.g. daily commute). The system auto-generates individual scheduled
rides from active templates.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.ride import RideStatus
from app.models.user import User
from app.schemas.recurring_ride import (
    GeneratedRideSummary,
    RecurringRideCreate,
    RecurringRideDetailResponse,
    RecurringRideListResponse,
    RecurringRideResponse,
    RecurringRideSkipCreate,
    RecurringRideSkipResponse,
    RecurringRideUpdate,
)
from app.services.recurring_rides import (
    RecurringRideLimitError,
    RecurringRideNotFoundError,
    RecurringRideSkipError,
    RecurringRideStateError,
    cancel_recurring_ride,
    create_recurring_ride,
    get_recurring_ride,
    get_upcoming_generated_rides,
    list_recurring_rides,
    list_skipped_dates,
    pause_recurring_ride,
    resume_recurring_ride,
    skip_occurrence,
    unskip_occurrence,
    update_recurring_ride,
)

router = APIRouter(prefix="/rides/recurring", tags=["recurring-rides"])


@router.post("", response_model=RecurringRideResponse, status_code=status.HTTP_201_CREATED)
async def create(
    body: RecurringRideCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new recurring ride schedule."""
    try:
        ride = await create_recurring_ride(
            rider_id=user.id,
            pickup_lat=body.pickup.lat,
            pickup_lng=body.pickup.lng,
            dropoff_lat=body.dropoff.lat,
            dropoff_lng=body.dropoff.lng,
            pickup_address=body.pickup_address,
            dropoff_address=body.dropoff_address,
            days_of_week=body.days_of_week,
            pickup_time=body.pickup_time,
            tz=body.timezone,
            db=db,
            accessibility_required=body.accessibility_required,
            label=body.label,
            pickup_saved_location_id=body.pickup_saved_location_id,
            dropoff_saved_location_id=body.dropoff_saved_location_id,
        )
    except RecurringRideLimitError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return ride


@router.get("", response_model=RecurringRideListResponse)
async def list_mine(
    include_cancelled: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all my recurring rides."""
    rides = await list_recurring_rides(user.id, db, include_cancelled=include_cancelled)
    return RecurringRideListResponse(recurring_rides=rides, total=len(rides))


@router.get("/{recurring_ride_id}", response_model=RecurringRideDetailResponse)
async def get_detail(
    recurring_ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a recurring ride with upcoming generated rides."""
    try:
        ride = await get_recurring_ride(recurring_ride_id, user.id, db)
    except RecurringRideNotFoundError:
        raise HTTPException(status_code=404, detail="Recurring ride not found")

    upcoming = await get_upcoming_generated_rides(recurring_ride_id, db)
    upcoming_summaries = [
        GeneratedRideSummary(
            ride_id=r.id,
            status=r.status.value,
            scheduled_for=r.scheduled_for,
        )
        for r in upcoming
    ]
    skipped = await list_skipped_dates(recurring_ride_id, user.id, db)

    return RecurringRideDetailResponse(
        id=ride.id,
        rider_id=ride.rider_id,
        pickup_address=ride.pickup_address,
        dropoff_address=ride.dropoff_address,
        days_of_week=ride.days_of_week,
        pickup_time=ride.pickup_time,
        timezone=ride.timezone,
        accessibility_required=ride.accessibility_required,
        status=ride.status.value,
        label=ride.label,
        last_generated_date=ride.last_generated_date,
        created_at=ride.created_at,
        updated_at=ride.updated_at,
        upcoming_rides=upcoming_summaries,
        skipped_dates=skipped,
    )


@router.patch("/{recurring_ride_id}", response_model=RecurringRideResponse)
async def update(
    recurring_ride_id: int,
    body: RecurringRideUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a recurring ride schedule."""
    try:
        ride = await update_recurring_ride(
            recurring_ride_id,
            user.id,
            db,
            pickup_lat=body.pickup.lat if body.pickup else None,
            pickup_lng=body.pickup.lng if body.pickup else None,
            dropoff_lat=body.dropoff.lat if body.dropoff else None,
            dropoff_lng=body.dropoff.lng if body.dropoff else None,
            pickup_address=body.pickup_address,
            dropoff_address=body.dropoff_address,
            days_of_week=body.days_of_week,
            pickup_time=body.pickup_time,
            tz=body.timezone,
            accessibility_required=body.accessibility_required,
            label=body.label,
            pickup_saved_location_id=body.pickup_saved_location_id,
            dropoff_saved_location_id=body.dropoff_saved_location_id,
        )
    except RecurringRideNotFoundError:
        raise HTTPException(status_code=404, detail="Recurring ride not found")
    except RecurringRideStateError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return ride


@router.post("/{recurring_ride_id}/pause", response_model=RecurringRideResponse)
async def pause(
    recurring_ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pause a recurring ride (stops generating new rides)."""
    try:
        ride = await pause_recurring_ride(recurring_ride_id, user.id, db)
    except RecurringRideNotFoundError:
        raise HTTPException(status_code=404, detail="Recurring ride not found")
    except RecurringRideStateError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return ride


@router.post("/{recurring_ride_id}/resume", response_model=RecurringRideResponse)
async def resume(
    recurring_ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused recurring ride."""
    try:
        ride = await resume_recurring_ride(recurring_ride_id, user.id, db)
    except RecurringRideNotFoundError:
        raise HTTPException(status_code=404, detail="Recurring ride not found")
    except RecurringRideStateError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return ride


@router.delete("/{recurring_ride_id}", response_model=RecurringRideResponse)
async def cancel(
    recurring_ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a recurring ride permanently."""
    try:
        ride = await cancel_recurring_ride(recurring_ride_id, user.id, db)
    except RecurringRideNotFoundError:
        raise HTTPException(status_code=404, detail="Recurring ride not found")
    except RecurringRideStateError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return ride


@router.post("/{recurring_ride_id}/skip", response_model=RecurringRideSkipResponse, status_code=status.HTTP_201_CREATED)
async def skip(
    recurring_ride_id: int,
    body: RecurringRideSkipCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Skip a single upcoming occurrence of a recurring ride.

    The skip_date must fall on a scheduled day of the week and must be in
    the future. If a SCHEDULED ride has already been generated for that
    occurrence it will be cancelled automatically.
    """
    try:
        skip_record = await skip_occurrence(recurring_ride_id, user.id, body.skip_date, db)
    except RecurringRideNotFoundError:
        raise HTTPException(status_code=404, detail="Recurring ride not found")
    except RecurringRideStateError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except RecurringRideSkipError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    return skip_record


@router.delete("/{recurring_ride_id}/skip/{skip_date}", status_code=status.HTTP_204_NO_CONTENT)
async def unskip(
    recurring_ride_id: int,
    skip_date: date,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a previously recorded skip, allowing the occurrence to be generated again."""
    try:
        await unskip_occurrence(recurring_ride_id, user.id, skip_date, db)
    except RecurringRideNotFoundError:
        raise HTTPException(status_code=404, detail="Recurring ride not found")
    except RecurringRideSkipError as e:
        raise HTTPException(status_code=404, detail=str(e))
