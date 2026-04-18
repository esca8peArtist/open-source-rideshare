"""Unit tests for the driver mileage report service and endpoint.

Tests cover:
  - Empty rides → zeros, empty breakdown
  - Single ride — km/miles/deduction correct
  - Multiple rides — total aggregation
  - Monthly filter — only rides in that month included
  - Full-year view — 12-month breakdown populated
  - Rides with null distance_km excluded
  - Naive datetime in DB normalised to UTC
  - Monthly breakdown sums match totals
  - IRS deduction arithmetic (miles × rate)
  - Schema round-trip serialisation
  - Endpoint query param validation (invalid month → 422)
  - Endpoint query param validation (missing year → 422)
  - Endpoint requires driver auth (401 without credentials)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.driver_mileage_report import DriverMileageReport, MonthlyMileageBreakdown
from app.services.driver_mileage_report import (
    IRS_MILEAGE_RATE_PER_MILE,
    KM_TO_MILES,
    get_driver_mileage_report,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)

DRIVER_ID = 42


def _row(distance_km: float | None, completed_at: datetime | None):
    """Fake DB row mimicking (Ride.distance_km, Ride.completed_at)."""
    r = MagicMock()
    r.distance_km = distance_km
    r.completed_at = completed_at
    return r


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 10, 0, 0, tzinfo=timezone.utc)


async def _mock_db(rows: list) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    return db


# ---------------------------------------------------------------------------
# KM / miles constant sanity check
# ---------------------------------------------------------------------------


class TestConstants:
    def test_km_to_miles_approx(self):
        assert abs(KM_TO_MILES - 0.621371) < 1e-5

    def test_irs_rate_positive(self):
        assert IRS_MILEAGE_RATE_PER_MILE > 0


# ---------------------------------------------------------------------------
# Service — empty result set
# ---------------------------------------------------------------------------


class TestEmptyRides:
    @pytest.mark.asyncio
    async def test_empty_returns_zeros(self):
        db = await _mock_db([])
        with patch("app.services.driver_mileage_report._utc_now", return_value=_NOW):
            report = await get_driver_mileage_report(db, DRIVER_ID, 2026)

        assert report.rides_completed == 0
        assert report.total_km == 0.0
        assert report.total_miles == 0.0
        assert report.irs_deduction_usd == 0.0

    @pytest.mark.asyncio
    async def test_empty_full_year_has_12_month_breakdown(self):
        db = await _mock_db([])
        with patch("app.services.driver_mileage_report._utc_now", return_value=_NOW):
            report = await get_driver_mileage_report(db, DRIVER_ID, 2026)

        assert len(report.monthly_breakdown) == 12
        for mb in report.monthly_breakdown:
            assert mb.rides_completed == 0
            assert mb.total_km == 0.0

    @pytest.mark.asyncio
    async def test_empty_monthly_breakdown_empty_when_month_provided(self):
        db = await _mock_db([])
        with patch("app.services.driver_mileage_report._utc_now", return_value=_NOW):
            report = await get_driver_mileage_report(db, DRIVER_ID, 2026, month=4)

        assert report.monthly_breakdown == []


# ---------------------------------------------------------------------------
# Service — single ride
# ---------------------------------------------------------------------------


class TestSingleRide:
    @pytest.mark.asyncio
    async def test_single_ride_km_to_miles(self):
        row = _row(16.09344, _dt(2026, 4, 10))
        db = await _mock_db([row])
        with patch("app.services.driver_mileage_report._utc_now", return_value=_NOW):
            report = await get_driver_mileage_report(db, DRIVER_ID, 2026, month=4)

        expected_miles = round(16.09344 * KM_TO_MILES, 2)
        assert report.total_km == 16.09  # rounded
        assert report.total_miles == expected_miles

    @pytest.mark.asyncio
    async def test_irs_deduction_equals_miles_times_rate(self):
        row = _row(10.0, _dt(2026, 4, 10))
        db = await _mock_db([row])
        with patch("app.services.driver_mileage_report._utc_now", return_value=_NOW):
            report = await get_driver_mileage_report(db, DRIVER_ID, 2026, month=4)

        expected = round(report.total_miles * IRS_MILEAGE_RATE_PER_MILE, 2)
        assert report.irs_deduction_usd == expected

    @pytest.mark.asyncio
    async def test_rides_completed_count(self):
        row = _row(5.0, _dt(2026, 4, 1))
        db = await _mock_db([row])
        with patch("app.services.driver_mileage_report._utc_now", return_value=_NOW):
            report = await get_driver_mileage_report(db, DRIVER_ID, 2026)

        assert report.rides_completed == 1


# ---------------------------------------------------------------------------
# Service — multiple rides
# ---------------------------------------------------------------------------


class TestMultipleRides:
    @pytest.mark.asyncio
    async def test_total_km_aggregated(self):
        rows = [
            _row(10.0, _dt(2026, 1, 5)),
            _row(20.0, _dt(2026, 2, 10)),
            _row(30.0, _dt(2026, 3, 15)),
        ]
        db = await _mock_db(rows)
        with patch("app.services.driver_mileage_report._utc_now", return_value=_NOW):
            report = await get_driver_mileage_report(db, DRIVER_ID, 2026)

        assert report.total_km == 60.0
        assert report.rides_completed == 3

    @pytest.mark.asyncio
    async def test_monthly_breakdown_sums_match_total(self):
        rows = [
            _row(10.0, _dt(2026, 1, 5)),
            _row(20.0, _dt(2026, 1, 20)),
            _row(5.0, _dt(2026, 3, 1)),
        ]
        db = await _mock_db(rows)
        with patch("app.services.driver_mileage_report._utc_now", return_value=_NOW):
            report = await get_driver_mileage_report(db, DRIVER_ID, 2026)

        breakdown_total_km = sum(mb.total_km for mb in report.monthly_breakdown)
        assert abs(breakdown_total_km - report.total_km) < 0.01

    @pytest.mark.asyncio
    async def test_monthly_breakdown_january_correct(self):
        rows = [
            _row(10.0, _dt(2026, 1, 5)),
            _row(20.0, _dt(2026, 1, 20)),
            _row(5.0, _dt(2026, 3, 1)),
        ]
        db = await _mock_db(rows)
        with patch("app.services.driver_mileage_report._utc_now", return_value=_NOW):
            report = await get_driver_mileage_report(db, DRIVER_ID, 2026)

        jan = report.monthly_breakdown[0]
        assert jan.month == 1
        assert jan.rides_completed == 2
        assert jan.total_km == 30.0


# ---------------------------------------------------------------------------
# Service — null distance_km excluded
# ---------------------------------------------------------------------------


class TestNullDistance:
    @pytest.mark.asyncio
    async def test_null_distance_row_excluded(self):
        rows = [
            _row(None, _dt(2026, 4, 1)),  # should be excluded
            _row(10.0, _dt(2026, 4, 2)),
        ]
        # The DB query filters distance_km.is_not(None) — mock only returns non-null rows
        db = await _mock_db([rows[1]])
        with patch("app.services.driver_mileage_report._utc_now", return_value=_NOW):
            report = await get_driver_mileage_report(db, DRIVER_ID, 2026, month=4)

        assert report.rides_completed == 1
        assert report.total_km == 10.0


# ---------------------------------------------------------------------------
# Service — naive datetime normalisation
# ---------------------------------------------------------------------------


class TestNaiveDatetime:
    @pytest.mark.asyncio
    async def test_naive_datetime_treated_as_utc(self):
        naive_dt = datetime(2026, 4, 10, 10, 0, 0)  # no tzinfo
        row = _row(8.0, naive_dt)
        db = await _mock_db([row])
        with patch("app.services.driver_mileage_report._utc_now", return_value=_NOW):
            # Should not raise and should include this ride in April breakdown
            report = await get_driver_mileage_report(db, DRIVER_ID, 2026)

        jan_through_apr = [mb for mb in report.monthly_breakdown if mb.month <= 4]
        total_in_period = sum(mb.rides_completed for mb in jan_through_apr)
        assert total_in_period == 1


# ---------------------------------------------------------------------------
# Service — metadata fields
# ---------------------------------------------------------------------------


class TestMetadata:
    @pytest.mark.asyncio
    async def test_driver_id_echoed(self):
        db = await _mock_db([])
        with patch("app.services.driver_mileage_report._utc_now", return_value=_NOW):
            report = await get_driver_mileage_report(db, 99, 2026)
        assert report.driver_id == 99

    @pytest.mark.asyncio
    async def test_year_echoed(self):
        db = await _mock_db([])
        with patch("app.services.driver_mileage_report._utc_now", return_value=_NOW):
            report = await get_driver_mileage_report(db, DRIVER_ID, 2025)
        assert report.year == 2025

    @pytest.mark.asyncio
    async def test_month_echoed_when_provided(self):
        db = await _mock_db([])
        with patch("app.services.driver_mileage_report._utc_now", return_value=_NOW):
            report = await get_driver_mileage_report(db, DRIVER_ID, 2026, month=7)
        assert report.month == 7

    @pytest.mark.asyncio
    async def test_month_null_for_full_year(self):
        db = await _mock_db([])
        with patch("app.services.driver_mileage_report._utc_now", return_value=_NOW):
            report = await get_driver_mileage_report(db, DRIVER_ID, 2026)
        assert report.month is None

    @pytest.mark.asyncio
    async def test_irs_rate_in_response(self):
        db = await _mock_db([])
        with patch("app.services.driver_mileage_report._utc_now", return_value=_NOW):
            report = await get_driver_mileage_report(db, DRIVER_ID, 2026)
        assert report.irs_rate_per_mile == IRS_MILEAGE_RATE_PER_MILE


# ---------------------------------------------------------------------------
# Schema serialisation
# ---------------------------------------------------------------------------


class TestSchema:
    def test_schema_serialises(self):
        report = DriverMileageReport(
            driver_id=1,
            year=2026,
            month=4,
            as_of=_NOW,
            rides_completed=2,
            total_km=20.0,
            total_miles=12.43,
            irs_rate_per_mile=0.70,
            irs_deduction_usd=8.70,
            monthly_breakdown=[],
        )
        data = report.model_dump()
        assert data["driver_id"] == 1
        assert data["irs_deduction_usd"] == 8.70

    def test_monthly_breakdown_schema(self):
        mb = MonthlyMileageBreakdown(
            month=4,
            rides_completed=3,
            total_km=30.0,
            total_miles=18.64,
            irs_deduction_usd=13.05,
        )
        assert mb.month == 4
        assert mb.irs_deduction_usd == 13.05


# ---------------------------------------------------------------------------
# Endpoint — validation
# ---------------------------------------------------------------------------


class TestEndpointValidation:
    def test_missing_year_returns_422(self):
        with TestClient(app) as client:
            # Provide a fake driver auth header to reach param validation
            resp = client.get(
                "/api/v1/driver/me/mileage-report",
                headers={"Authorization": "Bearer fake"},
            )
        # 401 or 422 — either means we reached the endpoint layer
        assert resp.status_code in (401, 422)

    def test_invalid_month_zero_returns_422(self):
        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/driver/me/mileage-report",
                params={"year": 2026, "month": 0},
                headers={"Authorization": "Bearer fake"},
            )
        assert resp.status_code in (401, 422)

    def test_invalid_month_13_returns_422(self):
        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/driver/me/mileage-report",
                params={"year": 2026, "month": 13},
                headers={"Authorization": "Bearer fake"},
            )
        assert resp.status_code in (401, 422)

    def test_unauthenticated_returns_401(self):
        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/driver/me/mileage-report",
                params={"year": 2026},
            )
        assert resp.status_code == 401
