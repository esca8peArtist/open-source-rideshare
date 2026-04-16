"""Corporate Driver Performance SLA endpoints.

Enterprise accounts track individual driver performance against KPI thresholds.
Policies define dimensions (on-time rate, rating, cancellation, acceptance) and
are evaluated on a rolling window.  Flagging allows admins to escalate failing drivers.

Member endpoints (any authenticated account member):
  GET  /corporate/{account_id}/driver-sla/policy                       — get active policy

Admin endpoints (account admins only):
  POST /corporate/{account_id}/driver-sla/policy                       — create policy → 201
  GET  /corporate/{account_id}/driver-sla/policy/all                   — list all policies
  GET  /corporate/{account_id}/driver-sla/policy/{policy_id}           — get specific policy
  PUT  /corporate/{account_id}/driver-sla/policy/{policy_id}           — update
  POST /corporate/{account_id}/driver-sla/policy/{policy_id}/activate  — activate
  POST /corporate/{account_id}/driver-sla/policy/{policy_id}/deactivate — deactivate
  DELETE /corporate/{account_id}/driver-sla/policy/{policy_id}         — delete
  POST /corporate/{account_id}/driver-sla/drivers/{driver_profile_id}/evaluate — record evaluation
  GET  /corporate/{account_id}/driver-sla/drivers/{driver_profile_id}/summary  — driver summary
  GET  /corporate/{account_id}/driver-sla/flagged                      — list flagged drivers
  POST /corporate/{account_id}/driver-sla/records/{record_id}/flag     — flag a record

Platform-admin endpoints:
  GET /platform/corporate/driver-sla/all     — cross-account SLA record listing
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_driver_performance_sla import (
    DriverEvaluationInput,
    DriverFlagInput,
    DriverSLASummaryResponse,
    SLAPolicyCreate,
    SLAPolicyResponse,
    SLAPolicyUpdate,
    SLARecordResponse,
)
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin
from app.services.corporate_driver_performance_sla_service import (
    activate_sla_policy,
    create_sla_policy,
    deactivate_sla_policy,
    delete_sla_policy,
    flag_driver_for_review,
    get_driver_sla_summary,
    get_sla_policy,
    list_all_platform,
    list_flagged_drivers,
    list_sla_policies,
    record_driver_evaluation,
    update_sla_policy,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Driver Performance SLA"])


# ---------------------------------------------------------------------------
# Member: get active SLA policy  ← MUST be before /{policy_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/driver-sla/policy",
    response_model=Optional[SLAPolicyResponse],
    summary="Get the active driver performance SLA policy for the account",
)
async def get_active_policy_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the currently-active driver performance SLA policy.

    Any authenticated account member may call this endpoint.
    Returns null in the response body if no active policy exists.
    """
    await get_account(db, account_id)
    policies = await list_sla_policies(db, account_id, is_active=True)
    return policies[0] if policies else None


