"""Tests for driver performance trends endpoint and service function.

Service unit tests (AsyncMock DB — no live database required):
  1.  get_performance_trends — empty history returns empty list
  2.  get_performance_trends — single period has None for all delta fields
  3.  get_performance_trends — two periods: first has None deltas, second has correct deltas
  4.  get_performance_trends — score_delta is positive when score improves
  5.  get_performance_trends — score_delta is negative when score falls
  6.  get_performance_trends — rating_delta is positive when rating improves
  7.  get_performance_trends — rating_delta is negative when rating falls
  8.  get_performance_trends — acceptance_delta is positive when acceptance improves
  9.  get_performance_trends — acceptance_delta is negative when acceptance falls
  10. get_performance_trends — periods are ordered oldest-to-newest
  11. get_performance_trends — twelve-period history produces twelve dicts
  12. get_performance_trends — only first period has None deltas in multi-period history
  13. get_performance_trends — returned dicts include all required keys
  14. get_performance_trends — delta values are rounded to 4 decimal places
  15. get_performance_trends — calls get_snapshot_history with correct driver_id and weeks
  16. get_performance_trends — all snapshot fields propagated correctly into period dict
  17. get_performance_trends — score_delta=0.0 when two identical consecutive periods

API endpoint tests (patched service — no live DB required):
  18. GET /api/v1/drivers/{id}/performance/trends — 403 with no auth
  19. GET /api/v1/drivers/{id}/performance/trends — 403 when rider accesses endpoint
  20. GET /api/v1/drivers/{id}/performance/trends — 403 when driver accesses another driver's trends
  21. GET /api/v1/drivers/{id}/performance/trends — 200 when driver accesses their own trends
  22. GET /api/v1/drivers/{id}/performance/trends — 200 when admin accesses any driver's trends
  23. GET /api/v1/drivers/{id}/performance/trends — response contains driver_id field
  24. GET /api/v1/drivers/{id}/performance/trends — response contains weeks_requested field
  25. GET /api/v1/drivers/{id}/performance/trends — response contains periods list
  26. GET /api/v1/drivers/{id}/performance/trends — weeks_requested reflects query param
  27. GET /api/v1/drivers/{id}/performance/trends — 422 when weeks < 1
  28. GET /api/v1/drivers/{id}/performance/trends — 422 when weeks > 52
  29. GET /api/v1/drivers/{id}/performance/trends — empty periods list when no history
  30. GET /api/v1/drivers/{id}/performance/trends — delta fields present in period objects
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_performance import DriverPerformanceSnapshot
from app.services.driver_performance import get_performance_trends


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(
    *,
    id: int = 1,
    driver_id: int = 10,
    period_start: date = date(2026, 4, 7),
    period_end: date = date(2026, 4, 13),
    performance_score: float = 80.0,
    score_tier: str = "gold",
    acceptance_rate: float = 0.90,
    completion_rate: float = 0.95,
    cancellation_rate: float = 0.05,
    average_rider_rating: float = 4.5,
    total_rides_completed: int = 40,
    total_rides_offered: int = 45,
    on_time_rate: float = 0.88,
) -> MagicMock:
    snap = MagicMock(spec=DriverPerformanceSnapshot)
    snap.id = id
    snap.driver_id = driver_id
    snap.period_start = period_start
    snap.period_end = period_end
    snap.performance_score = performance_score
    snap.score_tier = score_tier
    snap.acceptance_rate = acceptance_rate
    snap.completion_rate = completion_rate
    snap.cancellation_rate = cancellation_rate
    snap.average_rider_rating = average_rider_rating
    snap.total_rides_completed = total_rides_completed
    snap.total_rides_offered = total_rides_offered
    snap.on_time_rate = on_time_rate
    return snap


def _make_db(snapshots: list) -> AsyncMock:
    """Return a mock DB whose execute() yields the given snapshots."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = snapshots
    db.execute = AsyncMock(return_value=result)
    return db


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


