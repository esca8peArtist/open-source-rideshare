"""Tests for the rider-facing busy hours indicator.

Service unit tests (using AsyncMock for get_demand_by_hour):
  1.  get_busy_hours — always returns exactly 24 slots
  2.  get_busy_hours — slots ordered by hour ascending (0–23)
  3.  get_busy_hours — empty demand data → all slots DemandLevel.low
  4.  get_busy_hours — peak hour (100% of max) gets DemandLevel.peak
  5.  get_busy_hours — hour at exactly 75% of max gets DemandLevel.peak
  6.  get_busy_hours — hour at 74% of max gets DemandLevel.high
  7.  get_busy_hours — hour at exactly 40% of max gets DemandLevel.high
  8.  get_busy_hours — hour at 39% of max gets DemandLevel.medium
  9.  get_busy_hours — hour at exactly 15% of max gets DemandLevel.medium
  10. get_busy_hours — hour at 14% of max gets DemandLevel.low
  11. get_busy_hours — typical_wait_minutes mirrors avg_wait_minutes from demand
  12. get_busy_hours — typical_wait_minutes is None for zero-count hours
  13. get_busy_hours — is_current_hour True only for current UTC hour
  14. get_busy_hours — current_hour in response matches current UTC hour
  15. get_busy_hours — current_demand_level matches slot for current hour
  16. get_busy_hours — peak_hour propagated from demand response
  17. get_busy_hours — day_of_week echoed in response
  18. get_busy_hours — generated_at is UTC-aware datetime

API integration tests:
  19. GET /rides/busy-hours — 401 with no auth
  20. GET /rides/busy-hours — 200 with rider token
  21. GET /rides/busy-hours — 200 with driver token
  22. GET /rides/busy-hours — 200 with admin token
  23. GET /rides/busy-hours — response has slots list with 24 entries
  24. GET /rides/busy-hours — slots ordered by hour 0–23
  25. GET /rides/busy-hours — day_of_week 0–6 accepted
  26. GET /rides/busy-hours — day_of_week=7 returns 422
  27. GET /rides/busy-hours — day_of_week=-1 returns 422
  28. GET /rides/busy-hours — no params returns 200
  29. GET /rides/busy-hours — response has required top-level fields
  30. GET /rides/busy-hours — each slot has required fields
  31. GET /rides/busy-hours — each slot demand_level is a valid enum value
  32. GET /rides/busy-hours — current_hour is an integer 0–23
  33. GET /rides/busy-hours — exactly one slot has is_current_hour=true
  34. GET /rides/busy-hours — all-zero data returns all slots as "low"
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.busy_hours import BusyHoursResponse, DemandLevel
from app.schemas.demand_heatmap import DemandByHourFilters, DemandByHourResponse, DemandHourSlot
from app.services.busy_hours import _classify_demand, get_busy_hours


# ---------------------------------------------------------------------------
# Helpers — build fake DemandByHourResponse
# ---------------------------------------------------------------------------


def _make_slot(
    hour: int,
    total_rides: int = 0,
    avg_wait_minutes: float | None = None,
) -> DemandHourSlot:
    return DemandHourSlot(
        hour=hour,
        hour_label=f"{hour:02d}:00",
        total_rides=total_rides,
        completed_rides=0,
        cancelled_rides=0,
        avg_fare=None,
        avg_wait_minutes=avg_wait_minutes,
    )


def _make_demand_response(
    ride_counts: dict[int, int] | None = None,
    wait_by_hour: dict[int, float | None] | None = None,
    peak_hour: int | None = None,
    day_of_week: int | None = None,
) -> DemandByHourResponse:
    """Build a full 24-slot DemandByHourResponse with optional overrides."""
    counts = ride_counts or {}
    waits = wait_by_hour or {}
    slots = [
        _make_slot(h, total_rides=counts.get(h, 0), avg_wait_minutes=waits.get(h))
        for h in range(24)
    ]
    total = sum(s.total_rides for s in slots)
    if peak_hour is None and total > 0:
        peak_hour = max(slots, key=lambda s: s.total_rides).hour
    return DemandByHourResponse(
        slots=slots,
        total_rides=total,
        peak_hour=peak_hour,
        generated_at=datetime.now(timezone.utc),
        filters=DemandByHourFilters(day_of_week=day_of_week),
    )


def _mock_db() -> AsyncMock:
    """Return a minimal DB mock; get_busy_hours delegates to get_demand_by_hour."""
    db = AsyncMock()
    result = MagicMock()
    result.fetchall = MagicMock(return_value=[])
    db.execute = AsyncMock(return_value=result)
    return db


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


class TestClassifyDemand:
    def test_zero_max_returns_low(self):
        assert _classify_demand(0, 0) == DemandLevel.low

    def test_100_percent_of_max_returns_peak(self):
        assert _classify_demand(100, 100) == DemandLevel.peak

    def test_75_percent_returns_peak(self):
        assert _classify_demand(75, 100) == DemandLevel.peak

    def test_74_percent_returns_high(self):
        assert _classify_demand(74, 100) == DemandLevel.high

    def test_40_percent_returns_high(self):
        assert _classify_demand(40, 100) == DemandLevel.high

    def test_39_percent_returns_medium(self):
        assert _classify_demand(39, 100) == DemandLevel.medium

    def test_15_percent_returns_medium(self):
        assert _classify_demand(15, 100) == DemandLevel.medium

    def test_14_percent_returns_low(self):
        assert _classify_demand(14, 100) == DemandLevel.low

    def test_zero_rides_any_max_returns_low(self):
        assert _classify_demand(0, 50) == DemandLevel.low


class TestGetBusyHours:
    @pytest.mark.asyncio
    async def test_always_returns_24_slots(self):
        demand = _make_demand_response()
        with patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            result = await get_busy_hours(_mock_db())
        assert len(result.slots) == 24

    @pytest.mark.asyncio
    async def test_slots_ordered_by_hour_ascending(self):
        demand = _make_demand_response()
        with patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            result = await get_busy_hours(_mock_db())
        assert [s.hour for s in result.slots] == list(range(24))

    @pytest.mark.asyncio
    async def test_empty_demand_all_slots_low(self):
        demand = _make_demand_response()
        with patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            result = await get_busy_hours(_mock_db())
        for slot in result.slots:
            assert slot.demand_level == DemandLevel.low

    @pytest.mark.asyncio
    async def test_peak_hour_slot_gets_peak_level(self):
        demand = _make_demand_response(ride_counts={9: 100, 17: 50, 22: 10})
        with patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            result = await get_busy_hours(_mock_db())
        assert result.slots[9].demand_level == DemandLevel.peak

    @pytest.mark.asyncio
    async def test_75_percent_of_max_gets_peak(self):
        demand = _make_demand_response(ride_counts={9: 100, 17: 75})
        with patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            result = await get_busy_hours(_mock_db())
        assert result.slots[17].demand_level == DemandLevel.peak

    @pytest.mark.asyncio
    async def test_74_percent_of_max_gets_high(self):
        demand = _make_demand_response(ride_counts={9: 100, 17: 74})
        with patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            result = await get_busy_hours(_mock_db())
        assert result.slots[17].demand_level == DemandLevel.high

    @pytest.mark.asyncio
    async def test_40_percent_of_max_gets_high(self):
        demand = _make_demand_response(ride_counts={9: 100, 17: 40})
        with patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            result = await get_busy_hours(_mock_db())
        assert result.slots[17].demand_level == DemandLevel.high

    @pytest.mark.asyncio
    async def test_39_percent_of_max_gets_medium(self):
        demand = _make_demand_response(ride_counts={9: 100, 17: 39})
        with patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            result = await get_busy_hours(_mock_db())
        assert result.slots[17].demand_level == DemandLevel.medium

    @pytest.mark.asyncio
    async def test_15_percent_of_max_gets_medium(self):
        demand = _make_demand_response(ride_counts={9: 100, 17: 15})
        with patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            result = await get_busy_hours(_mock_db())
        assert result.slots[17].demand_level == DemandLevel.medium

    @pytest.mark.asyncio
    async def test_14_percent_of_max_gets_low(self):
        demand = _make_demand_response(ride_counts={9: 100, 17: 14})
        with patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            result = await get_busy_hours(_mock_db())
        assert result.slots[17].demand_level == DemandLevel.low

    @pytest.mark.asyncio
    async def test_typical_wait_mirrors_avg_wait(self):
        demand = _make_demand_response(
            ride_counts={9: 10}, wait_by_hour={9: 3.5}
        )
        with patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            result = await get_busy_hours(_mock_db())
        assert result.slots[9].typical_wait_minutes == 3.5

    @pytest.mark.asyncio
    async def test_typical_wait_none_for_empty_hours(self):
        demand = _make_demand_response()
        with patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            result = await get_busy_hours(_mock_db())
        for slot in result.slots:
            assert slot.typical_wait_minutes is None

    @pytest.mark.asyncio
    async def test_is_current_hour_only_for_current_hour(self):
        demand = _make_demand_response()
        fixed_now = datetime(2026, 4, 14, 14, 30, 0, tzinfo=timezone.utc)
        with patch("app.services.busy_hours.datetime") as mock_dt, patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            mock_dt.now.return_value = fixed_now
            result = await get_busy_hours(_mock_db())
        current = [s for s in result.slots if s.is_current_hour]
        assert len(current) == 1
        assert current[0].hour == 14

    @pytest.mark.asyncio
    async def test_current_hour_in_response_matches_utc(self):
        demand = _make_demand_response()
        fixed_now = datetime(2026, 4, 14, 8, 0, 0, tzinfo=timezone.utc)
        with patch("app.services.busy_hours.datetime") as mock_dt, patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            mock_dt.now.return_value = fixed_now
            result = await get_busy_hours(_mock_db())
        assert result.current_hour == 8

    @pytest.mark.asyncio
    async def test_current_demand_level_matches_current_slot(self):
        # Hour 9 is busiest; set current time to 9
        demand = _make_demand_response(ride_counts={9: 100, 17: 20})
        fixed_now = datetime(2026, 4, 14, 9, 0, 0, tzinfo=timezone.utc)
        with patch("app.services.busy_hours.datetime") as mock_dt, patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            mock_dt.now.return_value = fixed_now
            result = await get_busy_hours(_mock_db())
        assert result.current_demand_level == DemandLevel.peak

    @pytest.mark.asyncio
    async def test_peak_hour_propagated_from_demand(self):
        demand = _make_demand_response(ride_counts={17: 100, 9: 20})
        with patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            result = await get_busy_hours(_mock_db())
        assert result.peak_hour == 17

    @pytest.mark.asyncio
    async def test_day_of_week_echoed_in_response(self):
        demand = _make_demand_response(day_of_week=5)
        with patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            result = await get_busy_hours(_mock_db(), day_of_week=5)
        assert result.day_of_week == 5

    @pytest.mark.asyncio
    async def test_generated_at_is_utc_aware(self):
        demand = _make_demand_response()
        with patch(
            "app.services.busy_hours.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            result = await get_busy_hours(_mock_db())
        assert result.generated_at.tzinfo is not None


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------


BASE = "/api/v1/rides/busy-hours"


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


VALID_DEMAND_LEVELS = {"low", "medium", "high", "peak"}


@pytest.mark.anyio
class TestBusyHoursEndpoint:
    async def test_no_auth_returns_401(self, client):
        resp = await client.get(BASE)
        assert resp.status_code == 401

    async def test_rider_token_returns_200(self, client, rider, rider_token):
        resp = await client.get(BASE, headers=auth_header(rider_token))
        assert resp.status_code == 200

    async def test_driver_token_returns_200(self, client, driver_user, driver_token):
        resp = await client.get(BASE, headers=auth_header(driver_token))
        assert resp.status_code == 200

    async def test_admin_token_returns_200(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        assert resp.status_code == 200

    async def test_response_has_24_slots(self, client, rider, rider_token):
        resp = await client.get(BASE, headers=auth_header(rider_token))
        data = resp.json()
        assert "slots" in data
        assert len(data["slots"]) == 24

    async def test_slots_ordered_by_hour(self, client, rider, rider_token):
        resp = await client.get(BASE, headers=auth_header(rider_token))
        data = resp.json()
        hours = [s["hour"] for s in data["slots"]]
        assert hours == list(range(24))

    async def test_day_of_week_valid_values_accepted(self, client, rider, rider_token):
        for dow in range(7):
            resp = await client.get(
                f"{BASE}?day_of_week={dow}", headers=auth_header(rider_token)
            )
            assert resp.status_code == 200, f"day_of_week={dow} should return 200"

    async def test_day_of_week_7_returns_422(self, client, rider, rider_token):
        resp = await client.get(
            f"{BASE}?day_of_week=7", headers=auth_header(rider_token)
        )
        assert resp.status_code == 422

    async def test_day_of_week_negative_returns_422(self, client, rider, rider_token):
        resp = await client.get(
            f"{BASE}?day_of_week=-1", headers=auth_header(rider_token)
        )
        assert resp.status_code == 422

    async def test_no_params_returns_200(self, client, rider, rider_token):
        resp = await client.get(BASE, headers=auth_header(rider_token))
        assert resp.status_code == 200

    async def test_response_has_required_top_level_fields(self, client, rider, rider_token):
        resp = await client.get(BASE, headers=auth_header(rider_token))
        data = resp.json()
        required = {"slots", "peak_hour", "current_hour", "current_demand_level", "generated_at"}
        missing = required - set(data.keys())
        assert not missing, f"Response missing top-level fields: {missing}"

    async def test_each_slot_has_required_fields(self, client, rider, rider_token):
        resp = await client.get(BASE, headers=auth_header(rider_token))
        data = resp.json()
        required = {"hour", "hour_label", "demand_level", "typical_wait_minutes", "is_current_hour"}
        for slot in data["slots"]:
            missing = required - set(slot.keys())
            assert not missing, f"Slot missing fields: {missing}"

    async def test_each_slot_demand_level_is_valid(self, client, rider, rider_token):
        resp = await client.get(BASE, headers=auth_header(rider_token))
        data = resp.json()
        for slot in data["slots"]:
            assert slot["demand_level"] in VALID_DEMAND_LEVELS, (
                f"Invalid demand_level: {slot['demand_level']}"
            )

    async def test_current_hour_is_integer_0_to_23(self, client, rider, rider_token):
        resp = await client.get(BASE, headers=auth_header(rider_token))
        data = resp.json()
        assert isinstance(data["current_hour"], int)
        assert 0 <= data["current_hour"] <= 23

    async def test_exactly_one_slot_is_current_hour(self, client, rider, rider_token):
        resp = await client.get(BASE, headers=auth_header(rider_token))
        data = resp.json()
        current = [s for s in data["slots"] if s["is_current_hour"]]
        assert len(current) == 1

    async def test_all_zero_data_returns_all_low(self, client, rider, rider_token):
        resp = await client.get(
            f"{BASE}?day_of_week=0", headers=auth_header(rider_token)
        )
        data = resp.json()
        # With no rides in the test DB, all hours should be "low"
        for slot in data["slots"]:
            assert slot["demand_level"] == "low"
