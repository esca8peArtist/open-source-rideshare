"""Rider-submits-driver-rating endpoints.

POST /rides/{ride_id}/driver-rating  — rider rates their driver after a completed ride
GET  /rides/{ride_id}/driver-rating  — rider retrieves their submitted rating
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_rider
from app.models.user import User
from app.schemas.driver_rating_submit import DriverRatingCreate, DriverRatingResponse
from app.services.driver_rating_submit import (
    DriverRatingError,
    get_driver_rating_for_ride,
    submit_driver_rating,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["driver-ratings"])


def _to_response(feedback) -> DriverRatingResponse:
    return DriverRatingResponse(
        id=feedback.id,
        ride_id=feedback.ride_id,
        rider_id=feedback.user_id,
        rating=feedback.rating,
        comment=feedback.comment,
        submitted_at=feedback.created_at,
    )


@router.post(
    "/rides/{ride_id}/driver-rating",
    response_model=DriverRatingResponse,
    status_code=201,
    summary="Rate your driver",
    description=(
        "Submit a 1–5 star rating for the driver on a completed ride. "
        "One rating per ride. Only the rider who took the ride may submit."
    ),
)
async def submit_rating(
    ride_id: int,
    req: DriverRatingCreate,
    rider: User = Depends(require_rider),
    db: AsyncSession = Depends(get_db),
) -> DriverRatingResponse:
    try:
        feedback = await submit_driver_rating(
            db,
            ride_id=ride_id,
            rider_user_id=rider.id,
            rating=req.rating,
            comment=req.comment,
        )
    except DriverRatingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return _to_response(feedback)


@router.get(
    "/rides/{ride_id}/driver-rating",
    response_model=DriverRatingResponse,
    summary="Get your driver rating for a ride",
    description="Retrieve the rating you submitted for the driver on a specific ride.",
)
async def get_rating(
    ride_id: int,
    rider: User = Depends(require_rider),
    db: AsyncSession = Depends(get_db),
) -> DriverRatingResponse:
    feedback = await get_driver_rating_for_ride(db, ride_id=ride_id, rider_user_id=rider.id)
    if not feedback:
        raise HTTPException(status_code=404, detail="No driver rating submitted for this ride")
    return _to_response(feedback)
