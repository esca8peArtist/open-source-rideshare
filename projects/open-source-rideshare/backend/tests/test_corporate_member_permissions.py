"""Tests for the Corporate Member Fine-Grained Permissions feature.

Service tests (async, mocked DB):
  1.  grant_permission — success creates new entry
  2.  grant_permission — duplicate active scope → 409
  3.  grant_permission — reactivates revoked entry (upsert)
  4.  grant_permission — reactivates expired entry (upsert)
  5.  revoke_permission — success sets is_active=False
  6.  revoke_permission — entry not found → 404
  7.  revoke_permission — entry already revoked → 404
  8.  get_permission — success returns entry
  9.  get_permission — not found → 404
  10. list_member_permissions — returns active entries by default
  11. list_member_permissions — active_only=False returns all entries
  12. list_account_permissions — returns all active grants for account
  13. list_account_permissions — scope filter applied
  14. has_permission — True when active non-expired grant exists
  15. has_permission — False when no entry exists
  16. has_permission — False when entry is inactive
  17. has_permission — False when entry is expired
  18. get_members_with_scope — returns members with given scope
  19. get_permission_summary — returns counts by scope
  20. list_all_platform — returns entries across accounts
  21. list_all_platform — account_id filter works
  22. list_all_platform — scope filter works

Schema tests (sync):
  23. PermissionGrantRequest — valid with all fields
  24. PermissionGrantRequest — valid without optional fields
  25. PermissionGrantRequest — notes too long → ValidationError
  26. PermissionResponse — from_attributes works
  27. PermissionCheckResponse — has_permission field
  28. PermissionListResponse — wraps items correctly
  29. PermissionSummaryResponse — by_scope list

API layer tests (services patched):
  30. GET  /corporate/accounts/me/permissions/my — 200 returns list
  31. POST /corporate/accounts/me/permissions — 201 creates grant
  32. POST /corporate/accounts/me/permissions — 409 on duplicate
  33. GET  /corporate/accounts/me/permissions — 200 returns all
  34. GET  /corporate/accounts/me/permissions/summary — 200
  35. GET  /corporate/accounts/me/permissions/scope/{scope} — 200
  36. GET  /corporate/accounts/me/permissions/member/{member_id} — 200
  37. GET  /corporate/accounts/me/permissions/check — 200 True
  38. GET  /corporate/accounts/me/permissions/check — 200 False
  39. DELETE /corporate/accounts/me/permissions/{id} — 204
  40. DELETE /corporate/accounts/me/permissions/{id} — 404
  41. GET  /admin/corporate/accounts/{id}/permissions — 200
  42. GET  /admin/corporate/accounts/{id}/permissions/member/{mid} — 200
  43. DELETE /admin/corporate/accounts/{id}/permissions/{pid} — 204
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate_member_permission import (
    CorporateMemberPermission,
    PermissionScope,
)
from app.schemas.corporate_member_permission import (
    PermissionCheckResponse,
    PermissionGrantRequest,
    PermissionListResponse,
    PermissionResponse,
    PermissionScopeCount,
    PermissionSummaryResponse,
)
from app.services.corporate_member_permission import (
    get_members_with_scope,
    get_permission,
    get_permission_summary,
    grant_permission,
    has_permission,
    list_account_permissions,
    list_all_platform,
    list_member_permissions,
    revoke_permission,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
_FUTURE = _NOW + timedelta(days=30)
_PAST = _NOW - timedelta(days=1)
_ACCOUNT_ID = 1
_MEMBER_ID = 5
_ADMIN_ID = 10
_PERM_ID = 42
_SCOPE = PermissionScope.BILLING_ADMIN

_BASE = "/api/v1/corporate/accounts/me/permissions"
_ADMIN_BASE = "/api/v1/admin/corporate/accounts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_perm(
    id: int = _PERM_ID,
    account_id: int = _ACCOUNT_ID,
    member_id: int = _MEMBER_ID,
    scope: PermissionScope = _SCOPE,
    is_active: bool = True,
    granted_by_id: int | None = _ADMIN_ID,
    expires_at: datetime | None = None,
    notes: str | None = None,
) -> CorporateMemberPermission:
    perm = CorporateMemberPermission(
        id=id,
        account_id=account_id,
        member_id=member_id,
        permission_scope=scope,
        is_active=is_active,
        granted_by_id=granted_by_id,
        granted_at=_NOW,
        expires_at=expires_at,
        notes=notes,
    )
    return perm


def _mock_db_with_entry(entry: CorporateMemberPermission | None) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = entry
    db.execute.return_value = result
    return db


def _mock_db_with_entries(entries: list[CorporateMemberPermission]) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = entries
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    return db


_DUMMY_PERM = _make_perm()


# ---------------------------------------------------------------------------
# Service: grant_permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grant_permission_success():
    """grant_permission creates a new active entry."""
    db = _mock_db_with_entry(None)  # no existing entry
    entry = await grant_permission(
        db,
        account_id=_ACCOUNT_ID,
        member_id=_MEMBER_ID,
        scope=_SCOPE,
        granted_by_id=_ADMIN_ID,
        expires_at=_FUTURE,
        notes="Finance team lead",
    )
    assert entry.account_id == _ACCOUNT_ID
    assert entry.member_id == _MEMBER_ID
    assert entry.permission_scope == _SCOPE
    assert entry.is_active is True
    assert entry.notes == "Finance team lead"
    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_grant_permission_duplicate_active_raises_409():
    """grant_permission raises 409 when member already holds an active, non-expired grant."""
    existing = _make_perm(is_active=True, expires_at=_FUTURE)
    db = _mock_db_with_entry(existing)

    with pytest.raises(HTTPException) as exc_info:
        await grant_permission(
            db,
            account_id=_ACCOUNT_ID,
            member_id=_MEMBER_ID,
            scope=_SCOPE,
            granted_by_id=_ADMIN_ID,
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_grant_permission_reactivates_revoked_entry():
    """grant_permission re-activates a previously revoked entry (upsert)."""
    existing = _make_perm(is_active=False, notes="Old note")
    db = _mock_db_with_entry(existing)

    entry = await grant_permission(
        db,
        account_id=_ACCOUNT_ID,
        member_id=_MEMBER_ID,
        scope=_SCOPE,
        granted_by_id=_ADMIN_ID,
        notes="Re-granted after role change",
    )
    assert entry.is_active is True
    assert entry.notes == "Re-granted after role change"
    db.add.assert_not_called()  # reused existing row
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_grant_permission_reactivates_expired_entry():
    """grant_permission re-activates an entry that has expired."""
    existing = _make_perm(is_active=True, expires_at=_PAST)
    db = _mock_db_with_entry(existing)

    entry = await grant_permission(
        db,
        account_id=_ACCOUNT_ID,
        member_id=_MEMBER_ID,
        scope=_SCOPE,
        granted_by_id=_ADMIN_ID,
        expires_at=_FUTURE,
    )
    assert entry.is_active is True
    assert entry.expires_at == _FUTURE
    db.add.assert_not_called()


# ---------------------------------------------------------------------------
# Service: revoke_permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_permission_success():
    """revoke_permission sets is_active=False."""
    existing = _make_perm(is_active=True)
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    db.execute.return_value = result

    entry = await revoke_permission(db, account_id=_ACCOUNT_ID, permission_id=_PERM_ID)
    assert entry.is_active is False
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_revoke_permission_not_found_raises_404():
    """revoke_permission raises 404 when entry does not exist."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await revoke_permission(db, account_id=_ACCOUNT_ID, permission_id=_PERM_ID)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_revoke_permission_already_revoked_raises_404():
    """revoke_permission raises 404 when entry is already inactive."""
    existing = _make_perm(is_active=False)
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    db.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await revoke_permission(db, account_id=_ACCOUNT_ID, permission_id=_PERM_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: get_permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_permission_success():
    """get_permission returns the entry by id."""
    existing = _make_perm()
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    db.execute.return_value = result

    entry = await get_permission(db, account_id=_ACCOUNT_ID, permission_id=_PERM_ID)
    assert entry.id == _PERM_ID


@pytest.mark.asyncio
async def test_get_permission_not_found_raises_404():
    """get_permission raises 404 when entry does not exist."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await get_permission(db, account_id=_ACCOUNT_ID, permission_id=_PERM_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: list_member_permissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_member_permissions_active_only():
    """list_member_permissions returns active entries by default."""
    perms = [_make_perm(), _make_perm(id=43, scope=PermissionScope.HR_ADMIN)]
    db = _mock_db_with_entries(perms)

    result = await list_member_permissions(
        db, account_id=_ACCOUNT_ID, member_id=_MEMBER_ID
    )
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_member_permissions_include_inactive():
    """list_member_permissions with active_only=False includes inactive entries."""
    perms = [
        _make_perm(),
        _make_perm(id=43, scope=PermissionScope.HR_ADMIN, is_active=False),
    ]
    db = _mock_db_with_entries(perms)

    result = await list_member_permissions(
        db, account_id=_ACCOUNT_ID, member_id=_MEMBER_ID, active_only=False
    )
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Service: list_account_permissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_account_permissions_returns_all_active():
    """list_account_permissions returns all active grants."""
    perms = [
        _make_perm(member_id=1),
        _make_perm(id=43, member_id=2, scope=PermissionScope.FLEET_MANAGER),
    ]
    db = _mock_db_with_entries(perms)

    result = await list_account_permissions(db, account_id=_ACCOUNT_ID)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_account_permissions_scope_filter():
    """list_account_permissions filters by scope when provided."""
    perms = [_make_perm()]
    db = _mock_db_with_entries(perms)

    result = await list_account_permissions(
        db, account_id=_ACCOUNT_ID, scope=PermissionScope.BILLING_ADMIN
    )
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Service: has_permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_has_permission_true():
    """has_permission returns True for an active non-expired grant."""
    existing = _make_perm(is_active=True, expires_at=_FUTURE)
    db = _mock_db_with_entry(existing)

    result = await has_permission(
        db, account_id=_ACCOUNT_ID, member_id=_MEMBER_ID, scope=_SCOPE
    )
    assert result is True


@pytest.mark.asyncio
async def test_has_permission_false_not_found():
    """has_permission returns False when no entry exists."""
    db = _mock_db_with_entry(None)

    result = await has_permission(
        db, account_id=_ACCOUNT_ID, member_id=_MEMBER_ID, scope=_SCOPE
    )
    assert result is False


@pytest.mark.asyncio
async def test_has_permission_false_inactive():
    """has_permission returns False when the entry is inactive."""
    existing = _make_perm(is_active=False)
    db = _mock_db_with_entry(existing)

    result = await has_permission(
        db, account_id=_ACCOUNT_ID, member_id=_MEMBER_ID, scope=_SCOPE
    )
    assert result is False


@pytest.mark.asyncio
async def test_has_permission_false_expired():
    """has_permission returns False when the entry has expired."""
    existing = _make_perm(is_active=True, expires_at=_PAST)
    db = _mock_db_with_entry(existing)

    result = await has_permission(
        db, account_id=_ACCOUNT_ID, member_id=_MEMBER_ID, scope=_SCOPE
    )
    assert result is False


# ---------------------------------------------------------------------------
# Service: get_members_with_scope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_members_with_scope_returns_entries():
    """get_members_with_scope returns all active entries for a scope."""
    perms = [_make_perm(member_id=1), _make_perm(id=43, member_id=2)]
    db = _mock_db_with_entries(perms)

    result = await get_members_with_scope(
        db, account_id=_ACCOUNT_ID, scope=_SCOPE
    )
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Service: get_permission_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_permission_summary_returns_counts():
    """get_permission_summary returns grouped counts and total."""
    db = AsyncMock()
    rows_result = MagicMock()
    rows_result.__iter__ = MagicMock(
        return_value=iter(
            [
                (PermissionScope.BILLING_ADMIN, 3),
                (PermissionScope.HR_ADMIN, 1),
            ]
        )
    )
    db.execute.return_value = rows_result

    summary = await get_permission_summary(db, account_id=_ACCOUNT_ID)
    assert summary["account_id"] == _ACCOUNT_ID
    assert summary["total_active_grants"] == 4
    assert len(summary["by_scope"]) == 2


# ---------------------------------------------------------------------------
# Service: list_all_platform
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_platform_returns_all():
    """list_all_platform returns entries across all accounts."""
    perms = [
        _make_perm(id=1, account_id=1),
        _make_perm(id=2, account_id=2),
    ]
    db = _mock_db_with_entries(perms)

    result = await list_all_platform(db)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_all_platform_account_filter():
    """list_all_platform filters by account_id when provided."""
    perms = [_make_perm(id=1, account_id=1)]
    db = _mock_db_with_entries(perms)

    result = await list_all_platform(db, account_id=1)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_all_platform_scope_filter():
    """list_all_platform filters by scope when provided."""
    perms = [_make_perm(scope=PermissionScope.BILLING_ADMIN)]
    db = _mock_db_with_entries(perms)

    result = await list_all_platform(db, scope=PermissionScope.BILLING_ADMIN)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_schema_grant_request_all_fields():
    """PermissionGrantRequest accepts all valid fields."""
    req = PermissionGrantRequest(
        member_id=_MEMBER_ID,
        permission_scope=PermissionScope.BILLING_ADMIN,
        expires_at=_FUTURE,
        notes="Temporary access for audit period",
    )
    assert req.member_id == _MEMBER_ID
    assert req.permission_scope == PermissionScope.BILLING_ADMIN
    assert req.notes == "Temporary access for audit period"


def test_schema_grant_request_minimal():
    """PermissionGrantRequest works without optional fields."""
    req = PermissionGrantRequest(
        member_id=_MEMBER_ID,
        permission_scope=PermissionScope.REPORT_VIEWER,
    )
    assert req.expires_at is None
    assert req.notes is None


def test_schema_grant_request_notes_too_long_raises():
    """PermissionGrantRequest rejects notes > 500 chars."""
    with pytest.raises(ValidationError):
        PermissionGrantRequest(
            member_id=_MEMBER_ID,
            permission_scope=PermissionScope.SSO_ADMIN,
            notes="x" * 501,
        )


def test_schema_permission_response_from_attributes():
    """PermissionResponse.model_validate works on the ORM model."""
    resp = PermissionResponse.model_validate(_DUMMY_PERM)
    assert resp.id == _PERM_ID
    assert resp.member_id == _MEMBER_ID
    assert resp.permission_scope == _SCOPE
    assert resp.is_active is True


def test_schema_check_response_has_permission_field():
    """PermissionCheckResponse carries has_permission bool."""
    resp = PermissionCheckResponse(
        account_id=_ACCOUNT_ID,
        member_id=_MEMBER_ID,
        permission_scope=_SCOPE,
        has_permission=True,
    )
    assert resp.has_permission is True


def test_schema_list_response_wraps_items():
    """PermissionListResponse wraps items correctly."""
    entry = PermissionResponse.model_validate(_DUMMY_PERM)
    resp = PermissionListResponse(
        account_id=_ACCOUNT_ID,
        total=1,
        items=[entry],
    )
    assert resp.total == 1
    assert resp.items[0].member_id == _MEMBER_ID


def test_schema_summary_response():
    """PermissionSummaryResponse holds by_scope list."""
    resp = PermissionSummaryResponse(
        account_id=_ACCOUNT_ID,
        total_active_grants=5,
        by_scope=[
            PermissionScopeCount(
                permission_scope=PermissionScope.BILLING_ADMIN, active_count=5
            )
        ],
    )
    assert resp.total_active_grants == 5
    assert resp.by_scope[0].active_count == 5


# ---------------------------------------------------------------------------
# API fixtures
# ---------------------------------------------------------------------------


def _make_app_client() -> TestClient:
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = _ADMIN_ID

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

_MODULE = "app.api.v1.corporate_member_permission"


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(f"{_MODULE}.list_member_permissions", new_callable=AsyncMock, return_value=[_DUMMY_PERM])
def test_api_list_my_permissions(mock_list, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/my")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(f"{_MODULE}.grant_permission", new_callable=AsyncMock, return_value=_DUMMY_PERM)
def test_api_grant_permission_201(mock_grant, mock_resolve):
    client = _make_app_client()
    resp = client.post(
        _BASE,
        json={
            "member_id": _MEMBER_ID,
            "permission_scope": "billing_admin",
            "notes": "Finance lead",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["member_id"] == _MEMBER_ID


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(
    f"{_MODULE}.grant_permission",
    new_callable=AsyncMock,
    side_effect=HTTPException(status_code=409, detail="Already active"),
)
def test_api_grant_permission_409(mock_grant, mock_resolve):
    client = _make_app_client()
    resp = client.post(
        _BASE,
        json={"member_id": _MEMBER_ID, "permission_scope": "billing_admin"},
    )
    assert resp.status_code == 409


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(
    f"{_MODULE}.list_account_permissions",
    new_callable=AsyncMock,
    return_value=[_DUMMY_PERM],
)
def test_api_list_account_permissions(mock_list, mock_resolve):
    client = _make_app_client()
    resp = client.get(_BASE)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(
    f"{_MODULE}.get_permission_summary",
    new_callable=AsyncMock,
    return_value={
        "account_id": _ACCOUNT_ID,
        "total_active_grants": 4,
        "by_scope": [
            {"permission_scope": "billing_admin", "active_count": 3},
            {"permission_scope": "hr_admin", "active_count": 1},
        ],
    },
)
def test_api_get_permission_summary(mock_summary, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_active_grants"] == 4
    assert len(data["by_scope"]) == 2


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(
    f"{_MODULE}.get_members_with_scope",
    new_callable=AsyncMock,
    return_value=[_DUMMY_PERM],
)
def test_api_list_members_with_scope(mock_members, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/scope/billing_admin")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(
    f"{_MODULE}.list_member_permissions",
    new_callable=AsyncMock,
    return_value=[_DUMMY_PERM],
)
def test_api_list_member_permission_grants(mock_list, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/member/{_MEMBER_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(f"{_MODULE}.has_permission", new_callable=AsyncMock, return_value=True)
def test_api_check_member_permission_true(mock_check, mock_resolve):
    client = _make_app_client()
    resp = client.get(
        f"{_BASE}/check",
        params={"member_id": _MEMBER_ID, "scope": "billing_admin"},
    )
    assert resp.status_code == 200
    assert resp.json()["has_permission"] is True


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(f"{_MODULE}.has_permission", new_callable=AsyncMock, return_value=False)
def test_api_check_member_permission_false(mock_check, mock_resolve):
    client = _make_app_client()
    resp = client.get(
        f"{_BASE}/check",
        params={"member_id": _MEMBER_ID, "scope": "fleet_manager"},
    )
    assert resp.status_code == 200
    assert resp.json()["has_permission"] is False


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(f"{_MODULE}.revoke_permission", new_callable=AsyncMock, return_value=_DUMMY_PERM)
def test_api_revoke_permission_204(mock_revoke, mock_resolve):
    client = _make_app_client()
    resp = client.delete(f"{_BASE}/{_PERM_ID}")
    assert resp.status_code == 204


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(
    f"{_MODULE}.revoke_permission",
    new_callable=AsyncMock,
    side_effect=HTTPException(status_code=404, detail="Not found"),
)
def test_api_revoke_permission_404(mock_revoke, mock_resolve):
    client = _make_app_client()
    resp = client.delete(f"{_BASE}/9999")
    assert resp.status_code == 404


@patch(
    f"{_MODULE}.list_account_permissions",
    new_callable=AsyncMock,
    return_value=[_DUMMY_PERM, _make_perm(id=43, member_id=6)],
)
def test_api_admin_list_permissions(mock_list):
    client = _make_app_client()
    resp = client.get(f"{_ADMIN_BASE}/{_ACCOUNT_ID}/permissions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2


@patch(
    f"{_MODULE}.list_member_permissions",
    new_callable=AsyncMock,
    return_value=[_DUMMY_PERM],
)
def test_api_admin_list_member_permissions(mock_list):
    client = _make_app_client()
    resp = client.get(
        f"{_ADMIN_BASE}/{_ACCOUNT_ID}/permissions/member/{_MEMBER_ID}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1


@patch(f"{_MODULE}.revoke_permission", new_callable=AsyncMock, return_value=_DUMMY_PERM)
def test_api_admin_revoke_permission_204(mock_revoke):
    client = _make_app_client()
    resp = client.delete(
        f"{_ADMIN_BASE}/{_ACCOUNT_ID}/permissions/{_PERM_ID}"
    )
    assert resp.status_code == 204
