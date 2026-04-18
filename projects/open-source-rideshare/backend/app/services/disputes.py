"""Dispute service.

Handles the full dispute lifecycle: filing, admin review, and resolution.
Disputes can be filed by either rider or driver on completed or cancelled rides.
Admin resolves disputes with notes and optional refund amount.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import Dispute, DisputeStatus, DisputeType
from app.models.ride import Ride, RideStatus


async def file_dispute(
    ride_id: int,
    user_id: int,
    dispute_type: str,
    description: str,
    db: AsyncSession,
) -> Dispute:
    """File a new dispute on a ride.

    - Validates ride exists and is completed or cancelled
    - Prevents duplicate open disputes from same user on same ride
    - Only rider or driver of the ride can file
    """
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()

    if not ride:
        raise ValueError("Ride not found")
    if ride.status not in (RideStatus.COMPLETED, RideStatus.CANCELLED):
        raise ValueError("Disputes can only be filed on completed or cancelled rides")
    if ride.rider_id != user_id and ride.driver_id != user_id:
        raise PermissionError("Not authorized — only ride participants can file disputes")

    # Check for existing open dispute from this user on this ride
    existing = await db.execute(
        select(Dispute).where(
            Dispute.ride_id == ride_id,
            Dispute.filed_by == user_id,
            Dispute.status.in_([DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW]),
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("An open dispute already exists for this ride")

    dispute = Dispute(
        ride_id=ride_id,
        filed_by=user_id,
        dispute_type=DisputeType(dispute_type),
        status=DisputeStatus.OPEN,
        description=description,
    )
    db.add(dispute)
    await db.commit()
    await db.refresh(dispute)

    other_party_id = ride.driver_id if user_id == ride.rider_id else ride.rider_id
    if other_party_id is not None:
        from app.services.notification_events import notify_dispute_filed
        asyncio.ensure_future(notify_dispute_filed(db, other_party_id, ride_id, dispute_type))

    return dispute


async def get_dispute(
    dispute_id: int,
    db: AsyncSession,
) -> Dispute | None:
    """Get a single dispute by ID."""
    result = await db.execute(select(Dispute).where(Dispute.id == dispute_id))
    return result.scalar_one_or_none()


async def list_disputes(
    db: AsyncSession,
    status_filter: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Dispute], int]:
    """List disputes with optional status filter. For admin use."""
    query = select(Dispute)
    if status_filter:
        query = query.where(Dispute.status == DisputeStatus(status_filter))

    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    query = query.order_by(Dispute.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def update_dispute_status(
    dispute_id: int,
    new_status: str,
    db: AsyncSession,
) -> Dispute | None:
    """Move a dispute to under_review. Admin only."""
    dispute = await get_dispute(dispute_id, db)
    if not dispute:
        return None
    if dispute.status != DisputeStatus.OPEN:
        raise ValueError("Can only review open disputes")

    dispute.status = DisputeStatus(new_status)
    await db.commit()
    await db.refresh(dispute)
    return dispute


async def resolve_dispute(
    dispute_id: int,
    admin_id: int,
    resolution_status: str,
    resolution_notes: str,
    refund_amount: float | None,
    db: AsyncSession,
) -> Dispute | None:
    """Resolve a dispute. Admin only.

    Sets the resolution status, notes, optional refund, and timestamps.
    """
    dispute = await get_dispute(dispute_id, db)
    if not dispute:
        return None
    if dispute.status not in (DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW):
        raise ValueError("Dispute is already resolved")

    dispute.status = DisputeStatus(resolution_status)
    dispute.resolution_notes = resolution_notes
    dispute.resolved_by = admin_id
    dispute.refund_amount = refund_amount
    dispute.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(dispute)

    from app.services.notification_events import notify_dispute_resolved
    asyncio.ensure_future(notify_dispute_resolved(db, dispute.filed_by, dispute.ride_id, resolution_status))

    return dispute


async def add_respondent_reply(
    dispute_id: int,
    user_id: int,
    response_text: str,
    db: AsyncSession,
) -> Dispute:
    """Submit the respondent's side of the dispute.

    Only the non-filing participant of the ride can respond.
    Can only respond while dispute is OPEN or UNDER_REVIEW.
    Only one response allowed (idempotent).
    """
    dispute = await get_dispute(dispute_id, db)
    if not dispute:
        raise ValueError("Dispute not found")

    if dispute.status not in (DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW):
        raise ValueError("Dispute is no longer accepting responses")

    result = await db.execute(select(Ride).where(Ride.id == dispute.ride_id))
    ride = result.scalar_one_or_none()

    other_party_id = ride.rider_id if dispute.filed_by == ride.driver_id else ride.driver_id

    if user_id != other_party_id:
        raise PermissionError("Only the other ride participant can respond")

    if dispute.respondent_response is not None:
        raise ValueError("A response has already been submitted")

    dispute.respondent_response = response_text
    dispute.respondent_responded_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(dispute)

    from app.services.notification_events import notify_dispute_response_received
    asyncio.ensure_future(notify_dispute_response_received(db, dispute.filed_by, dispute.ride_id))

    return dispute


async def get_user_disputes(
    user_id: int,
    db: AsyncSession,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Dispute], int]:
    """Get disputes filed by a specific user."""
    query = select(Dispute).where(Dispute.filed_by == user_id)

    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    query = query.order_by(Dispute.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all()), total
