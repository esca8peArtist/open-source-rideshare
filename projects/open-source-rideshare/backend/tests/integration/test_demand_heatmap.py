"""Integration tests for the demand-by-hour analytics endpoint.

These tests require a live PostgreSQL test database. They are automatically
skipped when the database is not reachable (the shared ``setup_database``
fixture in conftest.py calls ``pytest.skip`` on connection failure).

Tests:
  1.  GET /api/v1/admin/analytics/demand-by-hour — 401 without auth
  2.  GET /api/v1/admin/analytics/demand-by-hour — 403 with rider token
  3.  GET /api/v1/admin/analytics/demand-by-hour — 403 with driver token
  4.  GET /api/v1/admin/analytics/demand-by-hour — 200 with admin token
  5.  GET /api/v1/admin/analytics/demand-by-hour — response has slots list
  6.  GET /api/v1/admin/analytics/demand-by-hour — always returns 24 slots
  7.  GET /api/v1/admin/analytics/demand-by-hour — slots ordered by hour 0–23
  8.  GET /api/v1/admin/analytics/demand-by-hour — response has total_rides
  9.  GET /api/v1/admin/analytics/demand-by-hour — response has peak_hour
  10. GET /api/v1/admin/analytics/demand-by-hour — response has generated_at
  11. GET /api/v1/admin/analytics/demand-by-hour — response has filters
  12. GET /api/v1/admin/analytics/demand-by-hour — start_date filter accepted
  13. GET /api/v1/admin/analytics/demand-by-hour — end_date filter accepted
  14. GET /api/v1/admin/analytics/demand-by-hour — end_date before start_date → 422
  15. GET /api/v1/admin/analytics/demand-by-hour — day_of_week 0–6 accepted
  16. GET /api/v1/admin/analytics/demand-by-hour — day_of_week=7 returns 422
  17. GET /api/v1/admin/analytics/demand-by-hour — no params returns 200
  18. GET /api/v1/admin/analytics/demand-by-hour — peak_hour is None for empty result
  19. GET /api/v1/admin/analytics/demand-by-hour — total_rides=0 for empty result
  20. GET /api/v1/admin/analytics/demand-by-hour — slot has all required fields
  21. GET /api/v1/admin/analytics/demand-by-hour — ride at hour 14 reflected in slot 14
  22. GET /api/v1/admin/analytics/demand-by-hour — rides outside date range excluded
  23. GET /api/v1/admin/analytics/demand-by-hour — completed ride counted in completed_rides
  24. GET /api/v1/admin/analytics/demand-by-hour — cancelled ride counted in cancelled_rides
  25. GET /api/v1/admin/analytics/demand-by-hour — peak_hour matches highest-demand slot
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import auth_header

pytestmark = pytest.mark.integration

BASE = "/api/v1/admin/analytics/demand-by-hour"


@pytest.mark.anyio
class TestDemandByHourIntegration:
    async def test_no_auth_returns_401(self, client: AsyncClient):
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

    async def test_always_returns_24_slots(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        data = resp.json()
        assert len(data["slots"]) == 24

    async def test_slots_ordered_by_hour(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        data = resp.json()
        hours = [s["hour"] for s in data["slots"]]
        assert hours == list(range(24))

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

    async def test_end_before_start_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?start_date=2025-12-01&end_date=2025-01-01",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_day_of_week_valid_values_accepted(self, client, admin_user, admin_token):
        for dow in range(7):
            resp = await client.get(
                f"{BASE}?day_of_week={dow}", headers=auth_header(admin_token)
            )
            assert resp.status_code == 200

    async def test_day_of_week_7_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?day_of_week=7", headers=auth_header(admin_token)
        )
        assert resp.status_code == 422

    async def test_no_params_returns_200(self, client, admin_user, admin_token):
        resp = await client.get(BASE, headers=auth_header(admin_token))
        assert resp.status_code == 200

    async def test_peak_hour_none_for_empty_date_range(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?start_date=2099-01-01&end_date=2099-12-31",
            headers=auth_header(admin_token),
        )
        data = resp.json()
        assert data["peak_hour"] is None

    async def test_total_rides_zero_for_empty_date_range(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}?start_date=2099-01-01&end_date=2099-12-31",
            headers=auth_header(admin_token),
        )
        data = resp.json()
        assert data["total_rides"] == 0

    async def test_slot_has_all_required_fields(self, client, admin_user, admin_token):
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

    async def test_ride_at_hour_reflected_in_slot(
        self, client, db: AsyncSession, admin_user, admin_token, rider
    ):
        from app.models.ride import Ride, RideStatus
        from geoalchemy2.functions import ST_MakePoint

        ride = Ride(
            rider_id=rider.id,
            status=RideStatus.COMPLETED,
            pickup_location=ST_MakePoint(-122.4194, 37.7749),
            dropoff_location=ST_MakePoint(-122.4094, 37.7849),
            pickup_address="Demand Test Pickup",
            dropoff_address="Demand Test Dropoff",
            estimated_fare=22.0,
            actual_fare=22.0,
            requested_at=datetime(2025, 7, 15, 14, 30, 0, tzinfo=timezone.utc),
        )
        db.add(ride)
        await db.flush()

        resp = await client.get(
            f"{BASE}?start_date=2025-07-15&end_date=2025-07-15",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        slot_14 = data["slots"][14]
        assert slot_14["hour"] == 14
        assert slot_14["total_rides"] >= 1

    async def test_rides_outside_date_range_excluded(
        self, client, db: AsyncSession, admin_user, admin_token, rider
    ):
        from app.models.ride import Ride, RideStatus
        from geoalchemy2.functions import ST_MakePoint

        ride = Ride(
            rider_id=rider.id,
            status=RideStatus.COMPLETED,
            pickup_location=ST_MakePoint(-122.41, 37.77),
            dropoff_location=ST_MakePoint(-122.42, 37.78),
            pickup_address="Old Ride Pickup",
            dropoff_address="Old Ride Dropoff",
            estimated_fare=15.0,
            requested_at=datetime(2020, 3, 1, 10, 0, 0, tzinfo=timezone.utc),
        )
        db.add(ride)
        await db.flush()

        resp = await client.get(
            f"{BASE}?start_date=2099-01-01&end_date=2099-12-31",
            headers=auth_header(admin_token),
        )
        data = resp.json()
        assert data["total_rides"] == 0

    async def test_completed_ride_counted_in_completed_rides(
        self, client, db: AsyncSession, admin_user, admin_token, rider
    ):
        from app.models.ride import Ride, RideStatus
        from geoalchemy2.functions import ST_MakePoint

        ride = Ride(
            rider_id=rider.id,
            status=RideStatus.COMPLETED,
            pickup_location=ST_MakePoint(-122.41, 37.77),
            dropoff_location=ST_MakePoint(-122.42, 37.78),
            pickup_address="Completed Pickup",
            dropoff_address="Completed Dropoff",
            estimated_fare=18.0,
            actual_fare=18.0,
            requested_at=datetime(2025, 8, 1, 9, 0, 0, tzinfo=timezone.utc),
        )
        db.add(ride)
        await db.flush()

        resp = await client.get(
            f"{BASE}?start_date=2025-08-01&end_date=2025-08-01",
            headers=auth_header(admin_token),
        )
        data = resp.json()
        slot_9 = data["slots"][9]
        assert slot_9["completed_rides"] >= 1

    async def test_cancelled_ride_counted_in_cancelled_rides(
        self, client, db: AsyncSession, admin_user, admin_token, rider
    ):
        from app.models.ride import Ride, RideStatus
        from geoalchemy2.functions import ST_MakePoint

        ride = Ride(
            rider_id=rider.id,
            status=RideStatus.CANCELLED,
            pickup_location=ST_MakePoint(-122.43, 37.79),
            dropoff_location=ST_MakePoint(-122.44, 37.80),
            pickup_address="Cancelled Pickup",
            dropoff_address="Cancelled Dropoff",
            estimated_fare=12.0,
            requested_at=datetime(2025, 9, 5, 20, 0, 0, tzinfo=timezone.utc),
        )
        db.add(ride)
        await db.flush()

        resp = await client.get(
            f"{BASE}?start_date=2025-09-05&end_date=2025-09-05",
            headers=auth_header(admin_token),
        )
        data = resp.json()
        slot_20 = data["slots"][20]
        assert slot_20["cancelled_rides"] >= 1

    async def test_peak_hour_matches_highest_demand_slot(
        self, client, db: AsyncSession, admin_user, admin_token, rider
    ):
        from app.models.ride import Ride, RideStatus
        from geoalchemy2.functions import ST_MakePoint

        # Add 3 rides at hour 17 and 1 ride at hour 9
        for i in range(3):
            ride = Ride(
                rider_id=rider.id,
                status=RideStatus.COMPLETED,
                pickup_location=ST_MakePoint(-122.41 - i * 0.01, 37.77),
                dropoff_location=ST_MakePoint(-122.42, 37.78),
                pickup_address=f"Peak Test Pickup {i}",
                dropoff_address="Peak Test Dropoff",
                estimated_fare=20.0,
                actual_fare=20.0,
                requested_at=datetime(2025, 10, 3, 17, i * 10, 0, tzinfo=timezone.utc),
            )
            db.add(ride)

        off_peak = Ride(
            rider_id=rider.id,
            status=RideStatus.COMPLETED,
            pickup_location=ST_MakePoint(-122.45, 37.75),
            dropoff_location=ST_MakePoint(-122.46, 37.76),
            pickup_address="Off Peak Pickup",
            dropoff_address="Off Peak Dropoff",
            estimated_fare=15.0,
            actual_fare=15.0,
            requested_at=datetime(2025, 10, 3, 9, 0, 0, tzinfo=timezone.utc),
        )
        db.add(off_peak)
        await db.flush()

        resp = await client.get(
            f"{BASE}?start_date=2025-10-03&end_date=2025-10-03",
            headers=auth_header(admin_token),
        )
        data = resp.json()
        assert data["peak_hour"] == 17
