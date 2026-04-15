"""Tests for the Corporate Notification Settings feature.

Service tests (async, mocked DB):
  1.  get_notification_config — returns existing row
  2.  get_notification_config — creates default row when missing
  3.  get_all_notification_configs — returns all 12 event types (all pre-exist)
  4.  get_all_notification_configs — creates defaults for missing event types
  5.  get_all_notification_configs — returns exactly 12 rows
  6.  update_notification_config — updates fields on existing row
  7.  update_notification_config — 404 when row does not exist
  8.  bulk_update_notification_configs — updates multiple rows
  9.  bulk_update_notification_configs — 422 on unknown event_type
  10. reset_notification_configs — resets all rows to defaults
  11. reset_notification_configs — creates rows for missing event types
  12. get_recipients_for_event — returns empty lists when disabled
  13. get_recipients_for_event — returns billing emails when flag set
  14. get_recipients_for_event — returns account emails when flag set
  15. get_recipients_for_event — returns webhook urls when flag set
  16. get_recipients_for_event — returns additional_emails when enabled
  17. get_recipients_for_event — skips routing when config disabled

Schema tests (sync):
  18. CorporateNotificationConfigUpdate — all None is valid
  19. CorporateNotificationConfigUpdate — all fields supplied
  20. BulkNotificationConfigUpdate — valid with one entry
  21. BulkNotificationConfigUpdate — rejects empty list
  22. CorporateNotificationConfigResponse — from_attributes
  23. NotificationRecipientsResponse — constructed correctly

API layer tests (services patched):
  24. GET  /corporate/{account_id}/notification-settings — 200 with 12 entries
  25. GET  /corporate/{account_id}/notification-settings/{event_type} — 200
  26. PUT  /corporate/{account_id}/notification-settings/{event_type} — 200
  27. POST /corporate/{account_id}/notification-settings/bulk-update — 200
  28. POST /corporate/{account_id}/notification-settings/reset — 200
  29. GET  /corporate/{account_id}/notification-settings/{event_type}/preview-recipients — 200
  30. GET  /platform-admin/notification-settings/{account_id} — 200 (admin)
  31. GET  /platform-admin/notification-settings/{account_id} — 403 (non-admin)
  32. Auth: unauthenticated requests return 403
  33. NotificationEventType enum has exactly 12 values
  34. Default config has correct default values
  35. get_all_notification_configs covers all NotificationEventType values
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate_notification_settings import (
    CorporateNotificationConfig,
    NotificationEventType,
)
from app.schemas.corporate_notification_settings import (
    BulkNotificationConfigUpdate,
    CorporateNotificationConfigResponse,
    CorporateNotificationConfigUpdate,
    NotificationRecipientsResponse,
)
from app.services.corporate_notification_settings import (
    bulk_update_notification_configs,
    get_all_notification_configs,
    get_notification_config,
    get_recipients_for_event,
    reset_notification_configs,
    update_notification_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
_ACCOUNT_ID = 42
_ALL_EVENT_TYPES = list(NotificationEventType)


def _make_config(
    id: int = 1,
    account_id: int = _ACCOUNT_ID,
    event_type: NotificationEventType = NotificationEventType.invoice_generated,
    enabled: bool = True,
    notify_billing_contacts: bool = False,
    notify_account_contacts: bool = True,
    notify_via_webhooks: bool = True,
    additional_emails: list | None = None,
) -> CorporateNotificationConfig:
    cfg = CorporateNotificationConfig(
        id=id,
        account_id=account_id,
        event_type=event_type,
        enabled=enabled,
        notify_billing_contacts=notify_billing_contacts,
        notify_account_contacts=notify_account_contacts,
        notify_via_webhooks=notify_via_webhooks,
        additional_emails=additional_emails if additional_emails is not None else [],
        created_at=_NOW,
        updated_at=_NOW,
    )
    return cfg


def _make_all_configs(account_id: int = _ACCOUNT_ID) -> list[CorporateNotificationConfig]:
    return [
        _make_config(id=i + 1, account_id=account_id, event_type=et)
        for i, et in enumerate(_ALL_EVENT_TYPES)
    ]


def _mock_db_with_config(cfg: CorporateNotificationConfig | None) -> AsyncMock:
    """Build a mock DB that returns *cfg* from scalar_one_or_none."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = cfg
    result.scalars.return_value.all.return_value = [cfg] if cfg else []
    db.execute.return_value = result
    return db


