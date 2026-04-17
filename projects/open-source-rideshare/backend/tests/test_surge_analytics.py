"""Tests for admin surge analytics — SurgePricingEvent model, service, and API endpoints.

Covers:
- record_surge_event: correct event_type classification, field persistence
- get_surge_summary: counts by type, avg multiplier, peak hour, top zone
- get_zone_breakdown: per-zone aggregates, ordering
- get_demand_heatmap: geohash cell ranking, limit respected
- Admin API: GET /admin/surge-analytics/summary, /zones, /demand-heatmap
- Validation: days and limit bounds
- fare_preview integration: surge event emitted when is_surge_active
- fare_preview integration: event NOT emitted when no surge
- fare_preview integration: DB exception swallowed — preview still returns
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.surge_event import SurgeEventType
from app.schemas.surge_zone import (
    DemandHeatmapCellResponse,
    DemandHeatmapResponse,
    SurgeSummaryResponse,
    ZoneAnalyticsResponse,
    ZoneBreakdownResponse,
)
from app.services.surge_analytics import (
    DemandHeatmapCell,
    SurgeSummary,
    ZoneAnalytics,
    get_demand_heatmap,
    get_surge_summary,
    get_zone_breakdown,
    record_surge_event,
)


# ===========================================================================
# Helpers
# ===========================================================================


def _mock_db():
    """Minimal async DB session mock."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _row(event_type=None, cnt=None, hr=None, surge_zone_name=None,
         surge_zone_id=None, event_count=None, avg_multiplier=None,
         avg_demand=None, avg_supply=None, geohash=None):
    row = MagicMock()
    row.event_type = event_type
    row.cnt = cnt
    row.hr = hr
    row.surge_zone_name = surge_zone_name
    row.surge_zone_id = surge_zone_id
    row.event_count = event_count
    row.avg_multiplier = avg_multiplier
    row.avg_demand = avg_demand
    row.avg_supply = avg_supply
    row.geohash = geohash
    return row


def _make_result(rows):
    result = MagicMock()
    result.__iter__ = lambda s: iter(rows)
    result.scalar = MagicMock(return_value=None)
    result.one_or_none = MagicMock(return_value=rows[0] if rows else None)
    return result


# ===========================================================================
# record_surge_event — unit tests
# ===========================================================================


class TestRecordSurgeEvent:
    @pytest.mark.asyncio
    async def test_zone_only_event_type(self):
        db = _mock_db()
        await record_surge_event(
            db,
            lat=40.7128,
            lon=-74.0060,
            geohash="dr5r",
            surge_zone_id="abc",
            surge_zone_name="Airport",
            zone_multiplier=1.3,
            demand_multiplier=1.0,
            demand_count=0,
            supply_count=5,
            combined_multiplier=1.3,
        )
        db.add.assert_called_once()
        event = db.add.call_args[0][0]
        assert event.event_type == SurgeEventType.ZONE_ONLY
        assert event.surge_zone_name == "Airport"
        assert event.zone_multiplier == 1.3
        assert event.demand_multiplier == 1.0

    @pytest.mark.asyncio
    async def test_demand_only_event_type(self):
        db = _mock_db()
        await record_surge_event(
            db,
            lat=40.7128,
            lon=-74.0060,
            geohash="dr5r",
            surge_zone_id=None,
            surge_zone_name=None,
            zone_multiplier=1.0,
            demand_multiplier=1.4,
            demand_count=10,
            supply_count=2,
            combined_multiplier=1.4,
        )
        event = db.add.call_args[0][0]
        assert event.event_type == SurgeEventType.DEMAND_ONLY
        assert event.surge_zone_name is None
        assert event.demand_count == 10
        assert event.supply_count == 2

    @pytest.mark.asyncio
    async def test_combined_event_type(self):
        db = _mock_db()
        await record_surge_event(
            db,
            lat=40.7128,
            lon=-74.0060,
            geohash="dr5r",
            surge_zone_id="z1",
            surge_zone_name="Stadium",
            zone_multiplier=1.2,
            demand_multiplier=1.25,
            demand_count=8,
            supply_count=3,
            combined_multiplier=1.5,
        )
        event = db.add.call_args[0][0]
        assert event.event_type == SurgeEventType.COMBINED
        assert event.combined_multiplier == 1.5

    @pytest.mark.asyncio
    async def test_geohash_and_coords_stored(self):
        db = _mock_db()
        await record_surge_event(
            db,
            lat=51.5074,
            lon=-0.1278,
            geohash="gcpvh",
            surge_zone_id=None,
            surge_zone_name=None,
            zone_multiplier=1.0,
            demand_multiplier=1.2,
            demand_count=5,
            supply_count=1,
            combined_multiplier=1.2,
        )
        event = db.add.call_args[0][0]
        assert event.lat == 51.5074
        assert event.lon == -0.1278
        assert event.geohash == "gcpvh"

    @pytest.mark.asyncio
    async def test_flush_called(self):
        db = _mock_db()
        await record_surge_event(
            db,
            lat=0.0,
            lon=0.0,
            geohash="s0000",
            surge_zone_id=None,
            surge_zone_name=None,
            zone_multiplier=1.0,
            demand_multiplier=1.5,
            demand_count=12,
            supply_count=1,
            combined_multiplier=1.5,
        )
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_zone_id_stored_as_string(self):
        import uuid
        zone_id = uuid.uuid4()
        db = _mock_db()
        await record_surge_event(
            db,
            lat=0.0,
            lon=0.0,
            geohash="s0000",
            surge_zone_id=zone_id,
            surge_zone_name="Test",
            zone_multiplier=1.1,
            demand_multiplier=1.0,
            demand_count=0,
            supply_count=0,
            combined_multiplier=1.1,
        )
        event = db.add.call_args[0][0]
        assert event.surge_zone_id == str(zone_id)


