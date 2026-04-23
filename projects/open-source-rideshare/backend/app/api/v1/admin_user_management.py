"""Admin user management endpoints.

GET  /admin/users                     — paginated list of all users
GET  /admin/users/{user_id}           — detailed user profile
POST /admin/users/{user_id}/suspend   — suspend a user account
POST /admin/users/{user_id}/activate  — reactivate a suspended account

All endpoints are restricted to admin users only via the require_admin dependency.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.admin_user_management import (
    ActivateUserRequest,
    SuspendUserRequest,
    UserDetailResponse,
    UserListResponse,
    UserStatusChangeResponse,
)
from app.services.admin_user_management import (
    _AlreadyInStateError,
    activate_user,
    get_user_detail,
    list_users,
    suspend_user,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin-user-management"])


@router.get(
    "/admin/users",
    response_model=UserListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all users with filters (admin only)",
)
async def admin_list_users(
    role: str = Query("all", description="Filter by role: rider, driver, or all"),
    account_status: str = Query(
        "all",
        alias="status",
        description="Filter by account status: active, suspended, or all",
    ),
    search: str | None = Query(None, description="Case-insensitive search on name or email"),
    page: int = Query(1, ge=1, description="1-based page number"),
    page_size: int = Query(20, ge=1, le=100, description="Rows per page (max 100)"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserListResponse:
    """Return a paginated list of all riders and drivers.

    Admins are excluded from this list. Supports filtering by role and
    account status, plus a free-text search on name or email.
    """
    _validate_role_filter(role)
    _validate_status_filter(account_status)

    return await list_users(
        db=db,
        role=role,  # type: ignore[arg-type]
        status=account_status,  # type: ignore[arg-type]
        search=search,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/admin/users/{user_id}",
    response_model=UserDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get detailed user profile (admin only)",
)
async def admin_get_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserDetailResponse:
    """Return the full profile of a user, including ride statistics.

    Includes verification status, account metadata, and ride stats:
    total rides, completed, cancelled, and average rating received.
    """
    try:
        return await get_user_detail(db=db, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/admin/users/{user_id}/suspend",
    response_model=UserStatusChangeResponse,
    status_code=status.HTTP_200_OK,
    summary="Suspend a user account (admin only)",
)
async def admin_suspend_user(
    user_id: int,
    body: SuspendUserRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserStatusChangeResponse:
    """Suspend a user account.

    Sets the user's status to SUSPENDED and records the reason. Optionally
    sends an account status notification to the user.

    Returns HTTP 409 if the user is already suspended.
    """
    try:
        return await suspend_user(db=db, user_id=user_id, admin_id=admin.id, body=body)
    except _AlreadyInStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/admin/users/{user_id}/activate",
    response_model=UserStatusChangeResponse,
    status_code=status.HTTP_200_OK,
    summary="Reactivate a suspended user account (admin only)",
)
async def admin_activate_user(
    user_id: int,
    body: ActivateUserRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserStatusChangeResponse:
    """Reactivate a suspended user account.

    Sets the user's status back to ACTIVE and clears the suspension reason.
    Optionally sends an account status notification to the user.

    Returns HTTP 409 if the user is already active.
    """
    try:
        return await activate_user(db=db, user_id=user_id, admin_id=admin.id, body=body)
    except _AlreadyInStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_VALID_ROLES = {"rider", "driver", "all"}
_VALID_STATUSES = {"active", "suspended", "all"}


def _validate_role_filter(role: str) -> None:
    if role not in _VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid role filter '{role}'. Must be one of: {sorted(_VALID_ROLES)}",
        )


def _validate_status_filter(account_status: str) -> None:
    if account_status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status filter '{account_status}'. Must be one of: {sorted(_VALID_STATUSES)}",
        )
