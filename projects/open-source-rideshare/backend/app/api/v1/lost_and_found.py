"""Lost and found API endpoints.

Rider endpoints (authenticated as a rider):
  POST /riders/me/lost-items          — report a lost item
  GET  /riders/me/lost-items          — list my lost item reports
  GET  /riders/me/lost-items/{id}     — single lost report detail

Driver endpoints (authenticated as a driver):
  POST /drivers/me/found-items-v2          — report a found item
  GET  /drivers/me/found-items-v2          — list my found item reports
  GET  /drivers/me/found-items-v2/{id}     — single found report detail

Admin endpoints (authenticated as an admin):
  GET  /admin/lost-and-found/lost-reports             — all lost reports (filter by status)
  GET  /admin/lost-and-found/lost-reports/{id}        — detail
  GET  /admin/lost-and-found/found-reports            — all found reports (filter by status)
  GET  /admin/lost-and-found/found-reports/{id}       — detail
  POST /admin/lost-and-found/match                    — match a lost + found pair
  POST /admin/lost-and-found/found-reports/{id}/mark-returned — item returned to owner
  POST /admin/lost-and-found/found-reports/{id}/discard       — item discarded
  POST /admin/lost-and-found/lost-reports/{id}/close          — close with no match

Note: driver found-items uses a "-v2" suffix to avoid a path clash with
the existing /drivers/me/found-items route from the original lost_found module.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.lost_and_found import LafFoundItemStatus, LafLostItemStatus
from app.models.user import User
from app.schemas.lost_and_found import (
    FoundItemReportCreate,
    FoundItemReportResponse,
    LostItemReportCreate,
    LostItemReportResponse,
    MatchReportsRequest,
)
from app.services.lost_and_found import (
    LostAndFoundError,
    admin_list_found_reports,
    admin_list_lost_reports,
    close_lost_report,
    create_found_report,
    create_lost_report,
    discard_found_item,
    get_driver_found_reports,
    get_found_report,
    get_lost_report,
    get_rider_lost_reports,
    mark_returned,
    match_reports,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["lost-and-found"])


def _http(exc: LostAndFoundError) -> HTTPException:
    """Convert a service-layer error to an HTTPException."""
    return HTTPException(status_code=exc.status_code, detail=str(exc))


# ---------------------------------------------------------------------------
# Rider endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/riders/me/lost-items",
    response_model=LostItemReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Report a lost item",
)
async def rider_report_lost_item(
    req: LostItemReportCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rider submits a report for an item they left in a vehicle.

    ride_id is optional — the rider may not remember the exact ride.
    """
    try:
        report = await create_lost_report(
            db,
            rider_id=user.id,
            description=req.description,
            category=req.category,
            date_lost=req.date_lost,
            contact_preference=req.contact_preference,
            ride_id=req.ride_id,
        )
    except LostAndFoundError as exc:
        raise _http(exc)

    await db.commit()
    await db.refresh(report)
    return report


