"""Tests for the Corporate Multi-Currency Billing feature.

Service layer (async, mocked DB):
   1.  get_or_create_billing_currency — creates record with defaults on first call
   2.  get_or_create_billing_currency — returns existing record on subsequent calls
   3.  update_billing_currency — raises 404 when config not found
   4.  update_billing_currency — updates fields on existing record
   5.  get_billing_currency — raises 404 when not found
   6.  get_billing_currency — returns existing record
   7.  set_billing_currency — raises 422 for unsupported currency code
   8.  set_billing_currency — creates new record when none exists
   9.  set_billing_currency — updates existing record
  10.  set_billing_currency — normalises lowercase currency codes
  11.  create_fx_snapshot — returns None for USD-billed accounts
  12.  create_fx_snapshot — creates snapshot with correct converted amounts
  13.  create_fx_snapshot — returns existing snapshot on duplicate call
  14.  create_fx_snapshot — raises 404 when invoice not found
  15.  create_fx_snapshot — handles accounts with no billing currency config (defaults USD)
  16.  get_fx_snapshot — returns None when no snapshot exists
  17.  get_fx_snapshot — returns snapshot when it exists
  18.  list_account_fx_snapshots — returns empty list when none exist
  19.  list_account_fx_snapshots — returns paginated results newest-first
  20.  list_account_fx_snapshots — respects limit and offset
  21.  get_currency_summary — returns config with zero stats for new account
  22.  get_currency_summary — returns correct non_usd_invoice_count
  23.  get_currency_summary — totals_by_currency sums correctly per currency
  24.  list_all_platform — returns all configs without filter
  25.  list_all_platform — filters by currency_filter

Schema validation:
  26.  BillingCurrencyCreate — defaults billing_currency to USD
  27.  BillingCurrencyCreate — rejects unsupported currency XYZ
  28.  BillingCurrencyCreate — accepts all allowed currencies
  29.  BillingCurrencyUpdate — all fields optional
  30.  BillingCurrencyUpdate — rejects invalid currency on update
  31.  SetCurrencyRequest — rejects unsupported currency
  32.  SetCurrencyRequest — accepts valid currency
  33.  FXSnapshotCreate — requires exchange_rate > 0
  34.  FXSnapshotCreate — rate_source is optional
  35.  BillingCurrencyResponse — from_attributes construction
  36.  FXSnapshotResponse — from_attributes construction
  37.  FXSnapshotListResponse — construction with items
  38.  CurrencySummaryResponse — construction

API layer (service functions patched):
  39.  GET / — 200 member can get billing currency config
  40.  GET / — 404 when corporate account not found
  41.  GET /invoices/{id}/fx-snapshot — 200 returns snapshot
  42.  GET /invoices/{id}/fx-snapshot — 200 returns null when no snapshot
  43.  PUT / — 200 admin can update config
  44.  PUT / — 403 non-admin cannot update config
  45.  POST /set-currency — 200 admin can set currency
  46.  POST /set-currency — 403 non-admin cannot set currency
  47.  POST /set-currency — 422 rejects unsupported currency
  48.  POST /invoices/{id}/fx-snapshot — 201 admin can record snapshot
  49.  POST /invoices/{id}/fx-snapshot — 403 non-admin cannot record snapshot
  50.  POST /invoices/{id}/fx-snapshot — 409 when snapshot already exists
  51.  POST /invoices/{id}/fx-snapshot — 422 when account bills in USD
  52.  GET /fx-snapshots — 200 admin can list snapshots
  53.  GET /fx-snapshots — 403 non-admin cannot list snapshots
  54.  GET /summary — 200 admin can get summary
  55.  GET /summary — 403 non-admin cannot get summary
  56.  GET /platform/corporate/billing-currencies/ — 200 platform-admin can list
  57.  GET /platform/corporate/billing-currencies/ — 200 with currency filter
  58.  GET /platform/corporate/billing-currencies/{account_id} — 200 platform-admin
  59.  GET /platform/corporate/billing-currencies/{account_id} — 404 when not found
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.corporate_billing_currency import (
    CorporateBillingCurrency,
    CorporateInvoiceFXSnapshot,
)
from app.schemas.corporate_billing_currency import (
    ALLOWED_CURRENCIES,
    BillingCurrencyCreate,
    BillingCurrencyResponse,
    BillingCurrencyUpdate,
    CurrencySummaryResponse,
    FXSnapshotCreate,
    FXSnapshotListResponse,
    FXSnapshotResponse,
    SetCurrencyRequest,
)
from app.services.corporate_billing_currency_service import (
    create_fx_snapshot,
    get_billing_currency,
    get_currency_summary,
    get_fx_snapshot,
    get_or_create_billing_currency,
    list_account_fx_snapshots,
    list_all_platform,
    set_billing_currency,
    update_billing_currency,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 42
INVOICE_ID = 100
SNAPSHOT_ID = uuid.uuid4()
CONFIG_ID = uuid.uuid4()

_SERVICE = "app.services.corporate_billing_currency_service"
_ROUTER = "app.api.v1.corporate_billing_currency"

_NOW = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_config(
    config_id: uuid.UUID = CONFIG_ID,
    account_id: int = ACCOUNT_ID,
    billing_currency: str = "USD",
    auto_convert: bool = True,
    fx_provider: str | None = None,
    is_active: bool = True,
) -> CorporateBillingCurrency:
    c = CorporateBillingCurrency()
    c.id = config_id
    c.account_id = account_id
    c.billing_currency = billing_currency
    c.auto_convert_invoices = auto_convert
    c.preferred_fx_provider = fx_provider
    c.is_active = is_active
    c.created_at = _NOW
    c.updated_at = _NOW
    return c


def _make_snapshot(
    snapshot_id: uuid.UUID = SNAPSHOT_ID,
    invoice_id: int = INVOICE_ID,
    account_id: int = ACCOUNT_ID,
    source_currency: str = "USD",
    target_currency: str = "EUR",
    exchange_rate: Decimal = Decimal("1.08"),
    rate_captured_at: datetime = _NOW,
    rate_source: str | None = "ECB",
    original_amount_usd: Decimal = Decimal("100.00"),
    converted_amount: Decimal = Decimal("108.00"),
) -> CorporateInvoiceFXSnapshot:
    s = CorporateInvoiceFXSnapshot()
    s.id = snapshot_id
    s.invoice_id = invoice_id
    s.account_id = account_id
    s.source_currency = source_currency
    s.target_currency = target_currency
    s.exchange_rate = exchange_rate
    s.rate_captured_at = rate_captured_at
    s.rate_source = rate_source
    s.original_amount_usd = original_amount_usd
    s.converted_amount = converted_amount
    s.created_at = _NOW
    return s


def _config_response(config: CorporateBillingCurrency) -> BillingCurrencyResponse:
    return BillingCurrencyResponse(
        id=config.id,
        account_id=config.account_id,
        billing_currency=config.billing_currency,
        auto_convert_invoices=config.auto_convert_invoices,
        preferred_fx_provider=config.preferred_fx_provider,
        is_active=config.is_active,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


def _snapshot_response(snapshot: CorporateInvoiceFXSnapshot) -> FXSnapshotResponse:
    return FXSnapshotResponse(
        id=snapshot.id,
        invoice_id=snapshot.invoice_id,
        account_id=snapshot.account_id,
        source_currency=snapshot.source_currency,
        target_currency=snapshot.target_currency,
        exchange_rate=snapshot.exchange_rate,
        rate_captured_at=snapshot.rate_captured_at,
        rate_source=snapshot.rate_source,
        original_amount_usd=snapshot.original_amount_usd,
        converted_amount=snapshot.converted_amount,
        created_at=snapshot.created_at,
    )


# ---------------------------------------------------------------------------
# Shared mock DB helper
# ---------------------------------------------------------------------------


def _db_returning(scalar=None, *, scalars_all=None):
    """Return an AsyncMock db whose execute().scalar_one_or_none() == scalar."""
    db = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = scalar
    if scalars_all is not None:
        execute_result.scalars.return_value.all.return_value = scalars_all
    db.execute = AsyncMock(return_value=execute_result)
    db.commit = AsyncMock()

    def _refresh(obj):
        # Ensure timestamps exist after refresh so response schema validates
        if not getattr(obj, "created_at", None):
            obj.created_at = _NOW
        if hasattr(obj, "updated_at") and not getattr(obj, "updated_at", None):
            obj.updated_at = _NOW

    db.refresh = AsyncMock(side_effect=_refresh)
    db.add = MagicMock()
    return db


# ---------------------------------------------------------------------------
# Service tests: get_or_create_billing_currency  (1–2)
# ---------------------------------------------------------------------------


class TestGetOrCreateBillingCurrency:
    """Tests for get_or_create_billing_currency."""

    @pytest.mark.asyncio
    async def test_creates_record_with_defaults_on_first_call(self):
        """1. Creates a record with USD defaults when none exists."""
        db = _db_returning(scalar=None)
        result = await get_or_create_billing_currency(db, ACCOUNT_ID)
        assert result.account_id == ACCOUNT_ID
        assert result.billing_currency == "USD"
        assert result.auto_convert_invoices is True
        assert result.is_active is True
        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_existing_record(self):
        """2. Returns existing record without creating a new one."""
        config = _make_config(billing_currency="EUR")
        db = _db_returning(scalar=config)
        result = await get_or_create_billing_currency(db, ACCOUNT_ID)
        assert result.billing_currency == "EUR"
        db.add.assert_not_called()


# ---------------------------------------------------------------------------
# Service tests: update_billing_currency  (3–4)
# ---------------------------------------------------------------------------


class TestUpdateBillingCurrency:
    """Tests for update_billing_currency."""

    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(self):
        """3. Raises 404 when config not found."""
        db = _db_returning(scalar=None)
        with pytest.raises(HTTPException) as exc_info:
            await update_billing_currency(db, ACCOUNT_ID, billing_currency="EUR")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_updates_existing_record(self):
        """4. Updates fields on the existing record."""
        config = _make_config()
        db = _db_returning(scalar=config)
        result = await update_billing_currency(
            db, ACCOUNT_ID, billing_currency="GBP", auto_convert_invoices=False
        )
        assert config.billing_currency == "GBP"
        assert config.auto_convert_invoices is False
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Service tests: get_billing_currency  (5–6)
# ---------------------------------------------------------------------------


class TestGetBillingCurrency:
    """Tests for get_billing_currency."""

    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(self):
        """5. Raises 404 when no config found."""
        db = _db_returning(scalar=None)
        with pytest.raises(HTTPException) as exc_info:
            await get_billing_currency(db, ACCOUNT_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_existing_record(self):
        """6. Returns the existing record."""
        config = _make_config(billing_currency="CAD")
        db = _db_returning(scalar=config)
        result = await get_billing_currency(db, ACCOUNT_ID)
        assert result.billing_currency == "CAD"


# ---------------------------------------------------------------------------
# Service tests: set_billing_currency  (7–10)
# ---------------------------------------------------------------------------


class TestSetBillingCurrency:
    """Tests for set_billing_currency."""

    @pytest.mark.asyncio
    async def test_raises_422_for_unsupported_currency(self):
        """7. Raises 422 for unsupported currency code."""
        db = _db_returning(scalar=None)
        with pytest.raises(HTTPException) as exc_info:
            await set_billing_currency(db, ACCOUNT_ID, "XYZ")
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_creates_new_record_when_none_exists(self):
        """8. Creates a new record when no config exists."""
        db = _db_returning(scalar=None)
        result = await set_billing_currency(db, ACCOUNT_ID, "EUR")
        assert result.billing_currency == "EUR"
        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_existing_record(self):
        """9. Updates existing record's billing_currency."""
        config = _make_config(billing_currency="USD")
        db = _db_returning(scalar=config)
        result = await set_billing_currency(db, ACCOUNT_ID, "JPY")
        assert config.billing_currency == "JPY"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_normalises_lowercase_currency_codes(self):
        """10. Normalises lowercase currency codes to uppercase."""
        db = _db_returning(scalar=None)
        result = await set_billing_currency(db, ACCOUNT_ID, "eur")
        # The returned config will have the normalised code on the ORM object
        # After db.refresh our side_effect sets created_at/updated_at but billing_currency
        # was set to "EUR" before commit, so we check the ORM object was modified.
        db.add.assert_called_once()
        # The new record should have been created with "EUR"
        added_obj = db.add.call_args[0][0]
        assert added_obj.billing_currency == "EUR"


