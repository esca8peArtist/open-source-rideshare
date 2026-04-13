"""Service layer for driver insurance document management."""

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_insurance import (
    DriverInsuranceDocument,
    InsuranceDocumentStatus,
)
from app.schemas.driver_insurance import (
    AdminReviewRequest,
    InsuranceDocumentCreate,
    InsuranceDocumentUpdate,
    InsuranceDocumentResponse,
    InsuranceStatusSummary,
)


class InsuranceDocumentError(Exception):
    """Raised for insurance document business logic violations."""


async def get_driver_insurance_documents(
    db: AsyncSession,
    driver_id: int,
) -> list[DriverInsuranceDocument]:
    """Return all insurance documents for a driver, newest first."""
    result = await db.execute(
        select(DriverInsuranceDocument)
        .where(DriverInsuranceDocument.driver_id == driver_id)
        .order_by(DriverInsuranceDocument.created_at.desc())
    )
    return list(result.scalars().all())


async def get_latest_approved_insurance(
    db: AsyncSession,
    driver_id: int,
) -> Optional[DriverInsuranceDocument]:
    """Return the most recent approved, non-expired insurance document."""
    today = date.today()
    result = await db.execute(
        select(DriverInsuranceDocument)
        .where(
            and_(
                DriverInsuranceDocument.driver_id == driver_id,
                DriverInsuranceDocument.status == InsuranceDocumentStatus.APPROVED,
                DriverInsuranceDocument.policy_end_date >= today,
            )
        )
        .order_by(DriverInsuranceDocument.policy_end_date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_insurance_document(
    db: AsyncSession,
    driver_id: int,
    data: InsuranceDocumentCreate,
) -> DriverInsuranceDocument:
    """Create a new insurance document record.

    If a document_url is provided the status starts as pending_review;
    otherwise pending_upload until the driver attaches the file.
    """
    initial_status = (
        InsuranceDocumentStatus.PENDING_REVIEW
        if data.document_url
        else InsuranceDocumentStatus.PENDING_UPLOAD
    )
    doc = DriverInsuranceDocument(
        driver_id=driver_id,
        status=initial_status,
        **data.model_dump(),
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


async def update_insurance_document(
    db: AsyncSession,
    driver_id: int,
    doc_id: int,
    data: InsuranceDocumentUpdate,
) -> DriverInsuranceDocument:
    """Update a driver's own pending document.

    Raises InsuranceDocumentError if the document cannot be edited.
    """
    result = await db.execute(
        select(DriverInsuranceDocument).where(DriverInsuranceDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise InsuranceDocumentError("Document not found")
    if doc.driver_id != driver_id:
        raise InsuranceDocumentError("Not authorised to edit this document")
    editable_statuses = {
        InsuranceDocumentStatus.PENDING_UPLOAD,
        InsuranceDocumentStatus.PENDING_REVIEW,
    }
    if doc.status not in editable_statuses:
        raise InsuranceDocumentError(
            f"Cannot edit a document with status '{doc.status.value}'"
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(doc, field, value)

    # Promote to pending_review once a URL has been attached
    if doc.document_url and doc.status == InsuranceDocumentStatus.PENDING_UPLOAD:
        doc.status = InsuranceDocumentStatus.PENDING_REVIEW

    await db.commit()
    await db.refresh(doc)
    return doc


async def admin_review_document(
    db: AsyncSession,
    admin_id: int,
    doc_id: int,
    review: AdminReviewRequest,
) -> DriverInsuranceDocument:
    """Approve or reject a document as an admin.

    On approval any previously approved document for the same driver is
    expired so only one approved document is active at a time.
    """
    result = await db.execute(
        select(DriverInsuranceDocument).where(DriverInsuranceDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise InsuranceDocumentError("Document not found")

    if review.status == InsuranceDocumentStatus.APPROVED:
        # Expire any currently approved document for this driver
        prev_result = await db.execute(
            select(DriverInsuranceDocument).where(
                and_(
                    DriverInsuranceDocument.driver_id == doc.driver_id,
                    DriverInsuranceDocument.status == InsuranceDocumentStatus.APPROVED,
                    DriverInsuranceDocument.id != doc_id,
                )
            )
        )
        for prev_doc in prev_result.scalars().all():
            prev_doc.status = InsuranceDocumentStatus.EXPIRED

    doc.status = review.status
    doc.rejection_reason = review.rejection_reason
    doc.verified_by = admin_id
    doc.verified_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(doc)
    return doc


async def get_insurance_status_summary(
    db: AsyncSession,
    driver_id: int,
) -> InsuranceStatusSummary:
    """Return a high-level insurance status for a driver."""
    documents = await get_driver_insurance_documents(db, driver_id)
    active_doc = await get_latest_approved_insurance(db, driver_id)

    has_valid = active_doc is not None
    days_until_expiry: Optional[int] = None
    if active_doc:
        days_until_expiry = (active_doc.policy_end_date - date.today()).days

    doc_responses = [InsuranceDocumentResponse.model_validate(d) for d in documents]
    active_response = (
        InsuranceDocumentResponse.model_validate(active_doc) if active_doc else None
    )

    return InsuranceStatusSummary(
        has_valid_insurance=has_valid,
        days_until_expiry=days_until_expiry,
        active_document=active_response,
        documents=doc_responses,
    )


async def get_expiring_documents(
    db: AsyncSession,
    days_ahead: int,
) -> list[DriverInsuranceDocument]:
    """Return approved documents whose policy_end_date falls within *days_ahead* days."""
    today = date.today()
    from datetime import timedelta

    cutoff = today + timedelta(days=days_ahead)
    result = await db.execute(
        select(DriverInsuranceDocument).where(
            and_(
                DriverInsuranceDocument.status == InsuranceDocumentStatus.APPROVED,
                DriverInsuranceDocument.policy_end_date >= today,
                DriverInsuranceDocument.policy_end_date <= cutoff,
            )
        )
    )
    return list(result.scalars().all())


async def mark_expired_documents(db: AsyncSession) -> int:
    """Batch-update approved documents whose policy_end_date is in the past.

    Returns the number of documents updated.
    """
    today = date.today()
    result = await db.execute(
        select(DriverInsuranceDocument).where(
            and_(
                DriverInsuranceDocument.status == InsuranceDocumentStatus.APPROVED,
                DriverInsuranceDocument.policy_end_date < today,
            )
        )
    )
    docs = list(result.scalars().all())
    for doc in docs:
        doc.status = InsuranceDocumentStatus.EXPIRED
    if docs:
        await db.commit()
    return len(docs)
