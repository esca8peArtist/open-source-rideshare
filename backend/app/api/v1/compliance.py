"""Compliance API — driver eligibility gate and admin document management.

Public (driver-facing) endpoints:
    GET  /api/v1/compliance/check/{driver_id}
        Returns the live compliance status for a driver.  A driver can
        only check their own compliance status; admins can check any driver.

    GET  /api/v1/compliance/jurisdictions
        Lists all active jurisdictions.

    GET  /api/v1/compliance/jurisdictions/{jurisdiction_id}
        Returns config for a single jurisdiction.

Admin-only endpoints:
    POST  /api/v1/admin/drivers/{driver_id}/membership-status
        Update a driver's membership status with a mandatory reason.

    PATCH /api/v1/admin/drivers/{driver_id}/compliance-documents
        Set or update document expiry dates for a driver.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_driver
from app.db.database import get_db
from app.models.driver import DriverProfile
from app.models.jurisdiction import Jurisdiction
from app.models.user import User
from app.schemas.compliance import (
    ComplianceCheckResponse,
    ComplianceDocumentUpdate,
    ComplianceDocumentUpdateResponse,
    JurisdictionResponse,
    MembershipStatusUpdateRequest,
    MembershipStatusUpdateResponse,
)
from app.services.compliance import check_driver_compliance

router = APIRouter(tags=["compliance"])


# ── Driver / public endpoints ────────────────────────────────────────────────

@router.get(
    "/compliance/check/{driver_id}",
    response_model=ComplianceCheckResponse,
    summary="Check driver compliance eligibility",
    description=(
        "Returns whether a driver is eligible to go online right now, along "
        "with any blocking issues.  Drivers may only query their own record; "
        "admins may query any driver."
    ),
)
async def get_compliance_check(
    driver_id: int,
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> ComplianceCheckResponse:
    profile_result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == driver_id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")

    # Non-admin drivers can only check themselves
    if not getattr(current_user, "is_admin", False):
        own_profile = await db.execute(
            select(DriverProfile).where(DriverProfile.user_id == current_user.id)
        )
        own = own_profile.scalar_one_or_none()
        if own is None or own.id != driver_id:
            raise HTTPException(
                status_code=403,
                detail="You may only check your own compliance status",
            )

    # Load jurisdiction if the driver has one set
    jurisdiction: Jurisdiction | None = None
    if profile.jurisdiction_id:
        j_result = await db.execute(
            select(Jurisdiction).where(Jurisdiction.id == profile.jurisdiction_id)
        )
        jurisdiction = j_result.scalar_one_or_none()

    result = check_driver_compliance(profile, jurisdiction=jurisdiction)
    return ComplianceCheckResponse.from_result(result)


@router.get(
    "/compliance/jurisdictions",
    response_model=list[JurisdictionResponse],
    summary="List all active jurisdictions",
)
async def list_jurisdictions(
    db: AsyncSession = Depends(get_db),
) -> list[JurisdictionResponse]:
    result = await db.execute(
        select(Jurisdiction).where(Jurisdiction.is_active.is_(True))
    )
    return result.scalars().all()  # type: ignore[return-value]


@router.get(
    "/compliance/jurisdictions/{jurisdiction_id}",
    response_model=JurisdictionResponse,
    summary="Get jurisdiction configuration",
)
async def get_jurisdiction(
    jurisdiction_id: str,
    db: AsyncSession = Depends(get_db),
) -> JurisdictionResponse:
    result = await db.execute(
        select(Jurisdiction).where(Jurisdiction.id == jurisdiction_id)
    )
    jurisdiction = result.scalar_one_or_none()
    if not jurisdiction:
        raise HTTPException(status_code=404, detail="Jurisdiction not found")
    return jurisdiction  # type: ignore[return-value]


# ── Admin endpoints ──────────────────────────────────────────────────────────

@router.post(
    "/admin/drivers/{driver_id}/membership-status",
    response_model=MembershipStatusUpdateResponse,
    summary="Update driver membership status",
    description=(
        "Change a driver's cooperative membership status.  A non-empty reason "
        "is required for audit trail purposes.  Every change is logged."
    ),
)
async def update_membership_status(
    driver_id: int,
    body: MembershipStatusUpdateRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MembershipStatusUpdateResponse:
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == driver_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")

    previous_status = profile.membership_status
    profile.membership_status = body.new_status
    now = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(profile)

    return MembershipStatusUpdateResponse(
        driver_id=driver_id,
        previous_status=previous_status,
        new_status=body.new_status,
        reason=body.reason,
        updated_at=now,
    )


@router.patch(
    "/admin/drivers/{driver_id}/compliance-documents",
    response_model=ComplianceDocumentUpdateResponse,
    summary="Update driver compliance document expiry dates",
    description=(
        "Set or update expiry dates for compliance documents.  All fields are "
        "optional; only supplied fields are updated.  Dates must be in the "
        "future to prevent accidental data corruption."
    ),
)
async def update_compliance_documents(
    driver_id: int,
    body: ComplianceDocumentUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ComplianceDocumentUpdateResponse:
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == driver_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")

    if body.license_expiry is not None:
        profile.license_expiry = body.license_expiry
    if body.background_check_expiry is not None:
        profile.background_check_expiry = body.background_check_expiry
    if body.vehicle_inspection_expiry is not None:
        profile.vehicle_inspection_expiry = body.vehicle_inspection_expiry
    if body.insurance_endorsement_expiry is not None:
        profile.insurance_endorsement_expiry = body.insurance_endorsement_expiry

    now = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(profile)

    return ComplianceDocumentUpdateResponse(
        driver_id=driver_id,
        license_expiry=profile.license_expiry,
        background_check_expiry=profile.background_check_expiry,
        vehicle_inspection_expiry=profile.vehicle_inspection_expiry,
        insurance_endorsement_expiry=profile.insurance_endorsement_expiry,
        updated_at=now,
    )