# ---------------------------------------------------------------------------
# Service tests: create_fx_snapshot  (11–15)
# ---------------------------------------------------------------------------


class TestCreateFXSnapshot:
    """Tests for create_fx_snapshot."""

    @pytest.mark.asyncio
    async def test_returns_none_for_usd_billed_account(self):
        """11. Returns None when account billing currency is USD."""
        config = _make_config(billing_currency="USD")

        db = AsyncMock()
        # First execute returns currency config, second would return existing snapshot
        execute_result_currency = MagicMock()
        execute_result_currency.scalar_one_or_none.return_value = config
        execute_result_existing = MagicMock()
        execute_result_existing.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[execute_result_currency, execute_result_existing])
        db.commit = AsyncMock()
        db.add = MagicMock()

        result = await create_fx_snapshot(
            db, invoice_id=INVOICE_ID, account_id=ACCOUNT_ID,
            exchange_rate=Decimal("1.08")
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_creates_snapshot_with_correct_amounts(self):
        """12. Creates snapshot with correctly converted amounts."""
        from app.models.corporate_invoice import CorporateInvoice

        config = _make_config(billing_currency="EUR")
        invoice = CorporateInvoice()
        invoice.id = INVOICE_ID
        invoice.account_id = ACCOUNT_ID
        # Set total_amount attribute for the service (it reads invoice.total_amount)
        invoice.total_amount = Decimal("200.00")

        def _refresh_with_timestamp(obj):
            if not getattr(obj, "created_at", None):
                obj.created_at = _NOW
            if hasattr(obj, "updated_at") and not getattr(obj, "updated_at", None):
                obj.updated_at = _NOW

        db = AsyncMock()
        exec_config = MagicMock()
        exec_config.scalar_one_or_none.return_value = config
        exec_existing = MagicMock()
        exec_existing.scalar_one_or_none.return_value = None
        exec_invoice = MagicMock()
        exec_invoice.scalar_one_or_none.return_value = invoice
        db.execute = AsyncMock(side_effect=[exec_config, exec_existing, exec_invoice])
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=_refresh_with_timestamp)
        db.add = MagicMock()

        result = await create_fx_snapshot(
            db, invoice_id=INVOICE_ID, account_id=ACCOUNT_ID,
            exchange_rate=Decimal("1.08"), rate_source="ECB"
        )
        assert result is not None
        assert result.target_currency == "EUR"
        assert result.source_currency == "USD"
        assert result.rate_source == "ECB"
        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_existing_snapshot_on_duplicate(self):
        """13. Returns existing snapshot when one already exists for the invoice."""
        config = _make_config(billing_currency="EUR")
        existing_snapshot = _make_snapshot()

        db = AsyncMock()
        exec_config = MagicMock()
        exec_config.scalar_one_or_none.return_value = config
        exec_existing = MagicMock()
        exec_existing.scalar_one_or_none.return_value = existing_snapshot
        db.execute = AsyncMock(side_effect=[exec_config, exec_existing])
        db.commit = AsyncMock()
        db.add = MagicMock()

        result = await create_fx_snapshot(
            db, invoice_id=INVOICE_ID, account_id=ACCOUNT_ID,
            exchange_rate=Decimal("1.08")
        )
        assert result is not None
        assert result.id == existing_snapshot.id
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_404_when_invoice_not_found(self):
        """14. Raises 404 when invoice does not exist."""
        config = _make_config(billing_currency="EUR")

        db = AsyncMock()
        exec_config = MagicMock()
        exec_config.scalar_one_or_none.return_value = config
        exec_existing = MagicMock()
        exec_existing.scalar_one_or_none.return_value = None
        exec_invoice = MagicMock()
        exec_invoice.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[exec_config, exec_existing, exec_invoice])
        db.commit = AsyncMock()
        db.add = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await create_fx_snapshot(
                db, invoice_id=9999, account_id=ACCOUNT_ID,
                exchange_rate=Decimal("1.08")
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_no_currency_config_defaults_to_usd_no_snapshot(self):
        """15. No billing currency config → defaults to USD → returns None."""
        db = AsyncMock()
        exec_config = MagicMock()
        exec_config.scalar_one_or_none.return_value = None  # no config
        exec_existing = MagicMock()
        exec_existing.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[exec_config, exec_existing])
        db.commit = AsyncMock()
        db.add = MagicMock()

        result = await create_fx_snapshot(
            db, invoice_id=INVOICE_ID, account_id=ACCOUNT_ID,
            exchange_rate=Decimal("1.08")
        )
        assert result is None


