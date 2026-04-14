"""Service layer for the user blocklist feature.

Both riders and drivers can block each other. Blocks are directional:
  blocker_id → blocked_id

The matching engine calls `get_blocked_user_ids` and `get_blocker_user_ids`
to exclude blocked parties from candidate lists — both directions are checked
so either side can prevent future contact.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blocklist import MAX_BLOCKLIST_SIZE, UserBlocklist

DEFAULT_PAGE_SIZE = 20


async def block_user(
    blocker_id: int,
    blocked_user_id: int,
    db: AsyncSession,
    reason: str | None = None,
) -> UserBlocklist:
    """Add a block from blocker → blocked_user_id.

    Raises
    ------
    ValueError
        If blocked_user_id == blocker_id (cannot block yourself).
        If the pair already exists.
        If the blocker already has MAX_BLOCKLIST_SIZE entries.
    """
    if blocker_id == blocked_user_id:
        raise ValueError("You cannot block yourself")

    # Check for existing block
    existing = await db.execute(
        select(UserBlocklist).where(
            UserBlocklist.blocker_id == blocker_id,
            UserBlocklist.blocked_id == blocked_user_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError("User is already blocked")

    # Enforce per-user limit
    count_result = await db.execute(
        select(UserBlocklist).where(UserBlocklist.blocker_id == blocker_id)
    )
    current_count = len(count_result.scalars().all())
    if current_count >= MAX_BLOCKLIST_SIZE:
        raise ValueError(f"Blocklist limit of {MAX_BLOCKLIST_SIZE} reached")

    entry = UserBlocklist(
        blocker_id=blocker_id,
        blocked_id=blocked_user_id,
        reason=reason,
    )
    db.add(entry)
    await db.flush()
    return entry


async def unblock_user(
    blocker_id: int,
    blocked_user_id: int,
    db: AsyncSession,
) -> bool:
    """Remove a block. Returns True if a row was deleted, False if not found."""
    result = await db.execute(
        delete(UserBlocklist).where(
            UserBlocklist.blocker_id == blocker_id,
            UserBlocklist.blocked_id == blocked_user_id,
        )
    )
    return result.rowcount > 0


async def list_blocklist(
    blocker_id: int,
    db: AsyncSession,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_SIZE,
) -> list[UserBlocklist]:
    """Return the paginated list of users that blocker_id has blocked."""
    result = await db.execute(
        select(UserBlocklist)
        .where(UserBlocklist.blocker_id == blocker_id)
        .order_by(UserBlocklist.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_block_entry(
    blocker_id: int,
    blocked_user_id: int,
    db: AsyncSession,
) -> UserBlocklist | None:
    """Return the block entry if it exists, otherwise None."""
    result = await db.execute(
        select(UserBlocklist).where(
            UserBlocklist.blocker_id == blocker_id,
            UserBlocklist.blocked_id == blocked_user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_blocked_user_ids(blocker_id: int, db: AsyncSession) -> set[int]:
    """Return the set of user IDs that blocker_id has blocked."""
    result = await db.execute(
        select(UserBlocklist.blocked_id).where(UserBlocklist.blocker_id == blocker_id)
    )
    return set(result.scalars().all())


async def get_blocker_user_ids(blocked_id: int, db: AsyncSession) -> set[int]:
    """Return the set of user IDs that have blocked blocked_id.

    Used by the matching engine to exclude drivers who have blocked a given rider.
    """
    result = await db.execute(
        select(UserBlocklist.blocker_id).where(UserBlocklist.blocked_id == blocked_id)
    )
    return set(result.scalars().all())


async def list_all_blocks(
    db: AsyncSession,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_SIZE,
) -> list[UserBlocklist]:
    """Admin: return all block entries, newest first."""
    result = await db.execute(
        select(UserBlocklist)
        .order_by(UserBlocklist.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())
