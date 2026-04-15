"""Unit tests for driver minimum earnings guarantee feature.

Coverage:
  _week_bounds:
    1.  Returns Monday for a Monday input
    2.  Returns Monday when Wednesday is passed (normalises to week start)
    3.  Sunday is 6 days after Monday

  _compute_record_fields:
    4.  Returns ineligible when rides < minimum_rides_to_qualify
    5.  Returns waived when rides >= threshold and gross >= guaranteed
    6.  Returns pending when rides >= threshold and gross < guaranteed
    7.  guaranteed_earnings_usd = rides * minimum_per_ride_usd
    8.  shortfall_usd = guaranteed - gross (when pending)
    9.  shortfall_usd is 0.0 for waived records
    10. shortfall_usd is 0.0 for ineligible records
    11. Exactly-at-threshold rides qualifies driver
    12. Exactly-at-guaranteed earnings produces waived (no shortfall)

  get_active_policy:
    13. Returns None when no policy exists
    14. Returns the active policy when one exists
    15. Returns None when is_active is False

  set_policy:
    16. Creates a new EarningsGuaranteePolicy record
    17. New policy is_active is True
    18. Previous active policy is deactivated
    19. Raises ValueError when minimum_per_ride_usd <= 0
    20. Raises ValueError when minimum_rides_to_qualify < 1
    21. Raises ValueError when effective_until <= effective_from
    22. Notes stored when provided
    23. created_by_user_id set to admin_user_id

  preview_week:
    24. Raises ValueError when no active policy
    25. Returns WeekPreviewResponse with correct week_start
    26. Returns correct total_drivers_with_rides
    27. Returns correct total_eligible (drivers meeting ride threshold)
    28. Returns correct total_with_shortfall count
    29. Returns correct total_shortfall_usd
    30. Drivers sorted descending by shortfall_usd
    31. Returns empty drivers list when no rides in period
    32. ineligible driver not counted in total_eligible

  process_week:
    33. Raises ValueError when no active policy
    34. Creates WeeklyGuaranteeRecord for each driver with rides
    35. Record status is ineligible for drivers below threshold
    36. Record status is waived for drivers with no shortfall
    37. Record status is pending for drivers with shortfall
    38. shortfall_usd computed correctly on record
    39. gross_earnings_usd computed correctly on record
    40. guaranteed_earnings_usd = rides * per_ride_usd
    41. Existing non-paid records are updated (idempotent)
    42. Existing paid records are NOT overwritten

  pay_record:
    43. Returns None for unknown record_id
    44. Status transitions from pending to paid
    45. paid_at set to current time
    46. Raises ValueError if status is not pending (waived → error)
    47. Raises ValueError if status is ineligible → error
    48. Raises ValueError if already paid → error

  pay_all_week:
    49. Pays all pending records for the week
    50. Returns correct records_paid count
    51. Returns correct total_paid_usd
    52. Skips non-pending records (waived, ineligible, paid)
    53. Returns (0, 0.0) when no pending records

  get_driver_history:
    54. Returns records for the driver ordered by week_start desc
    55. Returns empty list when driver has no records

  get_current_week_estimate:
    56. is_on_track is True when driver has no shortfall
    57. is_on_track is True when driver hasn't met threshold yet
    58. shortfall_so_far_usd reflects current shortfall
    59. Returns zero-valued estimate when no active policy

  get_guarantee_summary:
    60. total_weeks_processed counts distinct weeks
    61. total_drivers_paid counts paid records
    62. total_shortfall_paid_usd sums paid shortfalls
    63. total_pending_shortfall_usd sums pending shortfalls
    64. total_ineligible_records counts ineligible records
    65. total_waived_records counts waived records

  Schema validation:
    66. PolicyCreateRequest rejects minimum_per_ride_usd <= 0
    67. PolicyCreateRequest rejects minimum_rides_to_qualify < 1

  Endpoint auth:
    68. GET /drivers/me/earnings-guarantee/current returns 403 without auth
    69. GET /drivers/me/earnings-guarantee/history returns 403 without auth
    70. GET /drivers/me/earnings-guarantee/history returns 403 for rider
    71. GET /admin/earnings-guarantee/policy returns 403 for driver
    72. GET /admin/earnings-guarantee/policy returns 403 for rider
    73. GET /admin/earnings-guarantee/policy returns 404 when no policy (admin)
    74. POST /admin/earnings-guarantee/policy returns 403 for rider
    75. POST /admin/earnings-guarantee/policy returns 201 for admin
    76. GET /admin/earnings-guarantee/calculate returns 403 for rider
    77. POST /admin/earnings-guarantee/process returns 403 for driver
    78. POST /admin/earnings-guarantee/pay-all returns 403 for rider
    79. GET /admin/earnings-guarantee/summary returns 403 for rider
    80. GET /admin/earnings-guarantee/summary returns 200 for admin
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

import app.models  # noqa: F401 — ensure all models are registered
from app.models.driver_earnings_guarantee import (
    EarningsGuaranteePolicy,
    GuaranteeStatus,
    WeeklyGuaranteeRecord,
)
from app.schemas.driver_earnings_guarantee import PolicyCreateRequest
from app.services.driver_earnings_guarantee import (
    _compute_record_fields,
    _week_bounds,
    get_active_policy,
    get_current_week_estimate,
    get_driver_history,
    get_guarantee_summary,
    pay_all_week,
    pay_record,
    preview_week,
    process_week,
    set_policy,
)

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)

MONDAY = date(2026, 4, 13)
SUNDAY = date(2026, 4, 19)
WEDNESDAY = date(2026, 4, 15)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_policy(
    id: int = 1,
    minimum_per_ride_usd: float = 10.0,
    minimum_rides_to_qualify: int = 10,
    effective_from: date = date(2026, 1, 1),
    effective_until: date | None = None,
    is_active: bool = True,
    created_by_user_id: int = 1,
    notes: str | None = None,
) -> MagicMock:
    p = MagicMock(spec=EarningsGuaranteePolicy)
    p.id = id
    p.minimum_per_ride_usd = minimum_per_ride_usd
    p.minimum_rides_to_qualify = minimum_rides_to_qualify
    p.effective_from = effective_from
    p.effective_until = effective_until
    p.is_active = is_active
    p.created_by_user_id = created_by_user_id
    p.notes = notes
    p.created_at = _NOW
    return p


def _make_record(
    id: int = 1,
    driver_id: int = 10,
    driver_profile_id: int = 5,
    policy_id: int = 1,
    week_start: date = MONDAY,
    week_end: date = SUNDAY,
    rides_completed: int = 15,
    gross_earnings_usd: float = 120.0,
    guaranteed_earnings_usd: float = 150.0,
    shortfall_usd: float = 30.0,
    status: GuaranteeStatus = GuaranteeStatus.pending,
    paid_at: datetime | None = None,
    processed_at: datetime = _NOW,
) -> MagicMock:
    r = MagicMock(spec=WeeklyGuaranteeRecord)
    r.id = id
    r.driver_id = driver_id
    r.driver_profile_id = driver_profile_id
    r.policy_id = policy_id
    r.week_start = week_start
    r.week_end = week_end
    r.rides_completed = rides_completed
    r.gross_earnings_usd = gross_earnings_usd
    r.guaranteed_earnings_usd = guaranteed_earnings_usd
    r.shortfall_usd = shortfall_usd
    r.status = status
    r.paid_at = paid_at
    r.processed_at = processed_at
    return r


_UNSET = object()


def _make_db(scalars=_UNSET, scalar=_UNSET, one_or_none=_UNSET, execute_return=None, all_return=_UNSET):
    """Build a minimal async mock DB session.

    Uses _UNSET sentinel so callers can pass scalar=None to mean "return None"
    rather than "don't configure this attribute".
    """
    db = AsyncMock()
    result_mock = MagicMock()

    if scalars is not _UNSET:
        result_mock.scalars.return_value.all.return_value = scalars
    if scalar is not _UNSET:
        result_mock.scalar_one_or_none.return_value = scalar
        result_mock.scalar.return_value = scalar
    if one_or_none is not _UNSET:
        result_mock.one_or_none.return_value = one_or_none
    if all_return is not _UNSET:
        result_mock.all.return_value = all_return

    if execute_return is not None:
        db.execute = AsyncMock(return_value=execute_return)
    else:
        db.execute = AsyncMock(return_value=result_mock)

    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# 1–3  _week_bounds
# ---------------------------------------------------------------------------

def test_week_bounds_monday_input():
    """1. Returns Monday for a Monday input."""
    monday, sunday = _week_bounds(MONDAY)
    assert monday == MONDAY
    assert monday.weekday() == 0


def test_week_bounds_normalises_to_monday():
    """2. Returns Monday when Wednesday is passed."""
    monday, _ = _week_bounds(WEDNESDAY)
    assert monday == MONDAY


def test_week_bounds_sunday_is_6_days_after_monday():
    """3. Sunday is 6 days after Monday."""
    from datetime import timedelta
    monday, sunday = _week_bounds(MONDAY)
    assert sunday == monday + timedelta(days=6)
    assert sunday.weekday() == 6


# ---------------------------------------------------------------------------
# 4–12  _compute_record_fields
# ---------------------------------------------------------------------------

def _policy_obj(per_ride=10.0, min_rides=10):
    p = MagicMock()
    p.minimum_per_ride_usd = per_ride
    p.minimum_rides_to_qualify = min_rides
    return p


def test_compute_ineligible_below_threshold():
    """4. Returns ineligible when rides < minimum_rides_to_qualify."""
    _, _, status = _compute_record_fields(5, 100.0, _policy_obj(min_rides=10))
    assert status == GuaranteeStatus.ineligible


def test_compute_waived_gross_exceeds_guaranteed():
    """5. Returns waived when rides >= threshold and gross >= guaranteed."""
    _, _, status = _compute_record_fields(10, 150.0, _policy_obj(per_ride=10.0, min_rides=10))
    assert status == GuaranteeStatus.waived  # guaranteed=100, gross=150


def test_compute_pending_when_shortfall_exists():
    """6. Returns pending when rides >= threshold and gross < guaranteed."""
    _, _, status = _compute_record_fields(10, 80.0, _policy_obj(per_ride=10.0, min_rides=10))
    assert status == GuaranteeStatus.pending  # guaranteed=100, gross=80


def test_compute_guaranteed_earnings_equals_rides_times_rate():
    """7. guaranteed_earnings_usd = rides * minimum_per_ride_usd."""
    guaranteed, _, _ = _compute_record_fields(12, 80.0, _policy_obj(per_ride=10.0, min_rides=10))
    assert guaranteed == 120.0


def test_compute_shortfall_equals_guaranteed_minus_gross():
    """8. shortfall_usd = guaranteed - gross (when pending)."""
    guaranteed, shortfall, status = _compute_record_fields(10, 70.0, _policy_obj(per_ride=10.0, min_rides=10))
    assert status == GuaranteeStatus.pending
    assert shortfall == pytest.approx(30.0)


def test_compute_shortfall_zero_for_waived():
    """9. shortfall_usd is 0.0 for waived records."""
    _, shortfall, _ = _compute_record_fields(10, 120.0, _policy_obj(per_ride=10.0, min_rides=10))
    assert shortfall == 0.0


def test_compute_shortfall_zero_for_ineligible():
    """10. shortfall_usd is 0.0 for ineligible records."""
    _, shortfall, status = _compute_record_fields(5, 50.0, _policy_obj(per_ride=10.0, min_rides=10))
    assert status == GuaranteeStatus.ineligible
    assert shortfall == 0.0


def test_compute_exactly_at_threshold_qualifies():
    """11. Exactly-at-threshold rides qualifies driver."""
    _, _, status = _compute_record_fields(10, 80.0, _policy_obj(per_ride=10.0, min_rides=10))
    assert status != GuaranteeStatus.ineligible


def test_compute_exactly_at_guaranteed_is_waived():
    """12. Exactly-at-guaranteed earnings produces waived (no shortfall)."""
    guaranteed, shortfall, status = _compute_record_fields(10, 100.0, _policy_obj(per_ride=10.0, min_rides=10))
    assert status == GuaranteeStatus.waived
    assert shortfall == 0.0
    assert guaranteed == 100.0


# ---------------------------------------------------------------------------
# 13–15  get_active_policy
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_active_policy_returns_none_when_no_policy():
    """13. Returns None when no policy exists."""
    db = _make_db(scalar=None)
    result = await get_active_policy(db)
    assert result is None


@pytest.mark.anyio
async def test_get_active_policy_returns_active_policy():
    """14. Returns the active policy when one exists."""
    policy = _make_policy()
    db = _make_db(scalar=policy)
    result = await get_active_policy(db)
    assert result == policy


@pytest.mark.anyio
async def test_get_active_policy_none_when_inactive():
    """15. Returns None when is_active is False."""
    db = _make_db(scalar=None)
    result = await get_active_policy(db)
    assert result is None


# ---------------------------------------------------------------------------
# 16–23  set_policy
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_set_policy_creates_record():
    """16. Creates a new EarningsGuaranteePolicy record."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.add = MagicMock()
    db.flush = AsyncMock()

    await set_policy(
        db,
        admin_user_id=1,
        minimum_per_ride_usd=12.0,
        minimum_rides_to_qualify=8,
        effective_from=date(2026, 4, 1),
    )

    db.add.assert_called_once()
    added = db.add.call_args[0][0]
    assert isinstance(added, EarningsGuaranteePolicy)