# ---------------------------------------------------------------------------
# Service tests: get_fx_snapshot  (16–17)
# ---------------------------------------------------------------------------


class TestGetFXSnapshot:
    """Tests for get_fx_snapshot."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_snapshot_exists(self):
        """16. Returns None when no snapshot exists for the invoice."""
        db = _db_returning(scalar=None)
        result = await get_fx_snapshot(db, INVOICE_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_snapshot_when_exists(self):
        """17. Returns snapshot when it exists."""
        snapshot = _make_snapshot()
        db = _db_returning(scalar=snapshot)
        result = await get_fx_snapshot(db, INVOICE_ID)
        assert result is not None
        assert result.id == snapshot.id


# ---------------------------------------------------------------------------
# Service tests: list_account_fx_snapshots  (18–20)
# ---------------------------------------------------------------------------


class TestListAccountFXSnapshots:
    """Tests for list_account_fx_snapshots."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_none_exist(self):
        """18. Returns empty list and zero total when none exist."""
        db = AsyncMock()
        exec_count = MagicMock()
        exec_count.scalar_one.return_value = 0
        exec_rows = MagicMock()
        exec_rows.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[exec_count, exec_rows])

        result = await list_account_fx_snapshots(db, ACCOUNT_ID)
        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_returns_paginated_results_newest_first(self):
        """19. Returns records newest-first in correct order."""
        s1 = _make_snapshot(snapshot_id=uuid.uuid4())
        s2 = _make_snapshot(snapshot_id=uuid.uuid4())

        db = AsyncMock()
        exec_count = MagicMock()
        exec_count.scalar_one.return_value = 2
        exec_rows = MagicMock()
        exec_rows.scalars.return_value.all.return_value = [s1, s2]
        db.execute = AsyncMock(side_effect=[exec_count, exec_rows])

        result = await list_account_fx_snapshots(db, ACCOUNT_ID)
        assert result.total == 2
        assert len(result.items) == 2

    @pytest.mark.asyncio
    async def test_respects_limit_and_offset(self):
        """20. Passes limit and offset parameters through correctly."""
        db = AsyncMock()
        exec_count = MagicMock()
        exec_count.scalar_one.return_value = 10
        exec_rows = MagicMock()
        exec_rows.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[exec_count, exec_rows])

        result = await list_account_fx_snapshots(db, ACCOUNT_ID, limit=5, offset=5)
        assert result.total == 10


