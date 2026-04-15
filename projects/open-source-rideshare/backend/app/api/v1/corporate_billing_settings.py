"""Corporate Billing Settings endpoints.

Corporate accounts configure how they want to be billed: billing address,
tax ID, PO number requirements, auto-pay, billing cycle, invoice email
recipients, and payment methods.

Member endpoints (any account member):
  GET  /api/v1/corporate/{account_id}/billing/summary
      — combined billing settings + payment methods overview (read-only)
  GET  /api/v1/corporate/{account_id}/billing/payment-methods
      — list active payment methods

Admin endpoints:
  GET    /api/v1/corporate/{account_id}/billing/settings
      — get billing settings (creates defaults on first access)
  PATCH  /api/v1/corporate/{account_id}/billing/settings
      — update billing settings
  POST   /api/v1/corporate/{account_id}/billing/payment-methods
      — add a new payment method
  GET    /api/v1/corporate/{account_id}/billing/payment-methods/{method_id}
      — get a specific payment method
  POST   /api/v1/corporate/{account_id}/billing/payment-methods/{method_id}/set-default
      — designate a payment method as default
  POST   /api/v1/corporate/{account_id}/billing/payment-methods/{method_id}/deactivate
      — soft-delete a payment method
  DELETE /api/v1/corporate/{account_id}/billing/payment-methods/{method_id}
      — hard-delete a payment method (not allowed if it's the default)

Platform-admin endpoints:
  GET  /api/v1/platform-admin/corporate-billing/
      — list all billing settings across accounts (paginated)
  GET  /api/v1/platform-admin/corporate-billing/{account_id}/settings
      — get billing settings for a specific account
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
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

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-billing-settings"])


# ---------------------------------------------------------------------------
# Member: billing summary (read-only overview)
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/billing/summary",
    response_model=BillingSummaryResponse,
    summary="Member: get billing summary for the corporate account",
)
async def get_billing_summary_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a combined overview of billing settings and payment methods.

    Creates a default settings row on first access.  Never returns 404.
    Any account member may view this.
    """
    return await get_billing_summary(db, account_id=account_id)


# ---------------------------------------------------------------------------
# Member: list payment methods (read-only)
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/billing/payment-methods",
    response_model=list[PaymentMethodResponse],
    summary="Member: list active payment methods for the corporate account",
)
async def list_payment_methods_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all active payment methods for the account.

    Returns an empty list if no payment methods exist.
    """
    methods = await list_payment_methods(db, account_id=account_id, active_only=True)
    return [PaymentMethodResponse.model_validate(m) for m in methods]


# ---------------------------------------------------------------------------
# Admin: get billing settings
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/billing/settings",
    response_model=BillingSettingsResponse,
    summary="Admin: get billing settings for the corporate account",
)
async def get_settings_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return billing settings for the account.

    Creates a default settings row on first access.
    Requires ADMIN role within the account.
    """
    settings = await get_or_create_settings(db, account_id=account_id)
    await db.commit()
    return BillingSettingsResponse.model_validate(settings)


# ---------------------------------------------------------------------------
# Admin: update billing settings
# ---------------------------------------------------------------------------


