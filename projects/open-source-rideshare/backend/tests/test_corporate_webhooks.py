"""Tests for the Corporate Webhooks feature.

Service tests (async, mocked DB):
  1.  create_webhook — success
  2.  create_webhook — unknown event type → 422
  3.  create_webhook — multiple unknown event types → 422
  4.  create_webhook — empty event_types list passes validation
  5.  get_webhook — success
  6.  get_webhook — wrong account → 404
  7.  list_webhooks — active_only=True returns only active
  8.  list_webhooks — active_only=False returns all
  9.  update_webhook — url updated
  10. update_webhook — event_types updated
  11. update_webhook — description updated
  12. update_webhook — is_active updated
  13. update_webhook — unknown event type → 422
  14. update_webhook — not found → 404
  15. deactivate_webhook — success: is_active=False
  16. deactivate_webhook — already inactive → 409
  17. deactivate_webhook — not found → 404
  18. delete_webhook — success
  19. delete_webhook — not found → 404
  20. list_deliveries — success, most recent first
  21. list_deliveries — empty
  22. list_deliveries — wrong account → 404
  23. deliver_event — mock httpx: success, HMAC header sent, delivery record created
  24. deliver_event — mock httpx: HTTP 500, records failure, does not raise
  25. deliver_event — mock httpx: network error, records failure, does not raise
  26. deliver_event — last_delivery_at and last_delivery_success updated on webhook

Schema tests (sync):
  27. WebhookCreate — valid
  28. WebhookCreate — multiple event types
  29. WebhookUpdate — all fields optional
  30. WebhookResponse — from_attributes
  31. WebhookDeliveryResponse — from_attributes

API layer tests (service patched):
  32. GET  /corporate/accounts/me/webhooks — 200
  33. POST /corporate/accounts/me/webhooks — 201
  34. GET  /corporate/accounts/me/webhooks/{id} — 200
  35. PUT  /corporate/accounts/me/webhooks/{id} — 200
  36. DELETE /corporate/accounts/me/webhooks/{id}/deactivate — 200
  37. DELETE /corporate/accounts/me/webhooks/{id} — 204
  38. GET  /corporate/accounts/me/webhooks/{id}/deliveries — 200
  39. POST /corporate/accounts/me/webhooks/{id}/test — 202
  40. GET  /admin/corporate/accounts/{account_id}/webhooks — 200

Extras:
  41. deliver_event — webhook not found → 404
  42. KNOWN_EVENT_TYPES contains all 10 expected event types
  43. _sign_payload produces deterministic sha256= prefixed result
  44. create_webhook — duplicate URL for same account is allowed (no constraint)
  45. list_webhooks — returns empty list when no webhooks configured
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate_webhook import CorporateWebhook, CorporateWebhookDelivery
from app.schemas.corporate_webhook import (
    WebhookCreate,
    WebhookDeliveryListResponse,
    WebhookDeliveryResponse,
    WebhookListResponse,
    WebhookResponse,
    WebhookUpdate,
)
from app.services.corporate_webhook import (
    KNOWN_EVENT_TYPES,
    _sign_payload,
    create_webhook,
    deactivate_webhook,
    delete_webhook,
    deliver_event,
    get_webhook,
    list_deliveries,
    list_webhooks,
    update_webhook,
)

# ---------------------------------------------------------------------------
# Constants / fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 1
ADMIN_ID = 10
WEBHOOK_ID = uuid.uuid4()
DELIVERY_ID = uuid.uuid4()
TEST_URL = "https://example.com/webhooks/rideshare"
TEST_SECRET = "a" * 64  # 32 bytes hex


def _make_webhook(
    webhook_id: uuid.UUID = WEBHOOK_ID,
    account_id: int = ACCOUNT_ID,
    url: str = TEST_URL,
    secret: str = TEST_SECRET,
    event_types: list = None,
    is_active: bool = True,
    description: str = None,
    created_by_id: int = ADMIN_ID,
    last_delivery_at=None,
    last_delivery_success=None,
) -> CorporateWebhook:
    w = MagicMock(spec=CorporateWebhook)
    w.id = webhook_id
    w.account_id = account_id
    w.url = url
    w.secret = secret
    w.event_types = event_types or ["ride.completed"]
    w.is_active = is_active
    w.description = description
    w.created_by_id = created_by_id
    w.created_at = NOW
    w.updated_at = NOW
    w.last_delivery_at = last_delivery_at
    w.last_delivery_success = last_delivery_success
    return w


def _make_delivery(
    delivery_id: uuid.UUID = DELIVERY_ID,
    webhook_id: uuid.UUID = WEBHOOK_ID,
    event_type: str = "ride.completed",
    payload: dict = None,
    status_code: int = 200,
    success: bool = True,
    attempted_at=None,
) -> CorporateWebhookDelivery:
    d = MagicMock(spec=CorporateWebhookDelivery)
    d.id = delivery_id
    d.webhook_id = webhook_id
    d.event_type = event_type
    d.payload = payload or {"event": event_type}
    d.status_code = status_code
    d.response_body = "OK"
    d.success = success
    d.attempt_number = 1
    d.attempted_at = attempted_at or NOW
    return d


# ---------------------------------------------------------------------------
# Service tests — create_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_webhook_success():
    """1. create_webhook — success."""
    db = AsyncMock()
    db.flush = AsyncMock()

    captured = {}

    def _capture(obj):
        captured["webhook"] = obj
        obj.id = WEBHOOK_ID
        obj.created_at = NOW
        obj.updated_at = NOW

    db.add = MagicMock(side_effect=_capture)

    result = await create_webhook(
        db,
        account_id=ACCOUNT_ID,
        url=TEST_URL,
        event_types=["ride.completed", "invoice.paid"],
        description="Test webhook",
        created_by_id=ADMIN_ID,
    )

    assert result.account_id == ACCOUNT_ID
    assert result.url == TEST_URL
    assert result.is_active is True
    assert len(result.secret) == 64  # 32 bytes hex
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_create_webhook_unknown_event_type():
    """2. create_webhook — unknown event type → 422."""
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await create_webhook(
            db,
            account_id=ACCOUNT_ID,
            url=TEST_URL,
            event_types=["ride.completed", "bogus.event"],
        )
    assert exc.value.status_code == 422
    assert "bogus.event" in exc.value.detail


@pytest.mark.asyncio
async def test_create_webhook_multiple_unknown_event_types():
    """3. create_webhook — multiple unknown event types → 422."""
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await create_webhook(
            db,
            account_id=ACCOUNT_ID,
            url=TEST_URL,
            event_types=["unknown.a", "unknown.b"],
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_create_webhook_empty_event_types_passes_validation():
    """4. create_webhook — empty event_types list passes service validation."""
    db = AsyncMock()
    db.flush = AsyncMock()

    def _capture(obj):
        obj.id = WEBHOOK_ID
        obj.created_at = NOW
        obj.updated_at = NOW

    db.add = MagicMock(side_effect=_capture)

    # Empty list has no unknown types, so it passes validation
    result = await create_webhook(
        db,
        account_id=ACCOUNT_ID,
        url=TEST_URL,
        event_types=[],
    )
    assert result.event_types == []


# ---------------------------------------------------------------------------
# Service tests — get_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_webhook_success():
    """5. get_webhook — success."""
    db = AsyncMock()
    webhook = _make_webhook()
    r = MagicMock()
    r.scalar_one_or_none.return_value = webhook
    db.execute = AsyncMock(return_value=r)

    result = await get_webhook(db, ACCOUNT_ID, WEBHOOK_ID)
    assert result.id == WEBHOOK_ID
    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_get_webhook_wrong_account():
    """6. get_webhook — wrong account → 404."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await get_webhook(db, 999, WEBHOOK_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Service tests — list_webhooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_webhooks_active_only():
    """7. list_webhooks — active_only=True returns only active."""
    db = AsyncMock()
    webhook = _make_webhook(is_active=True)
    r = MagicMock()
    r.scalars.return_value.all.return_value = [webhook]
    db.execute = AsyncMock(return_value=r)

    result = await list_webhooks(db, ACCOUNT_ID, active_only=True)
    assert len(result) == 1
    assert result[0].is_active is True