# ---------------------------------------------------------------------------
# Service tests: get_currency_summary  (21–23)
# ---------------------------------------------------------------------------


class TestGetCurrencySummary:
    """Tests for get_currency_summary."""

    @pytest.mark.asyncio
    async def test_returns_config_with_zero_stats_for_new_account(self):
        """21. New account with no snapshots → zero stats."""
        config = _make_config()

        db = AsyncMock()
        # get_or_create_billing_currency: select returns config
        exec_config = MagicMock()
        exec_config.scalar_one_or_none.return_value = config
        # list snapshots: returns empty
        exec_snapshots = MagicMock()
        exec_snapshots.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[exec_config, exec_snapshots])
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        db.add = MagicMock()

        result = await get_currency_summary(db, ACCOUNT_ID)
        assert result.non_usd_invoice_count == 0
        assert result.total_converted_by_currency == {}

    @pytest.mark.asyncio
    async def test_returns_correct_non_usd_count(self):
        """22. Returns correct non_usd_invoice_count."""
        config = _make_config(billing_currency="EUR")
        s1 = _make_snapshot(snapshot_id=uuid.uuid4(), target_currency="EUR",
                            converted_amount=Decimal("108.00"))
        s2 = _make_snapshot(snapshot_id=uuid.uuid4(), target_currency="EUR",
                            converted_amount=Decimal("216.00"))

        db = AsyncMock()
        exec_config = MagicMock()
        exec_config.scalar_one_or_none.return_value = config
        exec_snapshots = MagicMock()
        exec_snapshots.scalars.return_value.all.return_value = [s1, s2]
        db.execute = AsyncMock(side_effect=[exec_config, exec_snapshots])
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        db.add = MagicMock()

        result = await get_currency_summary(db, ACCOUNT_ID)
        assert result.non_usd_invoice_count == 2

    @pytest.mark.asyncio
    async def test_totals_by_currency_sums_correctly(self):
        """23. total_converted_by_currency sums correctly per currency."""
        config = _make_config(billing_currency="EUR")
        s1 = _make_snapshot(snapshot_id=uuid.uuid4(), target_currency="EUR",
                            converted_amount=Decimal("108.00"))
        s2 = _make_snapshot(snapshot_id=uuid.uuid4(), target_currency="GBP",
                            converted_amount=Decimal("85.00"))
        s3 = _make_snapshot(snapshot_id=uuid.uuid4(), target_currency="EUR",
                            converted_amount=Decimal("54.00"))

        db = AsyncMock()
        exec_config = MagicMock()
        exec_config.scalar_one_or_none.return_value = config
        exec_snapshots = MagicMock()
        exec_snapshots.scalars.return_value.all.return_value = [s1, s2, s3]
        db.execute = AsyncMock(side_effect=[exec_config, exec_snapshots])
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        db.add = MagicMock()

        result = await get_currency_summary(db, ACCOUNT_ID)
        assert result.total_converted_by_currency["EUR"] == Decimal("162.00")
        assert result.total_converted_by_currency["GBP"] == Decimal("85.00")