# ---------------------------------------------------------------------------
# Admin: list all policies  ← MUST be before /{policy_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/driver-sla/policy/all",
    response_model=List[SLAPolicyResponse],
    summary="List all driver SLA policies for the account (admin only)",
)
async def list_all_policies_endpoint(
    account_id: int,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all driver performance SLA policies for the account.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await list_sla_policies(db, account_id, is_active=is_active, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Admin: create policy
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/driver-sla/policy",
    response_model=SLAPolicyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a driver performance SLA policy (admin only)",
)
async def create_policy_endpoint(
    account_id: int,
    data: SLAPolicyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new driver performance SLA policy.

    Automatically deactivates any existing active policy.
    Returns 409 if a policy with the same name already exists for this account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await create_sla_policy(db, account_id, data, created_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: get specific policy
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/driver-sla/policy/{policy_id}",
    response_model=SLAPolicyResponse,
    summary="Get a specific driver SLA policy (admin only)",
)
async def get_policy_endpoint(
    account_id: int,
    policy_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single driver performance SLA policy by ID.

    Returns 404 if the policy does not exist or belongs to a different account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_sla_policy(db, policy_id, account_id)


# ---------------------------------------------------------------------------
# Admin: update policy
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/driver-sla/policy/{policy_id}",
    response_model=SLAPolicyResponse,
    summary="Update a driver SLA policy (admin only)",
)
async def update_policy_endpoint(
    account_id: int,
    policy_id: uuid.UUID,
    data: SLAPolicyUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a driver performance SLA policy.

    Returns 404 if the policy does not exist or belongs to a different account.
    Returns 409 on name collision or invalid activation transition.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await update_sla_policy(db, policy_id, account_id, data)


# ---------------------------------------------------------------------------
# Admin: activate policy
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/driver-sla/policy/{policy_id}/activate",
    response_model=SLAPolicyResponse,
    summary="Activate a driver SLA policy (admin only)",
)
async def activate_policy_endpoint(
    account_id: int,
    policy_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Activate a driver performance SLA policy, deactivating all others first.

    Returns 404 if the policy does not exist or belongs to a different account.
    Returns 409 if the policy is already active.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await activate_sla_policy(db, policy_id, account_id)


# ---------------------------------------------------------------------------
# Admin: deactivate policy
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/driver-sla/policy/{policy_id}/deactivate",
    response_model=SLAPolicyResponse,
    summary="Deactivate a driver SLA policy (admin only)",
)
async def deactivate_policy_endpoint(
    account_id: int,
    policy_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a driver performance SLA policy.

    Returns 404 if the policy does not exist or belongs to a different account.
    Returns 409 if the policy is already inactive.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await deactivate_sla_policy(db, policy_id, account_id)


# ---------------------------------------------------------------------------
# Admin: delete policy
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/{account_id}/driver-sla/policy/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a driver SLA policy (admin only)",
)
async def delete_policy_endpoint(
    account_id: int,
    policy_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a driver performance SLA policy.

    Returns 404 if the policy does not exist or belongs to a different account.
    Returns 409 if the policy is currently active (deactivate it first).
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    await delete_sla_policy(db, policy_id, account_id)


# ---------------------------------------------------------------------------
# Admin: record driver evaluation
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/driver-sla/drivers/{driver_profile_id}/evaluate",
    response_model=Optional[SLARecordResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Record a driver SLA evaluation (admin only)",
)
async def evaluate_driver_endpoint(
    account_id: int,
    driver_profile_id: int,
    data: DriverEvaluationInput,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compute per-dimension pass/fail and persist a driver SLA evaluation record.

    Returns null in the response body if no active SLA policy exists for the account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await record_driver_evaluation(db, account_id, driver_profile_id, data)


# ---------------------------------------------------------------------------
# Admin: get driver SLA summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/driver-sla/drivers/{driver_profile_id}/summary",
    response_model=DriverSLASummaryResponse,
    summary="Get a driver's SLA evaluation summary (admin only)",
)
async def get_driver_summary_endpoint(
    account_id: int,
    driver_profile_id: int,
    last_n_records: int = Query(10, ge=1, le=100, description="Number of recent records to include"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return recent SLA evaluation records and summary stats for a driver.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_driver_sla_summary(db, account_id, driver_profile_id, last_n_records=last_n_records)


# ---------------------------------------------------------------------------
# Admin: list flagged drivers  ← MUST be before /records/{record_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/driver-sla/flagged",
    response_model=List[SLARecordResponse],
    summary="List all flagged driver SLA records (admin only)",
)
async def list_flagged_drivers_endpoint(
    account_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all SLA records flagged for review for this account.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await list_flagged_drivers(db, account_id, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Admin: flag a driver record for review
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/driver-sla/records/{record_id}/flag",
    response_model=SLARecordResponse,
    summary="Flag a driver SLA record for review (admin only)",
)
async def flag_record_endpoint(
    account_id: int,
    record_id: uuid.UUID,
    data: DriverFlagInput = DriverFlagInput(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Flag a driver SLA evaluation record for review.

    Returns 404 if the record does not exist or belongs to a different account.
    Returns 409 if the record is already flagged.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await flag_driver_for_review(
        db, record_id, account_id, flagged_by_id=user.id, reason=data.reason
    )


# ---------------------------------------------------------------------------
# Platform-admin: cross-account listing
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/driver-sla/all",
    response_model=List[SLARecordResponse],
    summary="Admin: list all driver SLA records across all accounts",
)
async def platform_list_all_endpoint(
    account_id: Optional[int] = Query(None, description="Filter by corporate account ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return driver SLA evaluation records across all corporate accounts.

    Platform admin only.  Optionally filter by account_id.
    """
    return await list_all_platform(db, account_id=account_id, skip=skip, limit=limit)