def _mock_db_with_configs(configs: list[CorporateNotificationConfig]) -> AsyncMock:
    """Build a mock DB that returns *configs* from scalars().all()."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = configs
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# Service: get_notification_config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_notification_config_returns_existing():
    """get_notification_config returns the row when it already exists."""
    cfg = _make_config()
    db = _mock_db_with_config(cfg)

    result = await get_notification_config(
        db, account_id=_ACCOUNT_ID, event_type=NotificationEventType.invoice_generated
    )

    assert result is cfg
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_get_notification_config_creates_default_when_missing():
    """get_notification_config creates a default row when none exists."""
    db = _mock_db_with_config(None)

    result = await get_notification_config(
        db, account_id=_ACCOUNT_ID, event_type=NotificationEventType.invoice_paid
    )

    assert result.account_id == _ACCOUNT_ID
    assert result.event_type == NotificationEventType.invoice_paid
    assert result.enabled is True
    assert result.notify_billing_contacts is False
    assert result.notify_account_contacts is True
    assert result.notify_via_webhooks is True
    assert result.additional_emails == []
    db.add.assert_called_once()
    db.flush.assert_called_once()


# ---------------------------------------------------------------------------
# Service: get_all_notification_configs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_all_notification_configs_returns_all_12_when_exist():
    """get_all_notification_configs returns all 12 when they all already exist."""
    configs = _make_all_configs()
    db = _mock_db_with_configs(configs)

    result = await get_all_notification_configs(db, account_id=_ACCOUNT_ID)

    assert len(result) == 12


@pytest.mark.asyncio
async def test_get_all_notification_configs_creates_defaults_for_missing():
    """get_all_notification_configs creates default rows for missing event types."""
    # Only one config pre-exists
    existing = [_make_config(event_type=NotificationEventType.member_joined)]
    db = _mock_db_with_configs(existing)

    result = await get_all_notification_configs(db, account_id=_ACCOUNT_ID)

    assert len(result) == 12
    # db.add called for the 11 missing event types
    assert db.add.call_count == 11


@pytest.mark.asyncio
async def test_get_all_notification_configs_always_returns_12():
    """get_all_notification_configs returns exactly 12 rows regardless of DB state."""
    db = _mock_db_with_configs([])  # nothing pre-exists

    result = await get_all_notification_configs(db, account_id=_ACCOUNT_ID)

    assert len(result) == 12
    assert db.add.call_count == 12


# ---------------------------------------------------------------------------
# Service: update_notification_config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_notification_config_success():
    """update_notification_config applies supplied fields."""
    cfg = _make_config(enabled=True)
    db = _mock_db_with_config(cfg)

    updated = await update_notification_config(
        db,
        account_id=_ACCOUNT_ID,
        event_type=NotificationEventType.invoice_generated,
        enabled=False,
        notify_billing_contacts=True,
    )

    assert updated.enabled is False
    assert updated.notify_billing_contacts is True
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_update_notification_config_404_when_missing():
    """update_notification_config raises 404 when the row does not exist."""
    db = _mock_db_with_config(None)

    with pytest.raises(HTTPException) as exc_info:
        await update_notification_config(
            db,
            account_id=_ACCOUNT_ID,
            event_type=NotificationEventType.invoice_generated,
            enabled=False,
        )

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: bulk_update_notification_configs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_update_notification_configs_success():
    """bulk_update_notification_configs updates multiple configs."""
    cfg1 = _make_config(id=1, event_type=NotificationEventType.member_joined)
    cfg2 = _make_config(id=2, event_type=NotificationEventType.invoice_paid)

    call_count = 0

    async def fake_get(db, account_id, event_type):
        nonlocal call_count
        call_count += 1
        return cfg1 if event_type == NotificationEventType.member_joined else cfg2

    with patch(
        "app.services.corporate_notification_settings.get_notification_config",
        side_effect=fake_get,
    ):
        db = AsyncMock()
        updates = [
            {"event_type": "member_joined", "enabled": False},
            {"event_type": "invoice_paid", "notify_billing_contacts": True},
        ]
        results = await bulk_update_notification_configs(
            db, account_id=_ACCOUNT_ID, updates=updates
        )

    assert len(results) == 2
    assert results[0].enabled is False
    assert results[1].notify_billing_contacts is True


@pytest.mark.asyncio
async def test_bulk_update_notification_configs_422_on_unknown_event_type():
    """bulk_update_notification_configs raises 422 for unknown event type."""
    db = AsyncMock()
    updates = [{"event_type": "nonexistent_event", "enabled": False}]

    with pytest.raises(HTTPException) as exc_info:
        await bulk_update_notification_configs(db, account_id=_ACCOUNT_ID, updates=updates)

    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# Service: reset_notification_configs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_notification_configs_resets_all_rows():
    """reset_notification_configs resets existing rows to defaults."""
    configs = [
        _make_config(
            id=i + 1,
            event_type=et,
            enabled=False,
            notify_billing_contacts=True,
            notify_account_contacts=False,
            notify_via_webhooks=False,
            additional_emails=["extra@example.com"],
        )
        for i, et in enumerate(_ALL_EVENT_TYPES)
    ]
    db = _mock_db_with_configs(configs)

    result = await reset_notification_configs(db, account_id=_ACCOUNT_ID)

    assert len(result) == 12
    for cfg in result:
        assert cfg.enabled is True
        assert cfg.notify_billing_contacts is False
        assert cfg.notify_account_contacts is True
        assert cfg.notify_via_webhooks is True
        assert cfg.additional_emails == []


@pytest.mark.asyncio
async def test_reset_notification_configs_creates_missing_rows():
    """reset_notification_configs creates rows for missing event types."""
    db = _mock_db_with_configs([])  # nothing pre-exists

    result = await reset_notification_configs(db, account_id=_ACCOUNT_ID)

    assert len(result) == 12
    assert db.add.call_count == 12


# ---------------------------------------------------------------------------
# Service: get_recipients_for_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_recipients_returns_empty_when_all_flags_off():
    """get_recipients_for_event returns empty lists when all routing flags are False."""
    cfg = _make_config(
        enabled=True,
        notify_billing_contacts=False,
        notify_account_contacts=False,
        notify_via_webhooks=False,
        additional_emails=[],
    )

    with patch(
        "app.services.corporate_notification_settings.get_notification_config",
        new=AsyncMock(return_value=cfg),
    ):
        db = AsyncMock()
        result = await get_recipients_for_event(
            db, account_id=_ACCOUNT_ID, event_type=NotificationEventType.invoice_generated
        )

    assert result["billing_contact_emails"] == []
    assert result["account_contact_emails"] == []
    assert result["webhook_urls"] == []
    assert result["additional_emails"] == []


@pytest.mark.asyncio
async def test_get_recipients_returns_billing_emails():
    """get_recipients_for_event includes billing contact emails when flag is True."""
    cfg = _make_config(
        enabled=True,
        notify_billing_contacts=True,
        notify_account_contacts=False,
        notify_via_webhooks=False,
    )

    billing_contact = MagicMock()
    billing_contact.email = "billing@corp.example"

    bc_result = MagicMock()
    bc_result.scalars.return_value.all.return_value = [billing_contact]

    with patch(
        "app.services.corporate_notification_settings.get_notification_config",
        new=AsyncMock(return_value=cfg),
    ):
        db = AsyncMock()
        db.execute.return_value = bc_result
        result = await get_recipients_for_event(
            db, account_id=_ACCOUNT_ID, event_type=NotificationEventType.invoice_generated
        )

    assert "billing@corp.example" in result["billing_contact_emails"]


@pytest.mark.asyncio
async def test_get_recipients_returns_account_emails():
    """get_recipients_for_event includes account contact emails when flag is True."""
    cfg = _make_config(
        enabled=True,
        notify_billing_contacts=False,
        notify_account_contacts=True,
        notify_via_webhooks=False,
    )

    ac = MagicMock()
    ac.email = "ops@corp.example"

    ac_result = MagicMock()
    ac_result.scalars.return_value.all.return_value = [ac]

    with patch(
        "app.services.corporate_notification_settings.get_notification_config",
        new=AsyncMock(return_value=cfg),
    ):
        db = AsyncMock()
        db.execute.return_value = ac_result
        result = await get_recipients_for_event(
            db, account_id=_ACCOUNT_ID, event_type=NotificationEventType.member_joined
        )

    assert "ops@corp.example" in result["account_contact_emails"]


@pytest.mark.asyncio
async def test_get_recipients_returns_webhook_urls():
    """get_recipients_for_event includes webhook URLs when flag is True."""
    cfg = _make_config(
        enabled=True,
        notify_billing_contacts=False,
        notify_account_contacts=False,
        notify_via_webhooks=True,
    )

    wh = MagicMock()
    wh.url = "https://hooks.corp.example/events"

    wh_result = MagicMock()
    wh_result.scalars.return_value.all.return_value = [wh]

    with patch(
        "app.services.corporate_notification_settings.get_notification_config",
        new=AsyncMock(return_value=cfg),
    ):
        db = AsyncMock()
        db.execute.return_value = wh_result
        result = await get_recipients_for_event(
            db, account_id=_ACCOUNT_ID, event_type=NotificationEventType.invoice_paid
        )

    assert "https://hooks.corp.example/events" in result["webhook_urls"]


@pytest.mark.asyncio
async def test_get_recipients_returns_additional_emails():
    """get_recipients_for_event includes additional_emails from the config."""
    cfg = _make_config(
        enabled=True,
        notify_billing_contacts=False,
        notify_account_contacts=False,
        notify_via_webhooks=False,
        additional_emails=["extra1@example.com", "extra2@example.com"],
    )

    with patch(
        "app.services.corporate_notification_settings.get_notification_config",
        new=AsyncMock(return_value=cfg),
    ):
        db = AsyncMock()
        result = await get_recipients_for_event(
            db, account_id=_ACCOUNT_ID, event_type=NotificationEventType.data_export_ready
        )

    assert result["additional_emails"] == ["extra1@example.com", "extra2@example.com"]


@pytest.mark.asyncio
async def test_get_recipients_skips_routing_when_disabled():
    """get_recipients_for_event returns all empty lists when config.enabled is False."""
    cfg = _make_config(
        enabled=False,
        notify_billing_contacts=True,
        notify_account_contacts=True,
        notify_via_webhooks=True,
        additional_emails=["x@example.com"],
    )

    with patch(
        "app.services.corporate_notification_settings.get_notification_config",
        new=AsyncMock(return_value=cfg),
    ):
        db = AsyncMock()
        result = await get_recipients_for_event(
            db, account_id=_ACCOUNT_ID, event_type=NotificationEventType.sso_login_failed
        )

    assert result["billing_contact_emails"] == []
    assert result["account_contact_emails"] == []
    assert result["webhook_urls"] == []
    assert result["additional_emails"] == []


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_notification_config_update_all_none_is_valid():
    """CorporateNotificationConfigUpdate accepts all-None (partial update)."""
    data = CorporateNotificationConfigUpdate()
    assert data.enabled is None
    assert data.notify_billing_contacts is None


def test_notification_config_update_all_fields():
    """CorporateNotificationConfigUpdate accepts all fields supplied."""
    data = CorporateNotificationConfigUpdate(
        enabled=False,
        notify_billing_contacts=True,
        notify_account_contacts=False,
        notify_via_webhooks=False,
        additional_emails=["a@b.com"],
    )
    assert data.enabled is False
    assert data.additional_emails == ["a@b.com"]


def test_bulk_notification_config_update_valid():
    """BulkNotificationConfigUpdate accepts a valid single entry."""
    data = BulkNotificationConfigUpdate(
        updates=[{"event_type": "invoice_generated", "enabled": False}]
    )
    assert len(data.updates) == 1
    assert data.updates[0].event_type == NotificationEventType.invoice_generated


def test_bulk_notification_config_update_rejects_empty_list():
    """BulkNotificationConfigUpdate rejects an empty updates list."""
    with pytest.raises(ValidationError):
        BulkNotificationConfigUpdate(updates=[])


def test_notification_config_response_from_attributes():
    """CorporateNotificationConfigResponse validates from ORM object."""
    cfg = _make_config()
    resp = CorporateNotificationConfigResponse.model_validate(cfg)
    assert resp.account_id == _ACCOUNT_ID
    assert resp.event_type == NotificationEventType.invoice_generated
    assert resp.enabled is True
    assert resp.additional_emails == []


def test_notification_recipients_response_constructed():
    """NotificationRecipientsResponse constructs correctly."""
    resp = NotificationRecipientsResponse(
        event_type=NotificationEventType.invoice_generated,
        billing_contact_emails=["b@example.com"],
        account_contact_emails=["a@example.com"],
        webhook_urls=["https://hook.example.com"],
        additional_emails=["x@example.com"],
    )
    assert resp.event_type == NotificationEventType.invoice_generated
    assert len(resp.billing_contact_emails) == 1


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

_DUMMY_CFG = _make_config()
_BASE = f"/api/v1/corporate/{_ACCOUNT_ID}/notification-settings"
_ADMIN_BASE = f"/api/v1/platform-admin/notification-settings"


def _make_app_client(is_admin: bool = False):
    """Build a TestClient with auth + DB deps overridden."""
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = 99
    role = MagicMock()
    role.value = "admin" if is_admin else "rider"
    mock_user.role = role

    async def override_user():
        return mock_user

    async def override_admin():
        if not is_admin:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Admin access required")
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
    "app.api.v1.corporate_notification_settings.get_all_notification_configs",
    new_callable=AsyncMock,
    return_value=_make_all_configs(),
)
def test_api_list_notification_configs_200(mock_get_all):
    """GET /corporate/{account_id}/notification-settings returns 200 with 12 entries."""
    client = _make_app_client()
    response = client.get(_BASE)
    assert response.status_code == 200
    assert len(response.json()) == 12


@patch(
    "app.api.v1.corporate_notification_settings.get_notification_config",
    new_callable=AsyncMock,
    return_value=_DUMMY_CFG,
)
def test_api_get_single_notification_config_200(mock_get):
    """GET /corporate/{account_id}/notification-settings/{event_type} returns 200."""
    client = _make_app_client()
    response = client.get(f"{_BASE}/invoice_generated")
    assert response.status_code == 200
    assert response.json()["event_type"] == "invoice_generated"


@patch(
    "app.api.v1.corporate_notification_settings.update_notification_config",
    new_callable=AsyncMock,
    return_value=_make_config(enabled=False),
)
@patch(
    "app.api.v1.corporate_notification_settings.get_notification_config",
    new_callable=AsyncMock,
    return_value=_DUMMY_CFG,
)
def test_api_update_notification_config_200(mock_get, mock_update):
    """PUT /corporate/{account_id}/notification-settings/{event_type} returns 200."""
    client = _make_app_client()
    response = client.put(
        f"{_BASE}/invoice_generated",
        json={"enabled": False},
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False


@patch(
    "app.api.v1.corporate_notification_settings.bulk_update_notification_configs",
    new_callable=AsyncMock,
    return_value=[_DUMMY_CFG],
)
def test_api_bulk_update_200(mock_bulk):
    """POST /corporate/{account_id}/notification-settings/bulk-update returns 200."""
    client = _make_app_client()
    response = client.post(
        f"{_BASE}/bulk-update",
        json={"updates": [{"event_type": "invoice_generated", "enabled": False}]},
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@patch(
    "app.api.v1.corporate_notification_settings.reset_notification_configs",
    new_callable=AsyncMock,
    return_value=_make_all_configs(),
)
def test_api_reset_200(mock_reset):
    """POST /corporate/{account_id}/notification-settings/reset returns 200."""
    client = _make_app_client()
    response = client.post(f"{_BASE}/reset")
    assert response.status_code == 200
    assert len(response.json()) == 12


@patch(
    "app.api.v1.corporate_notification_settings.get_recipients_for_event",
    new_callable=AsyncMock,
    return_value={
        "billing_contact_emails": [],
        "account_contact_emails": ["ops@corp.example"],
        "webhook_urls": [],
        "additional_emails": [],
    },
)
def test_api_preview_recipients_200(mock_recipients):
    """GET /corporate/{account_id}/notification-settings/{event_type}/preview-recipients returns 200."""
    client = _make_app_client()
    response = client.get(f"{_BASE}/invoice_generated/preview-recipients")
    assert response.status_code == 200
    data = response.json()
    assert data["event_type"] == "invoice_generated"
    assert "ops@corp.example" in data["account_contact_emails"]


@patch(
    "app.api.v1.corporate_notification_settings.get_all_notification_configs",
    new_callable=AsyncMock,
    return_value=_make_all_configs(),
)
def test_api_platform_admin_list_200(mock_get_all):
    """GET /platform-admin/notification-settings/{account_id} returns 200 for admin."""
    client = _make_app_client(is_admin=True)
    response = client.get(f"{_ADMIN_BASE}/{_ACCOUNT_ID}")
    assert response.status_code == 200
    assert len(response.json()) == 12


def test_api_platform_admin_list_403_for_non_admin():
    """GET /platform-admin/notification-settings/{account_id} returns 403 for non-admin."""
    client = _make_app_client(is_admin=False)
    response = client.get(f"{_ADMIN_BASE}/{_ACCOUNT_ID}")
    assert response.status_code == 403


def test_api_unauthenticated_returns_401_or_403():
    """Unauthenticated requests to notification settings endpoints are rejected."""
    from app.main import app
    client = TestClient(app, raise_server_exceptions=True)
    response = client.get(_BASE)
    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Model / enum coverage tests
# ---------------------------------------------------------------------------


def test_notification_event_type_has_exactly_12_values():
    """NotificationEventType enum has exactly 12 values."""
    assert len(NotificationEventType) == 12


def test_default_config_has_correct_defaults():
    """The _default_config helper produces a config with correct default values."""
    from app.services.corporate_notification_settings import _default_config

    cfg = _default_config(account_id=1, event_type=NotificationEventType.member_joined)
    assert cfg.enabled is True
    assert cfg.notify_billing_contacts is False
    assert cfg.notify_account_contacts is True
    assert cfg.notify_via_webhooks is True
    assert cfg.additional_emails == []


def test_get_all_covers_all_event_types():
    """_ALL_EVENT_TYPES covers every value in NotificationEventType."""
    from app.services.corporate_notification_settings import _ALL_EVENT_TYPES

    assert set(_ALL_EVENT_TYPES) == set(NotificationEventType)
    assert len(_ALL_EVENT_TYPES) == 12
