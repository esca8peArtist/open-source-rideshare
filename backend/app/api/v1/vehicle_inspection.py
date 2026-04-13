"""Vehicle inspection record management endpoints.

Driver endpoints (own records only):
  GET   /drivers/me/vehicle-inspections          — list all my inspections
  GET   /drivers/me/vehicle-inspections/summary  — inspection status summary
  POST  /drivers/me/vehicle-inspections          — submit new inspection
  PATCH /drivers/me/vehicle-inspections/{id}     — update pending inspection

Admin endpoints:
  GET  /admin/vehicle-inspections/pending        — list all pending_review records
  GET  /admin/vehicle-inspections/expiring       — records expiring within N days
  POST /admin/vehicle-inspections/{id}/review    — approve or reject
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_driver
from app.db.database import get_db
from app.models.vehicle_inspection import InspectionStatus, VehicleInspection
from app.models.user import User
from app.schemas.vehicle_inspection import (
    AdminInspectionReview,
    InspectionStatusSummary,
    VehicleInspectionCreate,
    VehicleInspectionResponse,
    VehicleInspectionUpdate,
)
from app.services.vehicle_inspection import (
    VehicleInspectionError,
    admin_review_inspection,
    create_inspection,
    get_driver_inspections,
    get_driver_summary,
    get_expiring_inspections,
    update_inspection,
)

router = APIRouter(tags=["vehicle-inspections"])


# ---------------------------------------------------------------------------
# Driver routes
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/vehicle-inspections/summary",
    response_model=InspectionStatusSummary,
    summary="Get driver's vehicle inspection status summary",
)
async def get_my_inspection_summary(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    return await get_driver_summary(db, user.id)


@router.get(
    "/drivers/me/vehicle-inspections",
    response_model=list[VehicleInspectionResponse],
    summary="List all my vehicle inspection records",
)
async def list_my_inspections(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    return await get_driver_inspections(db, user.id)


@router.post(
    "/drivers/me/vehicle-inspections",
    response_model=VehicleInspectionResponse,
    status_code=201,
    summary="Submit a new vehicle inspection record",
)
async def submit_inspection(
    req: VehicleInspectionCreate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    return await create_inspection(db, user.id, req)


@router.patch(
    "/drivers/me/vehicle-inspections/{inspection_id}",
    response_model=VehicleInspectionResponse,
    summary="Update a pending vehicle inspection record",
)
async def update_my_inspection(
    inspection_id: int,
    req: VehicleInspectionUpdate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    try:
        inspection = await update_inspection(db, user.id, inspection_id, req)
    except VehicleInspectionError as exc:
        detail = str(exc)
        if "Not authorised" in detail:
            raise HTTPException(status_code=403, detail="Not authorised to edit this inspection")
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail="Inspection not found")
        raise HTTPException(status_code=409, detail=detail)
    return inspection


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


@router.get(
    "/admin/vehicle-inspections/pending",
    response_model=list[VehicleInspectionResponse],
    summary="List all vehicle inspection records pending admin review",
)
async def admin_list_pending_inspections(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(VehicleInspection)
        .where(VehicleInspection.status == InspectionStatus.PENDING_REVIEW)
        .order_by(VehicleInspection.created_at.asc())
    )
    return list(result.scalars().all())


@router.get(
    "/admin/vehicle-inspections/expiring",
    response_model=list[VehicleInspectionResponse],
    summary="List approved inspections expiring within N days (default 30)",
)
async def admin_list_expiring_inspections(
    days: int = Query(30, ge=1, le=365),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await get_expiring_inspections(db, days)


@router.post(
    "/admin/vehicle-inspections/{inspection_id}/review",
    response_model=VehicleInspectionResponse,
    summary="Approve or reject a vehicle inspection record",
)
async def admin_review_vehicle_inspection(
    inspection_id: int,
    req: AdminInspectionReview,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        inspection = await admin_review_inspection(db, admin.id, inspection_id, req)
    except VehicleInspectionError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return inspection
