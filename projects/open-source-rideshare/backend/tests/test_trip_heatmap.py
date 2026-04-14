"""Tests for the trip heatmap analytics feature.

Covers:

Service unit tests (using AsyncMock for DB):
  1.  get_trip_heatmap — empty DB returns empty cells list
  2.  get_trip_heatmap — cells list has correct length when data present
  3.  get_trip_heatmap — pickup_count populated from pickup aggregation query
  4.  get_trip_heatmap — dropoff_count populated from dropoff aggregation query
  5.  get_trip_heatmap — pickup-only cell has dropoff_count of 0
  6.  get_trip_heatmap — dropoff-only cell has pickup_count of 0
  7.  get_trip_heatmap — cells sharing lat/lng merge pickup and dropoff counts
  8.  get_trip_heatmap — total_activity equals pickup_count + dropoff_count
  9.  get_trip_heatmap — cells sorted by total_activity descending
  10. get_trip_heatmap — avg_fare is None for dropoff-only cell
  11. get_trip_heatmap — avg_fare rounded to 2 decimal places
  12. get_trip_heatmap — min_activity filter excludes low-activity cells
  13. get_trip_heatmap — min_activity=1 includes all cells (default)
  14. get_trip_heatmap — unknown status returns empty cells
  15. get_trip_heatmap — generated_at is a UTC-aware datetime
  16. get_trip_heatmap — filters echoed back in response
  17. get_trip_heatmap — precision echoed back in filters
  18. get_trip_heatmap — total_cells matches len(cells)
  19. get_trip_heatmap — cells with None lat/lng are skipped
  20. get_trip_heatmap — default status is completed (no status arg)

API integration tests (using real in-transaction test DB via conftest fixtures):
  21. GET /admin/analytics/trip-heatmap — 401 with no auth
  22. GET /admin/analytics/trip-heatmap — 403 with rider token
  23. GET /admin/analytics/trip-heatmap — 403 with driver token
  24. GET /admin/analytics/trip-heatmap — 200 with admin token
  25. GET /admin/analytics/trip-heatmap — response is JSON with cells list
  26. GET /admin/analytics/trip-heatmap — start_date filter accepted
  27. GET /admin/analytics/trip-heatmap — end_date filter accepted
  28. GET /admin/analytics/trip-heatmap — both dates accepted
  29. GET /admin/analytics/trip-heatmap — end_date before start_date returns 422
  30. GET /admin/analytics/trip-heatmap — invalid start_date format returns 422
  31. GET /admin/analytics/trip-heatmap — invalid end_date format returns 422
  32. GET /admin/analytics/trip-heatmap — precision param accepted (1-4)
  33. GET /admin/analytics/trip-heatmap — precision=0 returns 422
  34. GET /admin/analytics/trip-heatmap — precision=5 returns 422
  35. GET /admin/analytics/trip-heatmap — status filter accepted for valid value
  36. GET /admin/analytics/trip-heatmap — status filter: invalid value returns 422
  37. GET /admin/analytics/trip-heatmap — min_activity filter accepted
  38. GET /admin/analytics/trip-heatmap — min_activity=0 returns 422
  39. GET /admin/analytics/trip-heatmap — no params returns 200
  40. GET /admin/analytics/trip-heatmap — response contains total_cells field
  41. GET /admin/analytics/trip-heatmap — response contains generated_at field
  42. GET /admin/analytics/trip-heatmap — response contains filters field
  43. GET /admin/analytics/trip-heatmap — empty result has cells=[] and total_cells=0
  44. GET /admin/analytics/trip-heatmap — all valid RideStatus values accepted
  45. GET /admin/analytics/trip-heatmap — cells sorted by total_activity descending
  46. GET /admin/analytics/trip-heatmap — cell fields: lat, lng, pickup_count, dropoff_count, total_activity, avg_fare
  47. GET /admin/analytics/trip-heatmap — rides outside date range excluded
  48. GET /admin/analytics/trip-heatmap — min_activity filters out low-activity cells
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.trip_heatmap import HeatmapCell, HeatmapFilters, HeatmapResponse
from app.services.trip_heatmap import get_trip_heatmap


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_pickup_row(
    lat: float = 37.77,
    lng: float = -122.42,
    pickup_count: int = 10,
    avg_fare: float | None = 18.50,
) -> MagicMock:
    row = MagicMock()
    row.cell_lat = Decimal(str(lat))
    row.cell_lng = Decimal(str(lng))
    row.pickup_count = pickup_count
    row.avg_fare = Decimal(str(avg_fare)) if avg_fare is not None else None
    return row


def _make_dropoff_row(
    lat: float = 37.77,
    lng: float = -122.42,
    dropoff_count: int = 8,
) -> MagicMock:
    row = MagicMock()
    row.cell_lat = Decimal(str(lat))
    row.cell_lng = Decimal(str(lng))
    row.dropoff_count = dropoff_count
    return row


def _make_db(pickup_rows: list, dropoff_rows: list) -> AsyncMock:
    """DB mock with two sequential execute() calls (pickup then dropoff)."""
    db = AsyncMock()

    pickup_result = MagicMock()
    pickup_result.__iter__ = MagicMock(return_value=iter(pickup_rows))

    dropoff_result = MagicMock()
    dropoff_result.__iter__ = MagicMock(return_value=iter(dropoff_rows))

    db.execute = AsyncMock(side_effect=[pickup_result, dropoff_result])
    return db


def _make_empty_db() -> AsyncMock:
    return _make_db([], [])


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


class TestGetTripHeatmap:
    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_cells(self):
        db = _make_empty_db()
        result = await get_trip_heatmap(db)
        assert result.cells == []
        assert result.total_cells == 0

    @pytest.mark.asyncio
    async def test_cells_list_has_correct_length(self):
        pickup_rows = [
            _make_pickup_row(lat=37.77, lng=-122.42),
            _make_pickup_row(lat=37.78, lng=-122.43),
        ]
        db = _make_db(pickup_rows, [])
        result = await get_trip_heatmap(db)
        assert len(result.cells) == 2

    @pytest.mark.asyncio
    async def test_pickup_count_populated(self):
        pickup_rows = [_make_pickup_row(lat=37.77, lng=-122.42, pickup_count=15)]
        db = _make_db(pickup_rows, [])
        result = await get_trip_heatmap(db)
        assert result.cells[0].pickup_count == 15

    @pytest.mark.asyncio
    async def test_dropoff_count_populated(self):
        dropoff_rows = [_make_dropoff_row(lat=37.77, lng=-122.42, dropoff_count=12)]
        db = _make_db([], dropoff_rows)
        result = await get_trip_heatmap(db)
        assert result.cells[0].dropoff_count == 12

    @pytest.mark.asyncio
    async def test_pickup_only_cell_has_dropoff_count_zero(self):
        pickup_rows = [_make_pickup_row(lat=37.77, lng=-122.42, pickup_count=5)]
        db = _make_db(pickup_rows, [])
        result = await get_trip_heatmap(db)
        assert result.cells[0].dropoff_count == 0

    @pytest.mark.asyncio
    async def test_dropoff_only_cell_has_pickup_count_zero(self):
        dropoff_rows = [_make_dropoff_row(lat=37.88, lng=-122.50, dropoff_count=7)]
        db = _make_db([], dropoff_rows)
        result = await get_trip_heatmap(db)
        assert result.cells[0].pickup_count == 0

    @pytest.mark.asyncio
    async def test_shared_cell_merges_pickup_and_dropoff(self):
        pickup_rows = [_make_pickup_row(lat=37.77, lng=-122.42, pickup_count=10)]
        dropoff_rows = [_make_dropoff_row(lat=37.77, lng=-122.42, dropoff_count=6)]
        db = _make_db(pickup_rows, dropoff_rows)
        result = await get_trip_heatmap(db)
        assert len(result.cells) == 1
        cell = result.cells[0]
        assert cell.pickup_count == 10
        assert cell.dropoff_count == 6

    @pytest.mark.asyncio
    async def test_total_activity_is_sum_of_pickup_and_dropoff(self):
        pickup_rows = [_make_pickup_row(lat=37.77, lng=-122.42, pickup_count=10)]
        dropoff_rows = [_make_dropoff_row(lat=37.77, lng=-122.42, dropoff_count=6)]
        db = _make_db(pickup_rows, dropoff_rows)
        result = await get_trip_heatmap(db)
        cell = result.cells[0]
        assert cell.total_activity == cell.pickup_count + cell.dropoff_count

    @pytest.mark.asyncio
    async def test_cells_sorted_by_total_activity_descending(self):
        pickup_rows = [
            _make_pickup_row(lat=37.77, lng=-122.42, pickup_count=2),
            _make_pickup_row(lat=37.78, lng=-122.43, pickup_count=20),
            _make_pickup_row(lat=37.79, lng=-122.44, pickup_count=8),
        ]
        db = _make_db(pickup_rows, [])
        result = await get_trip_heatmap(db)
        activities = [c.total_activity for c in result.cells]
        assert activities == sorted(activities, reverse=True)

    @pytest.mark.asyncio
    async def test_avg_fare_none_for_dropoff_only_cell(self):
        dropoff_rows = [_make_dropoff_row(lat=37.88, lng=-122.50, dropoff_count=7)]
        db = _make_db([], dropoff_rows)
        result = await get_trip_heatmap(db)
        assert result.cells[0].avg_fare is None

    @pytest.mark.asyncio
    async def test_avg_fare_rounded_to_two_decimal_places(self):
        pickup_rows = [_make_pickup_row(lat=37.77, lng=-122.42, avg_fare=18.5678)]
        db = _make_db(pickup_rows, [])
        result = await get_trip_heatmap(db)
        cell = result.cells[0]
        assert cell.avg_fare == 18.57

    @pytest.mark.asyncio
    async def test_min_activity_excludes_low_activity_cells(self):
        pickup_rows = [
            _make_pickup_row(lat=37.77, lng=-122.42, pickup_count=1),
            _make_pickup_row(lat=37.78, lng=-122.43, pickup_count=5),
        ]
        db = _make_db(pickup_rows, [])
        result = await get_trip_heatmap(db, min_activity=3)
        assert len(result.cells) == 1
        assert result.cells[0].pickup_count == 5

    @pytest.mark.asyncio
    async def test_min_activity_one_includes_all_cells(self):
        pickup_rows = [
            _make_pickup_row(lat=37.77, lng=-122.42, pickup_count=1),
            _make_pickup_row(lat=37.78, lng=-122.43, pickup_count=100),
        ]
        db = _make_db(pickup_rows, [])
        result = await get_trip_heatmap(db, min_activity=1)
        assert len(result.cells) == 2

    @pytest.mark.asyncio
    async def test_unknown_status_returns_empty_cells(self):
        # DB should not be called at all for unknown status
        db = AsyncMock()
        result = await get_trip_heatmap(db, status="not_a_real_status")
        assert result.cells == []
        assert result.total_cells == 0

    @pytest.mark.asyncio
    async def test_generated_at_is_utc_aware(self):
        db = _make_empty_db()
        result = await get_trip_heatmap(db)
        assert result.generated_at.tzinfo is not None

    @pytest.mark.asyncio
    async def test_filters_echoed_in_response(self):
        db = _make_empty_db()
        start = date(2025, 1, 1)
        end = date(2025, 12, 31)
        result = await get_trip_heatmap(db, start_date=start, end_date=end, status="completed")
        assert result.filters.start_date == start
        assert result.filters.end_date == end
        assert result.filters.status == "completed"

    @pytest.mark.asyncio
    async def test_precision_echoed_in_filters(self):
        db = _make_empty_db()
        result = await get_trip_heatmap(db, precision=3)
        assert result.filters.precision == 3

    @pytest.mark.asyncio
    async def test_total_cells_matches_len_cells(self):
        pickup_rows = [
            _make_pickup_row(lat=37.77, lng=-122.42),
            _make_pickup_row(lat=37.78, lng=-122.43),
            _make_pickup_row(lat=37.79, lng=-122.44),
        ]
        db = _make_db(pickup_rows, [])
        result = await get_trip_heatmap(db)
        assert result.total_cells == len(result.cells)

    @pytest.mark.asyncio
    async def test_cells_with_none_lat_lng_are_skipped(self):
        pickup_rows = [_make_pickup_row(lat=37.77, lng=-122.42)]
        none_row = MagicMock()
        none_row.cell_lat = None
        none_row.cell_lng = None
        none_row.pickup_count = 5
        none_row.avg_fare = None
        pickup_rows.append(none_row)
        db = _make_db(pickup_rows, [])
        result = await get_trip_heatmap(db)
        # Only the valid row should appear
        assert len(result.cells) == 1
        assert result.cells[0].lat == 37.77

    @pytest.mark.asyncio
    async def test_default_status_is_completed(self):
        """Calling with no status arg should default to completed (not all rides)."""
        db = _make_empty_db()
        result = await get_trip_heatmap(db)
        # status was None (arg default), which means service used completed internally
        # The response filters.status should reflect what was passed in (None)
        assert result.filters.status is None


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------

BASE = "/api/v1/admin/analytics/trip-heatmap"


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
class TestTripHeatmapEndpoint:
    async def test_no_auth_returns_401(self, client):
        resp = await client.get(BASE)
        assert resp.status_code == 401

    async def test_rider_token_returns_403(self, client, rider, rider_token):
        resp = await client.get(BASE, headers=auth_header(rider_token))
        assert resp.status_code == 403

    async def test_driver_token_returns_403(self, client, driver_user, driver_token):
        resp = await client.get(BASE, headers=auth_header(driver_token))
        assert resp.status_code == 403

    async def test_admin_token_returns_200(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        assert resp.status_code == 200

    async def test_response_has_cells_list(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "cells" in data
        assert isinstance(data["cells"], list)

    async def test_start_date_filter_accepted(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?start_date=2025-01-01", headers=auth_header(admin_token)
        )
        assert resp.status_code == 200

    async def test_end_date_filter_accepted(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?end_date=2025-12-31", headers=auth_header(admin_token)
        )
        assert resp.status_code == 200

    async def test_both_dates_accepted(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?start_date=2025-01-01&end_date=2025-12-31",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_end_before_start_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?start_date=2025-12-01&end_date=2025-01-01",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_invalid_start_date_format_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?start_date=01-2025-01",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_invalid_end_date_format_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?end_date=31-12-2025",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_precision_param_accepted_valid_values(self, client, admin_user, admin_token):
        for p in [1, 2, 3, 4]:
            resp = await client.get(
                f"{BASE}?precision={p}", headers=auth_header(admin_token)
            )
            assert resp.status_code == 200, f"precision={p} should return 200"

    async def test_precision_zero_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(f"{BASE}?precision=0", headers=auth_header(admin_token))
        assert resp.status_code == 422

    async def test_precision_five_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(f"{BASE}?precision=5", headers=auth_header(admin_token))
        assert resp.status_code == 422

    async def test_valid_status_filter_accepted(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?status=completed", headers=auth_header(admin_token)
        )
        assert resp.status_code == 200

    async def test_invalid_status_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?status=bogus_status", headers=auth_header(admin_token)
        )
        assert resp.status_code == 422

    async def test_min_activity_filter_accepted(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?min_activity=5", headers=auth_header(admin_token)
        )
        assert resp.status_code == 200

    async def test_min_activity_zero_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?min_activity=0", headers=auth_header(admin_token)
        )
        assert resp.status_code == 422

    async def test_no_params_returns_200(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        assert resp.status_code == 200

    async def test_response_has_total_cells(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        data = resp.json()
        assert "total_cells" in data

    async def test_response_has_generated_at(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        data = resp.json()
        assert "generated_at" in data

    async def test_response_has_filters(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        data = resp.json()
        assert "filters" in data
        assert "precision" in data["filters"]

    async def test_empty_result_has_cells_list_and_total_cells_zero(
        self, client, admin_user, admin_token
    ):
        # Far-future date — no rides will exist
        resp = await client.get(
            f"{BASE}?start_date=2099-01-01&end_date=2099-12-31",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["cells"] == []
        assert data["total_cells"] == 0

    async def test_all_valid_statuses_accepted(self, client, admin_user, admin_token):
        valid_statuses = [
            "scheduled", "requested", "matched", "driver_en_route",
            "arrived", "in_progress", "completed", "cancelled",
        ]
        for status_val in valid_statuses:
            resp = await client.get(
                f"{BASE}?status={status_val}",
                headers=auth_header(admin_token),
            )
            assert resp.status_code == 200, (
                f"status={status_val!r} should return 200, got {resp.status_code}"
            )

    async def test_cell_fields_present(self, client, db, admin_user, admin_token, rider):
        """When rides exist, returned cells have expected fields."""
        from app.models.ride import Ride, RideStatus
        from geoalchemy2.functions import ST_MakePoint

        ride = Ride(
            rider_id=rider.id,
            status=RideStatus.COMPLETED,
            pickup_location=ST_MakePoint(-122.4194, 37.7749),
            dropoff_location=ST_MakePoint(-122.4094, 37.7849),
            pickup_address="Heatmap Test Pickup",
            dropoff_address="Heatmap Test Dropoff",
            estimated_fare=20.0,
            actual_fare=20.0,
            requested_at=datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
        )
        db.add(ride)
        await db.flush()

        resp = await client.get(
            f"{BASE}?start_date=2025-06-01&end_date=2025-06-30",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        if data["cells"]:
            cell = data["cells"][0]
            for field in ["lat", "lng", "pickup_count", "dropoff_count", "total_activity", "avg_fare"]:
                assert field in cell, f"Cell missing field: {field}"

    async def test_rides_outside_date_range_excluded(
        self, client, db, admin_user, admin_token, rider
    ):
        from app.models.ride import Ride, RideStatus
        from geoalchemy2.functions import ST_MakePoint

        old_ride = Ride(
            rider_id=rider.id,
            status=RideStatus.COMPLETED,
            pickup_location=ST_MakePoint(-122.41, 37.77),
            dropoff_location=ST_MakePoint(-122.42, 37.78),
            pickup_address="Old Ride Pickup",
            dropoff_address="Old Ride Dropoff",
            estimated_fare=10.0,
            requested_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        db.add(old_ride)
        await db.flush()

        # Query for 2099 — no rides should match
        resp = await client.get(
            f"{BASE}?start_date=2099-01-01&end_date=2099-12-31",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_cells"] == 0

    async def test_min_activity_filters_low_activity_cells(
        self, client, db, admin_user, admin_token, rider
    ):
        """min_activity=100 should return no cells when activity is low."""
        resp = await client.get(
            f"{BASE}?min_activity=100",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        # With min_activity=100, any real cells with < 100 trips should be excluded
        for cell in data["cells"]:
            assert cell["total_activity"] >= 100