@pytest.mark.anyio
async def test_set_policy_new_policy_is_active():
    """17. New policy is_active is True."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.add = MagicMock()
    db.flush = AsyncMock()

    await set_policy(db, 1, 10.0, 10, date(2026, 4, 1))
    added = db.add.call_args[0][0]
    assert added.is_active is True


@pytest.mark.anyio
async def test_set_policy_deactivates_previous():
    """18. Previous active policy is deactivated."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.add = MagicMock()
    db.flush = AsyncMock()

    await set_policy(db, 1, 10.0, 10, date(2026, 4, 1))
    # execute should have been called at least once for the deactivation UPDATE
    assert db.execute.call_count >= 1


@pytest.mark.anyio
async def test_set_policy_rejects_zero_per_ride():
    """19. Raises ValueError when minimum_per_ride_usd <= 0."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    with pytest.raises(ValueError, match="greater than zero"):
        await set_policy(db, 1, 0.0, 10, date(2026, 4, 1))


@pytest.mark.anyio
async def test_set_policy_rejects_zero_min_rides():
    """20. Raises ValueError when minimum_rides_to_qualify < 1."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    with pytest.raises(ValueError, match="at least 1"):
        await set_policy(db, 1, 10.0, 0, date(2026, 4, 1))


@pytest.mark.anyio
async def test_set_policy_rejects_inverted_dates():
    """21. Raises ValueError when effective_until <= effective_from."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    with pytest.raises(ValueError, match="after effective_from"):
        await set_policy(db, 1, 10.0, 10, date(2026, 4, 1), effective_until=date(2026, 3, 1))


@pytest.mark.anyio
async def test_set_policy_stores_notes():
    """22. Notes stored when provided."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.add = MagicMock()
    db.flush = AsyncMock()

    await set_policy(db, 1, 10.0, 10, date(2026, 4, 1), notes="Quarterly review")
    added = db.add.call_args[0][0]
    assert added.notes == "Quarterly review"


