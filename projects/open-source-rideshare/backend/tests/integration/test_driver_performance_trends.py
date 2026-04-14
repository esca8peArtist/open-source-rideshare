"""Integration tests for the driver performance trends endpoint.

These tests require a live PostgreSQL test database.  They are automatically
skipped when the database is not reachable (the shared ``setup_database``
fixture in conftest.py calls ``pytest.skip`` on connection failure).

Tests:
  1.  GET /api/v1/drivers/{id}/performance/trends — 403 when unauthenticated
  2.  GET /api/v1/drivers/{id}/performance/trends — 403 when rider token used
  3.  GET /api/v1/drivers/{id}/performance/trends — 403 when driver accesses another driver
  4.  GET /api/v1/drivers/{id}/performance/trends — 200 when driver accesses own trends
  5.  GET /api/v1/drivers/{id}/performance/trends — 200 when admin accesses any driver
  6.  GET /api/v1/drivers/{id}/performance/trends — response shape matches schema
  7.  GET /api/v1/drivers/{id}/performance/trends — periods list is empty when no snapshots exist
  8.  GET /api/v1/drivers/{id}/performance/trends — weeks_requested reflects requested value
  9.  GET /api/v1/drivers/{id}/performance/trends — default weeks is 12
  10. GET /api/v1/drivers/{id}/performance/trends — 422 for weeks=0
  11. GET /api/v1/drivers/{id}/performance/trends — 422 for weeks=53
  12. GET /api/v1/drivers/{id}/performance/trends — single snapshot has None deltas
  13. GET /api/v1/drivers/{id}/performance/trends — two snapshots produce correct deltas
  14. GET /api/v1/drivers/{id}/performance/trends — periods ordered oldest-to-newest
  15. GET /api/v1/drivers/{id}/performance/trends — only first period has None delta fields
"""
from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_performance import DriverPerformanceSnapshot
from app.models.user import User
from tests.conftest import auth_header

pytestmark = pytest.mark.integration


def _make_db_snapshot(
    driver_id: int,
    period_start: date,
    period_end: date,
    performance_score: float = 80.0,
    score_tier: str = "gold",
    acceptance_rate: float = 0.90,
    completion_rate: float = 0.95,
    cancellation_rate: float = 0.05,
    average_rider_rating: float = 4.5,
    total_rides_completed: int = 40,
    total_rides_offered: int = 45,
    total_rides_accepted: int = 43,
    total_rides_cancelled_by_driver: int = 2,
    on_time_rate: float = 0.88,
    total_rider_ratings: int = 20,
    total_complaints: int = 0,
    average_pickup_time_minutes: float = 3.5,
) -> DriverPerformanceSnapshot:
    return DriverPerformanceSnapshot(
        driver_id=driver_id,
        period_start=period_start,
        period_end=period_end,
        performance_score=performance_score,
        score_tier=score_tier,
        acceptance_rate=acceptance_rate,
        completion_rate=completion_rate,
        cancellation_rate=cancellation_rate,
        average_rider_rating=average_rider_rating,
        total_rides_completed=total_rides_completed,
        total_rides_offered=total_rides_offered,
        total_rides_accepted=total_rides_accepted,
        total_rides_cancelled_by_driver=total_rides_cancelled_by_driver,
        on_time_rate=on_time_rate,
        total_rider_ratings=total_rider_ratings,
        total_complaints=total_complaints,
        average_pickup_time_minutes=average_pickup_time_minutes,
    )


async def test_unauthenticated_returns_403(
    client: AsyncClient, driver_user: User
):
    resp = await client.get(f"/api/v1/drivers/{driver_user.id}/performance/trends")
    assert resp.status_code == 403


async def test_rider_returns_403(
    client: AsyncClient, driver_user: User, rider_token: str
):
    resp = await client.get(
        f"/api/v1/drivers/{driver_user.id}/performance/trends",
        headers=auth_header(rider_token),
    )
    assert resp.status_code == 403


