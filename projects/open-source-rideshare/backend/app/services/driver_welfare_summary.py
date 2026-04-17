"""Service layer for the driver welfare summary.

Aggregates shift hours, earnings, insurance status, and cooperative standing
into a single welfare snapshot. Designed with driver wellbeing in mind:
fatigue thresholds, insurance compliance, and earnings goal tracking.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_earnings_goal import DriverEarningsGoal, GoalPeriodType
from app.models.driver_insurance import DriverInsuranceDocument, InsuranceDocumentStatus
from app.models.driver_shift import DriverShift, ShiftStatus
from app.models.driver import DriverProfile
from app.models.ride import Ride
from app.schemas.driver_welfare_summary import (
    CooperativeStatus,
    DriverWelfareSummary,
    EarningsMetrics,
    InsuranceStatus,
    ShiftMetrics,
    SupportResource,
)

# --------------------------------------------------------------------------- #
# Public constants (imported by tests)
# --------------------------------------------------------------------------- #

_RECOMMENDED_DAILY_MAX_HOURS: float = 10.0
_RECOMMENDED_WEEKLY_MAX_HOURS: float = 50.0

# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #

_SUPPORT_RESOURCES: list[SupportResource] = [
    SupportResource(
        name="Safety Guidelines",
        description=(
            "Review our platform safety guidelines to stay protected on every trip."
        ),
    ),
    SupportResource(
        name="Hardship Fund",
        description=(
            "Apply for the cooperative hardship fund if you are experiencing financial difficulties."
        ),
    ),
    SupportResource(
        name="Driver Support Line",
        description="Reach our driver support team 24/7 for any platform or safety issue.",
    ),
]


def _utc_now() -> datetime:
    """Return the current UTC time. Patched by tests for determinism."""
    return datetime.now(tz=timezone.utc)


def _compute_shift_hours(
    started_at: datetime,
    ended_at: Optional[datetime],
    now: datetime,
) -> float:
    """Return elapsed hours for a shift; never negative.

    If *ended_at* is None the shift is still active and *now* is used as the
    end boundary.
    """
    end = ended_at if ended_at is not None else now
    elapsed = (end - started_at).total_seconds() / 3600.0
    return max(0.0, elapsed)


def _fatigue_risk(hours_this_week: float) -> str:
    """Classify weekly driving hours into a fatigue risk category.

    < 40  → "low"
    40–49.9 → "moderate"
    >= 50 → "high"
    """
    if hours_this_week >= _RECOMMENDED_WEEKLY_MAX_HOURS:
        return "high"
    if hours_this_week >= 40.0:
        return "moderate"
    return "low"


def _build_insurance_status(docs: list, today: date) -> InsuranceStatus:
    """Derive a single insurance status from a list of insurance documents.

    Priority rules:
    1. No documents → "not_on_file"
    2. Any APPROVED document → use the one with the latest policy_end_date
       - days_until_expiry < 0  → "expired"
       - days_until_expiry <= 30 → "expiring_soon"
       - else                    → "active"
    3. Only PENDING_REVIEW / PENDING_UPLOAD documents → "pending"
    4. All other states (REJECTED, EXPIRED) → "expired"
    """
    if not docs:
        return InsuranceStatus(status="not_on_file", expires_on=None, days_until_expiry=None)

    approved_docs = [
        d for d in docs if d.status == InsuranceDocumentStatus.APPROVED
    ]

    if approved_docs:
        best = max(approved_docs, key=lambda d: d.policy_end_date)
        days = (best.policy_end_date - today).days
        if days < 0:
            status_str = "expired"
        elif days <= 30:
            status_str = "expiring_soon"
        else:
            status_str = "active"
        return InsuranceStatus(
            status=status_str,
            expires_on=best.policy_end_date,
            days_until_expiry=days,
        )

    pending_statuses = {
        InsuranceDocumentStatus.PENDING_REVIEW,
        InsuranceDocumentStatus.PENDING_UPLOAD,
    }
    if all(d.status in pending_statuses for d in docs):
        return InsuranceStatus(status="pending", expires_on=None, days_until_expiry=None)

    # Remaining cases: rejected / expired docs with no approved
    return InsuranceStatus(status="expired", expires_on=None, days_until_expiry=None)


def _build_welfare_note(
    shift_metrics: ShiftMetrics,
    earnings_metrics: EarningsMetrics,
    insurance_status: InsuranceStatus,
) -> str:
    """Generate a single human-readable welfare note in priority order.

    Priority:
    1. Insurance not on file
    2. Expired insurance
    3. Expiring soon insurance
    4. High weekly fatigue (>= 50 h)
    5. Active shift too long (>= 10 h)
    6. Moderate fatigue (>= 40 h)
    7. Earnings goal reached (progress >= 100 %)
    8. No rides, no hours → idle
    9. Normal summary
    """
    ins = insurance_status.status

    if ins == "not_on_file":
        return (
            "No insurance document on file. Please upload a valid insurance policy "
            "to continue driving on the platform."
        )

    if ins == "expired":
        return (
            "Your insurance has expired. Please upload a renewed policy as soon as "
            "possible to remain active on the platform."
        )

    if ins == "expiring_soon":
        days = insurance_status.days_until_expiry
        day_word = "day" if days == 1 else "days"
        return (
            f"Insurance expiring in {days} {day_word}. Please renew your policy "
            "before it expires to avoid a service interruption."
        )

    # Fatigue — high weekly
    if shift_metrics.fatigue_risk == "high":
        return (
            f"You've driven {shift_metrics.hours_this_week:.1f} hours this week. "
            "The cooperative recommends taking a rest to stay safe on the road."
        )

    # Active shift too long
    if (
        shift_metrics.active_shift_hours is not None
        and shift_metrics.active_shift_hours >= _RECOMMENDED_DAILY_MAX_HOURS
    ):
        return (
            f"You've been driving for {shift_metrics.active_shift_hours:.1f} hours "
            "in this shift. Consider taking a break."
        )

    # Moderate fatigue
    if shift_metrics.fatigue_risk == "moderate":
        return (
            f"You've driven {shift_metrics.hours_this_week:.1f} hours this week. "
            "Approaching the recommended weekly limit — remember to rest."
        )

    # Earnings goal reached
    if (
        earnings_metrics.earnings_goal_set
        and earnings_metrics.earnings_goal_progress_pct is not None
        and earnings_metrics.earnings_goal_progress_pct >= 100.0
    ):
        return "Goal reached! You've hit your earnings target for this period. Great work!"

    # Idle — no rides, no hours
    if (
        earnings_metrics.rides_completed_this_week == 0
        and shift_metrics.hours_this_week == 0.0
    ):
        return (
            "You haven't completed any rides this week yet. "
            "Log on when you're ready to start earning."
        )

    # Normal summary
    rides = earnings_metrics.rides_completed_this_week
    earned = earnings_metrics.earnings_this_week_usd
    return (
        f"You've completed {rides} rides this week, earning ${earned:.2f}. "
        "Keep up the great work!"
    )


# --------------------------------------------------------------------------- #
# Main service function
# --------------------------------------------------------------------------- #

async def get_driver_welfare_summary(
    db: AsyncSession,
    driver_id: int,
) -> DriverWelfareSummary:
    """Build and return a full welfare summary for the given driver.

    Executes 5 sequential DB queries (in this exact order, as expected by tests):
      1. DriverShift — shifts in the last 7 days
      2. Ride        — completed rides in the last 7 days
      3. DriverEarningsGoal — the driver's active goal (scalar_one_or_none)
      4. DriverInsuranceDocument — all insurance docs for this driver
      5. DriverProfile — the driver's profile (scalar_one_or_none)
    """
    now = _utc_now()
    today = now.date()
    week_ago = now - timedelta(days=7)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # 1. Shifts this week
    result = await db.execute(
        select(DriverShift).where(
            DriverShift.driver_id == driver_id,
            DriverShift.started_at >= week_ago,
        )
    )
    shifts = result.scalars().all()

    # 2. Completed rides this week
    result = await db.execute(
        select(Ride).where(
            Ride.driver_id == driver_id,
            Ride.requested_at >= week_ago,
        )
    )
    rides = result.scalars().all()

    # 3. Earnings goal
    result = await db.execute(
        select(DriverEarningsGoal).where(
            DriverEarningsGoal.driver_id == driver_id
        )
    )
    goal = result.scalar_one_or_none()

    # 4. Insurance documents
    result = await db.execute(
        select(DriverInsuranceDocument).where(
            DriverInsuranceDocument.driver_id == driver_id
        )
    )
    insurance_docs = result.scalars().all()

    # 5. Driver profile
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == driver_id)
    )
    profile = result.scalar_one_or_none()

    # ------------------------------------------------------------------ #
    # Shift metrics
    # ------------------------------------------------------------------ #
    hours_this_week = 0.0
    hours_today = 0.0
    active_shift_hours: Optional[float] = None
    shift_hour_list: list[float] = []

    for shift in shifts:
        h = _compute_shift_hours(shift.started_at, shift.ended_at, now)
        hours_this_week += h
        shift_hour_list.append(h)

        # Active shift
        if shift.status == ShiftStatus.active:
            active_shift_hours = h

        # Today's hours
        if shift.started_at >= day_start:
            hours_today += h

    max_consecutive_hours: Optional[float] = max(shift_hour_list) if shift_hour_list else None

    shift_metrics = ShiftMetrics(
        hours_this_week=hours_this_week,
        hours_today=hours_today,
        max_consecutive_hours=max_consecutive_hours,
        active_shift_hours=active_shift_hours,
        fatigue_risk=_fatigue_risk(hours_this_week),
        recommended_weekly_max_hours=_RECOMMENDED_WEEKLY_MAX_HOURS,
        recommended_daily_max_hours=_RECOMMENDED_DAILY_MAX_HOURS,
    )

    # ------------------------------------------------------------------ #
    # Earnings metrics
    # ------------------------------------------------------------------ #
    earnings_this_week = sum(r.actual_fare for r in rides)
    tips_this_week = sum(r.tip_amount for r in rides)
    rides_count = len(rides)

    # Today's earnings for daily goal tracking
    earnings_today = sum(
        r.actual_fare for r in rides if r.requested_at >= day_start
    )

    estimated_hourly: Optional[float] = (
        earnings_this_week / hours_this_week if hours_this_week > 0 else None
    )

    goal_set = goal is not None
    goal_target: Optional[float] = None
    goal_progress: Optional[float] = None

    if goal is not None:
        goal_target = goal.target_amount
        if goal.period_type == GoalPeriodType.WEEKLY:
            base = earnings_this_week
        else:
            base = earnings_today
        goal_progress = (base / goal_target * 100.0) if goal_target else None

    earnings_metrics = EarningsMetrics(
        earnings_this_week_usd=earnings_this_week,
        tips_this_week_usd=tips_this_week,
        rides_completed_this_week=rides_count,
        estimated_hourly_rate_usd=estimated_hourly,
        earnings_goal_set=goal_set,
        earnings_goal_target_usd=goal_target,
        earnings_goal_progress_pct=goal_progress,
    )

    # ------------------------------------------------------------------ #
    # Insurance status
    # ------------------------------------------------------------------ #
    insurance_status = _build_insurance_status(list(insurance_docs), today)

    # ------------------------------------------------------------------ #
    # Cooperative status
    # ------------------------------------------------------------------ #
    if profile is not None:
        cooperative_status = CooperativeStatus(
            is_approved_member=bool(profile.is_approved),
            total_trips_lifetime=profile.total_trips,
            average_rating=profile.rating_avg,
            background_check_status=profile.background_check_status,
        )
    else:
        cooperative_status = CooperativeStatus(
            is_approved_member=False,
            total_trips_lifetime=0,
            average_rating=0.0,
            background_check_status="pending",
        )

    # ------------------------------------------------------------------ #
    # Welfare note
    # ------------------------------------------------------------------ #
    welfare_note = _build_welfare_note(shift_metrics, earnings_metrics, insurance_status)

    return DriverWelfareSummary(
        as_of=now,
        shift_metrics=shift_metrics,
        earnings_metrics=earnings_metrics,
        insurance_status=insurance_status,
        cooperative_status=cooperative_status,
        welfare_note=welfare_note,
        support_resources=_SUPPORT_RESOURCES,
    )