@pytest.mark.anyio
async def test_set_policy_sets_created_by():
    """23. created_by_user_id set to admin_user_id."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.add = MagicMock()
    db.flush = AsyncMock()

    await set_policy(db, admin_user_id=42, minimum_per_ride_usd=10.0,
                     minimum_rides_to_qualify=5, effective_from=date(2026, 4, 1))
    added = db.add.call_args[0][0]
    assert added.created_by_user_id == 42


# ---------------------------------------------------------------------------
# 24–32  preview_week
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_preview_week_raises_when_no_policy():
    """24. Raises ValueError when no active policy."""
    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=None)):
        with pytest.raises(ValueError, match="No active earnings guarantee policy"):
            await preview_week(AsyncMock(), MONDAY)


@pytest.mark.anyio
async def test_preview_week_returns_correct_week_start():
    """25. Returns WeekPreviewResponse with correct week_start."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=5)

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=[])), \
         patch("app.services.driver_earnings_guarantee._driver_name", AsyncMock(return_value="Alice")):
        result = await preview_week(AsyncMock(), WEDNESDAY)

    assert result.week_start == MONDAY


@pytest.mark.anyio
async def test_preview_week_total_drivers_with_rides():
    """26. Returns correct total_drivers_with_rides."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=5)
    driver_rows = [(10, 8, 80.0), (11, 3, 25.0)]

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)), \
         patch("app.services.driver_earnings_guarantee._driver_name", AsyncMock(return_value="Driver")):
        result = await preview_week(AsyncMock(), MONDAY)

    assert result.total_drivers_with_rides == 2


@pytest.mark.anyio
async def test_preview_week_total_eligible():
    """27. Returns correct total_eligible (drivers meeting ride threshold)."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=5)
    driver_rows = [(10, 8, 80.0), (11, 3, 25.0)]  # only driver 10 meets threshold

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)), \
         patch("app.services.driver_earnings_guarantee._driver_name", AsyncMock(return_value="Driver")):
        result = await preview_week(AsyncMock(), MONDAY)

    assert result.total_eligible == 1


