"""Corporate Admin Audit Log endpoints.

Provides admins with an immutable, searchable record of all significant
admin actions taken within their corporate account.

Member/admin endpoints (require ADMIN role within the account):
  GET /corporate/accounts/me/audit-log              — paginated list with filters
  GET /corporate/accounts/me/audit-log/{entry_id}   — single entry

Platform-admin endpoints:
  GET /admin/corporate/accounts/{account_id}/audit-log
  GET /admin/corporate/accounts/{account_id}/audit-log/{entry_id}
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_admin_audit_log import (
    AuditLogEntryResponse,
    AuditLogListResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_admin_audit_log import (
    get_audit_log_entry,
    get_audit_log_entry_platform,
    list_audit_logs,
    list_audit_logs_platform,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-admin-audit-log"])


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
# Admin: list audit log entries
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/audit-log",
    response_model=AuditLogListResponse,
    summary="Admin: list audit log entries for the account",
)
async def list_my_audit_log(
    actor_id: int | None = Query(
        None, description="Filter to actions performed by a specific user ID."
    ),
    action: str | None = Query(
        None,
        description="Filter by exact action string, e.g. 'billing_contact.create'.",
    ),
    resource_type: str | None = Query(
        None, description="Filter by resource type, e.g. 'billing_contact'."
    ),
    from_dt: datetime | None = Query(
        None, description="Only entries at or after this timestamp (ISO 8601)."
    ),
    to_dt: datetime | None = Query(
        None, description="Only entries at or before this timestamp (ISO 8601)."
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated audit log for the corporate account.

    Entries are ordered newest-first.  Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_audit_logs(
        db,
        account_id,
        user.id,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        from_dt=from_dt,
        to_dt=to_dt,
        skip=skip,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Admin: get a single audit log entry
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/audit-log/{entry_id}",
    response_model=AuditLogEntryResponse,
    summary="Admin: get a single audit log entry",
)
async def get_my_audit_log_entry(
    entry_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return details of a specific audit log entry.

    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_audit_log_entry(db, account_id, user.id, entry_id)


# ---------------------------------------------------------------------------
# Platform-admin: list audit log for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/audit-log",
    response_model=AuditLogListResponse,
    summary="Platform admin: list audit log entries for any corporate account",
)
async def platform_admin_list_audit_log(
    account_id: int,
    actor_id: int | None = Query(None),
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    from_dt: datetime | None = Query(None),
    to_dt: datetime | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return audit log entries for any corporate account.

    Requires platform-level admin role.
    """
    return await list_audit_logs_platform(
        db,
        account_id,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        from_dt=from_dt,
        to_dt=to_dt,
        skip=skip,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Platform-admin: get single entry for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/audit-log/{entry_id}",
    response_model=AuditLogEntryResponse,
    summary="Platform admin: get a single audit log entry for any corporate account",
)
async def platform_admin_get_audit_log_entry(
    account_id: int,
    entry_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a specific audit log entry for any corporate account.

    Requires platform-level admin role.
    """
    return await get_audit_log_entry_platform(db, account_id, entry_id)