@pytest.mark.asyncio
async def test_list_webhooks_all():
    """8. list_webhooks — active_only=False returns all."""
    db = AsyncMock()
    active = _make_webhook(is_active=True)
    inactive = _make_webhook(is_active=False)
    r = MagicMock()
    r.scalars.return_value.all.return_value = [active, inactive]
    db.execute = AsyncMock(return_value=r)

    result = await list_webhooks(db, ACCOUNT_ID, active_only=False)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Service tests — update_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_webhook_url():
    """9. update_webhook — url updated."""
    db = AsyncMock()
    webhook = _make_webhook()
    r = MagicMock()
    r.scalar_one_or_none.return_value = webhook
    db.execute = AsyncMock(return_value=r)
    db.flush = AsyncMock()

    new_url = "https://new.example.com/hook"
    result = await update_webhook(db, ACCOUNT_ID, WEBHOOK_ID, url=new_url)

    assert webhook.url == new_url


@pytest.mark.asyncio
async def test_update_webhook_event_types():
    """10. update_webhook — event_types updated."""
    db = AsyncMock()
    webhook = _make_webhook()
    r = MagicMock()
    r.scalar_one_or_none.return_value = webhook
    db.execute = AsyncMock(return_value=r)
    db.flush = AsyncMock()

    new_events = ["invoice.paid", "employee.joined"]
    await update_webhook(db, ACCOUNT_ID, WEBHOOK_ID, event_types=new_events)

    assert webhook.event_types == new_events