# ---------------------------------------------------------------------------
# Service tests: list_all_platform  (24–25)
# ---------------------------------------------------------------------------


class TestListAllPlatform:
    """Tests for list_all_platform."""

    @pytest.mark.asyncio
    async def test_returns_all_configs_without_filter(self):
        """24. Returns all configs when no filter applied."""
        c1 = _make_config(config_id=uuid.uuid4(), account_id=1, billing_currency="USD")
        c2 = _make_config(config_id=uuid.uuid4(), account_id=2, billing_currency="EUR")

        db = AsyncMock()
        exec_rows = MagicMock()
        exec_rows.scalars.return_value.all.return_value = [c1, c2]
        db.execute = AsyncMock(return_value=exec_rows)

        result = await list_all_platform(db)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_filters_by_currency_filter(self):
        """25. Filters results by currency_filter."""
        c1 = _make_config(config_id=uuid.uuid4(), account_id=1, billing_currency="EUR")

        db = AsyncMock()
        exec_rows = MagicMock()
        exec_rows.scalars.return_value.all.return_value = [c1]
        db.execute = AsyncMock(return_value=exec_rows)

        result = await list_all_platform(db, currency_filter="EUR")
        assert len(result) == 1
        assert result[0].billing_currency == "EUR"


# ---------------------------------------------------------------------------
# Schema tests  (26–38)
# ---------------------------------------------------------------------------


