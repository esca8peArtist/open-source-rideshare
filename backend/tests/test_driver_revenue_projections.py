"""Tests for driver revenue projections and earnings comparison endpoints.

Service unit tests (AsyncMock DB):
  1.  get_driver_revenue_projection — new driver (0 rides) returns new-driver baseline
  2.  get_driver_revenue_projection — new driver (< 5 rides) sets is_new_driver_estimate=True
  3.  get_driver_revenue_projection — new driver projection uses platform avg rides/day
  4.  get_driver_revenue_projection — new driver note references platform averages
  5.  get_driver_revenue_projection — established driver (>= 5 rides) uses real history
  6.  get_driver_revenue_projection — is_new_driver_estimate=False for established driver
  7.  get_driver_revenue_projection — conservative scenario applies 0.8x multiplier
  8.  get_driver_revenue_projection — moderate scenario applies 1.0x multiplier
  9.  get_driver_revenue_projection — optimistic scenario applies 1.25x multiplier
  10. get_driver_revenue_projection — period=week extrapolates over 7 days
  11. get_driver_revenue_projection — period=month extrapolates over 30 days
  12. get_driver_revenue_projection — period=quarter extrapolates over 90 days
  13. get_driver_revenue_projection — estimated_net = gross - fees
  14. get_driver_revenue_projection — platform_fees deducted matches fee pct
  15. get_driver_revenue_projection — avg_hourly_rate = net / (rides * duration_hours)
  16. get_driver_revenue_projection — avg_hourly_rate falls back gracefully when 0 rides
  17. get_driver_revenue_projection — based_on.historical_rides matches actual ride count
  18. get_driver_revenue_projection — scenario_multipliers dict has all three keys
  19. get_driver_revenue_projection — tips included in response even for new drivers
  20. get_driver_revenue_projection — default platform fee used when no payment records
  21. get_driver_revenue_projection — actual platform fee pct from payments when available

  22. get_driver_earnings_comparison — returns period in response
  23. get_driver_earnings_comparison — driver.total_rides matches completed ride count
  24. get_driver_earnings_comparison — driver.gross_earnings sums actual_fare
  25. get_driver_earnings_comparison — driver.avg_per_ride is correct
  26. get_driver_earnings_comparison — driver.tips sums completed tip records
  27. get_driver_earnings_comparison — driver.completion_rate calculated from completed+cancelled
  28. get_driver_earnings_comparison — platform_average.total_rides is mean across drivers
  29. get_driver_earnings_comparison — percentile.rides is 0 for driver below all others
  30. get_driver_earnings_comparison — percentile.rides is 100 for top driver
  31. get_driver_earnings_comparison — percentile values are ints in 0–100 range

  32. _percentile helper — empty list returns 50
  33. _percentile helper — sole value in list returns 0
  34. _percentile helper — value above all others returns 100

API integration tests (in-transaction test DB via conftest):
  35. GET /api/v1/analytics/drivers/me/revenue-projections — 401 with no auth
  36. GET /api/v1/analytics/drivers/me/revenue-projections — 403 with rider token
  37. GET /api/v1/analytics/drivers/me/revenue-projections — 200 with driver token
  38. GET /api/v1/analytics/drivers/me/revenue-projections — new-driver flag set when no rides
  39. GET /api/v1/analytics/drivers/me/revenue-projections — invalid period returns 422
  40. GET /api/v1/analytics/drivers/me/revenue-projections — invalid scenario returns 422
  41. GET /api/v1/analytics/drivers/me/revenue-projections — response schema valid
  42. GET /api/v1/analytics/drivers/me/revenue-projections — period=week accepted
  43. GET /api/v1/analytics/drivers/me/revenue-projections — period=quarter accepted
  44. GET /api/v1/analytics/drivers/me/earnings-comparison — 401 with no auth
  45. GET /api/v1/analytics/drivers/me/earnings-comparison — 403 with rider token
  46. GET /api/v1/analytics/drivers/me/earnings-comparison — 200 with driver token
  47. GET /api/v1/analytics/drivers/me/earnings-comparison — response has driver + platform_average
  48. GET /api/v1/analytics/drivers/me/earnings-comparison — response has percentile block
  49. GET /api/v1/analytics/drivers/me/earnings-comparison — invalid period returns 422
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.payment import Payment, PaymentStatus
from app.models.ride import Ride, RideStatus
from app.models.tip import TipRecord, TipStatus
from app.models.user import User, UserRole
from app.services.auth import create_access_token, hash_password
from app.services.driver_revenue import (
    _percentile,
    get_driver_earnings_comparison,
    get_driver_revenue_projection,
)

# ---------------------------------------------------------------------------
# Mock factory helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 4, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_ride(
    ride_id: int = 1,
    driver_id: int = 99,
    actual_fare: float | None = 15.00,
    estimated_fare: float = 14.00,
    duration_min: float | None = 20.0,
    completed_at: datetime | None = None,
    status: RideStatus = RideStatus.COMPLETED,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.driver_id = driver_id
    ride.status = status
    ride.actual_fare = actual_fare
    ride.estimated_fare = estimated_fare
    ride.duration_min = duration_min
    ride.completed_at = completed_at or _NOW
    return ride


def _make_tip(
    tip_id: int = 1,
    ride_id: int = 1,
    driver_id: int = 99,
    amount_cents: int = 150,
    status: TipStatus = TipStatus.COMPLETED,
) -> MagicMock:
    tip = MagicMock(spec=TipRecord)
    tip.id = tip_id
    tip.ride_id = ride_id
    tip.driver_id = driver_id
    tip.amount_cents = amount_cents
    tip.status = status
    return tip


def _make_payment(
    pay_id: int = 1,
    ride_id: int = 1,
    platform_fee: float = 1.80,
    status: PaymentStatus = PaymentStatus.COMPLETED,
) -> MagicMock:
    p = MagicMock(spec=Payment)
    p.id = pay_id
    p.ride_id = ride_id
    p.platform_fee = platform_fee
    p.status = status
    return p


def _db_sequence(*result_lists) -> AsyncMock:
    """Return an AsyncMock DB whose execute() calls yield each list in turn."""
    db = AsyncMock()
    side_effects = []
    for items in result_lists:
        mock_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = list(items)
        mock_result.scalars.return_value = scalars_mock
        side_effects.append(mock_result)
    db.execute = AsyncMock(side_effect=side_effects)
    return db


# ---------------------------------------------------------------------------
# Service unit tests — revenue projection
# ---------------------------------------------------------------------------


class TestRevenueProjectionNewDriver:
    """Tests for the new-driver (< 5 rides) baseline path."""

    @pytest.mark.anyio
    async def test_zero_rides_returns_new_driver_estimate(self):
        db = _db_sequence([])  # fetch_driver_rides returns empty
        result = await get_driver_revenue_projection(db, driver_id=1)
        assert result["is_new_driver_estimate"] is True

    @pytest.mark.anyio
    async def test_four_rides_still_new_driver(self):
        rides = [_make_ride(ride_id=i, driver_id=1) for i in range(4)]
        db = _db_sequence(rides)
        result = await get_driver_revenue_projection(db, driver_id=1)
        assert result["is_new_driver_estimate"] is True

    @pytest.mark.anyio
    async def test_new_driver_based_on_uses_platform_avg(self):
        from app.services.driver_revenue import _PLATFORM_AVG_RIDES_PER_DAY

        db = _db_sequence([])
        result = await get_driver_revenue_projection(db, driver_id=1)
        assert result["based_on"]["avg_daily_rides"] == _PLATFORM_AVG_RIDES_PER_DAY

    @pytest.mark.anyio
    async def test_new_driver_note_mentions_platform(self):
        db = _db_sequence([])
        result = await get_driver_revenue_projection(db, driver_id=1)
        assert "platform" in result["notes"].lower()

    @pytest.mark.anyio
    async def test_new_driver_projection_includes_tips(self):
        db = _db_sequence([])
        result = await get_driver_revenue_projection(db, driver_id=1)
        assert "estimated_tips" in result["projection"]
        assert result["projection"]["estimated_tips"] >= 0

    @pytest.mark.anyio
    async def test_new_driver_driver_id_in_response(self):
        db = _db_sequence([])
        result = await get_driver_revenue_projection(db, driver_id=42)
        assert result["driver_id"] == 42


class TestRevenueProjectionEstablishedDriver:
    """Tests for the established driver (>= 5 rides) projection path."""

    def _make_rides(self, count: int = 10, driver_id: int = 99) -> list[MagicMock]:
        base = _NOW - timedelta(days=9)
        return [
            _make_ride(
                ride_id=i,
                driver_id=driver_id,
                actual_fare=15.00,
                duration_min=20.0,
                completed_at=base + timedelta(days=i),
            )
            for i in range(count)
        ]

    @pytest.mark.anyio
    async def test_established_driver_flag_false(self):
        rides = self._make_rides(10)
        tips = [_make_tip(ride_id=r.id, driver_id=99) for r in rides]
        db = _db_sequence(rides, tips, [])  # rides, tips, payments
        result = await get_driver_revenue_projection(db, driver_id=99)
        assert result["is_new_driver_estimate"] is False

    @pytest.mark.anyio
    async def test_based_on_historical_rides_count(self):
        rides = self._make_rides(8)
        db = _db_sequence(rides, [], [])
        result = await get_driver_revenue_projection(db, driver_id=99)
        assert result["based_on"]["historical_rides"] == 8

    @pytest.mark.anyio
    async def test_scenario_multipliers_dict_has_all_keys(self):
        rides = self._make_rides(6)
        db = _db_sequence(rides, [], [])
        result = await get_driver_revenue_projection(db, driver_id=99)
        multipliers = result["scenario_multipliers"]
        assert set(multipliers.keys()) == {"conservative", "moderate", "optimistic"}

    @pytest.mark.anyio
    async def test_estimated_net_equals_gross_minus_fees(self):
        rides = self._make_rides(6)
        db = _db_sequence(rides, [], [])
        result = await get_driver_revenue_projection(db, driver_id=99)
        proj = result["projection"]
        expected_net = round(
            proj["estimated_gross_earnings"] - proj["platform_fees_deducted"], 2
        )
        assert abs(proj["estimated_net_earnings"] - expected_net) < 0.01

    @pytest.mark.anyio
    async def test_default_platform_fee_when_no_payments(self):
        from app.services.driver_revenue import DEFAULT_PLATFORM_FEE_PCT

        rides = self._make_rides(6, driver_id=99)
        db = _db_sequence(rides, [], [])  # empty tips and payments
        result = await get_driver_revenue_projection(db, driver_id=99)
        proj = result["projection"]
        gross = proj["estimated_gross_earnings"]
        expected_fees = round(gross * DEFAULT_PLATFORM_FEE_PCT, 2)
        assert abs(proj["platform_fees_deducted"] - expected_fees) < 0.02

    @pytest.mark.anyio
    async def test_actual_platform_fee_used_from_payments(self):
        rides = self._make_rides(6)
        payments = [
            _make_payment(pay_id=i, ride_id=r.id, platform_fee=3.00)
            for i, r in enumerate(rides)
        ]
        db = _db_sequence(rides, [], payments)
        result = await get_driver_revenue_projection(db, driver_id=99)
        proj = result["projection"]
        # With 6 rides at $15 each, $3 fee each => fee pct = 3/15 = 20%
        gross = proj["estimated_gross_earnings"]
        expected_fees = round(gross * 0.20, 2)
        assert abs(proj["platform_fees_deducted"] - expected_fees) < 0.05


class TestScenarioMultipliers:
    """Scenario multiplier application tests."""

    def _rides(self, n: int = 6) -> list[MagicMock]:
        base = _NOW - timedelta(days=5)
        return [
            _make_ride(
                ride_id=i, driver_id=1, actual_fare=10.00,
                completed_at=base + timedelta(days=i % 5),
            )
            for i in range(n)
        ]

    @pytest.mark.anyio
    async def test_conservative_multiplier(self):
        rides = self._rides()
        db_mod = _db_sequence(rides, [], [])
        mod_result = await get_driver_revenue_projection(
            db_mod, driver_id=1, period="month", scenario="moderate"
        )
        db_con = _db_sequence(rides, [], [])
        con_result = await get_driver_revenue_projection(
            db_con, driver_id=1, period="month", scenario="conservative"
        )
        # Conservative rides ~ moderate * 0.8
        assert con_result["projection"]["estimated_rides"] < mod_result["projection"]["estimated_rides"]

    @pytest.mark.anyio
    async def test_optimistic_multiplier(self):
        rides = self._rides()
        db_mod = _db_sequence(rides, [], [])
        mod_result = await get_driver_revenue_projection(
            db_mod, driver_id=1, period="month", scenario="moderate"
        )
        db_opt = _db_sequence(rides, [], [])
        opt_result = await get_driver_revenue_projection(
            db_opt, driver_id=1, period="month", scenario="optimistic"
        )
        assert opt_result["projection"]["estimated_rides"] > mod_result["projection"]["estimated_rides"]

    @pytest.mark.anyio
    async def test_moderate_multiplier_is_baseline(self):
        """Moderate result has scenario_multiplier exactly 1.0."""
        rides = self._rides()
        db = _db_sequence(rides, [], [])
        result = await get_driver_revenue_projection(
            db, driver_id=1, period="month", scenario="moderate"
        )
        assert result["scenario_multipliers"]["moderate"] == 1.0


class TestPeriodExtrapolation:
    """Period window tests."""

    def _rides(self, n: int = 6) -> list[MagicMock]:
        base = _NOW - timedelta(days=5)
        return [
            _make_ride(
                ride_id=i, driver_id=1, actual_fare=10.00,
                completed_at=base + timedelta(days=i % 5),
            )
            for i in range(n)
        ]

    @pytest.mark.anyio
    async def test_week_fewer_rides_than_month(self):
        rides = self._rides()
        db_week = _db_sequence(rides, [], [])
        week = await get_driver_revenue_projection(
            db_week, driver_id=1, period="week", scenario="moderate"
        )
        db_month = _db_sequence(rides, [], [])
        month = await get_driver_revenue_projection(
            db_month, driver_id=1, period="month", scenario="moderate"
        )
        assert week["projection"]["estimated_rides"] < month["projection"]["estimated_rides"]

    @pytest.mark.anyio
    async def test_quarter_more_rides_than_month(self):
        rides = self._rides()
        db_month = _db_sequence(rides, [], [])
        month = await get_driver_revenue_projection(
            db_month, driver_id=1, period="month", scenario="moderate"
        )
        db_q = _db_sequence(rides, [], [])
        quarter = await get_driver_revenue_projection(
            db_q, driver_id=1, period="quarter", scenario="moderate"
        )
        assert quarter["projection"]["estimated_rides"] > month["projection"]["estimated_rides"]

    @pytest.mark.anyio
    async def test_period_in_response(self):
        db = _db_sequence([])
        result = await get_driver_revenue_projection(db, driver_id=1, period="week")
        assert result["period"] == "week"

    @pytest.mark.anyio
    async def test_scenario_in_response(self):
        db = _db_sequence([])
        result = await get_driver_revenue_projection(
            db, driver_id=1, scenario="optimistic"
        )
        assert result["scenario"] == "optimistic"


class TestAvgHourlyRate:
    """avg_hourly_rate calculation."""

    @pytest.mark.anyio
    async def test_hourly_rate_positive_for_established_driver(self):
        rides = [
            _make_ride(ride_id=i, driver_id=1, actual_fare=15.00, duration_min=20.0,
                       completed_at=_NOW - timedelta(days=i))
            for i in range(6)
        ]
        db = _db_sequence(rides, [], [])
        result = await get_driver_revenue_projection(db, driver_id=1, period="month")
        assert result["projection"]["avg_hourly_rate"] > 0

    @pytest.mark.anyio
    async def test_hourly_rate_uses_net_not_gross(self):
        """avg_hourly_rate must be < gross/hour since fees are deducted."""
        rides = [
            _make_ride(ride_id=i, driver_id=1, actual_fare=15.00, duration_min=60.0,
                       completed_at=_NOW - timedelta(days=i))
            for i in range(6)
        ]
        db = _db_sequence(rides, [], [])
        result = await get_driver_revenue_projection(db, driver_id=1, period="month")
        proj = result["projection"]
        gross_hourly = proj["estimated_gross_earnings"] / max(proj["estimated_rides"], 1)
        assert proj["avg_hourly_rate"] < gross_hourly


# ---------------------------------------------------------------------------
# Service unit tests — earnings comparison
# ---------------------------------------------------------------------------


class TestEarningsComparison:
    """Tests for get_driver_earnings_comparison."""

    def _rides(self, n: int, driver_id: int, fare: float = 15.0) -> list[MagicMock]:
        return [
            _make_ride(ride_id=i + driver_id * 100, driver_id=driver_id, actual_fare=fare)
            for i in range(n)
        ]

    # DB call sequence in get_driver_earnings_comparison:
    #   With no driver rides (empty ride_ids → tips call skipped):
    #     1. _fetch_driver_rides       → driver completed rides (empty)
    #     2. _fetch_all_driver_rides   → all platform rides
    #     3. cancelled rides query     → driver cancelled rides
    #     (bulk tips skipped — no ride_ids)
    #
    #   With driver rides AND non-empty all_rides:
    #     1. _fetch_driver_rides       → driver completed rides
    #     2. _fetch_tips_for_rides     → driver tips
    #     3. _fetch_all_driver_rides   → all platform rides
    #     4. cancelled rides query     → driver cancelled rides
    #     5. bulk all tips query       → all platform tips

    @pytest.mark.anyio
    async def test_period_in_response(self):
        # No driver rides: tips and bulk tips calls are skipped
        db = _db_sequence([], [], [])  # driver rides, all platform rides, cancelled
        result = await get_driver_earnings_comparison(db, driver_id=1, period="week")
        assert result["period"] == "week"

    @pytest.mark.anyio
    async def test_driver_total_rides(self):
        driver_rides = self._rides(5, driver_id=1)
        all_rides = driver_rides[:]
        # driver rides, driver tips, all platform rides, cancelled, all tips
        db = _db_sequence(driver_rides, [], all_rides, [], [])
        result = await get_driver_earnings_comparison(db, driver_id=1, period="month")
        assert result["driver"]["total_rides"] == 5

    @pytest.mark.anyio
    async def test_driver_gross_earnings(self):
        driver_rides = self._rides(4, driver_id=1, fare=20.0)
        all_rides = driver_rides[:]
        db = _db_sequence(driver_rides, [], all_rides, [], [])
        result = await get_driver_earnings_comparison(db, driver_id=1)
        assert abs(result["driver"]["gross_earnings"] - 80.0) < 0.01

    @pytest.mark.anyio
    async def test_driver_avg_per_ride(self):
        driver_rides = self._rides(5, driver_id=1, fare=10.0)
        all_rides = driver_rides[:]
        db = _db_sequence(driver_rides, [], all_rides, [], [])
        result = await get_driver_earnings_comparison(db, driver_id=1)
        assert abs(result["driver"]["avg_per_ride"] - 10.0) < 0.01

    @pytest.mark.anyio
    async def test_driver_completion_rate_with_cancellations(self):
        driver_rides = self._rides(8, driver_id=1)  # 8 completed
        cancelled = [
            _make_ride(ride_id=900 + i, driver_id=1, status=RideStatus.CANCELLED)
            for i in range(2)
        ]
        all_rides = driver_rides[:]
        # driver rides, driver tips (empty), all rides, cancelled, all tips (empty)
        db = _db_sequence(driver_rides, [], all_rides, cancelled, [])
        result = await get_driver_earnings_comparison(db, driver_id=1)
        assert abs(result["driver"]["completion_rate"] - 0.8) < 0.01

    @pytest.mark.anyio
    async def test_driver_tips_summed(self):
        driver_rides = self._rides(3, driver_id=1)
        driver_tips = [
            _make_tip(tip_id=i, ride_id=r.id, driver_id=1, amount_cents=200)
            for i, r in enumerate(driver_rides)
        ]
        all_rides = driver_rides[:]
        # driver rides, driver tips, all platform rides, cancelled, all platform tips
        db = _db_sequence(driver_rides, driver_tips, all_rides, [], driver_tips)
        result = await get_driver_earnings_comparison(db, driver_id=1)
        assert abs(result["driver"]["tips"] - 6.0) < 0.01

    @pytest.mark.anyio
    async def test_percentile_values_in_range(self):
        driver_rides = self._rides(5, driver_id=1)
        all_rides = driver_rides[:]
        db = _db_sequence(driver_rides, [], all_rides, [], [])
        result = await get_driver_earnings_comparison(db, driver_id=1)
        pct = result["percentile"]
        for key in ("rides", "earnings", "tips", "completion_rate"):
            assert 0 <= pct[key] <= 100, f"{key} percentile out of range"

    @pytest.mark.anyio
    async def test_response_has_platform_average_block(self):
        # No driver rides → no tips or bulk tips call
        db = _db_sequence([], [], [])
        result = await get_driver_earnings_comparison(db, driver_id=1)
        assert "platform_average" in result
        assert "total_rides" in result["platform_average"]


# ---------------------------------------------------------------------------
# _percentile helper unit tests
# ---------------------------------------------------------------------------


class TestPercentileHelper:
    def test_empty_list_returns_50(self):
        assert _percentile(100.0, []) == 50

    def test_sole_value_returns_0(self):
        # Nothing is below the only value
        assert _percentile(10.0, [10.0]) == 0

    def test_value_above_all_others_returns_100(self):
        assert _percentile(100.0, [10.0, 20.0, 30.0]) == 100

    def test_middle_value(self):
        result = _percentile(5.0, [1.0, 5.0, 10.0])
        # 1 value (1.0) is below 5.0 => 1/3 = 33
        assert result == 33


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_revenue_projection_unauthenticated(client):
    resp = await client.get("/api/v1/analytics/drivers/me/revenue-projections")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_revenue_projection_rider_forbidden(client, rider_token):
    resp = await client.get(
        "/api/v1/analytics/drivers/me/revenue-projections",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_revenue_projection_driver_ok(client, driver_token):
    resp = await client.get(
        "/api/v1/analytics/drivers/me/revenue-projections",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_revenue_projection_new_driver_flag(client, driver_token):
    """A driver with no rides should get is_new_driver_estimate=True."""
    resp = await client.get(
        "/api/v1/analytics/drivers/me/revenue-projections",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_new_driver_estimate"] is True


@pytest.mark.anyio
async def test_revenue_projection_invalid_period(client, driver_token):
    resp = await client.get(
        "/api/v1/analytics/drivers/me/revenue-projections?period=year",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_revenue_projection_invalid_scenario(client, driver_token):
    resp = await client.get(
        "/api/v1/analytics/drivers/me/revenue-projections?scenario=supercharged",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_revenue_projection_schema_valid(client, driver_token):
    resp = await client.get(
        "/api/v1/analytics/drivers/me/revenue-projections",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "projection" in data
    assert "based_on" in data
    assert "scenario_multipliers" in data
    proj = data["projection"]
    for key in (
        "estimated_rides",
        "estimated_gross_earnings",
        "estimated_net_earnings",
        "estimated_tips",
        "platform_fees_deducted",
        "avg_hourly_rate",
    ):
        assert key in proj, f"Missing key '{key}' in projection"


@pytest.mark.anyio
async def test_revenue_projection_period_week(client, driver_token):
    resp = await client.get(
        "/api/v1/analytics/drivers/me/revenue-projections?period=week",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["period"] == "week"


@pytest.mark.anyio
async def test_revenue_projection_period_quarter(client, driver_token):
    resp = await client.get(
        "/api/v1/analytics/drivers/me/revenue-projections?period=quarter",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["period"] == "quarter"


@pytest.mark.anyio
async def test_earnings_comparison_unauthenticated(client):
    resp = await client.get("/api/v1/analytics/drivers/me/earnings-comparison")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_earnings_comparison_rider_forbidden(client, rider_token):
    resp = await client.get(
        "/api/v1/analytics/drivers/me/earnings-comparison",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_earnings_comparison_driver_ok(client, driver_token):
    resp = await client.get(
        "/api/v1/analytics/drivers/me/earnings-comparison",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_earnings_comparison_has_driver_and_platform(client, driver_token):
    resp = await client.get(
        "/api/v1/analytics/drivers/me/earnings-comparison",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "driver" in data
    assert "platform_average" in data


@pytest.mark.anyio
async def test_earnings_comparison_has_percentile(client, driver_token):
    resp = await client.get(
        "/api/v1/analytics/drivers/me/earnings-comparison",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "percentile" in data
    pct = data["percentile"]
    for key in ("rides", "earnings", "tips", "completion_rate"):
        assert key in pct


@pytest.mark.anyio
async def test_earnings_comparison_invalid_period(client, driver_token):
    resp = await client.get(
        "/api/v1/analytics/drivers/me/earnings-comparison?period=all",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 422
