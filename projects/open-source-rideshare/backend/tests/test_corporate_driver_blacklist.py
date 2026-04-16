"""Tests for the Corporate Driver Blacklist feature.

Service tests (async, mocked DB):
  1.  add_driver_to_blacklist — success creates new entry
  2.  add_driver_to_blacklist — duplicate active driver → 409
  3.  add_driver_to_blacklist — reactivates deactivated entry (upsert)
  4.  remove_driver_from_blacklist — success sets is_active=False
  5.  remove_driver_from_blacklist — driver not blacklisted → 404
  6.  remove_driver_from_blacklist — entry exists but inactive → 404
  7.  get_blacklist_entry — success returns active entry
  8.  get_blacklist_entry — not found → 404
  9.  get_blacklist_entry — found but inactive → 404
  10. list_blacklisted_drivers — returns active entries by default
  11. list_blacklisted_drivers — active_only=False returns all entries
  12. list_blacklisted_drivers — empty blacklist returns empty list
  13. is_driver_blacklisted — True when driver is actively blacklisted
  14. is_driver_blacklisted — False when not in blacklist
  15. is_driver_blacklisted — False when entry is inactive
  16. get_blacklist_summary — returns correct counts
  17. list_all_platform — returns all entries across accounts
  18. list_all_platform — account_id filter works

Schema tests (sync):
  19. DriverBlacklistAddRequest — valid with reason
  20. DriverBlacklistAddRequest — valid without reason (defaults to None)
  21. DriverBlacklistAddRequest — reason too long → ValidationError
  22. DriverBlacklistEntryResponse — from_attributes works
  23. DriverBlacklistCheckResponse — is_blacklisted field
  24. DriverBlacklistListResponse — wraps items correctly

API layer tests (services patched):
  25. GET  /corporate/accounts/me/driver-blacklist — 200 returns list
  26. POST /corporate/accounts/me/driver-blacklist — 201 creates entry
  27. GET  /corporate/accounts/me/driver-blacklist/summary — 200
  28. GET  /corporate/accounts/me/driver-blacklist/{driver_id}/check — 200 True
  29. GET  /corporate/accounts/me/driver-blacklist/{driver_id}/check — 200 False
  30. GET  /corporate/accounts/me/driver-blacklist/{driver_id} — 200
  31. GET  /corporate/accounts/me/driver-blacklist/{driver_id} — 404
  32. DELETE /corporate/accounts/me/driver-blacklist/{driver_id} — 204
  33. GET /admin/corporate/accounts/{id}/driver-blacklist — 200
  34. DELETE /admin/corporate/accounts/{id}/driver-blacklist/{driver_id} — 204
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate_driver_blacklist import CorporateDriverBlacklist
from app.schemas.corporate_driver_blacklist import (
    DriverBlacklistAddRequest,
    DriverBlacklistCheckResponse,
    DriverBlacklistEntryResponse,
    DriverBlacklistListResponse,
)
from app.services.corporate_driver_blacklist import (
    add_driver_to_blacklist,
    get_blacklist_entry,
    get_blacklist_summary,
    is_driver_blacklisted,
    list_all_platform,
    list_blacklisted_drivers,
    remove_driver_from_blacklist,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
_ACCOUNT_ID = 1
_DRIVER_ID = 7
_USER_ID = 10
_ENTRY_ID = 42

_BASE = "/api/v1/corporate/accounts/me/driver-blacklist"
_ADMIN_BASE = "/api/v1/admin/corporate/accounts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    id: int = _ENTRY_ID,
    account_id: int = _ACCOUNT_ID,
    driver_id: int = _DRIVER_ID,
    is_active: bool = True,
    reason: str | None = "Rude to employees",
    blacklisted_by_id: int | None = _USER_ID,
) -> CorporateDriverBlacklist:
    entry = CorporateDriverBlacklist(
        id=id,
        account_id=account_id,
        driver_id=driver_id,
        is_active=is_active,
        reason=reason,
        blacklisted_by_id=blacklisted_by_id,
        blacklisted_at=_NOW,
    )
    return entry


def _mock_db_with_entry(
    entry: CorporateDriverBlacklist | None,
) -> AsyncMock:
    """Mock DB returning *entry* from scalar_one_or_none."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = entry
    db.execute.return_value = result
    return db


