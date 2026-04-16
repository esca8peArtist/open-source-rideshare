"""Corporate Fleet Insurance Tracking endpoints.

Fleet managers track insurance policies for company vehicles — liability,
collision, comprehensive coverage — with expiry date alerts.

Member endpoints (any authenticated account member):
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/insurance       — list vehicle policies
  GET  /corporate/{account_id}/fleet-insurance/expiring                    — expiry alerts
  GET  /corporate/{account_id}/fleet-insurance/summary                     — summary stats
  GET  /corporate/{account_id}/fleet-insurance/{policy_id}                 — get one policy

Admin endpoints (account admins only):
  POST /corporate/{account_id}/fleet-insurance/                            — create → 201
  GET  /corporate/{account_id}/fleet-insurance/                            — list all (filtered)
  PUT  /corporate/{account_id}/fleet-insurance/{policy_id}                 — update
  POST /corporate/{account_id}/fleet-insurance/{policy_id}/deactivate      — deactivate
  POST /corporate/{account_id}/fleet-insurance/{policy_id}/reactivate      — reactivate

Platform-admin endpoints:
  GET /platform/corporate/fleet-insurance/              — all records across accounts
  GET /platform/corporate/fleet-insurance/{account_id}  — records for one account
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_fleet_insurance import InsuranceType
from app.models.user import User
from app.schemas.corporate_fleet_insurance import (
    InsuranceExpiringResponse,
    InsurancePolicyCreate,
    InsurancePolicyResponse,
    InsuranceSummaryResponse,
    InsurancePolicyUpdate,
)
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin
from app.services.corporate_fleet_insurance_service import (
    add_policy,
    deactivate_policy,
    get_expiring_policies,
    get_insurance_summary,
    get_policy,
    list_account_policies,
    list_all_platform,
    list_vehicle_policies,
    reactivate_policy,
    update_policy,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Fleet Insurance"])


# ---------------------------------------------------------------------------
# Member: list insurance policies for a specific vehicle
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/insurance",
    response_model=List[InsurancePolicyResponse],
    summary="List insurance policies for a fleet vehicle",
)
async def list_vehicle_insurance_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all insurance policies for a specific fleet vehicle.

    Any authenticated account member may call this endpoint.
    Returns 404 if the vehicle does not exist in this account.
    """
    await get_account(db, account_id)
    return await list_vehicle_policies(
        db, account_id, vehicle_id, is_active=is_active, skip=skip, limit=limit
    )


# ---------------------------------------------------------------------------
# Member: expiring policies alert  ← MUST be before /{policy_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-insurance/expiring",
    response_model=List[InsuranceExpiringResponse],
    summary="List insurance policies expiring soon for the account",
)
async def get_expiring_policies_endpoint(
    account_id: int,
    days_ahead: int = Query(30, ge=1, le=365, description="Look-ahead window in days"),
    fleet_vehicle_id: Optional[uuid.UUID] = Query(
        None, description="Filter to a specific vehicle"
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return active policies expiring within the next N days.

    Results are ordered by policy_end_date ascending (most urgent first).
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_expiring_policies(
        db, account_id, days_ahead=days_ahead, fleet_vehicle_id=fleet_vehicle_id
    )


# ---------------------------------------------------------------------------
# Member: insurance summary  ← MUST be before /{policy_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-insurance/summary",
    response_model=InsuranceSummaryResponse,
    summary="Get insurance statistics for the account",
)
async def get_insurance_summary_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate insurance counts and premium totals for the account.

    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_insurance_summary(db, account_id)


# ---------------------------------------------------------------------------
# Admin: create insurance policy  ← MUST be before /{policy_id}
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-insurance/",
    response_model=InsurancePolicyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a fleet insurance policy (admin only)",
)
async def add_policy_endpoint(
    account_id: int,
    data: InsurancePolicyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new insurance policy for a fleet vehicle.

    Returns 404 if the vehicle does not exist in this account.
    Returns 409 if the vehicle is inactive.
    Returns 409 if the policy number already exists for this account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await add_policy(db, account_id, data, created_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: list all insurance policies  ← MUST be before /{policy_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-insurance/",
    response_model=List[InsurancePolicyResponse],
    summary="List insurance policies for the account (admin only)",
)
async def list_account_policies_endpoint(
    account_id: int,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    insurance_type: Optional[InsuranceType] = Query(
        None, description="Filter by insurance category"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated, filtered list of insurance policies for the account.

    Ordered by policy_end_date ascending (soonest expiry first).
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await list_account_policies(
        db,
        account_id,
        is_active=is_active,
        insurance_type=insurance_type,
        skip=skip,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Member: get single insurance policy
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-insurance/{policy_id}",
    response_model=InsurancePolicyResponse,
    summary="Get a single insurance policy",
)
async def get_policy_endpoint(
    account_id: int,
    policy_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single insurance policy by ID.

    Returns 404 if the policy does not exist or belongs to a different account.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_policy(db, account_id, policy_id)


# ---------------------------------------------------------------------------
# Admin: update insurance policy
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/fleet-insurance/{policy_id}",
    response_model=InsurancePolicyResponse,
    summary="Update an insurance policy (admin only)",
)
async def update_policy_endpoint(
    account_id: int,
    policy_id: uuid.UUID,
    data: InsurancePolicyUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update an insurance policy.

    Returns 404 if the policy does not exist or belongs to a different account.
    Returns 409 if the policy number is already in use by another policy.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await update_policy(db, account_id, policy_id, data)


# ---------------------------------------------------------------------------
# Admin: deactivate insurance policy
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-insurance/{policy_id}/deactivate",
    response_model=InsurancePolicyResponse,
    summary="Deactivate an insurance policy (admin only)",
)
async def deactivate_policy_endpoint(
    account_id: int,
    policy_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an insurance policy as inactive.

    Returns 404 if the policy does not exist or belongs to a different account.
    Returns 409 if the policy is already inactive.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await deactivate_policy(db, account_id, policy_id)


# ---------------------------------------------------------------------------
# Admin: reactivate insurance policy
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-insurance/{policy_id}/reactivate",
    response_model=InsurancePolicyResponse,
    summary="Reactivate an insurance policy (admin only)",
)
async def reactivate_policy_endpoint(
    account_id: int,
    policy_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an insurance policy as active.

    Returns 404 if the policy does not exist or belongs to a different account.
    Returns 409 if the policy is already active.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await reactivate_policy(db, account_id, policy_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all insurance policies
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/fleet-insurance/",
    response_model=List[InsurancePolicyResponse],
    summary="Admin: list all fleet insurance policies across all accounts",
)
async def admin_list_insurance_policies(
    account_id: Optional[int] = Query(None, description="Filter by corporate account ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return fleet insurance policies across all corporate accounts.

    Platform admin only.  Optionally filter by account_id.
    """
    return await list_all_platform(db, account_id=account_id, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Platform-admin: list insurance policies for one account
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/fleet-insurance/{account_id}",
    response_model=List[InsurancePolicyResponse],
    summary="Admin: list fleet insurance policies for a specific corporate account",
)
async def admin_list_account_insurance_policies(
    account_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return fleet insurance policies for a specific corporate account.

    Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id, skip=skip, limit=limit)
