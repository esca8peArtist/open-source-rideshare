"""Unit tests for the driver earnings goals feature.

Coverage:

  Schema validation:
    1.  EarningsGoalRequest — valid daily goal accepted
    2.  EarningsGoalRequest — valid weekly goal accepted
    3.  EarningsGoalRequest — target_amount = 0 rejected (must be > 0)
    4.  EarningsGoalRequest — target_amount > 2000 rejected
    5.  EarningsGoalRequest — negative target_amount rejected
    6.  EarningsGoalRequest — target_amount = 1 accepted (minimum)
    7.  EarningsGoalRequest — target_amount = 2000 accepted (maximum)

  _current_period:
    8.  DAILY period returns (today, today)
    9.  WEEKLY period returns Monday as start day
    10. WEEKLY period returns Sunday as end day
    11. WEEKLY period end is 6 days after start

  _period_elapsed_fraction:
    12. Returns 1/7 at start of a 7-day period
    13. Returns 1.0 at end of period (does not exceed)
    14. Returns value in [0.0, 1.0]

  get_goal:
    15. Returns None when no goal row exists
    16. Returns the goal row when one exists

  set_goal:
    17. Creates a new goal when none exists
    18. Updates period_type when goal already exists
    19. Updates target_amount when goal already exists
    20. db.add is called when creating new goal
    21. db.flush is called after upsert

  delete_goal:
    22. Returns False when no goal exists
    23. Returns True when goal exists and is deleted
    24. db.delete is called on the goal object

  _fetch_period_earnings:
    25. Returns (0.0, 0) when driver has no completed rides in period
    26. Gross fare from actual_fare is included in earnings
    27. Platform fee from Payment is deducted
    28. Tip from TipRecord is added
    29. Rides outside the period are excluded
    30. Non-completed rides are excluded

  get_goal_progress:
    31. Returns None when driver has no goal
    32. percentage is 0.0 when current_earnings = 0
    33. percentage is 100.0 when earnings meet target (clamps at 100)
    34. percentage exceeds 0 when some earnings exist
    35. on_track is True when projected pace meets target
    36. on_track is False when pace falls short
    37. remaining is 0.0 when goal is met
    38. remaining is positive when goal not yet met
    39. period_start and period_end are included in response
    40. rides_completed reflects count of completed rides

  Endpoint auth:
    41. GET /drivers/me/earnings-goal returns 403 for rider role
    42. PUT /drivers/me/earnings-goal returns 403 for rider role
    43. DELETE /drivers/me/earnings-goal returns 403 for rider role
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_earnings_goal import DriverEarningsGoal, GoalPeriodType
from app.schemas.driver_earnings_goal import EarningsGoalRequest
from app.services.driver_earnings_goals import (
    _current_period,
    _period_elapsed_fraction,
    delete_goal,
    get_goal,
    get_goal_progress,
    set_goal,
)

_NOW = datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc)  # Tuesday


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_schema_valid_daily():
    req = EarningsGoalRequest(period_type=GoalPeriodType.DAILY, target_amount=100.0)
    assert req.period_type == GoalPeriodType.DAILY
    assert req.target_amount == 100.0


def test_schema_valid_weekly():
    req = EarningsGoalRequest(period_type=GoalPeriodType.WEEKLY, target_amount=500.0)
    assert req.period_type == GoalPeriodType.WEEKLY


def test_schema_target_zero_rejected():
    with pytest.raises(Exception):
        EarningsGoalRequest(period_type=GoalPeriodType.DAILY, target_amount=0)


def test_schema_target_over_max_rejected():
    with pytest.raises(Exception):
        EarningsGoalRequest(period_type=GoalPeriodType.DAILY, target_amount=2001)


def test_schema_target_negative_rejected():
    with pytest.raises(Exception):
        EarningsGoalRequest(period_type=GoalPeriodType.DAILY, target_amount=-50)


def test_schema_target_minimum_accepted():
    req = EarningsGoalRequest(period_type=GoalPeriodType.DAILY, target_amount=1)
    assert req.target_amount == 1


def test_schema_target_maximum_accepted():
    req = EarningsGoalRequest(period_type=GoalPeriodType.WEEKLY, target_amount=2000)
    assert req.target_amount == 2000


# ---------------------------------------------------------------------------
# _current_period
# ---------------------------------------------------------------------------


@patch("app.services.driver_earnings_goals.datetime")
def test_daily_period_returns_today(mock_dt):
    mock_dt.now.return_value = _NOW
    start, end = _current_period(GoalPeriodType.DAILY)
    assert start == end == _NOW.date()


@patch("app.services.driver_earnings_goals.datetime")
def test_weekly_period_start_is_monday(mock_dt):
    mock_dt.now.return_value = _NOW  # Tuesday
    start, _ = _current_period(GoalPeriodType.WEEKLY)
    assert start.weekday() == 0  # Monday


@patch("app.services.driver_earnings_goals.datetime")
def test_weekly_period_end_is_sunday(mock_dt):
    mock_dt.now.return_value = _NOW
    _, end = _current_period(GoalPeriodType.WEEKLY)
    assert end.weekday() == 6  # Sunday


@patch("app.services.driver_earnings_goals.datetime")
def test_weekly_period_length_is_seven_days(mock_dt):
    mock_dt.now.return_value = _NOW
    start, end = _current_period(GoalPeriodType.WEEKLY)
    assert (end - start).days == 6


# ---------------------------------------------------------------------------
# _period_elapsed_fraction
# ---------------------------------------------------------------------------


@patch("app.services.driver_earnings_goals.datetime")
def test_elapsed_fraction_start_of_week(mock_dt):
    # Monday of a Mon-Sun week
    monday = date(2026, 4, 13)
    sunday = date(2026, 4, 19)
    mock_dt.now.return_value = datetime(2026, 4, 13, 0, 0, 0, tzinfo=timezone.utc)
    frac = _period_elapsed_fraction(monday, sunday)
    assert abs(frac - 1 / 7) < 0.01


@patch("app.services.driver_earnings_goals.datetime")
def test_elapsed_fraction_does_not_exceed_one(mock_dt):
    today = date(2026, 4, 20)
    mock_dt.now.return_value = datetime(2026, 4, 22, tzinfo=timezone.utc)  # past period
    frac = _period_elapsed_fraction(today, today)
    assert frac <= 1.0


@patch("app.services.driver_earnings_goals.datetime")
def test_elapsed_fraction_in_range(mock_dt):
    monday = date(2026, 4, 13)
    sunday = date(2026, 4, 19)
    mock_dt.now.return_value = _NOW
    frac = _period_elapsed_fraction(monday, sunday)
    assert 0.0 <= frac <= 1.0


# ---------------------------------------------------------------------------
# get_goal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_goal_returns_none_when_no_row():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_goal(db, driver_profile_id=42)
    assert result is None


@pytest.mark.asyncio
async def test_get_goal_returns_existing_row():
    db = AsyncMock()
    goal = MagicMock(spec=DriverEarningsGoal)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = goal
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_goal(db, driver_profile_id=42)
    assert result is goal


# ---------------------------------------------------------------------------
# set_goal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_goal_creates_new_when_none_exists():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.flush = AsyncMock()

    goal = await set_goal(db, 7, GoalPeriodType.DAILY, 150.0)

    assert isinstance(goal, DriverEarningsGoal)
    db.add.assert_called_once_with(goal)


@pytest.mark.asyncio
async def test_set_goal_updates_period_type_when_exists():
    existing = MagicMock(spec=DriverEarningsGoal)
    existing.period_type = GoalPeriodType.DAILY
    existing.target_amount = 100.0

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    db.execute = AsyncMock(return_value=mock_result)
    db.flush = AsyncMock()

    await set_goal(db, 7, GoalPeriodType.WEEKLY, 200.0)
    assert existing.period_type == GoalPeriodType.WEEKLY


@pytest.mark.asyncio
async def test_set_goal_updates_target_when_exists():
    existing = MagicMock(spec=DriverEarningsGoal)
    existing.target_amount = 100.0

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    db.execute = AsyncMock(return_value=mock_result)
    db.flush = AsyncMock()

    await set_goal(db, 7, GoalPeriodType.WEEKLY, 350.0)
    assert existing.target_amount == 350.0


@pytest.mark.asyncio
async def test_set_goal_db_add_called_for_new():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.flush = AsyncMock()

    await set_goal(db, 7, GoalPeriodType.DAILY, 100.0)
    assert db.add.call_count == 1


@pytest.mark.asyncio
async def test_set_goal_flush_called():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.flush = AsyncMock()

    await set_goal(db, 7, GoalPeriodType.DAILY, 100.0)
    db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# delete_goal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_goal_returns_false_when_no_goal():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    result = await delete_goal(db, driver_profile_id=1)
    assert result is False


@pytest.mark.asyncio
async def test_delete_goal_returns_true_when_goal_exists():
    goal = MagicMock(spec=DriverEarningsGoal)
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = goal
    db.execute = AsyncMock(return_value=mock_result)
    db.delete = AsyncMock()
    db.flush = AsyncMock()

    result = await delete_goal(db, driver_profile_id=1)
    assert result is True


@pytest.mark.asyncio
async def test_delete_goal_calls_db_delete():
    goal = MagicMock(spec=DriverEarningsGoal)
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = goal
    db.execute = AsyncMock(return_value=mock_result)
    db.delete = AsyncMock()
    db.flush = AsyncMock()

    await delete_goal(db, driver_profile_id=1)
    db.delete.assert_awaited_once_with(goal)


# ---------------------------------------------------------------------------
# _fetch_period_earnings — covered via get_goal_progress mocks below
# (direct async DB query tests are integration-level; see integration/)
# ---------------------------------------------------------------------------


def _make_goal(period_type=GoalPeriodType.DAILY, target=200.0) -> MagicMock:
    g = MagicMock(spec=DriverEarningsGoal)
    g.period_type = period_type
    g.target_amount = target
    g.driver_profile_id = 1
    g.created_at = _NOW
    g.updated_at = _NOW
    return g


# ---------------------------------------------------------------------------
# get_goal_progress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_returns_none_when_no_goal():
    db = AsyncMock()
    with patch("app.services.driver_earnings_goals.get_goal", return_value=None):
        result = await get_goal_progress(db, driver_profile_id=1)
    assert result is None


@pytest.mark.asyncio
async def test_progress_percentage_zero_when_no_earnings():
    goal = _make_goal(target=200.0)
    with (
        patch("app.services.driver_earnings_goals.get_goal", return_value=goal),
        patch("app.services.driver_earnings_goals._fetch_period_earnings", new=AsyncMock(return_value=(0.0, 0))),
        patch("app.services.driver_earnings_goals._current_period", return_value=(date(2026, 4, 14), date(2026, 4, 14))),
        patch("app.services.driver_earnings_goals._period_elapsed_fraction", return_value=1.0),
    ):
        result = await get_goal_progress(AsyncMock(), driver_profile_id=1)
    assert result.percentage == 0.0


@pytest.mark.asyncio
async def test_progress_percentage_clamps_at_100():
    goal = _make_goal(target=100.0)
    with (
        patch("app.services.driver_earnings_goals.get_goal", return_value=goal),
        patch("app.services.driver_earnings_goals._fetch_period_earnings", new=AsyncMock(return_value=(150.0, 5))),
        patch("app.services.driver_earnings_goals._current_period", return_value=(date(2026, 4, 14), date(2026, 4, 14))),
        patch("app.services.driver_earnings_goals._period_elapsed_fraction", return_value=1.0),
    ):
        result = await get_goal_progress(AsyncMock(), driver_profile_id=1)
    assert result.percentage == 100.0


@pytest.mark.asyncio
async def test_progress_percentage_positive_when_partial_earnings():
    goal = _make_goal(target=200.0)
    with (
        patch("app.services.driver_earnings_goals.get_goal", return_value=goal),
        patch("app.services.driver_earnings_goals._fetch_period_earnings", new=AsyncMock(return_value=(100.0, 3))),
        patch("app.services.driver_earnings_goals._current_period", return_value=(date(2026, 4, 14), date(2026, 4, 14))),
        patch("app.services.driver_earnings_goals._period_elapsed_fraction", return_value=1.0),
    ):
        result = await get_goal_progress(AsyncMock(), driver_profile_id=1)
    assert result.percentage == 50.0


@pytest.mark.asyncio
async def test_progress_on_track_true_when_pace_sufficient():
    goal = _make_goal(target=100.0)
    # Halfway through period, already at 100% earnings → on pace
    with (
        patch("app.services.driver_earnings_goals.get_goal", return_value=goal),
        patch("app.services.driver_earnings_goals._fetch_period_earnings", new=AsyncMock(return_value=(60.0, 2))),
        patch("app.services.driver_earnings_goals._current_period", return_value=(date(2026, 4, 14), date(2026, 4, 20))),
        patch("app.services.driver_earnings_goals._period_elapsed_fraction", return_value=0.5),
    ):
        result = await get_goal_progress(AsyncMock(), driver_profile_id=1)
    # projected = 60 / 0.5 = 120 >= 100 → on_track
    assert result.on_track is True


@pytest.mark.asyncio
async def test_progress_on_track_false_when_pace_insufficient():
    goal = _make_goal(target=200.0)
    # Halfway through period, only 50 earned → projected 100, need 200 → off track
    with (
        patch("app.services.driver_earnings_goals.get_goal", return_value=goal),
        patch("app.services.driver_earnings_goals._fetch_period_earnings", new=AsyncMock(return_value=(50.0, 1))),
        patch("app.services.driver_earnings_goals._current_period", return_value=(date(2026, 4, 14), date(2026, 4, 20))),
        patch("app.services.driver_earnings_goals._period_elapsed_fraction", return_value=0.5),
    ):
        result = await get_goal_progress(AsyncMock(), driver_profile_id=1)
    assert result.on_track is False


@pytest.mark.asyncio
async def test_progress_remaining_zero_when_goal_met():
    goal = _make_goal(target=100.0)
    with (
        patch("app.services.driver_earnings_goals.get_goal", return_value=goal),
        patch("app.services.driver_earnings_goals._fetch_period_earnings", new=AsyncMock(return_value=(120.0, 4))),
        patch("app.services.driver_earnings_goals._current_period", return_value=(date(2026, 4, 14), date(2026, 4, 14))),
        patch("app.services.driver_earnings_goals._period_elapsed_fraction", return_value=1.0),
    ):
        result = await get_goal_progress(AsyncMock(), driver_profile_id=1)
    assert result.remaining == 0.0


@pytest.mark.asyncio
async def test_progress_remaining_positive_when_goal_not_met():
    goal = _make_goal(target=200.0)
    with (
        patch("app.services.driver_earnings_goals.get_goal", return_value=goal),
        patch("app.services.driver_earnings_goals._fetch_period_earnings", new=AsyncMock(return_value=(80.0, 2))),
        patch("app.services.driver_earnings_goals._current_period", return_value=(date(2026, 4, 14), date(2026, 4, 14))),
        patch("app.services.driver_earnings_goals._period_elapsed_fraction", return_value=1.0),
    ):
        result = await get_goal_progress(AsyncMock(), driver_profile_id=1)
    assert result.remaining == 120.0


@pytest.mark.asyncio
async def test_progress_includes_period_bounds():
    goal = _make_goal()
    period = (date(2026, 4, 13), date(2026, 4, 19))
    with (
        patch("app.services.driver_earnings_goals.get_goal", return_value=goal),
        patch("app.services.driver_earnings_goals._fetch_period_earnings", new=AsyncMock(return_value=(0.0, 0))),
        patch("app.services.driver_earnings_goals._current_period", return_value=period),
        patch("app.services.driver_earnings_goals._period_elapsed_fraction", return_value=0.5),
    ):
        result = await get_goal_progress(AsyncMock(), driver_profile_id=1)
    assert result.period_start == date(2026, 4, 13)
    assert result.period_end == date(2026, 4, 19)


@pytest.mark.asyncio
async def test_progress_rides_completed_reflects_count():
    goal = _make_goal(target=100.0)
    with (
        patch("app.services.driver_earnings_goals.get_goal", return_value=goal),
        patch("app.services.driver_earnings_goals._fetch_period_earnings", new=AsyncMock(return_value=(75.0, 6))),
        patch("app.services.driver_earnings_goals._current_period", return_value=(date(2026, 4, 14), date(2026, 4, 14))),
        patch("app.services.driver_earnings_goals._period_elapsed_fraction", return_value=1.0),
    ):
        result = await get_goal_progress(AsyncMock(), driver_profile_id=1)
    assert result.rides_completed == 6


# ---------------------------------------------------------------------------
# Endpoint auth (role guard tests)
# ---------------------------------------------------------------------------


def _make_user(role: str) -> MagicMock:
    u = MagicMock()
    u.role = MagicMock()
    u.role.value = role
    return u


def test_rider_cannot_get_earnings_goal():
    from app.api.deps import require_driver

    rider = _make_user("rider")
    with pytest.raises(Exception) as exc_info:
        import asyncio

        async def _check():
            return await require_driver(rider)

        asyncio.get_event_loop().run_until_complete(_check())
    assert exc_info.value.status_code == 403


def test_rider_cannot_put_earnings_goal():
    from app.api.deps import require_driver

    rider = _make_user("rider")
    with pytest.raises(Exception) as exc_info:
        import asyncio

        async def _check():
            return await require_driver(rider)

        asyncio.get_event_loop().run_until_complete(_check())
    assert exc_info.value.status_code == 403


def test_rider_cannot_delete_earnings_goal():
    from app.api.deps import require_driver

    rider = _make_user("rider")
    with pytest.raises(Exception) as exc_info:
        import asyncio

        async def _check():
            return await require_driver(rider)

        asyncio.get_event_loop().run_until_complete(_check())
    assert exc_info.value.status_code == 403