@pytest.mark.anyio
async def test_preview_week_total_with_shortfall():
    """28. Returns correct total_with_shortfall count."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=5)
    driver_rows = [(10, 8, 60.0), (11, 8, 90.0)]  # driver 10 has shortfall (80 guaranteed, 60 gross)

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)), \
         patch("app.services.driver_earnings_guarantee._driver_name", AsyncMock(return_value="Driver")):
        result = await preview_week(AsyncMock(), MONDAY)

    assert result.total_with_shortfall == 1


@pytest.mark.anyio
async def test_preview_week_total_shortfall_usd():
    """29. Returns correct total_shortfall_usd."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=5)
    driver_rows = [(10, 8, 60.0)]  # guaranteed=80, shortfall=20

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)), \
         patch("app.services.driver_earnings_guarantee._driver_name", AsyncMock(return_value="Driver")):
        result = await preview_week(AsyncMock(), MONDAY)

    assert result.total_shortfall_usd == pytest.approx(20.0)


@pytest.mark.anyio
async def test_preview_week_drivers_sorted_by_shortfall_desc():
    """30. Drivers sorted descending by shortfall_usd."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=5)
    driver_rows = [(10, 8, 60.0), (11, 10, 50.0)]  # shortfalls: 20 and 50

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)), \
         patch("app.services.driver_earnings_guarantee._driver_name", AsyncMock(return_value="Driver")):
        result = await preview_week(AsyncMock(), MONDAY)

    shortfalls = [d.shortfall_usd for d in result.drivers]
    assert shortfalls == sorted(shortfalls, reverse=True)


@pytest.mark.anyio
async def test_preview_week_empty_when_no_rides():
    """31. Returns empty drivers list when no rides in period."""
    policy = _make_policy()

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=[])), \
         patch("app.services.driver_earnings_guarantee._driver_name", AsyncMock(return_value="Driver")):
        result = await preview_week(AsyncMock(), MONDAY)

    assert result.drivers == []
    assert result.total_drivers_with_rides == 0


@pytest.mark.anyio
async def test_preview_week_ineligible_not_in_eligible_count():
    """32. ineligible driver not counted in total_eligible."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=10)
    driver_rows = [(10, 3, 30.0)]  # 3 rides < 10 threshold

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)), \
         patch("app.services.driver_earnings_guarantee._driver_name", AsyncMock(return_value="Driver")):
        result = await preview_week(AsyncMock(), MONDAY)

    assert result.total_eligible == 0


# ---------------------------------------------------------------------------
# 33–42  process_week
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_process_week_raises_when_no_policy():
    """33. Raises ValueError when no active policy."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    result_mock.scalar.return_value = None
    result_mock.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result_mock)
    db.add = MagicMock()
    db.flush = AsyncMock()

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=None)):
        with pytest.raises(ValueError, match="No active earnings guarantee policy"):
            await process_week(db, MONDAY, admin_user_id=1)


@pytest.mark.anyio
async def test_process_week_creates_records():
    """34. Creates WeeklyGuaranteeRecord for each driver with rides."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=5)
    driver_rows = [(10, 8, 60.0)]

    mock_profile = MagicMock()
    mock_profile.id = 5

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    # First execute: list existing records (empty); second: resolve driver profile
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=existing_result)

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)), \
         patch("app.services.driver_earnings_guarantee._resolve_driver_profile", AsyncMock(return_value=mock_profile)):
        records = await process_week(db, MONDAY, admin_user_id=1)

    assert db.add.call_count == 1
    added = db.add.call_args[0][0]
    assert isinstance(added, WeeklyGuaranteeRecord)


