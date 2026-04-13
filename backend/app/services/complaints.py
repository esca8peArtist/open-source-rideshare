"""Service layer for the complaint and dispute management feature.

Encapsulates all business logic:
- file_complaint: validate participants, create complaint with PENDING status
- get_my_complaints: complaints filed by a user
- get_complaints_against_me: complaints filed against a user
- admin_list_complaints: paginated admin view with optional status filter
- admin_get_complaint: fetch a single complaint by ID
- admin_update_complaint: update status and notes; enforce terminal-state guard

All mutating functions call db.flush() but leave commit to the caller.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.complaint import Complaint, ComplaintStatus
from app.schemas.complaint import ComplaintCreate, ComplaintUpdateAdmin

logger = logging.getLogger(__name__)

# Statuses that end the complaint lifecycle — no further updates allowed
_TERMINAL_STATUSES = {ComplaintStatus.RESOLVED, ComplaintStatus.DISMISSED}


class ComplaintError(Exception):
    """Business-logic error raised by the complaints service."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


async def file_complaint(
    db: AsyncSession,
    filed_by_user_id: int,
    data: ComplaintCreate,
) -> Complaint:
    """Create a new complaint filed by filed_by_user_id.

    Validates:
    - A user cannot file a complaint against themselves.
    - If ride_id is provided, both filed_by_user_id and against_user_id must
      be participants (rider or driver) in that ride.

    Raises ComplaintError for invalid input.
    """
    if filed_by_user_id == data.against_user_id:
        raise ComplaintError("You cannot file a complaint against yourself", status_code=400)

    if data.ride_id is not None:
        from app.models.ride import Ride

        result = await db.execute(select(Ride).where(Ride.id == data.ride_id))
        ride = result.scalar_one_or_none()
        if not ride:
            raise ComplaintError("Ride not found", status_code=404)

        ride_participant_ids = {ride.rider_id, ride.driver_id}
        if filed_by_user_id not in ride_participant_ids:
            raise ComplaintError(
                "You were not a participant in this ride", status_code=403
            )
        if data.against_user_id not in ride_participant_ids:
            raise ComplaintError(
                "The user you are complaining about was not a participant in this ride",
                status_code=403,
            )

    complaint = Complaint(
        filed_by_user_id=filed_by_user_id,
        against_user_id=data.against_user_id,
        ride_id=data.ride_id,
        category=data.category,
        description=data.description,
        status=ComplaintStatus.PENDING,
    )
    db.add(complaint)
    await db.flush()
    logger.info(
        "Complaint filed by user_id=%d against user_id=%d category=%s",
        filed_by_user_id,
        data.against_user_id,
        data.category.value,
    )
    return complaint


async def get_my_complaints(
    db: AsyncSession,
    user_id: int,
    skip: int = 0,
    limit: int = 20,
) -> List[Complaint]:
    """Return complaints filed BY this user, newest first."""
    result = await db.execute(
        select(Complaint)
        .where(Complaint.filed_by_user_id == user_id)
        .order_by(Complaint.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_complaints_against_me(
    db: AsyncSession,
    user_id: int,
    skip: int = 0,
    limit: int = 20,
) -> List[Complaint]:
    """Return complaints filed against this user, newest first.

    admin_notes are cleared on complaints that are not yet in a terminal state
    so that investigation details are not prematurely disclosed.
    """
    result = await db.execute(
        select(Complaint)
        .where(Complaint.against_user_id == user_id)
        .order_by(Complaint.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    complaints = list(result.scalars().all())

    # Mask admin_notes for non-terminal complaints
    for c in complaints:
        if c.status not in _TERMINAL_STATUSES:
            c.admin_notes = None

    return complaints


async def admin_list_complaints(
    db: AsyncSession,
    status: Optional[ComplaintStatus] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[Complaint]:
    """Admin: list all complaints with optional status filter, newest first."""
    query = (
        select(Complaint)
        .order_by(Complaint.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if status is not None:
        query = query.where(Complaint.status == status)

    result = await db.execute(query)
    return list(result.scalars().all())


async def admin_get_complaint(db: AsyncSession, complaint_id: int) -> Complaint:
    """Admin: fetch a single complaint by ID.

    Raises ComplaintError(404) if not found.
    """
    result = await db.execute(select(Complaint).where(Complaint.id == complaint_id))
    complaint = result.scalar_one_or_none()
    if not complaint:
        raise ComplaintError("Complaint not found", status_code=404)
    return complaint


async def admin_update_complaint(
    db: AsyncSession,
    complaint_id: int,
    admin_id: int,
    data: ComplaintUpdateAdmin,
) -> Complaint:
    """Admin: update the status and notes on a complaint.

    Validates:
    - The complaint must exist.
    - A complaint that is already resolved or dismissed cannot be updated.
    - Status must be one of: reviewing, resolved, dismissed (not pending).

    Sets resolved_by_admin_id when moving to a terminal status.
    Raises ComplaintError for invalid operations.
    """
    complaint = await admin_get_complaint(db, complaint_id)

    if complaint.status in _TERMINAL_STATUSES:
        raise ComplaintError(
            f"Complaint is already {complaint.status.value} and cannot be updated",
            status_code=409,
        )

    if data.status == ComplaintStatus.PENDING:
        raise ComplaintError(
            "Cannot set status back to pending", status_code=400
        )

    complaint.status = data.status
    if data.admin_notes is not None:
        complaint.admin_notes = data.admin_notes

    if data.status in _TERMINAL_STATUSES:
        complaint.resolved_by_admin_id = admin_id

    await db.flush()
    logger.info(
        "Complaint id=%d updated to status=%s by admin_id=%d",
        complaint_id,
        data.status.value,
        admin_id,
    )
    return complaint
