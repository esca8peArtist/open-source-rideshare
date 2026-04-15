"""Service layer for the Corporate Admin Audit Log.

Every significant admin action within a corporate account is recorded here for
compliance (SOX, SOC2, internal audit).  Entries are append-only — never
modified or deleted.

Public surface
--------------
log_action(db, account_id, actor_id, action, resource_type, resource_id, details)
    Internal helper — called by other service layers.  No auth check.

list_audit_logs(db, account_id, user_id, *, actor_id, action, resource_type,
                from_dt, to_dt, skip, limit)
    Admin-only paginated list with filters.

get_audit_log_entry(db, account_id, user_id, entry_id)
    Admin-only single-entry lookup.

list_audit_logs_platform(db, account_id, *, actor_id, action, resource_type,
                          from_dt, to_dt, skip, limit)
    Platform-admin variant — no member auth check.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_admin_audit_log import CorporateAdminAuditLog
from app.schemas.corporate_admin_audit_log import (
    AuditLogEntryResponse,
    AuditLogListResponse,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _require_admin(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> BusinessAccountMember:
    """Return the member row or raise HTTP 403 if not an account admin."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.role == MemberRole.ADMIN,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have admin access to this corporate account.",
        )
    return member


async def _get_entry(
    db: AsyncSession,
    account_id: int,
    entry_id: int,
) -> CorporateAdminAuditLog:
    """Return the log entry or raise HTTP 404."""
    result = await db.execute(
        select(CorporateAdminAuditLog).where(
            CorporateAdminAuditLog.id == entry_id,
            CorporateAdminAuditLog.account_id == account_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audit log entry not found in this account.",
        )
    return entry


def _entry_to_response(entry: CorporateAdminAuditLog) -> AuditLogEntryResponse:
    from datetime import timezone

    now = datetime.now(timezone.utc)
    return AuditLogEntryResponse(
        id=entry.id,
        account_id=entry.account_id,
        actor_id=entry.actor_id,
        action=entry.action,
        resource_type=entry.resource_type,
        resource_id=entry.resource_id,
        details=entry.details,
        created_at=entry.created_at or now,
    )


def _build_filtered_query(
    account_id: int,
    actor_id: int | None,
    action: str | None,
    resource_type: str | None,
    from_dt: datetime | None,
    to_dt: datetime | None,
):
    """Return a base SELECT with all optional filters applied."""
    q = select(CorporateAdminAuditLog).where(
        CorporateAdminAuditLog.account_id == account_id
    )
    if actor_id is not None:
        q = q.where(CorporateAdminAuditLog.actor_id == actor_id)
    if action is not None:
        q = q.where(CorporateAdminAuditLog.action == action)
    if resource_type is not None:
        q = q.where(CorporateAdminAuditLog.resource_type == resource_type)
    if from_dt is not None:
        q = q.where(CorporateAdminAuditLog.created_at >= from_dt)
    if to_dt is not None:
        q = q.where(CorporateAdminAuditLog.created_at <= to_dt)
    return q


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


async def log_action(
    db: AsyncSession,
    account_id: int,
    actor_id: int | None,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any] | None = None,
) -> CorporateAdminAuditLog:
    """Append an immutable audit log entry for an admin action.

    This is an internal helper intended to be called from other service
    functions (e.g. after approving an expense report).  It does NOT commit —
    the caller's transaction is responsible for the commit.

    Args:
        db: Database session.
        account_id: Corporate account the action belongs to.
        actor_id: ID of the admin who performed the action (None = system).
        action: Dot-namespaced action string, e.g. ``"billing_contact.create"``.
        resource_type: Resource category, e.g. ``"billing_contact"``.
        resource_id: Flexible identifier for the affected resource.
        details: Optional extra context (before/after state, notes, etc.).

    Returns:
        The newly created CorporateAdminAuditLog row (not yet committed).
    """
    entry = CorporateAdminAuditLog(
        account_id=account_id,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
    )
    db.add(entry)
    await db.flush()
    return entry


async def list_audit_logs(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    *,
    actor_id: int | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    skip: int = 0,
    limit: int = 50,
) -> AuditLogListResponse:
    """Return a paginated, filtered list of audit log entries (admin only).

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        user_id: ID of the requesting admin.
        actor_id: Optional filter — only entries by this user.
        action: Optional filter — only entries with this exact action string.
        resource_type: Optional filter — only entries for this resource type.
        from_dt: Optional lower bound for created_at.
        to_dt: Optional upper bound for created_at.
        skip: Pagination offset.
        limit: Maximum rows to return.

    Returns:
        AuditLogListResponse with total count and page of entries.

    Raises:
        HTTP 403: When the requesting user is not an account admin.
    """
    await _require_admin(db, account_id, user_id)

    q = _build_filtered_query(account_id, actor_id, action, resource_type, from_dt, to_dt)

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar_one() or 0

    page_result = await db.execute(
        q.order_by(CorporateAdminAuditLog.created_at.desc()).offset(skip).limit(limit)
    )
    entries: Sequence[CorporateAdminAuditLog] = page_result.scalars().all()

    return AuditLogListResponse(
        account_id=account_id,
        total=total,
        entries=[_entry_to_response(e) for e in entries],
    )


async def get_audit_log_entry(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    entry_id: int,
) -> AuditLogEntryResponse:
    """Return a single audit log entry (admin only).

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        user_id: ID of the requesting admin.
        entry_id: Audit log entry identifier.

    Returns:
        AuditLogEntryResponse.

    Raises:
        HTTP 403: When the requesting user is not an account admin.
        HTTP 404: When the entry is not found in this account.
    """
    await _require_admin(db, account_id, user_id)
    entry = await _get_entry(db, account_id, entry_id)
    return _entry_to_response(entry)


async def list_audit_logs_platform(
    db: AsyncSession,
    account_id: int,
    *,
    actor_id: int | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    skip: int = 0,
    limit: int = 50,
) -> AuditLogListResponse:
    """Platform-admin variant of list_audit_logs — no member auth check.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        actor_id: Optional filter — only entries by this user.
        action: Optional filter — only entries with this exact action string.
        resource_type: Optional filter — only entries for this resource type.
        from_dt: Optional lower bound for created_at.
        to_dt: Optional upper bound for created_at.
        skip: Pagination offset.
        limit: Maximum rows to return.

    Returns:
        AuditLogListResponse with total count and page of entries.
    """
    q = _build_filtered_query(account_id, actor_id, action, resource_type, from_dt, to_dt)

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar_one() or 0

    page_result = await db.execute(
        q.order_by(CorporateAdminAuditLog.created_at.desc()).offset(skip).limit(limit)
    )
    entries: Sequence[CorporateAdminAuditLog] = page_result.scalars().all()

    return AuditLogListResponse(
        account_id=account_id,
        total=total,
        entries=[_entry_to_response(e) for e in entries],
    )


async def get_audit_log_entry_platform(
    db: AsyncSession,
    account_id: int,
    entry_id: int,
) -> AuditLogEntryResponse:
    """Platform-admin variant of get_audit_log_entry — no member auth check.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        entry_id: Audit log entry identifier.

    Returns:
        AuditLogEntryResponse.

    Raises:
        HTTP 404: When the entry is not found in this account.
    """
    entry = await _get_entry(db, account_id, entry_id)
    return _entry_to_response(entry)
