"""Tests for the Corporate Preferred Driver Pool feature.

Service tests (async, mocked DB):
  1.  add_driver_to_pool — success creates new entry
  2.  add_driver_to_pool — duplicate active driver → 409
  3.  add_driver_to_pool — reactivates deactivated entry (upsert)
  4.  remove_driver_from_pool — success sets is_active=False
  5.  remove_driver_from_pool — driver not in pool → 404
  6.  remove_driver_from_pool — driver in pool but already inactive → 404
  7.  get_pool_entry — success returns active entry
  8.  get_pool_entry — not found → 404
  9.  get_pool_entry — found but inactive → 404
  10. list_pool_drivers — returns active entries by default
  11. list_pool_drivers — active_only=False returns all entries
  12. list_pool_drivers — empty pool returns empty list
  13. is_driver_preferred — True when driver is active pool member
  14. is_driver_preferred — False when not in pool
  15. is_driver_preferred — False when entry is inactive
  16. get_driver_pool_stats — returns correct count

Schema tests (sync):
  17. DriverPoolAddRequest — valid with notes
  18. DriverPoolAddRequest — valid without notes (notes defaults to None)
  19. DriverPoolAddRequest — notes too long → ValidationError
  20. DriverPoolEntryResponse — from_attributes works
  21. DriverPoolCheckResponse — is_preferred field
  22. DriverPoolStatsResponse — preferred_by_account_count field

API layer tests (services patched):
  23. GET  /corporate/accounts/me/driver-pool — 200 returns list
  24. POST /corporate/accounts/me/driver-pool — 201 creates entry
  25. GET  /corporate/accounts/me/driver-pool/{driver_id}/check — 200 True
  26. GET  /corporate/accounts/me/driver-pool/{driver_id}/check — 200 False
  27. GET  /corporate/accounts/me/driver-pool/{driver_id} — 200
  28. GET  /corporate/accounts/me/driver-pool/{driver_id} — 404
  29. DELETE /corporate/accounts/me/driver-pool/{driver_id} — 204
  30. GET /drivers/me/pool-stats — 200
  31. GET /admin/corporate/accounts/{id}/driver-pool — 200
  32. DELETE /admin/corporate/accounts/{id}/driver-pool/{driver_id} — 204
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate_driver_pool import CorporateDriverPool
from app.schemas.corporate_driver_pool import (
    DriverPoolAddRequest,
    DriverPoolCheckResponse,
    DriverPoolEntryResponse,
    DriverPoolListResponse,
    DriverPoolStatsResponse,
)
from app.services.corporate_driver_pool import (
    add_driver_to_pool,
    get_driver_pool_stats,
    get_pool_entry,
    is_driver_preferred,
    list_pool_drivers,
    remove_driver_from_pool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
_ACCOUNT_ID = 1
_DRIVER_ID = 7
_USER_ID = 10
_ENTRY_ID = 42


def _make_entry(
    id: int = _ENTRY_ID,
    account_id: int = _ACCOUNT_ID,
    driver_id: int = _DRIVER_ID,
    is_active: bool = True,
    notes: str | None = "Known reliable driver",
    added_by_id: int = _USER_ID,
) -> CorporateDriverPool:
    entry = CorporateDriverPool(
        id=id,
        account_id=account_id,
        driver_id=driver_id,
        is_active=is_active,
        notes=notes,
        added_by_id=added_by_id,
        added_at=_NOW,
    )
    return entry


def _mock_db_with_entry(
    entry: CorporateDriverPool | None,
) -> AsyncMock:
    """Mock DB returning *entry* from scalar_one_or_none."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = entry
    db.execute.return_value = result
    return db