# ===========================================================================
# get_surge_summary — unit tests
# ===========================================================================


class TestGetSurgeSummary:
    def _build_db(
        self,
        type_rows=None,
        avg_mult=1.3,
        peak_row=None,
        top_zone_row=None,
    ):
        db = AsyncMock()
        type_rows = type_rows or []

        async def execute(query):
            result = MagicMock()
            result.__iter__ = lambda s: iter(type_rows)
            result.scalar = MagicMock(return_value=avg_mult)
            result.one_or_none = MagicMock(return_value=peak_row if peak_row else top_zone_row)
            return result

        db.execute = execute
        return db

    @pytest.mark.asyncio
    async def test_empty_database_returns_zeros(self):
        db = AsyncMock()
        empty_result = MagicMock()
        empty_result.__iter__ = lambda s: iter([])
        empty_result.scalar = MagicMock(return_value=None)
        empty_result.one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=empty_result)

        summary = await get_surge_summary(db, days=7)

        assert summary.total_surge_events == 0
        assert summary.zone_surge_events == 0
        assert summary.demand_surge_events == 0
        assert summary.combined_surge_events == 0
        assert summary.peak_hour is None
        assert summary.top_zone_name is None
        assert summary.top_zone_event_count == 0

    @pytest.mark.asyncio
    async def test_counts_by_type_aggregated(self):
        type_rows = [
            _row(event_type=SurgeEventType.ZONE_ONLY, cnt=10),
            _row(event_type=SurgeEventType.DEMAND_ONLY, cnt=15),
            _row(event_type=SurgeEventType.COMBINED, cnt=5),
        ]
        db = AsyncMock()
        call_count = [0]

        async def execute(query):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                # type counts query
                result.__iter__ = lambda s: iter(type_rows)
            elif call_count[0] == 2:
                # avg multiplier
                result.__iter__ = lambda s: iter([])
                result.scalar = MagicMock(return_value=1.25)
            else:
                result.__iter__ = lambda s: iter([])
                result.one_or_none = MagicMock(return_value=None)
            return result

        db.execute = execute

        summary = await get_surge_summary(db, days=7)
        assert summary.total_surge_events == 30
        assert summary.zone_surge_events == 15  # zone_only + combined
        assert summary.demand_surge_events == 20  # demand_only + combined
        assert summary.combined_surge_events == 5

    @pytest.mark.asyncio
    async def test_period_days_reflected(self):
        db = AsyncMock()
        empty_result = MagicMock()
        empty_result.__iter__ = lambda s: iter([])
        empty_result.scalar = MagicMock(return_value=None)
        empty_result.one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=empty_result)

        summary = await get_surge_summary(db, days=30)
        assert summary.period_days == 30

    @pytest.mark.asyncio
    async def test_avg_multiplier_rounded(self):
        db = AsyncMock()
        call_count = [0]

        async def execute(query):
            call_count[0] += 1
            result = MagicMock()
            result.__iter__ = lambda s: iter([])
            result.scalar = MagicMock(return_value=1.23456789)
            result.one_or_none = MagicMock(return_value=None)
            return result

        db.execute = execute
        summary = await get_surge_summary(db, days=7)
        assert summary.avg_combined_multiplier == round(1.23456789, 3)


