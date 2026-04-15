"""Ride feedback endpoints.

Dedicated router for post-ride feedback submission and retrieval. Complements
the inline feedback endpoints on the rides router by adding user-level history
and admin views.

Endpoints:
  POST /rides/{ride_id}/feedback            — rider or driver submits feedback
  GET  /rides/{ride_id}/feedback/mine       — current user's feedback on this ride
  GET  /riders/me/feedback                  — paginated history for current rider
  GET  /drivers/me/feedback                 — paginated history for current driver
  GET  /admin/feedback                      — admin: all feedback (filterable)
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.ride import Ride
from app.models.user import User
from app.schemas.feedback import (
    FeedbackPaginatedResponse,
    FeedbackResponse,
    SubmitFeedbackRequest,
)
from app.services.feedback import (
    get_ride_feedback,
    get_user_feedback,
    submit_feedback as _submit_feedback,
)

router = APIRouter(tags=["ride-feedback"])


def _to_response(fb) -> FeedbackResponse:
    """Convert a RideFeedback ORM object to a FeedbackResponse schema."""
    return FeedbackResponse(
        id=fb.id,
        ride_id=fb.ride_id,
        user_id=fb.user_id,
        role=fb.role,
        rating=fb.rating,
        comment=fb.comment,
        categories=fb.categories.split(",") if fb.categories else None,
        created_at=fb.created_at,
    )


# ---------------------------------------------------------------------------
# POST /rides/{ride_id}/feedback
# ---------------------------------------------------------------------------


@router.post(
    "/rides/{ride_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit feedback for a completed ride",
)
async def post_ride_feedback(
    ride_id: int,
    req: SubmitFeedbackRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a rating, optional comment, and optional issue categories for a
    completed ride.

    Role is inferred automatically: if the authenticated user is the rider they
    submit rider feedback; if they are the driver they submit driver feedback.
    Returns 403 if the user is neither participant, 400/409 if feedback has
    already been submitted or the ride is not completed.
    """
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found")

    if user.id == ride.rider_id:
        role = "rider"
    elif user.id == ride.driver_id:
        role = "driver"
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant on this ride")

    try:
        feedback = await _submit_feedback(
            ride_id=ride_id,
            user_id=user.id,
            role=role,
            rating=req.rating,
            comment=req.comment,
            categories=req.categories,
            tip_amount=req.tip_amount,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    return _to_response(feedback)


# ---------------------------------------------------------------------------
# GET /rides/{ride_id}/feedback/mine
# ---------------------------------------------------------------------------


@router.get(
    "/rides/{ride_id}/feedback/mine",
    response_model=FeedbackResponse,
    summary="Get my own feedback for a specific ride",
)
async def get_my_ride_feedback(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current user's feedback entry for the given ride.

    Returns 404 if the ride does not exist, if the user has not submitted
    feedback yet, or if the user was not a participant.
    """
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found")

    all_feedback = await get_ride_feedback(ride_id, db)
    user_feedback = [fb for fb in all_feedback if fb.user_id == user.id]
    if not user_feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No feedback found for this user on this ride",
        )
    return _to_response(user_feedback[0])


# ---------------------------------------------------------------------------
# GET /riders/me/feedback
# ---------------------------------------------------------------------------


@router.get(
    "/riders/me/feedback",
    response_model=FeedbackPaginatedResponse,
    summary="Paginated feedback history for the current rider",
)
async def list_rider_feedback(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all feedback submitted by the current rider, newest first."""
    items, total = await get_user_feedback(
        user_id=user.id,
        role="rider",
        db=db,
        limit=limit,
        offset=offset,
    )
    return FeedbackPaginatedResponse(
        items=[_to_response(fb) for fb in items],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /drivers/me/feedback
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/feedback",
    response_model=FeedbackPaginatedResponse,
    summary="Paginated feedback history for the current driver",
)
async def list_driver_feedback(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return all feedback submitted by the current driver, newest first."""
    items, total = await get_user_feedback(
        user_id=user.id,
        role="driver",
        db=db,
        limit=limit,
        offset=offset,
    )
    return FeedbackPaginatedResponse(
        items=[_to_response(fb) for fb in items],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /admin/feedback
# ---------------------------------------------------------------------------


@router.get(
    "/admin/feedback",
    response_model=FeedbackPaginatedResponse,
    summary="Admin: list all feedback with optional filters",
)
async def admin_list_feedback(
    ride_id: int | None = Query(default=None, description="Filter by ride ID"),
    user_id: int | None = Query(default=None, description="Filter by user ID"),
    role: str | None = Query(default=None, description="Filter by role: rider or driver"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all platform feedback. Filterable by ride_id, user_id, and role.

    Requires admin authentication.
    """
    from sqlalchemy import func
    from app.models.feedback import RideFeedback

    query = select(RideFeedback)
    if ride_id is not None:
        query = query.where(RideFeedback.ride_id == ride_id)
    if user_id is not None:
        query = query.where(RideFeedback.user_id == user_id)
    if role is not None:
        query = query.where(RideFeedback.role == role)

    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    query = query.order_by(RideFeedback.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return FeedbackPaginatedResponse(
        items=[_to_response(fb) for fb in items],
        total=total,
        limit=limit,
        offset=offset,
    )
