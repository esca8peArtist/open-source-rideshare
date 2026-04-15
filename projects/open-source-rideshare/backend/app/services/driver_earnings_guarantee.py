"""Driver minimum earnings guarantee service.

The cooperative guarantees that driver-members earn at least
`minimum_per_ride_usd` per completed ride each week. Drivers must
complete at least `minimum_rides_to_qualify` rides to be eligible.

Core operations
---------------
  get_active_policy          — fetch the current policy (or None)
  set_policy                 — create a new policy, deactivating the prior one
  preview_week               — dry-run: compute per-driver guarantee (no DB writes)
  process_week               — persist WeeklyGuaranteeRecord for all qualifying drivers
  pay_record                 — mark a single record as paid
  pay_all_week               — bulk pay all pending records for a week
  get_driver_history         — driver's own past records
  get_current_week_estimate  — in-progress estimate for the current week
  list_week_records          — admin paginated list for a given week
  get_guarantee_summary      — platform-wide aggregate stats
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.driver import DriverProfile
from app.models.driver_earnings_guarantee import (
    EarningsGuaranteePolicy,
    GuaranteeStatus,
    WeeklyGuaranteeRecord,
)
from app.models.ride import Ride, RideStatus
from app.models.user import User


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _week_bounds(week_start: date) -> tuple[date, date]:
    """Return (monday, sunday) for the ISO week that week_start falls in."""
    # Normalise to Monday regardless of what date was passed
    monday = week_start - timedelta(days=week_start.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _to_dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


async def _driver_week_rides(
    db: AsyncSession, week_start: date
) -> list[tuple[int, int, float]]:
    """Return [(driver_user_id, ride_count, gross_earnings_usd)] for the week.

    gross_earnings = sum(actual_fare + tip_amount) for completed rides.
    Uses estimated_fare as fallback when actual_fare is NULL.
    """
    monday, sunday = _week_bounds(week_start)
    start_dt = _to_dt(monday)
    end_dt = datetime(sunday.year, sunday.month, sunday.day, 23, 59, 59, tzinfo=timezone.utc)

    result = await db.execute(
        select(
            Ride.driver_id,
            func.count(Ride.id).label("ride_count"),
            func.sum(
                func.coalesce(Ride.actual_fare, Ride.estimated_fare, 0.0)
                + func.coalesce(Ride.tip_amount, 0.0)
            ).label("gross_earnings"),
        )
        .where(
            Ride.status == RideStatus.COMPLETED,
            Ride.completed_at >= start_dt,
            Ride.completed_at <= end_dt,
            Ride.driver_id.isnot(None),
        )
        .group_by(Ride.driver_id)
    )
    return [(row.driver_id, row.ride_count, float(row.gross_earnings or 0.0)) for row in result.all()]


async def _resolve_driver_profile(
    db: AsyncSession, driver_user_id: int
) -> DriverProfile | None:
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == driver_user_id)
    )
    return result.scalar_one_or_none()


async def _driver_name(db: AsyncSession, user_id: int) -> str:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return f"Driver#{user_id}"
    return f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email


def _compute_record_fields(
    rides: int,
    gross: float,
    policy: EarningsGuaranteePolicy,
) -> tuple[float, float, GuaranteeStatus]:
    """Return (guaranteed_earnings_usd, shortfall_usd, status)."""
    min_rides = policy.minimum_rides_to_qualify
    per_ride = float(policy.minimum_per_ride_usd)

    if rides < min_rides:
        return 0.0, 0.0, GuaranteeStatus.ineligible

    guaranteed = rides * per_ride
    shortfall = max(0.0, guaranteed - gross)

    if shortfall == 0.0:
        return guaranteed, 0.0, GuaranteeStatus.waived

    return guaranteed, round(shortfall, 2), GuaranteeStatus.pending


# ---------------------------------------------------------------------------
# Policy management
# ---------------------------------------------------------------------------

async def get_active_policy(db: AsyncSession) -> EarningsGuaranteePolicy | None:
    """Return the currently active guarantee policy, or None if none exists."""
    result = await db.execute(
        select(EarningsGuaranteePolicy)
        .where(EarningsGuaranteePolicy.is_active.is_(True))
        .order_by(EarningsGuaranteePolicy.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def set_policy(
    db: AsyncSession,
    admin_user_id: int,
    minimum_per_ride_usd: float,
    minimum_rides_to_qualify: int,
    effective_from: date,
    effective_until: date | None = None,
    notes: str | None = None,
) -> EarningsGuaranteePolicy:
    """Create a new policy and deactivate any previous active policy.

    Raises ValueError for invalid inputs.
    """
    if minimum_per_ride_usd <= 0:
        raise ValueError("minimum_per_ride_usd must be greater than zero")
    if minimum_rides_to_qualify < 1:
        raise ValueError("minimum_rides_to_qualify must be at least 1")
    if effective_until and effective_until <= effective_from:
        raise ValueError("effective_until must be after effective_from")

    # Deactivate previous policy
    await db.execute(
        update(EarningsGuaranteePolicy)
        .where(EarningsGuaranteePolicy.is_active.is_(True))
        .values(is_active=False)
    )

    policy = EarningsGuaranteePolicy(
        minimum_per_ride_usd=minimum_per_ride_usd,
        minimum_rides_to_qualify=minimum_rides_to_qualify,
        effective_from=effective_from,
        effective_until=effective_until,
        is_active=True,
        notes=notes,
        created_by_user_id=admin_user_id,
    )
    db.add(policy)
    await db.flush()
    return policy


# ---------------------------------------------------------------------------
# Week preview (dry run)
# ---------------------------------------------------------------------------

async def preview_week(
    db: AsyncSession, week_start: date
) -> dict:
    """Compute per-driver guarantee data for a week without persisting anything."""
    policy = await get_active_policy(db)
    if policy is None:
        raise ValueError("No active earnings guarantee policy configured")

    monday, sunday = _week_bounds(week_start)
    driver_rows = await _driver_week_rides(db, monday)

    from app.schemas.driver_earnings_guarantee import (
        DriverGuaranteePreviewItem,
        WeekPreviewResponse,
    )

    items: list[DriverGuaranteePreviewItem] = []
    total_shortfall = 0.0
    total_eligible = 0
    total_with_shortfall = 0

    for driver_user_id, ride_count, gross in driver_rows:
        guaranteed, shortfall, status = _compute_record_fields(ride_count, gross, policy)
        name = await _driver_name(db, driver_user_id)

        if status != GuaranteeStatus.ineligible:
            total_eligible += 1
        if status == GuaranteeStatus.pending:
            total_with_shortfall += 1
            total_shortfall += shortfall

        items.append(
            DriverGuaranteePreviewItem(
                driver_id=driver_user_id,
                driver_name=name,
                rides_completed=ride_count,
                gross_earnings_usd=round(gross, 2),
                guaranteed_earnings_usd=round(guaranteed, 2),
                shortfall_usd=shortfall,
                projected_status=status,
            )
        )

    items.sort(key=lambda x: x.shortfall_usd, reverse=True)

    return WeekPreviewResponse(
        week_start=monday,
        week_end=sunday,
        policy_id=policy.id,
        minimum_per_ride_usd=float(policy.minimum_per_ride_usd),
        minimum_rides_to_qualify=policy.minimum_rides_to_qualify,
        total_drivers_with_rides=len(driver_rows),
        total_eligible=total_eligible,
        total_with_shortfall=total_with_shortfall,
        total_shortfall_usd=round(total_shortfall, 2),
        drivers=items,
    )


# ---------------------------------------------------------------------------
# Process week (persist records)
# ---------------------------------------------------------------------------

async def process_week(
    db: AsyncSession, week_start: date, admin_user_id: int
) -> list[WeeklyGuaranteeRecord]:
    """Create or update WeeklyGuaranteeRecord for every driver who completed rides.

    Idempotent — running again for the same week recalculates and updates
    existing records (useful if new rides were added after initial processing).

    Returns the full list of records for the week.
    """
    policy = await get_active_policy(db)
    if policy is None:
        raise ValueError("No active earnings guarantee policy configured")

    monday, sunday = _week_bounds(week_start)
    driver_rows = await _driver_week_rides(db, monday)

    # Fetch existing records for this week
    existing_result = await db.execute(
        select(WeeklyGuaranteeRecord).where(
            WeeklyGuaranteeRecord.week_start == monday,
        )
    )
    existing_by_driver: dict[int, WeeklyGuaranteeRecord] = {
        r.driver_id: r for r in existing_result.scalars().all()
    }

    records: list[WeeklyGuaranteeRecord] = []
    now = datetime.now(timezone.utc)

    for driver_user_id, ride_count, gross in driver_rows:
        guaranteed, shortfall, status = _compute_record_fields(ride_count, gross, policy)

        if driver_user_id in existing_by_driver:
            record = existing_by_driver[driver_user_id]
            # Only update if still pending/ineligible/waived — don't disturb paid records
            if record.status != GuaranteeStatus.paid:
                record.rides_completed = ride_count
                record.gross_earnings_usd = round(gross, 2)
                record.guaranteed_earnings_usd = round(guaranteed, 2)
                record.shortfall_usd = shortfall
                record.status = status
                record.policy_id = policy.id
                record.processed_at = now
        else:
            driver_profile = await _resolve_driver_profile(db, driver_user_id)
            if driver_profile is None:
                continue  # no driver profile — skip
            record = WeeklyGuaranteeRecord(
                driver_id=driver_user_id,
                driver_profile_id=driver_profile.id,
                policy_id=policy.id,
                week_start=monday,
                week_end=sunday,
                rides_completed=ride_count,
                gross_earnings_usd=round(gross, 2),
                guaranteed_earnings_usd=round(guaranteed, 2),
                shortfall_usd=shortfall,
                status=status,
                processed_at=now,
            )
            db.add(record)

        records.append(record)

    await db.flush()
    return records


# ---------------------------------------------------------------------------
# Payout operations
# ---------------------------------------------------------------------------

async def pay_record(
    db: AsyncSession, record_id: int, admin_user_id: int
) -> WeeklyGuaranteeRecord | None:
    """Mark a single pending guarantee record as paid.

    Returns None if the record doesn't exist.
    Raises ValueError if status is not `pending`.
    """
    result = await db.execute(
        select(WeeklyGuaranteeRecord).where(WeeklyGuaranteeRecord.id == record_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        return None

    if record.status != GuaranteeStatus.pending:
        raise ValueError(
            f"Cannot pay record with status '{record.status}' — only 'pending' records can be paid"
        )

    record.status = GuaranteeStatus.paid
    record.paid_at = datetime.now(timezone.utc)
    await db.flush()
    return record


async def pay_all_week(
    db: AsyncSession, week_start: date, admin_user_id: int
) -> tuple[int, float]:
    """Pay all pending records for a week.

    Returns (records_paid, total_paid_usd).
    """
    monday, _ = _week_bounds(week_start)
    result = await db.execute(
        select(WeeklyGuaranteeRecord).where(
            WeeklyGuaranteeRecord.week_start == monday,
            WeeklyGuaranteeRecord.status == GuaranteeStatus.pending,
        )
    )
    records = result.scalars().all()

    now = datetime.now(timezone.utc)
    total = 0.0
    for record in records:
        record.status = GuaranteeStatus.paid
        record.paid_at = now
        total += float(record.shortfall_usd)

    await db.flush()
    return len(records), round(total, 2)


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

async def list_week_records(
    db: AsyncSession,
    week_start: date,
    status_filter: GuaranteeStatus | None = None,
) -> list[tuple[WeeklyGuaranteeRecord, str]]:
    """Return (record, driver_name) pairs for the given week.

    Optionally filtered by status. Ordered by shortfall_usd desc.
    """
    monday, _ = _week_bounds(week_start)
    stmt = (
        select(WeeklyGuaranteeRecord, User)
        .join(User, WeeklyGuaranteeRecord.driver_id == User.id)
        .where(WeeklyGuaranteeRecord.week_start == monday)
    )
    if status_filter is not None:
        stmt = stmt.where(WeeklyGuaranteeRecord.status == status_filter)
    stmt = stmt.order_by(WeeklyGuaranteeRecord.shortfall_usd.desc())

    result = await db.execute(stmt)
    pairs = result.all()  # list of Row(WeeklyGuaranteeRecord, User)

    out = []
    for row in pairs:
        record, user = row
        name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email
        out.append((record, name))
    return out


async def get_driver_history(
    db: AsyncSession, driver_user_id: int
) -> list[WeeklyGuaranteeRecord]:
    """Return all weekly records for a driver, newest first."""
    result = await db.execute(
        select(WeeklyGuaranteeRecord)
        .where(WeeklyGuaranteeRecord.driver_id == driver_user_id)
        .order_by(WeeklyGuaranteeRecord.week_start.desc())
    )
    return list(result.scalars().all())


async def get_current_week_estimate(
    db: AsyncSession, driver_user_id: int
) -> dict:
    """Return an in-progress estimate for the driver's current week.

    Not persisted — uses today's date to define the current week.
    """
    from app.schemas.driver_earnings_guarantee import DriverCurrentWeekEstimate

    today = date.today()
    monday, sunday = _week_bounds(today)

    policy = await get_active_policy(db)
    if policy is None:
        # No policy — return zeros
        return DriverCurrentWeekEstimate(
            week_start=monday,
            week_end=sunday,
            rides_completed_so_far=0,
            gross_earnings_so_far_usd=0.0,
            guaranteed_if_finished_usd=0.0,
            shortfall_so_far_usd=0.0,
            minimum_rides_to_qualify=0,
            minimum_per_ride_usd=0.0,
            is_on_track=True,
        )

    # Get this driver's rides for the current week
    driver_rows = await _driver_week_rides(db, monday)
    driver_data = next(
        ((rides, gross) for uid, rides, gross in driver_rows if uid == driver_user_id),
        (0, 0.0),
    )
    rides_so_far, gross_so_far = driver_data

    guaranteed, shortfall, status = _compute_record_fields(rides_so_far, gross_so_far, policy)
    is_on_track = status in (GuaranteeStatus.waived, GuaranteeStatus.ineligible) or (
        status == GuaranteeStatus.pending and shortfall == 0.0
    )

    return DriverCurrentWeekEstimate(
        week_start=monday,
        week_end=sunday,
        rides_completed_so_far=rides_so_far,
        gross_earnings_so_far_usd=round(gross_so_far, 2),
        guaranteed_if_finished_usd=round(guaranteed, 2),
        shortfall_so_far_usd=shortfall,
        minimum_rides_to_qualify=policy.minimum_rides_to_qualify,
        minimum_per_ride_usd=float(policy.minimum_per_ride_usd),
        is_on_track=is_on_track,
    )


async def get_guarantee_summary(db: AsyncSession) -> dict:
    """Aggregate platform-wide guarantee statistics."""
    from app.schemas.driver_earnings_guarantee import GuaranteeSummaryResponse

    policy = await get_active_policy(db)

    # Count distinct weeks processed
    weeks_result = await db.execute(
        select(func.count(func.distinct(WeeklyGuaranteeRecord.week_start)))
    )
    total_weeks = weeks_result.scalar() or 0

    # Sum paid shortfalls
    paid_result = await db.execute(
        select(
            func.count(WeeklyGuaranteeRecord.id),
            func.coalesce(func.sum(WeeklyGuaranteeRecord.shortfall_usd), 0.0),
        ).where(WeeklyGuaranteeRecord.status == GuaranteeStatus.paid)
    )
    paid_row = paid_result.one()
    total_paid_count = paid_row[0] or 0
    total_paid_usd = float(paid_row[1] or 0.0)

    # Sum pending shortfalls
    pending_result = await db.execute(
        select(func.coalesce(func.sum(WeeklyGuaranteeRecord.shortfall_usd), 0.0))
        .where(WeeklyGuaranteeRecord.status == GuaranteeStatus.pending)
    )
    total_pending_usd = float(pending_result.scalar() or 0.0)

    # Count ineligible / waived
    ineligible_result = await db.execute(
        select(func.count(WeeklyGuaranteeRecord.id))
        .where(WeeklyGuaranteeRecord.status == GuaranteeStatus.ineligible)
    )
    total_ineligible = ineligible_result.scalar() or 0

    waived_result = await db.execute(
        select(func.count(WeeklyGuaranteeRecord.id))
        .where(WeeklyGuaranteeRecord.status == GuaranteeStatus.waived)
    )
    total_waived = waived_result.scalar() or 0

    return GuaranteeSummaryResponse(
        policy_minimum_per_ride_usd=float(policy.minimum_per_ride_usd) if policy else 0.0,
        policy_minimum_rides_to_qualify=policy.minimum_rides_to_qualify if policy else 0,
        total_weeks_processed=total_weeks,
        total_drivers_paid=total_paid_count,
        total_shortfall_paid_usd=round(total_paid_usd, 2),
        total_pending_shortfall_usd=round(total_pending_usd, 2),
        total_ineligible_records=total_ineligible,
        total_waived_records=total_waived,
    )