@pytest.mark.asyncio
async def test_update_webhook_description():
    """11. update_webhook — description updated."""
    db = AsyncMock()
    webhook = _make_webhook()
    r = MagicMock()
    r.scalar_one_or_none.return_value = webhook
    db.execute = AsyncMock(return_value=r)
    db.flush = AsyncMock()

    await update_webhook(db, ACCOUNT_ID, WEBHOOK_ID, description="New label")

    assert webhook.description == "New label"


@pytest.mark.asyncio
async def test_update_webhook_is_active():
    """12. update_webhook — is_active updated."""
    db = AsyncMock()
    webhook = _make_webhook(is_active=True)
    r = MagicMock()
    r.scalar_one_or_none.return_value = webhook
    db.execute = AsyncMock(return_value=r)
    db.flush = AsyncMock()

    await update_webhook(db, ACCOUNT_ID, WEBHOOK_ID, is_active=False)

    assert webhook.is_active is False


@pytest.mark.asyncio
async def test_update_webhook_unknown_event_type():
    """13. update_webhook — unknown event type → 422."""
    db = AsyncMock()
    webhook = _make_webhook()
    r = MagicMock()
    r.scalar_one_or_none.return_value = webhook
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await update_webhook(db, ACCOUNT_ID, WEBHOOK_ID, event_types=["bad.event"])
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_update_webhook_not_found():
    """14. update_webhook — not found → 404."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await update_webhook(db, ACCOUNT_ID, WEBHOOK_ID, url="https://x.com/hook")
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Service tests — deactivate_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_webhook_success():
    """15. deactivate_webhook — success: is_active=False."""
    db = AsyncMock()
    webhook = _make_webhook(is_active=True)
    r = MagicMock()
    r.scalar_one_or_none.return_value = webhook
    db.execute = AsyncMock(return_value=r)
    db.flush = AsyncMock()

    result = await deactivate_webhook(db, ACCOUNT_ID, WEBHOOK_ID)

    assert webhook.is_active is False
    assert result.id == WEBHOOK_ID


@pytest.mark.asyncio
async def test_deactivate_webhook_already_inactive():
    """16. deactivate_webhook — already inactive → 409."""
    db = AsyncMock()
    webhook = _make_webhook(is_active=False)
    r = MagicMock()
    r.scalar_one_or_none.return_value = webhook
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await deactivate_webhook(db, ACCOUNT_ID, WEBHOOK_ID)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_deactivate_webhook_not_found():
    """17. deactivate_webhook — not found → 404."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await deactivate_webhook(db, ACCOUNT_ID, WEBHOOK_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Service tests — delete_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_webhook_success():
    """18. delete_webhook — success."""
    db = AsyncMock()
    webhook = _make_webhook()
    r = MagicMock()
    r.scalar_one_or_none.return_value = webhook
    db.execute = AsyncMock(return_value=r)
    db.delete = AsyncMock()
    db.flush = AsyncMock()

    await delete_webhook(db, ACCOUNT_ID, WEBHOOK_ID)

    db.delete.assert_called_once_with(webhook)
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_delete_webhook_not_found():
    """19. delete_webhook — not found → 404."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await delete_webhook(db, ACCOUNT_ID, WEBHOOK_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Service tests — list_deliveries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_deliveries_success():
    """20. list_deliveries — success, most recent first."""
    db = AsyncMock()
    webhook = _make_webhook()
    delivery = _make_delivery()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = webhook  # get_webhook check
        else:
            r.scalars.return_value.all.return_value = [delivery]
        return r

    db.execute = fake_execute

    result = await list_deliveries(db, ACCOUNT_ID, WEBHOOK_ID)
    assert len(result) == 1
    assert result[0].event_type == "ride.completed"


@pytest.mark.asyncio
async def test_list_deliveries_empty():
    """21. list_deliveries — empty."""
    db = AsyncMock()
    webhook = _make_webhook()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = webhook
        else:
            r.scalars.return_value.all.return_value = []
        return r

    db.execute = fake_execute

    result = await list_deliveries(db, ACCOUNT_ID, WEBHOOK_ID)
    assert result == []


@pytest.mark.asyncio
async def test_list_deliveries_wrong_account():
    """22. list_deliveries — wrong account → 404."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await list_deliveries(db, 999, WEBHOOK_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Service tests — deliver_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_event_success_hmac_header_sent():
    """23. deliver_event — mock httpx: success, HMAC header sent, delivery record created."""
    db = AsyncMock()
    webhook = _make_webhook(secret=TEST_SECRET)
    call_count = 0
    captured_delivery = {}

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        r.scalar_one_or_none.return_value = webhook
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    def _capture(obj):
        captured_delivery["delivery"] = obj
        obj.id = DELIVERY_ID
        obj.attempted_at = NOW

    db.add = MagicMock(side_effect=_capture)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "OK"

    captured_request = {}

    class FakeClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, content, headers):
            captured_request["headers"] = headers
            captured_request["content"] = content
            return mock_response

    payload = {
        "event": "ride.completed",
        "account_id": str(ACCOUNT_ID),
        "timestamp": NOW.isoformat(),
        "data": {"ride_id": "abc123"},
    }

    with patch("app.services.corporate_webhook.httpx.Client", FakeClient):
        result = await deliver_event(db, WEBHOOK_ID, "ride.completed", payload)

    assert result.success is True
    assert result.status_code == 200

    # Verify HMAC header
    body = json.dumps(payload, default=str).encode("utf-8")
    expected_sig = _sign_payload(TEST_SECRET, body)
    assert captured_request["headers"]["X-Rideshare-Signature"] == expected_sig
    assert captured_request["headers"]["X-Rideshare-Signature"].startswith("sha256=")


