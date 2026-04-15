"""Service layer for the driver rating appeal system.

Business rules
--------------
- Only drivers may submit appeals.
- A driver may only appeal feedback records where they were the rated party
  (ride_feedback.role == 'driver' and the ride's driver_id == their user id).
- One appeal per feedback_id (enforced by DB unique constraint and validated here).
- Admins may approve or reject. Pending → approved/rejected only; no re-review.
- On approval, rating_nullified is set to True. The feedback row is untouched
  (preserved for audit). Score aggregation should filter out nullified ratings.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_rating_appeal import AppealStatus, DriverRatingAppeal
from app.models.feedback import RideFeedback
from app.models.ride import Ride


class AppealError(Exception):
    """Domain error with an HTTP status code hint."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Driver actions
# ---------------------------------------------------------------------------


async def submit_appeal(
    db: AsyncSession,
    *,
    driver_id: int,
    feedback_id: int,
    reason: str,
) -> DriverRatingAppeal:
    """Driver submits an appeal against a ride_feedback rating.

    Raises AppealError (400/403/404/409) for all validation failures.
    Caller must commit the session.
    """
    # 1. Fetch the feedback record
    result = await db.execute(select(RideFeedback).where(RideFeedback.id == feedback_id))
    feedback = result.scalar_one_or_none()
    if feedback is None:
        raise AppealError("Feedback record not found", status_code=404)

    # 2. Only driver-role feedback can be appealed
    if feedback.role != "driver":
        raise AppealError(
            "Only driver ratings (role='driver') can be appealed", status_code=400
        )

    # 3. Validate the driver is the rated party — look up the ride
    ride_result = await db.execute(select(Ride).where(Ride.id == feedback.ride_id))
    ride = ride_result.scalar_one_or_none()
    if ride is None:
        raise AppealError("Associated ride not found", status_code=404)

    if ride.driver_id != driver_id:
        raise AppealError(
            "You can only appeal ratings for rides you drove", status_code=403
        )

    # 4. No duplicate appeals
    existing = await db.execute(
        select(DriverRatingAppeal).where(DriverRatingAppeal.feedback_id == feedback_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise AppealError(
            "An appeal for this feedback has already been submitted", status_code=409
        )

    appeal = DriverRatingAppeal(
        driver_id=driver_id,
        feedback_id=feedback_id,
        reason=reason,
        status=AppealStatus.PENDING,
    )
    db.add(appeal)
    return appeal


async def list_driver_appeals(
    db: AsyncSession,
    *,
    driver_id: int,
    skip: int = 0,
    limit: int = 20,
) -> Sequence[DriverRatingAppeal]:
    """Return a driver's own appeals, newest first."""
    result = await db.execute(
        select(DriverRatingAppeal)
        .where(DriverRatingAppeal.driver_id == driver_id)
        .order_by(DriverRatingAppeal.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Admin actions
# ---------------------------------------------------------------------------


async def review_appeal(
    db: AsyncSession,
    *,
    appeal_id: int,
    admin_id: int,
    decision: AppealStatus,
    admin_notes: str,
) -> DriverRatingAppeal:
    """Admin approves or rejects an appeal.

    Approving sets rating_nullified=True so score aggregation skips it.
    Raises AppealError on not-found or if already reviewed.
    Caller must commit the session.
    """
    if decision == AppealStatus.PENDING:
        raise AppealError("Decision must be 'approved' or 'rejected'", status_code=400)

    result = await db.execute(
        select(DriverRatingAppeal).where(DriverRatingAppeal.id == appeal_id)
    )
    appeal = result.scalar_one_or_none()
    if appeal is None:
        raise AppealError("Appeal not found", status_code=404)

    if appeal.status != AppealStatus.PENDING:
        raise AppealError(
            f"Appeal has already been reviewed (status: {appeal.status.value})",
            status_code=409,
        )

    appeal.status = decision
    appeal.admin_notes = admin_notes
    appeal.reviewed_by = admin_id
    appeal.reviewed_at = datetime.now(tz=timezone.utc)

    if decision == AppealStatus.APPROVED:
        appeal.rating_nullified = True

    return appeal


async def list_all_appeals(
    db: AsyncSession,
    *,
    status_filter: AppealStatus | None = None,
    skip: int = 0,
    limit: int = 50,
) -> Sequence[DriverRatingAppeal]:
    """Admin: list all appeals, optionally filtered by status."""
    query = select(DriverRatingAppeal).order_by(DriverRatingAppeal.created_at.desc())
    if status_filter is not None:
        query = query.where(DriverRatingAppeal.status == status_filter)
    result = await db.execute(query.offset(skip).limit(limit))
    return result.scalars().all()


async def get_appeal_summary(db: AsyncSession) -> dict:
    """Aggregate counts for the admin dashboard."""
    rows = await db.execute(
        select(DriverRatingAppeal.status, func.count().label("n"))
        .group_by(DriverRatingAppeal.status)
    )
    counts: dict[str, int] = {r.status: r.n for r in rows}

    total_result = await db.execute(select(func.count()).select_from(DriverRatingAppeal))
    total = total_result.scalar_one()

    nullified_result = await db.execute(
        select(func.count()).select_from(DriverRatingAppeal).where(
            DriverRatingAppeal.rating_nullified == True  # noqa: E712
        )
    )
    nullified = nullified_result.scalar_one()

    return {
        "total": total,
        "pending": counts.get(AppealStatus.PENDING, 0),
        "approved": counts.get(AppealStatus.APPROVED, 0),
        "rejected": counts.get(AppealStatus.REJECTED, 0),
        "nullified": nullified,
    }
