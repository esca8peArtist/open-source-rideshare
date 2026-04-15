"""Service layer for the Driver Mentorship Program.

Business rules:
  - A mentee may only have one pending or active mentorship at a time.
  - A mentor may be assigned to multiple mentees concurrently (no hard cap;
    admins are responsible for not overloading individual mentors).
  - Commission is recorded per ride when a mentee completes a ride.
  - Mentorships are auto-completed when ends_at is in the past.
  - Only pending/active mentorships can be cancelled.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http import HTTPStatus

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_mentorship import (
    DriverMentorship,
    MentorshipEarning,
    MentorshipStatus,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MentorshipError(Exception):
    def __init__(self, message: str, status_code: int = HTTPStatus.BAD_REQUEST):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get_mentorship_or_404(db: AsyncSession, mentorship_id: int) -> DriverMentorship:
    result = await db.execute(
        select(DriverMentorship).where(DriverMentorship.id == mentorship_id)
    )
    m = result.scalar_one_or_none()
    if not m:
        raise MentorshipError(
            f"Mentorship {mentorship_id} not found.", HTTPStatus.NOT_FOUND
        )
    return m


# ---------------------------------------------------------------------------
# Mentee actions
# ---------------------------------------------------------------------------


async def request_mentorship(
    db: AsyncSession,
    mentee_user_id: int,
    note: str | None = None,
) -> DriverMentorship:
    """Create a pending mentorship request for a new driver.

    Raises 409 if the driver already has an active or pending mentorship.
    """
    existing = await db.execute(
        select(DriverMentorship).where(
            DriverMentorship.mentee_id == mentee_user_id,
            DriverMentorship.status.in_(
                [MentorshipStatus.pending, MentorshipStatus.active]
            ),
        )
    )
    if existing.scalar_one_or_none():
        raise MentorshipError(
            "You already have an active or pending mentorship.",
            HTTPStatus.CONFLICT,
        )

    mentorship = DriverMentorship(
        mentee_id=mentee_user_id,
        status=MentorshipStatus.pending,
        admin_note=note,
    )
    db.add(mentorship)
    await db.commit()
    await db.refresh(mentorship)
    return mentorship


async def get_mentee_mentorship(
    db: AsyncSession, mentee_user_id: int
) -> DriverMentorship | None:
    """Return the most recent mentorship for a mentee (any status)."""
    result = await db.execute(
        select(DriverMentorship)
        .where(DriverMentorship.mentee_id == mentee_user_id)
        .order_by(DriverMentorship.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Mentor actions
# ---------------------------------------------------------------------------


async def get_mentor_mentees(
    db: AsyncSession,
    mentor_user_id: int,
    status_filter: MentorshipStatus | None = None,
) -> list[DriverMentorship]:
    """Return mentorships where this user is the mentor."""
    q = select(DriverMentorship).where(DriverMentorship.mentor_id == mentor_user_id)
    if status_filter:
        q = q.where(DriverMentorship.status == status_filter)
    q = q.order_by(DriverMentorship.created_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_mentor_earnings(
    db: AsyncSession, mentor_user_id: int
) -> list[MentorshipEarning]:
    """Return all commission earnings where this user is the mentor."""
    result = await db.execute(
        select(MentorshipEarning)
        .join(DriverMentorship, MentorshipEarning.mentorship_id == DriverMentorship.id)
        .where(DriverMentorship.mentor_id == mentor_user_id)
        .order_by(MentorshipEarning.created_at.desc())
    )
    return list(result.scalars().all())


async def get_mentor_earning_summary(
    db: AsyncSession, mentor_user_id: int
) -> dict:
    """Aggregate commission totals for a mentor."""
    active_count_result = await db.execute(
        select(func.count()).select_from(DriverMentorship).where(
            DriverMentorship.mentor_id == mentor_user_id,
            DriverMentorship.status == MentorshipStatus.active,
        )
    )
    active_count = active_count_result.scalar_one()

    total_result = await db.execute(
        select(func.coalesce(func.sum(MentorshipEarning.commission_amount), 0.0))
        .select_from(MentorshipEarning)
        .join(DriverMentorship, MentorshipEarning.mentorship_id == DriverMentorship.id)
        .where(DriverMentorship.mentor_id == mentor_user_id)
    )
    lifetime_total = float(total_result.scalar_one())

    unpaid_result = await db.execute(
        select(func.coalesce(func.sum(MentorshipEarning.commission_amount), 0.0))
        .select_from(MentorshipEarning)
        .join(DriverMentorship, MentorshipEarning.mentorship_id == DriverMentorship.id)
        .where(
            DriverMentorship.mentor_id == mentor_user_id,
            MentorshipEarning.paid_at.is_(None),
        )
    )
    unpaid = float(unpaid_result.scalar_one())

    return {
        "mentor_id": mentor_user_id,
        "active_mentee_count": active_count,
        "lifetime_commission_earned": round(lifetime_total, 2),
        "unpaid_commission": round(unpaid, 2),
    }


# ---------------------------------------------------------------------------
# Admin actions
# ---------------------------------------------------------------------------


async def assign_mentor(
    db: AsyncSession,
    mentorship_id: int,
    mentor_user_id: int,
    commission_rate: float = 0.02,
    commission_days: int = 90,
    admin_note: str | None = None,
) -> DriverMentorship:
    """Assign a mentor to a pending mentorship and activate it.

    Raises 409 if the mentorship is not in pending status.
    Raises 400 if the mentor and mentee are the same person.
    """
    m = await _get_mentorship_or_404(db, mentorship_id)

    if m.status != MentorshipStatus.pending:
        raise MentorshipError(
            f"Mentorship is {m.status.value}; only pending mentorships can be assigned.",
            HTTPStatus.CONFLICT,
        )
    if m.mentee_id == mentor_user_id:
        raise MentorshipError(
            "A driver cannot mentor themselves.",
            HTTPStatus.BAD_REQUEST,
        )

    now = _now()
    m.mentor_id = mentor_user_id
    m.commission_rate = commission_rate
    m.commission_days = commission_days
    m.status = MentorshipStatus.active
    m.started_at = now
    m.ends_at = now + timedelta(days=commission_days)
    m.admin_note = admin_note
    await db.commit()
    await db.refresh(m)
    return m


async def cancel_mentorship(
    db: AsyncSession,
    mentorship_id: int,
    cancelled_by_id: int,
    reason: str,
) -> DriverMentorship:
    """Cancel a pending or active mentorship.

    Raises 409 if the mentorship is already completed or cancelled.
    """
    m = await _get_mentorship_or_404(db, mentorship_id)

    if m.status in (MentorshipStatus.completed, MentorshipStatus.cancelled):
        raise MentorshipError(
            f"Mentorship is already {m.status.value}.",
            HTTPStatus.CONFLICT,
        )

    m.status = MentorshipStatus.cancelled
    m.cancelled_at = _now()
    m.cancelled_by_id = cancelled_by_id
    m.cancel_reason = reason
    await db.commit()
    await db.refresh(m)
    return m


async def list_mentorships(
    db: AsyncSession,
    status_filter: MentorshipStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[DriverMentorship]:
    q = select(DriverMentorship)
    if status_filter:
        q = q.where(DriverMentorship.status == status_filter)
    q = q.order_by(DriverMentorship.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_admin_summary(db: AsyncSession) -> dict:
    """Platform-wide mentorship statistics."""

    async def _count(status: MentorshipStatus) -> int:
        r = await db.execute(
            select(func.count())
            .select_from(DriverMentorship)
            .where(DriverMentorship.status == status)
        )
        return r.scalar_one()

    pending = await _count(MentorshipStatus.pending)
    active = await _count(MentorshipStatus.active)
    completed = await _count(MentorshipStatus.completed)
    cancelled = await _count(MentorshipStatus.cancelled)

    paid_r = await db.execute(
        select(func.coalesce(func.sum(MentorshipEarning.commission_amount), 0.0))
        .where(MentorshipEarning.paid_at.is_not(None))
    )
    paid = float(paid_r.scalar_one())

    unpaid_r = await db.execute(
        select(func.coalesce(func.sum(MentorshipEarning.commission_amount), 0.0))
        .where(MentorshipEarning.paid_at.is_(None))
    )
    unpaid = float(unpaid_r.scalar_one())

    return {
        "total_pending": pending,
        "total_active": active,
        "total_completed": completed,
        "total_cancelled": cancelled,
        "total_commission_paid": round(paid, 2),
        "total_commission_unpaid": round(unpaid, 2),
    }


# ---------------------------------------------------------------------------
# Commission recording (called by ride completion logic)
# ---------------------------------------------------------------------------


async def record_commission(
    db: AsyncSession,
    ride_id: int,
    mentee_user_id: int,
    mentee_ride_earnings: float,
) -> MentorshipEarning | None:
    """Record a commission earning for the mentor when a mentee completes a ride.

    Returns None if there is no active mentorship or if ends_at has passed.
    Idempotent: if an earning already exists for this ride+mentorship pair it
    is returned unchanged.
    """
    now = _now()

    # Find the active mentorship for this mentee.
    result = await db.execute(
        select(DriverMentorship).where(
            DriverMentorship.mentee_id == mentee_user_id,
            DriverMentorship.status == MentorshipStatus.active,
            DriverMentorship.ends_at > now,
        )
    )
    mentorship = result.scalar_one_or_none()
    if not mentorship:
        return None

    # Idempotency check.
    existing = await db.execute(
        select(MentorshipEarning).where(
            MentorshipEarning.mentorship_id == mentorship.id,
            MentorshipEarning.ride_id == ride_id,
        )
    )
    if existing.scalar_one_or_none():
        return existing.scalar_one_or_none()

    commission = round(mentee_ride_earnings * mentorship.commission_rate, 2)
    earning = MentorshipEarning(
        mentorship_id=mentorship.id,
        ride_id=ride_id,
        mentee_earnings=mentee_ride_earnings,
        commission_amount=commission,
    )
    db.add(earning)
    await db.commit()
    await db.refresh(earning)
    return earning


# ---------------------------------------------------------------------------
# Background maintenance
# ---------------------------------------------------------------------------


async def complete_expired_mentorships(db: AsyncSession) -> int:
    """Mark active mentorships past their ends_at as completed.

    Returns the number of rows updated.
    """
    now = _now()
    result = await db.execute(
        select(DriverMentorship).where(
            DriverMentorship.status == MentorshipStatus.active,
            DriverMentorship.ends_at <= now,
        )
    )
    expired = list(result.scalars().all())
    for m in expired:
        m.status = MentorshipStatus.completed
        m.completed_at = now
    if expired:
        await db.commit()
    return len(expired)