@router.patch(
    "/corporate/{account_id}/billing/settings",
    response_model=BillingSettingsResponse,
    summary="Admin: update billing settings for the corporate account",
)
async def update_settings_endpoint(
    account_id: int,
    data: BillingSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update billing settings for the account.

    Creates the settings row with defaults if it does not yet exist.
    Requires ADMIN role within the account.
    """
    settings = await update_settings(
        db, account_id=account_id, data=data, updated_by_id=user.id
    )
    await db.commit()
    return BillingSettingsResponse.model_validate(settings)


# ---------------------------------------------------------------------------
# Admin: add payment method
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/billing/payment-methods",
    response_model=PaymentMethodResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: add a payment method to the corporate account",
)
async def add_payment_method_endpoint(
    account_id: int,
    data: PaymentMethodCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a new payment instrument to the account.

    When ``set_as_default=True``, the new method becomes the primary payment
    method and any prior default is cleared.
    Requires ADMIN role within the account.
    """
    method = await add_payment_method(
        db, account_id=account_id, data=data, created_by_id=user.id
    )
    await db.commit()
    return PaymentMethodResponse.model_validate(method)


# ---------------------------------------------------------------------------
# Admin: get payment method
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/billing/payment-methods/{method_id}",
    response_model=PaymentMethodResponse,
    summary="Admin: get a specific payment method",
)
async def get_payment_method_endpoint(
    account_id: int,
    method_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single payment method by ID.

    Returns HTTP 404 if not found.
    Requires ADMIN role within the account.
    """
    method = await get_payment_method(db, method_id=method_id, account_id=account_id)
    return PaymentMethodResponse.model_validate(method)


# ---------------------------------------------------------------------------
# Admin: set default payment method
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/billing/payment-methods/{method_id}/set-default",
    response_model=PaymentMethodResponse,
    summary="Admin: designate a payment method as the account default",
)
async def set_default_payment_method_endpoint(
    account_id: int,
    method_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set a payment method as the account's primary (default) method.

    Clears the default flag on any previously designated method.
    Returns HTTP 404 if not found.
    Returns HTTP 409 if the method is inactive.
    Requires ADMIN role within the account.
    """
    method = await set_default_payment_method(
        db, method_id=method_id, account_id=account_id
    )
    await db.commit()
    return PaymentMethodResponse.model_validate(method)


# ---------------------------------------------------------------------------
# Admin: deactivate payment method
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/billing/payment-methods/{method_id}/deactivate",
    response_model=PaymentMethodResponse,
    summary="Admin: soft-delete a payment method",
)
async def deactivate_payment_method_endpoint(
    account_id: int,
    method_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a payment method by marking it inactive.

    If the method was the default, the default flag is cleared.
    Returns HTTP 404 if not found.
    Requires ADMIN role within the account.
    """
    method = await deactivate_payment_method(
        db, method_id=method_id, account_id=account_id
    )
    await db.commit()
    return PaymentMethodResponse.model_validate(method)


# ---------------------------------------------------------------------------
# Admin: hard-delete payment method
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/{account_id}/billing/payment-methods/{method_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: permanently delete a payment method",
)
async def delete_payment_method_endpoint(
    account_id: int,
    method_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a payment method.

    Returns HTTP 404 if not found.
    Returns HTTP 409 if the method is the account's current default —
    designate another method as default first.
    Requires ADMIN role within the account.
    """
    await delete_payment_method(db, method_id=method_id, account_id=account_id)
    await db.commit()


# ---------------------------------------------------------------------------
# Platform-admin: list all billing settings
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate-billing/",
    response_model=list[BillingSettingsResponse],
    summary="Platform admin: list all corporate billing settings",
)
async def platform_admin_list_settings(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all corporate billing settings rows across all accounts.

    Requires platform-level admin role.
    """
    from app.models.corporate_billing_settings import (
        CorporateBillingSettings as CBS,
    )

    result = await db.execute(
        select(CBS).order_by(CBS.created_at.desc()).offset(skip).limit(limit)
    )
    return [BillingSettingsResponse.model_validate(s) for s in result.scalars().all()]


# ---------------------------------------------------------------------------
# Platform-admin: get billing settings for specific account
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate-billing/{account_id}/settings",
    response_model=BillingSettingsResponse,
    summary="Platform admin: get billing settings for a specific account",
)
async def platform_admin_get_settings(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return billing settings for a specific corporate account.

    Creates a default settings row on first access.
    Requires platform-level admin role.
    """
    from app.models.corporate_billing_settings import (
        CorporateBillingSettings as CBS,
    )

    result = await db.execute(
        select(CBS).where(CBS.account_id == account_id)
    )
    settings = result.scalar_one_or_none()
    if settings is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No billing settings found for this account.",
        )
    return BillingSettingsResponse.model_validate(settings)
