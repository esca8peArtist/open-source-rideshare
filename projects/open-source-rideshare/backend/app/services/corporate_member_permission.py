"""Service functions for corporate member fine-grained permissions.

Enterprise accounts can grant specific named scopes to individual members
beyond the binary admin/member role.

Public API
----------
grant_permission         — grant a scope; 409 if already active;
                           re-activates if a revoked entry exists (upsert)
revoke_permission        — soft-delete (is_active=False); 404 if not active
get_permission           — fetch one entry by id; 404 if not found
list_member_permissions  — list active grants for a specific member
list_account_permissions — list all grants for an account, optional scope filter
has_permission           — fast boolean check (scope + expiry-aware)
get_members_with_scope   — list all members holding a specific scope
get_permission_summary   — counts by scope for the account dashboard
list_all_platform        — platform-admin cross-account listing
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_member_permission import (
    CorporateMemberPermission,
    PermissionScope,
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


async def _get_row(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    scope: PermissionScope,
) -> Optional[CorporateMemberPermission]:
    """Return the permission row for the (account, member, scope) triple, or None."""
    result = await db.execute(
        select(CorporateMemberPermission).where(
            CorporateMemberPermission.account_id == account_id,
            CorporateMemberPermission.member_id == member_id,
            CorporateMemberPermission.permission_scope == scope,
        )
    )
    return result.scalar_one_or_none()


def _is_currently_active(entry: CorporateMemberPermission) -> bool:
    """Return True when the entry is active and not past its expiry."""
    if not entry.is_active:
        return False
    if entry.expires_at is not None and entry.expires_at <= _now_utc():
        return False
    return True


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


async def grant_permission(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    scope: PermissionScope,
    granted_by_id: int,
    expires_at: Optional[datetime] = None,
    notes: Optional[str] = None,
) -> CorporateMemberPermission:
    """Grant *scope* to *member_id* within *account_id*.

    If a previously revoked (or expired) entry exists it is re-activated
    so that the unique constraint is respected.  Returns 409 if the
    member already holds an active, non-expired grant for this scope.
    """
    existing = await _get_row(db, account_id, member_id, scope)

    if existing is not None:
        if _is_currently_active(existing):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Member already holds an active '{scope}' permission for this account.",
            )
        # Re-activate (upsert semantics).
        existing.is_active = True
        existing.granted_by_id = granted_by_id
        existing.granted_at = _now_utc()
        existing.expires_at = expires_at
        existing.notes = notes
        await db.flush()
        return existing

    entry = CorporateMemberPermission(
        account_id=account_id,
        member_id=member_id,
        permission_scope=scope,
        granted_by_id=granted_by_id,
        expires_at=expires_at,
        is_active=True,
        notes=notes,
    )
    db.add(entry)
    await db.flush()
    return entry


async def revoke_permission(
    db: AsyncSession,
    account_id: int,
    permission_id: int,
) -> CorporateMemberPermission:
    """Revoke a permission by its primary-key id (sets is_active=False).

    Raises 404 if the entry does not exist or is already revoked.
    """
    result = await db.execute(
        select(CorporateMemberPermission).where(
            CorporateMemberPermission.id == permission_id,
            CorporateMemberPermission.account_id == account_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None or not entry.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission not found or already revoked.",
        )
    entry.is_active = False
    await db.flush()
    return entry


async def get_permission(
    db: AsyncSession,
    account_id: int,
    permission_id: int,
) -> CorporateMemberPermission:
    """Return a permission entry by id.

    Raises 404 if the entry does not exist within *account_id*.
    """
    result = await db.execute(
        select(CorporateMemberPermission).where(
            CorporateMemberPermission.id == permission_id,
            CorporateMemberPermission.account_id == account_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission entry not found.",
        )
    return entry


async def list_member_permissions(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    active_only: bool = True,
) -> list[CorporateMemberPermission]:
    """Return all permission entries for a specific member within an account."""
    query = select(CorporateMemberPermission).where(
        CorporateMemberPermission.account_id == account_id,
        CorporateMemberPermission.member_id == member_id,
    )
    if active_only:
        query = query.where(CorporateMemberPermission.is_active.is_(True))
    query = query.order_by(CorporateMemberPermission.permission_scope)
    result = await db.execute(query)
    return list(result.scalars().all())


async def list_account_permissions(
    db: AsyncSession,
    account_id: int,
    scope: Optional[PermissionScope] = None,
    active_only: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> list[CorporateMemberPermission]:
    """Return all permission entries for an account.

    Optionally filtered to a single *scope* and/or active-only entries.
    """
    query = (
        select(CorporateMemberPermission)
        .where(CorporateMemberPermission.account_id == account_id)
        .order_by(
            CorporateMemberPermission.permission_scope,
            CorporateMemberPermission.member_id,
        )
        .limit(limit)
        .offset(offset)
    )
    if scope is not None:
        query = query.where(CorporateMemberPermission.permission_scope == scope)
    if active_only:
        query = query.where(CorporateMemberPermission.is_active.is_(True))
    result = await db.execute(query)
    return list(result.scalars().all())


async def has_permission(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    scope: PermissionScope,
) -> bool:
    """Return True if *member_id* holds an active, non-expired *scope* grant.

    Designed for service-layer gate checks — returns a plain bool so
    callers can branch without catching exceptions.
    """
    entry = await _get_row(db, account_id, member_id, scope)
    return entry is not None and _is_currently_active(entry)


async def get_members_with_scope(
    db: AsyncSession,
    account_id: int,
    scope: PermissionScope,
    active_only: bool = True,
) -> list[CorporateMemberPermission]:
    """Return all entries for *scope* within *account_id*.

    Used by admin UIs to see who holds a particular scope.
    """
    query = (
        select(CorporateMemberPermission)
        .where(
            CorporateMemberPermission.account_id == account_id,
            CorporateMemberPermission.permission_scope == scope,
        )
        .order_by(CorporateMemberPermission.member_id)
    )
    if active_only:
        query = query.where(CorporateMemberPermission.is_active.is_(True))
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_permission_summary(
    db: AsyncSession, account_id: int
) -> dict:
    """Return active grant counts grouped by scope, plus a total.

    Used by the account dashboard.
    """
    rows = await db.execute(
        select(
            CorporateMemberPermission.permission_scope,
            func.count(CorporateMemberPermission.id).label("cnt"),
        )
        .where(
            CorporateMemberPermission.account_id == account_id,
            CorporateMemberPermission.is_active.is_(True),
        )
        .group_by(CorporateMemberPermission.permission_scope)
    )
    by_scope = [{"permission_scope": row[0], "active_count": row[1]} for row in rows]
    total = sum(item["active_count"] for item in by_scope)
    return {
        "account_id": account_id,
        "total_active_grants": total,
        "by_scope": by_scope,
    }


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
    scope: Optional[PermissionScope] = None,
    active_only: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> list[CorporateMemberPermission]:
    """Platform-admin: list permission entries across all accounts.

    Optionally filtered to a single account or scope.
    """
    query = (
        select(CorporateMemberPermission)
        .order_by(
            CorporateMemberPermission.account_id,
            CorporateMemberPermission.member_id,
        )
        .limit(limit)
        .offset(offset)
    )
    if account_id is not None:
        query = query.where(CorporateMemberPermission.account_id == account_id)
    if scope is not None:
        query = query.where(CorporateMemberPermission.permission_scope == scope)
    if active_only:
        query = query.where(CorporateMemberPermission.is_active.is_(True))
    result = await db.execute(query)
    return list(result.scalars().all())