def _mock_db_with_entries(entries: list[CorporateDriverBlacklist]) -> AsyncMock:
    """Mock DB returning *entries* from scalars().all()."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = entries
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    return db


_DUMMY_ENTRY = _make_entry()


# ---------------------------------------------------------------------------
# Service: add_driver_to_blacklist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_driver_to_blacklist_success():
    """add_driver_to_blacklist creates a new active entry."""
    db = _mock_db_with_entry(None)  # no existing entry
    entry = await add_driver_to_blacklist(
        db,
        account_id=_ACCOUNT_ID,
        driver_id=_DRIVER_ID,
        blacklisted_by_id=_USER_ID,
        reason="Unsafe driving reported",
    )
    assert entry.account_id == _ACCOUNT_ID
    assert entry.driver_id == _DRIVER_ID
    assert entry.is_active is True
    assert entry.reason == "Unsafe driving reported"
    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_add_driver_to_blacklist_duplicate_active_raises_409():
    """add_driver_to_blacklist raises 409 when driver is already blacklisted."""
    existing = _make_entry(is_active=True)
    db = _mock_db_with_entry(existing)

    with pytest.raises(HTTPException) as exc_info:
        await add_driver_to_blacklist(
            db,
            account_id=_ACCOUNT_ID,
            driver_id=_DRIVER_ID,
            blacklisted_by_id=_USER_ID,
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_add_driver_to_blacklist_reactivates_inactive_entry():
    """add_driver_to_blacklist re-activates an existing lifted entry."""
    existing = _make_entry(is_active=False, reason="Old reason")
    db = _mock_db_with_entry(existing)

    entry = await add_driver_to_blacklist(
        db,
        account_id=_ACCOUNT_ID,
        driver_id=_DRIVER_ID,
        blacklisted_by_id=_USER_ID,
        reason="New complaint",
    )
    assert entry.is_active is True
    assert entry.reason == "New complaint"
    db.add.assert_not_called()  # reused existing row
    db.flush.assert_called_once()


# ---------------------------------------------------------------------------
# Service: remove_driver_from_blacklist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_driver_from_blacklist_success():
    """remove_driver_from_blacklist sets is_active=False."""
    existing = _make_entry(is_active=True)
    db = _mock_db_with_entry(existing)

    entry = await remove_driver_from_blacklist(
        db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID
    )
    assert entry.is_active is False
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_remove_driver_from_blacklist_not_found_raises_404():
    """remove_driver_from_blacklist raises 404 when driver is not blacklisted."""
    db = _mock_db_with_entry(None)

    with pytest.raises(HTTPException) as exc_info:
        await remove_driver_from_blacklist(
            db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_remove_driver_from_blacklist_inactive_raises_404():
    """remove_driver_from_blacklist raises 404 when entry exists but is inactive."""
    existing = _make_entry(is_active=False)
    db = _mock_db_with_entry(existing)

    with pytest.raises(HTTPException) as exc_info:
        await remove_driver_from_blacklist(
            db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID
        )
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: get_blacklist_entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_blacklist_entry_success():
    """get_blacklist_entry returns the active entry."""
    existing = _make_entry(is_active=True)
    db = _mock_db_with_entry(existing)

    entry = await get_blacklist_entry(
        db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID
    )
    assert entry.id == _ENTRY_ID
    assert entry.is_active is True


@pytest.mark.asyncio
async def test_get_blacklist_entry_not_found_raises_404():
    """get_blacklist_entry raises 404 when driver not in blacklist."""
    db = _mock_db_with_entry(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_blacklist_entry(db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_blacklist_entry_inactive_raises_404():
    """get_blacklist_entry raises 404 when entry exists but is inactive."""
    existing = _make_entry(is_active=False)
    db = _mock_db_with_entry(existing)

    with pytest.raises(HTTPException) as exc_info:
        await get_blacklist_entry(db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: list_blacklisted_drivers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_blacklisted_drivers_active_only():
    """list_blacklisted_drivers returns active entries by default."""
    entries = [_make_entry(is_active=True), _make_entry(id=43, driver_id=8, is_active=True)]
    db = _mock_db_with_entries(entries)

    result = await list_blacklisted_drivers(db, account_id=_ACCOUNT_ID)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_blacklisted_drivers_include_inactive():
    """list_blacklisted_drivers with active_only=False includes inactive entries."""
    entries = [
        _make_entry(is_active=True),
        _make_entry(id=43, driver_id=8, is_active=False),
    ]
    db = _mock_db_with_entries(entries)

    result = await list_blacklisted_drivers(
        db, account_id=_ACCOUNT_ID, active_only=False
    )
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_blacklisted_drivers_empty():
    """list_blacklisted_drivers returns an empty list when no entries."""
    db = _mock_db_with_entries([])

    result = await list_blacklisted_drivers(db, account_id=_ACCOUNT_ID)
    assert result == []


# ---------------------------------------------------------------------------
# Service: is_driver_blacklisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_driver_blacklisted_true():
    """is_driver_blacklisted returns True for an active entry."""
    existing = _make_entry(is_active=True)
    db = _mock_db_with_entry(existing)

    result = await is_driver_blacklisted(
        db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID
    )
    assert result is True


@pytest.mark.asyncio
async def test_is_driver_blacklisted_false_not_in_list():
    """is_driver_blacklisted returns False when driver is not in the blacklist."""
    db = _mock_db_with_entry(None)

    result = await is_driver_blacklisted(
        db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID
    )
    assert result is False


@pytest.mark.asyncio
async def test_is_driver_blacklisted_false_inactive():
    """is_driver_blacklisted returns False when the entry is inactive."""
    existing = _make_entry(is_active=False)
    db = _mock_db_with_entry(existing)

    result = await is_driver_blacklisted(
        db, account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID
    )
    assert result is False


# ---------------------------------------------------------------------------
# Service: get_blacklist_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_blacklist_summary_returns_correct_counts():
    """get_blacklist_summary returns active and total counts."""
    db = AsyncMock()
    total_result = MagicMock()
    total_result.scalar_one.return_value = 5
    active_result = MagicMock()
    active_result.scalar_one.return_value = 3

    db.execute.side_effect = [total_result, active_result]

    summary = await get_blacklist_summary(db, account_id=_ACCOUNT_ID)
    assert summary["account_id"] == _ACCOUNT_ID
    assert summary["total_entries"] == 5
    assert summary["active_blacklisted_count"] == 3


# ---------------------------------------------------------------------------
# Service: list_all_platform
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_platform_returns_all():
    """list_all_platform returns entries across accounts."""
    entries = [
        _make_entry(id=1, account_id=1, driver_id=7),
        _make_entry(id=2, account_id=2, driver_id=9),
    ]
    db = _mock_db_with_entries(entries)

    result = await list_all_platform(db)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_all_platform_account_filter():
    """list_all_platform filters by account_id when provided."""
    entries = [_make_entry(id=1, account_id=1, driver_id=7)]
    db = _mock_db_with_entries(entries)

    result = await list_all_platform(db, account_id=1)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_schema_add_request_with_reason():
    """DriverBlacklistAddRequest accepts valid driver_id and reason."""
    req = DriverBlacklistAddRequest(driver_id=7, reason="Repeated complaints")
    assert req.driver_id == 7
    assert req.reason == "Repeated complaints"


def test_schema_add_request_without_reason():
    """DriverBlacklistAddRequest defaults reason to None."""
    req = DriverBlacklistAddRequest(driver_id=7)
    assert req.reason is None


def test_schema_add_request_reason_too_long_raises():
    """DriverBlacklistAddRequest rejects reason > 500 chars."""
    with pytest.raises(ValidationError):
        DriverBlacklistAddRequest(driver_id=7, reason="x" * 501)


def test_schema_entry_response_from_attributes():
    """DriverBlacklistEntryResponse.model_validate works on the ORM model."""
    entry = _DUMMY_ENTRY
    resp = DriverBlacklistEntryResponse.model_validate(entry)
    assert resp.id == _ENTRY_ID
    assert resp.driver_id == _DRIVER_ID
    assert resp.is_active is True


def test_schema_check_response_is_blacklisted_field():
    """DriverBlacklistCheckResponse carries is_blacklisted bool."""
    resp = DriverBlacklistCheckResponse(
        account_id=_ACCOUNT_ID, driver_id=_DRIVER_ID, is_blacklisted=True
    )
    assert resp.is_blacklisted is True


def test_schema_list_response_wraps_items():
    """DriverBlacklistListResponse wraps items correctly."""
    entry = DriverBlacklistEntryResponse.model_validate(_DUMMY_ENTRY)
    resp = DriverBlacklistListResponse(
        account_id=_ACCOUNT_ID, total=1, items=[entry]
    )
    assert resp.total == 1
    assert resp.items[0].driver_id == _DRIVER_ID


# ---------------------------------------------------------------------------
# API fixtures
# ---------------------------------------------------------------------------


def _make_app_client() -> TestClient:
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


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------


@patch(
    "app.api.v1.corporate_driver_blacklist._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_driver_blacklist.list_blacklisted_drivers",
    new_callable=AsyncMock,
    return_value=[_DUMMY_ENTRY],
)
def test_api_list_driver_blacklist(mock_list, mock_resolve):
    client = _make_app_client()
    resp = client.get(_BASE)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1


@patch(
    "app.api.v1.corporate_driver_blacklist._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_driver_blacklist.add_driver_to_blacklist",
    new_callable=AsyncMock,
    return_value=_DUMMY_ENTRY,
)
def test_api_add_to_driver_blacklist(mock_add, mock_resolve):
    client = _make_app_client()
    resp = client.post(
        _BASE, json={"driver_id": _DRIVER_ID, "reason": "Unsafe behaviour"}
    )
    assert resp.status_code == 201
    assert resp.json()["driver_id"] == _DRIVER_ID


@patch(
    "app.api.v1.corporate_driver_blacklist._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_driver_blacklist.get_blacklist_summary",
    new_callable=AsyncMock,
    return_value={
        "account_id": _ACCOUNT_ID,
        "active_blacklisted_count": 2,
        "total_entries": 3,
    },
)
def test_api_get_blacklist_summary(mock_summary, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_blacklisted_count"] == 2
    assert data["total_entries"] == 3


@patch(
    "app.api.v1.corporate_driver_blacklist._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_driver_blacklist.is_driver_blacklisted",
    new_callable=AsyncMock,
    return_value=True,
)
def test_api_check_driver_blacklisted_true(mock_check, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/{_DRIVER_ID}/check")
    assert resp.status_code == 200
    assert resp.json()["is_blacklisted"] is True


@patch(
    "app.api.v1.corporate_driver_blacklist._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_driver_blacklist.is_driver_blacklisted",
    new_callable=AsyncMock,
    return_value=False,
)
def test_api_check_driver_blacklisted_false(mock_check, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/{_DRIVER_ID}/check")
    assert resp.status_code == 200
    assert resp.json()["is_blacklisted"] is False


@patch(
    "app.api.v1.corporate_driver_blacklist._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_driver_blacklist.get_blacklist_entry",
    new_callable=AsyncMock,
    return_value=_DUMMY_ENTRY,
)
def test_api_get_blacklist_entry_200(mock_get, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/{_DRIVER_ID}")
    assert resp.status_code == 200
    assert resp.json()["id"] == _ENTRY_ID


@patch(
    "app.api.v1.corporate_driver_blacklist._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_driver_blacklist.get_blacklist_entry",
    new_callable=AsyncMock,
    side_effect=HTTPException(status_code=404, detail="Not found"),
)
def test_api_get_blacklist_entry_404(mock_get, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/9999")
    assert resp.status_code == 404


@patch(
    "app.api.v1.corporate_driver_blacklist._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_driver_blacklist.remove_driver_from_blacklist",
    new_callable=AsyncMock,
    return_value=_DUMMY_ENTRY,
)
def test_api_remove_from_driver_blacklist_204(mock_remove, mock_resolve):
    client = _make_app_client()
    resp = client.delete(f"{_BASE}/{_DRIVER_ID}")
    assert resp.status_code == 204


@patch(
    "app.api.v1.corporate_driver_blacklist.list_blacklisted_drivers",
    new_callable=AsyncMock,
    return_value=[_DUMMY_ENTRY, _make_entry(id=43, driver_id=8)],
)
def test_api_admin_list_driver_blacklist(mock_list):
    client = _make_app_client()
    resp = client.get(f"{_ADMIN_BASE}/{_ACCOUNT_ID}/driver-blacklist")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2


@patch(
    "app.api.v1.corporate_driver_blacklist.remove_driver_from_blacklist",
    new_callable=AsyncMock,
    return_value=_DUMMY_ENTRY,
)
def test_api_admin_remove_from_blacklist_204(mock_remove):
    client = _make_app_client()
    resp = client.delete(
        f"{_ADMIN_BASE}/{_ACCOUNT_ID}/driver-blacklist/{_DRIVER_ID}"
    )
    assert resp.status_code == 204
