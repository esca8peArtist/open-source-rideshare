"""Driver rating history endpoint.

GET /drivers/me/ratings
  Returns the authenticated driver's rating history along with aggregate
  statistics: lifetime average, per-star breakdown, and a recent trend
  (average of the last 10 ratings).

  Rider identity is never included in any response field — this is a
  deliberate privacy protection for riders.

  This endpoint is a cooperative transparency feature: drivers deserve
  access to the same data about their own performance that the platform
  uses to evaluate them.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_driver
from app.models.user import User
from app.schemas.driver_ratings import DriverRatingsResponse
from app.services.driver_ratings import get_driver_ratings_history

router = APIRouter(prefix="/drivers", tags=["drivers"])

_MAX_PAGE_SIZE = 50
_DEFAULT_PAGE_SIZE = 20


@router.get(
    "/me/ratings",
    response_model=DriverRatingsResponse,
    summary="Get driver's own rating history",
    description=(
        "Returns the authenticated driver's lifetime rating statistics and a "
        "paginated list of individual ratings submitted by riders. "
        "Results are ordered newest first. "
        "Rider identity is never exposed."
    ),
)
async def get_my_ratings(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(
        _DEFAULT_PAGE_SIZE,
        ge=1,
        le=_MAX_PAGE_SIZE,
        description=f"Ratings per page (max {_MAX_PAGE_SIZE})",
    ),
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverRatingsResponse:
    """Return rating history for the authenticated driver.

    Includes:
    - **average_rating**: lifetime average across all completed rides, null
      if no ratings have been received yet.
    - **total_ratings**: total number of ratings received.
    - **rating_breakdown**: count per star level (1–5).
    - **recent_trend**: average of the most recent 10 ratings; null if none.
    - **ratings**: paginated list of individual rating records (newest first).
      Each item includes the ride_id, star rating, optional comment, and
      the datetime the rating was submitted.

    Rider identity is intentionally excluded from all items.
    """
    return await get_driver_ratings_history(
        db=db,
        driver_user_id=driver.id,
        page=page,
        page_size=page_size,
    )