def _mock_db_with_entries(entries: list[CorporateDriverPool]) -> AsyncMock:
    """Mock DB returning *entries* from scalars().all()."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = entries
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# Service: add_driver_to_pool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_driver_to_pool_success():
    """add_driver_to_pool creates a new active entry."""
    db = _mock_db_with_entry(None)  # no existing entry
    entry = await add_driver_to_pool(
        db,
        account_id=_ACCOUNT_ID,
        driver_id=_DRIVER_ID,
        added_by_id=_USER_ID,
        notes="VIP driver",
    )
    assert entry.account_id == _ACCOUNT_ID
    assert entry.driver_id == _DRIVER_ID
    assert entry.is_active is True
    assert entry.notes == "VIP driver"
    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_add_driver_to_pool_duplicate_active_raises_409():
    """add_driver_to_pool raises 409 when driver is already an active member."""
    existing = _make_entry(is_active=True)
    db = _mock_db_with_entry(existing)

    with pytest.raises(HTTPException) as exc_info:
        await add_driver_to_pool(
            db,
            account_id=_ACCOUNT_ID,
            driver_id=_DRIVER_ID,
            added_by_id=_USER_ID,
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_add_driver_to_pool_reactivates_inactive_entry():
    """add_driver_to_pool re-activates an existing deactivated entry."""
    existing = _make_entry(is_active=False, notes="Old notes")
    db = _mock_db_with_entry(existing)

    entry = await add_driver_to_pool(
        db,
        account_id=_ACCOUNT_ID,
        driver_id=_DRIVER_ID,
        added_by_id=_USER_ID,
        notes="Renewed",
    )
    assert entry.is_active is True
    assert entry.notes == "Renewed"
    db.add.assert_not_called()  # reused existing row
    db.flush.assert_called_once()


# ---------------------------------------------------------------------------
# Service: remove_driver_from_pool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_driver_from_pool_sets_inactive():
    """remove_driver_from_pool soft-deletes the entry."""
    entry = _make_entry(is_active=True)
    db = _mock_db_with_entry(entry)

    result = await remove_driver_from_pool(db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID)
    assert result.is_active is False
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_remove_driver_from_pool_not_in_pool_raises_404():
    """remove_driver_from_pool raises 404 when driver has never been added."""
    db = _mock_db_with_entry(None)

    with pytest.raises(HTTPException) as exc_info:
        await remove_driver_from_pool(db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_remove_driver_from_pool_already_inactive_raises_404():
    """remove_driver_from_pool raises 404 when the entry is already inactive."""
    inactive = _make_entry(is_active=False)
    db = _mock_db_with_entry(inactive)

    with pytest.raises(HTTPException) as exc_info:
        await remove_driver_from_pool(db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: get_pool_entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_pool_entry_success():
    """get_pool_entry returns the active entry."""
    entry = _make_entry()
    db = _mock_db_with_entry(entry)
    result = await get_pool_entry(db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID)
    assert result.id == _ENTRY_ID


@pytest.mark.asyncio
async def test_get_pool_entry_not_found_raises_404():
    """get_pool_entry raises 404 when driver is not in pool."""
    db = _mock_db_with_entry(None)
    with pytest.raises(HTTPException) as exc_info:
        await get_pool_entry(db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_pool_entry_inactive_raises_404():
    """get_pool_entry raises 404 for an inactive entry."""
    inactive = _make_entry(is_active=False)
    db = _mock_db_with_entry(inactive)
    with pytest.raises(HTTPException) as exc_info:
        await get_pool_entry(db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: list_pool_drivers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_pool_drivers_returns_active_by_default():
    """list_pool_drivers returns only active entries by default."""
    entries = [_make_entry(), _make_entry(id=43, driver_id=8)]
    db = _mock_db_with_entries(entries)
    result = await list_pool_drivers(db, account_id=_ACCOUNT_ID)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_pool_drivers_all_when_active_only_false():
    """list_pool_drivers with active_only=False returns all entries."""
    entries = [_make_entry(), _make_entry(id=43, driver_id=8, is_active=False)]
    db = _mock_db_with_entries(entries)
    result = await list_pool_drivers(db, account_id=_ACCOUNT_ID, active_only=False)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_pool_drivers_empty():
    """list_pool_drivers returns empty list when pool is empty."""
    db = _mock_db_with_entries([])
    result = await list_pool_drivers(db, account_id=_ACCOUNT_ID)
    assert result == []


# ---------------------------------------------------------------------------
# Service: is_driver_preferred
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_driver_preferred_true():
    """is_driver_preferred returns True for an active pool member."""
    entry = _make_entry(is_active=True)
    db = _mock_db_with_entry(entry)
    assert await is_driver_preferred(db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID) is True


@pytest.mark.asyncio
async def test_is_driver_preferred_false_not_in_pool():
    """is_driver_preferred returns False when driver is not in pool."""
    db = _mock_db_with_entry(None)
    assert await is_driver_preferred(db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID) is False


@pytest.mark.asyncio
async def test_is_driver_preferred_false_inactive():
    """is_driver_preferred returns False for an inactive pool entry."""
    entry = _make_entry(is_active=False)
    db = _mock_db_with_entry(entry)
    assert await is_driver_preferred(db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID) is False


# ---------------------------------------------------------------------------
# Service: get_driver_pool_stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_driver_pool_stats_returns_count():
    """get_driver_pool_stats returns the preferred account count."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one.return_value = 3
    db.execute.return_value = result
    count = await get_driver_pool_stats(db, driver_id=_DRIVER_ID)
    assert count == 3


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_driver_pool_add_request_with_notes():
    req = DriverPoolAddRequest(driver_id=7, notes="Punctual and professional")
    assert req.driver_id == 7
    assert req.notes == "Punctual and professional"


def test_driver_pool_add_request_notes_defaults_to_none():
    req = DriverPoolAddRequest(driver_id=7)
    assert req.notes is None


def test_driver_pool_add_request_notes_too_long_raises():
    with pytest.raises(ValidationError):
        DriverPoolAddRequest(driver_id=7, notes="x" * 501)


def test_driver_pool_entry_response_from_attributes():
    entry = _make_entry()
    resp = DriverPoolEntryResponse.model_validate(entry)
    assert resp.id == _ENTRY_ID
    assert resp.driver_id == _DRIVER_ID
    assert resp.is_active is True


def test_driver_pool_check_response():
    resp = DriverPoolCheckResponse(account_id=1, driver_id=7, is_preferred=True)
    assert resp.is_preferred is True


