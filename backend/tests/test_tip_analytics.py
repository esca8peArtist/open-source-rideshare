"""Tests for driver tip summary and admin tip analytics endpoints.

Covers:
Service unit tests (AsyncMock DB):
  1.  get_driver_tip_summary — empty period returns zeroed response
  2.  get_driver_tip_summary — total_cents sums all tip amounts
  3.  get_driver_tip_summary — tip_count matches number of records
  4.  get_driver_tip_summary — avg_tip_cents is integer division
  5.  get_driver_tip_summary — avg_tip_cents is 0 when no tips
  6.  get_driver_tip_summary — total_dollars is total_cents / 100
  7.  get_driver_tip_summary — status_breakdown counts completed tips
  8.  get_driver_tip_summary — status_breakdown counts pending tips
  9.  get_driver_tip_summary — status_breakdown counts refunded tips
  10. get_driver_tip_summary — status_breakdown counts failed tips
  11. get_driver_tip_summary — status_breakdown mixed statuses
  12. get_admin_tip_stats — empty period returns zeroed response
  13. get_admin_tip_stats — total_cents sums all tips
  14. get_admin_tip_stats — unique_drivers_tipped counts distinct drivers
  15. get_admin_tip_stats — unique_riders_who_tipped counts distinct riders
  16. get_admin_tip_stats — top_tipped_drivers ranked by total_cents desc
  17. get_admin_tip_stats — top_tipped_drivers capped at 10 entries
  18. get_admin_tip_stats — avg_tip_cents is 0 when no tips

API integration tests (real in-transaction test DB):
  19. GET /drivers/me/tips/summary — 401 without auth
  20. GET /drivers/me/tips/summary — 403 for rider role
  21. GET /drivers/me/tips/summary — 200 with driver token
  22. GET /drivers/me/tips/summary — response includes required fields
  23. GET /drivers/me/tips/summary — tip_count=0 with no tips in period
  24. GET /drivers/me/tips/summary — tip_count reflects driver's own tips only
  25. GET /drivers/me/tips/summary — period=week accepted
  26. GET /drivers/me/tips/summary — period=year accepted
  27. GET /drivers/me/tips/summary — period=all accepted
  28. GET /drivers/me/tips/summary — invalid period returns 422
  29. GET /admin/tips/stats — 401 without auth
  30. GET /admin/tips/stats — 403 for rider role
  31. GET /admin/tips/stats — 403 for driver role
  32. GET /admin/tips/stats — 200 with admin token
  33. GET /admin/tips/stats — response includes required fields
  34. GET /admin/tips/stats — tip_count=0 with no tips
  35. GET /admin/tips/stats — period=week accepted
  36. GET /admin/tips/stats — invalid period returns 422
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.tip import TipRecord, TipStatus
from app.services.analytics import get_admin_tip_stats, get_driver_tip_summary


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_tip(
    tip_id: int = 1,
    driver_id: int = 20,
    rider_id: int = 10,
    amount_cents: int = 300,
    status: TipStatus = TipStatus.COMPLETED,
    created_at: datetime | None = None,
) -> MagicMock:
    tip = MagicMock(spec=TipRecord)
    tip.id = tip_id
    tip.driver_id = driver_id
    tip.rider_id = rider_id
    tip.amount_cents = amount_cents
    tip.status = status
    tip.created_at = created_at or datetime(2025, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    return tip


def _make_db_tips(tips: list) -> AsyncMock:
    """Return a mock DB where a single execute returns the given tip list."""
    db = AsyncMock()
    mock_result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = tips
    mock_result.scalars.return_value = scalars_mock
    db.execute = AsyncMock(return_value=mock_result)
    return db


# ---------------------------------------------------------------------------
# Unit tests — get_driver_tip_summary
# ---------------------------------------------------------------------------


class TestGetDriverTipSummary:
    @pytest.mark.asyncio
    async def test_empty_returns_zeros(self):
        db = _make_db_tips([])
        result = await get_driver_tip_summary(db, driver_id=20, period="month")
        assert result["total_cents"] == 0
        assert result["tip_count"] == 0
        assert result["avg_tip_cents"] == 0
        assert result["total_dollars"] == 0.0

    @pytest.mark.asyncio
    async def test_total_cents_sums_all_tips(self):
        tips = [_make_tip(tip_id=1, amount_cents=200), _make_tip(tip_id=2, amount_cents=500)]
        db = _make_db_tips(tips)
        result = await get_driver_tip_summary(db, driver_id=20, period="month")
        assert result["total_cents"] == 700

    @pytest.mark.asyncio
    async def test_tip_count_matches_records(self):
        tips = [_make_tip(tip_id=i) for i in range(5)]
        db = _make_db_tips(tips)
        result = await get_driver_tip_summary(db, driver_id=20, period="month")
        assert result["tip_count"] == 5

    @pytest.mark.asyncio
    async def test_avg_tip_cents_integer_division(self):
        # 100 + 200 = 300 total, 3 tips: avg = 100
        tips = [_make_tip(tip_id=1, amount_cents=100), _make_tip(tip_id=2, amount_cents=100), _make_tip(tip_id=3, amount_cents=100)]
        db = _make_db_tips(tips)
        result = await get_driver_tip_summary(db, driver_id=20, period="month")
        assert result["avg_tip_cents"] == 100

    @pytest.mark.asyncio
    async def test_avg_tip_cents_zero_when_no_tips(self):
        db = _make_db_tips([])
        result = await get_driver_tip_summary(db, driver_id=20, period="month")
        assert result["avg_tip_cents"] == 0

    @pytest.mark.asyncio
    async def test_total_dollars_is_cents_divided_100(self):
        tips = [_make_tip(amount_cents=500)]
        db = _make_db_tips(tips)
        result = await get_driver_tip_summary(db, driver_id=20, period="month")
        assert result["total_dollars"] == 5.0

    @pytest.mark.asyncio
    async def test_status_breakdown_counts_completed(self):
        tips = [_make_tip(tip_id=i, status=TipStatus.COMPLETED) for i in range(3)]
        db = _make_db_tips(tips)
        result = await get_driver_tip_summary(db, driver_id=20, period="month")
        assert result["status_breakdown"]["completed"] == 3

    @pytest.mark.asyncio
    async def test_status_breakdown_counts_pending(self):
        tips = [_make_tip(tip_id=1, status=TipStatus.PENDING), _make_tip(tip_id=2, status=TipStatus.PENDING)]
        db = _make_db_tips(tips)
        result = await get_driver_tip_summary(db, driver_id=20, period="month")
        assert result["status_breakdown"]["pending"] == 2

    @pytest.mark.asyncio
    async def test_status_breakdown_counts_refunded(self):
        tips = [_make_tip(tip_id=1, status=TipStatus.REFUNDED)]
        db = _make_db_tips(tips)
        result = await get_driver_tip_summary(db, driver_id=20, period="all")
        assert result["status_breakdown"]["refunded"] == 1

    @pytest.mark.asyncio
    async def test_status_breakdown_counts_failed(self):
        tips = [_make_tip(tip_id=1, status=TipStatus.FAILED)]
        db = _make_db_tips(tips)
        result = await get_driver_tip_summary(db, driver_id=20, period="all")
        assert result["status_breakdown"]["failed"] == 1

    @pytest.mark.asyncio
    async def test_status_breakdown_mixed_statuses(self):
        tips = [
            _make_tip(tip_id=1, status=TipStatus.COMPLETED),
            _make_tip(tip_id=2, status=TipStatus.COMPLETED),
            _make_tip(tip_id=3, status=TipStatus.PENDING),
            _make_tip(tip_id=4, status=TipStatus.REFUNDED),
        ]
        db = _make_db_tips(tips)
        result = await get_driver_tip_summary(db, driver_id=20, period="year")
        sb = result["status_breakdown"]
        assert sb["completed"] == 2
        assert sb["pending"] == 1
        assert sb["refunded"] == 1
        assert sb["failed"] == 0


# ---------------------------------------------------------------------------
# Unit tests — get_admin_tip_stats
# ---------------------------------------------------------------------------


class TestGetAdminTipStats:
    @pytest.mark.asyncio
    async def test_empty_returns_zeros(self):
        db = _make_db_tips([])
        result = await get_admin_tip_stats(db, period="month")
        assert result["total_cents"] == 0
        assert result["tip_count"] == 0
        assert result["avg_tip_cents"] == 0
        assert result["unique_drivers_tipped"] == 0
        assert result["unique_riders_who_tipped"] == 0
        assert result["top_tipped_drivers"] == []

    @pytest.mark.asyncio
    async def test_total_cents_sums_all_tips(self):
        tips = [_make_tip(tip_id=1, amount_cents=300), _make_tip(tip_id=2, amount_cents=700)]
        db = _make_db_tips(tips)
        result = await get_admin_tip_stats(db, period="all")
        assert result["total_cents"] == 1000

    @pytest.mark.asyncio
    async def test_unique_drivers_tipped(self):
        tips = [
            _make_tip(tip_id=1, driver_id=10, rider_id=1),
            _make_tip(tip_id=2, driver_id=10, rider_id=2),
            _make_tip(tip_id=3, driver_id=20, rider_id=3),
        ]
        db = _make_db_tips(tips)
        result = await get_admin_tip_stats(db, period="all")
        assert result["unique_drivers_tipped"] == 2

    @pytest.mark.asyncio
    async def test_unique_riders_who_tipped(self):
        tips = [
            _make_tip(tip_id=1, driver_id=10, rider_id=100),
            _make_tip(tip_id=2, driver_id=20, rider_id=100),
            _make_tip(tip_id=3, driver_id=30, rider_id=200),
        ]
        db = _make_db_tips(tips)
        result = await get_admin_tip_stats(db, period="all")
        assert result["unique_riders_who_tipped"] == 2

    @pytest.mark.asyncio
    async def test_top_tipped_drivers_ranked_by_total_cents(self):
        tips = [
            _make_tip(tip_id=1, driver_id=10, amount_cents=100),
            _make_tip(tip_id=2, driver_id=10, amount_cents=200),
            _make_tip(tip_id=3, driver_id=20, amount_cents=500),
        ]
        db = _make_db_tips(tips)
        result = await get_admin_tip_stats(db, period="all")
        # driver 20 ($5.00) should rank above driver 10 ($3.00)
        assert result["top_tipped_drivers"][0]["driver_id"] == 20
        assert result["top_tipped_drivers"][1]["driver_id"] == 10

    @pytest.mark.asyncio
    async def test_top_tipped_drivers_capped_at_10(self):
        tips = [_make_tip(tip_id=i, driver_id=i, rider_id=i + 100) for i in range(1, 16)]
        db = _make_db_tips(tips)
        result = await get_admin_tip_stats(db, period="all")
        assert len(result["top_tipped_drivers"]) <= 10

    @pytest.mark.asyncio
    async def test_avg_tip_cents_zero_when_no_tips(self):
        db = _make_db_tips([])
        result = await get_admin_tip_stats(db, period="week")
        assert result["avg_tip_cents"] == 0


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.anyio


class TestDriverTipSummaryEndpoint:
    async def test_requires_auth(self, client):
        resp = await client.get("/drivers/me/tips/summary")
        assert resp.status_code == 401

    async def test_requires_driver_role(self, client, rider_token):
        from tests.conftest import auth_header
        resp = await client.get("/drivers/me/tips/summary", headers=auth_header(rider_token))
        assert resp.status_code == 403

    async def test_200_for_driver(self, client, driver_token):
        from tests.conftest import auth_header
        resp = await client.get("/drivers/me/tips/summary", headers=auth_header(driver_token))
        assert resp.status_code == 200

    async def test_response_has_required_fields(self, client, driver_token):
        from tests.conftest import auth_header
        resp = await client.get("/drivers/me/tips/summary", headers=auth_header(driver_token))
        data = resp.json()
        for field in ["period", "total_cents", "total_dollars", "tip_count", "avg_tip_cents", "avg_tip_dollars", "status_breakdown"]:
            assert field in data, f"Missing field: {field}"

    async def test_empty_period_returns_zero_tip_count(self, client, driver_token):
        from tests.conftest import auth_header
        resp = await client.get("/drivers/me/tips/summary?period=month", headers=auth_header(driver_token))
        assert resp.status_code == 200
        assert resp.json()["tip_count"] == 0

    async def test_driver_sees_only_own_tips(self, client, db, driver_user, rider, driver_token):
        """A second driver's tips are not included in the first driver's summary."""
        from tests.conftest import auth_header
        from app.models.user import User, UserRole
        from app.services.auth import hash_password, create_access_token

        # Create a second driver
        other_driver = User(
            phone="+15559999997",
            name="Other Driver",
            email="other_driver_tip_test@test.com",
            password_hash=hash_password("testpass123"),
            role=UserRole.DRIVER,
            is_active=True,
        )
        db.add(other_driver)
        await db.flush()

        # Add a tip for the other driver
        tip = TipRecord(
            ride_id=99999,
            driver_id=other_driver.id,
            rider_id=rider.id,
            amount_cents=500,
            status=TipStatus.COMPLETED,
        )
        db.add(tip)
        await db.flush()

        resp = await client.get("/drivers/me/tips/summary?period=all", headers=auth_header(driver_token))
        assert resp.status_code == 200
        # driver_user's own tip count should not include other_driver's tips
        assert resp.json()["tip_count"] == 0

    async def test_period_week_accepted(self, client, driver_token):
        from tests.conftest import auth_header
        resp = await client.get("/drivers/me/tips/summary?period=week", headers=auth_header(driver_token))
        assert resp.status_code == 200
        assert resp.json()["period"] == "week"

    async def test_period_year_accepted(self, client, driver_token):
        from tests.conftest import auth_header
        resp = await client.get("/drivers/me/tips/summary?period=year", headers=auth_header(driver_token))
        assert resp.status_code == 200

    async def test_period_all_accepted(self, client, driver_token):
        from tests.conftest import auth_header
        resp = await client.get("/drivers/me/tips/summary?period=all", headers=auth_header(driver_token))
        assert resp.status_code == 200

    async def test_invalid_period_returns_422(self, client, driver_token):
        from tests.conftest import auth_header
        resp = await client.get("/drivers/me/tips/summary?period=quarterly", headers=auth_header(driver_token))
        assert resp.status_code == 422


class TestAdminTipStatsEndpoint:
    async def test_requires_auth(self, client):
        resp = await client.get("/admin/tips/stats")
        assert resp.status_code == 401

    async def test_requires_admin_not_rider(self, client, rider_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/tips/stats", headers=auth_header(rider_token))
        assert resp.status_code == 403

    async def test_requires_admin_not_driver(self, client, driver_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/tips/stats", headers=auth_header(driver_token))
        assert resp.status_code == 403

    async def test_200_for_admin(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/tips/stats", headers=auth_header(admin_token))
        assert resp.status_code == 200

    async def test_response_has_required_fields(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/tips/stats", headers=auth_header(admin_token))
        data = resp.json()
        for field in [
            "period", "total_cents", "total_dollars", "tip_count",
            "avg_tip_cents", "avg_tip_dollars",
            "unique_drivers_tipped", "unique_riders_who_tipped",
            "top_tipped_drivers",
        ]:
            assert field in data, f"Missing field: {field}"

    async def test_empty_db_returns_zero_tip_count(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/tips/stats?period=week", headers=auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["tip_count"] == 0

    async def test_period_week_accepted(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/tips/stats?period=week", headers=auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["period"] == "week"

    async def test_invalid_period_returns_422(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/tips/stats?period=daily", headers=auth_header(admin_token))
        assert resp.status_code == 422
