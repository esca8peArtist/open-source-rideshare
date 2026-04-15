"""Tests for the Corporate SSO Configuration feature.

Service tests (async, mocked DB):
  1.  create_sso_config — success
  2.  create_sso_config — 409 when config already exists
  3.  get_sso_config — returns config when found
  4.  get_sso_config — returns None when not configured
  5.  update_sso_config — success (partial update)
  6.  update_sso_config — 404 when not found
  7.  delete_sso_config — success
  8.  delete_sso_config — 404 when not found
  9.  set_sso_enforcement — enable when active (success)
  10. set_sso_enforcement — disable (success, any status)
  11. set_sso_enforcement — 422 when enabling but status != active
  12. set_sso_enforcement — 404 when not found
  13. activate_sso_config — success
  14. activate_sso_config — 404 when not found
  15. disable_sso_config — sets status=disabled and enforce_sso=False
  16. disable_sso_config — 404 when not found
  17. record_sso_test — success, updates last_tested_at and last_tested_by_id
  18. record_sso_test — 404 when not found
  19. list_sso_configs — returns all without filters
  20. list_sso_configs — filters by status
  21. list_sso_configs — filters by provider
  22. list_sso_configs — returns empty list

Schema tests (sync):
  23. CorporateSSOConfigCreate — valid with provider only
  24. CorporateSSOConfigCreate — saml fields included
  25. CorporateSSOConfigCreate — oidc fields included
  26. CorporateSSOConfigUpdate — all None is valid (partial update)
  27. CorporateSSOConfigResponse — from_attributes; secret hash not in response
  28. SSOEnforcementUpdate — enforce=True
  29. SSOEnforcementUpdate — enforce=False

API layer tests (services patched):
  30. GET  /corporate/{account_id}/sso — 200
  31. GET  /corporate/{account_id}/sso — 404 when not configured
  32. POST /corporate/{account_id}/sso — 201
  33. PATCH /corporate/{account_id}/sso — 200
  34. DELETE /corporate/{account_id}/sso — 204
  35. POST /corporate/{account_id}/sso/enforce — 200
  36. POST /corporate/{account_id}/sso/activate — 200
  37. POST /corporate/{account_id}/sso/disable — 200
  38. POST /corporate/{account_id}/sso/test — 200
  39. GET  /platform-admin/corporate/sso/configs — 200
  40. GET  /platform-admin/corporate/sso/accounts/{account_id} — 200
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate_sso_config import (
    CorporateSSOConfig,
    SSOProvider,
    SSOStatus,
)
from app.schemas.corporate_sso_config import (
    CorporateSSOConfigCreate,
    CorporateSSOConfigResponse,
    CorporateSSOConfigUpdate,
    SSOEnforcementUpdate,
)
from app.services.corporate_sso_config import (
    activate_sso_config,
    create_sso_config,
    delete_sso_config,
    disable_sso_config,
    get_sso_config,
    list_sso_configs,
    record_sso_test,
    set_sso_enforcement,
    update_sso_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
_ACCOUNT_ID = 7
_USER_ID = 10


def _make_config(
    id: int = 1,
    account_id: int = _ACCOUNT_ID,
    provider: SSOProvider = SSOProvider.okta,
    status: SSOStatus = SSOStatus.pending,
    enforce_sso: bool = False,
    saml_metadata_url: str | None = None,
    saml_entity_id: str | None = None,
    saml_sso_url: str | None = None,
    saml_slo_url: str | None = None,
    saml_certificate: str | None = None,
    oidc_discovery_url: str | None = None,
    oidc_client_id: str | None = None,
    oidc_client_secret_hash: str | None = None,
    oidc_scopes: str | None = "openid email profile",
    attribute_mapping: dict | None = None,
    allowed_domains: list | None = None,
    last_tested_at: datetime | None = None,
    last_tested_by_id: int | None = None,
    created_by_id: int = _USER_ID,
) -> CorporateSSOConfig:
    cfg = CorporateSSOConfig(
        id=id,
        account_id=account_id,
        provider=provider,
        status=status,
        enforce_sso=enforce_sso,
        saml_metadata_url=saml_metadata_url,
        saml_entity_id=saml_entity_id,
        saml_sso_url=saml_sso_url,
        saml_slo_url=saml_slo_url,
        saml_certificate=saml_certificate,
        oidc_discovery_url=oidc_discovery_url,
        oidc_client_id=oidc_client_id,
        oidc_client_secret_hash=oidc_client_secret_hash,
        oidc_scopes=oidc_scopes,
        attribute_mapping=attribute_mapping,
        allowed_domains=allowed_domains,
        last_tested_at=last_tested_at,
        last_tested_by_id=last_tested_by_id,
        created_at=_NOW,
        updated_at=_NOW,
        created_by_id=created_by_id,
    )
    return cfg


def _mock_db_with_config(cfg: CorporateSSOConfig | None) -> AsyncMock:
    """Build a mock DB that returns *cfg* from scalar_one_or_none."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = cfg
    db.execute.return_value = result
    return db


