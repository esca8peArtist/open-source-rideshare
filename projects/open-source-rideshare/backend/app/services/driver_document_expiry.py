"""Scheduled document-expiry check service for OpenRide.

This module provides the logic that a cron job or scheduler calls to:
  1. Find all approved driver documents expiring within a given horizon.
  2. Send the appropriate notification (warning or expired) for each document.

Three document types are covered:
  - Driver's license  (DriverLicense, expiry_date field)
  - Vehicle registration  (VehicleRegistration, expiry_date field)
  - Vehicle insurance  (DriverInsuranceDocument, policy_end_date field)

The public entry-points are:
  get_expiring_documents(db, days_ahead)  — pure query, no side-effects
  send_document_expiry_notifications(db, days_ahead)  — query + notify
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Imported here so tests can patch them on this module.
from app.services.notification_events import (  # noqa: E402
    notify_document_expiry_warning,
    notify_document_expired,
)

# Alert thresholds (days before expiry) that trigger a warning notification.
EXPIRY_WARNING_THRESHOLDS = (30, 14, 7, 1)

# Human-readable labels used in notification templates.
_DOCUMENT_TYPE_LABELS = {
    "license": "license",
    "vehicle_registration": "vehicle_registration",
    "vehicle_insurance": "vehicle_insurance",
}


@dataclass
class ExpiringDocument:
    """Lightweight record of a single expiring/expired document."""

    driver_id: int
    document_type: str          # "license" | "vehicle_registration" | "vehicle_insurance"
    expiry_date: date
    document_id: int
    days_remaining: int         # negative means already expired


async def get_expiring_documents(
    db: AsyncSession,
    days_ahead: int,
) -> list[ExpiringDocument]:
    """Return all approved driver documents expiring within *days_ahead* days.

    This is the function a scheduler would call to drive the notification
    pipeline.  It covers all three document types (license, registration,
    insurance) and includes documents that have already expired (days_remaining
    < 0) so that expiry-day (day 0) and past-due alerts can be issued.

    Args:
        db: SQLAlchemy async session.
        days_ahead: Look-ahead window in days.  Documents expiring on or before
            ``today + days_ahead`` are returned.  Pass 0 to get only documents
            that expire today or are already past due.

    Returns:
        List of :class:`ExpiringDocument` sorted by (document_type, days_remaining).
    """
    from sqlalchemy import and_, select
    from app.models.driver_documents import DocumentStatus, DriverLicense, VehicleRegistration
    from app.models.driver_insurance import DriverInsuranceDocument, InsuranceDocumentStatus

    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    results: list[ExpiringDocument] = []

    # --- Driver's licenses ---
    license_result = await db.execute(
        select(DriverLicense).where(
            and_(
                DriverLicense.status == DocumentStatus.APPROVED,
                DriverLicense.expiry_date <= cutoff,
            )
        )
    )
    for lic in license_result.scalars().all():
        results.append(
            ExpiringDocument(
                driver_id=lic.driver_id,
                document_type="license",
                expiry_date=lic.expiry_date,
                document_id=lic.id,
                days_remaining=(lic.expiry_date - today).days,
            )
        )

    # --- Vehicle registrations ---
    reg_result = await db.execute(
        select(VehicleRegistration).where(
            and_(
                VehicleRegistration.status == DocumentStatus.APPROVED,
                VehicleRegistration.expiry_date <= cutoff,
            )
        )
    )
    for reg in reg_result.scalars().all():
        results.append(
            ExpiringDocument(
                driver_id=reg.driver_id,
                document_type="vehicle_registration",
                expiry_date=reg.expiry_date,
                document_id=reg.id,
                days_remaining=(reg.expiry_date - today).days,
            )
        )

    # --- Vehicle insurance ---
    ins_result = await db.execute(
        select(DriverInsuranceDocument).where(
            and_(
                DriverInsuranceDocument.status == InsuranceDocumentStatus.APPROVED,
                DriverInsuranceDocument.policy_end_date <= cutoff,
            )
        )
    )
    for ins in ins_result.scalars().all():
        results.append(
            ExpiringDocument(
                driver_id=ins.driver_id,
                document_type="vehicle_insurance",
                expiry_date=ins.policy_end_date,
                document_id=ins.id,
                days_remaining=(ins.policy_end_date - today).days,
            )
        )

    results.sort(key=lambda d: (d.document_type, d.days_remaining))
    return results


async def get_expiring_documents_for_driver(
    db: AsyncSession,
    driver_id: int,
    days_ahead: int = 60,
) -> list[ExpiringDocument]:
    """Return expiring or expired documents for a single driver.

    Mirrors :func:`get_expiring_documents` but scoped to one driver so the
    driver-facing endpoint avoids scanning the entire document table.

    Args:
        db: SQLAlchemy async session.
        driver_id: User ID of the driver (``users.id`` — same FK used by
            DriverLicense, VehicleRegistration, and DriverInsuranceDocument).
        days_ahead: Look-ahead window in days.  Documents expiring on or before
            ``today + days_ahead`` are returned.  Pass 0 to get only documents
            that expire today or are already past due.

    Returns:
        List of :class:`ExpiringDocument` sorted by days_remaining ascending
        (most urgent first).
    """
    from sqlalchemy import and_, select
    from app.models.driver_documents import DocumentStatus, DriverLicense, VehicleRegistration
    from app.models.driver_insurance import DriverInsuranceDocument, InsuranceDocumentStatus

    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    results: list[ExpiringDocument] = []

    lic_result = await db.execute(
        select(DriverLicense).where(
            and_(
                DriverLicense.driver_id == driver_id,
                DriverLicense.status == DocumentStatus.APPROVED,
                DriverLicense.expiry_date <= cutoff,
            )
        )
    )
    for lic in lic_result.scalars().all():
        results.append(
            ExpiringDocument(
                driver_id=lic.driver_id,
                document_type="license",
                expiry_date=lic.expiry_date,
                document_id=lic.id,
                days_remaining=(lic.expiry_date - today).days,
            )
        )

    reg_result = await db.execute(
        select(VehicleRegistration).where(
            and_(
                VehicleRegistration.driver_id == driver_id,
                VehicleRegistration.status == DocumentStatus.APPROVED,
                VehicleRegistration.expiry_date <= cutoff,
            )
        )
    )
    for reg in reg_result.scalars().all():
        results.append(
            ExpiringDocument(
                driver_id=reg.driver_id,
                document_type="vehicle_registration",
                expiry_date=reg.expiry_date,
                document_id=reg.id,
                days_remaining=(reg.expiry_date - today).days,
            )
        )

    ins_result = await db.execute(
        select(DriverInsuranceDocument).where(
            and_(
                DriverInsuranceDocument.driver_id == driver_id,
                DriverInsuranceDocument.status == InsuranceDocumentStatus.APPROVED,
                DriverInsuranceDocument.policy_end_date <= cutoff,
            )
        )
    )
    for ins in ins_result.scalars().all():
        results.append(
            ExpiringDocument(
                driver_id=ins.driver_id,
                document_type="vehicle_insurance",
                expiry_date=ins.policy_end_date,
                document_id=ins.id,
                days_remaining=(ins.policy_end_date - today).days,
            )
        )

    results.sort(key=lambda d: d.days_remaining)
    return results


async def has_valid_documents(db: AsyncSession, driver_id: int) -> bool:
    """Return True if the driver holds all three required, non-expired, approved documents.

    The three requirements are:
      - At least one APPROVED DriverLicense whose expiry_date >= today (or is None).
      - At least one APPROVED VehicleRegistration whose expiry_date >= today (or is None).
      - At least one APPROVED DriverInsuranceDocument whose policy_end_date >= today
        (or is None).

    A None expiry date is treated as "no expiry known" — the document is considered
    valid because requiring a date that the data model marks non-nullable would
    incorrectly block drivers with data inserted before any nullable migration.
    In practice, the ORM columns are currently non-nullable so the None branch is
    a defensive safeguard for future schema changes.

    Returns False if any of the three document types is absent, expired, or not yet
    approved.  Uses ``date.today()`` (not datetime) for comparisons.

    Args:
        db: SQLAlchemy async session.
        driver_id: ID of the DriverProfile (not the User) whose documents to check.

    Returns:
        True when all three document requirements are satisfied, False otherwise.
    """
    from sqlalchemy import and_, or_, select
    from app.models.driver_documents import DocumentStatus, DriverLicense, VehicleRegistration
    from app.models.driver_insurance import DriverInsuranceDocument, InsuranceDocumentStatus

    today = date.today()

    # --- Driver's license ---
    lic_result = await db.execute(
        select(DriverLicense).where(
            and_(
                DriverLicense.driver_id == driver_id,
                DriverLicense.status == DocumentStatus.APPROVED,
                or_(
                    DriverLicense.expiry_date.is_(None),
                    DriverLicense.expiry_date >= today,
                ),
            )
        ).limit(1)
    )
    if lic_result.scalars().first() is None:
        return False

    # --- Vehicle registration ---
    reg_result = await db.execute(
        select(VehicleRegistration).where(
            and_(
                VehicleRegistration.driver_id == driver_id,
                VehicleRegistration.status == DocumentStatus.APPROVED,
                or_(
                    VehicleRegistration.expiry_date.is_(None),
                    VehicleRegistration.expiry_date >= today,
                ),
            )
        ).limit(1)
    )
    if reg_result.scalars().first() is None:
        return False

    # --- Vehicle insurance ---
    ins_result = await db.execute(
        select(DriverInsuranceDocument).where(
            and_(
                DriverInsuranceDocument.driver_id == driver_id,
                DriverInsuranceDocument.status == InsuranceDocumentStatus.APPROVED,
                or_(
                    DriverInsuranceDocument.policy_end_date.is_(None),
                    DriverInsuranceDocument.policy_end_date >= today,
                ),
            )
        ).limit(1)
    )
    if ins_result.scalars().first() is None:
        return False

    return True


async def send_document_expiry_notifications(
    db: AsyncSession,
    days_ahead: int = 30,
) -> int:
    """Query expiring documents and dispatch notifications for each one.

    Intended to be called by a daily cron job.  Notifications are sent for:
      - Documents expiring within *days_ahead* days (warning).
      - Documents that have already expired (expired alert).

    Failures per document are logged but never raised — one bad notification
    must not prevent others from being sent.

    Args:
        db: SQLAlchemy async session.
        days_ahead: Look-ahead window forwarded to :func:`get_expiring_documents`.

    Returns:
        Number of notifications successfully dispatched.
    """
    docs = await get_expiring_documents(db, days_ahead)
    dispatched = 0

    for doc in docs:
        try:
            expiry_str = doc.expiry_date.isoformat()
            if doc.days_remaining < 0:
                await notify_document_expired(
                    db=db,
                    driver_id=doc.driver_id,
                    document_type=doc.document_type,
                    expiry_date=expiry_str,
                    days_overdue=abs(doc.days_remaining),
                )
            elif doc.days_remaining == 0:
                await notify_document_expired(
                    db=db,
                    driver_id=doc.driver_id,
                    document_type=doc.document_type,
                    expiry_date=expiry_str,
                    days_overdue=0,
                )
            else:
                await notify_document_expiry_warning(
                    db=db,
                    driver_id=doc.driver_id,
                    document_type=doc.document_type,
                    expiry_date=expiry_str,
                    days_remaining=doc.days_remaining,
                )
            dispatched += 1
        except Exception:
            logger.exception(
                "Failed to dispatch expiry notification for driver %d document %s (id=%d)",
                doc.driver_id,
                doc.document_type,
                doc.document_id,
            )

    return dispatched