@router.get(
    "/riders/me/lost-items",
    response_model=list[LostItemReportResponse],
    summary="List my lost item reports",
)
async def rider_list_lost_items(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated rider's lost item reports, newest first."""
    return await get_rider_lost_reports(db, rider_id=user.id, limit=limit, offset=offset)


@router.get(
    "/riders/me/lost-items/{report_id}",
    response_model=LostItemReportResponse,
    summary="Get a single lost item report",
)
async def rider_get_lost_item(
    report_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single lost item report.

    Riders may only retrieve their own reports.
    """
    try:
        report = await get_lost_report(db, lost_id=report_id)
    except LostAndFoundError as exc:
        raise _http(exc)

    if report.rider_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view this report",
        )
    return report


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/found-items-v2",
    response_model=FoundItemReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Report a found item",
)
async def driver_report_found_item(
    req: FoundItemReportCreate,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Driver submits a report for an item found in their vehicle.

    ride_id is optional — the driver may not know which ride it came from.
    """
    try:
        report = await create_found_report(
            db,
            driver_id=driver.id,
            description=req.description,
            category=req.category,
            date_found=req.date_found,
            storage_location=req.storage_location,
            ride_id=req.ride_id,
        )
    except LostAndFoundError as exc:
        raise _http(exc)

    await db.commit()
    await db.refresh(report)
    return report


@router.get(
    "/drivers/me/found-items-v2",
    response_model=list[FoundItemReportResponse],
    summary="List my found item reports",
)
async def driver_list_found_items(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated driver's found item reports, newest first."""
    return await get_driver_found_reports(db, driver_id=driver.id, limit=limit, offset=offset)


@router.get(
    "/drivers/me/found-items-v2/{report_id}",
    response_model=FoundItemReportResponse,
    summary="Get a single found item report",
)
async def driver_get_found_item(
    report_id: int,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single found item report.

    Drivers may only retrieve their own reports.
    """
    try:
        report = await get_found_report(db, found_id=report_id)
    except LostAndFoundError as exc:
        raise _http(exc)

    if report.driver_id != driver.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view this report",
        )
    return report


# ---------------------------------------------------------------------------
# Admin endpoints — lost reports
# ---------------------------------------------------------------------------


@router.get(
    "/admin/lost-and-found/lost-reports",
    response_model=list[LostItemReportResponse],
    summary="Admin: list all lost reports",
)
async def admin_list_lost(
    status_filter: LafLostItemStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: list all lost item reports, optionally filtered by status."""
    return await admin_list_lost_reports(db, status=status_filter, limit=limit, offset=offset)


@router.get(
    "/admin/lost-and-found/lost-reports/{report_id}",
    response_model=LostItemReportResponse,
    summary="Admin: get a lost report",
)
async def admin_get_lost(
    report_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: fetch details for a specific lost item report."""
    try:
        return await get_lost_report(db, lost_id=report_id)
    except LostAndFoundError as exc:
        raise _http(exc)


@router.post(
    "/admin/lost-and-found/lost-reports/{report_id}/close",
    response_model=LostItemReportResponse,
    summary="Admin: close a lost report with no match",
)
async def admin_close_lost(
    report_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: close a lost report that could not be matched to a found item."""
    try:
        report = await close_lost_report(db, lost_id=report_id, admin_id=admin.id)
    except LostAndFoundError as exc:
        raise _http(exc)

    await db.commit()
    await db.refresh(report)
    return report


# ---------------------------------------------------------------------------
# Admin endpoints — found reports
# ---------------------------------------------------------------------------


@router.get(
    "/admin/lost-and-found/found-reports",
    response_model=list[FoundItemReportResponse],
    summary="Admin: list all found reports",
)
async def admin_list_found(
    status_filter: LafFoundItemStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: list all found item reports, optionally filtered by status."""
    return await admin_list_found_reports(db, status=status_filter, limit=limit, offset=offset)


@router.get(
    "/admin/lost-and-found/found-reports/{report_id}",
    response_model=FoundItemReportResponse,
    summary="Admin: get a found report",
)
async def admin_get_found(
    report_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: fetch details for a specific found item report."""
    try:
        return await get_found_report(db, found_id=report_id)
    except LostAndFoundError as exc:
        raise _http(exc)


@router.post(
    "/admin/lost-and-found/found-reports/{report_id}/mark-returned",
    response_model=FoundItemReportResponse,
    summary="Admin: mark item as returned to owner",
)
async def admin_mark_returned(
    report_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: mark a found item as returned to its owner.

    The found report must be in MATCHED status. The linked lost report
    (if any) will also be updated to RETURNED.
    """
    try:
        found, _lost = await mark_returned(db, found_id=report_id, admin_id=admin.id)
    except LostAndFoundError as exc:
        raise _http(exc)

    await db.commit()
    await db.refresh(found)
    return found


@router.post(
    "/admin/lost-and-found/found-reports/{report_id}/discard",
    response_model=FoundItemReportResponse,
    summary="Admin: discard an unclaimed found item",
)
async def admin_discard_found(
    report_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: record that a found item was discarded (no owner came forward)."""
    try:
        report = await discard_found_item(db, found_id=report_id, admin_id=admin.id)
    except LostAndFoundError as exc:
        raise _http(exc)

    await db.commit()
    await db.refresh(report)
    return report


# ---------------------------------------------------------------------------
# Admin endpoints — matching
# ---------------------------------------------------------------------------


@router.post(
    "/admin/lost-and-found/match",
    response_model=LostItemReportResponse,
    summary="Admin: match a lost report to a found report",
)
async def admin_match(
    req: MatchReportsRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: link a lost item report to a found item report.

    Sets both reports to MATCHED status and records the cross-reference IDs.
    Returns the updated lost item report.
    """
    try:
        lost, _found = await match_reports(
            db,
            lost_id=req.lost_report_id,
            found_id=req.found_report_id,
            admin_id=admin.id,
        )
    except LostAndFoundError as exc:
        raise _http(exc)

    await db.commit()
    await db.refresh(lost)
    return lost