async def test_driver_cannot_access_other_driver_trends(
    client: AsyncClient, driver_user: User, driver_token: str
):
    other_id = driver_user.id + 9999
    resp = await client.get(
        f"/api/v1/drivers/{other_id}/performance/trends",
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 403


async def test_driver_can_access_own_trends(
    client: AsyncClient, driver_user: User, driver_token: str
):
    resp = await client.get(
        f"/api/v1/drivers/{driver_user.id}/performance/trends",
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 200


async def test_admin_can_access_any_driver_trends(
    client: AsyncClient, driver_user: User, admin_token: str
):
    resp = await client.get(
        f"/api/v1/drivers/{driver_user.id}/performance/trends",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200


async def test_response_shape_matches_schema(
    client: AsyncClient, driver_user: User, driver_token: str
):
    resp = await client.get(
        f"/api/v1/drivers/{driver_user.id}/performance/trends",
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "driver_id" in data
    assert "weeks_requested" in data
    assert "periods" in data
    assert isinstance(data["periods"], list)


async def test_empty_periods_when_no_snapshots(
    client: AsyncClient, driver_user: User, driver_token: str
):
    resp = await client.get(
        f"/api/v1/drivers/{driver_user.id}/performance/trends",
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    assert resp.json()["periods"] == []


async def test_weeks_requested_reflects_query_param(
    client: AsyncClient, driver_user: User, driver_token: str
):
    resp = await client.get(
        f"/api/v1/drivers/{driver_user.id}/performance/trends?weeks=6",
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    assert resp.json()["weeks_requested"] == 6


async def test_default_weeks_is_12(
    client: AsyncClient, driver_user: User, driver_token: str
):
    resp = await client.get(
        f"/api/v1/drivers/{driver_user.id}/performance/trends",
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    assert resp.json()["weeks_requested"] == 12


async def test_weeks_0_returns_422(
    client: AsyncClient, driver_user: User, driver_token: str
):
    resp = await client.get(
        f"/api/v1/drivers/{driver_user.id}/performance/trends?weeks=0",
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 422


async def test_weeks_53_returns_422(
    client: AsyncClient, driver_user: User, driver_token: str
):
    resp = await client.get(
        f"/api/v1/drivers/{driver_user.id}/performance/trends?weeks=53",
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 422


async def test_single_snapshot_has_none_deltas(
    client: AsyncClient, db: AsyncSession, driver_user: User, driver_token: str
):
    snap = _make_db_snapshot(
        driver_id=driver_user.id,
        period_start=date(2026, 4, 7),
        period_end=date(2026, 4, 13),
        performance_score=80.0,
    )
    db.add(snap)
    await db.flush()

    resp = await client.get(
        f"/api/v1/drivers/{driver_user.id}/performance/trends",
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    periods = resp.json()["periods"]
    assert len(periods) == 1
    assert periods[0]["score_delta"] is None
    assert periods[0]["rating_delta"] is None
    assert periods[0]["acceptance_delta"] is None


async def test_two_snapshots_produce_correct_deltas(
    client: AsyncClient, db: AsyncSession, driver_user: User, driver_token: str
):
    snap_old = _make_db_snapshot(
        driver_id=driver_user.id,
        period_start=date(2026, 3, 31),
        period_end=date(2026, 4, 6),
        performance_score=75.0,
        average_rider_rating=4.3,
        acceptance_rate=0.85,
    )
    snap_new = _make_db_snapshot(
        driver_id=driver_user.id,
        period_start=date(2026, 4, 7),
        period_end=date(2026, 4, 13),
        performance_score=82.0,
        average_rider_rating=4.6,
        acceptance_rate=0.91,
    )
    db.add(snap_old)
    db.add(snap_new)
    await db.flush()

    resp = await client.get(
        f"/api/v1/drivers/{driver_user.id}/performance/trends",
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    periods = resp.json()["periods"]
    assert len(periods) == 2

    first = periods[0]
    assert first["score_delta"] is None

    second = periods[1]
    assert second["score_delta"] == pytest.approx(7.0, abs=0.001)
    assert second["rating_delta"] == pytest.approx(0.3, abs=0.001)
    assert second["acceptance_delta"] == pytest.approx(0.06, abs=0.001)


async def test_periods_ordered_oldest_to_newest(
    client: AsyncClient, db: AsyncSession, driver_user: User, driver_token: str
):
    snap1 = _make_db_snapshot(
        driver_id=driver_user.id,
        period_start=date(2026, 3, 24),
        period_end=date(2026, 3, 30),
    )
    snap2 = _make_db_snapshot(
        driver_id=driver_user.id,
        period_start=date(2026, 3, 31),
        period_end=date(2026, 4, 6),
    )
    snap3 = _make_db_snapshot(
        driver_id=driver_user.id,
        period_start=date(2026, 4, 7),
        period_end=date(2026, 4, 13),
    )
    db.add(snap1)
    db.add(snap2)
    db.add(snap3)
    await db.flush()

    resp = await client.get(
        f"/api/v1/drivers/{driver_user.id}/performance/trends",
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    periods = resp.json()["periods"]
    starts = [p["period_start"] for p in periods]
    assert starts == sorted(starts)


async def test_only_first_period_has_none_deltas(
    client: AsyncClient, db: AsyncSession, driver_user: User, driver_token: str
):
    for i in range(3):
        snap = _make_db_snapshot(
            driver_id=driver_user.id,
            period_start=date(2026, 3, 17 + i * 7),
            period_end=date(2026, 3, 23 + i * 7),
            performance_score=float(75 + i * 3),
        )
        db.add(snap)
    await db.flush()

    resp = await client.get(
        f"/api/v1/drivers/{driver_user.id}/performance/trends",
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    periods = resp.json()["periods"]
    assert len(periods) == 3
    assert periods[0]["score_delta"] is None
    for p in periods[1:]:
        assert p["score_delta"] is not None
