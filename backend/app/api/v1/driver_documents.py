"""Driver license and vehicle registration document management endpoints.

Driver endpoints (own documents only):
  GET   /drivers/me/licenses              — list all my license records
  GET   /drivers/me/licenses/status       — license status summary
  POST  /drivers/me/licenses              — submit new license record
  PATCH /drivers/me/licenses/{id}         — update pending license record

  GET   /drivers/me/registrations         — list all my registration records
  GET   /drivers/me/registrations/status  — registration status summary
  POST  /drivers/me/registrations         — submit new registration record
  PATCH /drivers/me/registrations/{id}    — update pending registration record

  GET   /drivers/me/documents/summary     — combined license + registration summary

Admin endpoints:
  GET  /admin/licenses/pending            — list all pending_review license records
  GET  /admin/licenses/expiring           — licenses expiring within N days
  POST /admin/licenses/{id}/review        — approve or reject a license

  GET  /admin/registrations/pending       — list all pending_review registration records
  GET  /admin/registrations/expiring      — registrations expiring within N days
  POST /admin/registrations/{id}/review   — approve or reject a registration
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_driver
from app.db.database import get_db
from app.models.driver_documents import DocumentStatus, DriverLicense, VehicleRegistration
from app.models.user import User
from app.schemas.driver_documents import (
    AdminLicenseReview,
    AdminRegistrationReview,
    DriverDocumentsSummary,
    DriverLicenseCreate,
    DriverLicenseResponse,
    DriverLicenseUpdate,
    LicenseStatusSummary,
    RegistrationStatusSummary,
    VehicleRegistrationCreate,
    VehicleRegistrationResponse,
    VehicleRegistrationUpdate,
)
from app.services.driver_documents import (
    DriverDocumentError,
    admin_review_license,
    admin_review_registration,
    create_license,
    create_registration,
    get_driver_documents_summary,
    get_driver_licenses,
    get_driver_registrations,
    get_expiring_licenses,
    get_expiring_registrations,
    get_license_status_summary,
    get_registration_status_summary,
    update_license,
    update_registration,
)

router = APIRouter(tags=["driver-documents"])


# ---------------------------------------------------------------------------
# Driver license routes
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/licenses/status",
    response_model=LicenseStatusSummary,
    summary="Get driver's license status summary",
)
async def get_my_license_status(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    return await get_license_status_summary(db, user.id)


@router.get(
    "/drivers/me/licenses",
    response_model=list[DriverLicenseResponse],
    summary="List all my driver's license records",
)
async def list_my_licenses(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    return await get_driver_licenses(db, user.id)


@router.post(
    "/drivers/me/licenses",
    response_model=DriverLicenseResponse,
    status_code=201,
    summary="Submit a new driver's license record",
)
async def submit_license(
    req: DriverLicenseCreate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    return await create_license(db, user.id, req)


@router.patch(
    "/drivers/me/licenses/{license_id}",
    response_model=DriverLicenseResponse,
    summary="Update a pending driver's license record",
)
async def update_my_license(
    license_id: int,
    req: DriverLicenseUpdate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    try:
        license_rec = await update_license(db, user.id, license_id, req)
    except DriverDocumentError as exc:
        detail = str(exc)
        if "Not authorised" in detail:
            raise HTTPException(status_code=403, detail="Not authorised to edit this license")
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail="License not found")
        raise HTTPException(status_code=409, detail=detail)
    return license_rec


# ---------------------------------------------------------------------------
# Driver registration routes
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/registrations/status",
    response_model=RegistrationStatusSummary,
    summary="Get driver's vehicle registration status summary",
)
async def get_my_registration_status(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    return await get_registration_status_summary(db, user.id)


@router.get(
    "/drivers/me/registrations",
    response_model=list[VehicleRegistrationResponse],
    summary="List all my vehicle registration records",
)
async def list_my_registrations(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    return await get_driver_registrations(db, user.id)


@router.post(
    "/drivers/me/registrations",
    response_model=VehicleRegistrationResponse,
    status_code=201,
    summary="Submit a new vehicle registration record",
)
async def submit_registration(
    req: VehicleRegistrationCreate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    return await create_registration(db, user.id, req)


@router.patch(
    "/drivers/me/registrations/{registration_id}",
    response_model=VehicleRegistrationResponse,
    summary="Update a pending vehicle registration record",
)
async def update_my_registration(
    registration_id: int,
    req: VehicleRegistrationUpdate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    try:
        registration = await update_registration(db, user.id, registration_id, req)
    except DriverDocumentError as exc:
        detail = str(exc)
        if "Not authorised" in detail:
            raise HTTPException(
                status_code=403, detail="Not authorised to edit this registration"
            )
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail="Registration not found")
        raise HTTPException(status_code=409, detail=detail)
    return registration


# ---------------------------------------------------------------------------
# Driver combined summary route
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/documents/summary",
    response_model=DriverDocumentsSummary,
    summary="Get combined license and registration status summary",
)
async def get_my_documents_summary(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    return await get_driver_documents_summary(db, user.id)


# ---------------------------------------------------------------------------
# Admin license routes
# ---------------------------------------------------------------------------


@router.get(
    "/admin/licenses/pending",
    response_model=list[DriverLicenseResponse],
    summary="List all driver's license records pending admin review",
)
async def admin_list_pending_licenses(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DriverLicense)
        .where(DriverLicense.status == DocumentStatus.PENDING_REVIEW)
        .order_by(DriverLicense.created_at.asc())
    )
    return list(result.scalars().all())


@router.get(
    "/admin/licenses/expiring",
    response_model=list[DriverLicenseResponse],
    summary="List approved licenses expiring within N days (default 30)",
)
async def admin_list_expiring_licenses(
    days: int = Query(30, ge=1, le=365),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await get_expiring_licenses(db, days)


@router.post(
    "/admin/licenses/{license_id}/review",
    response_model=DriverLicenseResponse,
    summary="Approve or reject a driver's license record",
)
async def admin_review_driver_license(
    license_id: int,
    req: AdminLicenseReview,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        license_rec = await admin_review_license(db, admin.id, license_id, req)
    except DriverDocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return license_rec


# ---------------------------------------------------------------------------
# Admin registration routes
# ---------------------------------------------------------------------------


@router.get(
    "/admin/registrations/pending",
    response_model=list[VehicleRegistrationResponse],
    summary="List all vehicle registration records pending admin review",
)
async def admin_list_pending_registrations(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(VehicleRegistration)
        .where(VehicleRegistration.status == DocumentStatus.PENDING_REVIEW)
        .order_by(VehicleRegistration.created_at.asc())
    )
    return list(result.scalars().all())


@router.get(
    "/admin/registrations/expiring",
    response_model=list[VehicleRegistrationResponse],
    summary="List approved registrations expiring within N days (default 30)",
)
async def admin_list_expiring_registrations(
    days: int = Query(30, ge=1, le=365),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await get_expiring_registrations(db, days)


@router.post(
    "/admin/registrations/{registration_id}/review",
    response_model=VehicleRegistrationResponse,
    summary="Approve or reject a vehicle registration record",
)
async def admin_review_vehicle_registration(
    registration_id: int,
    req: AdminRegistrationReview,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        registration = await admin_review_registration(db, admin.id, registration_id, req)
    except DriverDocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return registration