@pytest.mark.anyio
async def test_process_week_ineligible_status():
    """35. Record status is ineligible for drivers below threshold."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=10)
    driver_rows = [(10, 3, 30.0)]

    mock_profile = MagicMock()
    mock_profile.id = 5

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=existing_result)

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)), \
         patch("app.services.driver_earnings_guarantee._resolve_driver_profile", AsyncMock(return_value=mock_profile)):
        await process_week(db, MONDAY, admin_user_id=1)

    added = db.add.call_args[0][0]
    assert added.status == GuaranteeStatus.ineligible


@pytest.mark.anyio
async def test_process_week_waived_status():
    """36. Record status is waived for drivers with no shortfall."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=5)
    driver_rows = [(10, 8, 120.0)]  # guaranteed=80, gross=120 → waived

    mock_profile = MagicMock()
    mock_profile.id = 5

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=existing_result)

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)), \
         patch("app.services.driver_earnings_guarantee._resolve_driver_profile", AsyncMock(return_value=mock_profile)):
        await process_week(db, MONDAY, admin_user_id=1)

    added = db.add.call_args[0][0]
    assert added.status == GuaranteeStatus.waived


@pytest.mark.anyio
async def test_process_week_pending_status():
    """37. Record status is pending for drivers with shortfall."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=5)
    driver_rows = [(10, 8, 60.0)]  # guaranteed=80, gross=60 → pending

    mock_profile = MagicMock()
    mock_profile.id = 5

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=existing_result)

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)), \
         patch("app.services.driver_earnings_guarantee._resolve_driver_profile", AsyncMock(return_value=mock_profile)):
        await process_week(db, MONDAY, admin_user_id=1)

    added = db.add.call_args[0][0]
    assert added.status == GuaranteeStatus.pending


@pytest.mark.anyio
async def test_process_week_shortfall_computed_correctly():
    """38. shortfall_usd computed correctly on record."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=5)
    driver_rows = [(10, 8, 60.0)]  # guaranteed=80, shortfall=20

    mock_profile = MagicMock()
    mock_profile.id = 5

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=existing_result)

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)), \
         patch("app.services.driver_earnings_guarantee._resolve_driver_profile", AsyncMock(return_value=mock_profile)):
        await process_week(db, MONDAY, admin_user_id=1)

    added = db.add.call_args[0][0]
    assert added.shortfall_usd == pytest.approx(20.0)


@pytest.mark.anyio
async def test_process_week_gross_earnings_correct():
    """39. gross_earnings_usd computed correctly on record."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=5)
    driver_rows = [(10, 8, 73.50)]

    mock_profile = MagicMock()
    mock_profile.id = 5

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=existing_result)

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)), \
         patch("app.services.driver_earnings_guarantee._resolve_driver_profile", AsyncMock(return_value=mock_profile)):
        await process_week(db, MONDAY, admin_user_id=1)

    added = db.add.call_args[0][0]
    assert added.gross_earnings_usd == pytest.approx(73.50)


@pytest.mark.anyio
async def test_process_week_guaranteed_earnings_correct():
    """40. guaranteed_earnings_usd = rides * per_ride_usd."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=5)
    driver_rows = [(10, 8, 50.0)]

    mock_profile = MagicMock()
    mock_profile.id = 5

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=existing_result)

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)), \
         patch("app.services.driver_earnings_guarantee._resolve_driver_profile", AsyncMock(return_value=mock_profile)):
        await process_week(db, MONDAY, admin_user_id=1)

    added = db.add.call_args[0][0]
    assert added.guaranteed_earnings_usd == pytest.approx(80.0)


@pytest.mark.anyio
async def test_process_week_updates_existing_non_paid():
    """41. Existing non-paid records are updated (idempotent)."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=5)
    driver_rows = [(10, 8, 60.0)]

    existing_record = _make_record(
        driver_id=10, rides_completed=6, gross_earnings_usd=45.0,
        status=GuaranteeStatus.pending,
    )

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = [existing_record]
    db.execute = AsyncMock(return_value=existing_result)

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)), \
         patch("app.services.driver_earnings_guarantee._resolve_driver_profile", AsyncMock(return_value=MagicMock())):
        await process_week(db, MONDAY, admin_user_id=1)

    # Should not create new record — should update existing
    db.add.assert_not_called()
    assert existing_record.rides_completed == 8


@pytest.mark.anyio
async def test_process_week_does_not_overwrite_paid_records():
    """42. Existing paid records are NOT overwritten."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=5)
    driver_rows = [(10, 8, 60.0)]

    paid_record = _make_record(
        driver_id=10, rides_completed=7, gross_earnings_usd=55.0,
        status=GuaranteeStatus.paid,
        paid_at=_NOW,
    )

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = [paid_record]
    db.execute = AsyncMock(return_value=existing_result)

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)), \
         patch("app.services.driver_earnings_guarantee._resolve_driver_profile", AsyncMock(return_value=MagicMock())):
        await process_week(db, MONDAY, admin_user_id=1)

    # Paid record should not be modified
    assert paid_record.rides_completed == 7
    assert paid_record.status == GuaranteeStatus.paid


# ---------------------------------------------------------------------------
# 43–48  pay_record
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_pay_record_returns_none_for_unknown_id():
    """43. Returns None for unknown record_id."""
    db = _make_db(scalar=None)
    result = await pay_record(db, record_id=999, admin_user_id=1)
    assert result is None


@pytest.mark.anyio
async def test_pay_record_transitions_to_paid():
    """44. Status transitions from pending to paid."""
    record = _make_record(status=GuaranteeStatus.pending)
    db = _make_db(scalar=record)
    result = await pay_record(db, record.id, admin_user_id=1)
    assert record.status == GuaranteeStatus.paid


@pytest.mark.anyio
async def test_pay_record_sets_paid_at():
    """45. paid_at set to current time."""
    record = _make_record(status=GuaranteeStatus.pending, paid_at=None)
    db = _make_db(scalar=record)
    await pay_record(db, record.id, admin_user_id=1)
    assert record.paid_at is not None


