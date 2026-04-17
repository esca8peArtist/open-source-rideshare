"""Driver welfare summary service.

Aggregates shift hours, ride earnings, insurance status, and cooperative
standing into a single welfare snapshot for GET /drivers/me/welfare-summary.

This is a cooperative-only feature.  Uber and Lyft have no equivalent — they
lack structural incentive to surface driver fatigue or burnout risk.  A
cooperative platform is owned by its drivers and is obligated to act in their
collective interest, which includes not normalising dangerous working hours.

Public API:
    get_driver_welfare_summary(db, driver_id) → DriverWelfareSummary
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import DriverProfile
from app.models.driver_earnings_goal import DriverEarningsGoal, GoalPeriodType
from app.models.driver_insurance import DriverInsuranceDocument, InsuranceDocumentStatus
from app.models.driver_shift import DriverShift, ShiftStatus
from app.models.ride import Ride, RideStatus
from app.schemas.driver_welfare_summary import (
    CooperativeStatus,
    DriverWelfareSummary,
    EarningsMetrics,
    InsuranceStatus,
    ShiftMetrics,
    SupportResource,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RECOMMENDED_WEEKLY_MAX_HOURS: float = 50.0
_RECOMMENDED_DAILY_MAX_HOURS: float = 10.0

_INSURANCE_EXPIRY_WARNING_DAYS: int = 30

_SUPPORT_RESOURCES: list[SupportResource] = [
    SupportResource(
        name="Driver Safety Guidelines",
        description=(
            "OpenRide recommends a maximum of 10 hours per day and 50 hours per week.  "
            "Fatigued driving significantly increases accident risk.  Please rest."
        ),
    ),
    SupportResource(
        name="Cooperative Hardship Fund",
        description=(
            "OpenRide's hardship fund provides emergency financial support to member "
            "drivers.  Applications are reviewed within 48 hours."
        ),
        url="/api/v1/hardship-fund/apply",
    ),
    SupportResource(
        name="Driver Mental Health Support",
        description=(
            "Rideshare driving can be isolating and stressful.  OpenRide partners "
            "with the Drivers Union counselling programme — available to all members."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _start_of_today_utc() -> datetime:
    now = _utc_now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _seven_days_ago_utc() -> datetime:
    return _start_of_today_utc() - timedelta(days=7)


def _compute_shift_hours(
    started_at: datetime,
    ended_at: Optional[datetime],
    now: datetime,
) -> float:
    """Return shift duration in hours, using now for still-active shifts."""
    end = ended_at if ended_at is not None else now
    delta = end - started_at
    return max(delta.total_seconds() / 3600.0, 0.0)


def _fatigue_risk(hours_this_week: float) -> str:
    if hours_this_week >= _RECOMMENDED_WEEKLY_MAX_HOURS:
        return "high"
    if hours_this_week >= 40.0:
        return "moderate"
    return "low"


def _build_insurance_status(
    docs: list[DriverInsuranceDocument],
    today: date,
) -> InsuranceStatus:
    """Derive the insurance status from the driver's document list."""
    if not docs:
        return InsuranceStatus(
            status="not_on_file",
            expires_on=None,
            days_until_expiry=None,
        )

    # Prefer approved docs; fall back to pending; then expired.
    approved = [d for d in docs if d.status == InsuranceDocumentStatus.APPROVED]
    pending = [d for d in docs if d.status in (
        InsuranceDocumentStatus.PENDING_REVIEW,
        InsuranceDocumentStatus.PENDING_UPLOAD,
    )]

    if approved:
        # Pick the one expiring latest.
        latest = max(approved, key=lambda d: d.policy_end_date)
        days = (latest.policy_end_date - today).days

        if days < 0:
            ins_status = "expired"
        elif days <= _INSURANCE_EXPIRY_WARNING_DAYS:
            ins_status = "expiring_soon"
        else:
            ins_status = "active"

        return InsuranceStatus(
            status=ins_status,
            expires_on=latest.policy_end_date,
            days_until_expiry=days,
        )

    if pending:
        return InsuranceStatus(
            status="pending",
            expires_on=None,
            days_until_expiry=None,
        )

    # All docs are rejected or expired.
    return InsuranceStatus(
        status="expired",
        expires_on=None,
        days_until_expiry=None,
    )


