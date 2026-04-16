"""Service layer for Corporate Multi-Currency Billing.

Corporate accounts can configure a preferred billing currency.  When invoices
are issued in a non-USD currency, an FX rate snapshot is stored for audit and
reporting.

Public functions
----------------
get_or_create_billing_currency  — upsert on read; returns existing or creates with defaults.
update_billing_currency         — partial update of billing currency settings.
get_billing_currency            — fetch config (404 if missing).
set_billing_currency            — validate ISO 4217 code and update/create config.
create_fx_snapshot              — record FX rate snapshot for an invoice.
get_fx_snapshot                 — return snapshot or None.
list_account_fx_snapshots       — newest-first paginated list for one account.
get_currency_summary            — config + aggregate stats for one account.
list_all_platform               — platform-admin cross-account view.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_billing_currency import (
    CorporateBillingCurrency,
    CorporateInvoiceFXSnapshot,
)
from app.models.corporate_invoice import CorporateInvoice
from app.schemas.corporate_billing_currency import (
    ALLOWED_CURRENCIES,
    BillingCurrencyResponse,
    BillingCurrencyUpdate,
    CurrencySummaryResponse,
    FXSnapshotListResponse,
    FXSnapshotResponse,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_currency_response(row: CorporateBillingCurrency) -> BillingCurrencyResponse:
    return BillingCurrencyResponse.model_validate(row)


def _to_snapshot_response(row: CorporateInvoiceFXSnapshot) -> FXSnapshotResponse:
    return FXSnapshotResponse.model_validate(row)


# ---------------------------------------------------------------------------
# get_or_create_billing_currency
# ---------------------------------------------------------------------------


async def get_or_create_billing_currency(
    db: AsyncSession,
    account_id: int,
) -> BillingCurrencyResponse:
    """Return the billing currency config for an account, creating it if absent.

    On the first call for an account, creates a default record (USD,
    auto_convert_invoices=True).  Subsequent calls return the existing record.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.

    Returns:
        ``BillingCurrencyResponse`` for the account.
    """
    stmt = select(CorporateBillingCurrency).where(
        CorporateBillingCurrency.account_id == account_id
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()

    if row is None:
        row = CorporateBillingCurrency(
            id=uuid.uuid4(),
            account_id=account_id,
            billing_currency="USD",
            auto_convert_invoices=True,
            preferred_fx_provider=None,
            is_active=True,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

    return _to_currency_response(row)


# ---------------------------------------------------------------------------
# update_billing_currency
# ---------------------------------------------------------------------------


async def update_billing_currency(
    db: AsyncSession,
    account_id: int,
    **kwargs,
) -> BillingCurrencyResponse:
    """Partially update the billing currency configuration for an account.

    Accepted keyword arguments:
        billing_currency (str): New ISO 4217 currency code.
        auto_convert_invoices (bool): Toggle FX snapshot generation.
        preferred_fx_provider (str | None): Audit label for the FX provider.
        is_active (bool): Whether the config is active.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        **kwargs: Fields to update.

    Returns:
        Updated ``BillingCurrencyResponse``.

    Raises:
        HTTPException 404: No billing currency config found for this account.
    """
    stmt = select(CorporateBillingCurrency).where(
        CorporateBillingCurrency.account_id == account_id
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Billing currency configuration not found for this account.",
        )

    allowed_fields = {
        "billing_currency",
        "auto_convert_invoices",
        "preferred_fx_provider",
        "is_active",
    }
    for field, value in kwargs.items():
        if field in allowed_fields and value is not None:
            setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    return _to_currency_response(row)


# ---------------------------------------------------------------------------
# get_billing_currency
# ---------------------------------------------------------------------------


async def get_billing_currency(
    db: AsyncSession,
    account_id: int,
) -> BillingCurrencyResponse:
    """Return the billing currency config for an account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.

    Returns:
        ``BillingCurrencyResponse``.

    Raises:
        HTTPException 404: No billing currency config found.
    """
    stmt = select(CorporateBillingCurrency).where(
        CorporateBillingCurrency.account_id == account_id
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Billing currency configuration not found for this account.",
        )
    return _to_currency_response(row)


# ---------------------------------------------------------------------------
# set_billing_currency
# ---------------------------------------------------------------------------


async def set_billing_currency(
    db: AsyncSession,
    account_id: int,
    currency_code: str,
) -> BillingCurrencyResponse:
    """Set the billing currency for an account.

    Validates that ``currency_code`` is in the allowed ISO 4217 set.  If a
    config record already exists it is updated; otherwise a new record is
    created with defaults.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        currency_code: ISO 4217 currency code to set.

    Returns:
        Updated or created ``BillingCurrencyResponse``.

    Raises:
        HTTPException 422: Currency code not in the allowed set.
    """
    code = currency_code.strip().upper()
    if code not in ALLOWED_CURRENCIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Currency '{currency_code}' is not supported. "
                f"Allowed values: {sorted(ALLOWED_CURRENCIES)}"
            ),
        )

    stmt = select(CorporateBillingCurrency).where(
        CorporateBillingCurrency.account_id == account_id
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()

    if row is None:
        row = CorporateBillingCurrency(
            id=uuid.uuid4(),
            account_id=account_id,
            billing_currency=code,
            auto_convert_invoices=True,
            preferred_fx_provider=None,
            is_active=True,
        )
        db.add(row)
    else:
        row.billing_currency = code

    await db.commit()
    await db.refresh(row)
    return _to_currency_response(row)


# ---------------------------------------------------------------------------
# create_fx_snapshot
# ---------------------------------------------------------------------------


async def create_fx_snapshot(
    db: AsyncSession,
    invoice_id: int,
    account_id: int,
    exchange_rate: Decimal,
    rate_source: Optional[str] = None,
) -> Optional[FXSnapshotResponse]:
    """Record an FX rate snapshot for an invoice.

    If the account's billing currency is USD (the platform base currency),
    no snapshot is needed and this function returns None.

    If a snapshot already exists for the invoice, the existing record is
    returned (upsert behaviour — callers receive 409 from the router).

    The invoice's ``total_amount`` is read from ``corporate_invoices_v2`` to
    compute the ``converted_amount``.

    Args:
        db: Async SQLAlchemy session.
        invoice_id: UUID of the invoice.
        account_id: Corporate account ID.
        exchange_rate: FX rate (USD → target currency).
        rate_source: Optional label for the rate provider.

    Returns:
        ``FXSnapshotResponse`` or None if the account bills in USD.

    Raises:
        HTTPException 404: Invoice not found.
    """
    # Look up billing currency
    currency_stmt = select(CorporateBillingCurrency).where(
        CorporateBillingCurrency.account_id == account_id
    )
    currency_result = await db.execute(currency_stmt)
    currency_row = currency_result.scalar_one_or_none()

    target_currency = currency_row.billing_currency if currency_row else "USD"

    if target_currency == "USD":
        return None

    # Check for existing snapshot
    existing_stmt = select(CorporateInvoiceFXSnapshot).where(
        CorporateInvoiceFXSnapshot.invoice_id == invoice_id
    )
    existing_result = await db.execute(existing_stmt)
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        return _to_snapshot_response(existing)

    # Look up invoice for the USD amount
    invoice_stmt = select(CorporateInvoice).where(
        CorporateInvoice.id == invoice_id,
        CorporateInvoice.account_id == account_id,
    )
    invoice_result = await db.execute(invoice_stmt)
    invoice = invoice_result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found.",
        )

    original_usd = Decimal(str(invoice.total_amount or 0))
    converted = (original_usd * exchange_rate).quantize(Decimal("0.01"))
    now = datetime.now(tz=timezone.utc)

    snapshot = CorporateInvoiceFXSnapshot(
        id=uuid.uuid4(),
        invoice_id=invoice_id,
        account_id=account_id,
        source_currency="USD",
        target_currency=target_currency,
        exchange_rate=exchange_rate,
        rate_captured_at=now,
        rate_source=rate_source,
        original_amount_usd=original_usd,
        converted_amount=converted,
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)
    return _to_snapshot_response(snapshot)


# ---------------------------------------------------------------------------
# get_fx_snapshot
# ---------------------------------------------------------------------------


async def get_fx_snapshot(
    db: AsyncSession,
    invoice_id: int,
) -> Optional[FXSnapshotResponse]:
    """Return the FX snapshot for an invoice, or None if it does not exist.

    Args:
        db: Async SQLAlchemy session.
        invoice_id: UUID of the invoice.

    Returns:
        ``FXSnapshotResponse`` or None.
    """
    stmt = select(CorporateInvoiceFXSnapshot).where(
        CorporateInvoiceFXSnapshot.invoice_id == invoice_id
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return _to_snapshot_response(row)


# ---------------------------------------------------------------------------
# list_account_fx_snapshots
# ---------------------------------------------------------------------------


async def list_account_fx_snapshots(
    db: AsyncSession,
    account_id: int,
    limit: int = 50,
    offset: int = 0,
) -> FXSnapshotListResponse:
    """Return FX snapshots for one account, newest first.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        limit: Max records to return (default 50).
        offset: Records to skip (default 0).

    Returns:
        ``FXSnapshotListResponse``.
    """
    count_stmt = select(func.count()).select_from(
        select(CorporateInvoiceFXSnapshot)
        .where(CorporateInvoiceFXSnapshot.account_id == account_id)
        .subquery()
    )
    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    rows_stmt = (
        select(CorporateInvoiceFXSnapshot)
        .where(CorporateInvoiceFXSnapshot.account_id == account_id)
        .order_by(CorporateInvoiceFXSnapshot.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows_result = await db.execute(rows_stmt)
    rows = rows_result.scalars().all()

    return FXSnapshotListResponse(
        total=total,
        items=[_to_snapshot_response(r) for r in rows],
    )


# ---------------------------------------------------------------------------
# get_currency_summary
# ---------------------------------------------------------------------------


async def get_currency_summary(
    db: AsyncSession,
    account_id: int,
) -> CurrencySummaryResponse:
    """Return billing currency config and aggregate invoice stats.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.

    Returns:
        ``CurrencySummaryResponse`` containing the config and stats.

    Raises:
        HTTPException 404: No billing currency config found.
    """
    config = await get_or_create_billing_currency(db, account_id)

    # Count non-USD invoices and total converted amount per currency
    rows_stmt = select(CorporateInvoiceFXSnapshot).where(
        CorporateInvoiceFXSnapshot.account_id == account_id
    )
    rows_result = await db.execute(rows_stmt)
    rows = rows_result.scalars().all()

    non_usd_count = len(rows)
    totals_by_currency: dict[str, Decimal] = {}
    for row in rows:
        cur = row.target_currency
        totals_by_currency[cur] = totals_by_currency.get(cur, Decimal("0")) + Decimal(
            str(row.converted_amount)
        )

    return CurrencySummaryResponse(
        config=config,
        non_usd_invoice_count=non_usd_count,
        total_converted_by_currency=totals_by_currency,
    )


# ---------------------------------------------------------------------------
# list_all_platform
# ---------------------------------------------------------------------------


async def list_all_platform(
    db: AsyncSession,
    currency_filter: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[BillingCurrencyResponse]:
    """Return billing currency configs across all accounts (platform admin).

    Args:
        db: Async SQLAlchemy session.
        currency_filter: Optional ISO 4217 code to filter by billing_currency.
        limit: Max records to return (default 100).
        offset: Records to skip (default 0).

    Returns:
        List of ``BillingCurrencyResponse`` records.
    """
    conditions = []
    if currency_filter is not None:
        conditions.append(
            CorporateBillingCurrency.billing_currency == currency_filter.upper()
        )

    base = select(CorporateBillingCurrency)
    if conditions:
        base = base.where(and_(*conditions))

    rows_stmt = (
        base.order_by(CorporateBillingCurrency.account_id)
        .limit(limit)
        .offset(offset)
    )
    rows_result = await db.execute(rows_stmt)
    rows = rows_result.scalars().all()
    return [_to_currency_response(r) for r in rows]
