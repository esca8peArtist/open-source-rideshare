"""Corporate Billing Contact Management endpoints.

Member endpoints (any active account member — read-only):
  GET  /corporate/accounts/me/billing-contacts                — list active
  GET  /corporate/accounts/me/billing-contacts/{id}           — get one

Admin endpoints (require ADMIN role within the account):
  POST   /corporate/accounts/me/billing-contacts              — add contact
  PUT    /corporate/accounts/me/billing-contacts/{id}         — update contact
  DELETE /corporate/accounts/me/billing-contacts/{id}/deactivate — soft-delete

Platform-admin endpoints:
  GET /admin/corporate/accounts/{account_id}/billing-contacts — list all
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_billing_contact import (
    BillingContactCreate,
    BillingContactListResponse,
    BillingContactResponse,
    BillingContactUpdate,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_billing_contact import (
    add_billing_contact,
    deactivate_billing_contact,
    get_billing_contact,
    list_billing_contacts,
    update_billing_contact,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-billing-contacts"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Member: list billing contacts
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/billing-contacts",
    response_model=BillingContactListResponse,
    summary="List billing contacts for the account",
)
async def list_my_billing_contacts(
    active_only: bool = Query(True, description="When True, only return active contacts."),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of billing contacts in the corporate account.

    Any active account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_billing_contacts(db, account_id, active_only=active_only, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Member: get a single billing contact
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/billing-contacts/{contact_id}",
    response_model=BillingContactResponse,
    summary="Get a billing contact by ID",
)
async def get_my_billing_contact(
    contact_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return details of a specific billing contact.

    Any active account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_billing_contact(db, account_id, contact_id)


# ---------------------------------------------------------------------------
# Admin: add billing contact
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/billing-contacts",
    response_model=BillingContactResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: add a new billing contact",
)
async def add_my_billing_contact(
    data: BillingContactCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a new billing contact to the corporate account.

    Billing contacts receive invoices and financial notification emails.
    They do not need to be platform users — email-only contacts are valid.

    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await add_billing_contact(db, account_id, user.id, data)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Admin: update billing contact
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/billing-contacts/{contact_id}",
    response_model=BillingContactResponse,
    summary="Admin: update a billing contact",
)
async def update_my_billing_contact(
    contact_id: int,
    data: BillingContactUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a billing contact's details.

    The email address is immutable and cannot be changed after creation.
    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await update_billing_contact(db, account_id, contact_id, user.id, data)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Admin: deactivate billing contact
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/billing-contacts/{contact_id}/deactivate",
    response_model=BillingContactResponse,
    summary="Admin: deactivate a billing contact (soft-delete)",
)
async def deactivate_my_billing_contact(
    contact_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a billing contact.

    Deactivated contacts are excluded from notification dispatch but their
    records are preserved for audit history.
    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await deactivate_billing_contact(db, account_id, contact_id, user.id)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Platform-admin: list billing contacts for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/billing-contacts",
    response_model=BillingContactListResponse,
    summary="Platform admin: list all billing contacts for any corporate account",
)
async def platform_admin_list_billing_contacts(
    account_id: int,
    active_only: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return billing contacts for any corporate account.

    Requires platform-level admin role.
    """
    return await list_billing_contacts(db, account_id, active_only=active_only, skip=skip, limit=limit)
