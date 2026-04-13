"""Tests for the rider spending analytics and driver tax summary features.

Covers:
Service unit tests (using AsyncMock for DB):
  1.  get_rider_spending — empty result returns zeroed summary
  2.  get_rider_spending — aggregates total_spent correctly
  3.  get_rider_spending — average_fare calculation
  4.  get_rider_spending — busiest_day determined from day-of-week counts
  5.  get_rider_spending — trips list respects the limit parameter
  6.  get_rider_spending — monthly_breakdown returned for year period
  7.  get_rider_spending — monthly_breakdown returned for all period
  8.  get_rider_spending — monthly_breakdown is None for week/month periods
  9.  get_rider_spending — tip amounts included in total_spent
  10. get_rider_spending — promo_discount subtracted from total
  11. export_rider_spending_csv — returns header row
  12. export_rider_spending_csv — returns correct number of data rows
  13. export_rider_spending_csv — CSV values match ride data
  14. export_rider_spending_csv — empty period returns header only
  15. _period_bounds — week starts on Monday
  16. _period_bounds — month starts on day 1
  17. _period_bounds — year starts on Jan 1
  18. _period_bounds — all starts on epoch start
  19. get_driver_tax_summary — empty result returns zeroed summary with disclaimer
  20. get_driver_tax_summary — gross_earnings sums actual_fare
  21. get_driver_tax_summary — falls back to estimated_fare when actual_fare is None
  22. get_driver_tax_summary — tips_received sums completed tip records
  23. get_driver_tax_summary — bonuses_received sums paid incentive records
  24. get_driver_tax_summary — total_income = gross + tips + bonuses
  25. get_driver_tax_summary — platform_fees_paid from payments table
  26. get_driver_tax_summary — rides_completed count is correct
  27. get_driver_tax_summary — miles_driven_estimate converts km to miles
  28. get_driver_tax_summary — miles_driven_estimate is None when no distance data
  29. get_driver_tax_summary — quarterly_breakdown groups rides by quarter
  30. get_driver_tax_summary — disclaimer is present in response
  31. export_driver_tax_csv — returns header row
  32. export_driver_tax_csv — returns correct data rows
  33. export_driver_tax_csv — duration_min formatted correctly
  34. export_driver_tax_csv — missing duration becomes empty string

API integration tests (using real in-transaction test DB via conftest fixtures):
  35. GET /analytics/rider/spending — 401 with no auth
  36. GET /analytics/rider/spending — 200 with rider token, default period
  37. GET /analytics/rider/spending — period=week returns valid structure
  38. GET /analytics/rider/spending — period=year includes monthly_breakdown
  39. GET /analytics/rider/spending — period=all includes monthly_breakdown
  40. GET /analytics/rider/spending — invalid period returns 422
  41. GET /analytics/rider/spending — trip_count reflects completed rides only
  42. GET /analytics/rider/spending — cancelled rides not counted
  43. GET /analytics/rider/spending/export — 200 with rider token, CSV content-type
  44. GET /analytics/rider/spending/export — CSV has header row
  45. GET /analytics/rider/spending/export — invalid period returns 422
  46. GET /analytics/driver/tax-summary — 401 with no auth
  47. GET /analytics/driver/tax-summary — 403 with rider token
  48. GET /analytics/driver/tax-summary — 200 with driver token
  49. GET /analytics/driver/tax-summary — response contains disclaimer
  50. GET /analytics/driver/tax-summary — year param filters correctly
  51. GET /analytics/driver/tax-summary — future year returns zero earnings
  52. GET /analytics/driver/tax-summary/export — 200 with driver token, CSV content-type
  53. GET /analytics/driver/tax-summary/export — CSV has header row
  54. GET /analytics/driver/tax-summary/export — year param in filename
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.incentive import DriverIncentiveProgress, ProgressStatus
from app.models.payment import Payment, PaymentStatus
from app.models.ride import Ride, RideStatus
from app.models.tip import TipRecord, TipStatus
from app.models.user import User, UserRole
from app.services.auth import create_access_token, hash_password
from app.services.analytics import (
    _period_bounds,
    export_driver_tax_csv,
    export_rider_spending_csv,
    get_driver_tax_summary,
    get_rider_spending,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_ride(
    ride_id: int = 1,
    rider_id: int = 10,
    driver_id: int = 20,
    status: RideStatus = RideStatus.COMPLETED,
    actual_fare: float | None = 15.00,
    estimated_fare: float = 14.50,
    promo_discount: float = 0.0,
    distance_km: float | None = None,
    duration_min: float | None = None,
    completed_at: datetime | None = None,
    promo_code_id: int | None = None,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.actual_fare = actual_fare
    ride.estimated_fare = estimated_fare
    ride.promo_discount = promo_discount
    ride.distance_km = distance_km
    ride.duration_min = duration_min
    ride.promo_code_id = promo_code_id
    ride.pickup_address = "123 Main St"
    ride.dropoff_address = "456 Oak Ave"
    ride.completed_at = completed_at or datetime(2025, 3, 15, 14, 0, 0, tzinfo=timezone.utc)
    return ride


def _make_tip(
    tip_id: int = 1,
    ride_id: int = 1,
    driver_id: int = 20,
    rider_id: int = 10,
    amount_cents: int = 200,
    status: TipStatus = TipStatus.COMPLETED,
) -> MagicMock:
    tip = MagicMock(spec=TipRecord)
    tip.id = tip_id
    tip.ride_id = ride_id
    tip.driver_id = driver_id
    tip.rider_id = rider_id
    tip.amount_cents = amount_cents
    tip.status = status
    return tip


def _make_payment(
    pay_id: int = 1,
    ride_id: int = 1,
    amount: float = 15.00,
    platform_fee: float = 2.25,
    driver_payout: float = 12.75,
    status: PaymentStatus = PaymentStatus.COMPLETED,
) -> MagicMock:
    p = MagicMock(spec=Payment)
    p.id = pay_id
    p.ride_id = ride_id
    p.amount = amount
    p.platform_fee = platform_fee
    p.driver_payout = driver_payout
    p.status = status
    return p


def _make_bonus(
    bonus_id: int = 1,
    driver_id: int = 20,
    bonus_earned: float = 25.00,
    status: str = ProgressStatus.PAID.value,
    paid_at: datetime | None = None,
) -> MagicMock:
    b = MagicMock(spec=DriverIncentiveProgress)
    b.id = bonus_id
    b.driver_id = driver_id
    b.bonus_earned = bonus_earned
    b.status = status
    b.paid_at = paid_at or datetime(2025, 3, 1, tzinfo=timezone.utc)
    return b


def _make_db_with_sequence(*result_lists) -> AsyncMock:
    """DB mock where each execute() call returns the next list via scalars().all()."""
    db = AsyncMock()
    side_effects = []
    for items in result_lists:
        mock_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = items
        mock_result.scalars.return_value = scalars_mock
        side_effects.append(mock_result)
    db.execute = AsyncMock(side_effect=side_effects)
    return db


# ---------------------------------------------------------------------------
# Service unit tests — _period_bounds
# ---------------------------------------------------------------------------


class TestPeriodBounds:
    def test_month_starts_on_first(self):
        start, end = _period_bounds("month")
        assert start.day == 1
        assert start.hour == 0
        assert start.minute == 0

    def test_year_starts_on_jan_1(self):
        start, _ = _period_bounds("year")
        assert start.month == 1
        assert start.day == 1

    def test_all_starts_on_epoch(self):
        start, _ = _period_bounds("all")
        assert start.year == 2000

    def test_week_starts_on_monday(self):
        start, _ = _period_bounds("week")
        # weekday() == 0 is Monday
        assert start.weekday() == 0

    def test_end_is_now_approximately(self):
        _, end = _period_bounds("month")
        now = datetime.now(tz=timezone.utc)
        # end should be within a few seconds of now
        delta = abs((now - end).total_seconds())
        assert delta < 5


# ---------------------------------------------------------------------------
# Service unit tests — get_rider_spending
# ---------------------------------------------------------------------------


class TestGetRiderSpending:
    @pytest.mark.asyncio
    async def test_empty_returns_zeroed_summary(self):
        db = _make_db_with_sequence([], [])
        result = await get_rider_spending(db, rider_id=10, period="month")
        assert result["total_spent"] == 0.0
        assert result["trip_count"] == 0
        assert result["average_fare"] == 0.0
        assert result["busiest_day"] is None
        assert result["trips"] == []

    @pytest.mark.asyncio
    async def test_monthly_breakdown_none_for_month_period(self):
        db = _make_db_with_sequence([], [])
        result = await get_rider_spending(db, rider_id=10, period="month")
        assert result["monthly_breakdown"] is None

    @pytest.mark.asyncio
    async def test_monthly_breakdown_none_for_week_period(self):
        db = _make_db_with_sequence([], [])
        result = await get_rider_spending(db, rider_id=10, period="week")
        assert result["monthly_breakdown"] is None

    @pytest.mark.asyncio
    async def test_total_spent_sums_fares(self):
        rides = [_make_ride(ride_id=1, actual_fare=10.0), _make_ride(ride_id=2, actual_fare=20.0)]
        db = _make_db_with_sequence(rides, [])
        result = await get_rider_spending(db, rider_id=10, period="month")
        assert result["total_spent"] == 30.0

    @pytest.mark.asyncio
    async def test_average_fare_computed(self):
        rides = [_make_ride(ride_id=1, actual_fare=10.0), _make_ride(ride_id=2, actual_fare=20.0)]
        db = _make_db_with_sequence(rides, [])
        result = await get_rider_spending(db, rider_id=10, period="month")
        assert result["average_fare"] == 15.0

    @pytest.mark.asyncio
    async def test_tip_added_to_total_spent(self):
        rides = [_make_ride(ride_id=1, actual_fare=10.0)]
        tips = [_make_tip(ride_id=1, amount_cents=200)]  # $2.00
        db = _make_db_with_sequence(rides, tips)
        result = await get_rider_spending(db, rider_id=10, period="month")
        assert result["total_spent"] == 12.0  # 10 + 2

    @pytest.mark.asyncio
    async def test_promo_discount_subtracted(self):
        rides = [_make_ride(ride_id=1, actual_fare=20.0, promo_discount=5.0)]
        db = _make_db_with_sequence(rides, [])
        result = await get_rider_spending(db, rider_id=10, period="month")
        assert result["total_spent"] == 15.0

    @pytest.mark.asyncio
    async def test_trip_count_matches_rides(self):
        rides = [_make_ride(ride_id=i) for i in range(5)]
        db = _make_db_with_sequence(rides, [])
        result = await get_rider_spending(db, rider_id=10, period="month")
        assert result["trip_count"] == 5

    @pytest.mark.asyncio
    async def test_trips_list_respects_limit(self):
        rides = [_make_ride(ride_id=i) for i in range(10)]
        db = _make_db_with_sequence(rides, [])
        result = await get_rider_spending(db, rider_id=10, period="month", limit=3)
        assert len(result["trips"]) == 3

    @pytest.mark.asyncio
    async def test_busiest_day_returned(self):
        # 3 rides on Saturday (weekday=5), 1 ride on Monday (weekday=0)
        saturday = datetime(2025, 3, 15, 14, 0, 0, tzinfo=timezone.utc)  # Saturday
        monday = datetime(2025, 3, 17, 14, 0, 0, tzinfo=timezone.utc)    # Monday
        rides = [
            _make_ride(ride_id=1, completed_at=saturday),
            _make_ride(ride_id=2, completed_at=saturday),
            _make_ride(ride_id=3, completed_at=saturday),
            _make_ride(ride_id=4, completed_at=monday),
        ]
        db = _make_db_with_sequence(rides, [])
        result = await get_rider_spending(db, rider_id=10, period="month")
        assert result["busiest_day"] == "Saturday"

    @pytest.mark.asyncio
    async def test_monthly_breakdown_returned_for_year(self):
        jan = datetime(2025, 1, 10, tzinfo=timezone.utc)
        feb = datetime(2025, 2, 10, tzinfo=timezone.utc)
        rides = [
            _make_ride(ride_id=1, actual_fare=10.0, completed_at=jan),
            _make_ride(ride_id=2, actual_fare=20.0, completed_at=feb),
        ]
        db = _make_db_with_sequence(rides, [])
        result = await get_rider_spending(db, rider_id=10, period="year")
        assert result["monthly_breakdown"] is not None
        assert len(result["monthly_breakdown"]) == 2

    @pytest.mark.asyncio
    async def test_monthly_breakdown_returned_for_all(self):
        rides = [_make_ride(ride_id=1)]
        db = _make_db_with_sequence(rides, [])
        result = await get_rider_spending(db, rider_id=10, period="all")
        assert result["monthly_breakdown"] is not None

    @pytest.mark.asyncio
    async def test_falls_back_to_estimated_fare_when_actual_is_none(self):
        rides = [_make_ride(ride_id=1, actual_fare=None, estimated_fare=12.5)]
        db = _make_db_with_sequence(rides, [])
        result = await get_rider_spending(db, rider_id=10, period="month")
        assert result["total_spent"] == 12.5

    @pytest.mark.asyncio
    async def test_trip_detail_contains_expected_fields(self):
        rides = [_make_ride(ride_id=42, actual_fare=18.0)]
        db = _make_db_with_sequence(rides, [])
        result = await get_rider_spending(db, rider_id=10, period="month")
        trip = result["trips"][0]
        assert trip["ride_id"] == 42
        assert "date" in trip
        assert "pickup_address" in trip
        assert "dropoff_address" in trip
        assert "fare" in trip
        assert "tip" in trip
        assert "promo_discount" in trip
        assert "total_charged" in trip


# ---------------------------------------------------------------------------
# Service unit tests — export_rider_spending_csv
# ---------------------------------------------------------------------------


class TestExportRiderSpendingCsv:
    @pytest.mark.asyncio
    async def test_header_row_present(self):
        db = _make_db_with_sequence([], [])
        csv_text = await export_rider_spending_csv(db, rider_id=10, period="month")
        first_line = csv_text.splitlines()[0]
        assert "date" in first_line
        assert "pickup_address" in first_line
        assert "ride_id" in first_line

    @pytest.mark.asyncio
    async def test_empty_period_returns_header_only(self):
        db = _make_db_with_sequence([], [])
        csv_text = await export_rider_spending_csv(db, rider_id=10, period="month")
        lines = [l for l in csv_text.splitlines() if l.strip()]
        assert len(lines) == 1  # header only

    @pytest.mark.asyncio
    async def test_data_rows_match_ride_count(self):
        rides = [_make_ride(ride_id=i) for i in range(3)]
        db = _make_db_with_sequence(rides, [])
        csv_text = await export_rider_spending_csv(db, rider_id=10, period="month")
        lines = [l for l in csv_text.splitlines() if l.strip()]
        assert len(lines) == 4  # 1 header + 3 data rows

    @pytest.mark.asyncio
    async def test_csv_values_match_ride(self):
        rides = [_make_ride(ride_id=99, actual_fare=25.0, promo_discount=5.0)]
        tips = [_make_tip(ride_id=99, amount_cents=300)]  # $3.00
        db = _make_db_with_sequence(rides, tips)
        csv_text = await export_rider_spending_csv(db, rider_id=10, period="month")
        data_line = csv_text.splitlines()[1]
        assert "99" in data_line  # ride_id
        assert "25.0" in data_line
        assert "3.0" in data_line


# ---------------------------------------------------------------------------
# Service unit tests — get_driver_tax_summary
# ---------------------------------------------------------------------------


class TestGetDriverTaxSummary:
    # NOTE on mock call counts:
    # get_driver_tax_summary makes these DB calls in order:
    #   1. rides query (always)
    #   2. tips query (only if ride_ids is non-empty)
    #   3. payments query (only if ride_ids is non-empty)
    #   4. bonuses query (always)
    # So empty rides => 2 DB calls; non-empty rides => 4 DB calls.

    @pytest.mark.asyncio
    async def test_empty_returns_zeroed_summary(self):
        # rides=[], bonuses=[] — 2 calls
        db = _make_db_with_sequence([], [])
        result = await get_driver_tax_summary(db, driver_id=20, year=2025)
        assert result["gross_earnings"] == 0.0
        assert result["tips_received"] == 0.0
        assert result["bonuses_received"] == 0.0
        assert result["rides_completed"] == 0
        assert result["miles_driven_estimate"] is None

    @pytest.mark.asyncio
    async def test_disclaimer_always_present(self):
        db = _make_db_with_sequence([], [])
        result = await get_driver_tax_summary(db, driver_id=20, year=2025)
        assert "disclaimer" in result
        assert len(result["disclaimer"]) > 10

    @pytest.mark.asyncio
    async def test_gross_earnings_sums_actual_fares(self):
        rides = [_make_ride(actual_fare=20.0), _make_ride(ride_id=2, actual_fare=30.0)]
        # rides, tips, payments, bonuses
        db = _make_db_with_sequence(rides, [], [], [])
        result = await get_driver_tax_summary(db, driver_id=20, year=2025)
        assert result["gross_earnings"] == 50.0

    @pytest.mark.asyncio
    async def test_falls_back_to_estimated_fare(self):
        rides = [_make_ride(actual_fare=None, estimated_fare=18.0)]
        db = _make_db_with_sequence(rides, [], [], [])
        result = await get_driver_tax_summary(db, driver_id=20, year=2025)
        assert result["gross_earnings"] == 18.0

    @pytest.mark.asyncio
    async def test_tips_received_sums_completed_tips(self):
        rides = [_make_ride(ride_id=1, actual_fare=15.0)]
        tips = [_make_tip(ride_id=1, amount_cents=400)]  # $4.00
        db = _make_db_with_sequence(rides, tips, [], [])
        result = await get_driver_tax_summary(db, driver_id=20, year=2025)
        assert result["tips_received"] == 4.0

    @pytest.mark.asyncio
    async def test_bonuses_received_sums_paid_incentives(self):
        # empty rides => only 2 calls: rides, bonuses
        bonuses = [_make_bonus(bonus_earned=50.0), _make_bonus(bonus_id=2, bonus_earned=25.0)]
        db = _make_db_with_sequence([], bonuses)
        result = await get_driver_tax_summary(db, driver_id=20, year=2025)
        assert result["bonuses_received"] == 75.0

    @pytest.mark.asyncio
    async def test_total_income_is_sum_of_components(self):
        rides = [_make_ride(ride_id=1, actual_fare=100.0)]
        tips = [_make_tip(ride_id=1, amount_cents=1000)]  # $10
        bonuses = [_make_bonus(bonus_earned=20.0)]
        # rides, tips, payments, bonuses
        db = _make_db_with_sequence(rides, tips, [], bonuses)
        result = await get_driver_tax_summary(db, driver_id=20, year=2025)
        assert result["total_income"] == pytest.approx(130.0)

    @pytest.mark.asyncio
    async def test_platform_fees_from_payments(self):
        rides = [_make_ride(ride_id=1, actual_fare=20.0)]
        payments = [_make_payment(ride_id=1, platform_fee=3.0)]
        # rides, tips, payments, bonuses
        db = _make_db_with_sequence(rides, [], payments, [])
        result = await get_driver_tax_summary(db, driver_id=20, year=2025)
        assert result["platform_fees_paid"] == 3.0

    @pytest.mark.asyncio
    async def test_rides_completed_count(self):
        rides = [_make_ride(ride_id=i) for i in range(7)]
        db = _make_db_with_sequence(rides, [], [], [])
        result = await get_driver_tax_summary(db, driver_id=20, year=2025)
        assert result["rides_completed"] == 7

    @pytest.mark.asyncio
    async def test_miles_driven_converts_km(self):
        rides = [_make_ride(ride_id=1, distance_km=10.0)]
        db = _make_db_with_sequence(rides, [], [], [])
        result = await get_driver_tax_summary(db, driver_id=20, year=2025)
        # 10 km * 0.621371 = 6.21371, rounded to 1 dp
        assert result["miles_driven_estimate"] == pytest.approx(6.2, abs=0.1)

    @pytest.mark.asyncio
    async def test_miles_driven_none_when_no_distance_data(self):
        rides = [_make_ride(ride_id=1, distance_km=None)]
        db = _make_db_with_sequence(rides, [], [], [])
        result = await get_driver_tax_summary(db, driver_id=20, year=2025)
        assert result["miles_driven_estimate"] is None

    @pytest.mark.asyncio
    async def test_quarterly_breakdown_groups_by_quarter(self):
        q1_ride = _make_ride(
            ride_id=1, actual_fare=10.0,
            completed_at=datetime(2025, 2, 1, tzinfo=timezone.utc)
        )
        q3_ride = _make_ride(
            ride_id=2, actual_fare=20.0,
            completed_at=datetime(2025, 8, 1, tzinfo=timezone.utc)
        )
        # rides, tips, payments, bonuses
        db = _make_db_with_sequence([q1_ride, q3_ride], [], [], [])
        result = await get_driver_tax_summary(db, driver_id=20, year=2025)
        quarters = {q["quarter"]: q for q in result["quarterly_breakdown"]}
        assert "Q1" in quarters
        assert "Q3" in quarters
        assert quarters["Q1"]["gross"] == 10.0
        assert quarters["Q3"]["gross"] == 20.0

    @pytest.mark.asyncio
    async def test_year_field_in_response(self):
        db = _make_db_with_sequence([], [])
        result = await get_driver_tax_summary(db, driver_id=20, year=2024)
        assert result["year"] == 2024


# ---------------------------------------------------------------------------
# Service unit tests — export_driver_tax_csv
# ---------------------------------------------------------------------------


class TestExportDriverTaxCsv:
    @pytest.mark.asyncio
    async def test_header_row_present(self):
        db = _make_db_with_sequence([], [])
        csv_text = await export_driver_tax_csv(db, driver_id=20, year=2025)
        first_line = csv_text.splitlines()[0]
        assert "date" in first_line
        assert "ride_id" in first_line
        assert "fare_earned" in first_line
        assert "ride_duration_minutes" in first_line

    @pytest.mark.asyncio
    async def test_data_rows_match_ride_count(self):
        rides = [_make_ride(ride_id=i) for i in range(4)]
        db = _make_db_with_sequence(rides, [])
        csv_text = await export_driver_tax_csv(db, driver_id=20, year=2025)
        lines = [l for l in csv_text.splitlines() if l.strip()]
        assert len(lines) == 5  # header + 4 rides

    @pytest.mark.asyncio
    async def test_duration_formatted(self):
        rides = [_make_ride(ride_id=1, actual_fare=10.0, duration_min=23.5)]
        db = _make_db_with_sequence(rides, [])
        csv_text = await export_driver_tax_csv(db, driver_id=20, year=2025)
        assert "23.5" in csv_text

    @pytest.mark.asyncio
    async def test_missing_duration_is_empty_string(self):
        rides = [_make_ride(ride_id=1, actual_fare=10.0, duration_min=None)]
        db = _make_db_with_sequence(rides, [])
        csv_text = await export_driver_tax_csv(db, driver_id=20, year=2025)
        # The duration field should be empty (two adjacent commas or trailing comma)
        data_line = csv_text.splitlines()[1]
        parts = data_line.split(",")
        assert parts[-1].strip() == ""  # last column is duration, should be empty

    @pytest.mark.asyncio
    async def test_empty_year_returns_header_only(self):
        db = _make_db_with_sequence([], [])
        csv_text = await export_driver_tax_csv(db, driver_id=20, year=2025)
        lines = [l for l in csv_text.splitlines() if l.strip()]
        assert len(lines) == 1


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestRiderSpendingEndpoints:
    async def test_spending_no_auth_returns_401(self, client):
        resp = await client.get("/api/v1/analytics/rider/spending")
        assert resp.status_code == 401

    async def test_spending_with_rider_token_returns_200(self, client, rider, rider_token):
        resp = await client.get(
            "/api/v1/analytics/rider/spending",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_spent" in data
        assert "trip_count" in data
        assert "average_fare" in data
        assert "trips" in data

    async def test_spending_period_week(self, client, rider, rider_token):
        resp = await client.get(
            "/api/v1/analytics/rider/spending?period=week",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["monthly_breakdown"] is None

    async def test_spending_period_year_has_monthly_breakdown(self, client, rider, rider_token):
        resp = await client.get(
            "/api/v1/analytics/rider/spending?period=year",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # monthly_breakdown is a list (possibly empty) for year period
        assert isinstance(data["monthly_breakdown"], list)

    async def test_spending_period_all_has_monthly_breakdown(self, client, rider, rider_token):
        resp = await client.get(
            "/api/v1/analytics/rider/spending?period=all",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json()["monthly_breakdown"], list)

    async def test_spending_invalid_period_returns_422(self, client, rider, rider_token):
        resp = await client.get(
            "/api/v1/analytics/rider/spending?period=quarterly",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 422

    async def test_spending_only_counts_completed_rides(
        self, client, db, rider, driver_user, rider_token
    ):
        from geoalchemy2.functions import ST_MakePoint

        # Add one completed ride and one cancelled ride
        completed = Ride(
            rider_id=rider.id,
            driver_id=driver_user.id,
            status=RideStatus.COMPLETED,
            pickup_location=ST_MakePoint(-122.4194, 37.7749),
            dropoff_location=ST_MakePoint(-122.4094, 37.7849),
            pickup_address="Start",
            dropoff_address="End",
            estimated_fare=12.0,
            actual_fare=12.0,
            completed_at=datetime.now(tz=timezone.utc),
            requested_at=datetime.now(tz=timezone.utc),
        )
        cancelled = Ride(
            rider_id=rider.id,
            driver_id=driver_user.id,
            status=RideStatus.CANCELLED,
            pickup_location=ST_MakePoint(-122.4194, 37.7749),
            dropoff_location=ST_MakePoint(-122.4094, 37.7849),
            pickup_address="Start",
            dropoff_address="End",
            estimated_fare=10.0,
            requested_at=datetime.now(tz=timezone.utc),
        )
        db.add(completed)
        db.add(cancelled)
        await db.flush()

        resp = await client.get(
            "/api/v1/analytics/rider/spending?period=month",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["trip_count"] == 1

    async def test_spending_cancelled_rides_not_included(
        self, client, db, rider, driver_user, rider_token
    ):
        from geoalchemy2.functions import ST_MakePoint

        cancelled = Ride(
            rider_id=rider.id,
            driver_id=driver_user.id,
            status=RideStatus.CANCELLED,
            pickup_location=ST_MakePoint(-122.4194, 37.7749),
            dropoff_location=ST_MakePoint(-122.4094, 37.7849),
            pickup_address="Start",
            dropoff_address="End",
            estimated_fare=10.0,
            requested_at=datetime.now(tz=timezone.utc),
        )
        db.add(cancelled)
        await db.flush()

        resp = await client.get(
            "/api/v1/analytics/rider/spending?period=month",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["trip_count"] == 0


@pytest.mark.anyio
class TestRiderSpendingExportEndpoints:
    async def test_export_returns_csv_content_type(self, client, rider, rider_token):
        resp = await client.get(
            "/api/v1/analytics/rider/spending/export",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    async def test_export_has_header_row(self, client, rider, rider_token):
        resp = await client.get(
            "/api/v1/analytics/rider/spending/export",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        first_line = resp.text.splitlines()[0]
        assert "pickup_address" in first_line

    async def test_export_invalid_period_returns_422(self, client, rider, rider_token):
        resp = await client.get(
            "/api/v1/analytics/rider/spending/export?period=bad",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 422


@pytest.mark.anyio
class TestDriverTaxSummaryEndpoints:
    async def test_tax_summary_no_auth_returns_401(self, client):
        resp = await client.get("/api/v1/analytics/driver/tax-summary")
        assert resp.status_code == 401

    async def test_tax_summary_rider_token_returns_403(self, client, rider, rider_token):
        resp = await client.get(
            "/api/v1/analytics/driver/tax-summary",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    async def test_tax_summary_driver_token_returns_200(
        self, client, driver_user, driver_token
    ):
        resp = await client.get(
            "/api/v1/analytics/driver/tax-summary",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "gross_earnings" in data
        assert "tips_received" in data
        assert "quarterly_breakdown" in data

    async def test_tax_summary_contains_disclaimer(self, client, driver_user, driver_token):
        resp = await client.get(
            "/api/v1/analytics/driver/tax-summary",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        assert "disclaimer" in resp.json()

    async def test_tax_summary_year_param(self, client, driver_user, driver_token):
        resp = await client.get(
            "/api/v1/analytics/driver/tax-summary?year=2024",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["year"] == 2024

    async def test_tax_summary_future_year_zero_earnings(
        self, client, driver_user, driver_token
    ):
        resp = await client.get(
            "/api/v1/analytics/driver/tax-summary?year=2099",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["gross_earnings"] == 0.0
        assert data["rides_completed"] == 0


@pytest.mark.anyio
class TestDriverTaxExportEndpoints:
    async def test_export_returns_csv_content_type(self, client, driver_user, driver_token):
        resp = await client.get(
            "/api/v1/analytics/driver/tax-summary/export",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    async def test_export_has_header_row(self, client, driver_user, driver_token):
        resp = await client.get(
            "/api/v1/analytics/driver/tax-summary/export",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        first_line = resp.text.splitlines()[0]
        assert "fare_earned" in first_line

    async def test_export_year_in_filename(self, client, driver_user, driver_token):
        resp = await client.get(
            "/api/v1/analytics/driver/tax-summary/export?year=2024",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        disposition = resp.headers.get("content-disposition", "")
        assert "2024" in disposition