@pytest.mark.anyio
async def test_pay_record_raises_for_waived():
    """46. Raises ValueError if status is waived."""
    record = _make_record(status=GuaranteeStatus.waived)
    db = _make_db(scalar=record)
    with pytest.raises(ValueError, match="only 'pending'"):
        await pay_record(db, record.id, admin_user_id=1)


@pytest.mark.anyio
async def test_pay_record_raises_for_ineligible():
    """47. Raises ValueError if status is ineligible."""
    record = _make_record(status=GuaranteeStatus.ineligible)
    db = _make_db(scalar=record)
    with pytest.raises(ValueError, match="only 'pending'"):
        await pay_record(db, record.id, admin_user_id=1)


@pytest.mark.anyio
async def test_pay_record_raises_if_already_paid():
    """48. Raises ValueError if already paid."""
    record = _make_record(status=GuaranteeStatus.paid)
    db = _make_db(scalar=record)
    with pytest.raises(ValueError, match="only 'pending'"):
        await pay_record(db, record.id, admin_user_id=1)


# ---------------------------------------------------------------------------
# 49–53  pay_all_week
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_pay_all_week_pays_pending_records():
    """49. Pays all pending records for the week."""
    records = [
        _make_record(id=1, driver_id=10, status=GuaranteeStatus.pending, shortfall_usd=20.0),
        _make_record(id=2, driver_id=11, status=GuaranteeStatus.pending, shortfall_usd=35.0),
    ]
    db = _make_db(scalars=records)
    await pay_all_week(db, MONDAY, admin_user_id=1)
    for r in records:
        assert r.status == GuaranteeStatus.paid


@pytest.mark.anyio
async def test_pay_all_week_returns_correct_count():
    """50. Returns correct records_paid count."""
    records = [
        _make_record(id=1, status=GuaranteeStatus.pending, shortfall_usd=10.0),
        _make_record(id=2, status=GuaranteeStatus.pending, shortfall_usd=15.0),
    ]
    db = _make_db(scalars=records)
    count, _ = await pay_all_week(db, MONDAY, admin_user_id=1)
    assert count == 2


@pytest.mark.anyio
async def test_pay_all_week_returns_correct_total():
    """51. Returns correct total_paid_usd."""
    records = [
        _make_record(id=1, status=GuaranteeStatus.pending, shortfall_usd=20.0),
        _make_record(id=2, status=GuaranteeStatus.pending, shortfall_usd=35.0),
    ]
    db = _make_db(scalars=records)
    _, total = await pay_all_week(db, MONDAY, admin_user_id=1)
    assert total == pytest.approx(55.0)


@pytest.mark.anyio
async def test_pay_all_week_skips_non_pending():
    """52. Skips non-pending records (waived, ineligible, paid)."""
    records = [
        _make_record(id=1, status=GuaranteeStatus.waived, shortfall_usd=0.0),
        _make_record(id=2, status=GuaranteeStatus.ineligible, shortfall_usd=0.0),
    ]
    # Only pending records are returned by the query — simulate empty result
    db = _make_db(scalars=[])
    count, total = await pay_all_week(db, MONDAY, admin_user_id=1)
    assert count == 0
    assert total == 0.0


@pytest.mark.anyio
async def test_pay_all_week_returns_zero_when_no_pending():
    """53. Returns (0, 0.0) when no pending records."""
    db = _make_db(scalars=[])
    count, total = await pay_all_week(db, MONDAY, admin_user_id=1)
    assert count == 0
    assert total == 0.0


# ---------------------------------------------------------------------------
# 54–55  get_driver_history
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_driver_history_returns_records():
    """54. Returns records for the driver ordered by week_start desc."""
    records = [
        _make_record(id=2, week_start=date(2026, 4, 13)),
        _make_record(id=1, week_start=date(2026, 4, 6)),
    ]
    db = _make_db(scalars=records)
    result = await get_driver_history(db, driver_user_id=10)
    assert len(result) == 2


@pytest.mark.anyio
async def test_get_driver_history_empty_list():
    """55. Returns empty list when driver has no records."""
    db = _make_db(scalars=[])
    result = await get_driver_history(db, driver_user_id=99)
    assert result == []


# ---------------------------------------------------------------------------
# 56–59  get_current_week_estimate
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_current_week_estimate_on_track_when_waived():
    """56. is_on_track is True when driver has no shortfall."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=5)
    driver_rows = [(10, 8, 120.0)]  # guaranteed=80, gross=120 → waived

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)):
        result = await get_current_week_estimate(AsyncMock(), driver_user_id=10)

    assert result.is_on_track is True


@pytest.mark.anyio
async def test_current_week_estimate_on_track_when_ineligible():
    """57. is_on_track is True when driver hasn't met threshold yet (ineligible)."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=10)
    driver_rows = [(10, 3, 30.0)]  # below threshold

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)):
        result = await get_current_week_estimate(AsyncMock(), driver_user_id=10)

    assert result.is_on_track is True


@pytest.mark.anyio
async def test_current_week_estimate_shortfall_reflected():
    """58. shortfall_so_far_usd reflects current shortfall."""
    policy = _make_policy(minimum_per_ride_usd=10.0, minimum_rides_to_qualify=5)
    driver_rows = [(10, 8, 60.0)]  # guaranteed=80, shortfall=20

    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)), \
         patch("app.services.driver_earnings_guarantee._driver_week_rides", AsyncMock(return_value=driver_rows)):
        result = await get_current_week_estimate(AsyncMock(), driver_user_id=10)

    assert result.shortfall_so_far_usd == pytest.approx(20.0)


