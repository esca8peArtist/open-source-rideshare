"""Driver Rating Appeal API endpoints.

Driver endpoints:
  POST /drivers/me/rating-appeals              — submit an appeal
  GET  /drivers/me/rating-appeals              — list own appeals

Admin endpoints:
  GET  /admin/rating-appeals                   — list all appeals (filter by status)
  POST /admin/rating-appeals/{id}/review       — approve or reject
  GET  /admin/rating-appeals/summary           — aggregate stats
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.driver_rating_appeal import AppealStatus
from app.models.user import User
from app.schemas.driver_rating_appeal import (
    AppealResponse,
    AppealReviewRequest,
    AppealSubmitRequest,
    AppealSummaryResponse,
)
from app.services.driver_rating_appeal import (
    AppealError,
    get_appeal_summary,
    list_all_appeals,
    list_driver_appeals,
    review_appeal,
    submit_appeal,
)

router = APIRouter(tags=["driver-rating-appeals"])


def _http(exc: AppealError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/rating-appeals",
    response_model=AppealResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Driver submits a rating appeal",
)
async def driver_submit_appeal(
    req: AppealSubmitRequest,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Submit an appeal against a rider-submitted feedback rating.

    The feedback must be a driver-role rating for a ride the driver completed.
    One appeal per feedback record; duplicate appeals return 409.
    """
    try:
        appeal = await submit_appeal(
            db,
            driver_id=driver.id,
            feedback_id=req.feedback_id,
            reason=req.reason,
        )
    except AppealError as exc:
        raise _http(exc)

    await db.commit()
    await db.refresh(appeal)
    return appeal


@router.get(
    "/drivers/me/rating-appeals",
    response_model=list[AppealResponse],
    summary="Driver lists their own rating appeals",
)
async def driver_list_own_appeals(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated driver's rating appeals, newest first."""
    appeals = await list_driver_appeals(db, driver_id=driver.id, skip=offset, limit=limit)
    return list(appeals)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/rating-appeals/summary",
    response_model=AppealSummaryResponse,
    summary="Admin: aggregate rating appeal statistics",
)
async def admin_appeals_summary(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return counts broken down by status and the total nullified rating count.

    Note: declared before /admin/rating-appeals/{id}/review so 'summary'
    is not captured as an integer path parameter.
    """
    data = await get_appeal_summary(db)
    return AppealSummaryResponse(**data)


@router.get(
    "/admin/rating-appeals",
    response_model=list[AppealResponse],
    summary="Admin: list all rating appeals",
)
async def admin_list_appeals(
    appeal_status: AppealStatus | None = Query(None, description="Filter by appeal status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all appeals, optionally filtered by status, newest first."""
    appeals = await list_all_appeals(
        db, status_filter=appeal_status, skip=offset, limit=limit
    )
    return list(appeals)


@router.post(
    "/admin/rating-appeals/{appeal_id}/review",
    response_model=AppealResponse,
    summary="Admin: approve or reject a rating appeal",
)
async def admin_review_appeal(
    appeal_id: int,
    req: AppealReviewRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject a pending appeal.

    - **approved**: sets rating_nullified=True; rating is excluded from driver
      average score computations going forward.
    - **rejected**: appeal closed, rating stands.

    Returns 409 if the appeal has already been reviewed.
    """
    try:
        appeal = await review_appeal(
            db,
            appeal_id=appeal_id,
            admin_id=admin.id,
            decision=req.decision,
            admin_notes=req.admin_notes,
        )
    except AppealError as exc:
        raise _http(exc)

    await db.commit()
    await db.refresh(appeal)
    return appeal
