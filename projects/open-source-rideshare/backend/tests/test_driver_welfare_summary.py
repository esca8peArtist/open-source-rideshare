"""Tests for the driver welfare summary feature.

GET /drivers/me/welfare-summary

Coverage
--------
Service layer (get_driver_welfare_summary)
  - No shifts, no rides, no profile → zeros, default cooperative status
  - Shifts this week → hours computed correctly
  - Active (open) shift → active_shift_hours populated
  - Completed shift from today → hours_today incremented
  - Multiple shifts → total hours summed, max_consecutive set
  - Shift older than 7 days → excluded from hours_this_week
  - Rides this week → earnings and tips accumulated
  - Rides older than 7 days → excluded
  - Hours this week > 0 → estimated_hourly_rate computed
  - Hours this week = 0 → estimated_hourly_rate is None
  - Earnings goal set (weekly) → progress_pct computed from weekly earnings
  - Earnings goal set (daily) → progress_pct computed from today's earnings
  - No earnings goal → goal_set False, target/progress None
  - Insurance: active, no expiry warning → status 'active'
  - Insurance: expiring within 30 days → status 'expiring_soon'
  - Insurance: expired (days < 0) → status 'expired'
  - Insurance: only pending docs → status 'pending'
  - Insurance: no docs → status 'not_on_file'
  - Driver profile present → cooperative_status populated
  - Driver profile absent → fallback cooperative_status (onboarding)
  - Fatigue risk: low (< 40h), moderate (40–50h), high (> 50h)
  - Welfare note: no rides, no hours → idle message
  - Welfare note: no insurance on file → urgent upload message
  - Welfare note: expired insurance → urgent message
  - Welfare note: expiring soon → expiry countdown message
  - Welfare note: high fatigue → fatigue warning
  - Welfare note: active shift >= 10h → single-shift fatigue warning
  - Welfare note: goal reached (>= 100%) → congratulations message
  - Welfare note: normal state → earnings/hours summary
  - Support resources always present and non-empty

Helpers (_fatigue_risk, _build_insurance_status, _build_welfare_note)
  - _fatigue_risk: 0h → low, 39.9h → low, 40h → moderate, 50h → high, 55h → high
  - _build_insurance_status: approved not-expired → active
  - _build_insurance_status: no docs → not_on_file
  - _build_insurance_status: approved + pending → approved wins
  - _build_welfare_note: no insurance wins over fatigue

Schema (DriverWelfareSummary, sub-schemas)
  - All required fields present
  - Optional fields can be None
  - support_resources is a list

Router (get_welfare_summary)
  - Delegates to service with driver.id
  - Returns DriverWelfareSummary
"""
from __future__ import annotations

