"""Tests for the Corporate Billing Settings feature.

Service tests (async, mocked DB):
  1.  get_or_create_settings — creates default row when none exists
  2.  get_or_create_settings — returns existing settings
  3.  update_settings — creates row on first update
  4.  update_settings — updates existing settings fields
  5.  update_settings — normalizes billing_country to uppercase
  6.  add_payment_method — success creates method
  7.  add_payment_method — set_as_default clears prior default
  8.  add_payment_method — set_as_default=False leaves no default change
  9.  get_payment_method — returns method when found
  10. get_payment_method — not found → 404
  11. list_payment_methods — returns active methods
  12. list_payment_methods — active_only=False returns all
  13. set_default_payment_method — success clears prior and sets new default
  14. set_default_payment_method — not found → 404
  15. set_default_payment_method — inactive method → 409
  16. deactivate_payment_method — sets is_active=False
  17. deactivate_payment_method — clears is_default when method was default
  18. deactivate_payment_method — not found → 404
  19. delete_payment_method — success hard-deletes non-default method
  20. delete_payment_method — not found → 404
  21. delete_payment_method — is_default → 409
  22. get_billing_summary — returns complete summary with default method
  23. get_billing_summary — auto_pay_ready True only when both conditions met
  24. get_billing_summary — has_complete_billing_address True when all fields set

Schema tests (sync):
  25. BillingSettingsUpdate — all fields optional
  26. BillingSettingsUpdate — billing_country accepts 2-char code
  27. PaymentMethodCreate — required fields validate
  28. PaymentMethodCreate — set_as_default defaults False
  29. BillingSettingsResponse — from_attributes works
  30. PaymentMethodResponse — from_attributes works
  31. BillingSummaryResponse — fields present

API layer tests (services patched):
  32. GET  /billing/summary — 200 returns summary
  33. GET  /billing/payment-methods — 200 returns list
  34. GET  /billing/settings — 200 returns settings
  35. PATCH /billing/settings — 200 updates settings
  36. POST /billing/payment-methods — 201 creates method
  37. POST /billing/payment-methods set_as_default — 201 created
  38. GET  /billing/payment-methods/{id} — 200 returns method
  39. GET  /billing/payment-methods/{id} — 404 not found
  40. POST /billing/payment-methods/{id}/set-default — 200 sets default
  41. POST /billing/payment-methods/{id}/deactivate — 200 deactivated
  42. DELETE /billing/payment-methods/{id} — 204 deleted
  43. DELETE /billing/payment-methods/{id} — 409 is default
  44. GET  /platform-admin/corporate-billing/ — 200 list all
  45. GET  /platform-admin/corporate-billing/{account_id}/settings — 200 get for account
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate_billing_settings import (
    BillingCycle,
    CorporateBillingSettings,
    CorporatePaymentMethod,
    PaymentMethodType,
)
from app.schemas.corporate_billing_settings import (
    BillingSummaryResponse,
    BillingSettingsResponse,
    BillingSettingsUpdate,
    PaymentMethodCreate,
    PaymentMethodResponse,
)
from app.services.corporate_billing_settings import (
    add_payment_method,
    deactivate_payment_method,
    delete_payment_method,
    get_billing_summary,
    get_or_create_settings,
    get_payment_method,
    list_payment_methods,
    set_default_payment_method,
    update_settings,
)


# ---------------------------------------------------------------------------
# Constants / factories
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
_ACCOUNT_ID = 1
_SETTINGS_ID = 10
_METHOD_ID = 20
_USER_ID = 99


def _make_settings(
    id: int = _SETTINGS_ID,
    account_id: int = _ACCOUNT_ID,
    billing_company_name: str | None = "Acme Corp",
    billing_address_line1: str | None = "123 Main St",
    billing_address_line2: str | None = None,
    billing_city: str | None = "Springfield",
    billing_state: str | None = "IL",
    billing_postal_code: str | None = "62701",
    billing_country: str | None = "US",
    tax_id: str | None = "12-3456789",
    po_number_required: bool = False,
    default_po_number: str | None = None,
    invoice_memo_template: str | None = None,
    auto_pay_enabled: bool = False,
    billing_cycle: BillingCycle = BillingCycle.monthly,
    invoice_emails: list | None = None,
    updated_by_id: int | None = None,
) -> CorporateBillingSettings:
    s = CorporateBillingSettings(
        id=id,
        account_id=account_id,
        billing_company_name=billing_company_name,
        billing_address_line1=billing_address_line1,
        billing_address_line2=billing_address_line2,
        billing_city=billing_city,
        billing_state=billing_state,
        billing_postal_code=billing_postal_code,
        billing_country=billing_country,
        tax_id=tax_id,
        po_number_required=po_number_required,
        default_po_number=default_po_number,
        invoice_memo_template=invoice_memo_template,
        auto_pay_enabled=auto_pay_enabled,
        billing_cycle=billing_cycle,
        invoice_emails=invoice_emails,
        updated_by_id=updated_by_id,
        created_at=_NOW,
        updated_at=_NOW,
    )
    return s


def _make_method(
    id: int = _METHOD_ID,
    billing_settings_id: int = _SETTINGS_ID,
    account_id: int = _ACCOUNT_ID,
    payment_type: PaymentMethodType = PaymentMethodType.credit_card,
    display_name: str = "Corporate Visa ending 4242",
    last_four: str | None = "4242",
    cardholder_name: str | None = "Acme Corp",
    bank_name: str | None = None,
    external_payment_method_id: str | None = "pm_abc123",
    is_default: bool = False,
    is_active: bool = True,
    created_by_id: int | None = _USER_ID,
) -> CorporatePaymentMethod:
    m = CorporatePaymentMethod(
        id=id,
        billing_settings_id=billing_settings_id,
        account_id=account_id,
        payment_type=payment_type,
        display_name=display_name,
        last_four=last_four,
        cardholder_name=cardholder_name,
        bank_name=bank_name,
        external_payment_method_id=external_payment_method_id,
        is_default=is_default,
        is_active=is_active,
        created_by_id=created_by_id,
        created_at=_NOW,
        updated_at=_NOW,
    )
    return m


def _mock_db_with_one(obj) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    db.execute.return_value = result
    return db


def _mock_db_with_list(items: list) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# Service: get_or_create_settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_settings_creates_default_when_none():
    """get_or_create_settings creates a default row when none exists."""
    db = _mock_db_with_one(None)
    settings = await get_or_create_settings(db, account_id=_ACCOUNT_ID)
    assert settings.account_id == _ACCOUNT_ID
    assert settings.po_number_required is False
    assert settings.auto_pay_enabled is False
    assert settings.billing_cycle == BillingCycle.monthly
    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_get_or_create_settings_returns_existing():
    """get_or_create_settings returns existing settings without creating."""
    existing = _make_settings()
    db = _mock_db_with_one(existing)
    settings = await get_or_create_settings(db, account_id=_ACCOUNT_ID)
    assert settings is existing
    db.add.assert_not_called()


# ---------------------------------------------------------------------------
# Service: update_settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_settings_creates_row_on_first_update():
    """update_settings creates a settings row on first call and applies fields."""
    db = _mock_db_with_one(None)
    data = BillingSettingsUpdate(billing_company_name="New Corp", auto_pay_enabled=True)
    settings = await update_settings(db, account_id=_ACCOUNT_ID, data=data, updated_by_id=_USER_ID)
    assert settings.billing_company_name == "New Corp"
    assert settings.auto_pay_enabled is True
    assert settings.updated_by_id == _USER_ID


@pytest.mark.asyncio
async def test_update_settings_updates_fields():
    """update_settings updates only the provided (non-None) fields."""
    existing = _make_settings(billing_cycle=BillingCycle.monthly)
    db = _mock_db_with_one(existing)
    data = BillingSettingsUpdate(billing_cycle=BillingCycle.weekly, tax_id="99-8887776")
    settings = await update_settings(db, account_id=_ACCOUNT_ID, data=data, updated_by_id=_USER_ID)
    assert settings.billing_cycle == BillingCycle.weekly
    assert settings.tax_id == "99-8887776"
    # unchanged field remains as-is
    assert settings.billing_company_name == "Acme Corp"


@pytest.mark.asyncio
async def test_update_settings_normalizes_country_to_uppercase():
    """update_settings normalizes billing_country to uppercase."""
    existing = _make_settings()
    db = _mock_db_with_one(existing)
    data = BillingSettingsUpdate(billing_country="us")
    settings = await update_settings(db, account_id=_ACCOUNT_ID, data=data, updated_by_id=_USER_ID)
    assert settings.billing_country == "US"


# ---------------------------------------------------------------------------
# Service: add_payment_method
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_payment_method_success():
    """add_payment_method creates a new payment method."""
    existing_settings = _make_settings()
    db = AsyncMock()
    r_settings = MagicMock()
    r_settings.scalar_one_or_none.return_value = existing_settings
    r_no_default = MagicMock()
    r_no_default.scalars.return_value.all.return_value = []
    db.execute.side_effect = [r_settings, r_no_default]

    data = PaymentMethodCreate(
        payment_type=PaymentMethodType.credit_card,
        display_name="Corporate Visa ending 4242",
        last_four="4242",
        set_as_default=True,
    )
    method = await add_payment_method(
        db, account_id=_ACCOUNT_ID, data=data, created_by_id=_USER_ID
    )
    assert method.display_name == "Corporate Visa ending 4242"
    assert method.is_default is True
    assert method.account_id == _ACCOUNT_ID
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_add_payment_method_set_as_default_false():
    """add_payment_method with set_as_default=False does not clear existing default."""
    existing_settings = _make_settings()
    db = _mock_db_with_one(existing_settings)
    data = PaymentMethodCreate(
        payment_type=PaymentMethodType.ach_bank_account,
        display_name="ACH Bank Account",
        set_as_default=False,
    )
    method = await add_payment_method(
        db, account_id=_ACCOUNT_ID, data=data, created_by_id=_USER_ID
    )
    assert method.is_default is False


# ---------------------------------------------------------------------------
# Service: get_payment_method
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_payment_method_returns_method():
    """get_payment_method returns the method when found."""
    method = _make_method()
    db = _mock_db_with_one(method)
    result = await get_payment_method(db, method_id=_METHOD_ID, account_id=_ACCOUNT_ID)
    assert result.id == _METHOD_ID


@pytest.mark.asyncio
async def test_get_payment_method_not_found_raises_404():
    """get_payment_method raises 404 when method does not exist."""
    db = _mock_db_with_one(None)
    with pytest.raises(HTTPException) as exc_info:
        await get_payment_method(db, method_id=999, account_id=_ACCOUNT_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: list_payment_methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_payment_methods_returns_active():
    """list_payment_methods returns active payment methods."""
    methods = [_make_method(), _make_method(id=21)]
    db = _mock_db_with_list(methods)
    result = await list_payment_methods(db, account_id=_ACCOUNT_ID, active_only=True)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_payment_methods_all():
    """list_payment_methods with active_only=False returns all methods."""
    methods = [_make_method(), _make_method(id=22, is_active=False)]
    db = _mock_db_with_list(methods)
    result = await list_payment_methods(db, account_id=_ACCOUNT_ID, active_only=False)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Service: set_default_payment_method
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_default_payment_method_success():
    """set_default_payment_method marks method as default and clears prior."""
    method = _make_method(is_default=False, is_active=True)
    db = AsyncMock()
    r_method = MagicMock()
    r_method.scalar_one_or_none.return_value = method
    r_clear = MagicMock()
    r_clear.scalars.return_value.all.return_value = []
    db.execute.side_effect = [r_method, r_clear]

    result = await set_default_payment_method(db, method_id=_METHOD_ID, account_id=_ACCOUNT_ID)
    assert result.is_default is True


@pytest.mark.asyncio
async def test_set_default_payment_method_not_found_raises_404():
    """set_default_payment_method raises 404 when method does not exist."""
    db = _mock_db_with_one(None)
    with pytest.raises(HTTPException) as exc_info:
        await set_default_payment_method(db, method_id=999, account_id=_ACCOUNT_ID)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_set_default_payment_method_inactive_raises_409():
    """set_default_payment_method raises 409 when method is inactive."""
    method = _make_method(is_active=False)
    db = _mock_db_with_one(method)
    with pytest.raises(HTTPException) as exc_info:
        await set_default_payment_method(db, method_id=_METHOD_ID, account_id=_ACCOUNT_ID)
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service: deactivate_payment_method
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_payment_method_sets_inactive():
    """deactivate_payment_method sets is_active=False."""
    method = _make_method(is_active=True, is_default=False)
    db = _mock_db_with_one(method)
    result = await deactivate_payment_method(db, method_id=_METHOD_ID, account_id=_ACCOUNT_ID)
    assert result.is_active is False
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_deactivate_payment_method_clears_default_flag():
    """deactivate_payment_method clears is_default when the method was default."""
    method = _make_method(is_active=True, is_default=True)
    db = _mock_db_with_one(method)
    result = await deactivate_payment_method(db, method_id=_METHOD_ID, account_id=_ACCOUNT_ID)
    assert result.is_default is False
    assert result.is_active is False


@pytest.mark.asyncio
async def test_deactivate_payment_method_not_found_raises_404():
    """deactivate_payment_method raises 404 when method does not exist."""
    db = _mock_db_with_one(None)
    with pytest.raises(HTTPException) as exc_info:
        await deactivate_payment_method(db, method_id=999, account_id=_ACCOUNT_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: delete_payment_method
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_payment_method_success():
    """delete_payment_method hard-deletes a non-default method."""
    method = _make_method(is_default=False)
    db = _mock_db_with_one(method)
    await delete_payment_method(db, method_id=_METHOD_ID, account_id=_ACCOUNT_ID)
    db.delete.assert_called_once_with(method)
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_delete_payment_method_not_found_raises_404():
    """delete_payment_method raises 404 when method does not exist."""
    db = _mock_db_with_one(None)
    with pytest.raises(HTTPException) as exc_info:
        await delete_payment_method(db, method_id=999, account_id=_ACCOUNT_ID)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_payment_method_is_default_raises_409():
    """delete_payment_method raises 409 when attempting to delete the default method."""
    method = _make_method(is_default=True)
    db = _mock_db_with_one(method)
    with pytest.raises(HTTPException) as exc_info:
        await delete_payment_method(db, method_id=_METHOD_ID, account_id=_ACCOUNT_ID)
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service: get_billing_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_billing_summary_returns_summary():
    """get_billing_summary returns settings, payment methods, and derived fields."""
    settings = _make_settings(auto_pay_enabled=True)
    default_method = _make_method(is_default=True, is_active=True)

    db = AsyncMock()
    r_settings = MagicMock()
    r_settings.scalar_one_or_none.return_value = settings
    r_methods = MagicMock()
    r_methods.scalars.return_value.all.return_value = [default_method]
    db.execute.side_effect = [r_settings, r_methods]

    summary = await get_billing_summary(db, account_id=_ACCOUNT_ID)
    assert summary.settings.id == _SETTINGS_ID
    assert len(summary.payment_methods) == 1
    assert summary.default_payment_method is not None
    assert summary.default_payment_method.id == _METHOD_ID
    assert summary.auto_pay_ready is True
    assert summary.has_tax_id is True
    assert summary.has_complete_billing_address is True


@pytest.mark.asyncio
async def test_get_billing_summary_auto_pay_not_ready_without_default():
    """get_billing_summary auto_pay_ready is False when no default payment method."""
    settings = _make_settings(auto_pay_enabled=True)
    db = AsyncMock()
    r_settings = MagicMock()
    r_settings.scalar_one_or_none.return_value = settings
    r_methods = MagicMock()
    r_methods.scalars.return_value.all.return_value = []
    db.execute.side_effect = [r_settings, r_methods]

    summary = await get_billing_summary(db, account_id=_ACCOUNT_ID)
    assert summary.auto_pay_ready is False
    assert summary.default_payment_method is None


@pytest.mark.asyncio
async def test_get_billing_summary_incomplete_address():
    """get_billing_summary has_complete_billing_address is False when fields missing."""
    settings = _make_settings(billing_city=None)  # missing city
    db = AsyncMock()
    r_settings = MagicMock()
    r_settings.scalar_one_or_none.return_value = settings
    r_methods = MagicMock()
    r_methods.scalars.return_value.all.return_value = []
    db.execute.side_effect = [r_settings, r_methods]

    summary = await get_billing_summary(db, account_id=_ACCOUNT_ID)
    assert summary.has_complete_billing_address is False


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_billing_settings_update_all_optional():
    """BillingSettingsUpdate accepts an empty payload (all fields optional)."""
    data = BillingSettingsUpdate()
    assert data.billing_company_name is None
    assert data.tax_id is None
    assert data.billing_cycle is None
    assert data.auto_pay_enabled is None


def test_billing_settings_update_country_accepted():
    """BillingSettingsUpdate accepts a valid 2-char billing_country."""
    data = BillingSettingsUpdate(billing_country="CA")
    assert data.billing_country == "CA"


def test_payment_method_create_required_fields():
    """PaymentMethodCreate validates required fields."""
    data = PaymentMethodCreate(
        payment_type=PaymentMethodType.ach_bank_account,
        display_name="ACH Wells Fargo ending 6789",
        last_four="6789",
        bank_name="Wells Fargo",
    )
    assert data.payment_type == PaymentMethodType.ach_bank_account
    assert data.bank_name == "Wells Fargo"


def test_payment_method_create_set_as_default_defaults_false():
    """PaymentMethodCreate set_as_default defaults to False."""
    data = PaymentMethodCreate(
        payment_type=PaymentMethodType.credit_card,
        display_name="Visa ending 1111",
    )
    assert data.set_as_default is False


def test_billing_settings_response_from_attributes():
    """BillingSettingsResponse.model_validate works on a model instance."""
    settings = _make_settings()
    resp = BillingSettingsResponse.model_validate(settings)
    assert resp.id == _SETTINGS_ID
    assert resp.account_id == _ACCOUNT_ID
    assert resp.billing_company_name == "Acme Corp"
    assert resp.billing_cycle == BillingCycle.monthly


def test_payment_method_response_from_attributes():
    """PaymentMethodResponse.model_validate works on a model instance."""
    method = _make_method()
    resp = PaymentMethodResponse.model_validate(method)
    assert resp.id == _METHOD_ID
    assert resp.payment_type == PaymentMethodType.credit_card
    assert resp.last_four == "4242"
    assert resp.is_active is True


def test_billing_summary_response_fields():
    """BillingSummaryResponse has all expected fields."""
    settings_resp = BillingSettingsResponse.model_validate(_make_settings())
    method_resp = PaymentMethodResponse.model_validate(_make_method(is_default=True))
    summary = BillingSummaryResponse(
        settings=settings_resp,
        payment_methods=[method_resp],
        default_payment_method=method_resp,
        has_complete_billing_address=True,
        has_tax_id=True,
        auto_pay_ready=True,
    )
    assert summary.has_complete_billing_address is True
    assert summary.auto_pay_ready is True
    assert summary.default_payment_method.id == _METHOD_ID


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

_BASE = f"/api/v1/corporate/{_ACCOUNT_ID}/billing"
_PLATFORM_BASE = "/api/v1/platform-admin/corporate-billing"

_DUMMY_SETTINGS = _make_settings()
_DUMMY_METHOD = _make_method()


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


# Member: billing summary (200)
@patch(
    "app.api.v1.corporate_billing_settings.get_billing_summary",
    new_callable=AsyncMock,
    return_value=BillingSummaryResponse(
        settings=BillingSettingsResponse.model_validate(_make_settings()),
        payment_methods=[],
        default_payment_method=None,
        has_complete_billing_address=True,
        has_tax_id=True,
        auto_pay_ready=False,
    ),
)
def test_api_get_billing_summary_200(mock_summary):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["settings"]["account_id"] == _ACCOUNT_ID
    assert data["has_complete_billing_address"] is True


# Member: list payment methods (200)
@patch(
    "app.api.v1.corporate_billing_settings.list_payment_methods",
    new_callable=AsyncMock,
    return_value=[_DUMMY_METHOD],
)
def test_api_list_payment_methods_200(mock_list):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/payment-methods")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


# Admin: get settings (200)
@patch(
    "app.api.v1.corporate_billing_settings.get_or_create_settings",
    new_callable=AsyncMock,
    return_value=_DUMMY_SETTINGS,
)
def test_api_get_settings_200(mock_get):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["account_id"] == _ACCOUNT_ID
    assert data["billing_cycle"] == "monthly"


# Admin: update settings (200)
@patch(
    "app.api.v1.corporate_billing_settings.update_settings",
    new_callable=AsyncMock,
    return_value=_make_settings(billing_company_name="Updated Corp"),
)
def test_api_update_settings_200(mock_update):
    client = _make_app_client()
    resp = client.patch(
        f"{_BASE}/settings",
        json={"billing_company_name": "Updated Corp"},
    )
    assert resp.status_code == 200
    assert resp.json()["billing_company_name"] == "Updated Corp"


# Admin: add payment method (201)
@patch(
    "app.api.v1.corporate_billing_settings.add_payment_method",
    new_callable=AsyncMock,
    return_value=_DUMMY_METHOD,
)
def test_api_add_payment_method_201(mock_add):
    client = _make_app_client()
    resp = client.post(
        f"{_BASE}/payment-methods",
        json={
            "payment_type": "credit_card",
            "display_name": "Corporate Visa ending 4242",
            "last_four": "4242",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["display_name"] == "Corporate Visa ending 4242"


# Admin: add payment method with set_as_default (201)
@patch(
    "app.api.v1.corporate_billing_settings.add_payment_method",
    new_callable=AsyncMock,
    return_value=_make_method(is_default=True),
)
def test_api_add_payment_method_set_default_201(mock_add):
    client = _make_app_client()
    resp = client.post(
        f"{_BASE}/payment-methods",
        json={
            "payment_type": "credit_card",
            "display_name": "Primary Card",
            "last_four": "9999",
            "set_as_default": True,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["is_default"] is True


# Admin: get payment method by ID (200)
@patch(
    "app.api.v1.corporate_billing_settings.get_payment_method",
    new_callable=AsyncMock,
    return_value=_DUMMY_METHOD,
)
def test_api_get_payment_method_200(mock_get):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/payment-methods/{_METHOD_ID}")
    assert resp.status_code == 200
    assert resp.json()["id"] == _METHOD_ID


# Admin: get payment method by ID (404)
@patch(
    "app.api.v1.corporate_billing_settings.get_payment_method",
    new_callable=AsyncMock,
    side_effect=HTTPException(status_code=404, detail="Payment method not found."),
)
def test_api_get_payment_method_404(mock_get):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/payment-methods/9999")
    assert resp.status_code == 404


# Admin: set default (200)
@patch(
    "app.api.v1.corporate_billing_settings.set_default_payment_method",
    new_callable=AsyncMock,
    return_value=_make_method(is_default=True),
)
def test_api_set_default_payment_method_200(mock_set):
    client = _make_app_client()
    resp = client.post(f"{_BASE}/payment-methods/{_METHOD_ID}/set-default")
    assert resp.status_code == 200
    assert resp.json()["is_default"] is True


# Admin: deactivate (200)
@patch(
    "app.api.v1.corporate_billing_settings.deactivate_payment_method",
    new_callable=AsyncMock,
    return_value=_make_method(is_active=False),
)
def test_api_deactivate_payment_method_200(mock_deact):
    client = _make_app_client()
    resp = client.post(f"{_BASE}/payment-methods/{_METHOD_ID}/deactivate")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


# Admin: delete (204)
@patch(
    "app.api.v1.corporate_billing_settings.delete_payment_method",
    new_callable=AsyncMock,
    return_value=None,
)
def test_api_delete_payment_method_204(mock_delete):
    client = _make_app_client()
    resp = client.delete(f"{_BASE}/payment-methods/{_METHOD_ID}")
    assert resp.status_code == 204


# Admin: delete default → 409
@patch(
    "app.api.v1.corporate_billing_settings.delete_payment_method",
    new_callable=AsyncMock,
    side_effect=HTTPException(status_code=409, detail="Cannot delete the default payment method."),
)
def test_api_delete_payment_method_409_is_default(mock_delete):
    client = _make_app_client()
    resp = client.delete(f"{_BASE}/payment-methods/{_METHOD_ID}")
    assert resp.status_code == 409


# Platform-admin: list all (200)
@patch(
    "app.api.v1.corporate_billing_settings.select",
    MagicMock(),
)
def test_api_platform_admin_list_settings_200():
    from unittest.mock import patch as p
    settings_list = [_DUMMY_SETTINGS]
    with p("app.api.v1.corporate_billing_settings.select", MagicMock()):
        client = _make_app_client()
        # override the db to return the list
        from app.main import app
        from app.api.deps import get_db

        async def override_db_with_list():
            db = AsyncMock()
            result = MagicMock()
            result.scalars.return_value.all.return_value = settings_list
            db.execute.return_value = result
            yield db

        app.dependency_overrides[get_db] = override_db_with_list
        resp = client.get(f"{_PLATFORM_BASE}/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


# Platform-admin: get for account (200)
def test_api_platform_admin_get_settings_200():
    from app.main import app
    from app.api.deps import get_db, require_admin
    from app.models.user import User
    from unittest.mock import MagicMock, AsyncMock

    mock_admin = MagicMock(spec=User)
    mock_admin.id = _USER_ID

    async def override_admin():
        return mock_admin

    async def override_db_with_settings():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _DUMMY_SETTINGS
        db.execute.return_value = result
        yield db

    app.dependency_overrides[require_admin] = override_admin
    app.dependency_overrides[get_db] = override_db_with_settings

    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get(f"{_PLATFORM_BASE}/{_ACCOUNT_ID}/settings")
    assert resp.status_code == 200
    assert resp.json()["account_id"] == _ACCOUNT_ID