class TestGetPerformanceTrendsService:
    @pytest.mark.asyncio
    async def test_empty_history_returns_empty_list(self):
        db = _make_db([])
        periods = await get_performance_trends(db, driver_id=10, weeks=12)
        assert periods == []

    @pytest.mark.asyncio
    async def test_single_period_has_none_deltas(self):
        snap = _make_snapshot(id=1, period_start=date(2026, 4, 7))
        db = _make_db([snap])
        periods = await get_performance_trends(db, driver_id=10, weeks=1)
        assert len(periods) == 1
        assert periods[0]["score_delta"] is None
        assert periods[0]["rating_delta"] is None
        assert periods[0]["acceptance_delta"] is None

    @pytest.mark.asyncio
    async def test_two_periods_first_has_none_deltas(self):
        # Service returns newest-first; second snap is newer
        snap_old = _make_snapshot(id=1, period_start=date(2026, 3, 31), performance_score=75.0)
        snap_new = _make_snapshot(id=2, period_start=date(2026, 4, 7), performance_score=80.0)
        # DB returns newest-first (service query ordering)
        db = _make_db([snap_new, snap_old])
        periods = await get_performance_trends(db, driver_id=10, weeks=2)
        assert len(periods) == 2
        assert periods[0]["score_delta"] is None
        assert periods[0]["rating_delta"] is None
        assert periods[0]["acceptance_delta"] is None

    @pytest.mark.asyncio
    async def test_two_periods_second_has_correct_score_delta(self):
        snap_old = _make_snapshot(id=1, period_start=date(2026, 3, 31), performance_score=75.0)
        snap_new = _make_snapshot(id=2, period_start=date(2026, 4, 7), performance_score=80.0)
        db = _make_db([snap_new, snap_old])
        periods = await get_performance_trends(db, driver_id=10, weeks=2)
        assert periods[1]["score_delta"] == pytest.approx(5.0, abs=0.001)

    @pytest.mark.asyncio
    async def test_score_delta_positive_when_score_improves(self):
        snap_old = _make_snapshot(id=1, period_start=date(2026, 3, 31), performance_score=70.0)
        snap_new = _make_snapshot(id=2, period_start=date(2026, 4, 7), performance_score=85.0)
        db = _make_db([snap_new, snap_old])
        periods = await get_performance_trends(db, driver_id=10, weeks=2)
        assert periods[1]["score_delta"] > 0

    @pytest.mark.asyncio
    async def test_score_delta_negative_when_score_falls(self):
        snap_old = _make_snapshot(id=1, period_start=date(2026, 3, 31), performance_score=90.0)
        snap_new = _make_snapshot(id=2, period_start=date(2026, 4, 7), performance_score=75.0)
        db = _make_db([snap_new, snap_old])
        periods = await get_performance_trends(db, driver_id=10, weeks=2)
        assert periods[1]["score_delta"] < 0

    @pytest.mark.asyncio
    async def test_rating_delta_positive_when_rating_improves(self):
        snap_old = _make_snapshot(id=1, period_start=date(2026, 3, 31), average_rider_rating=4.2)
        snap_new = _make_snapshot(id=2, period_start=date(2026, 4, 7), average_rider_rating=4.7)
        db = _make_db([snap_new, snap_old])
        periods = await get_performance_trends(db, driver_id=10, weeks=2)
        assert periods[1]["rating_delta"] > 0

    @pytest.mark.asyncio
    async def test_rating_delta_negative_when_rating_falls(self):
        snap_old = _make_snapshot(id=1, period_start=date(2026, 3, 31), average_rider_rating=4.8)
        snap_new = _make_snapshot(id=2, period_start=date(2026, 4, 7), average_rider_rating=4.1)
        db = _make_db([snap_new, snap_old])
        periods = await get_performance_trends(db, driver_id=10, weeks=2)
        assert periods[1]["rating_delta"] < 0

    @pytest.mark.asyncio
    async def test_acceptance_delta_positive_when_acceptance_improves(self):
        snap_old = _make_snapshot(id=1, period_start=date(2026, 3, 31), acceptance_rate=0.75)
        snap_new = _make_snapshot(id=2, period_start=date(2026, 4, 7), acceptance_rate=0.90)
        db = _make_db([snap_new, snap_old])
        periods = await get_performance_trends(db, driver_id=10, weeks=2)
        assert periods[1]["acceptance_delta"] > 0

    @pytest.mark.asyncio
    async def test_acceptance_delta_negative_when_acceptance_falls(self):
        snap_old = _make_snapshot(id=1, period_start=date(2026, 3, 31), acceptance_rate=0.95)
        snap_new = _make_snapshot(id=2, period_start=date(2026, 4, 7), acceptance_rate=0.80)
        db = _make_db([snap_new, snap_old])
        periods = await get_performance_trends(db, driver_id=10, weeks=2)
        assert periods[1]["acceptance_delta"] < 0

    @pytest.mark.asyncio
    async def test_periods_ordered_oldest_to_newest(self):
        # DB returns newest-first; service must reverse
        snap_newest = _make_snapshot(id=3, period_start=date(2026, 4, 14))
        snap_middle = _make_snapshot(id=2, period_start=date(2026, 4, 7))
        snap_oldest = _make_snapshot(id=1, period_start=date(2026, 3, 31))
        db = _make_db([snap_newest, snap_middle, snap_oldest])
        periods = await get_performance_trends(db, driver_id=10, weeks=3)
        dates = [p["period_start"] for p in periods]
        assert dates == sorted(dates)

    @pytest.mark.asyncio
    async def test_twelve_period_history_produces_twelve_dicts(self):
        from datetime import timedelta
        base = date(2025, 12, 1)
        snaps = [
            _make_snapshot(id=i, period_start=base + timedelta(weeks=i))
            for i in range(12)
        ]
        snaps_newest_first = list(reversed(snaps))
        db = _make_db(snaps_newest_first)
        periods = await get_performance_trends(db, driver_id=10, weeks=12)
        assert len(periods) == 12

    @pytest.mark.asyncio
    async def test_only_first_period_has_none_deltas(self):
        from datetime import timedelta
        base = date(2026, 1, 5)
        snaps = [
            _make_snapshot(
                id=i,
                period_start=base + timedelta(weeks=i),
                performance_score=float(70 + i),
                average_rider_rating=4.0 + i * 0.05,
                acceptance_rate=0.80 + i * 0.01,
            )
            for i in range(4)
        ]
        db = _make_db(list(reversed(snaps)))
        periods = await get_performance_trends(db, driver_id=10, weeks=4)
        # Only first period has None deltas
        assert periods[0]["score_delta"] is None
        for p in periods[1:]:
            assert p["score_delta"] is not None
            assert p["rating_delta"] is not None
            assert p["acceptance_delta"] is not None

    @pytest.mark.asyncio
    async def test_returned_dicts_include_all_required_keys(self):
        snap = _make_snapshot()
        db = _make_db([snap])
        periods = await get_performance_trends(db, driver_id=10, weeks=1)
        required_keys = {
            "period_start",
            "period_end",
            "performance_score",
            "score_tier",
            "acceptance_rate",
            "completion_rate",
            "cancellation_rate",
            "average_rider_rating",
            "total_rides_completed",
            "total_rides_offered",
            "score_delta",
            "rating_delta",
            "acceptance_delta",
        }
        assert required_keys.issubset(set(periods[0].keys()))

    @pytest.mark.asyncio
    async def test_delta_values_rounded_to_4_decimal_places(self):
        snap_old = _make_snapshot(
            id=1,
            period_start=date(2026, 3, 31),
            performance_score=75.123456789,
            average_rider_rating=4.123456789,
            acceptance_rate=0.823456789,
        )
        snap_new = _make_snapshot(
            id=2,
            period_start=date(2026, 4, 7),
            performance_score=80.987654321,
            average_rider_rating=4.567890123,
            acceptance_rate=0.912345678,
        )
        db = _make_db([snap_new, snap_old])
        periods = await get_performance_trends(db, driver_id=10, weeks=2)
        second = periods[1]
        for key in ("score_delta", "rating_delta", "acceptance_delta"):
            value = second[key]
            assert value == round(value, 4), f"{key} not rounded to 4dp: {value}"

    @pytest.mark.asyncio
    async def test_calls_get_snapshot_history_with_correct_args(self):
        with patch(
            "app.services.driver_performance.get_snapshot_history",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_history:
            db = AsyncMock()
            await get_performance_trends(db, driver_id=42, weeks=8)
            mock_history.assert_called_once_with(db, driver_id=42, limit=8)

    @pytest.mark.asyncio
    async def test_snapshot_fields_propagated_correctly(self):
        snap = _make_snapshot(
            performance_score=88.5,
            score_tier="gold",
            acceptance_rate=0.92,
            completion_rate=0.97,
            cancellation_rate=0.03,
            average_rider_rating=4.7,
            total_rides_completed=55,
            total_rides_offered=60,
            period_start=date(2026, 4, 7),
            period_end=date(2026, 4, 13),
        )
        db = _make_db([snap])
        periods = await get_performance_trends(db, driver_id=10, weeks=1)
        p = periods[0]
        assert p["performance_score"] == 88.5
        assert p["score_tier"] == "gold"
        assert p["acceptance_rate"] == 0.92
        assert p["completion_rate"] == 0.97
        assert p["cancellation_rate"] == 0.03
        assert p["average_rider_rating"] == 4.7
        assert p["total_rides_completed"] == 55
        assert p["total_rides_offered"] == 60
        assert p["period_start"] == date(2026, 4, 7)
        assert p["period_end"] == date(2026, 4, 13)

    @pytest.mark.asyncio
    async def test_score_delta_zero_when_consecutive_periods_identical(self):
        snap_old = _make_snapshot(id=1, period_start=date(2026, 3, 31), performance_score=80.0)
        snap_new = _make_snapshot(id=2, period_start=date(2026, 4, 7), performance_score=80.0)
        db = _make_db([snap_new, snap_old])
        periods = await get_performance_trends(db, driver_id=10, weeks=2)
        assert periods[1]["score_delta"] == 0.0


# ---------------------------------------------------------------------------
# API endpoint tests (patched service)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestPerformanceTrendsEndpoint:
    def _make_trend_periods(self):
        return [
            {
                "period_start": date(2026, 3, 31),
                "period_end": date(2026, 4, 6),
                "performance_score": 78.5,
                "score_tier": "gold",
                "acceptance_rate": 0.88,
                "completion_rate": 0.95,
                "cancellation_rate": 0.05,
                "average_rider_rating": 4.4,
                "total_rides_completed": 38,
                "total_rides_offered": 43,
                "score_delta": None,
                "rating_delta": None,
                "acceptance_delta": None,
            },
            {
                "period_start": date(2026, 4, 7),
                "period_end": date(2026, 4, 13),
                "performance_score": 82.0,
                "score_tier": "gold",
                "acceptance_rate": 0.91,
                "completion_rate": 0.96,
                "cancellation_rate": 0.04,
                "average_rider_rating": 4.6,
                "total_rides_completed": 42,
                "total_rides_offered": 46,
                "score_delta": 3.5,
                "rating_delta": 0.2,
                "acceptance_delta": 0.03,
            },
        ]

    async def test_unauthenticated_returns_403(self, client, driver_user):
        resp = await client.get(f"/api/v1/drivers/{driver_user.id}/performance/trends")
        assert resp.status_code == 403

    async def test_rider_cannot_access_trends(self, client, driver_user, rider, rider_token):
        headers = {"Authorization": f"Bearer {rider_token}"}
        resp = await client.get(
            f"/api/v1/drivers/{driver_user.id}/performance/trends",
            headers=headers,
        )
        assert resp.status_code == 403

    async def test_driver_cannot_access_other_driver_trends(
        self, client, driver_user, driver_token
    ):
        other_driver_id = driver_user.id + 999
        headers = {"Authorization": f"Bearer {driver_token}"}
        with patch(
            "app.api.v1.driver_performance.get_performance_trends",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await client.get(
                f"/api/v1/drivers/{other_driver_id}/performance/trends",
                headers=headers,
            )
        assert resp.status_code == 403

    async def test_driver_can_access_own_trends(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        periods = self._make_trend_periods()
        with patch(
            "app.api.v1.driver_performance.get_performance_trends",
            new_callable=AsyncMock,
            return_value=periods,
        ):
            resp = await client.get(
                f"/api/v1/drivers/{driver_user.id}/performance/trends",
                headers=headers,
            )
        assert resp.status_code == 200

    async def test_admin_can_access_any_driver_trends(
        self, client, admin_user, admin_token, driver_user
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        periods = self._make_trend_periods()
        with patch(
            "app.api.v1.driver_performance.get_performance_trends",
            new_callable=AsyncMock,
            return_value=periods,
        ):
            resp = await client.get(
                f"/api/v1/drivers/{driver_user.id}/performance/trends",
                headers=headers,
            )
        assert resp.status_code == 200

    async def test_response_contains_driver_id(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        with patch(
            "app.api.v1.driver_performance.get_performance_trends",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await client.get(
                f"/api/v1/drivers/{driver_user.id}/performance/trends",
                headers=headers,
            )
        assert resp.json()["driver_id"] == driver_user.id

    async def test_response_contains_weeks_requested(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        with patch(
            "app.api.v1.driver_performance.get_performance_trends",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await client.get(
                f"/api/v1/drivers/{driver_user.id}/performance/trends?weeks=6",
                headers=headers,
            )
        assert resp.json()["weeks_requested"] == 6

    async def test_response_contains_periods_list(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        periods = self._make_trend_periods()
        with patch(
            "app.api.v1.driver_performance.get_performance_trends",
            new_callable=AsyncMock,
            return_value=periods,
        ):
            resp = await client.get(
                f"/api/v1/drivers/{driver_user.id}/performance/trends",
                headers=headers,
            )
        data = resp.json()
        assert "periods" in data
        assert isinstance(data["periods"], list)

    async def test_weeks_requested_reflects_query_param(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        with patch(
            "app.api.v1.driver_performance.get_performance_trends",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await client.get(
                f"/api/v1/drivers/{driver_user.id}/performance/trends?weeks=20",
                headers=headers,
            )
        assert resp.json()["weeks_requested"] == 20

    async def test_weeks_below_1_returns_422(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        resp = await client.get(
            f"/api/v1/drivers/{driver_user.id}/performance/trends?weeks=0",
            headers=headers,
        )
        assert resp.status_code == 422

    async def test_weeks_above_52_returns_422(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        resp = await client.get(
            f"/api/v1/drivers/{driver_user.id}/performance/trends?weeks=53",
            headers=headers,
        )
        assert resp.status_code == 422

    async def test_empty_periods_when_no_history(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        with patch(
            "app.api.v1.driver_performance.get_performance_trends",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await client.get(
                f"/api/v1/drivers/{driver_user.id}/performance/trends",
                headers=headers,
            )
        assert resp.json()["periods"] == []

    async def test_period_objects_contain_delta_fields(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        periods = self._make_trend_periods()
        with patch(
            "app.api.v1.driver_performance.get_performance_trends",
            new_callable=AsyncMock,
            return_value=periods,
        ):
            resp = await client.get(
                f"/api/v1/drivers/{driver_user.id}/performance/trends",
                headers=headers,
            )
        period_data = resp.json()["periods"]
        assert len(period_data) == 2
        first = period_data[0]
        assert "score_delta" in first
        assert "rating_delta" in first
        assert "acceptance_delta" in first
        # First period has null deltas
        assert first["score_delta"] is None
        assert first["rating_delta"] is None
        assert first["acceptance_delta"] is None
        # Second period has numeric deltas
        second = period_data[1]
        assert second["score_delta"] is not None
        assert second["rating_delta"] is not None
        assert second["acceptance_delta"] is not None