# ===========================================================================
# get_zone_breakdown — unit tests
# ===========================================================================


class TestGetZoneBreakdown:
    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self):
        db = AsyncMock()
        result = MagicMock()
        result.__iter__ = lambda s: iter([])
        db.execute = AsyncMock(return_value=result)

        zones = await get_zone_breakdown(db, days=30)
        assert zones == []

    @pytest.mark.asyncio
    async def test_zone_row_mapped_correctly(self):
        row = _row(
            surge_zone_id="uuid-abc",
            surge_zone_name="Airport",
            event_count=25,
            avg_multiplier=1.45,
            avg_demand=7.2,
            avg_supply=2.1,
        )
        db = AsyncMock()
        result = MagicMock()
        result.__iter__ = lambda s: iter([row])
        db.execute = AsyncMock(return_value=result)

        zones = await get_zone_breakdown(db, days=30)
        assert len(zones) == 1
        z = zones[0]
        assert z.zone_id == "uuid-abc"
        assert z.zone_name == "Airport"
        assert z.event_count == 25
        assert z.avg_multiplier == round(1.45, 3)
        assert z.avg_demand_count == round(7.2, 1)
        assert z.avg_supply_count == round(2.1, 1)

    @pytest.mark.asyncio
    async def test_multiple_zones_all_returned(self):
        rows = [
            _row(surge_zone_id="z1", surge_zone_name="Zone A", event_count=30,
                 avg_multiplier=1.5, avg_demand=8.0, avg_supply=3.0),
            _row(surge_zone_id="z2", surge_zone_name="Zone B", event_count=10,
                 avg_multiplier=1.2, avg_demand=4.0, avg_supply=5.0),
        ]
        db = AsyncMock()
        result = MagicMock()
        result.__iter__ = lambda s: iter(rows)
        db.execute = AsyncMock(return_value=result)

        zones = await get_zone_breakdown(db, days=14)
        assert len(zones) == 2
        assert zones[0].zone_name == "Zone A"
        assert zones[1].zone_name == "Zone B"

    @pytest.mark.asyncio
    async def test_null_avg_values_default_to_zero(self):
        row = _row(
            surge_zone_id="z1",
            surge_zone_name="Zone X",
            event_count=5,
            avg_multiplier=None,
            avg_demand=None,
            avg_supply=None,
        )
        db = AsyncMock()
        result = MagicMock()
        result.__iter__ = lambda s: iter([row])
        db.execute = AsyncMock(return_value=result)

        zones = await get_zone_breakdown(db, days=7)
        assert zones[0].avg_multiplier == 1.0
        assert zones[0].avg_demand_count == 0.0
        assert zones[0].avg_supply_count == 0.0


# ===========================================================================
# get_demand_heatmap — unit tests
# ===========================================================================


class TestGetDemandHeatmap:
    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self):
        db = AsyncMock()
        result = MagicMock()
        result.__iter__ = lambda s: iter([])
        db.execute = AsyncMock(return_value=result)

        cells = await get_demand_heatmap(db, days=7)
        assert cells == []

    @pytest.mark.asyncio
    async def test_cell_row_mapped_correctly(self):
        row = _row(geohash="dr5r7", event_count=42, avg_multiplier=1.38)
        db = AsyncMock()
        result = MagicMock()
        result.__iter__ = lambda s: iter([row])
        db.execute = AsyncMock(return_value=result)

        cells = await get_demand_heatmap(db, days=7)
        assert len(cells) == 1
        c = cells[0]
        assert c.geohash == "dr5r7"
        assert c.event_count == 42
        assert c.avg_combined_multiplier == round(1.38, 3)

    @pytest.mark.asyncio
    async def test_multiple_cells_all_returned(self):
        rows = [
            _row(geohash="dr5r7", event_count=50, avg_multiplier=1.5),
            _row(geohash="dr5r8", event_count=30, avg_multiplier=1.2),
            _row(geohash="dr5r9", event_count=10, avg_multiplier=1.1),
        ]
        db = AsyncMock()
        result = MagicMock()
        result.__iter__ = lambda s: iter(rows)
        db.execute = AsyncMock(return_value=result)

        cells = await get_demand_heatmap(db, days=3)
        assert len(cells) == 3
        assert cells[0].geohash == "dr5r7"

    @pytest.mark.asyncio
    async def test_null_avg_multiplier_defaults_to_one(self):
        row = _row(geohash="aaaaa", event_count=1, avg_multiplier=None)
        db = AsyncMock()
        result = MagicMock()
        result.__iter__ = lambda s: iter([row])
        db.execute = AsyncMock(return_value=result)

        cells = await get_demand_heatmap(db, days=7)
        assert cells[0].avg_combined_multiplier == 1.0


