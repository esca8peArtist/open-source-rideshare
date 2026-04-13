"""Tests for the driver performance scoring system.

Covers:
- compute_performance_score: pure function, all edge cases
- compute_score_tier: boundary values
- calculate_period_metrics: service unit tests (mocked DB)
- create_or_update_snapshot: creation and idempotent update
- get_current_snapshot / get_snapshot_history: queries
- check_and_create_alerts: threshold logic, deduplication
- bulk_recalculate_all_drivers: happy path and error handling
- GET /drivers/me/performance              — driver self-view
- GET /drivers/me/performance/history      — driver history
- GET /admin/drivers/performance           — admin list, filters, sort
- GET /admin/drivers/{id}/performance      — admin single driver
- GET /admin/drivers/{id}/performance/history
- GET /admin/drivers/{id}/performance/alerts
- POST /admin/performance/recalculate
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.models.driver_performance import DriverPerformanceAlert, DriverPerformanceSnapshot
from app.models.ride import RideStatus
from app.services.driver_performance import (
    ALERT_HIGH_CANCELLATION,
    ALERT_LOW_ACCEPTANCE,
    ALERT_LOW_RATING,
    ALERT_LOW_SCORE,
    check_and_create_alerts,
    compute_performance_score,
    compute_score_tier,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_snapshot(**kwargs) -> DriverPerformanceSnapshot:
    """Build a DriverPerformanceSnapshot with sensible defaults."""
    defaults = dict(
        id=1,
        driver_id=10,
        period_start=date(2026, 4, 7),
        period_end=date(2026, 4, 13),
        total_rides_completed=50,
        total_rides_offered=60,
        total_rides_accepted=55,
        total_rides_cancelled_by_driver=5,
        acceptance_rate=0.90,
        completion_rate=0.95,
        cancellation_rate=0.09,
        average_pickup_time_minutes=3.0,
        on_time_rate=0.88,
        average_rider_rating=4.6,
        total_rider_ratings=50,
        total_complaints=0,
        performance_score=0.0,
        score_tier="bronze",
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    defaults.update(kwargs)
    snap = MagicMock(spec=DriverPerformanceSnapshot)
    for k, v in defaults.items():
        setattr(snap, k, v)
    return snap


# ---------------------------------------------------------------------------
# compute_performance_score — pure unit tests
# ---------------------------------------------------------------------------


class TestComputePerformanceScore:
    def test_perfect_driver_scores_100(self):
        snap = _make_snapshot(
            acceptance_rate=1.0,
            completion_rate=1.0,
            on_time_rate=1.0,
            average_rider_rating=5.0,
            total_rider_ratings=10,
            total_complaints=0,
        )
        score = compute_performance_score(snap)
        assert score == 100.0

    def test_zero_metrics_scores_zero(self):
        snap = _make_snapshot(
            acceptance_rate=0.0,
            completion_rate=0.0,
            on_time_rate=0.0,
            average_rider_rating=0.0,
            total_rider_ratings=10,
            total_complaints=0,
        )
        score = compute_performance_score(snap)
        assert score == 0.0

    def test_score_clamped_to_100_even_above_target(self):
        snap = _make_snapshot(
            acceptance_rate=1.5,  # above 100 %
            completion_rate=1.5,
            on_time_rate=1.5,
            average_rider_rating=5.0,
            total_rider_ratings=5,
            total_complaints=0,
        )
        score = compute_performance_score(snap)
        assert score <= 100.0

    def test_complaints_penalty_reduces_score(self):
        snap_clean = _make_snapshot(total_complaints=0)
        snap_complaints = _make_snapshot(total_complaints=2)
        assert compute_performance_score(snap_complaints) < compute_performance_score(snap_clean)

    def test_complaints_penalty_capped_at_30_points(self):
        snap_few = _make_snapshot(
            acceptance_rate=1.0,
            completion_rate=1.0,
            on_time_rate=1.0,
            average_rider_rating=5.0,
            total_rider_ratings=5,
            total_complaints=3,
        )
        snap_many = _make_snapshot(
            acceptance_rate=1.0,
            completion_rate=1.0,
            on_time_rate=1.0,
            average_rider_rating=5.0,
            total_rider_ratings=5,
            total_complaints=100,
        )
        # Both should produce the same score because the penalty is capped
        assert compute_performance_score(snap_few) == compute_performance_score(snap_many)

    def test_no_ratings_neutral_on_rating_component(self):
        """Drivers with no ratings yet should not be penalised."""
        snap_no_ratings = _make_snapshot(
            acceptance_rate=0.85,
            completion_rate=0.96,
            on_time_rate=0.87,
            average_rider_rating=0.0,
            total_rider_ratings=0,
            total_complaints=0,
        )
        snap_good_ratings = _make_snapshot(
            acceptance_rate=0.85,
            completion_rate=0.96,
            on_time_rate=0.87,
            average_rider_rating=4.5,
            total_rider_ratings=10,
            total_complaints=0,
        )
        score_no_ratings = compute_performance_score(snap_no_ratings)
        score_good_ratings = compute_performance_score(snap_good_ratings)
        # With no ratings the rating component is treated as 1.0 (neutral)
        assert score_no_ratings == score_good_ratings

    def test_score_between_0_and_100(self):
        snap = _make_snapshot(
            acceptance_rate=0.75,
            completion_rate=0.90,
            on_time_rate=0.80,
            average_rider_rating=4.2,
            total_rider_ratings=20,
            total_complaints=1,
        )
        score = compute_performance_score(snap)
        assert 0.0 <= score <= 100.0

    def test_partial_acceptance_rate(self):
        snap = _make_snapshot(
            acceptance_rate=0.80,   # exactly at target
            completion_rate=1.0,
            on_time_rate=1.0,
            average_rider_rating=5.0,
            total_rider_ratings=10,
            total_complaints=0,
        )
        score = compute_performance_score(snap)
        # acceptance component fully satisfied => should be 100
        assert score == 100.0

    def test_below_acceptance_target(self):
        snap = _make_snapshot(
            acceptance_rate=0.40,   # half of target
            completion_rate=1.0,
            on_time_rate=1.0,
            average_rider_rating=5.0,
            total_rider_ratings=5,
            total_complaints=0,
        )
        score = compute_performance_score(snap)
        # acceptance_norm = 0.5 * 0.25 * 100 = 12.5 pts lost
        assert score < 100.0
        assert score > 0.0

    def test_score_is_rounded_to_2dp(self):
        snap = _make_snapshot(
            acceptance_rate=0.83,
            completion_rate=0.93,
            on_time_rate=0.81,
            average_rider_rating=4.3,
            total_rider_ratings=7,
            total_complaints=0,
        )
        score = compute_performance_score(snap)
        assert score == round(score, 2)


# ---------------------------------------------------------------------------
# compute_score_tier — boundary tests
# ---------------------------------------------------------------------------


class TestComputeScoreTier:
    def test_below_60_is_bronze(self):
        assert compute_score_tier(59.9) == "bronze"

    def test_60_is_silver(self):
        assert compute_score_tier(60.0) == "silver"

    def test_74_9_is_silver(self):
        assert compute_score_tier(74.9) == "silver"

    def test_75_is_gold(self):
        assert compute_score_tier(75.0) == "gold"

    def test_89_9_is_gold(self):
        assert compute_score_tier(89.9) == "gold"

    def test_90_is_platinum(self):
        assert compute_score_tier(90.0) == "platinum"

    def test_100_is_platinum(self):
        assert compute_score_tier(100.0) == "platinum"

    def test_0_is_bronze(self):
        assert compute_score_tier(0.0) == "bronze"


# ---------------------------------------------------------------------------
# check_and_create_alerts — unit tests with mocked DB
# ---------------------------------------------------------------------------


class TestCheckAndCreateAlerts:
    def _make_db(self, existing_types: set[str] | None = None) -> AsyncMock:
        db = AsyncMock()
        existing = existing_types or set()
        rows = [(t,) for t in existing]
        result_mock = MagicMock()
        result_mock.all.return_value = rows
        db.execute = AsyncMock(return_value=result_mock)
        db.flush = AsyncMock()
        db.add = MagicMock()
        return db

    @pytest.mark.asyncio
    async def test_no_alerts_for_good_driver(self):
        snap = _make_snapshot(
            acceptance_rate=0.90,
            cancellation_rate=0.05,
            average_rider_rating=4.8,
            total_rider_ratings=30,
            performance_score=92.0,
        )
        db = self._make_db()
        alerts = await check_and_create_alerts(db, snap)
        assert alerts == []
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_low_acceptance_creates_alert(self):
        snap = _make_snapshot(
            acceptance_rate=0.60,  # below 0.70
            cancellation_rate=0.05,
            average_rider_rating=4.8,
            total_rider_ratings=10,
            performance_score=80.0,
        )
        db = self._make_db()
        alerts = await check_and_create_alerts(db, snap)
        types = [a.alert_type for a in alerts]
        assert "low_acceptance" in types

    @pytest.mark.asyncio
    async def test_high_cancellation_creates_alert(self):
        snap = _make_snapshot(
            acceptance_rate=0.85,
            cancellation_rate=0.25,  # above 0.20
            average_rider_rating=4.5,
            total_rider_ratings=10,
            performance_score=78.0,
        )
        db = self._make_db()
        alerts = await check_and_create_alerts(db, snap)
        types = [a.alert_type for a in alerts]
        assert "high_cancellation" in types

    @pytest.mark.asyncio
    async def test_low_rating_creates_alert(self):
        snap = _make_snapshot(
            acceptance_rate=0.85,
            cancellation_rate=0.10,
            average_rider_rating=3.0,  # below 3.5
            total_rider_ratings=10,
            performance_score=72.0,
        )
        db = self._make_db()
        alerts = await check_and_create_alerts(db, snap)
        types = [a.alert_type for a in alerts]
        assert "low_rating" in types

    @pytest.mark.asyncio
    async def test_no_low_rating_alert_when_no_ratings(self):
        snap = _make_snapshot(
            average_rider_rating=0.0,
            total_rider_ratings=0,  # no ratings — don't fire alert
            acceptance_rate=0.85,
            cancellation_rate=0.10,
            performance_score=80.0,
        )
        db = self._make_db()
        alerts = await check_and_create_alerts(db, snap)
        types = [a.alert_type for a in alerts]
        assert "low_rating" not in types

    @pytest.mark.asyncio
    async def test_low_score_creates_alert(self):
        snap = _make_snapshot(
            acceptance_rate=0.55,
            cancellation_rate=0.15,
            average_rider_rating=4.0,
            total_rider_ratings=10,
            performance_score=50.0,  # below 60
        )
        db = self._make_db()
        alerts = await check_and_create_alerts(db, snap)
        types = [a.alert_type for a in alerts]
        assert "low_score" in types

    @pytest.mark.asyncio
    async def test_duplicate_alerts_not_created(self):
        """If an unresolved alert of the same type already exists, skip it."""
        snap = _make_snapshot(
            acceptance_rate=0.60,
            cancellation_rate=0.05,
            average_rider_rating=4.8,
            total_rider_ratings=10,
            performance_score=80.0,
        )
        # Pretend low_acceptance already exists
        db = self._make_db(existing_types={"low_acceptance"})
        alerts = await check_and_create_alerts(db, snap)
        types = [a.alert_type for a in alerts]
        assert "low_acceptance" not in types

    @pytest.mark.asyncio
    async def test_multiple_alerts_at_once(self):
        snap = _make_snapshot(
            acceptance_rate=0.50,   # low_acceptance
            cancellation_rate=0.30,  # high_cancellation
            average_rider_rating=2.5,  # low_rating
            total_rider_ratings=10,
            performance_score=40.0,  # low_score
        )
        db = self._make_db()
        alerts = await check_and_create_alerts(db, snap)
        types = {a.alert_type for a in alerts}
        assert "low_acceptance" in types
        assert "high_cancellation" in types
        assert "low_rating" in types
        assert "low_score" in types


# ---------------------------------------------------------------------------
# Service integration — snapshot creation/update
# ---------------------------------------------------------------------------


class TestCreateOrUpdateSnapshot:
    @pytest.mark.asyncio
    async def test_creates_new_snapshot_when_none_exists(self):
        from app.services.driver_performance import create_or_update_snapshot

        db = AsyncMock()

        # First execute call: calculate_period_metrics rides query
        rides_result = MagicMock()
        rides_result.scalars.return_value.all.return_value = []

        # Second execute call: existing snapshot lookup
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None

        db.execute = AsyncMock(side_effect=[rides_result, existing_result])
        db.flush = AsyncMock()
        db.add = MagicMock()

        # db.refresh sets attributes on the object passed to it
        async def fake_refresh(obj):
            obj.performance_score = 0.0
            obj.score_tier = "bronze"

        db.refresh = AsyncMock(side_effect=fake_refresh)

        snap = await create_or_update_snapshot(
            db,
            driver_id=10,
            period_start=date(2026, 4, 7),
            period_end=date(2026, 4, 13),
        )
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_existing_snapshot(self):
        from app.services.driver_performance import create_or_update_snapshot

        db = AsyncMock()

        rides_result = MagicMock()
        rides_result.scalars.return_value.all.return_value = []

        existing_snap = _make_snapshot()
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = existing_snap

        db.execute = AsyncMock(side_effect=[rides_result, existing_result])
        db.flush = AsyncMock()

        async def fake_refresh(obj):
            pass

        db.refresh = AsyncMock(side_effect=fake_refresh)

        snap = await create_or_update_snapshot(
            db,
            driver_id=10,
            period_start=date(2026, 4, 7),
            period_end=date(2026, 4, 13),
        )
        # Should not call db.add — it updates existing
        db.add.assert_not_called()


class TestGetSnapshotQueries:
    @pytest.mark.asyncio
    async def test_get_current_snapshot_returns_none_when_empty(self):
        from app.services.driver_performance import get_current_snapshot

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        snap = await get_current_snapshot(db, driver_id=99)
        assert snap is None

    @pytest.mark.asyncio
    async def test_get_current_snapshot_returns_snapshot(self):
        from app.services.driver_performance import get_current_snapshot

        db = AsyncMock()
        expected = _make_snapshot()
        result = MagicMock()
        result.scalar_one_or_none.return_value = expected
        db.execute = AsyncMock(return_value=result)

        snap = await get_current_snapshot(db, driver_id=10)
        assert snap is expected

    @pytest.mark.asyncio
    async def test_get_snapshot_history_returns_list(self):
        from app.services.driver_performance import get_snapshot_history

        db = AsyncMock()
        snaps = [_make_snapshot(id=i) for i in range(3)]
        result = MagicMock()
        result.scalars.return_value.all.return_value = snaps
        db.execute = AsyncMock(return_value=result)

        history = await get_snapshot_history(db, driver_id=10, limit=12)
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_get_snapshot_history_empty(self):
        from app.services.driver_performance import get_snapshot_history

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        history = await get_snapshot_history(db, driver_id=99, limit=12)
        assert history == []


# ---------------------------------------------------------------------------
# bulk_recalculate_all_drivers
# ---------------------------------------------------------------------------


class TestBulkRecalculate:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_drivers(self):
        from app.services.driver_performance import bulk_recalculate_all_drivers

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        summary = await bulk_recalculate_all_drivers(db)
        assert summary["recalculated"] == 0
        assert summary["errors"] == 0

    @pytest.mark.asyncio
    async def test_counts_errors_on_failure(self):
        from app.services.driver_performance import bulk_recalculate_all_drivers

        db = AsyncMock()

        driver = MagicMock()
        driver.id = 7
        drivers_result = MagicMock()
        drivers_result.scalars.return_value.all.return_value = [driver]
        db.execute = AsyncMock(return_value=drivers_result)

        with patch(
            "app.services.driver_performance.create_or_update_snapshot",
            side_effect=Exception("DB error"),
        ):
            summary = await bulk_recalculate_all_drivers(db)

        assert summary["errors"] == 1
        assert summary["recalculated"] == 0
        assert len(summary["error_details"]) == 1


# ---------------------------------------------------------------------------
# HTTP endpoint tests — require live test DB (skip if unavailable)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestDriverSelfViewEndpoints:
    async def test_get_my_performance_requires_auth(self, client):
        resp = await client.get("/api/v1/drivers/me/performance")
        assert resp.status_code == 403

    async def test_get_my_performance_404_no_snapshot(
        self, client, driver_user, driver_token
    ):
        headers = {"Authorization": f"Bearer {driver_token}"}
        with patch(
            "app.api.v1.driver_performance.get_current_snapshot",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.get("/api/v1/drivers/me/performance", headers=headers)
        assert resp.status_code == 404

    async def test_get_my_performance_returns_scorecard(
        self, client, driver_user, driver_token
    ):
        snap = _make_snapshot(driver_id=driver_user.id)
        headers = {"Authorization": f"Bearer {driver_token}"}
        with patch(
            "app.api.v1.driver_performance.get_current_snapshot",
            new_callable=AsyncMock,
            return_value=snap,
        ):
            resp = await client.get("/api/v1/drivers/me/performance", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "performance_score" in data
        assert "score_tier" in data

    async def test_get_my_performance_history_empty(
        self, client, driver_user, driver_token
    ):
        headers = {"Authorization": f"Bearer {driver_token}"}
        with patch(
            "app.api.v1.driver_performance.get_snapshot_history",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await client.get(
                "/api/v1/drivers/me/performance/history", headers=headers
            )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_my_performance_history_returns_list(
        self, client, driver_user, driver_token
    ):
        snaps = [_make_snapshot(driver_id=driver_user.id, id=i) for i in range(3)]
        headers = {"Authorization": f"Bearer {driver_token}"}
        with patch(
            "app.api.v1.driver_performance.get_snapshot_history",
            new_callable=AsyncMock,
            return_value=snaps,
        ):
            resp = await client.get(
                "/api/v1/drivers/me/performance/history", headers=headers
            )
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    async def test_rider_cannot_access_driver_performance(
        self, client, rider, rider_token
    ):
        headers = {"Authorization": f"Bearer {rider_token}"}
        resp = await client.get("/api/v1/drivers/me/performance", headers=headers)
        assert resp.status_code == 403


@pytest.mark.anyio
class TestAdminPerformanceEndpoints:
    async def test_admin_list_requires_auth(self, client):
        resp = await client.get("/api/v1/admin/drivers/performance")
        assert resp.status_code == 403

    async def test_driver_cannot_access_admin_list(
        self, client, driver_user, driver_token
    ):
        headers = {"Authorization": f"Bearer {driver_token}"}
        resp = await client.get("/api/v1/admin/drivers/performance", headers=headers)
        assert resp.status_code == 403

    async def test_admin_list_returns_paginated_response(
        self, client, admin_user, admin_token
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        with patch(
            "app.api.v1.driver_performance.get_current_snapshot",
            new_callable=AsyncMock,
        ):
            resp = await client.get(
                "/api/v1/admin/drivers/performance", headers=headers
            )
        # The endpoint does its own DB query — just verify shape is correct
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data
        assert "limit" in data
        assert "offset" in data

    async def test_admin_list_invalid_sort_defaults_gracefully(
        self, client, admin_user, admin_token
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get(
            "/api/v1/admin/drivers/performance?sort_by=nonexistent",
            headers=headers,
        )
        assert resp.status_code == 200

    async def test_admin_get_driver_performance_404(
        self, client, admin_user, admin_token
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        with patch(
            "app.api.v1.driver_performance.get_current_snapshot",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.get(
                "/api/v1/admin/drivers/99999/performance", headers=headers
            )
        assert resp.status_code == 404

    async def test_admin_get_driver_performance_returns_snapshot(
        self, client, admin_user, admin_token, driver_user
    ):
        snap = _make_snapshot(driver_id=driver_user.id)
        headers = {"Authorization": f"Bearer {admin_token}"}
        with patch(
            "app.api.v1.driver_performance.get_current_snapshot",
            new_callable=AsyncMock,
            return_value=snap,
        ):
            resp = await client.get(
                f"/api/v1/admin/drivers/{driver_user.id}/performance",
                headers=headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "acceptance_rate" in data
        assert "total_complaints" in data

    async def test_admin_get_driver_history(
        self, client, admin_user, admin_token, driver_user
    ):
        snaps = [_make_snapshot(driver_id=driver_user.id, id=i) for i in range(5)]
        headers = {"Authorization": f"Bearer {admin_token}"}
        with patch(
            "app.api.v1.driver_performance.get_snapshot_history",
            new_callable=AsyncMock,
            return_value=snaps,
        ):
            resp = await client.get(
                f"/api/v1/admin/drivers/{driver_user.id}/performance/history",
                headers=headers,
            )
        assert resp.status_code == 200
        assert len(resp.json()) == 5

    async def test_admin_get_driver_alerts_empty(
        self, client, admin_user, admin_token, driver_user
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get(
            f"/api/v1/admin/drivers/{driver_user.id}/performance/alerts",
            headers=headers,
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_admin_recalculate_requires_admin(
        self, client, driver_user, driver_token
    ):
        headers = {"Authorization": f"Bearer {driver_token}"}
        resp = await client.post(
            "/api/v1/admin/performance/recalculate", headers=headers
        )
        assert resp.status_code == 403

    async def test_admin_recalculate_returns_counts(
        self, client, admin_user, admin_token
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        with patch(
            "app.api.v1.driver_performance.bulk_recalculate_all_drivers",
            new_callable=AsyncMock,
            return_value={"recalculated": 5, "errors": 0, "error_details": []},
        ):
            resp = await client.post(
                "/api/v1/admin/performance/recalculate", headers=headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["recalculated"] == 5
        assert data["errors"] == 0
        assert data["error_details"] == []

    async def test_admin_recalculate_reports_errors(
        self, client, admin_user, admin_token
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        with patch(
            "app.api.v1.driver_performance.bulk_recalculate_all_drivers",
            new_callable=AsyncMock,
            return_value={
                "recalculated": 3,
                "errors": 2,
                "error_details": ["driver_id=4: DB error", "driver_id=7: timeout"],
            },
        ):
            resp = await client.post(
                "/api/v1/admin/performance/recalculate", headers=headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["errors"] == 2
        assert len(data["error_details"]) == 2

    async def test_admin_list_with_tier_filter(
        self, client, admin_user, admin_token
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get(
            "/api/v1/admin/drivers/performance?tier=platinum",
            headers=headers,
        )
        assert resp.status_code == 200

    async def test_admin_list_with_score_range(
        self, client, admin_user, admin_token
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get(
            "/api/v1/admin/drivers/performance?min_score=70&max_score=90",
            headers=headers,
        )
        assert resp.status_code == 200

    async def test_admin_list_with_sort_by_acceptance(
        self, client, admin_user, admin_token
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get(
            "/api/v1/admin/drivers/performance?sort_by=acceptance_rate",
            headers=headers,
        )
        assert resp.status_code == 200

    async def test_admin_alerts_include_resolved(
        self, client, admin_user, admin_token, driver_user
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get(
            f"/api/v1/admin/drivers/{driver_user.id}/performance/alerts?include_resolved=true",
            headers=headers,
        )
        assert resp.status_code == 200

    async def test_admin_list_pagination(
        self, client, admin_user, admin_token
    ):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get(
            "/api/v1/admin/drivers/performance?limit=10&offset=0",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 10
        assert data["offset"] == 0
