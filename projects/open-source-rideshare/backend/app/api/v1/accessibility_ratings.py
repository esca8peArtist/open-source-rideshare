"""Accessibility ratings API.

POST /rides/{ride_id}/accessibility-rating   — rider submits accommodation rating
GET  /rides/{ride_id}/accessibility-rating   — rider or admin views the rating
GET  /me/accessibility-ratings               — rider lists their own history
GET  /admin/accessibility-ratings/summary    — admin aggregate quality stats
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.user import User, UserRole
from app.schemas.accessibility_rating import (
    AccessibilityRatingCreate,
    AccessibilityRatingResponse,
    AccessibilityRatingSummary,
)
from app.services.accessibility_ratings import (
    get_accessibility_rating,
    get_admin_accommodation_summary,
    list_rider_accessibility_ratings,
    submit_accessibility_rating,
)

router = APIRouter(tags=["accessibility-ratings"])


@router.post(
    "/rides/{ride_id}/accessibility-rating",
    response_model=AccessibilityRatingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit accessibility accommodation rating",
    description=(
        "Rate how well your accessibility needs were accommodated on a completed ride. "
        "Only one rating per ride is permitted. The ride must be in COMPLETED status."
    ),
)
async def post_accessibility_rating(
    ride_id: int,
    body: AccessibilityRatingCreate,
    rider: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AccessibilityRatingResponse:
    try:
        record = await submit_accessibility_rating(
            db=db,
            ride_id=ride_id,
            rider_id=rider.id,
            rating=body.rating,
            accommodation_type=body.accommodation_type,
            comment=body.comment,
        )
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found.")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await db.commit()
    await db.refresh(record)
    return AccessibilityRatingResponse.model_validate(record)


@router.get(
    "/rides/{ride_id}/accessibility-rating",
    response_model=AccessibilityRatingResponse,
    summary="Get accessibility rating for a ride",
    description="Retrieve the accessibility rating the caller submitted for this ride.",
)
async def get_ride_accessibility_rating(
    ride_id: int,
    caller: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AccessibilityRatingResponse:
    if caller.role == UserRole.ADMIN:
        from sqlalchemy import select
        from app.models.accessibility_rating import AccessibilityRating

        result = await db.execute(
            select(AccessibilityRating).where(AccessibilityRating.ride_id == ride_id)
        )
        record = result.scalar_one_or_none()
    else:
        record = await get_accessibility_rating(db=db, ride_id=ride_id, rider_id=caller.id)

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Accessibility rating not found.",
        )
    return AccessibilityRatingResponse.model_validate(record)


@router.get(
    "/me/accessibility-ratings",
    response_model=list[AccessibilityRatingResponse],
    summary="List my accessibility ratings",
    description="Return the caller's accessibility accommodation ratings, newest first.",
)
async def list_my_accessibility_ratings(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    rider: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AccessibilityRatingResponse]:
    _, items = await list_rider_accessibility_ratings(
        db=db, rider_id=rider.id, limit=limit, offset=offset
    )
    return [AccessibilityRatingResponse.model_validate(r) for r in items]


@router.get(
    "/admin/accessibility-ratings/summary",
    response_model=AccessibilityRatingSummary,
    summary="Admin: accommodation quality summary",
    description=(
        "Aggregate accessibility rating stats across the platform, broken down "
        "by accommodation type. Admin access required."
    ),
)
async def admin_accessibility_summary(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AccessibilityRatingSummary:
    data = await get_admin_accommodation_summary(db=db)
    return AccessibilityRatingSummary(**data)
