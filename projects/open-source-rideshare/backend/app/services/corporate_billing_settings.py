"""Service functions for Corporate Billing Settings.

Corporate accounts configure how they are billed: address, tax ID, PO number
requirements, auto-pay preference, billing cycle, invoice emails, and payment
methods.

Public API
----------
get_or_create_settings     — fetch existing settings or create defaults; never 404
update_settings            — partial-update billing settings; creates row if absent
add_payment_method         — add a new payment instrument to the account
get_payment_method         — fetch a single payment method by ID; 404 if absent
list_payment_methods       — list active payment methods for an account
set_default_payment_method — designate a method as default; clears prior default
deactivate_payment_method  — soft-delete a payment method; 404 if absent
delete_payment_method      — hard-delete a payment method; 404 if absent or is default
get_billing_summary        — combined settings + payment methods response object
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_billing_settings import (
    BillingCycle,
    CorporateBillingSettings,
    CorporatePaymentMethod,
)
from app.schemas.corporate_billing_settings import (
    BillingSummaryResponse,
    BillingSettingsResponse,
    BillingSettingsUpdate,
    PaymentMethodCreate,
    PaymentMethodResponse,
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _get_settings(
    db: AsyncSession, account_id: int
) -> Optional[CorporateBillingSettings]:
    """Return the billing settings row for *account_id*, or None."""
    result = await db.execute(
        select(CorporateBillingSettings).where(
            CorporateBillingSettings.account_id == account_id
        )
    )
    return result.scalar_one_or_none()


async def _require_payment_method(
    db: AsyncSession, method_id: int, account_id: int
) -> CorporatePaymentMethod:
    """Return the payment method or raise HTTP 404."""
    result = await db.execute(
        select(CorporatePaymentMethod).where(
            CorporatePaymentMethod.id == method_id,
            CorporatePaymentMethod.account_id == account_id,
        )
    )
    method = result.scalar_one_or_none()
    if method is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment method not found.",
        )
    return method


def _settings_response(s: CorporateBillingSettings) -> BillingSettingsResponse:
    return BillingSettingsResponse.model_validate(s)


def _method_response(m: CorporatePaymentMethod) -> PaymentMethodResponse:
    return PaymentMethodResponse.model_validate(m)


# ---------------------------------------------------------------------------
# Public service API — billing settings
# ---------------------------------------------------------------------------


async def get_or_create_settings(
    db: AsyncSession,
    account_id: int,
) -> CorporateBillingSettings:
    """Return existing billing settings for *account_id*, or create defaults.

    Never raises 404.  Creates the row with sensible defaults on first access.
    """
    settings = await _get_settings(db, account_id)
    if settings is not None:
        return settings

    settings = CorporateBillingSettings(
        account_id=account_id,
        po_number_required=False,
        auto_pay_enabled=False,
        billing_cycle=BillingCycle.monthly,
    )
    db.add(settings)
    await db.flush()
    return settings


async def update_settings(
    db: AsyncSession,
    account_id: int,
    data: BillingSettingsUpdate,
    updated_by_id: int,
) -> CorporateBillingSettings:
    """Partial-update billing settings for *account_id*.

    Creates the settings row with defaults if it does not yet exist, then
    applies only the non-None fields from *data*.
    """
    settings = await get_or_create_settings(db, account_id)
    settings.updated_by_id = updated_by_id

    if data.billing_company_name is not None:
        settings.billing_company_name = data.billing_company_name
    if data.billing_address_line1 is not None:
        settings.billing_address_line1 = data.billing_address_line1
    if data.billing_address_line2 is not None:
        settings.billing_address_line2 = data.billing_address_line2
    if data.billing_city is not None:
        settings.billing_city = data.billing_city
    if data.billing_state is not None:
        settings.billing_state = data.billing_state
    if data.billing_postal_code is not None:
        settings.billing_postal_code = data.billing_postal_code
    if data.billing_country is not None:
        settings.billing_country = data.billing_country.upper()
    if data.tax_id is not None:
        settings.tax_id = data.tax_id
    if data.po_number_required is not None:
        settings.po_number_required = data.po_number_required
    if data.default_po_number is not None:
        settings.default_po_number = data.default_po_number
    if data.invoice_memo_template is not None:
        settings.invoice_memo_template = data.invoice_memo_template
    if data.auto_pay_enabled is not None:
        settings.auto_pay_enabled = data.auto_pay_enabled
    if data.billing_cycle is not None:
        settings.billing_cycle = data.billing_cycle
    if data.invoice_emails is not None:
        settings.invoice_emails = data.invoice_emails

    await db.flush()
    return settings


# ---------------------------------------------------------------------------
# Public service API — payment methods
# ---------------------------------------------------------------------------


async def add_payment_method(
    db: AsyncSession,
    account_id: int,
    data: PaymentMethodCreate,
    created_by_id: int,
) -> CorporatePaymentMethod:
    """Add a new payment method to the account's billing settings.

    Ensures the settings row exists first (upsert).  When ``data.set_as_default``
    is True, clears the ``is_default`` flag on all other methods for the account
    before marking the new one as default.
    """
    settings = await get_or_create_settings(db, account_id)

    if data.set_as_default:
        await _clear_default_flag(db, account_id)

    method = CorporatePaymentMethod(
        billing_settings_id=settings.id,
        account_id=account_id,
        payment_type=data.payment_type,
        display_name=data.display_name,
        last_four=data.last_four,
        cardholder_name=data.cardholder_name,
        bank_name=data.bank_name,
        external_payment_method_id=data.external_payment_method_id,
        is_default=data.set_as_default,
        is_active=True,
        created_by_id=created_by_id,
    )
    db.add(method)
    await db.flush()
    return method


async def get_payment_method(
    db: AsyncSession, method_id: int, account_id: int
) -> CorporatePaymentMethod:
    """Return a payment method by ID, scoped to *account_id*.

    Raises HTTP 404 if not found.
    """
    return await _require_payment_method(db, method_id, account_id)


async def list_payment_methods(
    db: AsyncSession,
    account_id: int,
    active_only: bool = True,
) -> list[CorporatePaymentMethod]:
    """Return payment methods for *account_id*.

    When *active_only* is True (default), only returns methods where
    ``is_active=True``.
    """
    query = select(CorporatePaymentMethod).where(
        CorporatePaymentMethod.account_id == account_id
    )
    if active_only:
        query = query.where(CorporatePaymentMethod.is_active.is_(True))
    query = query.order_by(
        CorporatePaymentMethod.is_default.desc(),
        CorporatePaymentMethod.created_at.asc(),
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def _clear_default_flag(db: AsyncSession, account_id: int) -> None:
    """Set is_default=False on all payment methods for *account_id*."""
    result = await db.execute(
        select(CorporatePaymentMethod).where(
            CorporatePaymentMethod.account_id == account_id,
            CorporatePaymentMethod.is_default.is_(True),
        )
    )
    for m in result.scalars().all():
        m.is_default = False
    await db.flush()


async def set_default_payment_method(
    db: AsyncSession, method_id: int, account_id: int
) -> CorporatePaymentMethod:
    """Designate *method_id* as the default for *account_id*.

    Clears the ``is_default`` flag on all other methods for the account.
    Raises HTTP 404 if the method is not found.
    Raises HTTP 409 if the method is inactive.
    """
    method = await _require_payment_method(db, method_id, account_id)
    if not method.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot set an inactive payment method as default.",
        )
    await _clear_default_flag(db, account_id)
    method.is_default = True
    await db.flush()
    return method


async def deactivate_payment_method(
    db: AsyncSession, method_id: int, account_id: int
) -> CorporatePaymentMethod:
    """Soft-delete a payment method by setting is_active=False.

    If the method is the current default, the default flag is also cleared.
    Raises HTTP 404 if the method is not found.
    """
    method = await _require_payment_method(db, method_id, account_id)
    method.is_active = False
    if method.is_default:
        method.is_default = False
    await db.flush()
    return method


async def delete_payment_method(
    db: AsyncSession, method_id: int, account_id: int
) -> None:
    """Hard-delete a payment method.

    Raises HTTP 404 if the method is not found.
    Raises HTTP 409 if the method is the account's current default (must
    designate another method as default first).
    """
    method = await _require_payment_method(db, method_id, account_id)
    if method.is_default:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cannot delete the default payment method. "
                "Please designate another method as default first."
            ),
        )
    await db.delete(method)
    await db.flush()


async def get_billing_summary(
    db: AsyncSession, account_id: int
) -> BillingSummaryResponse:
    """Return combined billing settings and payment method overview.

    Creates a default settings row if none exists.  Never raises 404.
    """
    settings = await get_or_create_settings(db, account_id)
    methods = await list_payment_methods(db, account_id, active_only=True)

    default_method = next((m for m in methods if m.is_default), None)

    has_complete_address = all(
        [
            settings.billing_address_line1,
            settings.billing_city,
            settings.billing_state,
            settings.billing_postal_code,
            settings.billing_country,
        ]
    )

    auto_pay_ready = settings.auto_pay_enabled and default_method is not None

    return BillingSummaryResponse(
        settings=_settings_response(settings),
        payment_methods=[_method_response(m) for m in methods],
        default_payment_method=_method_response(default_method) if default_method else None,
        has_complete_billing_address=has_complete_address,
        has_tax_id=bool(settings.tax_id),
        auto_pay_ready=auto_pay_ready,
    )
