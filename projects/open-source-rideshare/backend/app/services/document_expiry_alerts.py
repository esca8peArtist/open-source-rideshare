"""Driver document expiry alert service.

Surfaces approaching and past expiry for the four document types required
of every active driver:
  - Driver's license            (driver_licenses.expiry_date)
  - Vehicle registration        (vehicle_registrations.expiry_date)
  - Insurance policy            (driver_insurance_documents.policy_end_date)
  - Vehicle inspection          (vehicle_inspections.expiry_date)

Public functions
----------------
get_driver_expiry_status(driver_id, db, days_ahead)
    → ExpiryStatusResult for a single driver (used by the driver-facing endpoint).

get_all_expiring_documents(db, days_ahead, doc_type)
    → list[DriverExpiryRow] — admin view across all drivers.

run_expiry_scan(db)
    → ExpiryScaResult — bulk-marks overdue active documents as EXPIRED and
      returns counts.  Safe to call repeatedly (idempotent per document).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_documents import (
    DocumentStatus,
    DriverLicense,
    VehicleRegistration,
)
from app.models.driver_insurance import (
    DriverInsuranceDocument,
    InsuranceDocumentStatus,
)
from app.models.vehicle_inspection import (
    InspectionStatus,
    VehicleInspection,
)

DocType = Literal["license", "registration", "insurance", "inspection"]

_ACTIVE_LICENSE_STATUSES = {DocumentStatus.APPROVED, DocumentStatus.PENDING_REVIEW}
_ACTIVE_INSURANCE_STATUSES = {InsuranceDocumentStatus.APPROVED, InsuranceDocumentStatus.PENDING_REVIEW}
_ACTIVE_INSPECTION_STATUSES = {InspectionStatus.APPROVED, InspectionStatus.PENDING_REVIEW}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ExpiringDocument:
    doc_type: DocType
    doc_id: int
    expiry_date: date | None
    days_until_expiry: int | None  # negative means already expired
    status: str


@dataclass
class ExpiryStatusResult:
    """Expiry summary for a single driver."""
    driver_id: int
    expiring: list[ExpiringDocument] = field(default_factory=list)
    expired: list[ExpiringDocument] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return bool(self.expiring or self.expired)


@dataclass
class DriverExpiryRow:
    """One row in the admin expiring-documents list."""
    driver_id: int
    doc_type: DocType
    doc_id: int
    expiry_date: date | None
    days_until_expiry: int | None
    status: str


@dataclass
class ExpiryScaResult:
    """Summary from a bulk expiry scan."""
    licenses_marked_expired: int = 0
    registrations_marked_expired: int = 0
    insurance_marked_expired: int = 0
    inspections_marked_expired: int = 0

    @property
    def total_marked_expired(self) -> int:
        return (
            self.licenses_marked_expired
            + self.registrations_marked_expired
            + self.insurance_marked_expired
            + self.inspections_marked_expired
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _days_until(expiry: date | None, today: date) -> int | None:
    if expiry is None:
        return None
    return (expiry - today).days


def _classify(expiry: date | None, today: date, days_ahead: int) -> str | None:
    """Returns 'expiring', 'expired', or None (not relevant for the window)."""
    if expiry is None:
        return None
    delta = (expiry - today).days
    if delta < 0:
        return "expired"
    if delta <= days_ahead:
        return "expiring"
    return None


# ---------------------------------------------------------------------------
# Single-driver expiry status
# ---------------------------------------------------------------------------

async def get_driver_expiry_status(
    driver_id: int,
    db: AsyncSession,
    days_ahead: int = 30,
) -> ExpiryStatusResult:
    """Return expiry status for all four document types for one driver."""
    today = date.today()
    result = ExpiryStatusResult(driver_id=driver_id)

    # --- Driver licenses ---
    lic_rows = await db.execute(
        select(DriverLicense).where(
            DriverLicense.driver_id == driver_id,
            DriverLicense.status.in_(_ACTIVE_LICENSE_STATUSES),
        )
    )
    for lic in lic_rows.scalars():
        cls = _classify(lic.expiry_date, today, days_ahead)
        if cls:
            doc = ExpiringDocument(
                doc_type="license",
                doc_id=lic.id,
                expiry_date=lic.expiry_date,
                days_until_expiry=_days_until(lic.expiry_date, today),
                status=lic.status.value,
            )
            (result.expired if cls == "expired" else result.expiring).append(doc)

    # --- Vehicle registrations ---
    reg_rows = await db.execute(
        select(VehicleRegistration).where(
            VehicleRegistration.driver_id == driver_id,
            VehicleRegistration.status.in_(_ACTIVE_LICENSE_STATUSES),
        )
    )
    for reg in reg_rows.scalars():
        cls = _classify(reg.expiry_date, today, days_ahead)
        if cls:
            doc = ExpiringDocument(
                doc_type="registration",
                doc_id=reg.id,
                expiry_date=reg.expiry_date,
                days_until_expiry=_days_until(reg.expiry_date, today),
                status=reg.status.value,
            )
            (result.expired if cls == "expired" else result.expiring).append(doc)

    # --- Insurance ---
    ins_rows = await db.execute(
        select(DriverInsuranceDocument).where(
            DriverInsuranceDocument.driver_id == driver_id,
            DriverInsuranceDocument.status.in_(_ACTIVE_INSURANCE_STATUSES),
        )
    )
    for ins in ins_rows.scalars():
        cls = _classify(ins.policy_end_date, today, days_ahead)
        if cls:
            doc = ExpiringDocument(
                doc_type="insurance",
                doc_id=ins.id,
                expiry_date=ins.policy_end_date,
                days_until_expiry=_days_until(ins.policy_end_date, today),
                status=ins.status.value,
            )
            (result.expired if cls == "expired" else result.expiring).append(doc)

    # --- Vehicle inspections ---
    insp_rows = await db.execute(
        select(VehicleInspection).where(
            VehicleInspection.driver_id == driver_id,
            VehicleInspection.status.in_(_ACTIVE_INSPECTION_STATUSES),
            VehicleInspection.expiry_date.isnot(None),
        )
    )
    for insp in insp_rows.scalars():
        cls = _classify(insp.expiry_date, today, days_ahead)
        if cls:
            doc = ExpiringDocument(
                doc_type="inspection",
                doc_id=insp.id,
                expiry_date=insp.expiry_date,
                days_until_expiry=_days_until(insp.expiry_date, today),
                status=insp.status.value,
            )
            (result.expired if cls == "expired" else result.expiring).append(doc)

    return result


# ---------------------------------------------------------------------------
# Admin: all expiring documents
# ---------------------------------------------------------------------------

async def get_all_expiring_documents(
    db: AsyncSession,
    days_ahead: int = 30,
    doc_type: DocType | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[DriverExpiryRow]:
    """Return all driver documents expiring within *days_ahead* days (or already expired)."""
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    rows: list[DriverExpiryRow] = []

    if doc_type is None or doc_type == "license":
        lic_rows = await db.execute(
            select(DriverLicense).where(
                DriverLicense.status.in_(_ACTIVE_LICENSE_STATUSES),
                DriverLicense.expiry_date <= cutoff,
            )
        )
        for lic in lic_rows.scalars():
            rows.append(DriverExpiryRow(
                driver_id=lic.driver_id,
                doc_type="license",
                doc_id=lic.id,
                expiry_date=lic.expiry_date,
                days_until_expiry=_days_until(lic.expiry_date, today),
                status=lic.status.value,
            ))

    if doc_type is None or doc_type == "registration":
        reg_rows = await db.execute(
            select(VehicleRegistration).where(
                VehicleRegistration.status.in_(_ACTIVE_LICENSE_STATUSES),
                VehicleRegistration.expiry_date <= cutoff,
            )
        )
        for reg in reg_rows.scalars():
            rows.append(DriverExpiryRow(
                driver_id=reg.driver_id,
                doc_type="registration",
                doc_id=reg.id,
                expiry_date=reg.expiry_date,
                days_until_expiry=_days_until(reg.expiry_date, today),
                status=reg.status.value,
            ))

    if doc_type is None or doc_type == "insurance":
        ins_rows = await db.execute(
            select(DriverInsuranceDocument).where(
                DriverInsuranceDocument.status.in_(_ACTIVE_INSURANCE_STATUSES),
                DriverInsuranceDocument.policy_end_date <= cutoff,
            )
        )
        for ins in ins_rows.scalars():
            rows.append(DriverExpiryRow(
                driver_id=ins.driver_id,
                doc_type="insurance",
                doc_id=ins.id,
                expiry_date=ins.policy_end_date,
                days_until_expiry=_days_until(ins.policy_end_date, today),
                status=ins.status.value,
            ))

    if doc_type is None or doc_type == "inspection":
        insp_rows = await db.execute(
            select(VehicleInspection).where(
                VehicleInspection.status.in_(_ACTIVE_INSPECTION_STATUSES),
                VehicleInspection.expiry_date.isnot(None),
                VehicleInspection.expiry_date <= cutoff,
            )
        )
        for insp in insp_rows.scalars():
            rows.append(DriverExpiryRow(
                driver_id=insp.driver_id,
                doc_type="inspection",
                doc_id=insp.id,
                expiry_date=insp.expiry_date,
                days_until_expiry=_days_until(insp.expiry_date, today),
                status=insp.status.value,
            ))

    # Sort: expired first, then soonest expiry
    rows.sort(key=lambda r: (
        r.days_until_expiry if r.days_until_expiry is not None else -9999
    ))

    return rows[skip: skip + limit]


# ---------------------------------------------------------------------------
# Bulk expiry scan — mark overdue active documents as EXPIRED
# ---------------------------------------------------------------------------

async def run_expiry_scan(db: AsyncSession) -> ExpiryScaResult:
    """Mark all active documents whose expiry date has passed as EXPIRED.

    Safe to call repeatedly — only affects documents that are still in an
    active status (approved or pending_review).
    """
    today = date.today()
    result = ExpiryScaResult()

    # Licenses
    lic_res = await db.execute(
        update(DriverLicense)
        .where(
            DriverLicense.status.in_(_ACTIVE_LICENSE_STATUSES),
            DriverLicense.expiry_date < today,
        )
        .values(status=DocumentStatus.EXPIRED)
        .execution_options(synchronize_session=False)
    )
    result.licenses_marked_expired = lic_res.rowcount

    # Registrations
    reg_res = await db.execute(
        update(VehicleRegistration)
        .where(
            VehicleRegistration.status.in_(_ACTIVE_LICENSE_STATUSES),
            VehicleRegistration.expiry_date < today,
        )
        .values(status=DocumentStatus.EXPIRED)
        .execution_options(synchronize_session=False)
    )
    result.registrations_marked_expired = reg_res.rowcount

    # Insurance
    ins_res = await db.execute(
        update(DriverInsuranceDocument)
        .where(
            DriverInsuranceDocument.status.in_(_ACTIVE_INSURANCE_STATUSES),
            DriverInsuranceDocument.policy_end_date < today,
        )
        .values(status=InsuranceDocumentStatus.EXPIRED)
        .execution_options(synchronize_session=False)
    )
    result.insurance_marked_expired = ins_res.rowcount

    # Inspections
    insp_res = await db.execute(
        update(VehicleInspection)
        .where(
            VehicleInspection.status.in_(_ACTIVE_INSPECTION_STATUSES),
            VehicleInspection.expiry_date.isnot(None),
            VehicleInspection.expiry_date < today,
        )
        .values(status=InspectionStatus.EXPIRED)
        .execution_options(synchronize_session=False)
    )
    result.inspections_marked_expired = insp_res.rowcount

    await db.commit()
    return result
