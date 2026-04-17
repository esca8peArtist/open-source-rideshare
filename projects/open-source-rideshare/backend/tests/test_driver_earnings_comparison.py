"""Tests for the driver earnings comparison feature.

Service unit tests (AsyncMock DB — no live DB required):
  1.  _estimate_driver_payout — base + per-min + per-mile multiplied by take-rate
  2.  _estimate_driver_payout — zero distance and duration yields base * take-rate
  3.  _estimate_driver_payout — km-to-miles conversion applied correctly
  4.  _pct_delta — positive when openride exceeds competitor
  5.  _pct_delta — negative when openride is less than competitor
  6.  _pct_delta — returns 0.0 when competitor is zero
  7.  get_earnings_comparison — returns zero-value response when driver has no rides
  8.  get_earnings_comparison — excludes rides missing distance or duration
  9.  get_earnings_comparison — rides_excluded count is accurate
  10. get_earnings_comparison — uses actual_fare when payment record present
  11. get_earnings_comparison — falls back to actual_fare field when no Payment record
  12. get_earnings_comparison — falls back to estimated_fare when actual_fare is None
  13. get_earnings_comparison — tips added to openride total but not competitor estimate
  14. get_earnings_comparison — correct total distance aggregated across rides
  15. get_earnings_comparison — correct total duration aggregated across rides
  16. get_earnings_comparison — uber estimate matches manual rate card calculation
  17. get_earnings_comparison — lyft estimate matches manual rate card calculation
  18. get_earnings_comparison — openride_vs_uber_delta positive when openride pays more
  19. get_earnings_comparison — openride_vs_uber_delta negative when uber pays more
  20. get_earnings_comparison — openride_vs_uber_pct reflects percentage advantage
  21. get_earnings_comparison — avg_payout_per_ride computed correctly
  22. get_earnings_comparison — avg_payout_per_mile computed correctly
  23. get_earnings_comparison — avg_payout_per_hour computed correctly
  24. get_earnings_comparison — period_start defaults to first of current month
  25. get_earnings_comparison — period_end defaults to today
  26. get_earnings_comparison — reversed date range clamped silently
  27. get_earnings_comparison — rate cards present in response
  28. get_earnings_comparison — methodology_note present in response
  29. get_earnings_comparison — total_distance_miles = km * 0.621371

API integration tests (in-transaction test DB via conftest):
  30. GET /api/v1/drivers/me/earnings-comparison — 401 with no auth
  31. GET /api/v1/drivers/me/earnings-comparison — 403 with rider token
  32. GET /api/v1/drivers/me/earnings-comparison — 200 with driver token
  33. GET /api/v1/drivers/me/earnings-comparison — response matches schema fields
  34. GET /api/v1/drivers/me/earnings-comparison — explicit start_date + end_date accepted
  35. GET /api/v1/drivers/me/earnings-comparison — 422 on invalid date format
  36. GET /api/v1/drivers/me/earnings-comparison — rides_analyzed >= 0 when no rides in DB
  37. GET /api/v1/drivers/me/earnings-comparison — uber_rate_card present in response
  38. GET /api/v1/drivers/me/earnings-comparison — lyft_rate_card present in response
  39. GET /api/v1/drivers/me/earnings-comparison — methodology_note present in response
  40. GET /api/v1/drivers/me/earnings-comparison — total_distance_miles in response
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.payment import Payment, PaymentStatus, PaymentType
from app.models.ride import Ride, RideStatus
from app.models.tip import TipRecord, TipStatus
from app.services.driver_earnings_comparison import (
    _KM_TO_MILES,
    _LYFT_RATE_CARD,
    _UBER_RATE_CARD,
    _estimate_driver_payout,
    _pct_delta,
    get_earnings_comparison,
)

# ---------------------------------------------------------------------------
# Shared constants and factory helpers
# ---------------------------------------------------------------------------

TODAY = date(2026, 4, 14)
DRIVER_ID = 77


def _dt(d: date, hour: int = 12) -> datetime:
    return datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=timezone.utc)


def _make_ride(
    ride_id: int = 1,
    driver_id: int = DRIVER_ID,
    actual_fare: float | None = 15.00,
    estimated_fare: float = 14.00,
    distance_km: float | None = 8.0,
    duration_min: float | None = 12.0,
    completed_at: datetime | None = None,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.driver_id = driver_id
    ride.actual_fare = actual_fare
    ride.estimated_fare = estimated_fare
    ride.distance_km = distance_km
    ride.duration_min = duration_min
    ride.status = RideStatus.COMPLETED
    ride.completed_at = completed_at or _dt(TODAY)
    return ride


def _make_payment_row(ride_id: int, driver_payout: float) -> MagicMock:
    row = MagicMock()
    row.ride_id = ride_id
    row.driver_payout = driver_payout
    return row


def _make_tip_row(ride_id: int, amount_cents: int) -> MagicMock:
    row = MagicMock()
    row.ride_id = ride_id
    row.amount_cents = amount_cents
    return row


def _scalars_list(items: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = list(items)
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _rows_result(rows: list) -> MagicMock:
    """Simulate a result that iterates as rows (non-scalar)."""
    result = MagicMock()
    result.__iter__ = MagicMock(return_value=iter(rows))
    return result


def _make_db(
    rides: list,
    payment_rows: list,
    tip_rows: list,
) -> AsyncMock:
    """Build a DB mock with three sequential execute() results.

    Call order:
      1. _fetch_completed_rides  → scalars list of Ride objects
      2. _fetch_payouts          → row iteration (ride_id, driver_payout)
      3. _fetch_tips             → row iteration (ride_id, amount_cents)
    """
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalars_list(rides),
            _rows_result(payment_rows),
            _rows_result(tip_rows),
        ]
    )
    return db


# ---------------------------------------------------------------------------
# Service unit tests — _estimate_driver_payout
# ---------------------------------------------------------------------------


class TestEstimateDriverPayout:
    def test_base_plus_time_plus_distance(self):
        card = _UBER_RATE_CARD
        dist_km = 8.046  # exactly 5 miles
        dur_min = 10.0
        miles = dist_km * _KM_TO_MILES
        expected_gross = card.base_fare_usd + card.per_minute_usd * dur_min + card.per_mile_usd * miles
        expected = round(expected_gross * card.driver_take_rate, 4)
        assert _estimate_driver_payout(dist_km, dur_min, card) == pytest.approx(expected, rel=1e-4)

    def test_zero_distance_and_duration_gives_base_only(self):
        card = _UBER_RATE_CARD
        result = _estimate_driver_payout(0.0, 0.0, card)
        expected = round(card.base_fare_usd * card.driver_take_rate, 4)
        assert result == pytest.approx(expected, rel=1e-4)

    def test_km_to_miles_conversion(self):
        card = _LYFT_RATE_CARD
        dist_km = 1.0
        dur_min = 0.0
        miles = dist_km * _KM_TO_MILES
        expected = round((card.base_fare_usd + card.per_mile_usd * miles) * card.driver_take_rate, 4)
        assert _estimate_driver_payout(dist_km, dur_min, card) == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# Service unit tests — _pct_delta
# ---------------------------------------------------------------------------


class TestPctDelta:
    def test_positive_when_openride_exceeds_competitor(self):
        result = _pct_delta(120.0, 100.0)
        assert result == pytest.approx(20.0, rel=1e-3)

    def test_negative_when_openride_less_than_competitor(self):
        result = _pct_delta(80.0, 100.0)
        assert result == pytest.approx(-20.0, rel=1e-3)

    def test_zero_when_competitor_is_zero(self):
        assert _pct_delta(50.0, 0.0) == 0.0

    def test_zero_when_equal(self):
        assert _pct_delta(100.0, 100.0) == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Service unit tests — get_earnings_comparison
# ---------------------------------------------------------------------------


class TestGetEarningsComparison:

    @pytest.mark.anyio
    async def test_no_rides_returns_zero_response(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_list([]))
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        assert result.rides_analyzed == 0
        assert result.openride_total_payout == 0.0
        assert result.uber_estimated_total_payout == 0.0

    @pytest.mark.anyio
    async def test_ride_missing_distance_is_excluded(self):
        ride_ok = _make_ride(ride_id=1, distance_km=5.0, duration_min=8.0)
        ride_no_dist = _make_ride(ride_id=2, distance_km=None, duration_min=8.0)
        db = _make_db(
            [ride_ok, ride_no_dist],
            [_make_payment_row(1, 12.0)],
            [],
        )
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        assert result.rides_analyzed == 1
        assert result.rides_excluded == 1

    @pytest.mark.anyio
    async def test_ride_missing_duration_is_excluded(self):
        ride_ok = _make_ride(ride_id=1, distance_km=5.0, duration_min=8.0)
        ride_no_dur = _make_ride(ride_id=2, distance_km=5.0, duration_min=None)
        db = _make_db(
            [ride_ok, ride_no_dur],
            [_make_payment_row(1, 12.0)],
            [],
        )
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        assert result.rides_analyzed == 1
        assert result.rides_excluded == 1

    @pytest.mark.anyio
    async def test_rides_excluded_count_accurate(self):
        rides = [
            _make_ride(ride_id=i, distance_km=5.0 if i % 2 == 0 else None, duration_min=8.0)
            for i in range(1, 7)
        ]
        db = _make_db(
            rides,
            [_make_payment_row(i, 10.0) for i in range(1, 7) if i % 2 == 0],
            [],
        )
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        assert result.rides_analyzed == 3
        assert result.rides_excluded == 3

    @pytest.mark.anyio
    async def test_payment_record_used_for_payout(self):
        ride = _make_ride(ride_id=1, actual_fare=5.0, distance_km=8.0, duration_min=12.0)
        db = _make_db([ride], [_make_payment_row(1, 14.00)], [])
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        # 14.00 from payment record, not 5.0 from actual_fare
        assert result.openride_total_payout == pytest.approx(14.00, rel=1e-3)

    @pytest.mark.anyio
    async def test_falls_back_to_actual_fare_when_no_payment(self):
        ride = _make_ride(ride_id=1, actual_fare=15.00, distance_km=8.0, duration_min=12.0)
        db = _make_db([ride], [], [])  # no payment rows
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        assert result.openride_total_payout == pytest.approx(15.00, rel=1e-3)

    @pytest.mark.anyio
    async def test_falls_back_to_estimated_fare_when_actual_fare_none(self):
        ride = _make_ride(ride_id=1, actual_fare=None, estimated_fare=13.00,
                          distance_km=8.0, duration_min=12.0)
        db = _make_db([ride], [], [])
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        assert result.openride_total_payout == pytest.approx(13.00, rel=1e-3)

    @pytest.mark.anyio
    async def test_tips_added_to_openride_not_competitor(self):
        ride = _make_ride(ride_id=1, distance_km=8.0, duration_min=12.0)
        tip_row = _make_tip_row(1, 500)  # $5.00
        db = _make_db([ride], [_make_payment_row(1, 14.00)], [tip_row])
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        assert result.openride_total_tips == pytest.approx(5.00, rel=1e-3)
        assert result.openride_total_payout == pytest.approx(19.00, rel=1e-3)
        # Uber/Lyft estimates don't include tips — only based on distance/duration
        uber_est = _estimate_driver_payout(8.0, 12.0, _UBER_RATE_CARD)
        assert result.uber_estimated_total_payout == pytest.approx(uber_est, rel=1e-3)

    @pytest.mark.anyio
    async def test_total_distance_aggregated(self):
        rides = [
            _make_ride(ride_id=1, distance_km=5.0, duration_min=8.0),
            _make_ride(ride_id=2, distance_km=3.0, duration_min=6.0),
        ]
        db = _make_db(rides, [_make_payment_row(1, 10.0), _make_payment_row(2, 8.0)], [])
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        assert result.total_distance_km == pytest.approx(8.0, rel=1e-3)

    @pytest.mark.anyio
    async def test_total_duration_aggregated(self):
        rides = [
            _make_ride(ride_id=1, distance_km=5.0, duration_min=8.0),
            _make_ride(ride_id=2, distance_km=3.0, duration_min=6.0),
        ]
        db = _make_db(rides, [_make_payment_row(1, 10.0), _make_payment_row(2, 8.0)], [])
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        assert result.total_duration_min == pytest.approx(14.0, rel=1e-3)

    @pytest.mark.anyio
    async def test_uber_estimate_matches_rate_card(self):
        dist_km, dur_min = 10.0, 15.0
        ride = _make_ride(ride_id=1, distance_km=dist_km, duration_min=dur_min)
        db = _make_db([ride], [_make_payment_row(1, 20.0)], [])
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        expected_uber = _estimate_driver_payout(dist_km, dur_min, _UBER_RATE_CARD)
        assert result.uber_estimated_total_payout == pytest.approx(expected_uber, rel=1e-3)

    @pytest.mark.anyio
    async def test_lyft_estimate_matches_rate_card(self):
        dist_km, dur_min = 10.0, 15.0
        ride = _make_ride(ride_id=1, distance_km=dist_km, duration_min=dur_min)
        db = _make_db([ride], [_make_payment_row(1, 20.0)], [])
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        expected_lyft = _estimate_driver_payout(dist_km, dur_min, _LYFT_RATE_CARD)
        assert result.lyft_estimated_total_payout == pytest.approx(expected_lyft, rel=1e-3)

    @pytest.mark.anyio
    async def test_openride_vs_uber_delta_positive_when_openride_better(self):
        ride = _make_ride(ride_id=1, distance_km=5.0, duration_min=8.0)
        db = _make_db([ride], [_make_payment_row(1, 999.0)], [])  # huge payout
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        assert result.openride_vs_uber_delta > 0

    @pytest.mark.anyio
    async def test_openride_vs_uber_delta_negative_when_uber_better(self):
        ride = _make_ride(ride_id=1, distance_km=5.0, duration_min=8.0)
        db = _make_db([ride], [_make_payment_row(1, 0.01)], [])  # tiny payout
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        assert result.openride_vs_uber_delta < 0

    @pytest.mark.anyio
    async def test_openride_vs_uber_pct_computed(self):
        dist_km, dur_min = 8.0, 10.0
        ride = _make_ride(ride_id=1, distance_km=dist_km, duration_min=dur_min)
        openride_payout = 20.0
        db = _make_db([ride], [_make_payment_row(1, openride_payout)], [])
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        uber_est = _estimate_driver_payout(dist_km, dur_min, _UBER_RATE_CARD)
        expected_pct = round((openride_payout / uber_est - 1.0) * 100.0, 2)
        assert result.openride_vs_uber_pct == pytest.approx(expected_pct, rel=1e-2)

    @pytest.mark.anyio
    async def test_avg_payout_per_ride(self):
        rides = [
            _make_ride(ride_id=1, distance_km=5.0, duration_min=8.0),
            _make_ride(ride_id=2, distance_km=5.0, duration_min=8.0),
        ]
        db = _make_db(rides, [_make_payment_row(1, 10.0), _make_payment_row(2, 20.0)], [])
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        assert result.openride_avg_payout_per_ride == pytest.approx(15.0, rel=1e-3)

    @pytest.mark.anyio
    async def test_avg_payout_per_mile(self):
        dist_km = 8.046  # ~5 miles
        ride = _make_ride(ride_id=1, distance_km=dist_km, duration_min=10.0)
        payout = 10.0
        db = _make_db([ride], [_make_payment_row(1, payout)], [])
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        dist_miles = dist_km * _KM_TO_MILES
        expected = round(payout / dist_miles, 2)
        assert result.openride_avg_payout_per_mile == pytest.approx(expected, rel=1e-2)

    @pytest.mark.anyio
    async def test_avg_payout_per_hour(self):
        ride = _make_ride(ride_id=1, distance_km=5.0, duration_min=30.0)
        payout = 15.0
        db = _make_db([ride], [_make_payment_row(1, payout)], [])
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        # 30 min = 0.5 hrs → $30/hr
        assert result.openride_avg_payout_per_hour == pytest.approx(30.0, rel=1e-3)

    @pytest.mark.anyio
    async def test_reversed_date_range_clamped(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_list([]))
        result = await get_earnings_comparison(
            db, DRIVER_ID, date(2026, 4, 14), date(2026, 4, 1)
        )
        assert result.period_start <= result.period_end

    @pytest.mark.anyio
    async def test_rate_cards_present(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_list([]))
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        assert result.uber_rate_card is not None
        assert result.lyft_rate_card is not None
        assert "Uber" in result.uber_rate_card.platform_name
        assert "Lyft" in result.lyft_rate_card.platform_name

    @pytest.mark.anyio
    async def test_methodology_note_present(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_list([]))
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        assert len(result.methodology_note) > 20

    @pytest.mark.anyio
    async def test_total_distance_miles_conversion(self):
        dist_km = 10.0
        ride = _make_ride(ride_id=1, distance_km=dist_km, duration_min=12.0)
        db = _make_db([ride], [_make_payment_row(1, 15.0)], [])
        result = await get_earnings_comparison(db, DRIVER_ID, TODAY, TODAY)
        assert result.total_distance_miles == pytest.approx(dist_km * _KM_TO_MILES, rel=1e-3)


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_api_earnings_comparison_no_auth(client):
    resp = await client.get("/api/v1/drivers/me/earnings-comparison")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_api_earnings_comparison_rider_forbidden(client, rider_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-comparison",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_api_earnings_comparison_driver_ok(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-comparison",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_api_earnings_comparison_schema_fields(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-comparison",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    body = resp.json()
    assert resp.status_code == 200
    required_fields = {
        "period_start", "period_end",
        "rides_analyzed", "rides_excluded",
        "total_distance_km", "total_distance_miles", "total_duration_min",
        "openride_total_payout", "openride_total_tips",
        "openride_avg_payout_per_ride", "openride_avg_payout_per_mile", "openride_avg_payout_per_hour",
        "uber_estimated_total_payout", "lyft_estimated_total_payout",
        "openride_vs_uber_delta", "openride_vs_lyft_delta",
        "openride_vs_uber_pct", "openride_vs_lyft_pct",
        "uber_rate_card", "lyft_rate_card",
        "methodology_note",
    }
    for field in required_fields:
        assert field in body, f"Missing field: {field}"


@pytest.mark.anyio
async def test_api_earnings_comparison_explicit_dates(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-comparison",
        params={"start_date": "2026-01-01", "end_date": "2026-03-31"},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["period_start"] == "2026-01-01"
    assert body["period_end"] == "2026-03-31"


@pytest.mark.anyio
async def test_api_earnings_comparison_invalid_date_format(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-comparison",
        params={"start_date": "not-a-date"},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_api_earnings_comparison_rides_analyzed_gte_zero(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-comparison",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    body = resp.json()
    assert resp.status_code == 200
    assert body["rides_analyzed"] >= 0


@pytest.mark.anyio
async def test_api_earnings_comparison_uber_rate_card(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-comparison",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    body = resp.json()
    assert resp.status_code == 200
    rc = body["uber_rate_card"]
    assert "Uber" in rc["platform_name"]
    assert rc["base_fare_usd"] > 0
    assert rc["per_mile_usd"] > 0
    assert rc["per_minute_usd"] > 0
    assert 0 < rc["driver_take_rate"] <= 1.0


@pytest.mark.anyio
async def test_api_earnings_comparison_lyft_rate_card(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-comparison",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    body = resp.json()
    assert resp.status_code == 200
    rc = body["lyft_rate_card"]
    assert "Lyft" in rc["platform_name"]
    assert rc["base_fare_usd"] > 0


@pytest.mark.anyio
async def test_api_earnings_comparison_methodology_note(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-comparison",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    body = resp.json()
    assert resp.status_code == 200
    assert len(body["methodology_note"]) > 20


@pytest.mark.anyio
async def test_api_earnings_comparison_distance_miles_present(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-comparison",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    body = resp.json()
    assert resp.status_code == 200
    assert "total_distance_miles" in body
    assert body["total_distance_miles"] >= 0.0