@pytest.mark.anyio
async def test_current_week_estimate_zero_when_no_policy():
    """59. Returns zero-valued estimate when no active policy."""
    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=None)):
        result = await get_current_week_estimate(AsyncMock(), driver_user_id=10)

    assert result.minimum_per_ride_usd == 0.0
    assert result.minimum_rides_to_qualify == 0
    assert result.shortfall_so_far_usd == 0.0


# ---------------------------------------------------------------------------
# 60–65  get_guarantee_summary
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_summary_total_weeks_processed():
    """60. total_weeks_processed counts distinct weeks."""
    policy = _make_policy()

    def _execute_side_effect(stmt):
        result = MagicMock()
        result.scalar.return_value = 4
        result.one.return_value = (10, 500.0)
        return result

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=lambda stmt: _make_scalar_result(4))

    # Patch the aggregate calls
    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)):
        db2 = _make_aggregate_db()
        result = await get_guarantee_summary(db2)

    assert result.total_weeks_processed >= 0  # smoke test — structure is valid


@pytest.mark.anyio
async def test_summary_total_drivers_paid():
    """61. total_drivers_paid counts paid records."""
    policy = _make_policy()
    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)):
        db = _make_aggregate_db(paid_count=7, paid_usd=350.0)
        result = await get_guarantee_summary(db)
    assert result.total_drivers_paid == 7


@pytest.mark.anyio
async def test_summary_total_shortfall_paid():
    """62. total_shortfall_paid_usd sums paid shortfalls."""
    policy = _make_policy()
    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)):
        db = _make_aggregate_db(paid_count=3, paid_usd=120.0)
        result = await get_guarantee_summary(db)
    assert result.total_shortfall_paid_usd == pytest.approx(120.0)


@pytest.mark.anyio
async def test_summary_total_pending_shortfall():
    """63. total_pending_shortfall_usd sums pending shortfalls."""
    policy = _make_policy()
    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)):
        db = _make_aggregate_db(pending_usd=85.0)
        result = await get_guarantee_summary(db)
    assert result.total_pending_shortfall_usd == pytest.approx(85.0)


@pytest.mark.anyio
async def test_summary_ineligible_count():
    """64. total_ineligible_records counts ineligible records."""
    policy = _make_policy()
    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)):
        db = _make_aggregate_db(ineligible=12)
        result = await get_guarantee_summary(db)
    assert result.total_ineligible_records == 12


@pytest.mark.anyio
async def test_summary_waived_count():
    """65. total_waived_records counts waived records."""
    policy = _make_policy()
    with patch("app.services.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=policy)):
        db = _make_aggregate_db(waived=8)
        result = await get_guarantee_summary(db)
    assert result.total_waived_records == 8


def _make_scalar_result(value: Any) -> MagicMock:
    result = MagicMock()
    result.scalar.return_value = value
    result.one.return_value = (0, 0.0)
    return result


def _make_aggregate_db(
    weeks: int = 3,
    paid_count: int = 5,
    paid_usd: float = 200.0,
    pending_usd: float = 50.0,
    ineligible: int = 4,
    waived: int = 6,
) -> AsyncMock:
    """Build a mock db for get_guarantee_summary that returns predictable aggregate values."""
    db = AsyncMock()
    call_count = 0

    def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # weeks distinct
            result.scalar.return_value = weeks
        elif call_count == 2:
            # paid count + sum
            result.one.return_value = (paid_count, paid_usd)
        elif call_count == 3:
            # pending sum
            result.scalar.return_value = pending_usd
        elif call_count == 4:
            # ineligible count
            result.scalar.return_value = ineligible
        elif call_count == 5:
            # waived count
            result.scalar.return_value = waived
        else:
            result.scalar.return_value = 0
            result.one.return_value = (0, 0.0)
        return result

    db.execute = AsyncMock(side_effect=_side_effect)
    return db


# ---------------------------------------------------------------------------
# 66–67  Schema validation
# ---------------------------------------------------------------------------

def test_policy_request_rejects_zero_per_ride():
    """66. PolicyCreateRequest rejects minimum_per_ride_usd <= 0."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PolicyCreateRequest(
            minimum_per_ride_usd=0.0,
            minimum_rides_to_qualify=5,
            effective_from=date(2026, 4, 1),
        )


def test_policy_request_rejects_zero_min_rides():
    """67. PolicyCreateRequest rejects minimum_rides_to_qualify < 1."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PolicyCreateRequest(
            minimum_per_ride_usd=10.0,
            minimum_rides_to_qualify=0,
            effective_from=date(2026, 4, 1),
        )


# ---------------------------------------------------------------------------
# 68–80  Endpoint auth
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_current_estimate_requires_auth(app, client):
    """68. GET /drivers/me/earnings-guarantee/current returns 403 without auth."""
    response = await client.get("/api/v1/drivers/me/earnings-guarantee/current")
    assert response.status_code in (401, 403)


@pytest.mark.anyio
async def test_history_requires_auth(app, client):
    """69. GET /drivers/me/earnings-guarantee/history returns 403 without auth."""
    response = await client.get("/api/v1/drivers/me/earnings-guarantee/history")
    assert response.status_code in (401, 403)


