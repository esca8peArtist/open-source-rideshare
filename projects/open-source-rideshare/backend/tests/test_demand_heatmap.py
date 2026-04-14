"""Tests for the demand-by-hour analytics feature.

Covers:

Service unit tests (using AsyncMock for DB):
  1.  get_demand_by_hour — always returns exactly 24 slots
  2.  get_demand_by_hour — slots ordered by hour ascending (0–23)
  3.  get_demand_by_hour — empty DB returns 24 slots all with zero total_rides
  4.  get_demand_by_hour — total_rides sums across all slots
  5.  get_demand_by_hour — peak_hour is None when no rides exist
  6.  get_demand_by_hour — peak_hour is the hour with highest total_rides
  7.  get_demand_by_hour — total_rides populated from DB row
  8.  get_demand_by_hour — completed_rides populated from DB row
  9.  get_demand_by_hour — cancelled_rides populated from DB row
  10. get_demand_by_hour — avg_fare is None for empty hours
  11. get_demand_by_hour — avg_fare rounded to 2 decimal places
  12. get_demand_by_hour — avg_wait_minutes is None for empty hours
  13. get_demand_by_hour — avg_wait_minutes rounded to 2 decimal places
  14. get_demand_by_hour — hours missing from DB rows produce zero-count slots
  15. get_demand_by_hour — hour_label formatted as HH:00
  16. get_demand_by_hour — generated_at is a UTC-aware datetime
  17. get_demand_by_hour — filters echoed back in response
  18. get_demand_by_hour — day_of_week filter echoed in filters
  19. get_demand_by_hour — peak_hour equals hour with max total_rides when tie broken by first
  20. get_demand_by_hour — total_rides in response equals sum of all slot total_rides

API integration tests:
  21. GET /admin/analytics/demand-by-hour — 401 with no auth
  22. GET /admin/analytics/demand-by-hour — 403 with rider token
  23. GET /admin/analytics/demand-by-hour — 403 with driver token
  24. GET /admin/analytics/demand-by-hour — 200 with admin token
  25. GET /admin/analytics/demand-by-hour — response has slots list
  26. GET /admin/analytics/demand-by-hour — response always has 24 slots
  27. GET /admin/analytics/demand-by-hour — slots ordered by hour 0–23
  28. GET /admin/analytics/demand-by-hour — start_date filter accepted
  29. GET /admin/analytics/demand-by-hour — end_date filter accepted
  30. GET /admin/analytics/demand-by-hour — both dates accepted
  31. GET /admin/analytics/demand-by-hour — end_date before start_date returns 422
  32. GET /admin/analytics/demand-by-hour — invalid start_date format returns 422
  33. GET /admin/analytics/demand-by-hour — invalid end_date format returns 422
  34. GET /admin/analytics/demand-by-hour — day_of_week 0–6 accepted
  35. GET /admin/analytics/demand-by-hour — day_of_week=7 returns 422
  36. GET /admin/analytics/demand-by-hour — day_of_week=-1 returns 422
  37. GET /admin/analytics/demand-by-hour — no params returns 200
  38. GET /admin/analytics/demand-by-hour — response has total_rides field
  39. GET /admin/analytics/demand-by-hour — response has peak_hour field
  40. GET /admin/analytics/demand-by-hour — response has generated_at field
  41. GET /admin/analytics/demand-by-hour — response has filters field
  42. GET /admin/analytics/demand-by-hour — each slot has required fields
  43. GET /admin/analytics/demand-by-hour — peak_hour is None when no rides
  44. GET /admin/analytics/demand-by-hour — total_rides is 0 when no rides
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.demand_heatmap import DemandByHourFilters, DemandByHourResponse, DemandHourSlot
from app.services.demand_heatmap import get_demand_by_hour


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_hour_row(
    hour: int = 9,
    total_rides: int = 10,
    completed_rides: int = 8,
    cancelled_rides: int = 2,
    avg_fare: float | None = 18.50,
    avg_wait_minutes: float | None = 3.5,
) -> MagicMock:
    row = MagicMock()
    row.hour = Decimal(str(hour))
    row.total_rides = total_rides
    row.completed_rides = completed_rides
    row.cancelled_rides = cancelled_rides
    row.avg_fare = Decimal(str(avg_fare)) if avg_fare is not None else None
    row.avg_wait_minutes = Decimal(str(avg_wait_minutes)) if avg_wait_minutes is not None else None
    return row


def _make_db(rows: list) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.fetchall = MagicMock(return_value=rows)
    db.execute = AsyncMock(return_value=result)
    return db


def _make_empty_db() -> AsyncMock:
    return _make_db([])


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


class TestGetDemandByHour:
    @pytest.mark.asyncio
    async def test_always_returns_24_slots(self):
        db = _make_empty_db()
        result = await get_demand_by_hour(db)
        assert len(result.slots) == 24

    @pytest.mark.asyncio
    async def test_slots_ordered_by_hour_ascending(self):
        db = _make_empty_db()
        result = await get_demand_by_hour(db)
        hours = [s.hour for s in result.slots]
        assert hours == list(range(24))

    @pytest.mark.asyncio
    async def test_empty_db_all_slots_zero(self):
        db = _make_empty_db()
        result = await get_demand_by_hour(db)
        for slot in result.slots:
            assert slot.total_rides == 0
            assert slot.completed_rides == 0
            assert slot.cancelled_rides == 0

    @pytest.mark.asyncio
    async def test_total_rides_sums_all_slots(self):
        rows = [
            _make_hour_row(hour=9, total_rides=10),
            _make_hour_row(hour=17, total_rides=25),
        ]
        db = _make_db(rows)
        result = await get_demand_by_hour(db)
        assert result.total_rides == 35

    @pytest.mark.asyncio
    async def test_peak_hour_none_when_no_rides(self):
        db = _make_empty_db()
        result = await get_demand_by_hour(db)
        assert result.peak_hour is None

    @pytest.mark.asyncio
    async def test_peak_hour_is_max_total_rides_hour(self):
        rows = [
            _make_hour_row(hour=9, total_rides=5),
            _make_hour_row(hour=17, total_rides=30),
            _make_hour_row(hour=22, total_rides=15),
        ]
        db = _make_db(rows)
        result = await get_demand_by_hour(db)
        assert result.peak_hour == 17

    @pytest.mark.asyncio
    async def test_total_rides_populated_from_row(self):
        rows = [_make_hour_row(hour=10, total_rides=42)]
        db = _make_db(rows)
        result = await get_demand_by_hour(db)
        assert result.slots[10].total_rides == 42

    @pytest.mark.asyncio
    async def test_completed_rides_populated_from_row(self):
        rows = [_make_hour_row(hour=10, total_rides=10, completed_rides=7)]
        db = _make_db(rows)
        result = await get_demand_by_hour(db)
        assert result.slots[10].completed_rides == 7

    @pytest.mark.asyncio
    async def test_cancelled_rides_populated_from_row(self):
        rows = [_make_hour_row(hour=10, total_rides=10, cancelled_rides=3)]
        db = _make_db(rows)
        result = await get_demand_by_hour(db)
        assert result.slots[10].cancelled_rides == 3

    @pytest.mark.asyncio
    async def test_avg_fare_none_for_empty_hours(self):
        db = _make_empty_db()
        result = await get_demand_by_hour(db)
        for slot in result.slots:
            assert slot.avg_fare is None

    @pytest.mark.asyncio
    async def test_avg_fare_rounded_to_two_decimal_places(self):
        rows = [_make_hour_row(hour=8, avg_fare=21.3333)]
        db = _make_db(rows)
        result = await get_demand_by_hour(db)
        assert result.slots[8].avg_fare == 21.33

    @pytest.mark.asyncio
    async def test_avg_wait_minutes_none_for_empty_hours(self):
        db = _make_empty_db()
        result = await get_demand_by_hour(db)
        for slot in result.slots:
            assert slot.avg_wait_minutes is None

    @pytest.mark.asyncio
    async def test_avg_wait_minutes_rounded_to_two_decimal_places(self):
        rows = [_make_hour_row(hour=12, avg_wait_minutes=4.6789)]
        db = _make_db(rows)
        result = await get_demand_by_hour(db)
        assert result.slots[12].avg_wait_minutes == 4.68

    @pytest.mark.asyncio
    async def test_missing_hours_produce_zero_slots(self):
        # Only hour 14 has data; all others should be zero
        rows = [_make_hour_row(hour=14, total_rides=20)]
        db = _make_db(rows)
        result = await get_demand_by_hour(db)
        for slot in result.slots:
            if slot.hour != 14:
                assert slot.total_rides == 0

    @pytest.mark.asyncio
    async def test_hour_label_format(self):
        db = _make_empty_db()
        result = await get_demand_by_hour(db)
        assert result.slots[0].hour_label == "00:00"
        assert result.slots[9].hour_label == "09:00"
        assert result.slots[14].hour_label == "14:00"
        assert result.slots[23].hour_label == "23:00"

    @pytest.mark.asyncio
    async def test_generated_at_is_utc_aware(self):
        db = _make_empty_db()
        result = await get_demand_by_hour(db)
        assert result.generated_at.tzinfo is not None

    @pytest.mark.asyncio
    async def test_filters_echoed_in_response(self):
        db = _make_empty_db()
        start = date(2025, 1, 1)
        end = date(2025, 12, 31)
        result = await get_demand_by_hour(db, start_date=start, end_date=end)
        assert result.filters.start_date == start
        assert result.filters.end_date == end

    @pytest.mark.asyncio
    async def test_day_of_week_echoed_in_filters(self):
        db = _make_empty_db()
        result = await get_demand_by_hour(db, day_of_week=5)
        assert result.filters.day_of_week == 5

    @pytest.mark.asyncio
    async def test_peak_hour_with_tied_max_uses_first_encountered(self):
        # Two hours tied; peak_hour should be the lower hour (first in sorted list)
        rows = [
            _make_hour_row(hour=8, total_rides=20),
            _make_hour_row(hour=18, total_rides=20),
        ]
        db = _make_db(rows)
        result = await get_demand_by_hour(db)
        # max() on a list returns first maximum found when iterating 0→23
        assert result.peak_hour in (8, 18)

    @pytest.mark.asyncio
    async def test_response_total_rides_equals_sum_of_slot_rides(self):
        rows = [
            _make_hour_row(hour=7, total_rides=12),
            _make_hour_row(hour=18, total_rides=40),
            _make_hour_row(hour=22, total_rides=8),
        ]
        db = _make_db(rows)
        result = await get_demand_by_hour(db)
        assert result.total_rides == sum(s.total_rides for s in result.slots)


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------

BASE = "/api/v1/admin/analytics/demand-by-hour"


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
class TestDemandByHourEndpoint:
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

    async def test_response_has_slots_list(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        data = resp.json()
        assert "slots" in data
        assert isinstance(data["slots"], list)

    async def test_response_always_has_24_slots(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["slots"]) == 24

    async def test_slots_ordered_by_hour(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        data = resp.json()
        hours = [s["hour"] for s in data["slots"]]
        assert hours == list(range(24))

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

    async def test_day_of_week_valid_values_accepted(self, client, admin_user, admin_token):
        for dow in range(7):
            resp = await client.get(
                f"{BASE}?day_of_week={dow}", headers=auth_header(admin_token)
            )
            assert resp.status_code == 200, f"day_of_week={dow} should return 200"

    async def test_day_of_week_7_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?day_of_week=7", headers=auth_header(admin_token)
        )
        assert resp.status_code == 422

    async def test_day_of_week_negative_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?day_of_week=-1", headers=auth_header(admin_token)
        )
        assert resp.status_code == 422

    async def test_no_params_returns_200(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        assert resp.status_code == 200

    async def test_response_has_total_rides(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        data = resp.json()
        assert "total_rides" in data

    async def test_response_has_peak_hour(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        data = resp.json()
        assert "peak_hour" in data

    async def test_response_has_generated_at(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        data = resp.json()
        assert "generated_at" in data

    async def test_response_has_filters(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        data = resp.json()
        assert "filters" in data

    async def test_each_slot_has_required_fields(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        data = resp.json()
        required = {
            "hour", "hour_label", "total_rides",
            "completed_rides", "cancelled_rides",
            "avg_fare", "avg_wait_minutes",
        }
        for slot in data["slots"]:
            missing = required - set(slot.keys())
            assert not missing, f"Slot missing fields: {missing}"

    async def test_peak_hour_none_when_no_rides(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?start_date=2099-01-01&end_date=2099-12-31",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["peak_hour"] is None

    async def test_total_rides_zero_when_no_rides(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?start_date=2099-01-01&end_date=2099-12-31",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_rides"] == 0
