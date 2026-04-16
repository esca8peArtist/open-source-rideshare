"""Corporate Receipt Template endpoints.

Finance teams configure per-account receipt templates for branded ride receipts.

Member endpoints (any active member):
  GET  /corporate/accounts/me/receipt-template          — view own account's template

Account-admin endpoints:
  PUT  /corporate/accounts/me/receipt-template          — create or update template
  POST /corporate/accounts/me/receipt-template/deactivate — deactivate template
  DELETE /corporate/accounts/me/receipt-template        — hard-delete template

Platform-admin endpoints:
  GET  /platform/corporate/receipt-templates            — list all templates
  GET  /platform/corporate/accounts/{account_id}/receipt-template
                                                        — get template for any account
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_receipt_template import (
    ReceiptTemplateListResponse,
    ReceiptTemplateResponse,
    ReceiptTemplateUpdate,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_receipt_template import (
    deactivate_receipt_template,
    delete_receipt_template,
    get_or_create_receipt_template,
    get_receipt_template_for_ride,
    list_all_receipt_templates,
    update_receipt_template,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-receipt-template"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the account_id for the authenticated user.

    Raises HTTP 404 if the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Member: view own account's receipt template
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/receipt-template",
    response_model=ReceiptTemplateResponse,
    summary="Get the receipt template for own corporate account",
)
async def get_my_receipt_template(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the receipt template for the requesting user's corporate account.

    Creates a default template record if none exists yet (upsert-on-read
    pattern).  Accessible by any active member.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_or_create_receipt_template(db, account_id)


# ---------------------------------------------------------------------------
# Admin: create or update receipt template
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/receipt-template",
    response_model=ReceiptTemplateResponse,
    summary="Create or update the receipt template for own account (admin only)",
)
async def update_my_receipt_template(
    payload: ReceiptTemplateUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or update the receipt template for the requesting user's account.

    Only account admins may call this endpoint.  Fields not included in the
    request body are left unchanged.  The template is created with defaults if
    none exists yet.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await update_receipt_template(db, account_id, payload, admin_id=user.id)


# ---------------------------------------------------------------------------
# Admin: deactivate receipt template
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/receipt-template/deactivate",
    response_model=ReceiptTemplateResponse,
    summary="Deactivate the receipt template for own account (admin only)",
)
async def deactivate_my_receipt_template(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate the receipt template for the requesting user's account.

    Sets ``is_active=False`` so the template is no longer applied to new ride
    receipts.  Returns 409 if the template is already inactive.  Returns 404
    if no template has been configured.

    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await deactivate_receipt_template(db, account_id, admin_id=user.id)


# ---------------------------------------------------------------------------
# Admin: hard-delete receipt template
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/receipt-template",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete the receipt template for own account (admin only)",
)
async def delete_my_receipt_template(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete the receipt template for the requesting user's account.

    This operation is irreversible.  Returns 404 if no template has been
    configured.  Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await delete_receipt_template(db, account_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all templates
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/receipt-templates",
    response_model=ReceiptTemplateListResponse,
    summary="Admin: list receipt templates for all corporate accounts",
)
async def admin_list_receipt_templates(
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of receipt templates across all corporate accounts.

    Ordered by account_id.  Platform admin only.
    """
    return await list_all_receipt_templates(db, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Platform-admin: get template for a specific account
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/accounts/{account_id}/receipt-template",
    response_model=ReceiptTemplateResponse,
    summary="Admin: get the receipt template for a specific corporate account",
)
async def admin_get_receipt_template(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the receipt template for any corporate account.

    Creates a default template record if none exists yet (upsert-on-read).
    Platform admin only.
    """
    return await get_or_create_receipt_template(db, account_id)
