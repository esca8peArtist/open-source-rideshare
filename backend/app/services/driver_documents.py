"""Service layer for driver license and vehicle registration document management."""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_documents import (
    DocumentStatus,
    DriverLicense,
    VehicleRegistration,
)
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

# Statuses that allow driver edits
_EDITABLE_STATUSES = {DocumentStatus.PENDING_UPLOAD, DocumentStatus.PENDING_REVIEW}


class DriverDocumentError(Exception):
    """Raised for driver document business logic violations."""


# ===========================================================================
# Driver's License service functions
# ===========================================================================


async def get_driver_licenses(
    db: AsyncSession,
    driver_id: int,
) -> list[DriverLicense]:
    """Return all license records for a driver, newest first."""
    result = await db.execute(
        select(DriverLicense)
        .where(DriverLicense.driver_id == driver_id)
        .order_by(DriverLicense.created_at.desc())
    )
    return list(result.scalars().all())


async def get_current_approved_license(
    db: AsyncSession,
    driver_id: int,
) -> Optional[DriverLicense]:
    """Return the most recent approved, non-expired license for the driver."""
    today = date.today()
    result = await db.execute(
        select(DriverLicense)
        .where(
            and_(
                DriverLicense.driver_id == driver_id,
                DriverLicense.status == DocumentStatus.APPROVED,
                DriverLicense.expiry_date >= today,
            )
        )
        .order_by(DriverLicense.expiry_date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_license(
    db: AsyncSession,
    driver_id: int,
    data: DriverLicenseCreate,
) -> DriverLicense:
    """Create a new driver's license record.

    If a document_url is provided the status starts as pending_review;
    otherwise pending_upload until the driver attaches the file.
    """
    initial_status = (
        DocumentStatus.PENDING_REVIEW
        if data.document_url
        else DocumentStatus.PENDING_UPLOAD
    )
    uploaded_at = datetime.now(timezone.utc) if data.document_url else None

    license_rec = DriverLicense(
        driver_id=driver_id,
        license_number=data.license_number,
        state_issued=data.state_issued,
        license_class=data.license_class,
        expiry_date=data.expiry_date,
        document_url=data.document_url,
        notes=data.notes,
        status=initial_status,
        uploaded_at=uploaded_at,
    )
    db.add(license_rec)
    await db.commit()
    await db.refresh(license_rec)
    return license_rec


async def update_license(
    db: AsyncSession,
    driver_id: int,
    license_id: int,
    data: DriverLicenseUpdate,
) -> DriverLicense:
    """Update a driver's own pending license record.

    Raises DriverDocumentError if the record cannot be edited.
    """
    result = await db.execute(
        select(DriverLicense).where(DriverLicense.id == license_id)
    )
    license_rec = result.scalar_one_or_none()
    if not license_rec:
        raise DriverDocumentError("License not found")
    if license_rec.driver_id != driver_id:
        raise DriverDocumentError("Not authorised to edit this license")
    if license_rec.status not in _EDITABLE_STATUSES:
        raise DriverDocumentError(
            f"Cannot edit a license with status '{license_rec.status.value}'"
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(license_rec, field, value)

    # Promote to pending_review once a URL has been attached
    if license_rec.document_url and license_rec.status == DocumentStatus.PENDING_UPLOAD:
        license_rec.status = DocumentStatus.PENDING_REVIEW
        license_rec.uploaded_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(license_rec)
    return license_rec


async def admin_review_license(
    db: AsyncSession,
    admin_id: int,
    license_id: int,
    review: AdminLicenseReview,
) -> DriverLicense:
    """Approve or reject a driver's license as an admin.

    On approval any previously approved license for the same driver is
    expired so only one approved record is active at a time.
    """
    result = await db.execute(
        select(DriverLicense).where(DriverLicense.id == license_id)
    )
    license_rec = result.scalar_one_or_none()
    if not license_rec:
        raise DriverDocumentError("License not found")

    if review.status == DocumentStatus.APPROVED:
        prev_result = await db.execute(
            select(DriverLicense).where(
                and_(
                    DriverLicense.driver_id == license_rec.driver_id,
                    DriverLicense.status == DocumentStatus.APPROVED,
                    DriverLicense.id != license_id,
                )
            )
        )
        for prev in prev_result.scalars().all():
            prev.status = DocumentStatus.EXPIRED

    license_rec.status = review.status
    license_rec.rejection_reason = review.rejection_reason
    if review.notes is not None:
        license_rec.notes = review.notes
    license_rec.reviewed_by = admin_id
    license_rec.reviewed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(license_rec)
    return license_rec


async def get_license_status_summary(
    db: AsyncSession,
    driver_id: int,
) -> LicenseStatusSummary:
    """Return a high-level license status for a driver."""
    licenses = await get_driver_licenses(db, driver_id)
    active = await get_current_approved_license(db, driver_id)

    has_valid = active is not None
    days_until_expiry: Optional[int] = None
    if active:
        days_until_expiry = (active.expiry_date - date.today()).days

    license_responses = [DriverLicenseResponse.model_validate(lic) for lic in licenses]
    active_response = (
        DriverLicenseResponse.model_validate(active) if active else None
    )

    return LicenseStatusSummary(
        has_valid_license=has_valid,
        days_until_expiry=days_until_expiry,
        active_license=active_response,
        licenses=license_responses,
    )


async def get_expiring_licenses(
    db: AsyncSession,
    days_ahead: int = 30,
) -> list[DriverLicense]:
    """Return approved licenses whose expiry_date falls within *days_ahead* days."""
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    result = await db.execute(
        select(DriverLicense).where(
            and_(
                DriverLicense.status == DocumentStatus.APPROVED,
                DriverLicense.expiry_date >= today,
                DriverLicense.expiry_date <= cutoff,
            )
        )
    )
    return list(result.scalars().all())


async def mark_expired_licenses(db: AsyncSession) -> int:
    """Batch-update approved licenses whose expiry_date is in the past.

    Returns the number of records updated.
    """
    today = date.today()
    result = await db.execute(
        select(DriverLicense).where(
            and_(
                DriverLicense.status == DocumentStatus.APPROVED,
                DriverLicense.expiry_date < today,
            )
        )
    )
    licenses = list(result.scalars().all())
    for lic in licenses:
        lic.status = DocumentStatus.EXPIRED
    if licenses:
        await db.commit()
    return len(licenses)


# ===========================================================================
# Vehicle Registration service functions
# ===========================================================================


async def get_driver_registrations(
    db: AsyncSession,
    driver_id: int,
) -> list[VehicleRegistration]:
    """Return all registration records for a driver, newest first."""
    result = await db.execute(
        select(VehicleRegistration)
        .where(VehicleRegistration.driver_id == driver_id)
        .order_by(VehicleRegistration.created_at.desc())
    )
    return list(result.scalars().all())


async def get_current_approved_registration(
    db: AsyncSession,
    driver_id: int,
) -> Optional[VehicleRegistration]:
    """Return the most recent approved, non-expired vehicle registration for the driver."""
    today = date.today()
    result = await db.execute(
        select(VehicleRegistration)
        .where(
            and_(
                VehicleRegistration.driver_id == driver_id,
                VehicleRegistration.status == DocumentStatus.APPROVED,
                VehicleRegistration.expiry_date >= today,
            )
        )
        .order_by(VehicleRegistration.expiry_date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_registration(
    db: AsyncSession,
    driver_id: int,
    data: VehicleRegistrationCreate,
) -> VehicleRegistration:
    """Create a new vehicle registration record.

    If a document_url is provided the status starts as pending_review;
    otherwise pending_upload until the driver attaches the file.
    """
    initial_status = (
        DocumentStatus.PENDING_REVIEW
        if data.document_url
        else DocumentStatus.PENDING_UPLOAD
    )
    uploaded_at = datetime.now(timezone.utc) if data.document_url else None

    registration = VehicleRegistration(
        driver_id=driver_id,
        vehicle_id=data.vehicle_id,
        plate_number=data.plate_number,
        state=data.state,
        expiry_date=data.expiry_date,
        document_url=data.document_url,
        notes=data.notes,
        status=initial_status,
        uploaded_at=uploaded_at,
    )
    db.add(registration)
    await db.commit()
    await db.refresh(registration)
    return registration


async def update_registration(
    db: AsyncSession,
    driver_id: int,
    registration_id: int,
    data: VehicleRegistrationUpdate,
) -> VehicleRegistration:
    """Update a driver's own pending vehicle registration record.

    Raises DriverDocumentError if the record cannot be edited.
    """
    result = await db.execute(
        select(VehicleRegistration).where(VehicleRegistration.id == registration_id)
    )
    registration = result.scalar_one_or_none()
    if not registration:
        raise DriverDocumentError("Registration not found")
    if registration.driver_id != driver_id:
        raise DriverDocumentError("Not authorised to edit this registration")
    if registration.status not in _EDITABLE_STATUSES:
        raise DriverDocumentError(
            f"Cannot edit a registration with status '{registration.status.value}'"
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(registration, field, value)

    # Promote to pending_review once a URL has been attached
    if (
        registration.document_url
        and registration.status == DocumentStatus.PENDING_UPLOAD
    ):
        registration.status = DocumentStatus.PENDING_REVIEW
        registration.uploaded_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(registration)
    return registration


async def admin_review_registration(
    db: AsyncSession,
    admin_id: int,
    registration_id: int,
    review: AdminRegistrationReview,
) -> VehicleRegistration:
    """Approve or reject a vehicle registration as an admin.

    On approval any previously approved registration for the same driver is
    expired so only one approved record is active at a time.
    """
    result = await db.execute(
        select(VehicleRegistration).where(VehicleRegistration.id == registration_id)
    )
    registration = result.scalar_one_or_none()
    if not registration:
        raise DriverDocumentError("Registration not found")

    if review.status == DocumentStatus.APPROVED:
        prev_result = await db.execute(
            select(VehicleRegistration).where(
                and_(
                    VehicleRegistration.driver_id == registration.driver_id,
                    VehicleRegistration.status == DocumentStatus.APPROVED,
                    VehicleRegistration.id != registration_id,
                )
            )
        )
        for prev in prev_result.scalars().all():
            prev.status = DocumentStatus.EXPIRED

    registration.status = review.status
    registration.rejection_reason = review.rejection_reason
    if review.notes is not None:
        registration.notes = review.notes
    registration.reviewed_by = admin_id
    registration.reviewed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(registration)
    return registration


async def get_registration_status_summary(
    db: AsyncSession,
    driver_id: int,
) -> RegistrationStatusSummary:
    """Return a high-level vehicle registration status for a driver."""
    registrations = await get_driver_registrations(db, driver_id)
    active = await get_current_approved_registration(db, driver_id)

    has_valid = active is not None
    days_until_expiry: Optional[int] = None
    if active:
        days_until_expiry = (active.expiry_date - date.today()).days

    reg_responses = [
        VehicleRegistrationResponse.model_validate(r) for r in registrations
    ]
    active_response = (
        VehicleRegistrationResponse.model_validate(active) if active else None
    )

    return RegistrationStatusSummary(
        has_valid_registration=has_valid,
        days_until_expiry=days_until_expiry,
        active_registration=active_response,
        registrations=reg_responses,
    )


async def get_expiring_registrations(
    db: AsyncSession,
    days_ahead: int = 30,
) -> list[VehicleRegistration]:
    """Return approved registrations whose expiry_date falls within *days_ahead* days."""
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    result = await db.execute(
        select(VehicleRegistration).where(
            and_(
                VehicleRegistration.status == DocumentStatus.APPROVED,
                VehicleRegistration.expiry_date >= today,
                VehicleRegistration.expiry_date <= cutoff,
            )
        )
    )
    return list(result.scalars().all())


async def mark_expired_registrations(db: AsyncSession) -> int:
    """Batch-update approved registrations whose expiry_date is in the past.

    Returns the number of records updated.
    """
    today = date.today()
    result = await db.execute(
        select(VehicleRegistration).where(
            and_(
                VehicleRegistration.status == DocumentStatus.APPROVED,
                VehicleRegistration.expiry_date < today,
            )
        )
    )
    registrations = list(result.scalars().all())
    for reg in registrations:
        reg.status = DocumentStatus.EXPIRED
    if registrations:
        await db.commit()
    return len(registrations)


# ===========================================================================
# Combined summary
# ===========================================================================


async def get_driver_documents_summary(
    db: AsyncSession,
    driver_id: int,
) -> DriverDocumentsSummary:
    """Return combined license and registration status for a driver."""
    license_summary = await get_license_status_summary(db, driver_id)
    registration_summary = await get_registration_status_summary(db, driver_id)
    return DriverDocumentsSummary(
        license_summary=license_summary,
        registration_summary=registration_summary,
    )
