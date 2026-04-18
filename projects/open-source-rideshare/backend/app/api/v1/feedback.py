"""Ride feedback endpoints.

POST  /rides/{ride_id}/feedback           — submit feedback (rider or driver)
GET   /rides/{ride_id}/feedback           — list feedback for a ride
GET   /me/feedback                        — list my submitted feedback (paginated)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.feedback import FeedbackCreate, FeedbackListResponse, FeedbackResponse
from app.services.feedback import get_ride_feedback, get_user_feedback, submit_feedback

router = APIRouter(tags=["feedback"])


def _parse_categories(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [c for c in raw.split(",") if c]


def _feedback_response(fb) -> FeedbackResponse:
    return FeedbackResponse(
        id=fb.id,
        ride_id=fb.ride_id,
        user_id=fb.user_id,
        role=fb.role,
        rating=fb.rating,
        comment=fb.comment,
        categories=_parse_categories(fb.categories),
        created_at=fb.created_at,
    )


@router.post(
    "/rides/{ride_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit feedback for a completed ride",
)
async def post_feedback(
    ride_id: int,
    body: FeedbackCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    """Submit a 1–5 star rating with optional comment and issue categories.

    Role is inferred from the caller's account type (rider or driver).
    Admins may not submit feedback. The ride must be COMPLETED and the caller
    must be a participant. One feedback submission per participant per ride.
    """
    role = user.role.value
    if role not in ("rider", "driver"):
        raise HTTPException(status_code=403, detail="Only riders and drivers can submit feedback")

    try:
        fb = await submit_feedback(
            ride_id=ride_id,
            user_id=user.id,
            role=role,
            rating=body.rating,
            comment=body.comment,
            categories=body.categories,
            tip_amount=body.tip_amount,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    return _feedback_response(fb)


@router.get(
    "/rides/{ride_id}/feedback",
    response_model=FeedbackListResponse,
    summary="List feedback for a ride",
)
async def get_ride_feedback_endpoint(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeedbackListResponse:
    """Return all feedback entries for a ride.

    Accessible to admin, or to the rider/driver who participated in the ride.
    """
    from sqlalchemy import select
    from app.models.ride import Ride

    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    role = user.role.value
    if role != "admin" and ride.rider_id != user.id and ride.driver_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this ride's feedback")

    items = await get_ride_feedback(ride_id, db)
    return FeedbackListResponse(
        feedback=[_feedback_response(fb) for fb in items],
        total=len(items),
    )


@router.get(
    "/me/feedback",
    response_model=FeedbackListResponse,
    summary="List my submitted feedback",
)
async def get_my_feedback(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeedbackListResponse:
    """Paginated list of all feedback the caller has submitted."""
    items, total = await get_user_feedback(
        user_id=user.id,
        role=None,
        db=db,
        limit=limit,
        offset=offset,
    )
    return FeedbackListResponse(
        feedback=[_feedback_response(fb) for fb in items],
        total=total,
    )
