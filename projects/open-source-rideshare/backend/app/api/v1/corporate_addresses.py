"""Corporate Address Book endpoints.

Enterprise admins maintain a shared library of named locations that employees
browse and select when booking rides.  Each address can auto-tag rides with a
default cost center and trip purpose.

Member endpoints (any active account member):
  GET  /corporate/accounts/me/addresses          — list (active_only, skip, limit)
  GET  /corporate/accounts/me/addresses/search   — keyword search
  GET  /corporate/accounts/me/addresses/{id}     — get one

Admin endpoints (require ADMIN role within the account):
  POST   /corporate/accounts/me/addresses               — create
  PATCH  /corporate/accounts/me/addresses/{id}          — update
  DELETE /corporate/accounts/me/addresses/{id}/deactivate — soft-delete
  DELETE /corporate/accounts/me/addresses/{id}          — hard-delete

Platform-admin endpoints:
  GET /admin/corporate/accounts/{account_id}/addresses          — list all
  GET /admin/corporate/accounts/{account_id}/addresses/{addr_id} — get one
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_address import (
    CorporateAddressCreate,
    CorporateAddressListResponse,
    CorporateAddressResponse,
    CorporateAddressUpdate,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_address import (
    create_corporate_address,
    delete_corporate_address,
    deactivate_corporate_address,
    get_corporate_address,
    list_all_corporate_addresses,
    list_corporate_addresses,
    search_corporate_addresses,
    update_corporate_address,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-addresses"])


# ---------------------------------------------------------------------------
# Member endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/addresses/search",
    response_model=CorporateAddressListResponse,
    summary="Search corporate address book",
)
async def search_addresses(
    q: str = Query(..., min_length=1, description="Keyword to search in name, city, or street"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search the corporate address book by name, city, or street address."""
    account = await get_user_account(db, current_user.id)
    return await search_corporate_addresses(
        db, account.id, current_user.id, q, skip=skip, limit=limit
    )


@router.get(
    "/corporate/accounts/me/addresses",
    response_model=CorporateAddressListResponse,
    summary="List corporate address book",
)
async def list_addresses(
    active_only: bool = Query(True),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all addresses in the corporate address book."""
    account = await get_user_account(db, current_user.id)
    return await list_corporate_addresses(
        db, account.id, current_user.id, active_only=active_only, skip=skip, limit=limit
    )


@router.get(
    "/corporate/accounts/me/addresses/{address_id}",
    response_model=CorporateAddressResponse,
    summary="Get a corporate address",
)
async def get_address(
    address_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve a single address from the corporate address book."""
    account = await get_user_account(db, current_user.id)
    return await get_corporate_address(db, account.id, address_id, current_user.id)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/addresses",
    response_model=CorporateAddressResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add address to corporate address book (admin)",
)
async def create_address(
    data: CorporateAddressCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a new named location to the corporate address book."""
    account = await get_user_account(db, current_user.id)
    return await create_corporate_address(db, account.id, current_user.id, data)


@router.patch(
    "/corporate/accounts/me/addresses/{address_id}",
    response_model=CorporateAddressResponse,
    summary="Update a corporate address (admin)",
)
async def update_address(
    address_id: int,
    data: CorporateAddressUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Partially update a named location in the corporate address book."""
    account = await get_user_account(db, current_user.id)
    return await update_corporate_address(
        db, account.id, address_id, current_user.id, data
    )


@router.delete(
    "/corporate/accounts/me/addresses/{address_id}/deactivate",
    response_model=CorporateAddressResponse,
    summary="Deactivate a corporate address (admin)",
)
async def deactivate_address(
    address_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Soft-delete a corporate address — hidden from employees but retained in records."""
    account = await get_user_account(db, current_user.id)
    return await deactivate_corporate_address(
        db, account.id, address_id, current_user.id
    )


@router.delete(
    "/corporate/accounts/me/addresses/{address_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a corporate address (admin)",
)
async def delete_address(
    address_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Hard-delete a corporate address from the address book."""
    account = await get_user_account(db, current_user.id)
    await delete_corporate_address(db, account.id, address_id, current_user.id)


# ---------------------------------------------------------------------------
# Platform-admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/addresses",
    response_model=CorporateAddressListResponse,
    summary="[Platform-admin] List all addresses for a corporate account",
)
async def admin_list_addresses(
    account_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Platform-admin: list all addresses (active and inactive) for a corporate account."""
    return await list_all_corporate_addresses(db, account_id, skip=skip, limit=limit)


@router.get(
    "/admin/corporate/accounts/{account_id}/addresses/{address_id}",
    response_model=CorporateAddressResponse,
    summary="[Platform-admin] Get a corporate address",
)
async def admin_get_address(
    account_id: int,
    address_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Platform-admin: retrieve a specific corporate address by ID."""
    from app.services.corporate_address import _get_address_or_404
    addr = await _get_address_or_404(db, account_id, address_id)
    return CorporateAddressResponse.model_validate(addr)
