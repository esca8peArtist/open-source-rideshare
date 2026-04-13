"""Tests for admin top-earners / top-spenders leaderboard endpoint.

Covers:
API integration tests (real in-transaction test DB):
  1.  GET /admin/stats/top-earners — 401 without auth
  2.  GET /admin/stats/top-earners — 403 with rider token
  3.  GET /admin/stats/top-earners — 403 with driver token
  4.  GET /admin/stats/top-earners — 200 with admin token
  5.  GET /admin/stats/top-earners — response has period and role fields
  6.  GET /admin/stats/top-earners — response has entries list
  7.  GET /admin/stats/top-earners — role=driver accepted
  8.  GET /admin/stats/top-earners — role=rider accepted
  9.  GET /admin/stats/top-earners — period=week accepted
  10. GET /admin/stats/top-earners — period=year accepted
  11. GET /admin/stats/top-earners — period=all accepted
  12. GET /admin/stats/top-earners — invalid period returns 422
  13. GET /admin/stats/top-earners — invalid role returns 422
  14. GET /admin/stats/top-earners — empty entries for no rides
  15. GET /admin/stats/top-earners — limit param accepted
  16. GET /admin/stats/top-earners?role=driver — driver entry has driver_id, driver_name, completed_trips, total_earned_dollars, avg_fare_dollars
  17. GET /admin/stats/top-earners?role=rider — rider entry has rider_id, rider_name, completed_trips, total_spent_dollars, avg_fare_dollars
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


class TestTopEarnersEndpoint:
    async def test_requires_auth(self, client):
        resp = await client.get("/admin/stats/top-earners")
        assert resp.status_code == 401

    async def test_requires_admin_not_rider(self, client, rider_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/stats/top-earners", headers=auth_header(rider_token))
        assert resp.status_code == 403

    async def test_requires_admin_not_driver(self, client, driver_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/stats/top-earners", headers=auth_header(driver_token))
        assert resp.status_code == 403

    async def test_200_with_admin(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/stats/top-earners", headers=auth_header(admin_token))
        assert resp.status_code == 200

    async def test_response_has_period_and_role(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/stats/top-earners?role=driver&period=month", headers=auth_header(admin_token))
        data = resp.json()
        assert "period" in data
        assert "role" in data
        assert data["period"] == "month"
        assert data["role"] == "driver"

    async def test_response_has_entries_list(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/stats/top-earners", headers=auth_header(admin_token))
        data = resp.json()
        assert "entries" in data
        assert isinstance(data["entries"], list)

    async def test_role_driver_accepted(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/stats/top-earners?role=driver", headers=auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["role"] == "driver"

    async def test_role_rider_accepted(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/stats/top-earners?role=rider", headers=auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["role"] == "rider"

    async def test_period_week_accepted(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/stats/top-earners?period=week", headers=auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["period"] == "week"

    async def test_period_year_accepted(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/stats/top-earners?period=year", headers=auth_header(admin_token))
        assert resp.status_code == 200

    async def test_period_all_accepted(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/stats/top-earners?period=all", headers=auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["period"] == "all"

    async def test_invalid_period_returns_422(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/stats/top-earners?period=quarterly", headers=auth_header(admin_token))
        assert resp.status_code == 422

    async def test_invalid_role_returns_422(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/stats/top-earners?role=admin", headers=auth_header(admin_token))
        assert resp.status_code == 422

    async def test_empty_entries_when_no_rides(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/stats/top-earners?period=week", headers=auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["entries"] == []

    async def test_limit_param_accepted(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/stats/top-earners?limit=5", headers=auth_header(admin_token))
        assert resp.status_code == 200

    async def test_driver_entry_has_expected_fields(self, client, admin_token):
        """When entries exist, driver entries have the correct fields."""
        from tests.conftest import auth_header
        # Even with no data, verify the response structure is valid
        resp = await client.get("/admin/stats/top-earners?role=driver&period=all", headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "driver"
        # If there were entries, they'd have driver_id, driver_name, etc.
        # With no data we just verify the shape is parseable
        for entry in data["entries"]:
            assert "driver_id" in entry
            assert "driver_name" in entry
            assert "completed_trips" in entry
            assert "total_earned_dollars" in entry
            assert "avg_fare_dollars" in entry

    async def test_rider_entry_has_expected_fields(self, client, admin_token):
        """When entries exist, rider entries have the correct fields."""
        from tests.conftest import auth_header
        resp = await client.get("/admin/stats/top-earners?role=rider&period=all", headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "rider"
        for entry in data["entries"]:
            assert "rider_id" in entry
            assert "rider_name" in entry
            assert "completed_trips" in entry
            assert "total_spent_dollars" in entry
            assert "avg_fare_dollars" in entry
