"""Corporate Shuttle Pass endpoints.

Enterprise accounts define shuttle pass types and issue pre-paid passes to
employees.  Employees redeem passes when booking shuttle seats; each redemption
is recorded in an append-only usage ledger.

Member endpoints (any authenticated account member):
  GET  /api/v1/corporate/{account_id}/shuttle/pass-types
                                            — list active pass types
  GET  /api/v1/corporate/{account_id}/shuttle/passes/my
                                            — list own passes
  GET  /api/v1/corporate/{account_id}/shuttle/passes/{pass_id}
                                            — get one pass
  POST /api/v1/corporate/{account_id}/shuttle/passes/{pass_id}/redeem
                                            — redeem a pass

Admin endpoints (account admins only):
  POST /api/v1/corporate/{account_id}/shuttle/pass-types
                                            — create pass type
  GET  /api/v1/corporate/{account_id}/shuttle/pass-types/{type_id}
                                            — get pass type detail
  PUT  /api/v1/corporate/{account_id}/shuttle/pass-types/{type_id}
                                            — update pass type
  POST /api/v1/corporate/{account_id}/shuttle/pass-types/{type_id}/deactivate
                                            — deactivate pass type
  POST /api/v1/corporate/{account_id}/shuttle/members/{member_id}/passes/issue
                                            — issue a pass to a member
  GET  /api/v1/corporate/{account_id}/shuttle/passes/summary
                                            — account-level pass summary

Platform-admin endpoints:
  GET /api/v1/platform/corporate/shuttle/passes/all
                                            — all passes across accounts
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_shuttle_pass import (
    PassIssueRequest,
    PassRedeemRequest,
    PassResponse,
    PassSummaryResponse,
    PassTypeCreateRequest,
    PassTypeResponse,
    PassTypeUpdateRequest,
    PassUsageResponse,
)
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin
from app.services.corporate_shuttle_pass_service import (
    create_pass_type,
    deactivate_pass_type,
    get_account_pass_summary,
    get_pass,
    get_pass_type,
    issue_pass,
    list_all_platform,
    list_member_passes,
    list_pass_types,
    redeem_pass,
    update_pass_type,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Shuttle Passes"])


# ---------------------------------------------------------------------------
# Member: list active pass types
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/shuttle/pass-types",
    response_model=List[PassTypeResponse],
    summary="List shuttle pass types for an account",
)
async def list_pass_types_endpoint(
    account_id: int,
    is_active: Optional[bool] = Query(
        None, description="Filter by active status (omit for all)"
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return shuttle pass types for the account.

    Members see all types (active + inactive) by default; use ?is_active=true
    to filter to bookable types only.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await list_pass_types(db, account_id, is_active=is_active)


# ---------------------------------------------------------------------------
# Member: list own passes  ← MUST be before /passes/{pass_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/shuttle/passes/my",
    response_model=List[PassResponse],
    summary="List the current user's shuttle passes",
)
async def list_my_passes_endpoint(
    account_id: int,
    is_active: Optional[bool] = Query(
        None, description="Filter by active status (omit for all)"
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all shuttle passes issued to the calling user in the account.

    Optionally filter by is_active.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await list_member_passes(db, account_id, user.id, is_active=is_active)


# ---------------------------------------------------------------------------
# Admin: account-level pass summary  ← MUST be before /passes/{pass_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/shuttle/passes/summary",
    response_model=PassSummaryResponse,
    summary="Get aggregate shuttle pass statistics for the account (admin only)",
)
async def get_pass_summary_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate pass statistics: type counts, issued/active/expired
    counts, and ride totals.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_account_pass_summary(db, account_id)


# ---------------------------------------------------------------------------
# Member: get a single pass
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/shuttle/passes/{pass_id}",
    response_model=PassResponse,
    summary="Get a shuttle pass by ID",
)
async def get_pass_endpoint(
    account_id: int,
    pass_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single shuttle pass by ID.

    Returns 404 if not found or belongs to a different account.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_pass(db, pass_id, account_id)


# ---------------------------------------------------------------------------
# Member: redeem a pass
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/shuttle/passes/{pass_id}/redeem",
    response_model=PassUsageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Redeem a shuttle pass ride",
)
async def redeem_pass_endpoint(
    account_id: int,
    pass_id: uuid.UUID,
    data: PassRedeemRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Redeem one ride from a shuttle pass.

    Returns 404 if the pass is not found.
    Returns 409 if the pass is inactive, expired, belongs to a different
    member, or has no rides remaining.
    Returns 201 with the usage record on success.
    Any authenticated account member may redeem their own pass.
    """
    await get_account(db, account_id)
    return await redeem_pass(
        db,
        pass_id=pass_id,
        account_id=account_id,
        member_id=user.id,
        booking_id=data.booking_id,
    )


