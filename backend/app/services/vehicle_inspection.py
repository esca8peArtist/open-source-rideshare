"""Service layer for vehicle inspection record management."""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle_inspection import (
    InspectionStatus,
    InspectionType,
    VehicleInspection,
)
from app.schemas.vehicle_inspection import (
    AdminInspectionReview,
    InspectionStatusSummary,
    VehicleInspectionCreate,
    VehicleInspectionResponse,
    VehicleInspectionUpdate,
)

# Inspection types that carry an expiry date (set to 1 year if not provided)
_EXPIRING_TYPES = {InspectionType.ANNUAL, InspectionType.SEMI_ANNUAL}
_SEMI_ANNUAL_DAYS = 182


class VehicleInspectionError(Exception):
    """Raised for vehicle inspection business logic violations."""


async def get_driver_inspections(
    db: AsyncSession,
    driver_id: int,
) -> list[VehicleInspection]:
    """Return all inspection records for a driver, newest first."""
    result = await db.execute(
        select(VehicleInspection)
        .where(VehicleInspection.driver_id == driver_id)
        .order_by(VehicleInspection.created_at.desc())
    )
    return list(result.scalars().all())


async def get_current_approved_inspection(
    db: AsyncSession,
    driver_id: int,
) -> Optional[VehicleInspection]:
    """Return the most recent approved, non-expired inspection for the driver."""
    today = date.today()
    result = await db.execute(
        select(VehicleInspection)
        .where(
            and_(
                VehicleInspection.driver_id == driver_id,
                VehicleInspection.status == InspectionStatus.APPROVED,
                # Records without an expiry_date are single-use; treat them as
                # valid only on the day they were issued.
                VehicleInspection.expiry_date >= today,
            )
        )
        .order_by(VehicleInspection.expiry_date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_inspection(
    db: AsyncSession,
    driver_id: int,
    data: VehicleInspectionCreate,
) -> VehicleInspection:
    """Create a new vehicle inspection record.

    If a document_url is provided the status starts as pending_review.
    Annual and semi-annual inspections receive an auto-calculated expiry_date
    when none is explicitly supplied.
    """
    expiry_date = data.expiry_date
    if expiry_date is None and data.inspection_type in _EXPIRING_TYPES:
        days = 365 if data.inspection_type == InspectionType.ANNUAL else _SEMI_ANNUAL_DAYS
        expiry_date = data.inspection_date + timedelta(days=days)

    inspection = VehicleInspection(
        driver_id=driver_id,
        inspection_type=data.inspection_type,
        inspection_date=data.inspection_date,
        expiry_date=expiry_date,
        status=InspectionStatus.PENDING_REVIEW,
        document_url=data.document_url,
        odometer_reading=data.odometer_reading,
        passed_items=data.passed_items,
        failed_items=data.failed_items,
        notes=data.notes,
    )
    db.add(inspection)
    await db.commit()
    await db.refresh(inspection)
    return inspection


async def update_inspection(
    db: AsyncSession,
    driver_id: int,
    inspection_id: int,
    data: VehicleInspectionUpdate,
) -> VehicleInspection:
    """Update a driver's own pending inspection record.

    Raises VehicleInspectionError if the record cannot be edited.
    """
    result = await db.execute(
        select(VehicleInspection).where(VehicleInspection.id == inspection_id)
    )
    inspection = result.scalar_one_or_none()
    if not inspection:
        raise VehicleInspectionError("Inspection not found")
    if inspection.driver_id != driver_id:
        raise VehicleInspectionError("Not authorised to edit this inspection")
    editable_statuses = {InspectionStatus.PENDING_REVIEW}
    if inspection.status not in editable_statuses:
        raise VehicleInspectionError(
            f"Cannot edit an inspection with status '{inspection.status.value}'"
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(inspection, field, value)

    await db.commit()
    await db.refresh(inspection)
    return inspection


async def admin_review_inspection(
    db: AsyncSession,
    admin_id: int,
    inspection_id: int,
    review: AdminInspectionReview,
) -> VehicleInspection:
    """Approve or reject an inspection record as an admin.

    On approval any previously approved inspection for the same driver is
    expired so only one approved record is active at a time.
    """
    result = await db.execute(
        select(VehicleInspection).where(VehicleInspection.id == inspection_id)
    )
    inspection = result.scalar_one_or_none()
    if not inspection:
        raise VehicleInspectionError("Inspection not found")

    if review.status == InspectionStatus.APPROVED:
        # Expire any currently approved inspection for this driver
        prev_result = await db.execute(
            select(VehicleInspection).where(
                and_(
                    VehicleInspection.driver_id == inspection.driver_id,
                    VehicleInspection.status == InspectionStatus.APPROVED,
                    VehicleInspection.id != inspection_id,
                )
            )
        )
        for prev in prev_result.scalars().all():
            prev.status = InspectionStatus.EXPIRED

    inspection.status = review.status
    inspection.rejection_reason = review.rejection_reason
    if review.notes is not None:
        inspection.notes = review.notes
    inspection.reviewed_by = admin_id
    inspection.reviewed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(inspection)
    return inspection


async def get_driver_summary(
    db: AsyncSession,
    driver_id: int,
) -> InspectionStatusSummary:
    """Return a high-level inspection status for a driver."""
    inspections = await get_driver_inspections(db, driver_id)
    current = await get_current_approved_inspection(db, driver_id)

    has_active = current is not None
    days_until_expiry: Optional[int] = None
    if current and current.expiry_date:
        days_until_expiry = (current.expiry_date - date.today()).days

    inspection_responses = [VehicleInspectionResponse.model_validate(i) for i in inspections]
    current_response = (
        VehicleInspectionResponse.model_validate(current) if current else None
    )

    return InspectionStatusSummary(
        has_active_inspection=has_active,
        days_until_expiry=days_until_expiry,
        current_inspection=current_response,
        inspections=inspection_responses,
    )


async def get_expiring_inspections(
    db: AsyncSession,
    days_ahead: int = 30,
) -> list[VehicleInspection]:
    """Return approved inspections whose expiry_date falls within *days_ahead* days."""
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    result = await db.execute(
        select(VehicleInspection).where(
            and_(
                VehicleInspection.status == InspectionStatus.APPROVED,
                VehicleInspection.expiry_date >= today,
                VehicleInspection.expiry_date <= cutoff,
            )
        )
    )
    return list(result.scalars().all())


async def mark_expired_inspections(db: AsyncSession) -> int:
    """Batch-update approved inspections whose expiry_date is in the past.

    Returns the number of records updated.
    """
    today = date.today()
    result = await db.execute(
        select(VehicleInspection).where(
            and_(
                VehicleInspection.status == InspectionStatus.APPROVED,
                VehicleInspection.expiry_date < today,
            )
        )
    )
    inspections = list(result.scalars().all())
    for inspection in inspections:
        inspection.status = InspectionStatus.EXPIRED
    if inspections:
        await db.commit()
    return len(inspections)