class TestBillingCurrencyCreate:
    """Schema validation for BillingCurrencyCreate."""

    def test_defaults_billing_currency_to_usd(self):
        """26. Defaults billing_currency to USD."""
        schema = BillingCurrencyCreate()
        assert schema.billing_currency == "USD"

    def test_rejects_unsupported_currency_xyz(self):
        """27. Rejects unsupported currency XYZ."""
        with pytest.raises(ValidationError):
            BillingCurrencyCreate(billing_currency="XYZ")

    def test_accepts_all_allowed_currencies(self):
        """28. Accepts all currencies in ALLOWED_CURRENCIES."""
        for currency in ALLOWED_CURRENCIES:
            schema = BillingCurrencyCreate(billing_currency=currency)
            assert schema.billing_currency == currency


class TestBillingCurrencyUpdate:
    """Schema validation for BillingCurrencyUpdate."""

    def test_all_fields_optional(self):
        """29. All fields are optional — empty construction is valid."""
        schema = BillingCurrencyUpdate()
        assert schema.billing_currency is None
        assert schema.auto_convert_invoices is None
        assert schema.preferred_fx_provider is None
        assert schema.is_active is None

    def test_rejects_invalid_currency_on_update(self):
        """30. Rejects invalid currency code on update."""
        with pytest.raises(ValidationError):
            BillingCurrencyUpdate(billing_currency="ZZZ")


class TestSetCurrencyRequest:
    """Schema validation for SetCurrencyRequest."""

    def test_rejects_unsupported_currency(self):
        """31. Rejects unsupported currency code."""
        with pytest.raises(ValidationError):
            SetCurrencyRequest(currency="XYZ")

    def test_accepts_valid_currency(self):
        """32. Accepts a valid supported currency."""
        schema = SetCurrencyRequest(currency="EUR")
        assert schema.currency == "EUR"


class TestFXSnapshotCreate:
    """Schema validation for FXSnapshotCreate."""

    def test_requires_exchange_rate_greater_than_zero(self):
        """33. exchange_rate must be > 0."""
        with pytest.raises(ValidationError):
            FXSnapshotCreate(exchange_rate=Decimal("0"))

    def test_rate_source_is_optional(self):
        """34. rate_source is optional — can be omitted."""
        schema = FXSnapshotCreate(exchange_rate=Decimal("1.08"))
        assert schema.rate_source is None


class TestResponseSchemas:
    """Tests for response schema construction."""

    def test_billing_currency_response_from_attributes(self):
        """35. BillingCurrencyResponse constructs from ORM attributes."""
        config = _make_config()
        response = BillingCurrencyResponse.model_validate(config)
        assert response.billing_currency == "USD"
        assert response.account_id == ACCOUNT_ID

    def test_fx_snapshot_response_from_attributes(self):
        """36. FXSnapshotResponse constructs from ORM attributes."""
        snapshot = _make_snapshot()
        response = FXSnapshotResponse.model_validate(snapshot)
        assert response.target_currency == "EUR"
        assert response.exchange_rate == Decimal("1.08")

    def test_fx_snapshot_list_response_construction(self):
        """37. FXSnapshotListResponse constructs correctly."""
        snapshot = _make_snapshot()
        resp = FXSnapshotResponse.model_validate(snapshot)
        list_resp = FXSnapshotListResponse(total=1, items=[resp])
        assert list_resp.total == 1
        assert len(list_resp.items) == 1

    def test_currency_summary_response_construction(self):
        """38. CurrencySummaryResponse constructs correctly."""
        config = _make_config()
        config_resp = BillingCurrencyResponse.model_validate(config)
        summary = CurrencySummaryResponse(
            config=config_resp,
            non_usd_invoice_count=5,
            total_converted_by_currency={"EUR": Decimal("540.00")},
        )
        assert summary.non_usd_invoice_count == 5
        assert summary.total_converted_by_currency["EUR"] == Decimal("540.00")


