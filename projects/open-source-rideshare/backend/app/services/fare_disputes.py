"""Service layer for fare dispute & refund operations.

All public functions are async and accept an AsyncSession.

Key rules
---------
- Only COMPLETED rides can be disputed.
- Only the rider on the ride can file a dispute.
- Only one non-withdrawn dispute per ride (uniqueness enforced here, not DB).
- disputed_amount cannot exceed the ride's actual_fare.
- Only PENDING disputes can be withdrawn by the rider.
- Admins can only resolve PENDING or UNDER_REVIEW disputes.
- On APPROVED/PARTIAL, refund_amount is required and must be ≤ disputed_amount.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fare_dispute import (
    REFUND_STATUSES,
    TERMINAL_STATUSES,
    DisputeStatus,
    FareDispute,
)
from app.models.ride import Ride, RideStatus

DEFAULT_PAGE_SIZE = 20


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get_ride_for_rider(
    db: AsyncSession, ride_id: int, rider_user_id: int
) -> Ride | None:
    """Return the ride if it exists and belongs to this rider."""
    result = await db.execute(
        select(Ride).where(Ride.id == ride_id, Ride.rider_id == rider_user_id)
    )
    return result.scalar_one_or_none()


async def _active_dispute_for_ride(
    db: AsyncSession, ride_id: int
) -> FareDispute | None:
    """Return any non-withdrawn dispute already open for this ride."""
    result = await db.execute(
        select(FareDispute).where(
            FareDispute.ride_id == ride_id,
            FareDispute.status != DisputeStatus.WITHDRAWN,
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Rider-facing operations
# ---------------------------------------------------------------------------

async def create_dispute(
    db: AsyncSession,
    *,
    ride_id: int,
    rider_user_id: int,
    category: str,
    description: str,
    disputed_amount: float,
) -> tuple[FareDispute | None, str | None]:
    """Create a new fare dispute.

    Returns (dispute, None) on success or (None, error_message) on failure.
    """
    ride = await _get_ride_for_rider(db, ride_id, rider_user_id)
    if ride is None:
        return None, "Ride not found or does not belong to this rider"

    if ride.status != RideStatus.COMPLETED:
        return None, "Only completed rides can be disputed"

    if ride.actual_fare is None:
        return None, "Ride has no recorded fare to dispute"

    if disputed_amount > ride.actual_fare:
        return None, f"Disputed amount ({disputed_amount}) cannot exceed the ride fare ({ride.actual_fare})"

    existing = await _active_dispute_for_ride(db, ride_id)
    if existing is not None:
        return None, "An active dispute already exists for this ride"

    dispute = FareDispute(
        ride_id=ride_id,
        rider_id=rider_user_id,
        category=category,
        description=description,
        disputed_amount=disputed_amount,
        status=DisputeStatus.PENDING,
    )
    db.add(dispute)
    await db.commit()
    await db.refresh(dispute)
    return dispute, None


async def get_dispute_for_rider(
    db: AsyncSession, dispute_id: int, rider_user_id: int
) -> FareDispute | None:
    """Return the dispute if it exists and belongs to this rider."""
    result = await db.execute(
        select(FareDispute).where(
            FareDispute.id == dispute_id,
            FareDispute.rider_id == rider_user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_rider_disputes(
    db: AsyncSession,
    rider_user_id: int,
    *,
    status: DisputeStatus | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[FareDispute], int]:
    """Return paginated disputes for a rider."""
    base = select(FareDispute).where(FareDispute.rider_id == rider_user_id)
    if status:
        base = base.where(FareDispute.status == status)

    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = count_result.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(
        base.order_by(FareDispute.created_at.desc()).offset(offset).limit(page_size)
    )
    return list(result.scalars().all()), total


async def withdraw_dispute(
    db: AsyncSession, dispute_id: int, rider_user_id: int
) -> tuple[FareDispute | None, str | None]:
    """Rider withdraws a PENDING dispute."""
    dispute = await get_dispute_for_rider(db, dispute_id, rider_user_id)
    if dispute is None:
        return None, "Dispute not found"

    if dispute.status != DisputeStatus.PENDING:
        return None, "Only pending disputes can be withdrawn"

    dispute.status = DisputeStatus.WITHDRAWN
    dispute.resolved_at = _now()
    await db.commit()
    await db.refresh(dispute)
    return dispute, None


# ---------------------------------------------------------------------------
# Admin-facing operations
# ---------------------------------------------------------------------------

async def get_dispute(db: AsyncSession, dispute_id: int) -> FareDispute | None:
    result = await db.execute(
        select(FareDispute).where(FareDispute.id == dispute_id)
    )
    return result.scalar_one_or_none()


async def list_all_disputes(
    db: AsyncSession,
    *,
    status: DisputeStatus | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[FareDispute], int]:
    """Return paginated disputes for admin view."""
    base = select(FareDispute)
    if status:
        base = base.where(FareDispute.status == status)

    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = count_result.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(
        base.order_by(FareDispute.created_at.desc()).offset(offset).limit(page_size)
    )
    return list(result.scalars().all()), total


async def admin_review_dispute(
    db: AsyncSession,
    dispute_id: int,
    admin_user_id: int,
    *,
    decision: DisputeStatus,
    admin_notes: str,
    refund_amount: float | None,
    stripe_refund_id: str | None,
) -> tuple[FareDispute | None, str | None]:
    """Admin resolves a dispute: approved, partial, or denied.

    Rules:
    - Dispute must be in PENDING or UNDER_REVIEW state.
    - APPROVED/PARTIAL require refund_amount > 0 and ≤ disputed_amount.
    - DENIED requires no refund_amount (ignored if provided).
    """
    if decision not in {DisputeStatus.APPROVED, DisputeStatus.PARTIAL, DisputeStatus.DENIED}:
        return None, "Decision must be one of: approved, partial, denied"

    dispute = await get_dispute(db, dispute_id)
    if dispute is None:
        return None, "Dispute not found"

    if dispute.status not in {DisputeStatus.PENDING, DisputeStatus.UNDER_REVIEW}:
        return None, "Dispute is already in a terminal state"

    if decision in REFUND_STATUSES:
        if refund_amount is None or refund_amount <= 0:
            return None, "refund_amount is required and must be > 0 for approved/partial decisions"
        if refund_amount > dispute.disputed_amount:
            return None, f"refund_amount ({refund_amount}) cannot exceed disputed_amount ({dispute.disputed_amount})"

    dispute.status = decision
    dispute.reviewed_by_admin_id = admin_user_id
    dispute.admin_notes = admin_notes
    dispute.resolved_at = _now()

    if decision in REFUND_STATUSES:
        dispute.refund_amount = refund_amount
        dispute.stripe_refund_id = stripe_refund_id
    else:
        dispute.refund_amount = None
        dispute.stripe_refund_id = None

    await db.commit()
    await db.refresh(dispute)
    return dispute, None


async def get_dispute_summary(db: AsyncSession) -> dict:
    """Return aggregate stats across all disputes."""
    result = await db.execute(select(FareDispute))
    disputes = list(result.scalars().all())

    counts: dict[str, int] = {s.value: 0 for s in DisputeStatus}
    total_refunded = 0.0
    total_disputed = 0.0

    for d in disputes:
        counts[d.status.value] += 1
        total_disputed += d.disputed_amount
        if d.refund_amount is not None:
            total_refunded += d.refund_amount

    n = len(disputes)
    return {
        "total_disputes": n,
        "pending": counts[DisputeStatus.PENDING.value],
        "under_review": counts[DisputeStatus.UNDER_REVIEW.value],
        "approved": counts[DisputeStatus.APPROVED.value],
        "partial": counts[DisputeStatus.PARTIAL.value],
        "denied": counts[DisputeStatus.DENIED.value],
        "withdrawn": counts[DisputeStatus.WITHDRAWN.value],
        "total_refunded": round(total_refunded, 2),
        "avg_disputed_amount": round(total_disputed / n, 2) if n else 0.0,
    }
