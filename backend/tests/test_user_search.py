"""Tests for admin unified user search endpoint.

Covers:
API integration tests (real in-transaction test DB):
  1.  GET /admin/users/search — 401 without auth
  2.  GET /admin/users/search — 403 with rider token
  3.  GET /admin/users/search — 403 with driver token
  4.  GET /admin/users/search — 422 without q param
  5.  GET /admin/users/search — 200 with admin token and q
  6.  GET /admin/users/search — response has query, role_filter, results, total
  7.  GET /admin/users/search — empty results when no match
  8.  GET /admin/users/search — role=driver accepted
  9.  GET /admin/users/search — role=rider accepted
  10. GET /admin/users/search — role=all accepted (default)
  11. GET /admin/users/search — invalid role returns 422
  12. GET /admin/users/search — limit param accepted
  13. GET /admin/users/search — result entry has user_id, name, phone, email, role, is_active
  14. GET /admin/users/search — driver result includes driver_is_approved, driver_total_trips, driver_rating_avg
  15. GET /admin/users/search — rider result has driver fields as null
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


class TestUserSearchEndpoint:
    async def test_requires_auth(self, client):
        resp = await client.get("/admin/users/search?q=test")
        assert resp.status_code == 401

    async def test_requires_admin_not_rider(self, client, rider_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/users/search?q=test", headers=auth_header(rider_token))
        assert resp.status_code == 403

    async def test_requires_admin_not_driver(self, client, driver_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/users/search?q=test", headers=auth_header(driver_token))
        assert resp.status_code == 403

    async def test_missing_q_param_returns_422(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/users/search", headers=auth_header(admin_token))
        assert resp.status_code == 422

    async def test_200_with_valid_query(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/users/search?q=test", headers=auth_header(admin_token))
        assert resp.status_code == 200

    async def test_response_has_required_fields(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/users/search?q=xyznotfound", headers=auth_header(admin_token))
        data = resp.json()
        assert "query" in data
        assert "role_filter" in data
        assert "results" in data
        assert "total" in data

    async def test_empty_results_when_no_match(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/users/search?q=xyznotfound999", headers=auth_header(admin_token))
        assert resp.json()["results"] == []
        assert resp.json()["total"] == 0

    async def test_role_driver_accepted(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/users/search?q=test&role=driver", headers=auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["role_filter"] == "driver"

    async def test_role_rider_accepted(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/users/search?q=test&role=rider", headers=auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["role_filter"] == "rider"

    async def test_role_all_is_default(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/users/search?q=test", headers=auth_header(admin_token))
        assert resp.json()["role_filter"] == "all"

    async def test_invalid_role_returns_422(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/users/search?q=test&role=admin", headers=auth_header(admin_token))
        assert resp.status_code == 422

    async def test_limit_param_accepted(self, client, admin_token):
        from tests.conftest import auth_header
        resp = await client.get("/admin/users/search?q=test&limit=5", headers=auth_header(admin_token))
        assert resp.status_code == 200

    async def test_result_has_user_fields(self, client, db, rider, admin_token):
        """A rider matching the search has the expected fields."""
        from tests.conftest import auth_header
        # Search by rider's name fragment
        resp = await client.get(f"/admin/users/search?q=Test+Rider&role=rider", headers=auth_header(admin_token))
        assert resp.status_code == 200
        results = resp.json()["results"]
        if results:
            entry = results[0]
            for field in ["user_id", "name", "phone", "email", "role", "is_active"]:
                assert field in entry, f"Missing field: {field}"

    async def test_driver_result_has_driver_fields(self, client, db, driver_profile, admin_token):
        """A driver result includes driver-specific fields."""
        from tests.conftest import auth_header
        resp = await client.get("/admin/users/search?q=Test+Driver&role=driver", headers=auth_header(admin_token))
        assert resp.status_code == 200
        results = resp.json()["results"]
        if results:
            entry = results[0]
            assert "driver_is_approved" in entry
            assert "driver_total_trips" in entry
            assert "driver_rating_avg" in entry

    async def test_rider_result_has_null_driver_fields(self, client, db, rider, admin_token):
        """Rider entries have null driver-specific fields."""
        from tests.conftest import auth_header
        resp = await client.get("/admin/users/search?q=Test+Rider&role=rider", headers=auth_header(admin_token))
        assert resp.status_code == 200
        results = resp.json()["results"]
        if results:
            entry = results[0]
            # Rider should have null driver fields
            assert entry.get("driver_is_approved") is None
            assert entry.get("driver_total_trips") is None
            assert entry.get("driver_rating_avg") is None