def _mock_db_with_configs(configs: list[CorporateSSOConfig]) -> AsyncMock:
    """Build a mock DB that returns *configs* from scalars().all()."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = configs
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# Service: create_sso_config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_sso_config_success():
    """create_sso_config creates and returns a new config."""
    db = _mock_db_with_config(None)  # no existing config

    cfg = await create_sso_config(
        db,
        account_id=_ACCOUNT_ID,
        provider=SSOProvider.okta,
        created_by_id=_USER_ID,
    )

    assert cfg.account_id == _ACCOUNT_ID
    assert cfg.provider == SSOProvider.okta
    assert cfg.status == SSOStatus.pending
    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_create_sso_config_409_when_already_exists():
    """create_sso_config raises 409 when a config already exists."""
    existing = _make_config()
    db = _mock_db_with_config(existing)

    with pytest.raises(HTTPException) as exc_info:
        await create_sso_config(
            db,
            account_id=_ACCOUNT_ID,
            provider=SSOProvider.saml,
            created_by_id=_USER_ID,
        )
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service: get_sso_config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_sso_config_returns_config():
    """get_sso_config returns the config when it exists."""
    cfg = _make_config()
    db = _mock_db_with_config(cfg)
    result = await get_sso_config(db, account_id=_ACCOUNT_ID)
    assert result is cfg


@pytest.mark.asyncio
async def test_get_sso_config_returns_none_when_not_configured():
    """get_sso_config returns None when no config exists."""
    db = _mock_db_with_config(None)
    result = await get_sso_config(db, account_id=_ACCOUNT_ID)
    assert result is None


# ---------------------------------------------------------------------------
# Service: update_sso_config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_sso_config_success():
    """update_sso_config applies the supplied fields."""
    cfg = _make_config(oidc_client_id=None)
    db = _mock_db_with_config(cfg)

    updated = await update_sso_config(
        db, account_id=_ACCOUNT_ID, oidc_client_id="new-client-id"
    )
    assert updated.oidc_client_id == "new-client-id"
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_update_sso_config_404_when_not_found():
    """update_sso_config raises 404 when no config exists."""
    db = _mock_db_with_config(None)
    with pytest.raises(HTTPException) as exc_info:
        await update_sso_config(db, account_id=_ACCOUNT_ID, oidc_client_id="x")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: delete_sso_config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_sso_config_success():
    """delete_sso_config calls db.delete on the config."""
    cfg = _make_config()
    db = _mock_db_with_config(cfg)
    await delete_sso_config(db, account_id=_ACCOUNT_ID)
    db.delete.assert_called_once_with(cfg)
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_delete_sso_config_404_when_not_found():
    """delete_sso_config raises 404 when no config exists."""
    db = _mock_db_with_config(None)
    with pytest.raises(HTTPException) as exc_info:
        await delete_sso_config(db, account_id=_ACCOUNT_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: set_sso_enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_sso_enforcement_enable_when_active():
    """set_sso_enforcement enables enforcement when config is active."""
    cfg = _make_config(status=SSOStatus.active, enforce_sso=False)
    db = _mock_db_with_config(cfg)
    updated = await set_sso_enforcement(db, account_id=_ACCOUNT_ID, enforce=True)
    assert updated.enforce_sso is True


@pytest.mark.asyncio
async def test_set_sso_enforcement_disable_any_status():
    """set_sso_enforcement can disable enforcement regardless of status."""
    cfg = _make_config(status=SSOStatus.pending, enforce_sso=True)
    db = _mock_db_with_config(cfg)
    updated = await set_sso_enforcement(db, account_id=_ACCOUNT_ID, enforce=False)
    assert updated.enforce_sso is False


@pytest.mark.asyncio
async def test_set_sso_enforcement_422_when_not_active():
    """set_sso_enforcement raises 422 when enabling enforcement on non-active config."""
    cfg = _make_config(status=SSOStatus.pending, enforce_sso=False)
    db = _mock_db_with_config(cfg)
    with pytest.raises(HTTPException) as exc_info:
        await set_sso_enforcement(db, account_id=_ACCOUNT_ID, enforce=True)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_set_sso_enforcement_404_when_not_found():
    """set_sso_enforcement raises 404 when no config exists."""
    db = _mock_db_with_config(None)
    with pytest.raises(HTTPException) as exc_info:
        await set_sso_enforcement(db, account_id=_ACCOUNT_ID, enforce=True)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: activate_sso_config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activate_sso_config_success():
    """activate_sso_config sets status to active."""
    cfg = _make_config(status=SSOStatus.pending)
    db = _mock_db_with_config(cfg)
    updated = await activate_sso_config(db, account_id=_ACCOUNT_ID)
    assert updated.status == SSOStatus.active


@pytest.mark.asyncio
async def test_activate_sso_config_404_when_not_found():
    """activate_sso_config raises 404 when no config exists."""
    db = _mock_db_with_config(None)
    with pytest.raises(HTTPException) as exc_info:
        await activate_sso_config(db, account_id=_ACCOUNT_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: disable_sso_config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disable_sso_config_sets_disabled_and_clears_enforcement():
    """disable_sso_config sets status=disabled and enforce_sso=False."""
    cfg = _make_config(status=SSOStatus.active, enforce_sso=True)
    db = _mock_db_with_config(cfg)
    updated = await disable_sso_config(db, account_id=_ACCOUNT_ID)
    assert updated.status == SSOStatus.disabled
    assert updated.enforce_sso is False


@pytest.mark.asyncio
async def test_disable_sso_config_404_when_not_found():
    """disable_sso_config raises 404 when no config exists."""
    db = _mock_db_with_config(None)
    with pytest.raises(HTTPException) as exc_info:
        await disable_sso_config(db, account_id=_ACCOUNT_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: record_sso_test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_sso_test_success():
    """record_sso_test updates last_tested_at and last_tested_by_id."""
    cfg = _make_config(last_tested_at=None, last_tested_by_id=None)
    db = _mock_db_with_config(cfg)
    updated = await record_sso_test(db, account_id=_ACCOUNT_ID, tested_by_id=42)
    assert updated.last_tested_at is not None
    assert updated.last_tested_by_id == 42


@pytest.mark.asyncio
async def test_record_sso_test_404_when_not_found():
    """record_sso_test raises 404 when no config exists."""
    db = _mock_db_with_config(None)
    with pytest.raises(HTTPException) as exc_info:
        await record_sso_test(db, account_id=_ACCOUNT_ID, tested_by_id=42)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: list_sso_configs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sso_configs_returns_all():
    """list_sso_configs returns all configs without filters."""
    configs = [_make_config(id=1), _make_config(id=2, account_id=8)]
    db = _mock_db_with_configs(configs)
    result = await list_sso_configs(db)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_sso_configs_filters_by_status():
    """list_sso_configs applies status filter."""
    active_cfg = _make_config(status=SSOStatus.active)
    db = _mock_db_with_configs([active_cfg])
    result = await list_sso_configs(db, status_filter=SSOStatus.active)
    assert all(c.status == SSOStatus.active for c in result)


@pytest.mark.asyncio
async def test_list_sso_configs_filters_by_provider():
    """list_sso_configs applies provider filter."""
    google_cfg = _make_config(provider=SSOProvider.google)
    db = _mock_db_with_configs([google_cfg])
    result = await list_sso_configs(db, provider_filter=SSOProvider.google)
    assert all(c.provider == SSOProvider.google for c in result)


@pytest.mark.asyncio
async def test_list_sso_configs_returns_empty():
    """list_sso_configs returns an empty list when none exist."""
    db = _mock_db_with_configs([])
    result = await list_sso_configs(db)
    assert result == []


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_create_schema_provider_only():
    """CorporateSSOConfigCreate accepts provider as the only required field."""
    req = CorporateSSOConfigCreate(provider=SSOProvider.okta)
    assert req.provider == SSOProvider.okta
    assert req.saml_metadata_url is None
    assert req.oidc_client_id is None


def test_create_schema_saml_fields():
    """CorporateSSOConfigCreate accepts SAML-specific fields."""
    req = CorporateSSOConfigCreate(
        provider=SSOProvider.saml,
        saml_metadata_url="https://idp.example.com/metadata",
        saml_entity_id="https://sp.example.com",
        saml_sso_url="https://idp.example.com/sso",
        saml_slo_url="https://idp.example.com/slo",
        saml_certificate="-----BEGIN CERTIFICATE-----...",
    )
    assert req.saml_metadata_url == "https://idp.example.com/metadata"
    assert req.saml_certificate is not None


def test_create_schema_oidc_fields():
    """CorporateSSOConfigCreate accepts OIDC-specific fields."""
    req = CorporateSSOConfigCreate(
        provider=SSOProvider.oidc,
        oidc_discovery_url="https://idp.example.com/.well-known/openid-configuration",
        oidc_client_id="client-123",
        oidc_client_secret_hash="hashed-secret",
        oidc_scopes="openid email profile groups",
    )
    assert req.oidc_discovery_url is not None
    assert req.oidc_client_id == "client-123"


def test_update_schema_all_none_valid():
    """CorporateSSOConfigUpdate accepts all None (partial update intent)."""
    req = CorporateSSOConfigUpdate()
    assert req.saml_metadata_url is None
    assert req.oidc_client_id is None


def test_response_schema_excludes_secret_hash():
    """CorporateSSOConfigResponse does not expose oidc_client_secret_hash."""
    cfg = _make_config(oidc_client_secret_hash="should-not-appear")
    resp = CorporateSSOConfigResponse.model_validate(cfg)
    resp_dict = resp.model_dump()
    assert "oidc_client_secret_hash" not in resp_dict
    assert resp.account_id == _ACCOUNT_ID


def test_enforcement_update_schema_true():
    """SSOEnforcementUpdate accepts enforce=True."""
    req = SSOEnforcementUpdate(enforce=True)
    assert req.enforce is True


def test_enforcement_update_schema_false():
    """SSOEnforcementUpdate accepts enforce=False."""
    req = SSOEnforcementUpdate(enforce=False)
    assert req.enforce is False


# ---------------------------------------------------------------------------
# API layer (services patched)
# ---------------------------------------------------------------------------

_DUMMY_CFG = _make_config()
_DUMMY_CFG_DICT = {
    "id": _DUMMY_CFG.id,
    "account_id": _DUMMY_CFG.account_id,
    "provider": _DUMMY_CFG.provider,
    "status": _DUMMY_CFG.status,
    "enforce_sso": _DUMMY_CFG.enforce_sso,
    "saml_metadata_url": None,
    "saml_entity_id": None,
    "saml_sso_url": None,
    "saml_slo_url": None,
    "saml_certificate": None,
    "oidc_discovery_url": None,
    "oidc_client_id": None,
    "oidc_scopes": "openid email profile",
    "attribute_mapping": None,
    "allowed_domains": None,
    "last_tested_at": None,
    "last_tested_by_id": None,
    "created_at": _NOW,
    "updated_at": _NOW,
    "created_by_id": _USER_ID,
}

_BASE = f"/api/v1/corporate/{_ACCOUNT_ID}/sso"
_ADMIN_BASE = "/api/v1/platform-admin/corporate/sso"


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
    "app.api.v1.corporate_sso_config.get_sso_config",
    new_callable=AsyncMock,
    return_value=_DUMMY_CFG,
)
def test_api_get_sso_config_200(mock_get):
    client = _make_app_client()
    resp = client.get(_BASE)
    assert resp.status_code == 200
    assert resp.json()["account_id"] == _ACCOUNT_ID


@patch(
    "app.api.v1.corporate_sso_config.get_sso_config",
    new_callable=AsyncMock,
    return_value=None,
)
def test_api_get_sso_config_404_when_not_configured(mock_get):
    client = _make_app_client()
    resp = client.get(_BASE)
    assert resp.status_code == 404


@patch(
    "app.api.v1.corporate_sso_config.create_sso_config",
    new_callable=AsyncMock,
    return_value=_DUMMY_CFG,
)
def test_api_create_sso_config_201(mock_create):
    client = _make_app_client()
    resp = client.post(_BASE, json={"provider": "okta"})
    assert resp.status_code == 201
    assert resp.json()["provider"] == "okta"


@patch(
    "app.api.v1.corporate_sso_config.update_sso_config",
    new_callable=AsyncMock,
    return_value=_DUMMY_CFG,
)
def test_api_update_sso_config_200(mock_update):
    client = _make_app_client()
    resp = client.patch(_BASE, json={"oidc_client_id": "new-id"})
    assert resp.status_code == 200


@patch(
    "app.api.v1.corporate_sso_config.delete_sso_config",
    new_callable=AsyncMock,
    return_value=None,
)
def test_api_delete_sso_config_204(mock_delete):
    client = _make_app_client()
    resp = client.delete(_BASE)
    assert resp.status_code == 204


@patch(
    "app.api.v1.corporate_sso_config.set_sso_enforcement",
    new_callable=AsyncMock,
    return_value=_make_config(enforce_sso=True, status=SSOStatus.active),
)
def test_api_enforce_sso_200(mock_enforce):
    client = _make_app_client()
    resp = client.post(f"{_BASE}/enforce", json={"enforce": True})
    assert resp.status_code == 200
    assert resp.json()["enforce_sso"] is True


@patch(
    "app.api.v1.corporate_sso_config.activate_sso_config",
    new_callable=AsyncMock,
    return_value=_make_config(status=SSOStatus.active),
)
def test_api_activate_sso_config_200(mock_activate):
    client = _make_app_client()
    resp = client.post(f"{_BASE}/activate")
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


@patch(
    "app.api.v1.corporate_sso_config.disable_sso_config",
    new_callable=AsyncMock,
    return_value=_make_config(status=SSOStatus.disabled, enforce_sso=False),
)
def test_api_disable_sso_config_200(mock_disable):
    client = _make_app_client()
    resp = client.post(f"{_BASE}/disable")
    assert resp.status_code == 200
    assert resp.json()["status"] == "disabled"
    assert resp.json()["enforce_sso"] is False


@patch(
    "app.api.v1.corporate_sso_config.record_sso_test",
    new_callable=AsyncMock,
    return_value=_make_config(
        last_tested_at=_NOW, last_tested_by_id=_USER_ID
    ),
)
def test_api_record_sso_test_200(mock_test):
    client = _make_app_client()
    resp = client.post(f"{_BASE}/test")
    assert resp.status_code == 200
    assert resp.json()["last_tested_by_id"] == _USER_ID


@patch(
    "app.api.v1.corporate_sso_config.list_sso_configs",
    new_callable=AsyncMock,
    return_value=[_DUMMY_CFG],
)
def test_api_platform_admin_list_sso_configs_200(mock_list):
    client = _make_app_client()
    resp = client.get(f"{_ADMIN_BASE}/configs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1


@patch(
    "app.api.v1.corporate_sso_config.get_sso_config",
    new_callable=AsyncMock,
    return_value=_DUMMY_CFG,
)
def test_api_platform_admin_get_sso_config_200(mock_get):
    client = _make_app_client()
    resp = client.get(f"{_ADMIN_BASE}/accounts/{_ACCOUNT_ID}")
    assert resp.status_code == 200
    assert resp.json()["account_id"] == _ACCOUNT_ID