# ===========================================================================
# Admin API endpoints
# ===========================================================================


def _make_admin_client(app, db, admin_user):
    from app.api.deps import get_current_user, require_admin
    from app.db.database import get_db

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_admin] = lambda: admin_user
    app.dependency_overrides[get_current_user] = lambda: admin_user
    return app


def _admin_user():
    user = MagicMock()
    user.id = 1
    user.email = "admin@test.com"
    user.is_active = True
    return user


class TestSurgeAnalyticsAPI:
    @pytest.mark.asyncio
    async def test_summary_endpoint_returns_200(self):
        from httpx import ASGITransport, AsyncClient
        from app.main import app
        from app.api.deps import get_current_user, require_admin
        from app.db.database import get_db

        admin = _admin_user()
        summary = SurgeSummary(
            period_days=7,
            total_surge_events=50,
            zone_surge_events=20,
            demand_surge_events=35,
            combined_surge_events=5,
            avg_combined_multiplier=1.25,
            peak_hour=17,
            top_zone_name="Airport",
            top_zone_event_count=15,
        )

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[require_admin] = lambda: admin
        app.dependency_overrides[get_current_user] = lambda: admin

        try:
            with patch(
                "app.api.v1.surge_zones.get_surge_summary",
                new=AsyncMock(return_value=summary),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(
                        "/api/v1/admin/surge-analytics/summary",
                        params={"days": 7},
                    )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_surge_events"] == 50
            assert data["zone_surge_events"] == 20
            assert data["demand_surge_events"] == 35
            assert data["combined_surge_events"] == 5
            assert data["avg_combined_multiplier"] == 1.25
            assert data["peak_hour"] == 17
            assert data["top_zone_name"] == "Airport"
            assert data["top_zone_event_count"] == 15
            assert data["period_days"] == 7
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_summary_invalid_days_returns_422(self):
        from httpx import ASGITransport, AsyncClient
        from app.main import app
        from app.api.deps import get_current_user, require_admin
        from app.db.database import get_db

        admin = _admin_user()
        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[require_admin] = lambda: admin
        app.dependency_overrides[get_current_user] = lambda: admin

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/api/v1/admin/surge-analytics/summary",
                    params={"days": 400},
                )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_summary_days_zero_returns_422(self):
        from httpx import ASGITransport, AsyncClient
        from app.main import app
        from app.api.deps import get_current_user, require_admin
        from app.db.database import get_db

        admin = _admin_user()
        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[require_admin] = lambda: admin
        app.dependency_overrides[get_current_user] = lambda: admin

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/api/v1/admin/surge-analytics/summary",
                    params={"days": 0},
                )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_zones_endpoint_returns_200(self):
        from httpx import ASGITransport, AsyncClient
        from app.main import app
        from app.api.deps import get_current_user, require_admin
        from app.db.database import get_db

        admin = _admin_user()
        zone_data = [
            ZoneAnalytics(
                zone_id="z1",
                zone_name="Airport",
                event_count=30,
                avg_multiplier=1.4,
                avg_demand_count=6.5,
                avg_supply_count=2.0,
            )
        ]
        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[require_admin] = lambda: admin
        app.dependency_overrides[get_current_user] = lambda: admin

        try:
            with patch(
                "app.api.v1.surge_zones.get_zone_breakdown",
                new=AsyncMock(return_value=zone_data),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(
                        "/api/v1/admin/surge-analytics/zones",
                        params={"days": 30},
                    )
            assert resp.status_code == 200
            data = resp.json()
            assert data["period_days"] == 30
            assert data["total_zones"] == 1
            assert data["zones"][0]["zone_name"] == "Airport"
            assert data["zones"][0]["event_count"] == 30
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_zones_empty_result(self):
        from httpx import ASGITransport, AsyncClient
        from app.main import app
        from app.api.deps import get_current_user, require_admin
        from app.db.database import get_db

        admin = _admin_user()
        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[require_admin] = lambda: admin
        app.dependency_overrides[get_current_user] = lambda: admin

        try:
            with patch(
                "app.api.v1.surge_zones.get_zone_breakdown",
                new=AsyncMock(return_value=[]),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get("/api/v1/admin/surge-analytics/zones")
            assert resp.status_code == 200
            data = resp.json()
            assert data["zones"] == []
            assert data["total_zones"] == 0
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_heatmap_endpoint_returns_200(self):
        from httpx import ASGITransport, AsyncClient
        from app.main import app
        from app.api.deps import get_current_user, require_admin
        from app.db.database import get_db

        admin = _admin_user()
        cells = [
            DemandHeatmapCell(geohash="dr5r7", event_count=42, avg_combined_multiplier=1.35),
            DemandHeatmapCell(geohash="dr5r8", event_count=18, avg_combined_multiplier=1.15),
        ]
        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[require_admin] = lambda: admin
        app.dependency_overrides[get_current_user] = lambda: admin

        try:
            with patch(
                "app.api.v1.surge_zones.get_demand_heatmap",
                new=AsyncMock(return_value=cells),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(
                        "/api/v1/admin/surge-analytics/demand-heatmap",
                        params={"days": 7, "limit": 50},
                    )
            assert resp.status_code == 200
            data = resp.json()
            assert data["period_days"] == 7
            assert data["total_cells"] == 2
            assert data["cells"][0]["geohash"] == "dr5r7"
            assert data["cells"][0]["event_count"] == 42
            assert data["cells"][1]["geohash"] == "dr5r8"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_heatmap_invalid_limit_returns_422(self):
        from httpx import ASGITransport, AsyncClient
        from app.main import app
        from app.api.deps import get_current_user, require_admin
        from app.db.database import get_db

        admin = _admin_user()
        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[require_admin] = lambda: admin
        app.dependency_overrides[get_current_user] = lambda: admin

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/api/v1/admin/surge-analytics/demand-heatmap",
                    params={"limit": 0},
                )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_heatmap_limit_too_high_returns_422(self):
        from httpx import ASGITransport, AsyncClient
        from app.main import app
        from app.api.deps import get_current_user, require_admin
        from app.db.database import get_db

        admin = _admin_user()
        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[require_admin] = lambda: admin
        app.dependency_overrides[get_current_user] = lambda: admin

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/api/v1/admin/surge-analytics/demand-heatmap",
                    params={"limit": 201},
                )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_endpoints_require_admin_auth(self):
        """Unauthenticated requests should be rejected."""
        from httpx import ASGITransport, AsyncClient
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for path in [
                "/api/v1/admin/surge-analytics/summary",
                "/api/v1/admin/surge-analytics/zones",
                "/api/v1/admin/surge-analytics/demand-heatmap",
            ]:
                resp = await client.get(path)
                assert resp.status_code in (401, 403, 422), (
                    f"Expected auth failure for {path}, got {resp.status_code}"
                )


# ===========================================================================
# fare_preview integration — surge event emission
# ===========================================================================


class TestFarePreviewSurgeEventEmission:
    @pytest.mark.asyncio
    async def test_surge_event_emitted_when_zone_active(self):
        from app.services.fare_preview import get_fare_preview

        mock_db = AsyncMock()
        mock_redis = AsyncMock()

        zone = MagicMock()
        zone.multiplier = 1.3
        zone.name = "Test Zone"
        zone.description = None

        with (
            patch("app.services.routing.get_route", side_effect=Exception("no osrm")),
            patch("app.services.fare_preview.list_zones", new=AsyncMock(return_value=[zone])),
            patch("app.services.fare_preview.is_zone_active_now", return_value=True),
            patch("app.services.fare_preview._point_in_zone", return_value=True),
            patch("app.services.fare_preview.get_demand_info", side_effect=Exception("no redis")),
            patch(
                "app.services.surge_analytics.record_surge_event",
                new=AsyncMock(),
            ) as mock_record,
        ):
            await get_fare_preview(
                origin_lat=40.7128,
                origin_lon=-74.0060,
                dest_lat=40.7580,
                dest_lon=-73.9855,
                db=mock_db,
                redis_client=mock_redis,
            )
            mock_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_surge_event_when_no_surge(self):
        from app.services.fare_preview import get_fare_preview

        mock_db = AsyncMock()
        mock_redis = AsyncMock()

        with (
            patch("app.services.routing.get_route", side_effect=Exception("no osrm")),
            patch("app.services.fare_preview.list_zones", new=AsyncMock(return_value=[])),
            patch("app.services.fare_preview.get_demand_info", side_effect=Exception("no redis")),
        ):
            with patch(
                "app.services.surge_analytics.record_surge_event",
                new=AsyncMock(),
            ) as mock_record:
                await get_fare_preview(
                    origin_lat=40.7128,
                    origin_lon=-74.0060,
                    dest_lat=40.7580,
                    dest_lon=-73.9855,
                    db=mock_db,
                    redis_client=mock_redis,
                )
                mock_record.assert_not_called()

    @pytest.mark.asyncio
    async def test_fare_preview_succeeds_even_if_event_write_fails(self):
        """DB exception during surge event write must not propagate to caller."""
        from app.services.fare_preview import get_fare_preview

        mock_db = AsyncMock()
        mock_redis = AsyncMock()

        zone = MagicMock()
        zone.multiplier = 1.2
        zone.name = "Crash Zone"
        zone.description = None

        with (
            patch("app.services.routing.get_route", side_effect=Exception("no osrm")),
            patch("app.services.fare_preview.list_zones", new=AsyncMock(return_value=[zone])),
            patch("app.services.fare_preview.is_zone_active_now", return_value=True),
            patch("app.services.fare_preview._point_in_zone", return_value=True),
            patch("app.services.fare_preview.get_demand_info", side_effect=Exception("no redis")),
            patch(
                "app.services.surge_analytics.record_surge_event",
                new=AsyncMock(side_effect=Exception("DB is down")),
            ),
        ):
            result = await get_fare_preview(
                origin_lat=40.7128,
                origin_lon=-74.0060,
                dest_lat=40.7580,
                dest_lon=-73.9855,
                db=mock_db,
                redis_client=mock_redis,
            )
            # Preview should succeed regardless
            assert result is not None
            assert result.is_surge_active is True


# ===========================================================================
# Schema validation
# ===========================================================================


class TestSurgeAnalyticsSchemas:
    def test_surge_summary_response_fields(self):
        s = SurgeSummaryResponse(
            period_days=7,
            total_surge_events=100,
            zone_surge_events=60,
            demand_surge_events=50,
            combined_surge_events=10,
            avg_combined_multiplier=1.3,
            peak_hour=18,
            top_zone_name="Airport",
            top_zone_event_count=40,
        )
        assert s.period_days == 7
        assert s.peak_hour == 18
        assert s.top_zone_name == "Airport"

    def test_surge_summary_nullable_fields(self):
        s = SurgeSummaryResponse(
            period_days=7,
            total_surge_events=0,
            zone_surge_events=0,
            demand_surge_events=0,
            combined_surge_events=0,
            avg_combined_multiplier=1.0,
            peak_hour=None,
            top_zone_name=None,
            top_zone_event_count=0,
        )
        assert s.peak_hour is None
        assert s.top_zone_name is None

    def test_zone_breakdown_response_fields(self):
        r = ZoneBreakdownResponse(
            period_days=30,
            zones=[
                ZoneAnalyticsResponse(
                    zone_id="z1",
                    zone_name="Stadium",
                    event_count=20,
                    avg_multiplier=1.4,
                    avg_demand_count=5.5,
                    avg_supply_count=1.8,
                )
            ],
            total_zones=1,
        )
        assert r.total_zones == 1
        assert r.zones[0].zone_name == "Stadium"

    def test_demand_heatmap_response_fields(self):
        r = DemandHeatmapResponse(
            period_days=7,
            cells=[
                DemandHeatmapCellResponse(
                    geohash="dr5r7",
                    event_count=42,
                    avg_combined_multiplier=1.35,
                )
            ],
            total_cells=1,
        )
        assert r.total_cells == 1
        assert r.cells[0].geohash == "dr5r7"

    def test_zone_analytics_nullable_zone_id(self):
        z = ZoneAnalyticsResponse(
            zone_id=None,
            zone_name="Unknown",
            event_count=5,
            avg_multiplier=1.1,
            avg_demand_count=2.0,
            avg_supply_count=3.0,
        )
        assert z.zone_id is None
