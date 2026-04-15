"""Service functions for the corporate preferred driver pool.

Enterprise accounts maintain a pool of preferred, vetted drivers.  When
corporate rides are dispatched the matching engine can query
``is_driver_preferred`` to surface pool members first — giving companies
continuity and quality assurance over employee travel.

Public API
----------
add_driver_to_pool       — add a driver; 409 if already active in the pool;
                           re-activates if a deactivated entry already exists
remove_driver_from_pool  — soft-delete (is_active=False); 404 if not found
get_pool_entry           — fetch one entry by driver_id within an account; 404
list_pool_drivers        — paginated list of preferred drivers
is_driver_preferred      — fast boolean check for the matching engine
get_driver_pool_stats    — driver-facing: count of accounts that prefer them
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_driver_pool import CorporateDriverPool


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _get_entry_by_driver(
    db: AsyncSession, account_id: int, driver_id: int
) -> Optional[CorporateDriverPool]:
    """Return the pool entry for *driver_id* within *account_id*, or None."""
    result = await db.execute(
        select(CorporateDriverPool).where(
            CorporateDriverPool.account_id == account_id,
            CorporateDriverPool.driver_id == driver_id,
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


async def add_driver_to_pool(
    db: AsyncSession,
    account_id: int,
    driver_id: int,
    added_by_id: int,
    notes: Optional[str] = None,
) -> CorporateDriverPool:
    """Add *driver_id* to the preferred pool for *account_id*.

    If a deactivated entry already exists it is re-activated (upsert
    semantics) so that the account_id/driver_id unique constraint is
    respected.  Returns 409 if the driver is already an active pool member.
    """
    existing = await _get_entry_by_driver(db, account_id, driver_id)

    if existing is not None:
        if existing.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This driver is already in the preferred pool for this account.",
            )
        # Re-activate a previously removed entry.
        existing.is_active = True
        existing.notes = notes
        existing.added_by_id = added_by_id
        await db.flush()
        return existing

    entry = CorporateDriverPool(
        account_id=account_id,
        driver_id=driver_id,
        is_active=True,
        notes=notes,
        added_by_id=added_by_id,
    )
    db.add(entry)
    await db.flush()
    return entry


async def remove_driver_from_pool(
    db: AsyncSession, account_id: int, driver_id: int
) -> CorporateDriverPool:
    """Soft-delete the pool entry for *driver_id* (sets is_active=False).

    Raises 404 if the driver is not an active pool member.
    """
    entry = await _get_entry_by_driver(db, account_id, driver_id)
    if entry is None or not entry.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver is not in the preferred pool for this account.",
        )
    entry.is_active = False
    await db.flush()
    return entry


async def get_pool_entry(
    db: AsyncSession, account_id: int, driver_id: int
) -> CorporateDriverPool:
    """Return the pool entry for *driver_id* within *account_id*.

    Raises 404 if the driver has never been added or has been removed.
    Only returns active entries; inactive entries are treated as not-present.
    """
    entry = await _get_entry_by_driver(db, account_id, driver_id)
    if entry is None or not entry.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver is not in the preferred pool for this account.",
        )
    return entry


async def list_pool_drivers(
    db: AsyncSession,
    account_id: int,
    active_only: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[CorporateDriverPool]:
    """Return paginated preferred driver pool entries for *account_id*.

    By default only active entries are included.  Pass *active_only=False*
    to include previously removed drivers (useful for audit views).
    """
    query = (
        select(CorporateDriverPool)
        .where(CorporateDriverPool.account_id == account_id)
        .order_by(CorporateDriverPool.added_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if active_only:
        query = query.where(CorporateDriverPool.is_active.is_(True))

    result = await db.execute(query)
    return list(result.scalars().all())


async def is_driver_preferred(
    db: AsyncSession, account_id: int, driver_id: int
) -> bool:
    """Return True if *driver_id* is an active preferred driver for *account_id*.

    Designed for use by the matching engine — returns a plain bool rather
    than raising exceptions so call sites can use it as a simple flag.
    """
    entry = await _get_entry_by_driver(db, account_id, driver_id)
    return entry is not None and entry.is_active


async def get_driver_pool_stats(
    db: AsyncSession, driver_id: int
) -> int:
    """Return the number of corporate accounts that currently prefer *driver_id*.

    Used by the driver-facing endpoint so drivers can see their pool standing
    across the platform without exposing which specific accounts prefer them.
    """
    result = await db.execute(
        select(func.count(CorporateDriverPool.id)).where(
            CorporateDriverPool.driver_id == driver_id,
            CorporateDriverPool.is_active.is_(True),
        )
    )
    return result.scalar_one() or 0