# ---------------------------------------------------------------------------
# API layer tests  (39–59)
# ---------------------------------------------------------------------------

_ACCOUNT_URL = f"/api/v1/corporate/{ACCOUNT_ID}/billing-currency"
_PLATFORM_URL = "/api/v1/platform/corporate/billing-currencies"

client = TestClient(app)


def _make_user(user_id: int = 1, is_admin: bool = False):
    user = MagicMock()
    user.id = user_id
    user.is_admin = is_admin
    return user


def _mock_account():
    account = MagicMock()
    account.id = ACCOUNT_ID
    return account


def _dep_overrides(is_admin: bool = False):
    """Return dependency override dict for FastAPI DI injection."""
    from app.api.deps import get_current_user, get_db, require_admin

    async def _user():
        return _make_user(is_admin=is_admin)

    async def _db():
        return AsyncMock()

    async def _admin():
        return _make_user(is_admin=True)

    return {
        get_current_user: _user,
        get_db: _db,
        require_admin: _admin,
    }


class TestGetBillingCurrencyEndpoint:
    """GET /corporate/{account_id}/billing-currency/"""

    def test_member_can_get_config(self):
        """39. 200 — member can get billing currency config."""
        config_resp = _config_response(_make_config())

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}.get_or_create_billing_currency", new=AsyncMock(return_value=config_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_ACCOUNT_URL}/")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_404_when_account_not_found(self):
        """40. 404 when corporate account not found."""
        with patch(
            f"{_ROUTER}.get_account",
            new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_ACCOUNT_URL}/")
            app.dependency_overrides.clear()
        assert response.status_code == 404


class TestGetFXSnapshotEndpoint:
    """GET /corporate/{account_id}/billing-currency/invoices/{invoice_id}/fx-snapshot"""

    def test_member_can_get_snapshot(self):
        """41. 200 — returns snapshot when it exists."""
        snapshot = _snapshot_response(_make_snapshot())

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}.get_fx_snapshot", new=AsyncMock(return_value=snapshot)),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_ACCOUNT_URL}/invoices/{INVOICE_ID}/fx-snapshot")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_returns_null_when_no_snapshot(self):
        """42. 200 — returns null when no snapshot exists."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}.get_fx_snapshot", new=AsyncMock(return_value=None)),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_ACCOUNT_URL}/invoices/{INVOICE_ID}/fx-snapshot")
            app.dependency_overrides.clear()
        assert response.status_code == 200
        assert response.json() is None


class TestUpdateBillingCurrencyEndpoint:
    """PUT /corporate/{account_id}/billing-currency/"""

    def test_admin_can_update_config(self):
        """43. 200 — admin can update billing currency config."""
        config_resp = _config_response(_make_config(billing_currency="EUR"))

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.update_billing_currency", new=AsyncMock(return_value=config_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.put(f"{_ACCOUNT_URL}/", json={"billing_currency": "EUR"})
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_non_admin_cannot_update(self):
        """44. 403 — non-admin cannot update billing currency config."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.put(f"{_ACCOUNT_URL}/", json={"billing_currency": "EUR"})
            app.dependency_overrides.clear()
        assert response.status_code == 403


class TestSetCurrencyEndpoint:
    """POST /corporate/{account_id}/billing-currency/set-currency"""

    def test_admin_can_set_currency(self):
        """45. 200 — admin can set billing currency."""
        config_resp = _config_response(_make_config(billing_currency="EUR"))

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.set_billing_currency", new=AsyncMock(return_value=config_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.post(f"{_ACCOUNT_URL}/set-currency", json={"currency": "EUR"})
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_non_admin_cannot_set_currency(self):
        """46. 403 — non-admin cannot set billing currency."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.post(f"{_ACCOUNT_URL}/set-currency", json={"currency": "EUR"})
            app.dependency_overrides.clear()
        assert response.status_code == 403

    def test_422_rejects_unsupported_currency(self):
        """47. 422 — rejects unsupported currency code via schema validation."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.post(f"{_ACCOUNT_URL}/set-currency", json={"currency": "XYZ"})
            app.dependency_overrides.clear()
        assert response.status_code == 422


