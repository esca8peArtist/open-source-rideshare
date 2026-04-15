"""Service layer for driver tax reporting and 1099-NEC generation.

Handles:
  - W-9 / tax profile management (stores TIN last-4 only)
  - Annual earnings calculation from completed payouts
  - 1099-NEC document generation (threshold: $600 gross)
  - Admin batch generation and IRS submission tracking

IRS threshold: drivers with $600+ gross earnings in a calendar year receive a
1099-NEC.  Below that threshold an earnings_summary is generated instead.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import and_, distinct, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import DriverProfile
from app.models.driver_tax_document import (
    DriverTaxDocument,
    DriverTaxProfile,
    TaxDocumentStatus,
    TaxDocumentType,
    TinType,
)
from app.models.payout import DriverPayout, PayoutStatus

logger = logging.getLogger(__name__)

# IRS 1099-NEC threshold in cents ($600.00)
NEC_THRESHOLD_CENTS = 60_000


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Tax profile
# ---------------------------------------------------------------------------


async def get_or_create_tax_profile(
    db: AsyncSession,
    driver_profile_id: int,
) -> DriverTaxProfile:
    """Return the existing tax profile or create a blank one."""
    result = await db.execute(
        select(DriverTaxProfile).where(
            DriverTaxProfile.driver_profile_id == driver_profile_id
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = DriverTaxProfile(driver_profile_id=driver_profile_id)
        db.add(profile)
        await db.flush()
        await db.refresh(profile)
    return profile


async def update_w9(
    db: AsyncSession,
    driver_profile_id: int,
    tin_type: TinType,
    tin_last4: str,
    business_name: str | None = None,
) -> DriverTaxProfile:
    """Record W-9 information for a driver.

    Only the last 4 digits of the TIN are accepted.  Callers must strip the
    full TIN before calling this function.
    """
    if len(tin_last4) != 4 or not tin_last4.isdigit():
        raise HTTPException(
            status_code=422,
            detail="tin_last4 must be exactly 4 digits.",
        )

    profile = await get_or_create_tax_profile(db, driver_profile_id)
    profile.tin_type = tin_type
    profile.tin_last4 = tin_last4
    profile.business_name = business_name
    profile.has_w9 = True
    profile.w9_received_at = _now()
    await db.flush()
    await db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------
# Earnings calculation
# ---------------------------------------------------------------------------


async def calculate_annual_earnings(
    db: AsyncSession,
    driver_profile_id: int,
    tax_year: int,
) -> dict:
    """Sum completed payouts for a driver within a calendar year.

    Resolves driver_profile_id → user_id via DriverProfile, then queries
    DriverPayout (which references users.id).

    Returns a dict with:
      gross_earnings_cents  — total_amount converted to cents
      rides_count           — total trips covered by completed payouts
    """
    # Resolve user_id from driver_profile_id
    profile_result = await db.execute(
        select(DriverProfile.user_id).where(DriverProfile.id == driver_profile_id)
    )
    row = profile_result.scalar_one_or_none()
    if row is None:
        return {"gross_earnings_cents": 0, "rides_count": 0}
    user_id = row

    result = await db.execute(
        select(
            func.coalesce(
                func.sum(func.round(DriverPayout.total_amount * 100)),
                0,
            ).label("gross_cents"),
            func.coalesce(func.sum(DriverPayout.trip_count), 0).label("rides_count"),
        ).where(
            and_(
                DriverPayout.driver_id == user_id,
                DriverPayout.status == PayoutStatus.COMPLETED,
                extract("year", DriverPayout.completed_at) == tax_year,
            )
        )
    )
    earnings_row = result.one()
    return {
        "gross_earnings_cents": int(earnings_row.gross_cents or 0),
        "rides_count": int(earnings_row.rides_count or 0),
    }


# ---------------------------------------------------------------------------
# Document generation
# ---------------------------------------------------------------------------


async def generate_tax_document(
    db: AsyncSession,
    driver_profile_id: int,
    tax_year: int,
) -> DriverTaxDocument:
    """Create or update the tax document for a driver for a given year.

    If gross earnings >= $600 the document type is 1099_nec with status
    ready.  Otherwise an earnings_summary is created.
    """
    earnings = await calculate_annual_earnings(db, driver_profile_id, tax_year)
    gross_cents = earnings["gross_earnings_cents"]
    rides_count = earnings["rides_count"]

    if gross_cents >= NEC_THRESHOLD_CENTS:
        doc_type = TaxDocumentType.nec_1099
        nec_cents = gross_cents
    else:
        doc_type = TaxDocumentType.earnings_summary
        nec_cents = 0

    # Upsert: find existing doc for this driver / year / type
    existing = await db.execute(
        select(DriverTaxDocument).where(
            and_(
                DriverTaxDocument.driver_profile_id == driver_profile_id,
                DriverTaxDocument.tax_year == tax_year,
                DriverTaxDocument.document_type == doc_type,
            )
        )
    )
    doc = existing.scalar_one_or_none()

    if doc is None:
        doc = DriverTaxDocument(
            driver_profile_id=driver_profile_id,
            tax_year=tax_year,
            document_type=doc_type,
        )
        db.add(doc)

    doc.status = TaxDocumentStatus.ready
    doc.gross_earnings_cents = gross_cents
    doc.nonemployee_compensation_cents = nec_cents
    doc.rides_count = rides_count
    doc.generated_at = _now()

    await db.flush()
    await db.refresh(doc)
    return doc


# ---------------------------------------------------------------------------
# Retrieval helpers
# ---------------------------------------------------------------------------


async def get_driver_tax_documents(
    db: AsyncSession,
    driver_profile_id: int,
) -> list[DriverTaxDocument]:
    """Return all tax documents for a driver, newest year first."""
    result = await db.execute(
        select(DriverTaxDocument)
        .where(DriverTaxDocument.driver_profile_id == driver_profile_id)
        .order_by(DriverTaxDocument.tax_year.desc())
    )
    return list(result.scalars().all())


async def get_driver_tax_documents_for_year(
    db: AsyncSession,
    driver_profile_id: int,
    tax_year: int,
) -> list[DriverTaxDocument]:
    """Return tax documents for a driver for a specific year."""
    result = await db.execute(
        select(DriverTaxDocument).where(
            and_(
                DriverTaxDocument.driver_profile_id == driver_profile_id,
                DriverTaxDocument.tax_year == tax_year,
            )
        )
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Admin functions
# ---------------------------------------------------------------------------


async def admin_get_tax_documents(
    db: AsyncSession,
    tax_year: int,
    status: TaxDocumentStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[DriverTaxDocument]:
    """List all drivers' tax documents for a given year with optional status filter."""
    query = select(DriverTaxDocument).where(
        DriverTaxDocument.tax_year == tax_year
    )
    if status is not None:
        query = query.where(DriverTaxDocument.status == status)
    query = query.order_by(DriverTaxDocument.driver_profile_id).limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