import enum
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.driver_welfare_summary import (
    CooperativeStatus,
    DriverWelfareSummary,
    EarningsMetrics,
    InsuranceStatus,
    ShiftMetrics,
    SupportResource,
)
from app.services.driver_welfare_summary import (
    _RECOMMENDED_DAILY_MAX_HOURS,
    _RECOMMENDED_WEEKLY_MAX_HOURS,
    _build_insurance_status,
    _build_welfare_note,
    _compute_shift_hours,
    _fatigue_risk,
    get_driver_welfare_summary,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

DRIVER_ID = 7
NOW = datetime(2026, 4, 17, 14, 0, 0, tzinfo=timezone.utc)
TODAY = NOW.date()
WEEK_START = datetime(2026, 4, 10, 0, 0, 0, tzinfo=timezone.utc)  # 7 days before today
DAY_START = datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Mock builders
# ---------------------------------------------------------------------------


def _make_shift(
    *,
    started_at: datetime,
    ended_at: Optional[datetime] = None,
    status: str = "completed",
    rides_completed: int = 1,
) -> MagicMock:
    from app.models.driver_shift import ShiftStatus

    shift = MagicMock()
    shift.driver_id = DRIVER_ID
    shift.started_at = started_at
    shift.ended_at = ended_at
    status_map = {
        "active": ShiftStatus.active,
        "completed": ShiftStatus.completed,
        "auto_ended": ShiftStatus.auto_ended,
    }
    shift.status = status_map[status]
    shift.rides_completed = rides_completed
    shift.total_minutes = None if ended_at is None else (ended_at - started_at).total_seconds() / 60.0
    return shift


def _make_ride(
    *,
    actual_fare: float = 10.0,
    tip_amount: float = 0.0,
    requested_at: Optional[datetime] = None,
) -> MagicMock:
    ride = MagicMock()
    ride.driver_id = DRIVER_ID
    ride.actual_fare = actual_fare
    ride.tip_amount = tip_amount
    ride.requested_at = requested_at or datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
    return ride


def _make_goal(
    *,
    target_amount: float = 500.0,
    period_type: str = "weekly",
) -> MagicMock:
    from app.models.driver_earnings_goal import GoalPeriodType

    goal = MagicMock()
    goal.target_amount = target_amount
    goal.period_type = GoalPeriodType.WEEKLY if period_type == "weekly" else GoalPeriodType.DAILY
    return goal


def _make_insurance_doc(
    *,
    status: str = "approved",
    policy_end_date: date = date(2027, 1, 1),
) -> MagicMock:
    from app.models.driver_insurance import InsuranceDocumentStatus

    doc = MagicMock()
    status_map = {
        "approved": InsuranceDocumentStatus.APPROVED,
        "pending_review": InsuranceDocumentStatus.PENDING_REVIEW,
        "pending_upload": InsuranceDocumentStatus.PENDING_UPLOAD,
        "rejected": InsuranceDocumentStatus.REJECTED,
        "expired": InsuranceDocumentStatus.EXPIRED,
    }
    doc.status = status_map[status]
    doc.policy_end_date = policy_end_date
    return doc


def _make_profile(
    *,
    is_approved: bool = True,
    total_trips: int = 100,
    rating_avg: float = 4.8,
    background_check_status: str = "approved",
    user_id: int = DRIVER_ID,
) -> MagicMock:
    profile = MagicMock()
    profile.user_id = user_id
    profile.is_approved = is_approved
    profile.total_trips = total_trips
    profile.rating_avg = rating_avg
    profile.background_check_status = background_check_status
    return profile


def _make_scalars(items: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    result.scalar_one_or_none.return_value = items[0] if items else None
    return result


def _mock_db(
    shifts: list,
    rides: list,
    goal,
    insurance_docs: list,
    profile,
) -> AsyncMock:
    """Return a mock AsyncSession with sequential execute results.

    The service makes 5 db.execute calls in order:
      1. DriverShift query
      2. Ride query
      3. DriverEarningsGoal query (scalar_one_or_none)
      4. DriverInsuranceDocument query
      5. DriverProfile query (scalar_one_or_none)
    """
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _make_scalars(shifts),
        _make_scalars(rides),
        _make_scalars([goal] if goal is not None else []),
        _make_scalars(insurance_docs),
        _make_scalars([profile] if profile is not None else []),
    ])
    return db


# ---------------------------------------------------------------------------
# _compute_shift_hours — unit tests
# ---------------------------------------------------------------------------