@pytest.mark.asyncio
async def test_deliver_event_http_500_records_failure_no_raise():
    """24. deliver_event — mock httpx: HTTP 500, records failure, does not raise."""
    db = AsyncMock()
    webhook = _make_webhook(secret=TEST_SECRET)
    r = MagicMock()
    r.scalar_one_or_none.return_value = webhook
    db.execute = AsyncMock(return_value=r)
    db.flush = AsyncMock()

    def _capture(obj):
        obj.id = DELIVERY_ID
        obj.attempted_at = NOW

    db.add = MagicMock(side_effect=_capture)

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    class FakeClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, content, headers):
            return mock_response

    payload = {"event": "invoice.paid", "account_id": "1", "timestamp": NOW.isoformat(), "data": {}}

    with patch("app.services.corporate_webhook.httpx.Client", FakeClient):
        result = await deliver_event(db, WEBHOOK_ID, "invoice.paid", payload)

    assert result.success is False
    assert result.status_code == 500


@pytest.mark.asyncio
async def test_deliver_event_network_error_no_raise():
    """25. deliver_event — mock httpx: network error, records failure, does not raise."""
    db = AsyncMock()
    webhook = _make_webhook(secret=TEST_SECRET)
    r = MagicMock()
    r.scalar_one_or_none.return_value = webhook
    db.execute = AsyncMock(return_value=r)
    db.flush = AsyncMock()

    def _capture(obj):
        obj.id = DELIVERY_ID
        obj.attempted_at = NOW

    db.add = MagicMock(side_effect=_capture)

    class FakeClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, content, headers):
            raise ConnectionError("Connection refused")

    payload = {"event": "ping", "account_id": "1", "timestamp": NOW.isoformat(), "data": {}}

    with patch("app.services.corporate_webhook.httpx.Client", FakeClient):
        result = await deliver_event(db, WEBHOOK_ID, "ping", payload)

    assert result.success is False
    assert result.status_code is None