async def admin_batch_generate(
    db: AsyncSession,
    tax_year: int,
) -> dict:
    """Generate tax documents for all drivers that have completed payouts for the year.

    Resolves user_id → driver_profile_id via DriverProfile join.
    Returns a summary dict with generated, skipped, and errors counts.
    """
    # Find all distinct user_ids with completed payouts in tax_year.
    result = await db.execute(
        select(distinct(DriverPayout.driver_id)).where(
            and_(
                DriverPayout.status == PayoutStatus.COMPLETED,
                extract("year", DriverPayout.completed_at) == tax_year,
            )
        )
    )
    user_ids = [row[0] for row in result.all()]

    # Resolve to driver_profile_ids
    profile_result = await db.execute(
        select(DriverProfile.id).where(DriverProfile.user_id.in_(user_ids))
    )
    driver_profile_ids = [row[0] for row in profile_result.all()]

    generated = 0
    skipped = 0
    errors = 0

    for driver_profile_id in driver_profile_ids:
        try:
            await generate_tax_document(db, driver_profile_id, tax_year)
            generated += 1
        except Exception as exc:
            logger.error(
                "Failed to generate tax doc for driver_profile_id=%s year=%s: %s",
                driver_profile_id,
                tax_year,
                exc,
            )
            errors += 1

    return {"generated": generated, "skipped": skipped, "errors": errors}


async def mark_submitted(
    db: AsyncSession,
    document_id: int,
    admin_notes: str | None = None,
) -> DriverTaxDocument:
    """Mark a tax document as submitted to the IRS."""
    result = await db.execute(
        select(DriverTaxDocument).where(DriverTaxDocument.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Tax document not found.")

    doc.status = TaxDocumentStatus.submitted_to_irs
    doc.submitted_at = _now()
    if admin_notes is not None:
        doc.admin_notes = admin_notes

    await db.flush()
    await db.refresh(doc)
    return doc