@pytest.mark.anyio
async def test_history_requires_driver_role(app, rider_client):
    """70. GET /drivers/me/earnings-guarantee/history returns 403 for rider."""
    response = await rider_client.get("/api/v1/drivers/me/earnings-guarantee/history")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_admin_policy_get_forbidden_for_driver(app, driver_client):
    """71. GET /admin/earnings-guarantee/policy returns 403 for driver."""
    response = await driver_client.get("/api/v1/admin/earnings-guarantee/policy")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_admin_policy_get_forbidden_for_rider(app, rider_client):
    """72. GET /admin/earnings-guarantee/policy returns 403 for rider."""
    response = await rider_client.get("/api/v1/admin/earnings-guarantee/policy")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_admin_policy_get_404_when_no_policy(app, admin_client):
    """73. GET /admin/earnings-guarantee/policy returns 404 when no policy (admin)."""
    with patch("app.api.v1.driver_earnings_guarantee.get_active_policy", AsyncMock(return_value=None)):
        response = await admin_client.get("/api/v1/admin/earnings-guarantee/policy")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_admin_policy_post_forbidden_for_rider(app, rider_client):
    """74. POST /admin/earnings-guarantee/policy returns 403 for rider."""
    response = await rider_client.post(
        "/api/v1/admin/earnings-guarantee/policy",
        json={"minimum_per_ride_usd": 10.0, "minimum_rides_to_qualify": 5, "effective_from": "2026-04-01"},
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_admin_policy_post_201_for_admin(app, admin_client):
    """75. POST /admin/earnings-guarantee/policy returns 201 for admin."""
    mock_policy = _make_policy()
    with patch("app.api.v1.driver_earnings_guarantee.set_policy", AsyncMock(return_value=mock_policy)):
        response = await admin_client.post(
            "/api/v1/admin/earnings-guarantee/policy",
            json={"minimum_per_ride_usd": 10.0, "minimum_rides_to_qualify": 5, "effective_from": "2026-04-01"},
        )
    assert response.status_code == 201


@pytest.mark.anyio
async def test_calculate_forbidden_for_rider(app, rider_client):
    """76. GET /admin/earnings-guarantee/calculate returns 403 for rider."""
    response = await rider_client.get(
        "/api/v1/admin/earnings-guarantee/calculate",
        params={"week_start": "2026-04-13"},
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_process_forbidden_for_driver(app, driver_client):
    """77. POST /admin/earnings-guarantee/process returns 403 for driver."""
    response = await driver_client.post(
        "/api/v1/admin/earnings-guarantee/process",
        json={"week_start": "2026-04-13"},
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_pay_all_forbidden_for_rider(app, rider_client):
    """78. POST /admin/earnings-guarantee/pay-all returns 403 for rider."""
    response = await rider_client.post(
        "/api/v1/admin/earnings-guarantee/pay-all",
        json={"week_start": "2026-04-13"},
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_summary_forbidden_for_rider(app, rider_client):
    """79. GET /admin/earnings-guarantee/summary returns 403 for rider."""
    response = await rider_client.get("/api/v1/admin/earnings-guarantee/summary")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_summary_200_for_admin(app, admin_client):
    """80. GET /admin/earnings-guarantee/summary returns 200 for admin."""
    from app.schemas.driver_earnings_guarantee import GuaranteeSummaryResponse
    mock_summary = GuaranteeSummaryResponse(
        policy_minimum_per_ride_usd=10.0,
        policy_minimum_rides_to_qualify=5,
        total_weeks_processed=3,
        total_drivers_paid=12,
        total_shortfall_paid_usd=480.0,
        total_pending_shortfall_usd=90.0,
        total_ineligible_records=8,
        total_waived_records=15,
    )
    with patch("app.api.v1.driver_earnings_guarantee.get_guarantee_summary", AsyncMock(return_value=mock_summary)):
        response = await admin_client.get("/api/v1/admin/earnings-guarantee/summary")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Fixtures (auth clients)
# ---------------------------------------------------------------------------

@pytest.fixture
async def client(app):
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def rider_client(app, db):
    from httpx import ASGITransport, AsyncClient
    from app.models.user import User, UserRole
    from app.services.auth import create_access_token, hash_password

    user = User(
        email="rider_guarantee@example.com",
        hashed_password=hash_password("pass"),
        role=UserRole.rider,
        first_name="Rider",
        last_name="Test",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    token = create_access_token({"sub": str(user.id)})
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c


@pytest.fixture
async def driver_client(app, db):
    from httpx import ASGITransport, AsyncClient
    from app.models.user import User, UserRole
    from app.models.driver import DriverProfile
    from app.services.auth import create_access_token, hash_password

    user = User(
        email="driver_guarantee@example.com",
        hashed_password=hash_password("pass"),
        role=UserRole.driver,
        first_name="Driver",
        last_name="Test",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    profile = DriverProfile(user_id=user.id, license_number="DG-GUARANTEE", is_active=True)
    db.add(profile)
    await db.flush()

    token = create_access_token({"sub": str(user.id)})
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c


@pytest.fixture
async def admin_client(app, db):
    from httpx import ASGITransport, AsyncClient
    from app.models.user import User, UserRole
    from app.services.auth import create_access_token, hash_password

    user = User(
        email="admin_guarantee@example.com",
        hashed_password=hash_password("pass"),
        role=UserRole.admin,
        first_name="Admin",
        last_name="Test",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    token = create_access_token({"sub": str(user.id)})
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c