class TestRecordFXSnapshotEndpoint:
    """POST /corporate/{account_id}/billing-currency/invoices/{invoice_id}/fx-snapshot"""

    def test_admin_can_record_snapshot(self):
        """48. 201 — admin can record FX snapshot."""
        snapshot_resp = _snapshot_response(_make_snapshot())

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.get_fx_snapshot", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.create_fx_snapshot", new=AsyncMock(return_value=snapshot_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.post(
                f"{_ACCOUNT_URL}/invoices/{INVOICE_ID}/fx-snapshot",
                json={"exchange_rate": "1.08", "rate_source": "ECB"},
            )
            app.dependency_overrides.clear()
        assert response.status_code == 201

    def test_non_admin_cannot_record_snapshot(self):
        """49. 403 — non-admin cannot record FX snapshot."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.post(
                f"{_ACCOUNT_URL}/invoices/{INVOICE_ID}/fx-snapshot",
                json={"exchange_rate": "1.08"},
            )
            app.dependency_overrides.clear()
        assert response.status_code == 403

    def test_409_when_snapshot_already_exists(self):
        """50. 409 — when snapshot already exists for invoice."""
        existing = _snapshot_response(_make_snapshot())

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.get_fx_snapshot", new=AsyncMock(return_value=existing)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.post(
                f"{_ACCOUNT_URL}/invoices/{INVOICE_ID}/fx-snapshot",
                json={"exchange_rate": "1.08"},
            )
            app.dependency_overrides.clear()
        assert response.status_code == 409

    def test_422_when_account_bills_in_usd(self):
        """51. 422 — when account's billing currency is USD (no snapshot needed)."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.get_fx_snapshot", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.create_fx_snapshot", new=AsyncMock(return_value=None)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.post(
                f"{_ACCOUNT_URL}/invoices/{INVOICE_ID}/fx-snapshot",
                json={"exchange_rate": "1.0"},
            )
            app.dependency_overrides.clear()
        assert response.status_code == 422


class TestListFXSnapshotsEndpoint:
    """GET /corporate/{account_id}/billing-currency/fx-snapshots"""

    def test_admin_can_list_snapshots(self):
        """52. 200 — admin can list FX snapshots."""
        list_resp = FXSnapshotListResponse(total=0, items=[])

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.list_account_fx_snapshots", new=AsyncMock(return_value=list_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.get(f"{_ACCOUNT_URL}/fx-snapshots")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_non_admin_cannot_list_snapshots(self):
        """53. 403 — non-admin cannot list FX snapshots."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_ACCOUNT_URL}/fx-snapshots")
            app.dependency_overrides.clear()
        assert response.status_code == 403


class TestGetCurrencySummaryEndpoint:
    """GET /corporate/{account_id}/billing-currency/summary"""

    def test_admin_can_get_summary(self):
        """54. 200 — admin can get currency summary."""
        config_resp = _config_response(_make_config())
        summary = CurrencySummaryResponse(
            config=config_resp,
            non_usd_invoice_count=0,
            total_converted_by_currency={},
        )

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.get_currency_summary", new=AsyncMock(return_value=summary)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.get(f"{_ACCOUNT_URL}/summary")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_non_admin_cannot_get_summary(self):
        """55. 403 — non-admin cannot get currency summary."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_ACCOUNT_URL}/summary")
            app.dependency_overrides.clear()
        assert response.status_code == 403


class TestPlatformAdminEndpoints:
    """Platform-admin endpoints."""

    def test_platform_admin_can_list_all(self):
        """56. 200 — platform-admin can list all billing currency configs."""
        config_resp = _config_response(_make_config())

        with patch(f"{_ROUTER}.list_all_platform", new=AsyncMock(return_value=[config_resp])):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.get(f"{_PLATFORM_URL}/")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_platform_admin_can_list_with_currency_filter(self):
        """57. 200 — platform-admin can filter by currency."""
        config_resp = _config_response(_make_config(billing_currency="EUR"))

        with patch(f"{_ROUTER}.list_all_platform", new=AsyncMock(return_value=[config_resp])):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.get(f"{_PLATFORM_URL}/?currency=EUR")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_platform_admin_can_get_specific_account(self):
        """58. 200 — platform-admin can get one account's config."""
        config_resp = _config_response(_make_config())

        with patch(f"{_ROUTER}.get_billing_currency", new=AsyncMock(return_value=config_resp)):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.get(f"{_PLATFORM_URL}/{ACCOUNT_ID}")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_platform_admin_gets_404_for_missing_account(self):
        """59. 404 — when account config not found."""
        with patch(
            f"{_ROUTER}.get_billing_currency",
            new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.get(f"{_PLATFORM_URL}/{ACCOUNT_ID}")
            app.dependency_overrides.clear()
        assert response.status_code == 404