def _build_welfare_note(
    shift_metrics: ShiftMetrics,
    earnings_metrics: EarningsMetrics,
    insurance_status: InsuranceStatus,
) -> str:
    """Return the single most important welfare message for this driver."""

    # Priority 1: urgent insurance issue
    if insurance_status.status == "not_on_file":
        return (
            "No insurance document is on file.  Please upload your insurance "
            "policy to remain eligible for rides.  Your earnings are protected "
            "— the cooperative cannot dispatch you without active insurance."
        )

    if insurance_status.status == "expired":
        return (
            "Your insurance policy has expired.  Please upload a renewed policy "
            "as soon as possible.  You will not be dispatched until insurance "
            "is re-approved."
        )

    if insurance_status.status == "expiring_soon" and insurance_status.days_until_expiry is not None:
        return (
            f"Your insurance expires in {insurance_status.days_until_expiry} day"
            f"{'s' if insurance_status.days_until_expiry != 1 else ''}.  "
            "Please upload a renewed policy before it lapses to avoid a gap in coverage."
        )

    # Priority 2: fatigue risk
    if shift_metrics.fatigue_risk == "high":
        return (
            f"You've driven {shift_metrics.hours_this_week:.1f} hours this week — "
            f"above the cooperative's recommended {_RECOMMENDED_WEEKLY_MAX_HOURS:.0f}-hour limit.  "
            "Fatigued driving significantly increases accident risk.  "
            "Please consider taking time off.  Your cooperative has your back."
        )

    if shift_metrics.active_shift_hours is not None and shift_metrics.active_shift_hours >= _RECOMMENDED_DAILY_MAX_HOURS:
        return (
            f"You've been driving for {shift_metrics.active_shift_hours:.1f} hours in this shift.  "
            "We recommend taking a break — driver fatigue affects safety for you and your passengers."
        )

    if shift_metrics.fatigue_risk == "moderate":
        return (
            f"You've driven {shift_metrics.hours_this_week:.1f} hours this week.  "
            "You're approaching the cooperative's recommended maximum.  "
            "Keep an eye on your hours and remember: rest is part of the job."
        )

    # Priority 3: earnings goal progress
    if (
        earnings_metrics.earnings_goal_set
        and earnings_metrics.earnings_goal_progress_pct is not None
        and earnings_metrics.earnings_goal_progress_pct >= 100.0
    ):
        return (
            f"Goal reached!  You've hit your target of "
            f"${earnings_metrics.earnings_goal_target_usd:,.2f} this week.  "
            "Consider wrapping up — you've earned it."
        )

    # Default: positive summary
    rides = earnings_metrics.rides_completed_this_week
    earned = earnings_metrics.earnings_this_week_usd
    hours = shift_metrics.hours_this_week

    if rides == 0:
        return (
            "You haven't completed any rides this period.  "
            "When you're ready to drive, the cooperative is here to support you."
        )

    parts = [
        f"This week: {rides} ride{'s' if rides != 1 else ''}, "
        f"${earned:,.2f} earned"
    ]
    if hours > 0:
        parts.append(f"{hours:.1f} hours on shift")
    if earnings_metrics.estimated_hourly_rate_usd is not None:
        parts.append(f"~${earnings_metrics.estimated_hourly_rate_usd:.2f}/hr")

    parts.append("Insurance active.")
    return ".  ".join(parts) + "  Keep it up."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_driver_welfare_summary(
    db: AsyncSession,
    driver_id: int,
) -> DriverWelfareSummary:
    """Compute welfare summary for driver_id.

    Args:
        db:         Async database session.
        driver_id:  ID of the authenticated driver (User.id).

    Returns:
        DriverWelfareSummary with shift hours, earnings, insurance status,
        cooperative standing, a welfare note, and support resources.
    """
    now = _utc_now()
    today = now.date()
    week_start = _seven_days_ago_utc()
    day_start = _start_of_today_utc()

    # ------------------------------------------------------------------
    # 1. Fetch shifts in last 7 days
    # ------------------------------------------------------------------
    shifts_stmt = select(DriverShift).where(
        and_(
            DriverShift.driver_id == driver_id,
            DriverShift.started_at >= week_start,
        )
    )
    shifts_result = await db.execute(shifts_stmt)
    shifts = shifts_result.scalars().all()

    hours_this_week: float = 0.0
    hours_today: float = 0.0
    max_consecutive_hours: Optional[float] = None
    active_shift_hours: Optional[float] = None

    for shift in shifts:
        h = _compute_shift_hours(shift.started_at, shift.ended_at, now)
        hours_this_week += h

        if shift.started_at >= day_start:
            hours_today += h

        if shift.status == ShiftStatus.active and shift.ended_at is None:
            # Currently active shift
            active_h = _compute_shift_hours(shift.started_at, None, now)
            active_shift_hours = round(active_h, 2)
        elif shift.status in (ShiftStatus.completed, ShiftStatus.auto_ended):
            if max_consecutive_hours is None or h > max_consecutive_hours:
                max_consecutive_hours = h

    hours_this_week = round(hours_this_week, 2)
    hours_today = round(hours_today, 2)
    if max_consecutive_hours is not None:
        max_consecutive_hours = round(max_consecutive_hours, 2)

    shift_metrics = ShiftMetrics(
        hours_this_week=hours_this_week,
        hours_today=hours_today,
        max_consecutive_hours=max_consecutive_hours,
        active_shift_hours=active_shift_hours,
        fatigue_risk=_fatigue_risk(hours_this_week),
        recommended_weekly_max_hours=_RECOMMENDED_WEEKLY_MAX_HOURS,
        recommended_daily_max_hours=_RECOMMENDED_DAILY_MAX_HOURS,
    )

    # ------------------------------------------------------------------
    # 2. Fetch completed rides in last 7 days
    # ------------------------------------------------------------------
    rides_stmt = select(Ride).where(
        and_(
            Ride.driver_id == driver_id,
            Ride.status == RideStatus.COMPLETED,
            Ride.requested_at >= week_start,
        )
    )
    rides_result = await db.execute(rides_stmt)
    rides = rides_result.scalars().all()

    earnings_this_week: float = sum(r.actual_fare or 0.0 for r in rides)
    tips_this_week: float = sum(r.tip_amount or 0.0 for r in rides)
    earnings_this_week = round(earnings_this_week, 2)
    tips_this_week = round(tips_this_week, 2)

    estimated_hourly: Optional[float] = None
    if hours_this_week > 0:
        estimated_hourly = round(earnings_this_week / hours_this_week, 2)

    # ------------------------------------------------------------------
    # 3. Fetch earnings goal
    # ------------------------------------------------------------------
    goal_stmt = select(DriverEarningsGoal).join(
        DriverProfile, DriverEarningsGoal.driver_profile_id == DriverProfile.id
    ).where(DriverProfile.user_id == driver_id)
    goal_result = await db.execute(goal_stmt)
    goal = goal_result.scalar_one_or_none()

    earnings_goal_set = goal is not None
    goal_target: Optional[float] = None
    goal_progress_pct: Optional[float] = None

    if goal is not None:
        goal_target = goal.target_amount
        reference_earnings = earnings_this_week
        if goal.period_type == GoalPeriodType.DAILY:
            # Measure against today's earnings only
            today_earnings = sum(
                r.actual_fare or 0.0
                for r in rides
                if r.requested_at >= day_start
            )
            reference_earnings = round(today_earnings, 2)

        if goal_target and goal_target > 0:
            goal_progress_pct = round((reference_earnings / goal_target) * 100.0, 1)

    earnings_metrics = EarningsMetrics(
        earnings_this_week_usd=earnings_this_week,
        tips_this_week_usd=tips_this_week,
        rides_completed_this_week=len(rides),
        estimated_hourly_rate_usd=estimated_hourly,
        earnings_goal_set=earnings_goal_set,
        earnings_goal_target_usd=goal_target,
        earnings_goal_progress_pct=goal_progress_pct,
    )

    # ------------------------------------------------------------------
    # 4. Fetch insurance status
    # ------------------------------------------------------------------
    insurance_stmt = select(DriverInsuranceDocument).where(
        DriverInsuranceDocument.driver_id == driver_id
    )
    insurance_result = await db.execute(insurance_stmt)
    insurance_docs = insurance_result.scalars().all()

    insurance_status = _build_insurance_status(list(insurance_docs), today)

    # ------------------------------------------------------------------
    # 5. Fetch driver profile
    # ------------------------------------------------------------------
    profile_stmt = select(DriverProfile).where(DriverProfile.user_id == driver_id)
    profile_result = await db.execute(profile_stmt)
    profile = profile_result.scalar_one_or_none()

    if profile is not None:
        cooperative_status = CooperativeStatus(
            is_approved_member=profile.is_approved,
            total_trips_lifetime=profile.total_trips,
            average_rating=round(profile.rating_avg, 2),
            background_check_status=profile.background_check_status,
        )
    else:
        # Profile not yet created — driver is in onboarding
        cooperative_status = CooperativeStatus(
            is_approved_member=False,
            total_trips_lifetime=0,
            average_rating=0.0,
            background_check_status="pending",
        )

    # ------------------------------------------------------------------
    # 6. Build welfare note
    # ------------------------------------------------------------------
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
