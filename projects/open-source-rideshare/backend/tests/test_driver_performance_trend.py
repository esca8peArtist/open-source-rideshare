"""Tests for the driver performance trend analysis feature.

Covers:
- _metric_direction: pure function edge cases
- _compute_trend: direction logic, four-week avg, change values
- _score_velocity: linear regression slope correctness
- get_performance_trend: mocked DB — empty, single snapshot, multi-snapshot
- GET /drivers/me/performance/trend          — driver self-view endpoints
- GET /admin/drivers/{id}/performance/trend  — admin endpoints
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_performance import DriverPerformanceSnapshot
from app.services.driver_performance import (
    TARGET_ACCEPTANCE,
    TARGET_CANCELLATION_RATE,
    TARGET_COMPLETION,
    TARGET_ON_TIME,
    TARGET_RATING,
    _compute_trend,
    _metric_direction,
    _score_velocity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_snapshot(**kwargs) -> DriverPerformanceSnapshot:
    """Build a DriverPerformanceSnapshot MagicMock with sensible defaults."""
    defaults = dict(
        id=1,
        driver_id=10,
        period_start=date(2026, 4, 7),
        period_end=date(2026, 4, 13),
        total_rides_completed=50,
        total_rides_offered=60,
        total_rides_accepted=55,
        total_rides_cancelled_by_driver=5,
        total_no_shows=0,
        no_show_rate=0.0,
        acceptance_rate=0.90,
        completion_rate=0.96,
        cancellation_rate=0.08,
        average_pickup_time_minutes=3.0,
        on_time_rate=0.88,
        average_rider_rating=4.6,
        total_rider_ratings=50,
        total_complaints=0,
        performance_score=85.0,
        score_tier="gold",
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    defaults.update(kwargs)
    snap = MagicMock(spec=DriverPerformanceSnapshot)
    for k, v in defaults.items():
        setattr(snap, k, v)
    return snap


def _make_snapshots_series(scores: list[float]) -> list[DriverPerformanceSnapshot]:
    """Create a chronological series of snapshots with the given scores."""
    snaps = []
    base_date = date(2026, 1, 5)  # Monday
    for i, score in enumerate(scores):
        period_start = date(base_date.year, base_date.month, base_date.day)
        # Advance by i weeks
        from datetime import timedelta

        period_start = base_date + timedelta(weeks=i)
        snaps.append(
            _make_snapshot(
                id=i + 1,
                period_start=period_start,
                period_end=period_start + timedelta(days=6),
                performance_score=score,
                score_tier="gold" if score >= 75 else "silver",
                acceptance_rate=0.90,
                completion_rate=0.96,
                cancellation_rate=0.08,
                no_show_rate=0.0,
                total_no_shows=0,
                on_time_rate=0.88,
                average_rider_rating=4.6,
                total_rider_ratings=20,
            )
        )
    return snaps


# ---------------------------------------------------------------------------
# _metric_direction — pure unit tests
# ---------------------------------------------------------------------------


class TestMetricDirection:
    def test_unknown_when_no_previous(self):
        assert _metric_direction(0.9, None, True, 0.02) == "unknown"

    def test_improving_higher_is_better(self):
        assert _metric_direction(0.95, 0.90, True, 0.02) == "improving"

    def test_declining_higher_is_better(self):
        assert _metric_direction(0.85, 0.92, True, 0.02) == "declining"

    def test_stable_within_threshold_higher(self):
        assert _metric_direction(0.91, 0.90, True, 0.02) == "stable"

    def test_improving_lower_is_better(self):
        # cancellation_rate decreased — that is improving
        assert _metric_direction(0.05, 0.10, False, 0.01) == "improving"

    def test_declining_lower_is_better(self):
        # cancellation_rate increased — that is declining
        assert _metric_direction(0.15, 0.08, False, 0.01) == "declining"

    def test_stable_within_threshold_lower(self):
        assert _metric_direction(0.09, 0.08, False, 0.01) == "stable"

    def test_within_threshold_stable(self):
        # Change of 0.01 — below the 0.02 threshold, so stable
        assert _metric_direction(0.91, 0.90, True, 0.02) == "stable"

    def test_just_above_threshold_higher(self):
        assert _metric_direction(0.93, 0.90, True, 0.02) == "improving"

    def test_score_improving(self):
        # performance_score — threshold 1.0
        assert _metric_direction(82.0, 80.0, True, 1.0) == "improving"

    def test_score_stable(self):
        assert _metric_direction(80.5, 80.0, True, 1.0) == "stable"


# ---------------------------------------------------------------------------
# _compute_trend — unit tests
# ---------------------------------------------------------------------------


class TestComputeTrend:
    def test_empty_returns_unknown(self):
        result = _compute_trend([], True, 1.0)
        assert result["direction"] == "unknown"
        assert result["current"] == 0.0
        assert result["previous"] is None
        assert result["four_week_avg"] is None
        assert result["change_from_previous"] is None

    def test_single_value_unknown_direction(self):
        result = _compute_trend([80.0], True, 1.0)
        assert result["current"] == 80.0
        assert result["previous"] is None
        assert result["direction"] == "unknown"

    def test_two_values_improving(self):
        result = _compute_trend([75.0, 82.0], True, 1.0)
        assert result["current"] == 82.0
        assert result["previous"] == 75.0
        assert result["direction"] == "improving"
        assert result["change_from_previous"] == pytest.approx(7.0, abs=0.001)

    def test_two_values_declining(self):
        result = _compute_trend([85.0, 78.0], True, 1.0)
        assert result["direction"] == "declining"

    def test_two_values_stable(self):
        result = _compute_trend([80.0, 80.5], True, 1.0)
        assert result["direction"] == "stable"

    def test_four_week_avg_uses_last_four(self):
        # 8 values — avg should use only last 4
        values = [60.0, 65.0, 70.0, 75.0, 80.0, 82.0, 84.0, 86.0]
        result = _compute_trend(values, True, 1.0)
        expected_avg = (80.0 + 82.0 + 84.0 + 86.0) / 4
        assert result["four_week_avg"] == pytest.approx(expected_avg, abs=0.001)

    def test_four_week_avg_with_fewer_than_four(self):
        values = [80.0, 82.0]
        result = _compute_trend(values, True, 1.0)
        expected_avg = (80.0 + 82.0) / 2
        assert result["four_week_avg"] == pytest.approx(expected_avg, abs=0.001)

    def test_lower_is_better_cancellation_improving(self):
        result = _compute_trend([0.12, 0.08], False, 0.01)
        assert result["direction"] == "improving"

    def test_lower_is_better_cancellation_declining(self):
        result = _compute_trend([0.05, 0.15], False, 0.01)
        assert result["direction"] == "declining"

    def test_change_is_signed(self):
        result = _compute_trend([90.0, 80.0], True, 1.0)
        assert result["change_from_previous"] == pytest.approx(-10.0, abs=0.001)

    def test_current_is_last_value(self):
        result = _compute_trend([70.0, 75.0, 80.0], True, 1.0)
        assert result["current"] == 80.0
        assert result["previous"] == 75.0


# ---------------------------------------------------------------------------
# _score_velocity — unit tests
# ---------------------------------------------------------------------------


class TestScoreVelocity:
    def test_empty_returns_zero(self):
        assert _score_velocity([]) == 0.0

    def test_single_value_returns_zero(self):
        assert _score_velocity([80.0]) == 0.0

    def test_flat_line_returns_zero(self):
        assert _score_velocity([75.0, 75.0, 75.0, 75.0]) == 0.0

    def test_monotone_increasing(self):
        # [70, 72, 74, 76, 78] — slope = 2.0 points/week
        scores = [70.0 + 2 * i for i in range(5)]
        velocity = _score_velocity(scores)
        assert velocity == pytest.approx(2.0, abs=0.01)

    def test_monotone_decreasing(self):
        scores = [80.0 - 3 * i for i in range(4)]
        velocity = _score_velocity(scores)
        assert velocity == pytest.approx(-3.0, abs=0.01)

    def test_two_values_slope(self):
        # [70, 80] → slope = 10
        assert _score_velocity([70.0, 80.0]) == pytest.approx(10.0, abs=0.01)

    def test_positive_velocity_means_improving(self):
        scores = [60.0, 65.0, 70.0, 75.0]
        assert _score_velocity(scores) > 0

    def test_negative_velocity_means_declining(self):
        scores = [80.0, 75.0, 70.0, 65.0]
        assert _score_velocity(scores) < 0

    def test_noisy_upward_trend(self):
        # General trend up despite some noise
        scores = [70.0, 68.0, 72.0, 75.0, 73.0, 78.0]
        assert _score_velocity(scores) > 0

    def test_result_rounded_to_3dp(self):
        scores = [70.0, 71.0, 72.0]
        v = _score_velocity(scores)
        assert v == round(v, 3)


# ---------------------------------------------------------------------------
# get_performance_trend — service integration tests (mocked DB)
# ---------------------------------------------------------------------------


class TestGetPerformanceTrend:
    def _make_fleet_db(
        self, snapshots: list, fleet_scores: list[float] | None = None
    ) -> AsyncMock:
        """Build a mock DB returning the given snapshots and fleet scores."""
        db = AsyncMock()

        # First execute: snapshot history query
        snap_result = MagicMock()
        snap_result.scalars.return_value.all.return_value = list(reversed(snapshots))

        # Second execute: fleet scores query
        fleet_scores_list = fleet_scores if fleet_scores is not None else []
        fleet_result = MagicMock()
        fleet_result.all.return_value = [(s,) for s in fleet_scores_list]

        db.execute = AsyncMock(side_effect=[snap_result, fleet_result])
        return db

    @pytest.mark.asyncio
    async def test_no_snapshots_returns_zero_analyzed(self):
        from app.services.driver_performance import get_performance_trend

        db = self._make_fleet_db(snapshots=[], fleet_scores=[])
        result = await get_performance_trend(db, driver_id=99, weeks=8)

        assert result["snapshots_analyzed"] == 0
        assert result["overall_direction"] == "unknown"
        assert result["score_velocity"] == 0.0
        assert result["weekly_scores"] == []
        assert result["fleet_avg_score"] is None
        assert result["score_percentile"] is None

    @pytest.mark.asyncio
    async def test_single_snapshot_unknown_direction(self):
        from app.services.driver_performance import get_performance_trend

        snaps = _make_snapshots_series([82.0])
        db = self._make_fleet_db(snapshots=snaps, fleet_scores=[82.0, 78.0, 90.0])
        result = await get_performance_trend(db, driver_id=10, weeks=8)

        assert result["snapshots_analyzed"] == 1
        assert result["overall_direction"] == "unknown"
        assert result["performance_score"]["direction"] == "unknown"
        assert result["current_score"] == pytest.approx(82.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_improving_trend_detected(self):
        from app.services.driver_performance import get_performance_trend

        scores = [70.0, 73.0, 77.0, 81.0, 85.0]
        snaps = _make_snapshots_series(scores)
        db = self._make_fleet_db(snapshots=snaps, fleet_scores=[80.0, 75.0, 85.0])
        result = await get_performance_trend(db, driver_id=10, weeks=8)

        assert result["overall_direction"] == "improving"
        assert result["score_velocity"] > 0
        assert result["performance_score"]["direction"] == "improving"

    @pytest.mark.asyncio
    async def test_declining_trend_detected(self):
        from app.services.driver_performance import get_performance_trend

        scores = [90.0, 86.0, 82.0, 78.0, 74.0]
        snaps = _make_snapshots_series(scores)
        db = self._make_fleet_db(snapshots=snaps, fleet_scores=[80.0])
        result = await get_performance_trend(db, driver_id=10, weeks=8)

        assert result["overall_direction"] == "declining"
        assert result["score_velocity"] < 0

    @pytest.mark.asyncio
    async def test_stable_trend(self):
        from app.services.driver_performance import get_performance_trend

        scores = [80.0, 80.5, 80.2, 80.4, 80.1]
        snaps = _make_snapshots_series(scores)
        db = self._make_fleet_db(snapshots=snaps, fleet_scores=[80.0])
        result = await get_performance_trend(db, driver_id=10, weeks=8)

        assert result["overall_direction"] == "stable"

    @pytest.mark.asyncio
    async def test_fleet_comparison_computed(self):
        from app.services.driver_performance import get_performance_trend

        snaps = _make_snapshots_series([80.0, 82.0])
        # Fleet: 4 drivers with scores 70, 75, 80, 85 — this driver is at 82
        fleet_scores = [70.0, 75.0, 80.0, 85.0, 82.0]
        db = self._make_fleet_db(snapshots=snaps, fleet_scores=fleet_scores)
        result = await get_performance_trend(db, driver_id=10, weeks=8)

        assert result["fleet_avg_score"] is not None
        assert result["score_percentile"] is not None
        assert 0 <= result["score_percentile"] <= 100

    @pytest.mark.asyncio
    async def test_strengths_identified_for_good_driver(self):
        from app.services.driver_performance import get_performance_trend

        snaps = [
            _make_snapshot(
                acceptance_rate=0.95,   # above TARGET_ACCEPTANCE (0.80)
                completion_rate=0.98,   # above TARGET_COMPLETION (0.95)
                on_time_rate=0.90,      # above TARGET_ON_TIME (0.85)
                average_rider_rating=4.8,  # above TARGET_RATING (4.5)
                total_rider_ratings=30,
                cancellation_rate=0.05,  # below TARGET_CANCELLATION_RATE (0.10)
            )
        ]
        db = self._make_fleet_db(snapshots=snaps, fleet_scores=[85.0])
        result = await get_performance_trend(db, driver_id=10, weeks=8)

        assert "acceptance_rate" in result["strengths"]
        assert "completion_rate" in result["strengths"]
        assert "on_time_rate" in result["strengths"]
        assert "average_rider_rating" in result["strengths"]
        assert "cancellation_rate" in result["strengths"]
        assert result["improvement_areas"] == []

    @pytest.mark.asyncio
    async def test_improvement_areas_identified(self):
        from app.services.driver_performance import get_performance_trend

        snaps = [
            _make_snapshot(
                acceptance_rate=0.65,   # below target
                completion_rate=0.90,   # below target
                on_time_rate=0.75,      # below target
                average_rider_rating=3.8,   # below target
                total_rider_ratings=10,
                cancellation_rate=0.25,  # above target
            )
        ]
        db = self._make_fleet_db(snapshots=snaps, fleet_scores=[80.0])
        result = await get_performance_trend(db, driver_id=10, weeks=8)

        assert "acceptance_rate" in result["improvement_areas"]
        assert "completion_rate" in result["improvement_areas"]
        assert "on_time_rate" in result["improvement_areas"]
        assert "average_rider_rating" in result["improvement_areas"]
        assert "cancellation_rate" in result["improvement_areas"]

    @pytest.mark.asyncio
    async def test_no_rating_omitted_from_strengths_and_weaknesses(self):
        from app.services.driver_performance import get_performance_trend

        snaps = [
            _make_snapshot(
                average_rider_rating=0.0,
                total_rider_ratings=0,  # no ratings yet
                acceptance_rate=0.90,
                completion_rate=0.96,
                on_time_rate=0.88,
                cancellation_rate=0.05,
            )
        ]
        db = self._make_fleet_db(snapshots=snaps, fleet_scores=[80.0])
        result = await get_performance_trend(db, driver_id=10, weeks=8)

        assert "average_rider_rating" not in result["strengths"]
        assert "average_rider_rating" not in result["improvement_areas"]

    @pytest.mark.asyncio
    async def test_weekly_scores_ordered_oldest_to_newest(self):
        from app.services.driver_performance import get_performance_trend

        scores = [70.0, 75.0, 80.0]
        snaps = _make_snapshots_series(scores)
        db = self._make_fleet_db(snapshots=snaps, fleet_scores=[])
        result = await get_performance_trend(db, driver_id=10, weeks=8)

        assert len(result["weekly_scores"]) == 3
        point_scores = [p["performance_score"] for p in result["weekly_scores"]]
        assert point_scores == [70.0, 75.0, 80.0]

    @pytest.mark.asyncio
    async def test_weeks_param_limits_snapshots(self):
        from app.services.driver_performance import get_performance_trend

        # DB returns only 3 snapshots (simulating limit=3 being applied)
        snaps = _make_snapshots_series([80.0, 82.0, 84.0])
        db = self._make_fleet_db(snapshots=snaps, fleet_scores=[])
        result = await get_performance_trend(db, driver_id=10, weeks=3)

        assert result["weeks_requested"] == 3
        assert result["snapshots_analyzed"] == 3

    @pytest.mark.asyncio
    async def test_driver_id_in_response(self):
        from app.services.driver_performance import get_performance_trend

        db = self._make_fleet_db(snapshots=[], fleet_scores=[])
        result = await get_performance_trend(db, driver_id=42, weeks=8)
        assert result["driver_id"] == 42

    @pytest.mark.asyncio
    async def test_percentile_100_for_top_driver(self):
        from app.services.driver_performance import get_performance_trend

        snaps = _make_snapshots_series([95.0])
        # All fleet scores <= 95 → 100th percentile
        fleet = [70.0, 75.0, 80.0, 85.0, 90.0, 95.0]
        db = self._make_fleet_db(snapshots=snaps, fleet_scores=fleet)
        result = await get_performance_trend(db, driver_id=10, weeks=8)
        assert result["score_percentile"] == 100

    @pytest.mark.asyncio
    async def test_percentile_low_for_bottom_driver(self):
        from app.services.driver_performance import get_performance_trend

        snaps = _make_snapshots_series([55.0])
        fleet = [55.0, 70.0, 80.0, 90.0, 95.0]  # this driver is lowest
        db = self._make_fleet_db(snapshots=snaps, fleet_scores=fleet)
        result = await get_performance_trend(db, driver_id=10, weeks=8)
        # 1 out of 5 scores <= 55 → 20th percentile
        assert result["score_percentile"] == 20

    @pytest.mark.asyncio
    async def test_fleet_avg_computed_correctly(self):
        from app.services.driver_performance import get_performance_trend

        snaps = _make_snapshots_series([80.0])
        fleet = [70.0, 80.0, 90.0]  # avg = 80.0
        db = self._make_fleet_db(snapshots=snaps, fleet_scores=fleet)
        result = await get_performance_trend(db, driver_id=10, weeks=8)
        assert result["fleet_avg_score"] == pytest.approx(80.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_empty_fleet_gives_none_comparison(self):
        from app.services.driver_performance import get_performance_trend

        snaps = _make_snapshots_series([80.0])
        db = self._make_fleet_db(snapshots=snaps, fleet_scores=[])
        result = await get_performance_trend(db, driver_id=10, weeks=8)
        assert result["fleet_avg_score"] is None
        assert result["score_percentile"] is None


# ---------------------------------------------------------------------------
# HTTP endpoint tests — driver self-view
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestDriverTrendEndpoint:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/v1/drivers/me/performance/trend")
        assert resp.status_code == 403

    async def test_rider_cannot_access(self, client, rider, rider_token):
        headers = {"Authorization": f"Bearer {rider_token}"}
        resp = await client.get("/api/v1/drivers/me/performance/trend", headers=headers)
        assert resp.status_code == 403

    async def test_driver_gets_200(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        mock_data = _build_mock_trend_data(driver_id=driver_user.id)
        with patch(
            "app.api.v1.driver_performance.get_performance_trend",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            resp = await client.get(
                "/api/v1/drivers/me/performance/trend", headers=headers
            )
        assert resp.status_code == 200

    async def test_response_shape(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        mock_data = _build_mock_trend_data(driver_id=driver_user.id)
        with patch(
            "app.api.v1.driver_performance.get_performance_trend",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            resp = await client.get(
                "/api/v1/drivers/me/performance/trend", headers=headers
            )
        data = resp.json()
        assert "driver_id" in data
        assert "snapshots_analyzed" in data
        assert "overall_direction" in data
        assert "score_velocity" in data
        assert "current_score" in data
        assert "current_tier" in data
        assert "performance_score" in data
        assert "acceptance_rate" in data
        assert "completion_rate" in data
        assert "cancellation_rate" in data
        assert "on_time_rate" in data
        assert "average_rider_rating" in data
        assert "fleet_avg_score" in data
        assert "score_percentile" in data
        assert "strengths" in data
        assert "improvement_areas" in data
        assert "weekly_scores" in data

    async def test_metric_trend_shape(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        mock_data = _build_mock_trend_data(driver_id=driver_user.id)
        with patch(
            "app.api.v1.driver_performance.get_performance_trend",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            resp = await client.get(
                "/api/v1/drivers/me/performance/trend", headers=headers
            )
        perf = resp.json()["performance_score"]
        assert "current" in perf
        assert "previous" in perf
        assert "four_week_avg" in perf
        assert "direction" in perf
        assert "change_from_previous" in perf

    async def test_weeks_param_passed(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        mock_data = _build_mock_trend_data(driver_id=driver_user.id, weeks_requested=4)
        captured_weeks = {}

        async def fake_trend(db, driver_id, weeks=8):
            captured_weeks["weeks"] = weeks
            return mock_data

        with patch(
            "app.api.v1.driver_performance.get_performance_trend",
            side_effect=fake_trend,
        ):
            resp = await client.get(
                "/api/v1/drivers/me/performance/trend?weeks=4", headers=headers
            )
        assert resp.status_code == 200
        assert captured_weeks.get("weeks") == 4

    async def test_weeks_minimum_1(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        resp = await client.get(
            "/api/v1/drivers/me/performance/trend?weeks=0", headers=headers
        )
        assert resp.status_code == 422

    async def test_weeks_maximum_52(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        resp = await client.get(
            "/api/v1/drivers/me/performance/trend?weeks=53", headers=headers
        )
        assert resp.status_code == 422

    async def test_weeks_52_is_valid(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        mock_data = _build_mock_trend_data(driver_id=driver_user.id, weeks_requested=52)
        with patch(
            "app.api.v1.driver_performance.get_performance_trend",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            resp = await client.get(
                "/api/v1/drivers/me/performance/trend?weeks=52", headers=headers
            )
        assert resp.status_code == 200

    async def test_no_snapshots_returns_200_with_zero(
        self, client, driver_user, driver_token
    ):
        headers = {"Authorization": f"Bearer {driver_token}"}
        mock_data = _build_mock_trend_data(driver_id=driver_user.id, snapshots_analyzed=0)
        with patch(
            "app.api.v1.driver_performance.get_performance_trend",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            resp = await client.get(
                "/api/v1/drivers/me/performance/trend", headers=headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["snapshots_analyzed"] == 0

    async def test_weekly_scores_list(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        weekly = [
            {
                "period_start": "2026-04-07",
                "performance_score": 80.0,
                "score_tier": "gold",
                "rides_completed": 45,
            }
        ]
        mock_data = _build_mock_trend_data(
            driver_id=driver_user.id, weekly_scores=weekly
        )
        with patch(
            "app.api.v1.driver_performance.get_performance_trend",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            resp = await client.get(
                "/api/v1/drivers/me/performance/trend", headers=headers
            )
        assert resp.status_code == 200
        assert len(resp.json()["weekly_scores"]) == 1


# ---------------------------------------------------------------------------
# HTTP endpoint tests — admin view
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestAdminDriverTrendEndpoint:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/v1/admin/drivers/10/performance/trend")
        assert resp.status_code == 403

    async def test_driver_cannot_access(self, client, driver_user, driver_token):
        headers = {"Authorization": f"Bearer {driver_token}"}
        resp = await client.get(
            f"/api/v1/admin/drivers/{driver_user.id}/performance/trend",
            headers=headers,
        )
        assert resp.status_code == 403

    async def test_admin_gets_200(self, client, admin_user, admin_token, driver_user):
        headers = {"Authorization": f"Bearer {admin_token}"}
        mock_data = _build_mock_trend_data(driver_id=driver_user.id)
        with patch(
            "app.api.v1.driver_performance.get_performance_trend",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            resp = await client.get(
                f"/api/v1/admin/drivers/{driver_user.id}/performance/trend",
                headers=headers,
            )
        assert resp.status_code == 200

    async def test_admin_response_contains_driver_id(
        self, client, admin_user, admin_token, driver_user
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        mock_data = _build_mock_trend_data(driver_id=driver_user.id)
        with patch(
            "app.api.v1.driver_performance.get_performance_trend",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            resp = await client.get(
                f"/api/v1/admin/drivers/{driver_user.id}/performance/trend",
                headers=headers,
            )
        assert resp.status_code == 200
        assert "driver_id" in resp.json()

    async def test_admin_weeks_param(
        self, client, admin_user, admin_token, driver_user
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        captured = {}

        async def fake_trend(db, driver_id, weeks=8):
            captured["weeks"] = weeks
            return _build_mock_trend_data(driver_id=driver_id, weeks_requested=weeks)

        with patch(
            "app.api.v1.driver_performance.get_performance_trend",
            side_effect=fake_trend,
        ):
            resp = await client.get(
                f"/api/v1/admin/drivers/{driver_user.id}/performance/trend?weeks=12",
                headers=headers,
            )
        assert resp.status_code == 200
        assert captured.get("weeks") == 12

    async def test_admin_weeks_minimum(
        self, client, admin_user, admin_token, driver_user
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get(
            f"/api/v1/admin/drivers/{driver_user.id}/performance/trend?weeks=0",
            headers=headers,
        )
        assert resp.status_code == 422

    async def test_admin_weeks_maximum(
        self, client, admin_user, admin_token, driver_user
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get(
            f"/api/v1/admin/drivers/{driver_user.id}/performance/trend?weeks=53",
            headers=headers,
        )
        assert resp.status_code == 422

    async def test_admin_no_snapshots_returns_200(
        self, client, admin_user, admin_token, driver_user
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        mock_data = _build_mock_trend_data(driver_id=driver_user.id, snapshots_analyzed=0)
        with patch(
            "app.api.v1.driver_performance.get_performance_trend",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            resp = await client.get(
                f"/api/v1/admin/drivers/{driver_user.id}/performance/trend",
                headers=headers,
            )
        assert resp.status_code == 200

    async def test_admin_can_access_any_driver(
        self, client, admin_user, admin_token
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        mock_data = _build_mock_trend_data(driver_id=9999)
        with patch(
            "app.api.v1.driver_performance.get_performance_trend",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            resp = await client.get(
                "/api/v1/admin/drivers/9999/performance/trend", headers=headers
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Helper to build a complete mock trend response dict
# ---------------------------------------------------------------------------


def _empty_trend() -> dict:
    return {
        "current": 0.0,
        "previous": None,
        "four_week_avg": None,
        "direction": "unknown",
        "change_from_previous": None,
    }


def _build_mock_trend_data(
    driver_id: int = 10,
    weeks_requested: int = 8,
    snapshots_analyzed: int = 5,
    weekly_scores: list | None = None,
) -> dict:
    """Build a complete dict matching the PerformanceTrendResponse schema."""
    return {
        "driver_id": driver_id,
        "weeks_requested": weeks_requested,
        "snapshots_analyzed": snapshots_analyzed,
        "overall_direction": "improving",
        "score_velocity": 2.5,
        "current_score": 85.0,
        "current_tier": "gold",
        "performance_score": {
            "current": 85.0,
            "previous": 82.0,
            "four_week_avg": 81.5,
            "direction": "improving",
            "change_from_previous": 3.0,
        },
        "acceptance_rate": {
            "current": 0.90,
            "previous": 0.88,
            "four_week_avg": 0.87,
            "direction": "improving",
            "change_from_previous": 0.02,
        },
        "completion_rate": {
            "current": 0.96,
            "previous": 0.95,
            "four_week_avg": 0.95,
            "direction": "stable",
            "change_from_previous": 0.01,
        },
        "cancellation_rate": {
            "current": 0.08,
            "previous": 0.10,
            "four_week_avg": 0.09,
            "direction": "improving",
            "change_from_previous": -0.02,
        },
        "on_time_rate": {
            "current": 0.88,
            "previous": 0.86,
            "four_week_avg": 0.86,
            "direction": "improving",
            "change_from_previous": 0.02,
        },
        "average_rider_rating": {
            "current": 4.6,
            "previous": 4.5,
            "four_week_avg": 4.5,
            "direction": "improving",
            "change_from_previous": 0.1,
        },
        "fleet_avg_score": 78.0,
        "score_percentile": 72,
        "strengths": ["acceptance_rate", "completion_rate", "cancellation_rate"],
        "improvement_areas": [],
        "weekly_scores": weekly_scores
        if weekly_scores is not None
        else [
            {
                "period_start": "2026-03-10",
                "performance_score": 80.0,
                "score_tier": "gold",
                "rides_completed": 42,
            },
            {
                "period_start": "2026-03-17",
                "performance_score": 82.0,
                "score_tier": "gold",
                "rides_completed": 45,
            },
            {
                "period_start": "2026-03-24",
                "performance_score": 85.0,
                "score_tier": "gold",
                "rides_completed": 48,
            },
        ],
    }
