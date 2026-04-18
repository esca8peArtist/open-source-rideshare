"""Tests for GET /admin/safety/overview.

Covers:
Schema:
  1.  SafetyTypeStats — required fields present
  2.  SafetyTypeStats — change is this_period minus prior_period
  3.  SafetyTypeStats — negative change when prior > this
  4.  SafetyOverview — all fields present
  5.  SafetyOverview — total_incidents is sum of individual types

Endpoint — mocked DB:
  6.  401 when no auth token provided
  7.  200 with all-zero stats when DB returns nothing
  8.  period=today fires 9 DB queries (4 cur + 4 prior + 1 active)
  9.  period=week fires 9 DB queries
  10. period=month fires 9 DB queries
  11. period=year fires 9 DB queries
  12. sos_active_now reflects active SOS count independently of period
  13. current period counts are reflected in sos_alerts.this_period
  14. prior period counts are reflected in sos_alerts.prior_period
  15. change is positive when current > prior
  16. change is negative when current < prior
  17. total_incidents.this_period equals sum of all current counts
  18. total_incidents.change equals sum of all individual changes
  19. generated_at is a datetime
  20. period field echoed in response
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.schemas.admin import SafetyOverview, SafetyTypeStats

NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scalar_result(value: int) -> MagicMock:
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _make_db(*scalars: int) -> AsyncMock:
    """Build a mock AsyncSession returning the given scalar values in sequence."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_scalar_result(v) for v in scalars])
    return db


def _overview_db(
    sos_cur=0,
    speeding_cur=0,
    dev_cur=0,
    noshow_cur=0,
    sos_pri=0,
    speeding_pri=0,
    dev_pri=0,
    noshow_pri=0,
    sos_active=0,
) -> AsyncMock:
    """Return a mock DB pre-loaded with the exact 9-query sequence the endpoint fires."""
    return _make_db(
        sos_cur,
        speeding_cur,
        dev_cur,
        noshow_cur,
        sos_pri,
        speeding_pri,
        dev_pri,
        noshow_pri,
        sos_active,
    )


# ---------------------------------------------------------------------------
# 1–5: Schema validation
# ---------------------------------------------------------------------------


class TestSafetyTypeStatsSchema:
    def test_required_fields(self):
        s = SafetyTypeStats(this_period=5, prior_period=3, change=2)
        assert s.this_period == 5
        assert s.prior_period == 3
        assert s.change == 2

    def test_change_positive(self):
        s = SafetyTypeStats(this_period=10, prior_period=6, change=4)
        assert s.change == 4

    def test_change_negative(self):
        s = SafetyTypeStats(this_period=2, prior_period=8, change=-6)
        assert s.change == -6


class TestSafetyOverviewSchema:
    def _make(self, **kwargs):
        defaults = dict(
            period="week",
            sos_alerts=SafetyTypeStats(this_period=1, prior_period=0, change=1),
            speeding_incidents=SafetyTypeStats(this_period=2, prior_period=1, change=1),
            route_deviation_incidents=SafetyTypeStats(this_period=3, prior_period=2, change=1),
            driver_no_show_incidents=SafetyTypeStats(this_period=4, prior_period=3, change=1),
            total_incidents=SafetyTypeStats(this_period=10, prior_period=6, change=4),
            sos_active_now=0,
            generated_at=NOW,
        )
        defaults.update(kwargs)
        return SafetyOverview(**defaults)

    def test_all_fields_present(self):
        overview = self._make()
        assert overview.period == "week"
        assert overview.sos_active_now == 0
        assert overview.generated_at == NOW

    def test_total_is_sum_of_types(self):
        overview = self._make()
        expected_this = (
            overview.sos_alerts.this_period
            + overview.speeding_incidents.this_period
            + overview.route_deviation_incidents.this_period
            + overview.driver_no_show_incidents.this_period
        )
        assert overview.total_incidents.this_period == expected_this


# ---------------------------------------------------------------------------
# 6: HTTP auth test
# ---------------------------------------------------------------------------


class TestSafetyOverviewAuth:
    @pytest.mark.asyncio
    async def test_requires_authentication(self):
        from httpx import ASGITransport, AsyncClient
        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/admin/safety/overview")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 7–20: Endpoint unit tests (direct call with mocked DB)
# ---------------------------------------------------------------------------


