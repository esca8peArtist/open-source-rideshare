"""Corporate Preferred Driver Pool endpoints.

Enterprise admins curate a pool of preferred, vetted drivers for their
corporate account.  The matching engine surfaces pool members first when
dispatching corporate rides — giving companies continuity and quality
assurance over employee travel.

Member endpoints (any corporate member):
  GET  /corporate/accounts/me/driver-pool               — list pool
  GET  /corporate/accounts/me/driver-pool/{driver_id}   — get entry
  GET  /corporate/accounts/me/driver-pool/{driver_id}/check — bool check

Admin endpoints (account-admin only):
  POST   /corporate/accounts/me/driver-pool             — add driver (201)
  DELETE /corporate/accounts/me/driver-pool/{driver_id} — remove driver (204)

Driver endpoint:
  GET /drivers/me/pool-stats — driver: count of accounts that prefer them

Platform-admin endpoints:
  GET    /admin/corporate/accounts/{account_id}/driver-pool            — list
  DELETE /admin/corporate/accounts/{account_id}/driver-pool/{driver_id} — remove
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_driver_pool import (
    DriverPoolAddRequest,
    DriverPoolCheckResponse,
    DriverPoolEntryResponse,
    DriverPoolListResponse,
    DriverPoolStatsResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_driver_pool import (
    add_driver_to_pool,
    get_driver_pool_stats,
    get_pool_entry,
    is_driver_preferred,
    list_pool_drivers,
    remove_driver_from_pool,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-driver-pool"])


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


def _to_response(entry) -> DriverPoolEntryResponse:
    return DriverPoolEntryResponse.model_validate(entry)


# ---------------------------------------------------------------------------
# Member: list pool
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/driver-pool",
    response_model=DriverPoolListResponse,
    summary="Member: list preferred drivers for my corporate account",
)
async def list_my_driver_pool(
    active_only: bool = Query(True, description="Only return active pool entries."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the preferred driver pool for the caller's corporate account.

    By default only active entries are included.  Pass ``active_only=false``
    to see previously removed drivers (audit view).
    """
    account_id = await _resolve_account_id(db, user.id)
    entries = await list_pool_drivers(
        db,
        account_id=account_id,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return DriverPoolListResponse(
        account_id=account_id,
        total=len(entries),
        items=[_to_response(e) for e in entries],
    )


# ---------------------------------------------------------------------------
# Admin: add driver to pool — declared before /{driver_id} paths
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/driver-pool",
    response_model=DriverPoolEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: add a driver to the preferred pool",
)
async def add_to_my_driver_pool(
    data: DriverPoolAddRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a driver to the preferred pool for the caller's corporate account.

    Returns 409 if the driver is already an active pool member.  If a
    previously removed entry exists it is re-activated instead of creating
    a duplicate row.
    """
    account_id = await _resolve_account_id(db, user.id)
    entry = await add_driver_to_pool(
        db,
        account_id=account_id,
        driver_id=data.driver_id,
        added_by_id=user.id,
        notes=data.notes,
    )
    await db.commit()
    return _to_response(entry)


# ---------------------------------------------------------------------------
# Member: boolean preferred check — declared BEFORE /{driver_id} to avoid
# FastAPI treating "check" as a driver_id path parameter
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/driver-pool/{driver_id}/check",
    response_model=DriverPoolCheckResponse,
    summary="Member: check whether a specific driver is preferred",
)
async def check_driver_preferred(
    driver_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a simple boolean indicating whether *driver_id* is in the
    preferred pool for the caller's corporate account.

    Intended for client-side UI hints (e.g. showing a 'preferred' badge on
    a driver card).  Never raises 404 — returns ``is_preferred: false``
    when the driver is not in the pool.
    """
    account_id = await _resolve_account_id(db, user.id)
    preferred = await is_driver_preferred(db, account_id=account_id, driver_id=driver_id)
    return DriverPoolCheckResponse(
        account_id=account_id,
        driver_id=driver_id,
        is_preferred=preferred,
    )


# ---------------------------------------------------------------------------
# Member: get single pool entry
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/driver-pool/{driver_id}",
    response_model=DriverPoolEntryResponse,
    summary="Member: get a single preferred driver pool entry",
)
async def get_my_pool_entry(
    driver_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the pool entry for a specific driver in the caller's account.

    Raises 404 if the driver is not an active pool member.
    """
    account_id = await _resolve_account_id(db, user.id)
    entry = await get_pool_entry(db, account_id=account_id, driver_id=driver_id)
    return _to_response(entry)


# ---------------------------------------------------------------------------
# Admin: remove driver from pool
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/driver-pool/{driver_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: remove a driver from the preferred pool",
)
async def remove_from_my_driver_pool(
    driver_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a driver from the preferred pool (soft-delete: is_active=False).

    Raises 404 if the driver is not an active pool member.
    """
    account_id = await _resolve_account_id(db, user.id)
    await remove_driver_from_pool(db, account_id=account_id, driver_id=driver_id)
    await db.commit()


# ---------------------------------------------------------------------------
# Driver: pool stats
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/pool-stats",
    response_model=DriverPoolStatsResponse,
    summary="Driver: see how many corporate accounts currently prefer you",
)
async def get_my_pool_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the count of active corporate accounts that have added this driver
    to their preferred pool.

    The identity of those accounts is not disclosed — only the aggregate count.
    Drivers can use this to gauge their corporate standing on the platform.
    """
    # Resolve driver profile id from user id.
    from sqlalchemy import select as sa_select
    from app.models.driver import DriverProfile

    result = await db.execute(
        sa_select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    driver = result.scalar_one_or_none()
    if driver is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found.",
        )

    count = await get_driver_pool_stats(db, driver_id=driver.id)
    return DriverPoolStatsResponse(
        driver_id=driver.id,
        preferred_by_account_count=count,
    )


# ---------------------------------------------------------------------------
# Platform-admin: list pool for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/driver-pool",
    response_model=DriverPoolListResponse,
    summary="Platform admin: list preferred drivers for any corporate account",
)
async def platform_admin_list_driver_pool(
    account_id: int,
    active_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the preferred driver pool for any corporate account."""
    entries = await list_pool_drivers(
        db,
        account_id=account_id,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return DriverPoolListResponse(
        account_id=account_id,
        total=len(entries),
        items=[_to_response(e) for e in entries],
    )


# ---------------------------------------------------------------------------
# Platform-admin: remove driver from any account's pool
# ---------------------------------------------------------------------------


@router.delete(
    "/admin/corporate/accounts/{account_id}/driver-pool/{driver_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Platform admin: remove a driver from any corporate account's preferred pool",
)
async def platform_admin_remove_from_pool(
    account_id: int,
    driver_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a pool entry for any corporate account.

    Raises 404 if the driver is not an active pool member of the account.
    """
    await remove_driver_from_pool(db, account_id=account_id, driver_id=driver_id)
    await db.commit()