@pytest.mark.asyncio
async def test_deliver_event_updates_webhook_last_delivery():
    """26. deliver_event — last_delivery_at and last_delivery_success updated on webhook."""
    db = AsyncMock()
    webhook = _make_webhook(secret=TEST_SECRET, last_delivery_at=None, last_delivery_success=None)
    r = MagicMock()
    r.scalar_one_or_none.return_value = webhook
    db.execute = AsyncMock(return_value=r)
    db.flush = AsyncMock()

    def _capture(obj):
        obj.id = DELIVERY_ID
        obj.attempted_at = NOW

    db.add = MagicMock(side_effect=_capture)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "OK"

    class FakeClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, content, headers):
            return mock_response

    payload = {"event": "employee.joined", "account_id": "1", "timestamp": NOW.isoformat(), "data": {}}

    with patch("app.services.corporate_webhook.httpx.Client", FakeClient):
        await deliver_event(db, WEBHOOK_ID, "employee.joined", payload)

    assert webhook.last_delivery_at is not None
    assert webhook.last_delivery_success is True


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_webhook_create_valid():
    """27. WebhookCreate — valid."""
    w = WebhookCreate(url="https://example.com/hook", event_types=["ride.completed"])
    assert w.url == "https://example.com/hook"
    assert w.event_types == ["ride.completed"]
    assert w.description is None


def test_webhook_create_multiple_event_types():
    """28. WebhookCreate — multiple event types."""
    w = WebhookCreate(
        url="https://example.com/hook",
        event_types=["ride.completed", "invoice.paid", "employee.joined"],
        description="My webhook",
    )
    assert len(w.event_types) == 3
    assert w.description == "My webhook"


def test_webhook_update_all_optional():
    """29. WebhookUpdate — all fields optional."""
    w = WebhookUpdate()
    assert w.url is None
    assert w.event_types is None
    assert w.description is None
    assert w.is_active is None


def test_webhook_response_from_attributes():
    """30. WebhookResponse — from_attributes."""
    mock_wh = MagicMock()
    mock_wh.id = WEBHOOK_ID
    mock_wh.account_id = ACCOUNT_ID
    mock_wh.url = TEST_URL
    mock_wh.event_types = ["ride.completed"]
    mock_wh.is_active = True
    mock_wh.description = None
    mock_wh.created_by_id = ADMIN_ID
    mock_wh.created_at = NOW
    mock_wh.updated_at = NOW
    mock_wh.last_delivery_at = None
    mock_wh.last_delivery_success = None

    resp = WebhookResponse.model_validate(mock_wh)
    assert resp.id == WEBHOOK_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.url == TEST_URL


def test_webhook_delivery_response_from_attributes():
    """31. WebhookDeliveryResponse — from_attributes."""
    mock_del = MagicMock()
    mock_del.id = DELIVERY_ID
    mock_del.webhook_id = WEBHOOK_ID
    mock_del.event_type = "ride.completed"
    mock_del.payload = {"event": "ride.completed"}
    mock_del.attempted_at = NOW
    mock_del.status_code = 200
    mock_del.response_body = "OK"
    mock_del.success = True
    mock_del.attempt_number = 1

    resp = WebhookDeliveryResponse.model_validate(mock_del)
    assert resp.id == DELIVERY_ID
    assert resp.success is True


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------


def _make_webhook_response(**kwargs) -> WebhookResponse:
    defaults = dict(
        id=WEBHOOK_ID,
        account_id=ACCOUNT_ID,
        url=TEST_URL,
        event_types=["ride.completed"],
        is_active=True,
        description=None,
        created_by_id=ADMIN_ID,
        created_at=NOW,
        updated_at=NOW,
        last_delivery_at=None,
        last_delivery_success=None,
    )
    defaults.update(kwargs)
    return WebhookResponse(**defaults)


