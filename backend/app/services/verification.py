"""Driver verification service.

Manages the document submission and review workflow for driver onboarding.
Required documents must all be approved before a driver can go online.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import DriverProfile
from app.models.verification import (
    DocumentType,
    DriverDocument,
    VerificationStatus,
)

# Documents every driver must have approved
REQUIRED_DOCUMENTS = {
    DocumentType.DRIVERS_LICENSE,
    DocumentType.VEHICLE_REGISTRATION,
    DocumentType.INSURANCE,
}

# Valid status transitions
_VALID_TRANSITIONS = {
    VerificationStatus.PENDING: {VerificationStatus.UNDER_REVIEW, VerificationStatus.REJECTED},
    VerificationStatus.UNDER_REVIEW: {VerificationStatus.APPROVED, VerificationStatus.REJECTED},
    VerificationStatus.REJECTED: {VerificationStatus.PENDING},  # resubmission
    VerificationStatus.APPROVED: {VerificationStatus.EXPIRED},
    VerificationStatus.EXPIRED: {VerificationStatus.PENDING},  # resubmission
}


class VerificationError(Exception):
    pass


async def submit_document(
    db: AsyncSession,
    driver_profile_id: int,
    document_type: DocumentType,
    document_ref: str,
    document_number: str | None = None,
    expiry_date: datetime | None = None,
) -> DriverDocument:
    """Submit a new document or replace a rejected/expired one."""
    # Check for existing active document of this type
    result = await db.execute(
        select(DriverDocument).where(
            DriverDocument.driver_profile_id == driver_profile_id,
            DriverDocument.document_type == document_type,
            DriverDocument.status.in_([
                VerificationStatus.PENDING,
                VerificationStatus.UNDER_REVIEW,
                VerificationStatus.APPROVED,
            ]),
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise VerificationError(
            f"Active {document_type.value} document already exists (status: {existing.status.value})"
        )

    doc = DriverDocument(
        driver_profile_id=driver_profile_id,
        document_type=document_type,
        document_ref=document_ref,
        document_number=document_number,
        expiry_date=expiry_date,
        status=VerificationStatus.PENDING,
    )
    db.add(doc)
    await db.flush()
    return doc


async def review_document(
    db: AsyncSession,
    document_id: int,
    reviewer_id: int,
    new_status: VerificationStatus,
    rejection_reason: str | None = None,
    review_notes: str | None = None,
) -> DriverDocument:
    """Admin reviews a submitted document."""
    result = await db.execute(
        select(DriverDocument).where(DriverDocument.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise VerificationError("Document not found")

    if new_status not in _VALID_TRANSITIONS.get(doc.status, set()):
        raise VerificationError(
            f"Cannot transition from {doc.status.value} to {new_status.value}"
        )

    if new_status == VerificationStatus.REJECTED and not rejection_reason:
        raise VerificationError("Rejection reason is required")

    doc.status = new_status
    doc.reviewed_by = reviewer_id
    doc.reviewed_at = datetime.now(timezone.utc)
    doc.rejection_reason = rejection_reason
    doc.review_notes = review_notes
    await db.flush()

    # If approved, check if all required docs are now approved → auto-approve driver
    if new_status == VerificationStatus.APPROVED:
        await _check_auto_approve(db, doc.driver_profile_id)

    return doc


async def get_verification_status(
    db: AsyncSession, driver_profile_id: int
) -> dict:
    """Get summary of a driver's verification status."""
    result = await db.execute(
        select(DriverDocument).where(
            DriverDocument.driver_profile_id == driver_profile_id
        )
    )
    docs = result.scalars().all()

    doc_statuses = {}
    for doc in docs:
        # Keep the most recent document per type
        existing = doc_statuses.get(doc.document_type)
        if not existing or doc.submitted_at > existing.submitted_at:
            doc_statuses[doc.document_type] = doc

    missing = REQUIRED_DOCUMENTS - set(doc_statuses.keys())
    approved = {
        dt for dt, doc in doc_statuses.items()
        if doc.status == VerificationStatus.APPROVED
    }
    all_approved = REQUIRED_DOCUMENTS.issubset(approved)

    return {
        "documents": list(doc_statuses.values()),
        "missing_required": [dt.value for dt in missing],
        "all_required_approved": all_approved,
    }


async def _check_auto_approve(db: AsyncSession, driver_profile_id: int) -> None:
    """If all required documents are approved, auto-approve the driver."""
    status = await get_verification_status(db, driver_profile_id)
    if status["all_required_approved"]:
        result = await db.execute(
            select(DriverProfile).where(DriverProfile.id == driver_profile_id)
        )
        profile = result.scalar_one_or_none()
        if profile and not profile.is_approved:
            profile.is_approved = True
            profile.background_check_status = "approved"
