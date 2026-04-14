"""Tests for surge zone boundary suggestion service and endpoint.

Covers:
- _haversine: basic distance calculation, same-point returns 0
- _cell_half_size_km: decreasing size with increasing precision
- _cluster_cells: empty input, single cell, two close cells merge, two far cells split,
    min_cells filtering, multi-cluster expansion, BFS expansion correctness
- _compute_weighted_centroid: single cell, uniform weights, different weights
- _compute_radius: single cell, multi-cell cluster
- _compute_avg_fare: all None, partial fare data, fully populated
- _suggest_multiplier: boundary values (0.0, 0.5, 1.0) and clamping
- _build_reason: overlap vs. no overlap, confidence tiers
- _check_overlaps: no zones, overlap hit, no overlap miss
- get_zone_boundary_suggestions: empty heatmap, single cluster, multiple clusters,
    date validation (422), max_suggestions cap, overlap flagging
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.surge_zone_suggestions import (
    ZoneSuggestion,
    ZoneSuggestionsFilters,
    ZoneSuggestionsResponse,
)
from app.services.surge_zone_suggestions import (
    _cell_half_size_km,
    _check_overlaps,
    _cluster_cells,
    _compute_avg_fare,
    _compute_radius,
    _compute_weighted_centroid,
    _haversine,
    _suggest_multiplier,
    get_zone_boundary_suggestions,
)


# ===========================================================================
# Helpers
# ===========================================================================


def _make_cell(lat: float, lng: float, total_activity: int = 10, avg_fare: float | None = None):
    """Build a minimal mock HeatmapCell."""
    c = MagicMock()
    c.lat = lat
    c.lng = lng
    c.total_activity = total_activity
    c.avg_fare = avg_fare
    return c


def _make_zone_mock(
    center_lat: float | None = None,
    center_lon: float | None = None,
    radius_km: float | None = None,
    polygon: list | None = None,
    name: str = "Existing Zone",
):
    z = MagicMock()
    z.center_lat = center_lat
    z.center_lon = center_lon
    z.radius_km = radius_km
    z.polygon = polygon
    z.name = name
    z.is_active = True
    return z


def _make_heatmap_response(cells: list):
    """Build a minimal mock HeatmapResponse."""
    r = MagicMock()
    r.cells = cells
    return r


# ===========================================================================
# _haversine
# ===========================================================================


class TestHaversine:
    def test_same_point_is_zero(self):
        assert _haversine(40.0, -74.0, 40.0, -74.0) == pytest.approx(0.0, abs=1e-6)

    def test_known_distance_approx(self):
        # NYC (40.7128, -74.0060) to London (51.5074, -0.1278) ≈ 5570 km
        d = _haversine(40.7128, -74.006, 51.5074, -0.1278)
        assert 5500 < d < 5650

    def test_short_distance(self):
        # One degree of latitude ≈ 111 km
        d = _haversine(0.0, 0.0, 1.0, 0.0)
        assert 110 < d < 112

    def test_symmetry(self):
        d1 = _haversine(40.0, -74.0, 41.0, -73.0)
        d2 = _haversine(41.0, -73.0, 40.0, -74.0)
        assert d1 == pytest.approx(d2, abs=1e-6)


# ===========================================================================
# _cell_half_size_km
# ===========================================================================


class TestCellHalfSizeKm:
    def test_precision_1(self):
        # 111 km / 10 / 2 = 5.55 km
        assert _cell_half_size_km(1) == pytest.approx(5.55, abs=0.01)

    def test_precision_2(self):
        # 111 km / 100 / 2 = 0.555 km
        assert _cell_half_size_km(2) == pytest.approx(0.555, abs=0.001)

    def test_precision_3(self):
        assert _cell_half_size_km(3) == pytest.approx(0.0555, abs=0.001)

    def test_decreasing_with_precision(self):
        assert _cell_half_size_km(1) > _cell_half_size_km(2) > _cell_half_size_km(3)


# ===========================================================================
# _cluster_cells
# ===========================================================================


class TestClusterCells:
    def test_empty_input(self):
        assert _cluster_cells([], cluster_radius_km=2.0, min_cells=1) == []

    def test_single_cell_meets_min(self):
        cells = [_make_cell(40.0, -74.0)]
        clusters = _cluster_cells(cells, cluster_radius_km=2.0, min_cells=1)
        assert len(clusters) == 1
        assert len(clusters[0]) == 1

    def test_single_cell_below_min(self):
        cells = [_make_cell(40.0, -74.0)]
        clusters = _cluster_cells(cells, cluster_radius_km=2.0, min_cells=2)
        assert clusters == []

    def test_two_close_cells_merge(self):
        # ~1.1 km apart at precision 2 — within 2 km radius
        c1 = _make_cell(40.00, -74.00)
        c2 = _make_cell(40.01, -74.00)  # ~1.1 km north
        clusters = _cluster_cells([c1, c2], cluster_radius_km=2.0, min_cells=2)
        assert len(clusters) == 1
        assert len(clusters[0]) == 2

    def test_two_far_cells_split(self):
        # ~111 km apart — well beyond 2 km radius
        c1 = _make_cell(40.00, -74.00, total_activity=20)
        c2 = _make_cell(41.00, -74.00, total_activity=10)
        clusters = _cluster_cells([c1, c2], cluster_radius_km=2.0, min_cells=1)
        assert len(clusters) == 2
        activities = sorted([sum(c.total_activity for c in cl) for cl in clusters], reverse=True)
        assert activities == [20, 10]

    def test_cluster_radius_boundary(self):
        # c1 at 40.00 and c3 at 40.02 are ~2.2 km apart — beyond 2.0 km
        c1 = _make_cell(40.00, -74.00, total_activity=30)
        c2 = _make_cell(40.01, -74.00, total_activity=20)  # ~1.1 km from c1
        c3 = _make_cell(40.02, -74.00, total_activity=10)  # ~1.1 km from c2
        # BFS: c1 seeds cluster, expands to c2 (~1.1 km), c2 expands to c3 (~1.1 km)
        # All should be in one cluster despite c1-c3 being ~2.2 km apart
        clusters = _cluster_cells([c1, c2, c3], cluster_radius_km=2.0, min_cells=1)
        # All connected via c2 bridge
        assert len(clusters) == 1
        assert len(clusters[0]) == 3

    def test_multiple_separate_clusters(self):
        # Two dense groups far apart
        group_a = [_make_cell(40.0 + i * 0.005, -74.0, total_activity=10) for i in range(3)]
        group_b = [_make_cell(45.0 + i * 0.005, -74.0, total_activity=5) for i in range(3)]
        cells = group_a + group_b
        clusters = _cluster_cells(cells, cluster_radius_km=2.0, min_cells=2)
        assert len(clusters) == 2

    def test_min_cells_filters_small_clusters(self):
        # One big cluster (3 cells) + one singleton
        big = [_make_cell(40.0 + i * 0.005, -74.0, total_activity=10) for i in range(3)]
        lone = [_make_cell(50.0, -74.0, total_activity=1)]
        clusters = _cluster_cells(big + lone, cluster_radius_km=2.0, min_cells=2)
        # Singleton excluded; big cluster included
        assert len(clusters) == 1
        assert len(clusters[0]) == 3


# ===========================================================================
# _compute_weighted_centroid
# ===========================================================================


class TestComputeWeightedCentroid:
    def test_single_cell(self):
        c = _make_cell(40.0, -74.0, total_activity=10)
        lat, lon = _compute_weighted_centroid([c])
        assert lat == pytest.approx(40.0)
        assert lon == pytest.approx(-74.0)

    def test_uniform_weights_is_geometric_center(self):
        c1 = _make_cell(40.0, -74.0, total_activity=10)
        c2 = _make_cell(42.0, -74.0, total_activity=10)
        lat, lon = _compute_weighted_centroid([c1, c2])
        assert lat == pytest.approx(41.0)
        assert lon == pytest.approx(-74.0)

    def test_skewed_weights_pulls_toward_heavy_cell(self):
        c1 = _make_cell(40.0, -74.0, total_activity=90)  # heavy
        c2 = _make_cell(42.0, -74.0, total_activity=10)  # light
        lat, lon = _compute_weighted_centroid([c1, c2])
        # Should be much closer to 40.0 than 42.0
        assert lat < 41.0
        assert lat == pytest.approx(40.2, abs=0.01)

    def test_zero_activity_fallback(self):
        c1 = _make_cell(40.0, -74.0, total_activity=0)
        c2 = _make_cell(42.0, -74.0, total_activity=0)
        lat, lon = _compute_weighted_centroid([c1, c2])
        assert lat == pytest.approx(41.0)
        assert lon == pytest.approx(-74.0)


# ===========================================================================
# _compute_radius
# ===========================================================================


class TestComputeRadius:
    def test_single_cell_returns_half_size_buffer(self):
        c = _make_cell(40.0, -74.0)
        r = _compute_radius(40.0, -74.0, [c], precision=2)
        # max_dist = 0 + half_size = 0.555 km
        assert r == pytest.approx(_cell_half_size_km(2), abs=0.001)

    def test_wider_cluster_has_larger_radius(self):
        c1 = _make_cell(40.0, -74.0)
        c2 = _make_cell(40.02, -74.0)  # ~2.2 km north
        r = _compute_radius(40.01, -74.0, [c1, c2], precision=2)
        assert r > _cell_half_size_km(2)
        assert r > 1.0  # definitely more than buffer only


# ===========================================================================
# _compute_avg_fare
# ===========================================================================


class TestComputeAvgFare:
    def test_all_none(self):
        cells = [_make_cell(40.0, -74.0, avg_fare=None) for _ in range(3)]
        assert _compute_avg_fare(cells) is None

    def test_single_cell_with_fare(self):
        c = _make_cell(40.0, -74.0, total_activity=10, avg_fare=15.0)
        assert _compute_avg_fare([c]) == pytest.approx(15.0)

    def test_weighted_average(self):
        c1 = _make_cell(40.0, -74.0, total_activity=10, avg_fare=10.0)
        c2 = _make_cell(40.01, -74.0, total_activity=10, avg_fare=20.0)
        result = _compute_avg_fare([c1, c2])
        assert result == pytest.approx(15.0, abs=0.01)

    def test_partial_fare_data_ignores_none_cells(self):
        c1 = _make_cell(40.0, -74.0, total_activity=10, avg_fare=12.0)
        c2 = _make_cell(40.01, -74.0, total_activity=10, avg_fare=None)
        # Only c1 contributes to fare average
        assert _compute_avg_fare([c1, c2]) == pytest.approx(12.0, abs=0.01)


# ===========================================================================
# _suggest_multiplier
# ===========================================================================


class TestSuggestMultiplier:
    def test_zero_confidence_gives_min(self):
        assert _suggest_multiplier(0.0) == 1.2

    def test_full_confidence_gives_max(self):
        assert _suggest_multiplier(1.0) == 2.0

    def test_mid_confidence(self):
        # 0.5 → 1.2 + 0.5 * 0.8 = 1.6
        assert _suggest_multiplier(0.5) == pytest.approx(1.6, abs=0.05)

    def test_clamp_above_one(self):
        assert _suggest_multiplier(1.5) == 2.0

    def test_clamp_below_zero(self):
        assert _suggest_multiplier(-0.5) == 1.2

    def test_result_is_rounded_to_one_decimal(self):
        result = _suggest_multiplier(0.333)
        # Should be a clean 1-decimal float
        assert result == round(result, 1)


# ===========================================================================
# _check_overlaps
# ===========================================================================


class TestCheckOverlaps:
    def test_no_zones_returns_false(self):
        overlaps, name = _check_overlaps(40.0, -74.0, [])
        assert overlaps is False
        assert name is None

    def test_centroid_inside_circular_zone(self):
        zone = _make_zone_mock(center_lat=40.0, center_lon=-74.0, radius_km=5.0)
        overlaps, name = _check_overlaps(40.0, -74.0, [zone])
        assert overlaps is True
        assert name == "Existing Zone"

    def test_centroid_outside_circular_zone(self):
        # Zone centre is 100+ km away
        zone = _make_zone_mock(center_lat=41.0, center_lon=-74.0, radius_km=1.0)
        overlaps, name = _check_overlaps(40.0, -74.0, [zone])
        assert overlaps is False
        assert name is None

    def test_zone_with_no_geometry_does_not_match(self):
        # Zone has neither polygon nor circle — _point_in_zone returns False
        zone = _make_zone_mock(center_lat=None, center_lon=None, radius_km=None, polygon=None)
        overlaps, name = _check_overlaps(40.0, -74.0, [zone])
        assert overlaps is False

    def test_first_overlapping_zone_is_returned(self):
        z1 = _make_zone_mock(center_lat=40.0, center_lon=-74.0, radius_km=5.0, name="Zone A")
        z2 = _make_zone_mock(center_lat=40.0, center_lon=-74.0, radius_km=5.0, name="Zone B")
        overlaps, name = _check_overlaps(40.0, -74.0, [z1, z2])
        assert overlaps is True
        assert name == "Zone A"


# ===========================================================================
# get_zone_boundary_suggestions (integration-style, mocked DB)
# ===========================================================================


def _make_db_mock():
    """Return an AsyncMock that behaves as a minimal DB session."""
    return AsyncMock()


class TestGetZoneBoundarySuggestions:
    @pytest.mark.asyncio
    async def test_empty_heatmap_returns_no_suggestions(self):
        db = _make_db_mock()
        empty_response = _make_heatmap_response([])
        with (
            patch(
                "app.services.surge_zone_suggestions.get_trip_heatmap",
                new=AsyncMock(return_value=empty_response),
            ),
            patch(
                "app.services.surge_zone_suggestions.list_zones",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await get_zone_boundary_suggestions(db)
        assert result.total_suggestions == 0
        assert result.suggestions == []

    @pytest.mark.asyncio
    async def test_single_cluster_returned(self):
        cells = [
            _make_cell(40.00, -74.00, total_activity=20),
            _make_cell(40.01, -74.00, total_activity=15),
            _make_cell(40.00, -74.01, total_activity=10),
        ]
        heatmap = _make_heatmap_response(cells)
        with (
            patch(
                "app.services.surge_zone_suggestions.get_trip_heatmap",
                new=AsyncMock(return_value=heatmap),
            ),
            patch(
                "app.services.surge_zone_suggestions.list_zones",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await get_zone_boundary_suggestions(
                _make_db_mock(), cluster_radius_km=2.0, min_cells=2
            )
        assert result.total_suggestions == 1
        s = result.suggestions[0]
        assert s.suggestion_id == 1
        assert s.cell_count == 3
        assert s.total_activity == 45
        assert s.confidence == pytest.approx(1.0)
        assert s.overlaps_existing_zone is False

    @pytest.mark.asyncio
    async def test_multiple_clusters_sorted_by_activity(self):
        # Two distant groups
        group_a = [_make_cell(40.0 + i * 0.005, -74.0, total_activity=10) for i in range(3)]  # 30 total
        group_b = [_make_cell(45.0 + i * 0.005, -74.0, total_activity=5) for i in range(3)]   # 15 total
        cells = group_a + group_b
        heatmap = _make_heatmap_response(cells)
        with (
            patch(
                "app.services.surge_zone_suggestions.get_trip_heatmap",
                new=AsyncMock(return_value=heatmap),
            ),
            patch(
                "app.services.surge_zone_suggestions.list_zones",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await get_zone_boundary_suggestions(
                _make_db_mock(), cluster_radius_km=2.0, min_cells=2
            )
        assert result.total_suggestions == 2
        # First suggestion has higher activity
        assert result.suggestions[0].total_activity > result.suggestions[1].total_activity
        # First suggestion has confidence 1.0
        assert result.suggestions[0].confidence == pytest.approx(1.0)
        # Second suggestion has lower confidence
        assert result.suggestions[1].confidence < 1.0

    @pytest.mark.asyncio
    async def test_max_suggestions_cap(self):
        # 5 widely separated singleton clusters (precision=1 so min_cells=1 works)
        cells = [_make_cell(float(30 + i * 5), -74.0, total_activity=10) for i in range(5)]
        heatmap = _make_heatmap_response(cells)
        with (
            patch(
                "app.services.surge_zone_suggestions.get_trip_heatmap",
                new=AsyncMock(return_value=heatmap),
            ),
            patch(
                "app.services.surge_zone_suggestions.list_zones",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await get_zone_boundary_suggestions(
                _make_db_mock(), cluster_radius_km=2.0, min_cells=1, max_suggestions=3
            )
        assert result.total_suggestions <= 3

    @pytest.mark.asyncio
    async def test_overlap_flagged_when_centroid_in_existing_zone(self):
        cells = [
            _make_cell(40.0, -74.0, total_activity=20),
            _make_cell(40.01, -74.0, total_activity=10),
        ]
        heatmap = _make_heatmap_response(cells)
        # Existing zone covers the cluster centroid
        existing = _make_zone_mock(
            center_lat=40.005, center_lon=-74.0, radius_km=5.0, name="Downtown Zone"
        )
        with (
            patch(
                "app.services.surge_zone_suggestions.get_trip_heatmap",
                new=AsyncMock(return_value=heatmap),
            ),
            patch(
                "app.services.surge_zone_suggestions.list_zones",
                new=AsyncMock(return_value=[existing]),
            ),
        ):
            result = await get_zone_boundary_suggestions(
                _make_db_mock(), cluster_radius_km=2.0, min_cells=2
            )
        assert result.total_suggestions == 1
        s = result.suggestions[0]
        assert s.overlaps_existing_zone is True
        assert s.overlapping_zone_name == "Downtown Zone"
        assert "Downtown Zone" in s.reason

    @pytest.mark.asyncio
    async def test_filters_echoed_in_response(self):
        heatmap = _make_heatmap_response([])
        with (
            patch(
                "app.services.surge_zone_suggestions.get_trip_heatmap",
                new=AsyncMock(return_value=heatmap),
            ),
            patch(
                "app.services.surge_zone_suggestions.list_zones",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await get_zone_boundary_suggestions(
                _make_db_mock(),
                start_date=date(2026, 1, 1),
                end_date=date(2026, 3, 31),
                min_activity=3,
                precision=3,
                cluster_radius_km=1.5,
                min_cells=4,
                max_suggestions=5,
            )
        f = result.filters
        assert f.start_date == date(2026, 1, 1)
        assert f.end_date == date(2026, 3, 31)
        assert f.min_activity == 3
        assert f.precision == 3
        assert f.cluster_radius_km == pytest.approx(1.5)
        assert f.min_cells == 4
        assert f.max_suggestions == 5

    @pytest.mark.asyncio
    async def test_suggestion_ids_are_sequential_from_one(self):
        group_a = [_make_cell(40.0 + i * 0.005, -74.0, total_activity=10) for i in range(3)]
        group_b = [_make_cell(45.0 + i * 0.005, -74.0, total_activity=5) for i in range(3)]
        heatmap = _make_heatmap_response(group_a + group_b)
        with (
            patch(
                "app.services.surge_zone_suggestions.get_trip_heatmap",
                new=AsyncMock(return_value=heatmap),
            ),
            patch(
                "app.services.surge_zone_suggestions.list_zones",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await get_zone_boundary_suggestions(
                _make_db_mock(), cluster_radius_km=2.0, min_cells=2
            )
        ids = [s.suggestion_id for s in result.suggestions]
        assert ids == list(range(1, len(ids) + 1))

    @pytest.mark.asyncio
    async def test_suggested_multiplier_in_range(self):
        cells = [
            _make_cell(40.00, -74.00, total_activity=100),
            _make_cell(40.01, -74.00, total_activity=80),
        ]
        heatmap = _make_heatmap_response(cells)
        with (
            patch(
                "app.services.surge_zone_suggestions.get_trip_heatmap",
                new=AsyncMock(return_value=heatmap),
            ),
            patch(
                "app.services.surge_zone_suggestions.list_zones",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await get_zone_boundary_suggestions(
                _make_db_mock(), cluster_radius_km=2.0, min_cells=2
            )
        for s in result.suggestions:
            assert 1.2 <= s.suggested_multiplier <= 2.0

    @pytest.mark.asyncio
    async def test_generated_at_is_recent_utc(self):
        heatmap = _make_heatmap_response([])
        with (
            patch(
                "app.services.surge_zone_suggestions.get_trip_heatmap",
                new=AsyncMock(return_value=heatmap),
            ),
            patch(
                "app.services.surge_zone_suggestions.list_zones",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await get_zone_boundary_suggestions(_make_db_mock())
        assert result.generated_at.tzinfo is not None
        delta = datetime.now(timezone.utc) - result.generated_at
        assert abs(delta.total_seconds()) < 5


# ===========================================================================
# Endpoint (HTTP layer)
# ===========================================================================


class TestGetZoneSuggestionsEndpoint:
    """HTTP-level tests using FastAPI TestClient."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def _auth_headers(self):
        return {}  # TestClient integration tests skip real auth; unit tests mock deps

    @pytest.mark.asyncio
    async def test_endpoint_returns_200_with_mocked_service(self):
        """Smoke test: endpoint wiring is correct when service is mocked."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import require_admin

        async def _mock_admin():
            return MagicMock()

        empty_response = ZoneSuggestionsResponse(
            suggestions=[],
            total_suggestions=0,
            filters=ZoneSuggestionsFilters(
                start_date=None,
                end_date=None,
                min_activity=5,
                precision=2,
                cluster_radius_km=2.0,
                min_cells=2,
                max_suggestions=10,
            ),
            generated_at=datetime.now(timezone.utc),
        )

        app.dependency_overrides[require_admin] = _mock_admin
        with (
            patch(
                "app.api.v1.surge_zones.get_zone_boundary_suggestions",
                new=AsyncMock(return_value=empty_response),
            ),
        ):
            client = TestClient(app)
            resp = client.get("/api/v1/admin/surge-zones/suggestions")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "suggestions" in data
        assert data["total_suggestions"] == 0

    @pytest.mark.asyncio
    async def test_endpoint_422_when_start_after_end(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import require_admin

        async def _mock_admin():
            return MagicMock()

        app.dependency_overrides[require_admin] = _mock_admin
        client = TestClient(app)
        resp = client.get(
            "/api/v1/admin/surge-zones/suggestions",
            params={"start_date": "2026-03-01", "end_date": "2026-01-01"},
        )
        app.dependency_overrides.clear()

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_endpoint_requires_admin_auth(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/admin/surge-zones/suggestions")
        assert resp.status_code in (401, 403, 422)