def _make_list_response(webhooks=None) -> WebhookListResponse:
    if webhooks is None:
        webhooks = [_make_webhook_response()]
    return WebhookListResponse(
        account_id=ACCOUNT_ID,
        total=len(webhooks),
        webhooks=webhooks,
    )


def _make_delivery_response(**kwargs) -> WebhookDeliveryResponse:
    defaults = dict(
        id=DELIVERY_ID,
        webhook_id=WEBHOOK_ID,
        event_type="ride.completed",
        payload={"event": "ride.completed"},
        attempted_at=NOW,
        status_code=200,
        response_body="OK",
        success=True,
        attempt_number=1,
    )
    defaults.update(kwargs)
    return WebhookDeliveryResponse(**defaults)


def _make_delivery_list_response(deliveries=None) -> WebhookDeliveryListResponse:
    if deliveries is None:
        deliveries = [_make_delivery_response()]
    return WebhookDeliveryListResponse(
        webhook_id=WEBHOOK_ID,
        total=len(deliveries),
        deliveries=deliveries,
    )


def _get_test_client():
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = ADMIN_ID
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


def test_api_list_webhooks():
    """32. GET /corporate/accounts/me/webhooks — 200."""
    client = _get_test_client()
    resp_data = _make_list_response()

    with patch("app.api.v1.corporate_webhooks._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch("app.api.v1.corporate_webhooks.list_webhooks", new=AsyncMock(return_value=[_make_webhook()])):
        resp = client.get("/api/v1/corporate/accounts/me/webhooks")

    assert resp.status_code == 200
    data = resp.json()
    assert data["account_id"] == ACCOUNT_ID
    assert data["total"] == 1


def test_api_create_webhook():
    """33. POST /corporate/accounts/me/webhooks — 201."""
    client = _get_test_client()
    wh = _make_webhook()

    with patch("app.api.v1.corporate_webhooks._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch("app.api.v1.corporate_webhooks.create_webhook", new=AsyncMock(return_value=wh)), \
         patch("app.api.v1.corporate_webhooks.get_db"):
        resp = client.post(
            "/api/v1/corporate/accounts/me/webhooks",
            json={"url": TEST_URL, "event_types": ["ride.completed"]},
        )

    assert resp.status_code == 201
    assert resp.json()["url"] == TEST_URL


def test_api_get_webhook():
    """34. GET /corporate/accounts/me/webhooks/{id} — 200."""
    client = _get_test_client()
    wh = _make_webhook()

    with patch("app.api.v1.corporate_webhooks._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch("app.api.v1.corporate_webhooks.get_webhook", new=AsyncMock(return_value=wh)):
        resp = client.get(f"/api/v1/corporate/accounts/me/webhooks/{WEBHOOK_ID}")

    assert resp.status_code == 200
    assert resp.json()["id"] == str(WEBHOOK_ID)


def test_api_update_webhook():
    """35. PUT /corporate/accounts/me/webhooks/{id} — 200."""
    client = _get_test_client()
    wh = _make_webhook(url="https://new.example.com/hook")

    with patch("app.api.v1.corporate_webhooks._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch("app.api.v1.corporate_webhooks.update_webhook", new=AsyncMock(return_value=wh)):
        resp = client.put(
            f"/api/v1/corporate/accounts/me/webhooks/{WEBHOOK_ID}",
            json={"url": "https://new.example.com/hook"},
        )

    assert resp.status_code == 200
    assert resp.json()["url"] == "https://new.example.com/hook"


def test_api_deactivate_webhook():
    """36. DELETE /corporate/accounts/me/webhooks/{id}/deactivate — 200."""
    client = _get_test_client()
    wh = _make_webhook(is_active=False)

    with patch("app.api.v1.corporate_webhooks._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch("app.api.v1.corporate_webhooks.deactivate_webhook", new=AsyncMock(return_value=wh)):
        resp = client.delete(f"/api/v1/corporate/accounts/me/webhooks/{WEBHOOK_ID}/deactivate")

    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_api_delete_webhook():
    """37. DELETE /corporate/accounts/me/webhooks/{id} — 204."""
    client = _get_test_client()

    with patch("app.api.v1.corporate_webhooks._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch("app.api.v1.corporate_webhooks.delete_webhook", new=AsyncMock(return_value=None)):
        resp = client.delete(f"/api/v1/corporate/accounts/me/webhooks/{WEBHOOK_ID}")

    assert resp.status_code == 204


def test_api_get_deliveries():
    """38. GET /corporate/accounts/me/webhooks/{id}/deliveries — 200."""
    client = _get_test_client()
    delivery = _make_delivery()

    with patch("app.api.v1.corporate_webhooks._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch("app.api.v1.corporate_webhooks.list_deliveries", new=AsyncMock(return_value=[delivery])):
        resp = client.get(f"/api/v1/corporate/accounts/me/webhooks/{WEBHOOK_ID}/deliveries")

    assert resp.status_code == 200
    data = resp.json()
    assert data["webhook_id"] == str(WEBHOOK_ID)
    assert data["total"] == 1


def test_api_test_webhook():
    """39. POST /corporate/accounts/me/webhooks/{id}/test — 202."""
    client = _get_test_client()
    wh = _make_webhook()
    delivery = _make_delivery(event_type="ping")

    with patch("app.api.v1.corporate_webhooks._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch("app.api.v1.corporate_webhooks.get_webhook", new=AsyncMock(return_value=wh)), \
         patch("app.api.v1.corporate_webhooks.deliver_event", new=AsyncMock(return_value=delivery)):
        resp = client.post(f"/api/v1/corporate/accounts/me/webhooks/{WEBHOOK_ID}/test")

    assert resp.status_code == 202
    data = resp.json()
    assert "delivery_id" in data
    assert data["success"] is True


def test_api_platform_admin_list_webhooks():
    """40. GET /admin/corporate/accounts/{account_id}/webhooks — 200."""
    client = _get_test_client()
    wh = _make_webhook()

    with patch("app.api.v1.corporate_webhooks.list_webhooks", new=AsyncMock(return_value=[wh])):
        resp = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/webhooks")

    assert resp.status_code == 200
    data = resp.json()
    assert data["account_id"] == ACCOUNT_ID
    assert data["total"] == 1


# ---------------------------------------------------------------------------
# Extra tests (41–45)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_event_webhook_not_found():
    """41. deliver_event — webhook not found → 404."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await deliver_event(db, WEBHOOK_ID, "ping", {})
    assert exc.value.status_code == 404


def test_known_event_types_contains_all_expected():
    """42. KNOWN_EVENT_TYPES contains all 10 expected event types."""
    expected = {
        "ride.completed",
        "invoice.finalized",
        "invoice.paid",
        "expense_report.submitted",
        "expense_report.approved",
        "expense_report.rejected",
        "budget_alert.triggered",
        "ride_approval.approved",
        "ride_approval.rejected",
        "employee.joined",
    }
    assert expected == KNOWN_EVENT_TYPES


def test_sign_payload_deterministic_sha256_prefix():
    """43. _sign_payload produces deterministic sha256= prefixed result."""
    secret = "testsecret"
    body = b'{"event":"ping"}'

    sig1 = _sign_payload(secret, body)
    sig2 = _sign_payload(secret, body)

    assert sig1 == sig2
    assert sig1.startswith("sha256=")

    # Verify manually
    expected = hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    assert sig1 == f"sha256={expected}"


@pytest.mark.asyncio
async def test_create_webhook_duplicate_url_same_account_allowed():
    """44. create_webhook — duplicate URL for same account is allowed (no unique constraint)."""
    db = AsyncMock()
    db.flush = AsyncMock()
    created = []

    def _capture(obj):
        obj.id = uuid.uuid4()
        obj.created_at = NOW
        obj.updated_at = NOW
        created.append(obj)

    db.add = MagicMock(side_effect=_capture)

    await create_webhook(db, ACCOUNT_ID, TEST_URL, ["ride.completed"])
    await create_webhook(db, ACCOUNT_ID, TEST_URL, ["invoice.paid"])

    assert len(created) == 2
    # Both share the same URL — that's fine
    assert created[0].url == created[1].url


@pytest.mark.asyncio
async def test_list_webhooks_empty():
    """45. list_webhooks — returns empty list when no webhooks configured."""
    db = AsyncMock()
    r = MagicMock()
    r.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=r)

    result = await list_webhooks(db, ACCOUNT_ID)
    assert result == []
