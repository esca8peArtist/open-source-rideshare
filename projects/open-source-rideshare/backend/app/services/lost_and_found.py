"""Service layer for the lost and found system.

Business logic for creating, retrieving, and resolving lost and found reports.
All functions that modify state call db.flush() but leave commit to the caller
(FastAPI endpoint layer).

Public functions:
  create_lost_report       — rider submits a lost item report
  create_found_report      — driver submits a found item report
  get_lost_report          — fetch a single lost report (raises on missing)
  get_found_report         — fetch a single found report (raises on missing)
  get_rider_lost_reports   — all reports belonging to a specific rider
  get_driver_found_reports — all reports belonging to a specific driver
  match_reports            — admin links a lost report to a found report
  mark_returned            — admin marks an item as returned to owner
  discard_found_item       — admin records that the item was discarded
  close_lost_report        — admin closes a lost report with no match found
  admin_list_lost_reports  — admin query: all lost reports, filterable by status
  admin_list_found_reports — admin query: all found reports, filterable by status
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.lost_and_found import (
    ContactPreference,
    ItemCategory,
    LafFoundItemReport,
    LafFoundItemStatus,
    LafLostItemReport,
    LafLostItemStatus,
)

logger = logging.getLogger(__name__)


class LostAndFoundError(Exception):
    """Business-logic error raised by the lost and found service.

    status_code maps to the appropriate HTTP response code.
    """

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_LOST_TERMINAL = {LafLostItemStatus.RETURNED, LafLostItemStatus.CLOSED_NO_MATCH}
_FOUND_TERMINAL = {LafFoundItemStatus.RETURNED_TO_OWNER, LafFoundItemStatus.DISCARDED}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_lost(db: AsyncSession, lost_id: int) -> LafLostItemReport:
    result = await db.execute(
        select(LafLostItemReport)
        .options(selectinload(LafLostItemReport.matched_found_report))
        .where(LafLostItemReport.id == lost_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise LostAndFoundError("Lost item report not found", status_code=404)
    return report


async def _load_found(db: AsyncSession, found_id: int) -> LafFoundItemReport:
    result = await db.execute(
        select(LafFoundItemReport)
        .options(selectinload(LafFoundItemReport.matched_lost_report_ref))
        .where(LafFoundItemReport.id == found_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise LostAndFoundError("Found item report not found", status_code=404)
    return report


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def create_lost_report(
    db: AsyncSession,
    rider_id: int,
    description: str,
    category: ItemCategory,
    date_lost: date,
    contact_preference: ContactPreference,
    ride_id: int | None = None,
) -> LafLostItemReport:
    """Rider submits a lost item report.

    If ride_id is provided the rider must have been a participant in that
    ride. Raises LostAndFoundError(404) if the ride does not exist, or
    LostAndFoundError(403) if the rider was not a participant.
    """
    if ride_id is not None:
        from app.models.ride import Ride

        result = await db.execute(select(Ride).where(Ride.id == ride_id))
        ride = result.scalar_one_or_none()
        if not ride:
            raise LostAndFoundError("Ride not found", status_code=404)
        if ride.rider_id != rider_id:
            raise LostAndFoundError(
                "You were not a rider on this ride", status_code=403
            )

    report = LafLostItemReport(
        rider_id=rider_id,
        ride_id=ride_id,
        description=description,
        category=category,
        date_lost=date_lost,
        contact_preference=contact_preference,
        status=LafLostItemStatus.OPEN,
    )
    db.add(report)
    await db.flush()
    return report


async def create_found_report(
    db: AsyncSession,
    driver_id: int,
    description: str,
    category: ItemCategory,
    date_found: date,
    storage_location: str,
    ride_id: int | None = None,
) -> LafFoundItemReport:
    """Driver submits a found item report.

    If ride_id is provided the driver must have driven that ride.
    Raises LostAndFoundError(404) if the ride does not exist, or
    LostAndFoundError(403) if the driver did not drive that ride.
    """
    if ride_id is not None:
        from app.models.ride import Ride

        result = await db.execute(select(Ride).where(Ride.id == ride_id))
        ride = result.scalar_one_or_none()
        if not ride:
            raise LostAndFoundError("Ride not found", status_code=404)
        if ride.driver_id != driver_id:
            raise LostAndFoundError(
                "You were not the driver on this ride", status_code=403
            )

    report = LafFoundItemReport(
        driver_id=driver_id,
        ride_id=ride_id,
        description=description,
        category=category,
        date_found=date_found,
        storage_location=storage_location,
        status=LafFoundItemStatus.PENDING_MATCH,
    )
    db.add(report)
    await db.flush()
    return report


# ---------------------------------------------------------------------------
# Retrieve (single)
# ---------------------------------------------------------------------------


async def get_lost_report(db: AsyncSession, lost_id: int) -> LafLostItemReport:
    """Fetch a single lost item report by ID.

    Raises LostAndFoundError(404) if not found.
    """
    return await _load_lost(db, lost_id)


async def get_found_report(db: AsyncSession, found_id: int) -> LafFoundItemReport:
    """Fetch a single found item report by ID.

    Raises LostAndFoundError(404) if not found.
    """
    return await _load_found(db, found_id)


# ---------------------------------------------------------------------------
# Retrieve (list)
# ---------------------------------------------------------------------------


async def get_rider_lost_reports(
    db: AsyncSession,
    rider_id: int,
    limit: int = 20,
    offset: int = 0,
) -> list[LafLostItemReport]:
    """Return all lost item reports belonging to a specific rider, newest first."""
    result = await db.execute(
        select(LafLostItemReport)
        .options(selectinload(LafLostItemReport.matched_found_report))
        .where(LafLostItemReport.rider_id == rider_id)
        .order_by(LafLostItemReport.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def get_driver_found_reports(
    db: AsyncSession,
    driver_id: int,
    limit: int = 20,
    offset: int = 0,
) -> list[LafFoundItemReport]:
    """Return all found item reports belonging to a specific driver, newest first."""
    result = await db.execute(
        select(LafFoundItemReport)
        .options(selectinload(LafFoundItemReport.matched_lost_report_ref))
        .where(LafFoundItemReport.driver_id == driver_id)
        .order_by(LafFoundItemReport.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def admin_list_lost_reports(
    db: AsyncSession,
    status: LafLostItemStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[LafLostItemReport]:
    """Admin query: list all lost item reports, optionally filtered by status."""
    filters = []
    if status is not None:
        filters.append(LafLostItemReport.status == status)

    query = (
        select(LafLostItemReport)
        .options(selectinload(LafLostItemReport.matched_found_report))
        .order_by(LafLostItemReport.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if filters:
        query = query.where(and_(*filters))

    result = await db.execute(query)
    return list(result.scalars().all())


async def admin_list_found_reports(
    db: AsyncSession,
    status: LafFoundItemStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[LafFoundItemReport]:
    """Admin query: list all found item reports, optionally filtered by status."""
    filters = []
    if status is not None:
        filters.append(LafFoundItemReport.status == status)

    query = (
        select(LafFoundItemReport)
        .options(selectinload(LafFoundItemReport.matched_lost_report_ref))
        .order_by(LafFoundItemReport.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if filters:
        query = query.where(and_(*filters))

    result = await db.execute(query)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Admin actions
# ---------------------------------------------------------------------------


async def match_reports(
    db: AsyncSession,
    lost_id: int,
    found_id: int,
    admin_id: int,
) -> tuple[LafLostItemReport, LafFoundItemReport]:
    """Admin matches a lost report to a found report.

    Sets the lost report to MATCHED and the found report to MATCHED.
    Links each report to the other via their matched_*_id fields.

    Raises LostAndFoundError if:
    - Either report does not exist (404)
    - Either report is already in a terminal state (409)
    - The lost report is already MATCHED (409)
    - The found report is already MATCHED (409)
    """
    lost = await _load_lost(db, lost_id)
    found = await _load_found(db, found_id)

    if lost.status in _LOST_TERMINAL:
        raise LostAndFoundError(
            f"Lost report {lost_id} is already resolved (status: {lost.status.value})",
            status_code=409,
        )
    if found.status in _FOUND_TERMINAL:
        raise LostAndFoundError(
            f"Found report {found_id} is already resolved (status: {found.status.value})",
            status_code=409,
        )
    if lost.status == LafLostItemStatus.MATCHED:
        raise LostAndFoundError(
            f"Lost report {lost_id} is already matched",
            status_code=409,
        )
    if found.status == LafFoundItemStatus.MATCHED:
        raise LostAndFoundError(
            f"Found report {found_id} is already matched",
            status_code=409,
        )

    lost.status = LafLostItemStatus.MATCHED
    lost.matched_found_report_id = found_id

    found.status = LafFoundItemStatus.MATCHED
    found.matched_lost_report_id = lost_id

    await db.flush()

    logger.info(
        "Admin %d matched lost report %d to found report %d",
        admin_id,
        lost_id,
        found_id,
    )

    return lost, found


async def mark_returned(
    db: AsyncSession,
    found_id: int,
    admin_id: int,
) -> tuple[LafFoundItemReport, LafLostItemReport | None]:
    """Admin marks an item as returned to its owner.

    Sets the found report to RETURNED_TO_OWNER.
    If a matched lost report exists, sets it to RETURNED.
    The found report must be in MATCHED status.

    Returns (found_report, lost_report_or_None).
    """
    found = await _load_found(db, found_id)

    if found.status != LafFoundItemStatus.MATCHED:
        raise LostAndFoundError(
            f"Found report must be in MATCHED status to mark as returned "
            f"(current status: {found.status.value})",
            status_code=409,
        )

    now = datetime.now(timezone.utc)
    found.status = LafFoundItemStatus.RETURNED_TO_OWNER
    found.resolved_at = now

    lost: LafLostItemReport | None = None
    if found.matched_lost_report_id is not None:
        lost = await _load_lost(db, found.matched_lost_report_id)
        lost.status = LafLostItemStatus.RETURNED
        lost.resolved_at = now

    await db.flush()
    logger.info("Admin %d marked found report %d as returned to owner", admin_id, found_id)
    return found, lost


async def discard_found_item(
    db: AsyncSession,
    found_id: int,
    admin_id: int,
) -> LafFoundItemReport:
    """Admin records that an unclaimed found item was discarded.

    The found report must not already be in a terminal state.
    """
    found = await _load_found(db, found_id)

    if found.status in _FOUND_TERMINAL:
        raise LostAndFoundError(
            f"Found report {found_id} is already resolved (status: {found.status.value})",
            status_code=409,
        )

    found.status = LafFoundItemStatus.DISCARDED
    found.resolved_at = datetime.now(timezone.utc)

    await db.flush()
    logger.info("Admin %d discarded found report %d", admin_id, found_id)
    return found


async def close_lost_report(
    db: AsyncSession,
    lost_id: int,
    admin_id: int,
) -> LafLostItemReport:
    """Admin closes a lost item report with no match found.

    The lost report must not already be in a terminal state.
    """
    lost = await _load_lost(db, lost_id)

    if lost.status in _LOST_TERMINAL:
        raise LostAndFoundError(
            f"Lost report {lost_id} is already resolved (status: {lost.status.value})",
            status_code=409,
        )

    lost.status = LafLostItemStatus.CLOSED_NO_MATCH
    lost.resolved_at = datetime.now(timezone.utc)

    await db.flush()
    logger.info("Admin %d closed lost report %d with no match", admin_id, lost_id)
    return lost