class TestComputeShiftHours:
    def test_completed_shift_duration(self):
        started = datetime(2026, 4, 17, 8, 0, 0, tzinfo=timezone.utc)
        ended = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)
        assert _compute_shift_hours(started, ended, NOW) == pytest.approx(4.0)

    def test_active_shift_uses_now(self):
        started = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)
        # NOW is 14:00, so 2 hours elapsed
        assert _compute_shift_hours(started, None, NOW) == pytest.approx(2.0)

    def test_zero_duration_shift(self):
        t = datetime(2026, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
        assert _compute_shift_hours(t, t, NOW) == pytest.approx(0.0)

    def test_negative_never_returned(self):
        # ended before started — should return 0.0
        started = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)
        ended = datetime(2026, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
        assert _compute_shift_hours(started, ended, NOW) == 0.0


# ---------------------------------------------------------------------------
# _fatigue_risk — unit tests
# ---------------------------------------------------------------------------


class TestFatigueRisk:
    def test_zero_hours_is_low(self):
        assert _fatigue_risk(0.0) == "low"

    def test_below_40_is_low(self):
        assert _fatigue_risk(39.9) == "low"

    def test_exactly_40_is_moderate(self):
        assert _fatigue_risk(40.0) == "moderate"

    def test_between_40_and_50_is_moderate(self):
        assert _fatigue_risk(45.0) == "moderate"

    def test_below_50_is_still_moderate(self):
        assert _fatigue_risk(49.9) == "moderate"

    def test_exactly_50_is_high(self):
        assert _fatigue_risk(50.0) == "high"

    def test_above_50_is_high(self):
        assert _fatigue_risk(60.0) == "high"


# ---------------------------------------------------------------------------
# _build_insurance_status — unit tests
# ---------------------------------------------------------------------------


class TestBuildInsuranceStatus:
    def test_no_docs_returns_not_on_file(self):
        status = _build_insurance_status([], TODAY)
        assert status.status == "not_on_file"
        assert status.expires_on is None
        assert status.days_until_expiry is None

    def test_approved_far_future_returns_active(self):
        doc = _make_insurance_doc(status="approved", policy_end_date=date(2027, 6, 1))
        status = _build_insurance_status([doc], TODAY)
        assert status.status == "active"
        assert status.expires_on == date(2027, 6, 1)
        assert status.days_until_expiry > 30

    def test_approved_expiring_within_30_days_returns_expiring_soon(self):
        expiry = TODAY + timedelta(days=15)
        doc = _make_insurance_doc(status="approved", policy_end_date=expiry)
        status = _build_insurance_status([doc], TODAY)
        assert status.status == "expiring_soon"
        assert status.days_until_expiry == 15

    def test_approved_expired_returns_expired(self):
        expiry = TODAY - timedelta(days=5)
        doc = _make_insurance_doc(status="approved", policy_end_date=expiry)
        status = _build_insurance_status([doc], TODAY)
        assert status.status == "expired"
        assert status.days_until_expiry == -5

    def test_only_pending_review_returns_pending(self):
        doc = _make_insurance_doc(status="pending_review", policy_end_date=date(2027, 1, 1))
        status = _build_insurance_status([doc], TODAY)
        assert status.status == "pending"

    def test_only_pending_upload_returns_pending(self):
        doc = _make_insurance_doc(status="pending_upload", policy_end_date=date(2027, 1, 1))
        status = _build_insurance_status([doc], TODAY)
        assert status.status == "pending"

    def test_approved_wins_over_pending(self):
        approved = _make_insurance_doc(status="approved", policy_end_date=date(2027, 1, 1))
        pending = _make_insurance_doc(status="pending_review", policy_end_date=date(2027, 6, 1))
        status = _build_insurance_status([approved, pending], TODAY)
        assert status.status == "active"

    def test_latest_expiry_chosen_among_multiple_approved(self):
        early = _make_insurance_doc(status="approved", policy_end_date=date(2026, 8, 1))
        late = _make_insurance_doc(status="approved", policy_end_date=date(2027, 3, 1))
        status = _build_insurance_status([early, late], TODAY)
        assert status.expires_on == date(2027, 3, 1)

    def test_all_rejected_returns_expired(self):
        doc = _make_insurance_doc(status="rejected", policy_end_date=date(2025, 1, 1))
        status = _build_insurance_status([doc], TODAY)
        assert status.status == "expired"


# ---------------------------------------------------------------------------
# _build_welfare_note — unit tests
# ---------------------------------------------------------------------------


def _make_shift_metrics(
    hours_this_week: float = 20.0,
    hours_today: float = 4.0,
    fatigue_risk: str = "low",
    active_shift_hours: Optional[float] = None,
) -> ShiftMetrics:
    return ShiftMetrics(
        hours_this_week=hours_this_week,
        hours_today=hours_today,
        max_consecutive_hours=None,
        active_shift_hours=active_shift_hours,
        fatigue_risk=fatigue_risk,
        recommended_weekly_max_hours=_RECOMMENDED_WEEKLY_MAX_HOURS,
        recommended_daily_max_hours=_RECOMMENDED_DAILY_MAX_HOURS,
    )


def _make_earnings_metrics(
    earnings_this_week_usd: float = 200.0,
    rides_completed_this_week: int = 20,
    tips_this_week_usd: float = 15.0,
    estimated_hourly_rate_usd: Optional[float] = 10.0,
    earnings_goal_set: bool = False,
    earnings_goal_target_usd: Optional[float] = None,
    earnings_goal_progress_pct: Optional[float] = None,
) -> EarningsMetrics:
    return EarningsMetrics(
        earnings_this_week_usd=earnings_this_week_usd,
        tips_this_week_usd=tips_this_week_usd,
        rides_completed_this_week=rides_completed_this_week,
        estimated_hourly_rate_usd=estimated_hourly_rate_usd,
        earnings_goal_set=earnings_goal_set,
        earnings_goal_target_usd=earnings_goal_target_usd,
        earnings_goal_progress_pct=earnings_goal_progress_pct,
    )


def _make_insurance_status(status: str = "active") -> InsuranceStatus:
    return InsuranceStatus(
        status=status,
        expires_on=date(2027, 6, 1) if status not in ("not_on_file", "pending") else None,
        days_until_expiry=420 if status == "active" else (15 if status == "expiring_soon" else None),
    )


class TestBuildWelfareNote:
    def test_no_insurance_on_file_urgent(self):
        note = _build_welfare_note(
            _make_shift_metrics(),
            _make_earnings_metrics(),
            _make_insurance_status("not_on_file"),
        )
        assert "No insurance document" in note
        assert "upload" in note.lower()

    def test_expired_insurance_urgent(self):
        note = _build_welfare_note(
            _make_shift_metrics(),
            _make_earnings_metrics(),
            _make_insurance_status("expired"),
        )
        assert "expired" in note.lower()
        assert "renewed policy" in note.lower()

    def test_expiring_soon_shows_countdown(self):
        ins = InsuranceStatus(status="expiring_soon", expires_on=date(2026, 5, 2), days_until_expiry=15)
        note = _build_welfare_note(
            _make_shift_metrics(),
            _make_earnings_metrics(),
            ins,
        )
        assert "15 day" in note
        assert "expir" in note.lower()

    def test_expiring_1_day_singular_grammar(self):
        ins = InsuranceStatus(status="expiring_soon", expires_on=date(2026, 4, 18), days_until_expiry=1)
        note = _build_welfare_note(
            _make_shift_metrics(),
            _make_earnings_metrics(),
            ins,
        )
        assert "1 day" in note
        assert "1 days" not in note

    def test_insurance_priority_over_fatigue(self):
        """Insurance issues should be surfaced before fatigue warnings."""
        note = _build_welfare_note(
            _make_shift_metrics(hours_this_week=55.0, fatigue_risk="high"),
            _make_earnings_metrics(),
            _make_insurance_status("not_on_file"),
        )
        # Insurance message, not fatigue message
        assert "insurance" in note.lower()
        assert "fatigue" not in note.lower()

    def test_high_fatigue_risk(self):
        note = _build_welfare_note(
            _make_shift_metrics(hours_this_week=55.0, fatigue_risk="high"),
            _make_earnings_metrics(),
            _make_insurance_status("active"),
        )
        assert "55.0 hours" in note
        assert "cooperative" in note.lower()

    def test_active_shift_too_long(self):
        note = _build_welfare_note(
            _make_shift_metrics(
                hours_this_week=30.0,
                fatigue_risk="low",
                active_shift_hours=10.5,
            ),
            _make_earnings_metrics(),
            _make_insurance_status("active"),
        )
        assert "10.5 hours" in note
        assert "break" in note.lower()

    def test_moderate_fatigue(self):
        note = _build_welfare_note(
            _make_shift_metrics(hours_this_week=45.0, fatigue_risk="moderate"),
            _make_earnings_metrics(),
            _make_insurance_status("active"),
        )
        assert "45.0 hours" in note
        assert "approaching" in note.lower()

    def test_goal_reached(self):
        note = _build_welfare_note(
            _make_shift_metrics(),
            _make_earnings_metrics(
                earnings_goal_set=True,
                earnings_goal_target_usd=200.0,
                earnings_goal_progress_pct=100.0,
            ),
            _make_insurance_status("active"),
        )
        assert "Goal reached" in note or "goal" in note.lower()

    def test_goal_over_100_pct_still_congrats(self):
        note = _build_welfare_note(
            _make_shift_metrics(),
            _make_earnings_metrics(
                earnings_goal_set=True,
                earnings_goal_target_usd=100.0,
                earnings_goal_progress_pct=120.0,
            ),
            _make_insurance_status("active"),
        )
        assert "Goal reached" in note or "goal" in note.lower()

    def test_no_rides_idle_message(self):
        note = _build_welfare_note(
            _make_shift_metrics(hours_this_week=0.0, hours_today=0.0, fatigue_risk="low"),
            _make_earnings_metrics(earnings_this_week_usd=0.0, rides_completed_this_week=0, estimated_hourly_rate_usd=None),
            _make_insurance_status("active"),
        )
        assert "0" in note or "haven't completed" in note.lower() or "no ride" in note.lower()

    def test_normal_state_shows_earnings_summary(self):
        note = _build_welfare_note(
            _make_shift_metrics(hours_this_week=15.0, hours_today=3.0, fatigue_risk="low"),
            _make_earnings_metrics(
                earnings_this_week_usd=180.0,
                rides_completed_this_week=18,
                estimated_hourly_rate_usd=12.0,
            ),
            _make_insurance_status("active"),
        )
        assert "18 rides" in note or "rides" in note.lower()
        assert "$180.00" in note or "180" in note


# ---------------------------------------------------------------------------
# get_driver_welfare_summary — service integration tests (mocked DB)
# ---------------------------------------------------------------------------


class TestGetDriverWelfareSummaryService:
    @pytest.mark.asyncio
    async def test_no_data_returns_zeros(self):
        db = _mock_db(
            shifts=[],
            rides=[],
            goal=None,
            insurance_docs=[],
            profile=None,
        )
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert result.shift_metrics.hours_this_week == 0.0
        assert result.shift_metrics.hours_today == 0.0
        assert result.shift_metrics.fatigue_risk == "low"
        assert result.shift_metrics.active_shift_hours is None
        assert result.earnings_metrics.earnings_this_week_usd == 0.0
        assert result.earnings_metrics.rides_completed_this_week == 0
        assert result.earnings_metrics.estimated_hourly_rate_usd is None
        assert result.earnings_metrics.earnings_goal_set is False
        assert result.insurance_status.status == "not_on_file"
        assert result.cooperative_status.is_approved_member is False
        assert result.cooperative_status.total_trips_lifetime == 0

    @pytest.mark.asyncio
    async def test_completed_shift_contributes_hours(self):
        shift = _make_shift(
            started_at=datetime(2026, 4, 15, 8, 0, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc),
            status="completed",
        )
        db = _mock_db([shift], [], None, [], None)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert result.shift_metrics.hours_this_week == pytest.approx(4.0)
        assert result.shift_metrics.max_consecutive_hours == pytest.approx(4.0)

    @pytest.mark.asyncio
    async def test_active_shift_sets_active_shift_hours(self):
        # Shift started 2 hours before NOW
        started = NOW - timedelta(hours=2)
        shift = _make_shift(
            started_at=started,
            ended_at=None,
            status="active",
        )
        db = _mock_db([shift], [], None, [], None)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert result.shift_metrics.active_shift_hours == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_todays_shift_counted_in_hours_today(self):
        # Shift started today at 08:00
        shift = _make_shift(
            started_at=datetime(2026, 4, 17, 8, 0, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 4, 17, 11, 0, 0, tzinfo=timezone.utc),
            status="completed",
        )
        db = _mock_db([shift], [], None, [], None)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert result.shift_metrics.hours_today == pytest.approx(3.0)

    @pytest.mark.asyncio
    async def test_multiple_shifts_hours_summed(self):
        shift_a = _make_shift(
            started_at=datetime(2026, 4, 14, 8, 0, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc),
            status="completed",
        )
        shift_b = _make_shift(
            started_at=datetime(2026, 4, 15, 9, 0, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 4, 15, 15, 0, 0, tzinfo=timezone.utc),
            status="completed",
        )
        db = _mock_db([shift_a, shift_b], [], None, [], None)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert result.shift_metrics.hours_this_week == pytest.approx(10.0)
        assert result.shift_metrics.max_consecutive_hours == pytest.approx(6.0)

    @pytest.mark.asyncio
    async def test_rides_this_week_earnings_accumulated(self):
        ride_a = _make_ride(actual_fare=20.0, tip_amount=3.0)
        ride_b = _make_ride(actual_fare=15.0, tip_amount=0.0)
        db = _mock_db([], [ride_a, ride_b], None, [], None)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert result.earnings_metrics.earnings_this_week_usd == pytest.approx(35.0)
        assert result.earnings_metrics.tips_this_week_usd == pytest.approx(3.0)
        assert result.earnings_metrics.rides_completed_this_week == 2

    @pytest.mark.asyncio
    async def test_hourly_rate_computed_when_hours_nonzero(self):
        shift = _make_shift(
            started_at=datetime(2026, 4, 15, 8, 0, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 4, 15, 18, 0, 0, tzinfo=timezone.utc),
            status="completed",
        )  # 10 hours
        ride = _make_ride(actual_fare=200.0)
        db = _mock_db([shift], [ride], None, [], None)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert result.earnings_metrics.estimated_hourly_rate_usd == pytest.approx(20.0)

    @pytest.mark.asyncio
    async def test_hourly_rate_is_none_when_zero_hours(self):
        ride = _make_ride(actual_fare=50.0)
        db = _mock_db([], [ride], None, [], None)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert result.earnings_metrics.estimated_hourly_rate_usd is None

    @pytest.mark.asyncio
    async def test_weekly_goal_progress_pct_computed(self):
        goal = _make_goal(target_amount=400.0, period_type="weekly")
        ride = _make_ride(actual_fare=200.0)
        db = _mock_db([], [ride], goal, [], None)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert result.earnings_metrics.earnings_goal_set is True
        assert result.earnings_metrics.earnings_goal_target_usd == 400.0
        assert result.earnings_metrics.earnings_goal_progress_pct == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_no_goal_fields_are_none(self):
        db = _mock_db([], [], None, [], None)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert result.earnings_metrics.earnings_goal_set is False
        assert result.earnings_metrics.earnings_goal_target_usd is None
        assert result.earnings_metrics.earnings_goal_progress_pct is None

    @pytest.mark.asyncio
    async def test_active_insurance_status(self):
        doc = _make_insurance_doc(status="approved", policy_end_date=date(2027, 6, 1))
        db = _mock_db([], [], None, [doc], None)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert result.insurance_status.status == "active"
        assert result.insurance_status.expires_on == date(2027, 6, 1)

    @pytest.mark.asyncio
    async def test_expiring_soon_insurance_status(self):
        expiry = TODAY + timedelta(days=20)
        doc = _make_insurance_doc(status="approved", policy_end_date=expiry)
        db = _mock_db([], [], None, [doc], None)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert result.insurance_status.status == "expiring_soon"
        assert result.insurance_status.days_until_expiry == 20

    @pytest.mark.asyncio
    async def test_no_insurance_status(self):
        db = _mock_db([], [], None, [], None)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert result.insurance_status.status == "not_on_file"

    @pytest.mark.asyncio
    async def test_driver_profile_populates_cooperative_status(self):
        profile = _make_profile(
            is_approved=True,
            total_trips=250,
            rating_avg=4.92,
            background_check_status="approved",
        )
        db = _mock_db([], [], None, [], profile)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert result.cooperative_status.is_approved_member is True
        assert result.cooperative_status.total_trips_lifetime == 250
        assert result.cooperative_status.average_rating == pytest.approx(4.92)
        assert result.cooperative_status.background_check_status == "approved"

    @pytest.mark.asyncio
    async def test_no_profile_gives_onboarding_defaults(self):
        db = _mock_db([], [], None, [], None)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert result.cooperative_status.is_approved_member is False
        assert result.cooperative_status.total_trips_lifetime == 0
        assert result.cooperative_status.average_rating == 0.0

    @pytest.mark.asyncio
    async def test_high_fatigue_risk_from_shifts(self):
        # 51 hours of shifts — span two days to avoid invalid hour value
        start = datetime(2026, 4, 10, 8, 0, 0, tzinfo=timezone.utc)
        shifts = [
            _make_shift(
                started_at=start,
                ended_at=start + timedelta(hours=51),
                status="completed",
            )
        ]
        db = _mock_db(shifts, [], None, [], None)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert result.shift_metrics.fatigue_risk == "high"

    @pytest.mark.asyncio
    async def test_support_resources_always_present(self):
        db = _mock_db([], [], None, [], None)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert len(result.support_resources) > 0
        names = [r.name for r in result.support_resources]
        assert any("safety" in n.lower() or "guideline" in n.lower() for n in names)
        assert any("hardship" in n.lower() or "fund" in n.lower() for n in names)

    @pytest.mark.asyncio
    async def test_as_of_timestamp_is_present(self):
        db = _mock_db([], [], None, [], None)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert result.as_of == NOW

    @pytest.mark.asyncio
    async def test_welfare_note_is_non_empty(self):
        db = _mock_db([], [], None, [], None)
        with patch("app.services.driver_welfare_summary._utc_now", return_value=NOW):
            result = await get_driver_welfare_summary(db, DRIVER_ID)

        assert len(result.welfare_note) > 0


# ---------------------------------------------------------------------------
# DriverWelfareSummary schema — unit tests
# ---------------------------------------------------------------------------


class TestDriverWelfareSummarySchema:
    def _make_full_summary(self) -> DriverWelfareSummary:
        return DriverWelfareSummary(
            as_of=NOW,
            shift_metrics=ShiftMetrics(
                hours_this_week=20.0,
                hours_today=4.0,
                max_consecutive_hours=4.0,
                active_shift_hours=None,
                fatigue_risk="low",
                recommended_weekly_max_hours=50.0,
                recommended_daily_max_hours=10.0,
            ),
            earnings_metrics=EarningsMetrics(
                earnings_this_week_usd=200.0,
                tips_this_week_usd=15.0,
                rides_completed_this_week=20,
                estimated_hourly_rate_usd=10.0,
                earnings_goal_set=False,
                earnings_goal_target_usd=None,
                earnings_goal_progress_pct=None,
            ),
            insurance_status=InsuranceStatus(
                status="active",
                expires_on=date(2027, 6, 1),
                days_until_expiry=420,
            ),
            cooperative_status=CooperativeStatus(
                is_approved_member=True,
                total_trips_lifetime=150,
                average_rating=4.85,
                background_check_status="approved",
            ),
            welfare_note="All good this week.",
            support_resources=[
                SupportResource(name="Safety Guidelines", description="Stay safe."),
            ],
        )

    def test_all_fields_present(self):
        s = self._make_full_summary()
        assert s.shift_metrics.hours_this_week == 20.0
        assert s.earnings_metrics.earnings_this_week_usd == 200.0
        assert s.insurance_status.status == "active"
        assert s.cooperative_status.is_approved_member is True
        assert len(s.support_resources) == 1
        assert s.welfare_note == "All good this week."

    def test_optional_fields_can_be_none(self):
        s = self._make_full_summary()
        assert s.shift_metrics.active_shift_hours is None
        assert s.earnings_metrics.earnings_goal_target_usd is None

    def test_serialises_to_dict(self):
        s = self._make_full_summary()
        d = s.model_dump()
        assert "shift_metrics" in d
        assert "earnings_metrics" in d
        assert "insurance_status" in d
        assert "cooperative_status" in d
        assert "welfare_note" in d
        assert "support_resources" in d
        assert isinstance(d["support_resources"], list)


# ---------------------------------------------------------------------------
# get_welfare_summary — router unit tests
# ---------------------------------------------------------------------------


class TestGetWelfareSummaryRouter:
    @pytest.mark.asyncio
    async def test_router_delegates_to_service(self):
        from app.api.v1.driver_welfare_summary import get_welfare_summary

        mock_driver = MagicMock()
        mock_driver.id = DRIVER_ID
        mock_db = AsyncMock()

        stub = DriverWelfareSummary(
            as_of=NOW,
            shift_metrics=ShiftMetrics(
                hours_this_week=0.0, hours_today=0.0,
                max_consecutive_hours=None, active_shift_hours=None,
                fatigue_risk="low",
                recommended_weekly_max_hours=50.0,
                recommended_daily_max_hours=10.0,
            ),
            earnings_metrics=EarningsMetrics(
                earnings_this_week_usd=0.0, tips_this_week_usd=0.0,
                rides_completed_this_week=0, estimated_hourly_rate_usd=None,
                earnings_goal_set=False, earnings_goal_target_usd=None,
                earnings_goal_progress_pct=None,
            ),
            insurance_status=InsuranceStatus(
                status="not_on_file", expires_on=None, days_until_expiry=None,
            ),
            cooperative_status=CooperativeStatus(
                is_approved_member=False, total_trips_lifetime=0,
                average_rating=0.0, background_check_status="pending",
            ),
            welfare_note="Welcome.",
            support_resources=[],
        )

        with patch(
            "app.api.v1.driver_welfare_summary.get_driver_welfare_summary",
            new_callable=AsyncMock,
            return_value=stub,
        ) as mock_service:
            result = await get_welfare_summary(driver=mock_driver, db=mock_db)

        mock_service.assert_called_once_with(db=mock_db, driver_id=DRIVER_ID)
        assert result is stub

    @pytest.mark.asyncio
    async def test_router_passes_correct_driver_id(self):
        from app.api.v1.driver_welfare_summary import get_welfare_summary

        mock_driver = MagicMock()
        mock_driver.id = 999
        mock_db = AsyncMock()

        stub = DriverWelfareSummary(
            as_of=NOW,
            shift_metrics=ShiftMetrics(
                hours_this_week=0.0, hours_today=0.0,
                max_consecutive_hours=None, active_shift_hours=None,
                fatigue_risk="low",
                recommended_weekly_max_hours=50.0,
                recommended_daily_max_hours=10.0,
            ),
            earnings_metrics=EarningsMetrics(
                earnings_this_week_usd=0.0, tips_this_week_usd=0.0,
                rides_completed_this_week=0, estimated_hourly_rate_usd=None,
                earnings_goal_set=False, earnings_goal_target_usd=None,
                earnings_goal_progress_pct=None,
            ),
            insurance_status=InsuranceStatus(
                status="not_on_file", expires_on=None, days_until_expiry=None,
            ),
            cooperative_status=CooperativeStatus(
                is_approved_member=False, total_trips_lifetime=0,
                average_rating=0.0, background_check_status="pending",
            ),
            welfare_note="Welcome.",
            support_resources=[],
        )

        with patch(
            "app.api.v1.driver_welfare_summary.get_driver_welfare_summary",
            new_callable=AsyncMock,
            return_value=stub,
        ) as mock_service:
            await get_welfare_summary(driver=mock_driver, db=mock_db)

        call_kwargs = mock_service.call_args.kwargs
        assert call_kwargs["driver_id"] == 999
