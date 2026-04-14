"""Integration tests for the platform admin config API.

These tests require a live PostgreSQL test database.  They are automatically
skipped when the database is not reachable (the shared ``setup_database``
fixture in conftest.py calls ``pytest.skip`` on connection failure).

Tests:
  1.  GET /api/v1/admin/config — 401 without auth
  2.  GET /api/v1/admin/config — 403 with rider token
  3.  GET /api/v1/admin/config — 403 with driver token
  4.  GET /api/v1/admin/config — 200 with admin token
  5.  GET /api/v1/admin/config — response has entries and total fields
  6.  GET /api/v1/admin/config — total matches len(entries)
  7.  GET /api/v1/admin/config — category filter returns only matching entries
  8.  GET /api/v1/admin/config — invalid category returns 422
  9.  GET /api/v1/admin/config/{key} — 401 without auth
  10. GET /api/v1/admin/config/{key} — 403 with rider token
  11. GET /api/v1/admin/config/{key} — 404 for unknown key
  12. GET /api/v1/admin/config/{key} — 200 for known seeded key
  13. GET /api/v1/admin/config/{key} — response includes typed_value field
  14. GET /api/v1/admin/config/{key} — typed_value is correct type for float entry
  15. PUT /api/v1/admin/config/{key} — 401 without auth
  16. PUT /api/v1/admin/config/{key} — 403 with rider token
  17. PUT /api/v1/admin/config/{key} — 404 for unknown key
  18. PUT /api/v1/admin/config/{key} — 200 updates float value
  19. PUT /api/v1/admin/config/{key} — updated value reflected in response
  20. PUT /api/v1/admin/config/{key} — 422 for non-numeric value on float key
  21. PUT /api/v1/admin/config/{key} — 422 for empty value string
  22. PUT /api/v1/admin/config/{key} — description updated when provided
  23. POST /api/v1/admin/config/bulk — 401 without auth
  24. POST /api/v1/admin/config/bulk — 403 with rider token
  25. POST /api/v1/admin/config/bulk — 200 with valid updates list
  26. POST /api/v1/admin/config/bulk — 422 for empty updates list
  27. POST /api/v1/admin/config/bulk — updated_count correct for all-success batch
  28. POST /api/v1/admin/config/bulk — failed_count correct for unknown keys
  29. POST /api/v1/admin/config/bulk — results list has one entry per update
  30. POST /api/v1/admin/config/bulk — mixed success/failure reported correctly
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_config import ConfigCategory, ConfigValueType, PlatformConfig
from tests.conftest import auth_header

pytestmark = pytest.mark.integration


async def _seed_entry(
    db: AsyncSession,
    key: str = "test_base_fare",
    category: ConfigCategory = ConfigCategory.PRICING,
    value_type: ConfigValueType = ConfigValueType.FLOAT,
    value: str = "2.50",
    label: str = "Test Base Fare",
) -> PlatformConfig:
    entry = PlatformConfig(
        key=key,
        category=category,
        value_type=value_type,
        value=value,
        label=label,
    )
    db.add(entry)
    await db.flush()
    return entry


# ---------------------------------------------------------------------------
# GET /api/v1/admin/config
# ---------------------------------------------------------------------------


async def test_list_config_no_auth(client: AsyncClient):
    resp = await client.get("/api/v1/admin/config")
    assert resp.status_code in (401, 403)


async def test_list_config_rider_forbidden(client: AsyncClient, rider_token: str):
    resp = await client.get(
        "/api/v1/admin/config",
        headers=auth_header(rider_token),
    )
    assert resp.status_code == 403


async def test_list_config_driver_forbidden(client: AsyncClient, driver_token: str):
    resp = await client.get(
        "/api/v1/admin/config",
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 403


async def test_list_config_admin_ok(
    client: AsyncClient, admin_token: str, db: AsyncSession
):
    await _seed_entry(db, key="test_list_ok")
    resp = await client.get(
        "/api/v1/admin/config",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200


async def test_list_config_response_shape(
    client: AsyncClient, admin_token: str, db: AsyncSession
):
    await _seed_entry(db, key="test_shape_a")
    resp = await client.get(
        "/api/v1/admin/config",
        headers=auth_header(admin_token),
    )
    data = resp.json()
    assert "entries" in data
    assert "total" in data


async def test_list_config_total_matches_entries(
    client: AsyncClient, admin_token: str, db: AsyncSession
):
    await _seed_entry(db, key="test_total_x")
    resp = await client.get(
        "/api/v1/admin/config",
        headers=auth_header(admin_token),
    )
    data = resp.json()
    assert data["total"] == len(data["entries"])


async def test_list_config_category_filter(
    client: AsyncClient, admin_token: str, db: AsyncSession
):
    await _seed_entry(db, key="test_filter_pricing", category=ConfigCategory.PRICING)
    await _seed_entry(db, key="test_filter_safety", category=ConfigCategory.SAFETY)
    resp = await client.get(
        "/api/v1/admin/config",
        params={"category": "pricing"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    for entry in data["entries"]:
        assert entry["category"] == "pricing"


async def test_list_config_invalid_category_422(client: AsyncClient, admin_token: str):
    resp = await client.get(
        "/api/v1/admin/config",
        params={"category": "invalid_cat"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/admin/config/{key}
# ---------------------------------------------------------------------------


async def test_get_config_no_auth(client: AsyncClient):
    resp = await client.get("/api/v1/admin/config/base_fare")
    assert resp.status_code in (401, 403)


async def test_get_config_rider_forbidden(client: AsyncClient, rider_token: str):
    resp = await client.get(
        "/api/v1/admin/config/base_fare",
        headers=auth_header(rider_token),
    )
    assert resp.status_code == 403


async def test_get_config_unknown_key_404(client: AsyncClient, admin_token: str):
    resp = await client.get(
        "/api/v1/admin/config/completely_unknown_key_xyz",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 404


async def test_get_config_known_key_200(
    client: AsyncClient, admin_token: str, db: AsyncSession
):
    await _seed_entry(db, key="test_get_known")
    resp = await client.get(
        "/api/v1/admin/config/test_get_known",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200


async def test_get_config_includes_typed_value(
    client: AsyncClient, admin_token: str, db: AsyncSession
):
    await _seed_entry(db, key="test_typed")
    resp = await client.get(
        "/api/v1/admin/config/test_typed",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "typed_value" in data


async def test_get_config_typed_value_is_float_for_float_entry(
    client: AsyncClient, admin_token: str, db: AsyncSession
):
    await _seed_entry(
        db,
        key="test_typed_float",
        value_type=ConfigValueType.FLOAT,
        value="3.75",
    )
    resp = await client.get(
        "/api/v1/admin/config/test_typed_float",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["typed_value"], float)
    assert abs(data["typed_value"] - 3.75) < 0.001


# ---------------------------------------------------------------------------
# PUT /api/v1/admin/config/{key}
# ---------------------------------------------------------------------------


async def test_put_config_no_auth(client: AsyncClient):
    resp = await client.put(
        "/api/v1/admin/config/base_fare",
        json={"value": "3.0"},
    )
    assert resp.status_code in (401, 403)


async def test_put_config_rider_forbidden(client: AsyncClient, rider_token: str):
    resp = await client.put(
        "/api/v1/admin/config/base_fare",
        json={"value": "3.0"},
        headers=auth_header(rider_token),
    )
    assert resp.status_code == 403


async def test_put_config_unknown_key_404(client: AsyncClient, admin_token: str):
    resp = await client.put(
        "/api/v1/admin/config/completely_unknown_xyz",
        json={"value": "1.0"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 404


async def test_put_config_updates_float_value(
    client: AsyncClient, admin_token: str, db: AsyncSession
):
    await _seed_entry(
        db,
        key="test_put_float",
        value_type=ConfigValueType.FLOAT,
        value="2.5",
    )
    resp = await client.put(
        "/api/v1/admin/config/test_put_float",
        json={"value": "5.0"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200


async def test_put_config_updated_value_in_response(
    client: AsyncClient, admin_token: str, db: AsyncSession
):
    await _seed_entry(
        db,
        key="test_put_reflect",
        value_type=ConfigValueType.FLOAT,
        value="2.5",
    )
    resp = await client.put(
        "/api/v1/admin/config/test_put_reflect",
        json={"value": "9.99"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["value"] == "9.99"


async def test_put_config_invalid_type_422(
    client: AsyncClient, admin_token: str, db: AsyncSession
):
    await _seed_entry(
        db,
        key="test_put_invalid",
        value_type=ConfigValueType.FLOAT,
        value="2.5",
    )
    resp = await client.put(
        "/api/v1/admin/config/test_put_invalid",
        json={"value": "not_a_number"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 422


async def test_put_config_empty_value_422(
    client: AsyncClient, admin_token: str, db: AsyncSession
):
    await _seed_entry(db, key="test_put_empty", value="2.5")
    resp = await client.put(
        "/api/v1/admin/config/test_put_empty",
        json={"value": "   "},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 422


async def test_put_config_updates_description(
    client: AsyncClient, admin_token: str, db: AsyncSession
):
    await _seed_entry(db, key="test_put_desc", value="2.5")
    resp = await client.put(
        "/api/v1/admin/config/test_put_desc",
        json={"value": "2.5", "description": "updated description"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["description"] == "updated description"


# ---------------------------------------------------------------------------
# POST /api/v1/admin/config/bulk
# ---------------------------------------------------------------------------


async def test_bulk_update_no_auth(client: AsyncClient):
    resp = await client.post(
        "/api/v1/admin/config/bulk",
        json={"updates": [{"key": "base_fare", "value": "3.0"}]},
    )
    assert resp.status_code in (401, 403)


async def test_bulk_update_rider_forbidden(client: AsyncClient, rider_token: str):
    resp = await client.post(
        "/api/v1/admin/config/bulk",
        json={"updates": [{"key": "base_fare", "value": "3.0"}]},
        headers=auth_header(rider_token),
    )
    assert resp.status_code == 403


async def test_bulk_update_valid_200(
    client: AsyncClient, admin_token: str, db: AsyncSession
):
    await _seed_entry(db, key="test_bulk_a", value="1.0")
    resp = await client.post(
        "/api/v1/admin/config/bulk",
        json={"updates": [{"key": "test_bulk_a", "value": "2.0"}]},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200


async def test_bulk_update_empty_list_422(client: AsyncClient, admin_token: str):
    resp = await client.post(
        "/api/v1/admin/config/bulk",
        json={"updates": []},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 422


async def test_bulk_update_count_all_success(
    client: AsyncClient, admin_token: str, db: AsyncSession
):
    await _seed_entry(db, key="test_bulk_c1", value="1.0")
    await _seed_entry(db, key="test_bulk_c2", value="2.0")
    resp = await client.post(
        "/api/v1/admin/config/bulk",
        json={
            "updates": [
                {"key": "test_bulk_c1", "value": "9.0"},
                {"key": "test_bulk_c2", "value": "8.0"},
            ]
        },
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["updated_count"] == 2
    assert data["failed_count"] == 0


async def test_bulk_update_failed_count_for_unknown_keys(
    client: AsyncClient, admin_token: str
):
    resp = await client.post(
        "/api/v1/admin/config/bulk",
        json={"updates": [{"key": "no_such_key_xyz", "value": "1.0"}]},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["failed_count"] == 1
    assert data["updated_count"] == 0


async def test_bulk_update_results_has_one_per_update(
    client: AsyncClient, admin_token: str, db: AsyncSession
):
    await _seed_entry(db, key="test_bulk_r1", value="1.0")
    resp = await client.post(
        "/api/v1/admin/config/bulk",
        json={
            "updates": [
                {"key": "test_bulk_r1", "value": "9.0"},
                {"key": "missing_r2", "value": "9.0"},
            ]
        },
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 2


async def test_bulk_update_mixed_success_failure(
    client: AsyncClient, admin_token: str, db: AsyncSession
):
    await _seed_entry(db, key="test_bulk_mix_good", value="1.0")
    resp = await client.post(
        "/api/v1/admin/config/bulk",
        json={
            "updates": [
                {"key": "test_bulk_mix_good", "value": "5.0"},
                {"key": "completely_missing_mix", "value": "5.0"},
            ]
        },
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["updated_count"] == 1
    assert data["failed_count"] == 1
    successes = [r for r in data["results"] if r["success"]]
    failures = [r for r in data["results"] if not r["success"]]
    assert len(successes) == 1
    assert len(failures) == 1
