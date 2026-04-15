"""Corporate Account Contact endpoints.

Enterprise admins register non-billing operational contacts for their accounts.
These contacts can be reached for account issues, travel policy questions,
employee onboarding, and legal/compliance matters.

Member endpoints (any corporate member):
  GET  /corporate/accounts/me/contacts              — list contacts
  GET  /corporate/accounts/me/contacts/{id}         — get single contact

Admin endpoints (require account membership):
  POST   /corporate/accounts/me/contacts            — create contact (201)
  PUT    /corporate/accounts/me/contacts/{id}       — update contact (200)
  POST   /corporate/accounts/me/contacts/{id}/deactivate — deactivate (200)
  DELETE /corporate/accounts/me/contacts/{id}       — hard delete (204)

Platform-admin endpoints:
  GET /admin/corporate/accounts/{account_id}/contacts         — list any account
  GET /admin/corporate/accounts/{account_id}/contacts/primary — primary contact
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_account_contact import ContactRole
from app.models.user import User
from app.schemas.corporate_account_contact import (
    ContactCreateRequest,
    ContactDeactivateResponse,
    ContactListResponse,
    ContactResponse,
    ContactUpdateRequest,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_account_contact import (
    create_contact,
    deactivate_contact,
    delete_contact,
    get_contact,
    get_primary_contact,
    list_contacts,
    update_contact,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-account-contacts"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


def _to_response(contact) -> ContactResponse:
    return ContactResponse.model_validate(contact)


# ---------------------------------------------------------------------------
# Member: list contacts
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/contacts",
    response_model=ContactListResponse,
    summary="Member: list operational contacts for my corporate account",
)
async def list_my_contacts(
    active_only: bool = Query(True, description="Only return active contacts."),
    role: Optional[ContactRole] = Query(None, description="Filter by role."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return operational contacts for the caller's corporate account.

    By default only active contacts are included.  Pass ``active_only=false``
    to include deactivated contacts.  Optionally filter by contact role.
    """
    account_id = await _resolve_account_id(db, user.id)
    contacts = await list_contacts(
        db,
        account_id=account_id,
        role=role,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return ContactListResponse(
        account_id=account_id,
        total=len(contacts),
        items=[_to_response(c) for c in contacts],
    )


# ---------------------------------------------------------------------------
# Member: get single contact
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/contacts/{contact_id}",
    response_model=ContactResponse,
    summary="Member: get a single operational contact",
)
async def get_my_contact(
    contact_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single operational contact by id for the caller's account."""
    account_id = await _resolve_account_id(db, user.id)
    contact = await get_contact(db, account_id=account_id, contact_id=contact_id)
    return _to_response(contact)


# ---------------------------------------------------------------------------
# Admin: create contact
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/contacts",
    response_model=ContactResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a new operational contact",
)
async def create_my_contact(
    data: ContactCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a new operational contact for the caller's corporate account.

    The email is normalised to lowercase.  Returns 409 if the email already
    exists on the account.  When ``is_primary`` is true any existing primary
    contact is demoted automatically.
    """
    account_id = await _resolve_account_id(db, user.id)
    contact = await create_contact(
        db,
        account_id=account_id,
        name=data.name,
        email=data.email,
        phone=data.phone,
        title=data.title,
        contact_role=data.contact_role,
        notes=data.notes,
        is_primary=data.is_primary,
        added_by_id=user.id,
    )
    await db.commit()
    return _to_response(contact)


# ---------------------------------------------------------------------------
# Admin: update contact
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/contacts/{contact_id}",
    response_model=ContactResponse,
    summary="Admin: update an operational contact",
)
async def update_my_contact(
    contact_id: int,
    data: ContactUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update an operational contact.

    Only supplied fields are changed.  Returns 409 on duplicate email and 404
    if the contact does not exist on the caller's account.
    """
    account_id = await _resolve_account_id(db, user.id)
    updates = data.model_dump(exclude_none=True)
    contact = await update_contact(
        db, account_id=account_id, contact_id=contact_id, **updates
    )
    await db.commit()
    return _to_response(contact)


# ---------------------------------------------------------------------------
# Admin: deactivate contact
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/contacts/{contact_id}/deactivate",
    response_model=ContactDeactivateResponse,
    summary="Admin: deactivate an operational contact",
)
async def deactivate_my_contact(
    contact_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete an operational contact (sets ``is_active=False``).

    The row is preserved for history.  Returns 404 if the contact does not
    exist on the caller's account.
    """
    account_id = await _resolve_account_id(db, user.id)
    contact = await deactivate_contact(db, account_id=account_id, contact_id=contact_id)
    await db.commit()
    return ContactDeactivateResponse(
        id=contact.id,
        account_id=contact.account_id,
        is_active=contact.is_active,
        message="Contact deactivated successfully.",
    )


# ---------------------------------------------------------------------------
# Admin: hard delete
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/contacts/{contact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: permanently delete an operational contact",
)
async def delete_my_contact(
    contact_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently remove an operational contact from the account.

    Returns 404 if the contact does not exist on the caller's account.
    """
    account_id = await _resolve_account_id(db, user.id)
    await delete_contact(db, account_id=account_id, contact_id=contact_id)
    await db.commit()


# ---------------------------------------------------------------------------
# Platform-admin: primary contact (must be declared before /{contact_id})
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/contacts/primary",
    response_model=Optional[ContactResponse],
    summary="Platform admin: get the primary contact for any corporate account",
)
async def platform_admin_get_primary_contact(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the primary contact for any corporate account, or null if none
    is set."""
    contact = await get_primary_contact(db, account_id=account_id)
    return _to_response(contact) if contact is not None else None


# ---------------------------------------------------------------------------
# Platform-admin: list contacts for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/contacts",
    response_model=ContactListResponse,
    summary="Platform admin: list contacts for any corporate account",
)
async def platform_admin_list_contacts(
    account_id: int,
    active_only: bool = Query(True),
    role: Optional[ContactRole] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return paginated operational contacts for any corporate account."""
    contacts = await list_contacts(
        db,
        account_id=account_id,
        role=role,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return ContactListResponse(
        account_id=account_id,
        total=len(contacts),
        items=[_to_response(c) for c in contacts],
    )
