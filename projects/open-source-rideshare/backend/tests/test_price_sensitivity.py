"""Tests for price sensitivity analytics.

Covers:
- get_price_sensitivity_report: empty DB, only price cancellations, mixed data,
  rate calculation, daily breakdown merge, days validation
- GET /admin/surge-analytics/price-sensitivity: days validation 422, response shape,
  empty period, populated period
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.surge_analytics import (
    DailyPriceSensitivity,
    PriceSensitivityReport,
    get_price_sensitivity_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scalar_result(value) -> MagicMock:
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _fetchall_result(rows: list) -> MagicMock:
    r = MagicMock()
    r.fetchall.return_value = rows
    return r


def _row(**kwargs):
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


def _iter_result(rows: list) -> MagicMock:
    """Mock db.execute result that is directly iterable."""
    r = MagicMock()
    r.__iter__ = MagicMock(return_value=iter(rows))
    return r


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


class TestGetPriceSensitivityReport:
    @pytest.mark.anyio
    async def test_all_zeros_when_no_data(self):
        """Empty database returns zeros and empty daily breakdown."""
        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                # Scalar count queries (total, price, surge total)
                return _scalar_result(0)
            # Iterable day-bucketed queries
            return _iter_result([])

        db = AsyncMock()
        db.execute = _execute

        report = await get_price_sensitivity_report(db, days=30)

        assert report.period_days == 30
        assert report.total_cancellations == 0
        assert report.price_cancellations == 0
        assert report.price_cancellation_rate == 0.0
        assert report.total_surge_events == 0
        assert report.daily_breakdown == []

    @pytest.mark.anyio
    async def test_price_cancellation_rate_calculated_correctly(self):
        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalar_result(20)  # total cancellations
            if call_count == 2:
                return _scalar_result(5)   # price cancellations
            if call_count == 3:
                return _scalar_result(10)  # total surge events
            return _iter_result([])        # empty daily queries

        db = AsyncMock()
        db.execute = _execute

        report = await get_price_sensitivity_report(db, days=7)

        assert report.total_cancellations == 20
        assert report.price_cancellations == 5
        assert report.price_cancellation_rate == pytest.approx(0.25, rel=1e-4)
        assert report.total_surge_events == 10

    @pytest.mark.anyio
    async def test_zero_rate_when_no_cancellations(self):
        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return _scalar_result(0)
            if call_count == 3:
                return _scalar_result(50)  # surge events even though no cancels
            return _iter_result([])

        db = AsyncMock()
        db.execute = _execute

        report = await get_price_sensitivity_report(db, days=30)

        assert report.price_cancellation_rate == 0.0

    @pytest.mark.anyio
    async def test_daily_breakdown_merge(self):
        """Days appearing in only one table are included with zeros in the other."""
        from datetime import datetime, timezone

        dt_a = datetime(2026, 4, 15, tzinfo=timezone.utc)
        dt_b = datetime(2026, 4, 16, tzinfo=timezone.utc)

        cancel_rows = [
            _row(day=dt_a, total_cancels=10, price_cancels=3),
        ]
        surge_rows = [
            _row(day=dt_b, surge_cnt=7),
        ]

        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalar_result(10)  # total cancels
            if call_count == 2:
                return _scalar_result(3)   # price cancels
            if call_count == 3:
                return _scalar_result(7)   # total surge events
            if call_count == 4:
                return _iter_result(cancel_rows)
            return _iter_result(surge_rows)

        db = AsyncMock()
        db.execute = _execute

        report = await get_price_sensitivity_report(db, days=30)

        assert len(report.daily_breakdown) == 2
        day_a = next(d for d in report.daily_breakdown if d.date == "2026-04-15")
        day_b = next(d for d in report.daily_breakdown if d.date == "2026-04-16")

        assert day_a.total_cancellations == 10
        assert day_a.price_cancellations == 3
        assert day_a.surge_events == 0
        assert day_a.price_cancellation_rate == pytest.approx(0.3, rel=1e-4)

        assert day_b.total_cancellations == 0
        assert day_b.price_cancellations == 0
        assert day_b.surge_events == 7
        assert day_b.price_cancellation_rate == 0.0

    @pytest.mark.anyio
    async def test_daily_breakdown_both_tables_same_day(self):
        """Day present in both tables merges correctly."""
        from datetime import datetime, timezone

        dt = datetime(2026, 4, 17, tzinfo=timezone.utc)

        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalar_result(8)
            if call_count == 2:
                return _scalar_result(4)
            if call_count == 3:
                return _scalar_result(15)
            if call_count == 4:
                return _iter_result([_row(day=dt, total_cancels=8, price_cancels=4)])
            return _iter_result([_row(day=dt, surge_cnt=15)])

        db = AsyncMock()
        db.execute = _execute

        report = await get_price_sensitivity_report(db, days=30)

        assert len(report.daily_breakdown) == 1
        day = report.daily_breakdown[0]
        assert day.date == "2026-04-17"
        assert day.total_cancellations == 8
        assert day.price_cancellations == 4
        assert day.surge_events == 15
        assert day.price_cancellation_rate == pytest.approx(0.5, rel=1e-4)


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------


class TestPriceSensitivityEndpoint:
    @pytest.mark.anyio
    async def test_returns_422_for_days_below_one(self):
        from fastapi import HTTPException

        from app.api.v1.surge_zones import surge_analytics_price_sensitivity

        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await surge_analytics_price_sensitivity(days=0, db=db)

        assert exc_info.value.status_code == 422

    @pytest.mark.anyio
    async def test_returns_422_for_days_above_365(self):
        from fastapi import HTTPException

        from app.api.v1.surge_zones import surge_analytics_price_sensitivity

        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await surge_analytics_price_sensitivity(days=366, db=db)

        assert exc_info.value.status_code == 422

    @pytest.mark.anyio
    async def test_returns_empty_report_shape(self):
        from app.api.v1.surge_zones import surge_analytics_price_sensitivity

        empty_report = PriceSensitivityReport(
            period_days=30,
            total_cancellations=0,
            price_cancellations=0,
            price_cancellation_rate=0.0,
            total_surge_events=0,
            daily_breakdown=[],
        )

        db = AsyncMock()

        with patch(
            "app.api.v1.surge_zones.get_price_sensitivity_report",
            new=AsyncMock(return_value=empty_report),
        ):
            resp = await surge_analytics_price_sensitivity(days=30, db=db)

        assert resp.period_days == 30
        assert resp.total_cancellations == 0
        assert resp.price_cancellations == 0
        assert resp.price_cancellation_rate == 0.0
        assert resp.total_surge_events == 0
        assert resp.daily_breakdown == []

    @pytest.mark.anyio
    async def test_returns_populated_report(self):
        from app.api.v1.surge_zones import surge_analytics_price_sensitivity

        report = PriceSensitivityReport(
            period_days=7,
            total_cancellations=50,
            price_cancellations=12,
            price_cancellation_rate=0.24,
            total_surge_events=30,
            daily_breakdown=[
                DailyPriceSensitivity(
                    date="2026-04-17",
                    total_cancellations=10,
                    price_cancellations=3,
                    surge_events=5,
                    price_cancellation_rate=0.3,
                ),
            ],
        )

        db = AsyncMock()

        with patch(
            "app.api.v1.surge_zones.get_price_sensitivity_report",
            new=AsyncMock(return_value=report),
        ):
            resp = await surge_analytics_price_sensitivity(days=7, db=db)

        assert resp.period_days == 7
        assert resp.total_cancellations == 50
        assert resp.price_cancellations == 12
        assert resp.price_cancellation_rate == pytest.approx(0.24)
        assert resp.total_surge_events == 30
        assert len(resp.daily_breakdown) == 1

        day = resp.daily_breakdown[0]
        assert day.date == "2026-04-17"
        assert day.total_cancellations == 10
        assert day.price_cancellations == 3
        assert day.surge_events == 5
        assert day.price_cancellation_rate == pytest.approx(0.3)

    @pytest.mark.anyio
    async def test_passes_days_param_to_service(self):
        from app.api.v1.surge_zones import surge_analytics_price_sensitivity

        empty_report = PriceSensitivityReport(
            period_days=14,
            total_cancellations=0,
            price_cancellations=0,
            price_cancellation_rate=0.0,
            total_surge_events=0,
            daily_breakdown=[],
        )

        mock_service = AsyncMock(return_value=empty_report)
        db = AsyncMock()

        with patch("app.api.v1.surge_zones.get_price_sensitivity_report", new=mock_service):
            await surge_analytics_price_sensitivity(days=14, db=db)

        mock_service.assert_called_once_with(db, days=14)

    @pytest.mark.anyio
    async def test_accepts_boundary_days_1(self):
        from app.api.v1.surge_zones import surge_analytics_price_sensitivity

        empty_report = PriceSensitivityReport(
            period_days=1,
            total_cancellations=0,
            price_cancellations=0,
            price_cancellation_rate=0.0,
            total_surge_events=0,
            daily_breakdown=[],
        )
        db = AsyncMock()

        with patch(
            "app.api.v1.surge_zones.get_price_sensitivity_report",
            new=AsyncMock(return_value=empty_report),
        ):
            resp = await surge_analytics_price_sensitivity(days=1, db=db)

        assert resp.period_days == 1

    @pytest.mark.anyio
    async def test_accepts_boundary_days_365(self):
        from app.api.v1.surge_zones import surge_analytics_price_sensitivity

        empty_report = PriceSensitivityReport(
            period_days=365,
            total_cancellations=0,
            price_cancellations=0,
            price_cancellation_rate=0.0,
            total_surge_events=0,
            daily_breakdown=[],
        )
        db = AsyncMock()

        with patch(
            "app.api.v1.surge_zones.get_price_sensitivity_report",
            new=AsyncMock(return_value=empty_report),
        ):
            resp = await surge_analytics_price_sensitivity(days=365, db=db)

        assert resp.period_days == 365
