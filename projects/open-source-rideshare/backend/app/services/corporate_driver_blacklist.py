"""Service functions for the corporate driver blacklist.

Enterprise accounts can block specific drivers from being dispatched on
their corporate rides.  This is the inverse of the preferred driver pool.

Public API
----------
add_driver_to_blacklist      — add a driver; 409 if already active;
                               re-activates if a deactivated entry exists
remove_driver_from_blacklist — soft-delete (is_active=False); 404 if not found
get_blacklist_entry          — fetch one entry by driver_id; 404 if not active
list_blacklisted_drivers     — paginated list with active_only filter
is_driver_blacklisted        — fast boolean check for the matching engine
list_all_platform            — platform-admin cross-account listing
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_driver_blacklist import CorporateDriverBlacklist


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _get_entry_by_driver(
    db: AsyncSession, account_id: int, driver_id: int
) -> Optional[CorporateDriverBlacklist]:
    """Return the blacklist entry for *driver_id* within *account_id*, or None."""
    result = await db.execute(
        select(CorporateDriverBlacklist).where(
            CorporateDriverBlacklist.account_id == account_id,
            CorporateDriverBlacklist.driver_id == driver_id,
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


async def add_driver_to_blacklist(
    db: AsyncSession,
    account_id: int,
    driver_id: int,
    blacklisted_by_id: int,
    reason: Optional[str] = None,
) -> CorporateDriverBlacklist:
    """Add *driver_id* to the blacklist for *account_id*.

    If a deactivated entry already exists it is re-activated (upsert
    semantics) so that the account_id/driver_id unique constraint is
    respected.  Returns 409 if the driver is already actively blacklisted.
    """
    existing = await _get_entry_by_driver(db, account_id, driver_id)

    if existing is not None:
        if existing.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This driver is already blacklisted for this account.",
            )
        # Re-activate a previously lifted entry.
        existing.is_active = True
        existing.reason = reason
        existing.blacklisted_by_id = blacklisted_by_id
        await db.flush()
        return existing

    entry = CorporateDriverBlacklist(
        account_id=account_id,
        driver_id=driver_id,
        is_active=True,
        reason=reason,
        blacklisted_by_id=blacklisted_by_id,
    )
    db.add(entry)
    await db.flush()
    return entry


async def remove_driver_from_blacklist(
    db: AsyncSession, account_id: int, driver_id: int
) -> CorporateDriverBlacklist:
    """Lift the blacklist for *driver_id* (sets is_active=False).

    Raises 404 if the driver is not actively blacklisted for this account.
    """
    entry = await _get_entry_by_driver(db, account_id, driver_id)
    if entry is None or not entry.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver is not blacklisted for this account.",
        )
    entry.is_active = False
    await db.flush()
    return entry


async def get_blacklist_entry(
    db: AsyncSession, account_id: int, driver_id: int
) -> CorporateDriverBlacklist:
    """Return the blacklist entry for *driver_id* within *account_id*.

    Raises 404 if the driver is not actively blacklisted.
    """
    entry = await _get_entry_by_driver(db, account_id, driver_id)
    if entry is None or not entry.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver is not blacklisted for this account.",
        )
    return entry


async def list_blacklisted_drivers(
    db: AsyncSession,
    account_id: int,
    active_only: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[CorporateDriverBlacklist]:
    """Return paginated blacklist entries for *account_id*.

    By default only active entries are included.  Pass *active_only=False*
    to include previously lifted entries (useful for audit views).
    """
    query = (
        select(CorporateDriverBlacklist)
        .where(CorporateDriverBlacklist.account_id == account_id)
        .order_by(CorporateDriverBlacklist.blacklisted_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if active_only:
        query = query.where(CorporateDriverBlacklist.is_active.is_(True))

    result = await db.execute(query)
    return list(result.scalars().all())


async def is_driver_blacklisted(
    db: AsyncSession, account_id: int, driver_id: int
) -> bool:
    """Return True if *driver_id* is actively blacklisted for *account_id*.

    Designed for use by the matching engine — returns a plain bool rather
    than raising exceptions so call sites can use it as a simple flag.
    """
    entry = await _get_entry_by_driver(db, account_id, driver_id)
    return entry is not None and entry.is_active


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
    active_only: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[CorporateDriverBlacklist]:
    """Platform-admin: list blacklist entries across all accounts.

    Optionally filtered to a single account by *account_id*.
    """
    query = (
        select(CorporateDriverBlacklist)
        .order_by(CorporateDriverBlacklist.blacklisted_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if account_id is not None:
        query = query.where(CorporateDriverBlacklist.account_id == account_id)
    if active_only:
        query = query.where(CorporateDriverBlacklist.is_active.is_(True))

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_blacklist_summary(
    db: AsyncSession, account_id: int
) -> dict:
    """Return a summary count of active and total blacklist entries.

    Used by admin dashboards to show how many drivers are currently blocked.
    """
    total_result = await db.execute(
        select(func.count(CorporateDriverBlacklist.id)).where(
            CorporateDriverBlacklist.account_id == account_id,
        )
    )
    active_result = await db.execute(
        select(func.count(CorporateDriverBlacklist.id)).where(
            CorporateDriverBlacklist.account_id == account_id,
            CorporateDriverBlacklist.is_active.is_(True),
        )
    )
    total = total_result.scalar_one() or 0
    active = active_result.scalar_one() or 0
    return {
        "account_id": account_id,
        "active_blacklisted_count": active,
        "total_entries": total,
    }