def test_driver_pool_stats_response():
    resp = DriverPoolStatsResponse(driver_id=7, preferred_by_account_count=5)
    assert resp.preferred_by_account_count == 5


# ---------------------------------------------------------------------------
# API layer tests (services patched)
# ---------------------------------------------------------------------------

_BASE = "/api/v1/corporate/accounts/me/driver-pool"
_ADMIN_BASE = "/api/v1/admin/corporate/accounts"

_DUMMY_ENTRY = _make_entry()


def _make_app_client():
    """Build a TestClient with auth + DB deps overridden."""
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = _USER_ID

    async def override_user():
        return mock_user

    async def override_admin():
        return mock_user

    async def override_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[require_admin] = override_admin
    app.dependency_overrides[get_db] = override_db
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _clear_dep_overrides():
    yield
    from app.main import app
    app.dependency_overrides.clear()


@patch(
    "app.api.v1.corporate_driver_pool._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_driver_pool.list_pool_drivers",
    new_callable=AsyncMock,
    return_value=[_DUMMY_ENTRY],
)
def test_api_list_driver_pool(mock_list, mock_resolve):
    client = _make_app_client()
    resp = client.get(_BASE)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1


@patch(
    "app.api.v1.corporate_driver_pool._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_driver_pool.add_driver_to_pool",
    new_callable=AsyncMock,
    return_value=_DUMMY_ENTRY,
)
def test_api_add_to_driver_pool(mock_add, mock_resolve):
    client = _make_app_client()
    resp = client.post(_BASE, json={"driver_id": _DRIVER_ID, "notes": "Great driver"})
    assert resp.status_code == 201
    assert resp.json()["driver_id"] == _DRIVER_ID


@patch(
    "app.api.v1.corporate_driver_pool._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_driver_pool.is_driver_preferred",
    new_callable=AsyncMock,
    return_value=True,
)
def test_api_check_driver_preferred_true(mock_check, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/{_DRIVER_ID}/check")
    assert resp.status_code == 200
    assert resp.json()["is_preferred"] is True


@patch(
    "app.api.v1.corporate_driver_pool._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_driver_pool.is_driver_preferred",
    new_callable=AsyncMock,
    return_value=False,
)
def test_api_check_driver_preferred_false(mock_check, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/{_DRIVER_ID}/check")
    assert resp.status_code == 200
    assert resp.json()["is_preferred"] is False


@patch(
    "app.api.v1.corporate_driver_pool._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_driver_pool.get_pool_entry",
    new_callable=AsyncMock,
    return_value=_DUMMY_ENTRY,
)
def test_api_get_pool_entry_200(mock_get, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/{_DRIVER_ID}")
    assert resp.status_code == 200
    assert resp.json()["id"] == _ENTRY_ID


@patch(
    "app.api.v1.corporate_driver_pool._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_driver_pool.get_pool_entry",
    new_callable=AsyncMock,
    side_effect=HTTPException(status_code=404, detail="Not found"),
)
def test_api_get_pool_entry_404(mock_get, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/9999")
    assert resp.status_code == 404


@patch(
    "app.api.v1.corporate_driver_pool._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_driver_pool.remove_driver_from_pool",
    new_callable=AsyncMock,
    return_value=_DUMMY_ENTRY,
)
def test_api_remove_from_driver_pool_204(mock_remove, mock_resolve):
    client = _make_app_client()
    resp = client.delete(f"{_BASE}/{_DRIVER_ID}")
    assert resp.status_code == 204


@patch(
    "app.api.v1.corporate_driver_pool.get_driver_pool_stats",
    new_callable=AsyncMock,
    return_value=2,
)
def test_api_driver_pool_stats(mock_stats):
    from app.models.driver import DriverProfile
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User
    import sqlalchemy

    mock_user = MagicMock(spec=User)
    mock_user.id = _USER_ID

    mock_driver = MagicMock(spec=DriverProfile)
    mock_driver.id = _DRIVER_ID

    # Mock db that returns the driver profile
    mock_db_instance = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_driver
    mock_db_instance.execute.return_value = mock_result

    async def override_user():
        return mock_user

    async def override_db():
        yield mock_db_instance

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_db] = override_db

    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/api/v1/drivers/me/pool-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "preferred_by_account_count" in data
    assert data["preferred_by_account_count"] == 2


@patch(
    "app.api.v1.corporate_driver_pool.list_pool_drivers",
    new_callable=AsyncMock,
    return_value=[_DUMMY_ENTRY, _make_entry(id=43, driver_id=8)],
)
def test_api_admin_list_driver_pool(mock_list):
    client = _make_app_client()
    resp = client.get(f"{_ADMIN_BASE}/{_ACCOUNT_ID}/driver-pool")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2


@patch(
    "app.api.v1.corporate_driver_pool.remove_driver_from_pool",
    new_callable=AsyncMock,
    return_value=_DUMMY_ENTRY,
)
def test_api_admin_remove_from_pool_204(mock_remove):
    client = _make_app_client()
    resp = client.delete(f"{_ADMIN_BASE}/{_ACCOUNT_ID}/driver-pool/{_DRIVER_ID}")
    assert resp.status_code == 204
