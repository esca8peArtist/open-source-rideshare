"""Corporate Driver Blacklist endpoints.

Enterprise admins block specific drivers from being dispatched on corporate
rides for their account.  This is the inverse of the preferred driver pool.

Member endpoints (any corporate member):
  GET  /corporate/accounts/me/driver-blacklist                   — list blacklist
  GET  /corporate/accounts/me/driver-blacklist/{driver_id}       — get entry
  GET  /corporate/accounts/me/driver-blacklist/{driver_id}/check — bool check

Admin endpoints (account-admin only):
  POST   /corporate/accounts/me/driver-blacklist             — add driver (201)
  DELETE /corporate/accounts/me/driver-blacklist/{driver_id} — lift block (204)
  GET    /corporate/accounts/me/driver-blacklist/summary      — counts summary

Platform-admin endpoints:
  GET    /admin/corporate/accounts/{account_id}/driver-blacklist  — list
  DELETE /admin/corporate/accounts/{account_id}/driver-blacklist/{driver_id} — lift
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_driver_blacklist import (
    DriverBlacklistAddRequest,
    DriverBlacklistCheckResponse,
    DriverBlacklistEntryResponse,
    DriverBlacklistListResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_driver_blacklist import (
    add_driver_to_blacklist,
    get_blacklist_entry,
    get_blacklist_summary,
    is_driver_blacklisted,
    list_all_platform,
    list_blacklisted_drivers,
    remove_driver_from_blacklist,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-driver-blacklist"])


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


def _to_response(entry) -> DriverBlacklistEntryResponse:
    return DriverBlacklistEntryResponse.model_validate(entry)


# ---------------------------------------------------------------------------
# Member: list blacklist
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/driver-blacklist",
    response_model=DriverBlacklistListResponse,
    summary="Member: list blacklisted drivers for my corporate account",
)
async def list_my_driver_blacklist(
    active_only: bool = Query(True, description="Only return active blacklist entries."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the driver blacklist for the caller's corporate account.

    By default only active entries are included.  Pass ``active_only=false``
    to see previously lifted blocks (audit view).
    """
    account_id = await _resolve_account_id(db, user.id)
    entries = await list_blacklisted_drivers(
        db,
        account_id=account_id,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return DriverBlacklistListResponse(
        account_id=account_id,
        total=len(entries),
        items=[_to_response(e) for e in entries],
    )


# ---------------------------------------------------------------------------
# Admin: add driver to blacklist — declared before /{driver_id} paths
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/driver-blacklist",
    response_model=DriverBlacklistEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: blacklist a driver for my corporate account",
)
async def add_to_my_driver_blacklist(
    data: DriverBlacklistAddRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a driver to the blacklist for the caller's corporate account.

    Returns 409 if the driver is already actively blacklisted.  If a
    previously lifted entry exists it is re-activated (upsert semantics).
    """
    account_id = await _resolve_account_id(db, user.id)
    entry = await add_driver_to_blacklist(
        db,
        account_id=account_id,
        driver_id=data.driver_id,
        blacklisted_by_id=user.id,
        reason=data.reason,
    )
    await db.commit()
    return _to_response(entry)


# ---------------------------------------------------------------------------
# Member: get summary — declared BEFORE /{driver_id} to avoid path collision
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/driver-blacklist/summary",
    summary="Admin: get blacklist counts summary for my account",
)
async def get_my_blacklist_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return active and total blacklist entry counts for the caller's account."""
    account_id = await _resolve_account_id(db, user.id)
    return await get_blacklist_summary(db, account_id=account_id)


# ---------------------------------------------------------------------------
# Member: boolean check — declared BEFORE /{driver_id} to avoid path collision
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/driver-blacklist/{driver_id}/check",
    response_model=DriverBlacklistCheckResponse,
    summary="Member: check whether a specific driver is blacklisted",
)
async def check_driver_blacklisted(
    driver_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a simple boolean indicating whether *driver_id* is blacklisted
    for the caller's corporate account.

    Never raises 404 — returns ``is_blacklisted: false`` when the driver is
    not in the blacklist.  Intended for client-side UI hints and the
    matching engine gate check.
    """
    account_id = await _resolve_account_id(db, user.id)
    blacklisted = await is_driver_blacklisted(
        db, account_id=account_id, driver_id=driver_id
    )
    return DriverBlacklistCheckResponse(
        account_id=account_id,
        driver_id=driver_id,
        is_blacklisted=blacklisted,
    )


# ---------------------------------------------------------------------------
# Member: get single blacklist entry
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/driver-blacklist/{driver_id}",
    response_model=DriverBlacklistEntryResponse,
    summary="Member: get a single blacklist entry",
)
async def get_my_blacklist_entry(
    driver_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the blacklist entry for a specific driver in the caller's account.

    Raises 404 if the driver is not actively blacklisted.
    """
    account_id = await _resolve_account_id(db, user.id)
    entry = await get_blacklist_entry(db, account_id=account_id, driver_id=driver_id)
    return _to_response(entry)


# ---------------------------------------------------------------------------
# Admin: lift blacklist (remove driver)
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/driver-blacklist/{driver_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: lift the blacklist on a driver",
)
async def remove_from_my_driver_blacklist(
    driver_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lift the blacklist on a driver (soft-delete: is_active=False).

    Raises 404 if the driver is not actively blacklisted for this account.
    """
    account_id = await _resolve_account_id(db, user.id)
    await remove_driver_from_blacklist(
        db, account_id=account_id, driver_id=driver_id
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Platform-admin: list blacklist for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/driver-blacklist",
    response_model=DriverBlacklistListResponse,
    summary="Platform admin: list blacklisted drivers for any corporate account",
)
async def platform_admin_list_driver_blacklist(
    account_id: int,
    active_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the driver blacklist for any corporate account."""
    entries = await list_blacklisted_drivers(
        db,
        account_id=account_id,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return DriverBlacklistListResponse(
        account_id=account_id,
        total=len(entries),
        items=[_to_response(e) for e in entries],
    )


# ---------------------------------------------------------------------------
# Platform-admin: lift blacklist for any account
# ---------------------------------------------------------------------------


@router.delete(
    "/admin/corporate/accounts/{account_id}/driver-blacklist/{driver_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Platform admin: lift the blacklist on a driver for any corporate account",
)
async def platform_admin_remove_from_blacklist(
    account_id: int,
    driver_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Lift the blacklist on a driver for any corporate account.

    Raises 404 if the driver is not actively blacklisted for the account.
    """
    await remove_driver_from_blacklist(
        db, account_id=account_id, driver_id=driver_id
    )
    await db.commit()
