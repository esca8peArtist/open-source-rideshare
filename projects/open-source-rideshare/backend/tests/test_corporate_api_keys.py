"""Tests for the Corporate API Keys feature.

Service tests (async, mocked DB):
  1.  create_api_key — success, returns (key, plain_key)
  2.  create_api_key — plain_key has rsk_ prefix
  3.  create_api_key — key_hash is SHA-256 of plain_key
  4.  create_api_key — key_prefix is first 8 chars of plain_key
  5.  create_api_key — unknown scope → 422
  6.  create_api_key — multiple unknown scopes → 422
  7.  create_api_key — empty scopes allowed
  8.  create_api_key — scopes=None defaults to empty list
  9.  get_api_key — success
  10. get_api_key — wrong account → 404
  11. list_api_keys — active_only=True returns only active
  12. list_api_keys — active_only=False returns all
  13. list_api_keys — empty list when no keys
  14. update_api_key — name updated
  15. update_api_key — scopes updated
  16. update_api_key — expires_at updated
  17. update_api_key — unknown scope → 422
  18. update_api_key — not found → 404
  19. revoke_api_key — success: is_active=False
  20. revoke_api_key — already revoked → 409
  21. revoke_api_key — not found → 404
  22. delete_api_key — success
  23. delete_api_key — not found → 404
  24. rotate_api_key — success, new plain_key returned
  25. rotate_api_key — new hash differs from old
  26. rotate_api_key — key_prefix updated to new value
  27. rotate_api_key — revoked key is re-activated
  28. rotate_api_key — not found → 404
  29. verify_api_key — success returns key
  30. verify_api_key — wrong key returns None
  31. verify_api_key — inactive key returns None
  32. verify_api_key — expired key returns None
  33. verify_api_key — non-expired key passes

Schema tests (sync):
  34. ApiKeyCreate — valid
  35. ApiKeyCreate — expires_at optional
  36. ApiKeyUpdate — all fields optional
  37. ApiKeyResponse — from_attributes
  38. ApiKeyCreateResponse — includes plain_key

API layer tests (service patched):
  39. GET  /corporate/accounts/me/api-keys — 200
  40. POST /corporate/accounts/me/api-keys — 201, plain_key present
  41. GET  /corporate/accounts/me/api-keys/{id} — 200
  42. PUT  /corporate/accounts/me/api-keys/{id} — 200
  43. DELETE /corporate/accounts/me/api-keys/{id}/revoke — 200
  44. DELETE /corporate/accounts/me/api-keys/{id} — 204
  45. POST /corporate/accounts/me/api-keys/{id}/rotate — 200, plain_key present
  46. GET  /admin/corporate/accounts/{account_id}/api-keys — 200
  47. POST /admin/corporate/api-keys/verify — 200 valid key
  48. POST /admin/corporate/api-keys/verify — 200 invalid key returns valid=False

Extras:
  49. KNOWN_SCOPES contains all 6 expected scopes
  50. _generate_api_key returns rsk_-prefixed string of correct length
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate_api_key import CorporateApiKey
from app.schemas.corporate_api_key import (
    ApiKeyCreate,
    ApiKeyCreateResponse,
    ApiKeyListResponse,
    ApiKeyResponse,
    ApiKeyUpdate,
    ApiKeyVerifyRequest,
    ApiKeyVerifyResponse,
)
from app.services.corporate_api_key import (
    KNOWN_SCOPES,
    _generate_api_key,
    _hash_key,
    create_api_key,
    delete_api_key,
    get_api_key,
    list_api_keys,
    revoke_api_key,
    rotate_api_key,
    update_api_key,
    verify_api_key,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_key(
    account_id: int = 1,
    name: str = "Test Key",
    scopes: list[str] | None = None,
    is_active: bool = True,
    expires_at: datetime | None = None,
) -> CorporateApiKey:
    plain = _generate_api_key()
    key_obj = CorporateApiKey(
        id=uuid.uuid4(),
        account_id=account_id,
        name=name,
        key_prefix=plain[:8],
        key_hash=_hash_key(plain),
        scopes=scopes or [],
        is_active=is_active,
        expires_at=expires_at,
        last_used_at=None,
        created_by_id=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    return key_obj


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_api_key_success():
    db = _mock_db()
    key_obj, plain_key = await create_api_key(db, account_id=1, name="CI key")
    assert key_obj.account_id == 1
    assert key_obj.name == "CI key"
    assert plain_key is not None
    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_create_api_key_prefix():
    db = _mock_db()
    key_obj, plain_key = await create_api_key(db, account_id=1, name="k")
    assert plain_key.startswith("rsk_")


@pytest.mark.asyncio
async def test_create_api_key_hash():
    db = _mock_db()
    key_obj, plain_key = await create_api_key(db, account_id=1, name="k")
    expected = hashlib.sha256(plain_key.encode()).hexdigest()
    assert key_obj.key_hash == expected


@pytest.mark.asyncio
async def test_create_api_key_key_prefix_field():
    db = _mock_db()
    key_obj, plain_key = await create_api_key(db, account_id=1, name="k")
    assert key_obj.key_prefix == plain_key[:8]


@pytest.mark.asyncio
async def test_create_api_key_unknown_scope():
    db = _mock_db()
    with pytest.raises(HTTPException) as exc_info:
        await create_api_key(db, account_id=1, name="k", scopes=["super:admin"])
    assert exc_info.value.status_code == 422
    assert "super:admin" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_api_key_multiple_unknown_scopes():
    db = _mock_db()
    with pytest.raises(HTTPException) as exc_info:
        await create_api_key(db, account_id=1, name="k", scopes=["a:b", "c:d"])
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_create_api_key_empty_scopes():
    db = _mock_db()
    key_obj, _ = await create_api_key(db, account_id=1, name="k", scopes=[])
    assert key_obj.scopes == []


@pytest.mark.asyncio
async def test_create_api_key_none_scopes_defaults_empty():
    db = _mock_db()
    key_obj, _ = await create_api_key(db, account_id=1, name="k", scopes=None)
    assert key_obj.scopes == []


@pytest.mark.asyncio
async def test_get_api_key_success():
    key_obj = _make_key()
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = key_obj
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_api_key(db, account_id=key_obj.account_id, key_id=key_obj.id)
    assert result is key_obj


@pytest.mark.asyncio
async def test_get_api_key_wrong_account():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HTTPException) as exc_info:
        await get_api_key(db, account_id=99, key_id=uuid.uuid4())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_api_keys_active_only():
    active_key = _make_key(is_active=True)
    inactive_key = _make_key(is_active=False)
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [active_key]
    db.execute = AsyncMock(return_value=mock_result)

    keys = await list_api_keys(db, account_id=1, active_only=True)
    assert len(keys) == 1
    assert keys[0].is_active


@pytest.mark.asyncio
async def test_list_api_keys_all():
    active_key = _make_key(is_active=True)
    inactive_key = _make_key(is_active=False)
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [active_key, inactive_key]
    db.execute = AsyncMock(return_value=mock_result)

    keys = await list_api_keys(db, account_id=1, active_only=False)
    assert len(keys) == 2


@pytest.mark.asyncio
async def test_list_api_keys_empty():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)

    keys = await list_api_keys(db, account_id=1)
    assert keys == []


@pytest.mark.asyncio
async def test_update_api_key_name():
    key_obj = _make_key(name="Old Name")
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = key_obj
    db.execute = AsyncMock(return_value=mock_result)

    updated = await update_api_key(db, account_id=1, key_id=key_obj.id, name="New Name")
    assert updated.name == "New Name"


@pytest.mark.asyncio
async def test_update_api_key_scopes():
    key_obj = _make_key()
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = key_obj
    db.execute = AsyncMock(return_value=mock_result)

    updated = await update_api_key(
        db, account_id=1, key_id=key_obj.id, scopes=["rides:read", "invoices:read"]
    )
    assert "rides:read" in updated.scopes


@pytest.mark.asyncio
async def test_update_api_key_expires_at():
    key_obj = _make_key()
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = key_obj
    db.execute = AsyncMock(return_value=mock_result)

    new_expiry = datetime.now(timezone.utc) + timedelta(days=30)
    updated = await update_api_key(
        db, account_id=1, key_id=key_obj.id, expires_at=new_expiry
    )
    assert updated.expires_at == new_expiry


@pytest.mark.asyncio
async def test_update_api_key_unknown_scope():
    key_obj = _make_key()
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = key_obj
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HTTPException) as exc_info:
        await update_api_key(db, account_id=1, key_id=key_obj.id, scopes=["bad:scope"])
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_update_api_key_not_found():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HTTPException) as exc_info:
        await update_api_key(db, account_id=1, key_id=uuid.uuid4(), name="x")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_revoke_api_key_success():
    key_obj = _make_key(is_active=True)
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = key_obj
    db.execute = AsyncMock(return_value=mock_result)

    result = await revoke_api_key(db, account_id=1, key_id=key_obj.id)
    assert not result.is_active


@pytest.mark.asyncio
async def test_revoke_api_key_already_revoked():
    key_obj = _make_key(is_active=False)
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = key_obj
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HTTPException) as exc_info:
        await revoke_api_key(db, account_id=1, key_id=key_obj.id)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_revoke_api_key_not_found():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HTTPException) as exc_info:
        await revoke_api_key(db, account_id=1, key_id=uuid.uuid4())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_api_key_success():
    key_obj = _make_key()
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = key_obj
    db.execute = AsyncMock(return_value=mock_result)

    await delete_api_key(db, account_id=1, key_id=key_obj.id)
    db.delete.assert_called_once_with(key_obj)


@pytest.mark.asyncio
async def test_delete_api_key_not_found():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HTTPException) as exc_info:
        await delete_api_key(db, account_id=1, key_id=uuid.uuid4())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_rotate_api_key_success():
    key_obj = _make_key()
    old_hash = key_obj.key_hash
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = key_obj
    db.execute = AsyncMock(return_value=mock_result)

    _, plain_key = await rotate_api_key(db, account_id=1, key_id=key_obj.id)
    assert plain_key.startswith("rsk_")


@pytest.mark.asyncio
async def test_rotate_api_key_new_hash():
    key_obj = _make_key()
    old_hash = key_obj.key_hash
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = key_obj
    db.execute = AsyncMock(return_value=mock_result)

    updated, plain_key = await rotate_api_key(db, account_id=1, key_id=key_obj.id)
    assert updated.key_hash != old_hash
    assert updated.key_hash == _hash_key(plain_key)


@pytest.mark.asyncio
async def test_rotate_api_key_prefix_updated():
    key_obj = _make_key()
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = key_obj
    db.execute = AsyncMock(return_value=mock_result)

    updated, plain_key = await rotate_api_key(db, account_id=1, key_id=key_obj.id)
    assert updated.key_prefix == plain_key[:8]


@pytest.mark.asyncio
async def test_rotate_api_key_reactivates_revoked():
    key_obj = _make_key(is_active=False)
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = key_obj
    db.execute = AsyncMock(return_value=mock_result)

    updated, _ = await rotate_api_key(db, account_id=1, key_id=key_obj.id)
    assert updated.is_active


@pytest.mark.asyncio
async def test_rotate_api_key_not_found():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HTTPException) as exc_info:
        await rotate_api_key(db, account_id=1, key_id=uuid.uuid4())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_verify_api_key_success():
    plain = _generate_api_key()
    key_obj = _make_key(is_active=True)
    key_obj.key_hash = _hash_key(plain)

    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = key_obj
    db.execute = AsyncMock(return_value=mock_result)

    result = await verify_api_key(db, plain)
    assert result is key_obj
    assert result.last_used_at is not None


@pytest.mark.asyncio
async def test_verify_api_key_wrong_key():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    result = await verify_api_key(db, "rsk_notavalidkey")
    assert result is None


@pytest.mark.asyncio
async def test_verify_api_key_inactive():
    plain = _generate_api_key()
    key_obj = _make_key(is_active=False)
    key_obj.key_hash = _hash_key(plain)

    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = key_obj
    db.execute = AsyncMock(return_value=mock_result)

    result = await verify_api_key(db, plain)
    assert result is None


@pytest.mark.asyncio
async def test_verify_api_key_expired():
    plain = _generate_api_key()
    past = datetime.now(timezone.utc) - timedelta(days=1)
    key_obj = _make_key(is_active=True, expires_at=past)
    key_obj.key_hash = _hash_key(plain)

    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = key_obj
    db.execute = AsyncMock(return_value=mock_result)

    result = await verify_api_key(db, plain)
    assert result is None


@pytest.mark.asyncio
async def test_verify_api_key_not_expired():
    plain = _generate_api_key()
    future = datetime.now(timezone.utc) + timedelta(days=30)
    key_obj = _make_key(is_active=True, expires_at=future)
    key_obj.key_hash = _hash_key(plain)

    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = key_obj
    db.execute = AsyncMock(return_value=mock_result)

    result = await verify_api_key(db, plain)
    assert result is key_obj


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_api_key_create_valid():
    data = ApiKeyCreate(name="HRIS integration", scopes=["rides:read"])
    assert data.name == "HRIS integration"
    assert "rides:read" in data.scopes


def test_api_key_create_expires_at_optional():
    data = ApiKeyCreate(name="k")
    assert data.expires_at is None


def test_api_key_update_all_optional():
    data = ApiKeyUpdate()
    assert data.name is None
    assert data.scopes is None
    assert data.expires_at is None


def test_api_key_response_from_attributes():
    key_obj = _make_key()
    resp = ApiKeyResponse.model_validate(key_obj)
    assert resp.account_id == key_obj.account_id
    assert resp.name == key_obj.name
    assert resp.key_prefix == key_obj.key_prefix


def test_api_key_create_response_includes_plain_key():
    key_obj = _make_key()
    resp = ApiKeyCreateResponse(
        **ApiKeyResponse.model_validate(key_obj).model_dump(),
        plain_key="rsk_abc123",
    )
    assert resp.plain_key == "rsk_abc123"


# ---------------------------------------------------------------------------
# API layer tests (dependency overrides + service patched)
# ---------------------------------------------------------------------------

_BASE = "/api/v1"
_ACCOUNT_ID = 5
_ADMIN_ID = 99


def _get_test_client():
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = _ADMIN_ID
    mock_user.is_admin = True

    async def override_user():
        return mock_user

    async def override_db():
        yield AsyncMock()

    async def override_admin():
        return mock_user

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = override_admin

    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def clear_overrides():
    from app.main import app
    yield
    app.dependency_overrides.clear()


def test_list_keys_endpoint():
    """39. GET /corporate/accounts/me/api-keys — 200."""
    client = _get_test_client()
    key_obj = _make_key(account_id=_ACCOUNT_ID)

    with (
        patch("app.api.v1.corporate_api_keys._resolve_account_id", new=AsyncMock(return_value=_ACCOUNT_ID)),
        patch("app.api.v1.corporate_api_keys.list_api_keys", new=AsyncMock(return_value=[key_obj])),
    ):
        resp = client.get(f"{_BASE}/corporate/accounts/me/api-keys")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["account_id"] == _ACCOUNT_ID


def test_create_key_endpoint():
    """40. POST /corporate/accounts/me/api-keys — 201, plain_key present."""
    client = _get_test_client()
    key_obj = _make_key(account_id=_ACCOUNT_ID)
    plain_key = _generate_api_key()

    with (
        patch("app.api.v1.corporate_api_keys._resolve_account_id", new=AsyncMock(return_value=_ACCOUNT_ID)),
        patch(
            "app.api.v1.corporate_api_keys.create_api_key",
            new=AsyncMock(return_value=(key_obj, plain_key)),
        ),
    ):
        resp = client.post(
            f"{_BASE}/corporate/accounts/me/api-keys",
            json={"name": "CI key", "scopes": ["rides:read"]},
        )
    assert resp.status_code == 201
    assert "plain_key" in resp.json()
    assert resp.json()["plain_key"] == plain_key


def test_get_key_endpoint():
    """41. GET /corporate/accounts/me/api-keys/{id} — 200."""
    client = _get_test_client()
    key_obj = _make_key(account_id=_ACCOUNT_ID)

    with (
        patch("app.api.v1.corporate_api_keys._resolve_account_id", new=AsyncMock(return_value=_ACCOUNT_ID)),
        patch("app.api.v1.corporate_api_keys.get_api_key", new=AsyncMock(return_value=key_obj)),
    ):
        resp = client.get(f"{_BASE}/corporate/accounts/me/api-keys/{key_obj.id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == key_obj.name


def test_update_key_endpoint():
    """42. PUT /corporate/accounts/me/api-keys/{id} — 200."""
    client = _get_test_client()
    key_obj = _make_key(account_id=_ACCOUNT_ID, name="Updated")

    with (
        patch("app.api.v1.corporate_api_keys._resolve_account_id", new=AsyncMock(return_value=_ACCOUNT_ID)),
        patch("app.api.v1.corporate_api_keys.update_api_key", new=AsyncMock(return_value=key_obj)),
    ):
        resp = client.put(
            f"{_BASE}/corporate/accounts/me/api-keys/{key_obj.id}",
            json={"name": "Updated"},
        )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated"


def test_revoke_key_endpoint():
    """43. DELETE /corporate/accounts/me/api-keys/{id}/revoke — 200."""
    client = _get_test_client()
    key_obj = _make_key(account_id=_ACCOUNT_ID, is_active=False)

    with (
        patch("app.api.v1.corporate_api_keys._resolve_account_id", new=AsyncMock(return_value=_ACCOUNT_ID)),
        patch("app.api.v1.corporate_api_keys.revoke_api_key", new=AsyncMock(return_value=key_obj)),
    ):
        resp = client.delete(
            f"{_BASE}/corporate/accounts/me/api-keys/{key_obj.id}/revoke"
        )
    assert resp.status_code == 200
    assert not resp.json()["is_active"]


def test_delete_key_endpoint():
    """44. DELETE /corporate/accounts/me/api-keys/{id} — 204."""
    client = _get_test_client()

    with (
        patch("app.api.v1.corporate_api_keys._resolve_account_id", new=AsyncMock(return_value=_ACCOUNT_ID)),
        patch("app.api.v1.corporate_api_keys.delete_api_key", new=AsyncMock(return_value=None)),
    ):
        resp = client.delete(
            f"{_BASE}/corporate/accounts/me/api-keys/{uuid.uuid4()}"
        )
    assert resp.status_code == 204


def test_rotate_key_endpoint():
    """45. POST /corporate/accounts/me/api-keys/{id}/rotate — 200, plain_key present."""
    client = _get_test_client()
    key_obj = _make_key(account_id=_ACCOUNT_ID)
    plain_key = _generate_api_key()

    with (
        patch("app.api.v1.corporate_api_keys._resolve_account_id", new=AsyncMock(return_value=_ACCOUNT_ID)),
        patch(
            "app.api.v1.corporate_api_keys.rotate_api_key",
            new=AsyncMock(return_value=(key_obj, plain_key)),
        ),
    ):
        resp = client.post(
            f"{_BASE}/corporate/accounts/me/api-keys/{key_obj.id}/rotate"
        )
    assert resp.status_code == 200
    assert "plain_key" in resp.json()


def test_platform_admin_list_keys_endpoint():
    """46. GET /admin/corporate/accounts/{account_id}/api-keys — 200."""
    client = _get_test_client()
    key_obj = _make_key(account_id=7)

    with patch("app.api.v1.corporate_api_keys.list_api_keys", new=AsyncMock(return_value=[key_obj])):
        resp = client.get(f"{_BASE}/admin/corporate/accounts/7/api-keys")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_platform_admin_verify_valid_key():
    """47. POST /admin/corporate/api-keys/verify — 200 valid key."""
    client = _get_test_client()
    key_obj = _make_key(account_id=7)

    with patch("app.api.v1.corporate_api_keys.verify_api_key", new=AsyncMock(return_value=key_obj)):
        resp = client.post(
            f"{_BASE}/admin/corporate/api-keys/verify",
            json={"raw_key": "rsk_somerawkey"},
        )
    assert resp.status_code == 200
    assert resp.json()["valid"] is True
    assert resp.json()["account_id"] == 7


def test_platform_admin_verify_invalid_key():
    """48. POST /admin/corporate/api-keys/verify — 200 invalid key returns valid=False."""
    client = _get_test_client()

    with patch("app.api.v1.corporate_api_keys.verify_api_key", new=AsyncMock(return_value=None)):
        resp = client.post(
            f"{_BASE}/admin/corporate/api-keys/verify",
            json={"raw_key": "rsk_badkey"},
        )
    assert resp.status_code == 200
    assert resp.json()["valid"] is False


# ---------------------------------------------------------------------------
# Extra tests
# ---------------------------------------------------------------------------


def test_known_scopes_content():
    expected = {"rides:read", "invoices:read", "analytics:read", "employees:read", "exports:read", "reports:read"}
    assert expected == KNOWN_SCOPES


def test_generate_api_key_format():
    key = _generate_api_key()
    assert key.startswith("rsk_")
    # rsk_ (4) + 64 hex chars = 68 total
    assert len(key) == 68
