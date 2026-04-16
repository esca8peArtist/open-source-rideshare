"""Corporate Multi-Currency Billing endpoints.

Corporate accounts operating internationally can configure a preferred billing
currency.  When invoices are issued in a non-USD currency, admins can record
an FX rate snapshot for audit.

Member endpoints (any active member):
  GET  /corporate/{account_id}/billing-currency/              — get/create config
  GET  /corporate/{account_id}/billing-currency/invoices/{invoice_id}/fx-snapshot
          — get FX snapshot for an invoice

Admin endpoints (account admins only):
  PUT  /corporate/{account_id}/billing-currency/              — update config
  POST /corporate/{account_id}/billing-currency/set-currency  — set currency
  POST /corporate/{account_id}/billing-currency/invoices/{invoice_id}/fx-snapshot
          — record FX snapshot for an invoice
  GET  /corporate/{account_id}/billing-currency/fx-snapshots  — list snapshots
  GET  /corporate/{account_id}/billing-currency/summary       — currency summary

Platform-admin endpoints:
  GET  /platform/corporate/billing-currencies/                — all accounts
  GET  /platform/corporate/billing-currencies/{account_id}    — one account
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_billing_currency import (
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
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Billing Currency"])


# ---------------------------------------------------------------------------
# Member: get billing currency config (get_or_create)
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/billing-currency/",
    response_model=BillingCurrencyResponse,
    summary="Get billing currency config for a corporate account",
)
async def get_billing_currency_config(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the billing currency configuration for the account.

    Creates the config with defaults (USD) on first access.
    Any active member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_or_create_billing_currency(db, account_id)


# ---------------------------------------------------------------------------
# Member: get FX snapshot for an invoice
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/billing-currency/invoices/{invoice_id}/fx-snapshot",
    response_model=Optional[FXSnapshotResponse],
    summary="Get FX snapshot for an invoice",
)
async def get_invoice_fx_snapshot(
    account_id: int,
    invoice_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the FX rate snapshot for an invoice, or null if none exists.

    Any active member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_fx_snapshot(db, invoice_id)


# ---------------------------------------------------------------------------
# Admin: update billing currency settings
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/billing-currency/",
    response_model=BillingCurrencyResponse,
    summary="Update billing currency settings (admin only)",
)
async def update_billing_currency_config(
    account_id: int,
    data: BillingCurrencyUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update the billing currency configuration.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    update_kwargs = data.model_dump(exclude_none=True)
    return await update_billing_currency(db, account_id, **update_kwargs)


# ---------------------------------------------------------------------------
# Admin: set billing currency
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/billing-currency/set-currency",
    response_model=BillingCurrencyResponse,
    summary="Set the billing currency for a corporate account (admin only)",
)
async def set_account_billing_currency(
    account_id: int,
    data: SetCurrencyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set the billing currency, validated against the allowed ISO 4217 set.

    Returns 422 if the currency code is not in the allowed set.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await set_billing_currency(db, account_id, data.currency)


# ---------------------------------------------------------------------------
# Admin: record FX snapshot for an invoice
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/billing-currency/invoices/{invoice_id}/fx-snapshot",
    response_model=FXSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record FX rate snapshot for an invoice (admin only)",
)
async def record_invoice_fx_snapshot(
    account_id: int,
    invoice_id: int,
    data: FXSnapshotCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record an FX rate snapshot for an invoice.

    Returns 409 if a snapshot already exists for this invoice.
    Returns 422 if the account's billing currency is USD (no snapshot needed).
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)

    # Check for existing snapshot before creating
    existing = await get_fx_snapshot(db, invoice_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An FX snapshot already exists for this invoice.",
        )

    result = await create_fx_snapshot(
        db,
        invoice_id=invoice_id,
        account_id=account_id,
        exchange_rate=data.exchange_rate,
        rate_source=data.rate_source,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "This account bills in USD. No FX snapshot is required for "
                "USD-billed accounts."
            ),
        )
    return result


# ---------------------------------------------------------------------------
# Admin: list FX snapshots for account
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/billing-currency/fx-snapshots",
    response_model=FXSnapshotListResponse,
    summary="List FX snapshots for a corporate account (admin only)",
)
async def list_account_fx_snapshots_endpoint(
    account_id: int,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all FX snapshots for an account, newest first.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await list_account_fx_snapshots(db, account_id, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Admin: currency summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/billing-currency/summary",
    response_model=CurrencySummaryResponse,
    summary="Get currency summary with stats (admin only)",
)
async def get_account_currency_summary(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return billing currency config combined with aggregate invoice stats.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_currency_summary(db, account_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all billing currency configs
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/billing-currencies/",
    response_model=List[BillingCurrencyResponse],
    summary="Admin: list all corporate billing currency configs",
)
async def admin_list_billing_currencies(
    currency: Optional[str] = Query(None, description="Filter by billing currency code"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return billing currency configs across all accounts.

    Platform admin only.
    """
    return await list_all_platform(db, currency_filter=currency, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Platform-admin: get one account's billing currency config
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/billing-currencies/{account_id}",
    response_model=BillingCurrencyResponse,
    summary="Admin: get billing currency config for a specific account",
)
async def admin_get_billing_currency(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the billing currency config for any corporate account.

    Platform admin only.
    """
    return await get_billing_currency(db, account_id)