# ---------------------------------------------------------------------------
# Admin: create pass type
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/shuttle/pass-types",
    response_model=PassTypeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a shuttle pass type (admin only)",
)
async def create_pass_type_endpoint(
    account_id: int,
    data: PassTypeCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new shuttle pass type for the account.

    Returns 409 if a pass type with this name already exists.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await create_pass_type(
        db,
        account_id=account_id,
        name=data.name,
        ride_count=data.ride_count,
        created_by_id=user.id,
        description=data.description,
        validity_days=data.validity_days,
        price_usd=data.price_usd,
        notes=data.notes,
    )


# ---------------------------------------------------------------------------
# Admin: get pass type detail
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/shuttle/pass-types/{type_id}",
    response_model=PassTypeResponse,
    summary="Get a shuttle pass type by ID (admin only)",
)
async def get_pass_type_endpoint(
    account_id: int,
    type_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single pass type by ID.

    Returns 404 if not found or belongs to a different account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_pass_type(db, type_id, account_id)


# ---------------------------------------------------------------------------
# Admin: update pass type
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/shuttle/pass-types/{type_id}",
    response_model=PassTypeResponse,
    summary="Update a shuttle pass type (admin only)",
)
async def update_pass_type_endpoint(
    account_id: int,
    type_id: uuid.UUID,
    data: PassTypeUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a shuttle pass type.

    Only provided fields are updated. Returns 409 if the new name collides
    with an existing type.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await update_pass_type(
        db,
        type_id=type_id,
        account_id=account_id,
        name=data.name,
        description=data.description,
        ride_count=data.ride_count,
        validity_days=data.validity_days,
        price_usd=data.price_usd,
        notes=data.notes,
    )


# ---------------------------------------------------------------------------
# Admin: deactivate pass type
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/shuttle/pass-types/{type_id}/deactivate",
    response_model=PassTypeResponse,
    summary="Deactivate a shuttle pass type (admin only)",
)
async def deactivate_pass_type_endpoint(
    account_id: int,
    type_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-deactivate a shuttle pass type.

    Returns 404 if not found. Returns 409 if already inactive.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await deactivate_pass_type(db, type_id, account_id)


# ---------------------------------------------------------------------------
# Admin: issue a pass to a member
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/shuttle/members/{member_id}/passes/issue",
    response_model=PassResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a shuttle pass to a member (admin only)",
)
async def issue_pass_endpoint(
    account_id: int,
    member_id: int,
    data: PassIssueRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Issue a shuttle pass to an employee.

    Returns 404 if the pass type is not found.
    Returns 409 if the pass type is inactive.
    Returns 201 with the issued pass on success.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await issue_pass(
        db,
        pass_type_id=data.pass_type_id,
        account_id=account_id,
        member_id=member_id,
        issued_by_id=user.id,
        notes=data.notes,
    )


# ---------------------------------------------------------------------------
# Platform-admin: cross-account listing
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/shuttle/passes/all",
    response_model=List[PassResponse],
    summary="Admin: list all shuttle passes across all accounts",
)
async def platform_list_all_endpoint(
    account_id: Optional[int] = Query(
        None, description="Filter by corporate account ID"
    ),
    is_active: Optional[bool] = Query(
        None, description="Filter by active status"
    ),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return shuttle passes across all corporate accounts.

    Platform admin only. Optionally filter by account_id or is_active.
    """
    return await list_all_platform(db, account_id=account_id, is_active=is_active)