class TestSafetyOverviewEndpoint:
    @pytest.mark.asyncio
    async def test_all_zeros_when_db_empty(self):
        from app.api.v1.admin import safety_overview
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _overview_db()
        resp = await safety_overview(db=db, _admin=admin, period="week")

        assert resp.sos_alerts.this_period == 0
        assert resp.speeding_incidents.this_period == 0
        assert resp.route_deviation_incidents.this_period == 0
        assert resp.driver_no_show_incidents.this_period == 0
        assert resp.total_incidents.this_period == 0
        assert resp.sos_active_now == 0

    @pytest.mark.asyncio
    async def test_period_today_fires_nine_queries(self):
        from app.api.v1.admin import safety_overview
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _overview_db()
        await safety_overview(db=db, _admin=admin, period="today")
        assert db.execute.call_count == 9

    @pytest.mark.asyncio
    async def test_period_week_fires_nine_queries(self):
        from app.api.v1.admin import safety_overview
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _overview_db()
        await safety_overview(db=db, _admin=admin, period="week")
        assert db.execute.call_count == 9

    @pytest.mark.asyncio
    async def test_period_month_fires_nine_queries(self):
        from app.api.v1.admin import safety_overview
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _overview_db()
        await safety_overview(db=db, _admin=admin, period="month")
        assert db.execute.call_count == 9

    @pytest.mark.asyncio
    async def test_period_year_fires_nine_queries(self):
        from app.api.v1.admin import safety_overview
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _overview_db()
        await safety_overview(db=db, _admin=admin, period="year")
        assert db.execute.call_count == 9

    @pytest.mark.asyncio
    async def test_sos_active_now_independent_of_period(self):
        from app.api.v1.admin import safety_overview
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _overview_db(sos_active=7)
        resp = await safety_overview(db=db, _admin=admin, period="week")
        assert resp.sos_active_now == 7

    @pytest.mark.asyncio
    async def test_sos_current_count_in_this_period(self):
        from app.api.v1.admin import safety_overview
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _overview_db(sos_cur=3)
        resp = await safety_overview(db=db, _admin=admin, period="week")
        assert resp.sos_alerts.this_period == 3

    @pytest.mark.asyncio
    async def test_sos_prior_count_in_prior_period(self):
        from app.api.v1.admin import safety_overview
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _overview_db(sos_pri=5)
        resp = await safety_overview(db=db, _admin=admin, period="week")
        assert resp.sos_alerts.prior_period == 5

    @pytest.mark.asyncio
    async def test_change_positive_when_current_greater(self):
        from app.api.v1.admin import safety_overview
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _overview_db(speeding_cur=8, speeding_pri=3)
        resp = await safety_overview(db=db, _admin=admin, period="week")
        assert resp.speeding_incidents.change == 5

    @pytest.mark.asyncio
    async def test_change_negative_when_prior_greater(self):
        from app.api.v1.admin import safety_overview
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _overview_db(dev_cur=2, dev_pri=9)
        resp = await safety_overview(db=db, _admin=admin, period="month")
        assert resp.route_deviation_incidents.change == -7

    @pytest.mark.asyncio
    async def test_total_this_period_is_sum_of_all_types(self):
        from app.api.v1.admin import safety_overview
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _overview_db(sos_cur=1, speeding_cur=2, dev_cur=3, noshow_cur=4)
        resp = await safety_overview(db=db, _admin=admin, period="week")
        assert resp.total_incidents.this_period == 10

    @pytest.mark.asyncio
    async def test_total_change_is_sum_of_individual_changes(self):
        from app.api.v1.admin import safety_overview
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _overview_db(
            sos_cur=5, sos_pri=3,
            speeding_cur=4, speeding_pri=2,
            dev_cur=3, dev_pri=3,
            noshow_cur=1, noshow_pri=2,
        )
        resp = await safety_overview(db=db, _admin=admin, period="week")
        # change = (5-3) + (4-2) + (3-3) + (1-2) = 2+2+0-1 = 3
        assert resp.total_incidents.change == 3

    @pytest.mark.asyncio
    async def test_generated_at_is_datetime(self):
        from app.api.v1.admin import safety_overview
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _overview_db()
        resp = await safety_overview(db=db, _admin=admin, period="week")
        assert isinstance(resp.generated_at, datetime)

    @pytest.mark.asyncio
    async def test_period_echoed_in_response(self):
        from app.api.v1.admin import safety_overview
        from app.models.user import User

        admin = MagicMock(spec=User)
        for p in ("today", "week", "month", "year"):
            db = _overview_db()
            resp = await safety_overview(db=db, _admin=admin, period=p)
            assert resp.period == p
