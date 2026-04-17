"""Tests for the trip demand heatmap feature.

Covers:
- resolution_degrees:        pure function for all resolutions
- resolution_decimal_places: pure function for all resolutions
- build_cell:                conversion with and without fare data
- get_demand_heatmap:        mocked DB — empty results, single cell, multiple cells,
                             date-window handling, hour/day filters
- GET /drivers/demand-heatmap           — driver endpoint (auth, params, response shape)
- GET /admin/analytics/demand-heatmap   — admin endpoint (auth, filters, validation)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.demand_heatmap import (
    MAX_LIMIT_ADMIN,
    MAX_LIMIT_DRIVER,
    build_cell,
    get_demand_heatmap,
    resolution_decimal_places,
    resolution_degrees,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(
    lat: float,
    lng: float,
    request_count: int = 10,
    completed_count: int = 8,
    avg_fare: float | None = 15.50,
    total_fare: float = 124.0,
    include_fare: bool = False,
) -> MagicMock:
    """Build a mock result row."""
    row = MagicMock()
    row.lat = Decimal(str(lat))
    row.lng = Decimal(str(lng))
    row.request_count = request_count
    row.completed_count = completed_count
    if include_fare:
        row.avg_fare = Decimal(str(avg_fare)) if avg_fare is not None else None
        row.total_fare = Decimal(str(total_fare))
    return row


def _mock_db(rows: list) -> AsyncMock:
    """Return an AsyncSession mock that returns *rows* from execute()."""
    result_mock = MagicMock()
    result_mock.fetchall.return_value = rows
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_mock)
    return db


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestResolutionDegrees:
    def test_low(self):
        assert resolution_degrees("low") == 0.1

    def test_medium(self):
        assert resolution_degrees("medium") == 0.01

    def test_high(self):
        assert resolution_degrees("high") == 0.001

    def test_unknown_falls_back_to_medium(self):
        assert resolution_degrees("unknown") == 0.01


class TestResolutionDecimalPlaces:
    def test_low(self):
        assert resolution_decimal_places("low") == 1

    def test_medium(self):
        assert resolution_decimal_places("medium") == 2

    def test_high(self):
        assert resolution_decimal_places("high") == 3

    def test_unknown_falls_back_to_medium(self):
        assert resolution_decimal_places("unknown") == 2


class TestBuildCell:
    def test_without_fare(self):
        row = _make_row(40.71, -74.00, request_count=20, completed_count=18)
        cell = build_cell(row, include_fare=False)
        assert cell == {
            "lat": 40.71,
            "lng": -74.00,
            "request_count": 20,
            "completed_count": 18,
        }
        assert "avg_fare" not in cell

    def test_with_fare(self):
        row = _make_row(
            40.71, -74.00, request_count=20, completed_count=18,
            avg_fare=18.75, total_fare=337.5, include_fare=True,
        )
        cell = build_cell(row, include_fare=True)
        assert cell["avg_fare"] == 18.75
        assert cell["total_fare"] == 337.5
        assert cell["request_count"] == 20

    def test_with_fare_null_avg(self):
        """Null avg_fare (no completed rides) should be None, not raise."""
        row = _make_row(
            40.71, -74.00, request_count=5, completed_count=0,
            avg_fare=None, total_fare=0.0, include_fare=True,
        )
        cell = build_cell(row, include_fare=True)
        assert cell["avg_fare"] is None
        assert cell["total_fare"] == 0.0

    def test_float_conversion(self):
        """Decimal values from DB should become plain floats."""
        row = _make_row(40.712345, -74.006789, include_fare=False)
        cell = build_cell(row, include_fare=False)
        assert isinstance(cell["lat"], float)
        assert isinstance(cell["lng"], float)

    def test_rounding_fare(self):
        """Fare values should be rounded to 2 decimal places."""
        row = _make_row(
            40.71, -74.00, avg_fare=18.7549999, total_fare=337.4999, include_fare=True
        )
        cell = build_cell(row, include_fare=True)
        assert cell["avg_fare"] == 18.75
        assert cell["total_fare"] == 337.5


# ---------------------------------------------------------------------------
# Service: get_demand_heatmap
# ---------------------------------------------------------------------------


class TestGetDemandHeatmap:
    @pytest.mark.anyio
    async def test_empty_results(self):
        db = _mock_db([])
        result = await get_demand_heatmap(
            db,
            start_date=date(2026, 4, 10),
            end_date=date(2026, 4, 17),
        )
        assert result["total_requests"] == 0
        assert result["total_cells"] == 0
        assert result["cells"] == []

    @pytest.mark.anyio
    async def test_single_cell_without_fare(self):
        rows = [_make_row(40.71, -74.00, request_count=50, completed_count=45)]
        db = _mock_db(rows)
        result = await get_demand_heatmap(
            db,
            start_date=date(2026, 4, 10),
            end_date=date(2026, 4, 17),
            include_fare=False,
        )
        assert result["total_requests"] == 50
        assert result["total_cells"] == 1
        assert result["cells"][0]["request_count"] == 50
        assert "avg_fare" not in result["cells"][0]

    @pytest.mark.anyio
    async def test_single_cell_with_fare(self):
        rows = [_make_row(40.71, -74.00, request_count=50, completed_count=45,
                          avg_fare=20.0, total_fare=900.0, include_fare=True)]
        db = _mock_db(rows)
        result = await get_demand_heatmap(
            db,
            start_date=date(2026, 4, 10),
            end_date=date(2026, 4, 17),
            include_fare=True,
        )
        cell = result["cells"][0]
        assert cell["avg_fare"] == 20.0
        assert cell["total_fare"] == 900.0

    @pytest.mark.anyio
    async def test_multiple_cells_total_requests_sum(self):
        rows = [
            _make_row(40.71, -74.00, request_count=100, completed_count=90),
            _make_row(40.72, -74.01, request_count=60, completed_count=55),
            _make_row(40.73, -74.02, request_count=30, completed_count=28),
        ]
        db = _mock_db(rows)
        result = await get_demand_heatmap(
            db,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 17),
        )
        assert result["total_requests"] == 190
        assert result["total_cells"] == 3

    @pytest.mark.anyio
    async def test_resolution_stored_in_result(self):
        db = _mock_db([])
        result = await get_demand_heatmap(
            db,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 7),
            resolution="low",
        )
        assert result["resolution"] == "low"
        assert result["resolution_degrees"] == 0.1

    @pytest.mark.anyio
    async def test_period_dates_echoed(self):
        start = date(2026, 4, 10)
        end = date(2026, 4, 17)
        db = _mock_db([])
        result = await get_demand_heatmap(db, start_date=start, end_date=end)
        assert result["period_start"] == start
        assert result["period_end"] == end

    @pytest.mark.anyio
    async def test_db_execute_called_once(self):
        db = _mock_db([])
        await get_demand_heatmap(db, start_date=date(2026, 4, 10), end_date=date(2026, 4, 17))
        db.execute.assert_called_once()

    @pytest.mark.anyio
    async def test_high_resolution_stores_correct_degrees(self):
        db = _mock_db([])
        result = await get_demand_heatmap(
            db,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 7),
            resolution="high",
        )
        assert result["resolution_degrees"] == 0.001

    @pytest.mark.anyio
    async def test_medium_resolution_default(self):
        db = _mock_db([])
        result = await get_demand_heatmap(
            db,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 7),
        )
        assert result["resolution_degrees"] == 0.01

    @pytest.mark.anyio
    async def test_cells_ordered_by_count_desc(self):
        """Cells are sorted highest demand first (DB ordering preserved)."""
        rows = [
            _make_row(40.71, -74.00, request_count=200, completed_count=180),
            _make_row(40.72, -74.01, request_count=50, completed_count=45),
        ]
        db = _mock_db(rows)
        result = await get_demand_heatmap(db, start_date=date(2026, 4, 1), end_date=date(2026, 4, 7))
        counts = [c["request_count"] for c in result["cells"]]
        assert counts == sorted(counts, reverse=True)

    @pytest.mark.anyio
    async def test_zero_completed_cell(self):
        rows = [_make_row(40.71, -74.00, request_count=5, completed_count=0,
                          avg_fare=None, total_fare=0.0, include_fare=True)]
        db = _mock_db(rows)
        result = await get_demand_heatmap(
            db,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 7),
            include_fare=True,
        )
        cell = result["cells"][0]
        assert cell["completed_count"] == 0
        assert cell["avg_fare"] is None


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


class TestDriverDemandHeatmapEndpoint:
    @pytest.mark.anyio
    async def test_requires_driver_auth(self, client):
        """No auth → 401."""
        resp = await client.get("/api/v1/drivers/demand-heatmap")
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_rider_cannot_access(self, client, rider_token):
        resp = await client.get(
            "/api/v1/drivers/demand-heatmap",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_driver_gets_200(self, client, driver_token):
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 11),
                "period_end": date(2026, 4, 17),
                "resolution": "medium",
                "resolution_degrees": 0.01,
                "total_requests": 0,
                "total_cells": 0,
                "cells": [],
            },
        ):
            resp = await client.get(
                "/api/v1/drivers/demand-heatmap",
                headers={"Authorization": f"Bearer {driver_token}"},
            )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_response_shape(self, client, driver_token):
        cells = [{"lat": 40.71, "lng": -74.00, "request_count": 50, "completed_count": 45}]
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 11),
                "period_end": date(2026, 4, 17),
                "resolution": "medium",
                "resolution_degrees": 0.01,
                "total_requests": 50,
                "total_cells": 1,
                "cells": cells,
            },
        ):
            resp = await client.get(
                "/api/v1/drivers/demand-heatmap",
                headers={"Authorization": f"Bearer {driver_token}"},
            )
        body = resp.json()
        assert body["total_requests"] == 50
        assert body["total_cells"] == 1
        assert body["cells"][0]["lat"] == 40.71
        assert "avg_fare" not in body["cells"][0]

    @pytest.mark.anyio
    async def test_days_param_accepted(self, client, driver_token):
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 4),
                "period_end": date(2026, 4, 17),
                "resolution": "medium",
                "resolution_degrees": 0.01,
                "total_requests": 0,
                "total_cells": 0,
                "cells": [],
            },
        ) as mock_fn:
            resp = await client.get(
                "/api/v1/drivers/demand-heatmap?days=14",
                headers={"Authorization": f"Bearer {driver_token}"},
            )
        assert resp.status_code == 200
        call_kwargs = mock_fn.call_args.kwargs
        assert call_kwargs["limit"] == 100  # default

    @pytest.mark.anyio
    async def test_days_out_of_range_rejected(self, client, driver_token):
        resp = await client.get(
            "/api/v1/drivers/demand-heatmap?days=31",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_resolution_low_accepted(self, client, driver_token):
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 11),
                "period_end": date(2026, 4, 17),
                "resolution": "low",
                "resolution_degrees": 0.1,
                "total_requests": 0,
                "total_cells": 0,
                "cells": [],
            },
        ) as mock_fn:
            resp = await client.get(
                "/api/v1/drivers/demand-heatmap?resolution=low",
                headers={"Authorization": f"Bearer {driver_token}"},
            )
        assert resp.status_code == 200
        assert mock_fn.call_args.kwargs["resolution"] == "low"

    @pytest.mark.anyio
    async def test_limit_capped_at_max(self, client, driver_token):
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 11),
                "period_end": date(2026, 4, 17),
                "resolution": "medium",
                "resolution_degrees": 0.01,
                "total_requests": 0,
                "total_cells": 0,
                "cells": [],
            },
        ):
            resp = await client.get(
                f"/api/v1/drivers/demand-heatmap?limit={MAX_LIMIT_DRIVER + 1}",
                headers={"Authorization": f"Bearer {driver_token}"},
            )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_response_has_no_fare_fields(self, client, driver_token):
        """Driver response schema must not expose fare data."""
        cells = [{"lat": 40.71, "lng": -74.00, "request_count": 30, "completed_count": 28}]
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 11),
                "period_end": date(2026, 4, 17),
                "resolution": "medium",
                "resolution_degrees": 0.01,
                "total_requests": 30,
                "total_cells": 1,
                "cells": cells,
            },
        ):
            resp = await client.get(
                "/api/v1/drivers/demand-heatmap",
                headers={"Authorization": f"Bearer {driver_token}"},
            )
        body = resp.json()
        for cell in body["cells"]:
            assert "avg_fare" not in cell
            assert "total_fare" not in cell


class TestAdminDemandHeatmapEndpoint:
    @pytest.mark.anyio
    async def test_requires_admin_auth(self, client):
        resp = await client.get("/api/v1/admin/analytics/demand-heatmap")
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_driver_cannot_access(self, client, driver_token):
        resp = await client.get(
            "/api/v1/admin/analytics/demand-heatmap",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_rider_cannot_access(self, client, rider_token):
        resp = await client.get(
            "/api/v1/admin/analytics/demand-heatmap",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_admin_gets_200(self, client, admin_token):
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 11),
                "period_end": date(2026, 4, 17),
                "resolution": "medium",
                "resolution_degrees": 0.01,
                "total_requests": 0,
                "total_cells": 0,
                "cells": [],
            },
        ):
            resp = await client.get(
                "/api/v1/admin/analytics/demand-heatmap",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_response_includes_fare_fields(self, client, admin_token):
        cells = [
            {
                "lat": 40.71, "lng": -74.00,
                "request_count": 100, "completed_count": 90,
                "avg_fare": 18.50, "total_fare": 1665.0,
            }
        ]
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 11),
                "period_end": date(2026, 4, 17),
                "resolution": "medium",
                "resolution_degrees": 0.01,
                "total_requests": 100,
                "total_cells": 1,
                "cells": cells,
            },
        ):
            resp = await client.get(
                "/api/v1/admin/analytics/demand-heatmap",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        body = resp.json()
        assert body["cells"][0]["avg_fare"] == 18.50
        assert body["cells"][0]["total_fare"] == 1665.0

    @pytest.mark.anyio
    async def test_response_includes_filters_applied(self, client, admin_token):
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 11),
                "period_end": date(2026, 4, 17),
                "resolution": "medium",
                "resolution_degrees": 0.01,
                "total_requests": 0,
                "total_cells": 0,
                "cells": [],
            },
        ):
            resp = await client.get(
                "/api/v1/admin/analytics/demand-heatmap",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        body = resp.json()
        assert "filters_applied" in body
        assert "period_start" in body["filters_applied"]
        assert "resolution" in body["filters_applied"]

    @pytest.mark.anyio
    async def test_explicit_date_range(self, client, admin_token):
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 1),
                "period_end": date(2026, 4, 10),
                "resolution": "medium",
                "resolution_degrees": 0.01,
                "total_requests": 0,
                "total_cells": 0,
                "cells": [],
            },
        ) as mock_fn:
            resp = await client.get(
                "/api/v1/admin/analytics/demand-heatmap"
                "?start_date=2026-04-01&end_date=2026-04-10",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert resp.status_code == 200
        kwargs = mock_fn.call_args.kwargs
        assert kwargs["start_date"] == date(2026, 4, 1)
        assert kwargs["end_date"] == date(2026, 4, 10)

    @pytest.mark.anyio
    async def test_start_date_without_end_date_rejected(self, client, admin_token):
        resp = await client.get(
            "/api/v1/admin/analytics/demand-heatmap?start_date=2026-04-01",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_end_date_before_start_date_rejected(self, client, admin_token):
        resp = await client.get(
            "/api/v1/admin/analytics/demand-heatmap"
            "?start_date=2026-04-10&end_date=2026-04-01",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_hour_start_gt_hour_end_rejected(self, client, admin_token):
        resp = await client.get(
            "/api/v1/admin/analytics/demand-heatmap?hour_start=18&hour_end=8",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_day_of_week_filter_passed_to_service(self, client, admin_token):
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 11),
                "period_end": date(2026, 4, 17),
                "resolution": "medium",
                "resolution_degrees": 0.01,
                "total_requests": 0,
                "total_cells": 0,
                "cells": [],
            },
        ) as mock_fn:
            resp = await client.get(
                "/api/v1/admin/analytics/demand-heatmap?day_of_week=4",  # Friday
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert resp.status_code == 200
        # Friday = 0-based 4 → ISODOW 5
        assert mock_fn.call_args.kwargs["day_of_week"] == 5

    @pytest.mark.anyio
    async def test_day_of_week_0_maps_to_isodow_1(self, client, admin_token):
        """Monday (0) should map to ISODOW 1."""
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 11),
                "period_end": date(2026, 4, 17),
                "resolution": "medium",
                "resolution_degrees": 0.01,
                "total_requests": 0,
                "total_cells": 0,
                "cells": [],
            },
        ) as mock_fn:
            await client.get(
                "/api/v1/admin/analytics/demand-heatmap?day_of_week=0",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert mock_fn.call_args.kwargs["day_of_week"] == 1

    @pytest.mark.anyio
    async def test_day_of_week_6_maps_to_isodow_7(self, client, admin_token):
        """Sunday (6) should map to ISODOW 7."""
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 11),
                "period_end": date(2026, 4, 17),
                "resolution": "medium",
                "resolution_degrees": 0.01,
                "total_requests": 0,
                "total_cells": 0,
                "cells": [],
            },
        ) as mock_fn:
            await client.get(
                "/api/v1/admin/analytics/demand-heatmap?day_of_week=6",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert mock_fn.call_args.kwargs["day_of_week"] == 7

    @pytest.mark.anyio
    async def test_day_of_week_out_of_range_rejected(self, client, admin_token):
        resp = await client.get(
            "/api/v1/admin/analytics/demand-heatmap?day_of_week=7",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_hour_filters_passed_to_service(self, client, admin_token):
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 11),
                "period_end": date(2026, 4, 17),
                "resolution": "medium",
                "resolution_degrees": 0.01,
                "total_requests": 0,
                "total_cells": 0,
                "cells": [],
            },
        ) as mock_fn:
            await client.get(
                "/api/v1/admin/analytics/demand-heatmap?hour_start=7&hour_end=10",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        kwargs = mock_fn.call_args.kwargs
        assert kwargs["hour_start"] == 7
        assert kwargs["hour_end"] == 10

    @pytest.mark.anyio
    async def test_limit_out_of_range_rejected(self, client, admin_token):
        resp = await client.get(
            f"/api/v1/admin/analytics/demand-heatmap?limit={MAX_LIMIT_ADMIN + 1}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_days_lookback_default(self, client, admin_token):
        """When no start/end_date, days=7 → 7-day window ending today."""
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 11),
                "period_end": date(2026, 4, 17),
                "resolution": "medium",
                "resolution_degrees": 0.01,
                "total_requests": 0,
                "total_cells": 0,
                "cells": [],
            },
        ) as mock_fn:
            resp = await client.get(
                "/api/v1/admin/analytics/demand-heatmap",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert resp.status_code == 200
        kwargs = mock_fn.call_args.kwargs
        span = (kwargs["end_date"] - kwargs["start_date"]).days
        assert span == 6  # 7 days inclusive → span of 6

    @pytest.mark.anyio
    async def test_include_fare_passed_as_true(self, client, admin_token):
        """Admin endpoint must always request fare data."""
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 11),
                "period_end": date(2026, 4, 17),
                "resolution": "medium",
                "resolution_degrees": 0.01,
                "total_requests": 0,
                "total_cells": 0,
                "cells": [],
            },
        ) as mock_fn:
            await client.get(
                "/api/v1/admin/analytics/demand-heatmap",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert mock_fn.call_args.kwargs["include_fare"] is True

    @pytest.mark.anyio
    async def test_driver_endpoint_does_not_include_fare(self, client, driver_token):
        """Driver endpoint must NOT request fare data."""
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 11),
                "period_end": date(2026, 4, 17),
                "resolution": "medium",
                "resolution_degrees": 0.01,
                "total_requests": 0,
                "total_cells": 0,
                "cells": [],
            },
        ) as mock_fn:
            await client.get(
                "/api/v1/drivers/demand-heatmap",
                headers={"Authorization": f"Bearer {driver_token}"},
            )
        assert mock_fn.call_args.kwargs["include_fare"] is False

    @pytest.mark.anyio
    async def test_high_resolution_accepted(self, client, admin_token):
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 11),
                "period_end": date(2026, 4, 17),
                "resolution": "high",
                "resolution_degrees": 0.001,
                "total_requests": 0,
                "total_cells": 0,
                "cells": [],
            },
        ) as mock_fn:
            resp = await client.get(
                "/api/v1/admin/analytics/demand-heatmap?resolution=high",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert resp.status_code == 200
        assert mock_fn.call_args.kwargs["resolution"] == "high"

    @pytest.mark.anyio
    async def test_null_avg_fare_cell_serialized(self, client, admin_token):
        """avg_fare=None in a cell should serialize to null, not raise."""
        cells = [
            {
                "lat": 40.71, "lng": -74.00,
                "request_count": 5, "completed_count": 0,
                "avg_fare": None, "total_fare": 0.0,
            }
        ]
        with patch(
            "app.api.v1.demand_heatmap.get_demand_heatmap",
            new_callable=AsyncMock,
            return_value={
                "period_start": date(2026, 4, 11),
                "period_end": date(2026, 4, 17),
                "resolution": "medium",
                "resolution_degrees": 0.01,
                "total_requests": 5,
                "total_cells": 1,
                "cells": cells,
            },
        ):
            resp = await client.get(
                "/api/v1/admin/analytics/demand-heatmap",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["cells"][0]["avg_fare"] is None
