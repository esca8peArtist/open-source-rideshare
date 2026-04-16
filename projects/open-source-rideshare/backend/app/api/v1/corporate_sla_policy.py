"""Corporate SLA Policy & Compliance Reporting endpoints.

Enterprise corporate accounts define SLA policies with contractual quality
targets for rides.  Each ride is evaluated against the active policy and
admins can view compliance reports and breach lists.

Member endpoints (any active account member):
  GET  /corporate/sla/policy   — get the active SLA policy (404 if none)
  GET  /corporate/sla/summary  — compliance summary (query: year, month)
  GET  /corporate/sla/trend    — monthly compliance trend (query: months)

Admin endpoints (account admins only):
  POST   /corporate/sla/policies                        — create policy (201)
  GET    /corporate/sla/policies                        — list policies
  GET    /corporate/sla/policies/{policy_id}            — get policy
  PUT    /corporate/sla/policies/{policy_id}            — update policy
  POST   /corporate/sla/policies/{policy_id}/activate   — activate
  POST   /corporate/sla/policies/{policy_id}/deactivate — deactivate
  DELETE /corporate/sla/policies/{policy_id}            — delete (204)
  POST   /corporate/sla/rides/{ride_id}/evaluate        — record evaluation (201)
  GET    /corporate/sla/breaches                        — list SLA breaches

Platform-admin endpoints:
  GET  /platform-admin/corporate/sla/all                          — all policies
  GET  /platform-admin/corporate/sla/account/{account_id}/summary — account summary
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_sla_policy import (
    SLAComplianceSummary,
    SLAEvaluationCreate,
    SLAPolicyCreate,
    SLAPolicyListResponse,
    SLAPolicyResponse,
    SLAPolicyUpdate,
    SLARideRecordListResponse,
    SLARideRecordResponse,
    SLATrendResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_sla_policy import (
    activate_sla_policy,
    create_sla_policy,
    deactivate_sla_policy,
    delete_sla_policy,
    get_sla_compliance_summary,
    get_sla_compliance_trend,
    get_sla_policy,
    list_all_platform,
    list_sla_breaches,
    list_sla_policies,
    record_sla_evaluation,
    update_sla_policy,
)
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-sla-policy"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the account_id for the authenticated user.

    Raises HTTP 404 if the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Member: get active policy
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/sla/policy",
    response_model=SLAPolicyResponse,
    summary="Get the active SLA policy for my corporate account",
)
async def get_active_policy(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the currently active SLA policy for the authenticated user's account.

    Returns 404 if no active policy is configured.
    Any active corporate account member may call this endpoint.
    """
    from app.models.corporate_sla_policy import CorporateSLAPolicy
    from app.services.corporate_sla_policy import _policy_to_response

    account_id = await _resolve_account_id(db, user.id)
    result = await db.execute(
        select(CorporateSLAPolicy).where(
            CorporateSLAPolicy.account_id == account_id,
            CorporateSLAPolicy.is_active.is_(True),
        )
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active SLA policy found for this account.",
        )
    return _policy_to_response(policy)


# ---------------------------------------------------------------------------
# Member: compliance summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/sla/summary",
    response_model=SLAComplianceSummary,
    summary="Get SLA compliance summary for my corporate account",
)
async def get_compliance_summary(
    year: Optional[int] = Query(None, description="Filter to this calendar year"),
    month: Optional[int] = Query(None, description="Filter to this month (1–12); requires year"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return overall SLA compliance summary for the authenticated user's account.

    Optionally filter to a specific year/month.
    Any active corporate account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_sla_compliance_summary(db, account_id, year=year, month=month)


# ---------------------------------------------------------------------------
# Member: compliance trend
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/sla/trend",
    response_model=SLATrendResponse,
    summary="Get monthly SLA compliance trend for my corporate account",
)
async def get_compliance_trend(
    months: int = Query(6, ge=1, le=24, description="Number of months to return"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return monthly SLA compliance trend for the authenticated user's account.

    Returns the most recent N months ordered oldest to newest.
    Any active corporate account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_sla_compliance_trend(db, account_id, months=months)


# ---------------------------------------------------------------------------
# Admin: create policy
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/sla/policies",
    response_model=SLAPolicyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new SLA policy (admin only)",
)
async def create_policy_endpoint(
    data: SLAPolicyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new SLA policy for the account.

    Returns 409 if an active policy with the same name already exists.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await create_sla_policy(db, account_id, data, created_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: list policies
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/sla/policies",
    response_model=SLAPolicyListResponse,
    summary="List SLA policies (admin only)",
)
async def list_policies_endpoint(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all SLA policies for the account.

    Optionally filter by ``is_active``.  Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_sla_policies(db, account_id, is_active=is_active)


# ---------------------------------------------------------------------------
# Admin: get policy
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/sla/policies/{policy_id}",
    response_model=SLAPolicyResponse,
    summary="Get a specific SLA policy (admin only)",
)
async def get_policy_endpoint(
    policy_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a specific SLA policy by ID.

    Returns 404 if not found.  Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await get_sla_policy(db, policy_id, account_id)


# ---------------------------------------------------------------------------
# Admin: update policy
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/sla/policies/{policy_id}",
    response_model=SLAPolicyResponse,
    summary="Update a SLA policy (admin only)",
)
async def update_policy_endpoint(
    policy_id: uuid.UUID,
    data: SLAPolicyUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update an SLA policy.

    Returns 409 on duplicate name.  Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await update_sla_policy(db, policy_id, account_id, data)


# ---------------------------------------------------------------------------
# Admin: activate policy
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/sla/policies/{policy_id}/activate",
    response_model=SLAPolicyResponse,
    summary="Activate a SLA policy (admin only)",
)
async def activate_policy_endpoint(
    policy_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Activate an SLA policy, deactivating the previously active one.

    Returns 409 if already active.  Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await activate_sla_policy(db, policy_id, account_id)


# ---------------------------------------------------------------------------
# Admin: deactivate policy
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/sla/policies/{policy_id}/deactivate",
    response_model=SLAPolicyResponse,
    summary="Deactivate a SLA policy (admin only)",
)
async def deactivate_policy_endpoint(
    policy_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate an active SLA policy.

    Returns 409 if already inactive.  Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await deactivate_sla_policy(db, policy_id, account_id)


# ---------------------------------------------------------------------------
# Admin: delete policy
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/sla/policies/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a SLA policy (admin only)",
)
async def delete_policy_endpoint(
    policy_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete an SLA policy.

    Returns 409 if the policy is active — deactivate it first.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    await delete_sla_policy(db, policy_id, account_id)


# ---------------------------------------------------------------------------
# Admin: record ride evaluation
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/sla/rides/{ride_id}/evaluate",
    response_model=SLARideRecordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record SLA evaluation for a ride (admin only)",
)
async def evaluate_ride_endpoint(
    ride_id: int,
    data: SLAEvaluationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a per-ride SLA evaluation snapshot.

    Evaluates the ride against the account's current active SLA policy.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await record_sla_evaluation(
        db,
        account_id=account_id,
        ride_id=ride_id,
        member_id=user.id,
        wait_time_minutes=data.wait_time_minutes,
        driver_rating=data.driver_rating,
        was_scheduled_ride=data.was_scheduled_ride,
        scheduled_pickup_at=data.scheduled_pickup_at,
        actual_pickup_at=data.actual_pickup_at,
    )


# ---------------------------------------------------------------------------
# Admin: list breaches
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/sla/breaches",
    response_model=SLARideRecordListResponse,
    summary="List SLA breaches (admin only)",
)
async def list_breaches_endpoint(
    year: Optional[int] = Query(None, description="Filter to this calendar year"),
    month: Optional[int] = Query(None, description="Filter to this month (1–12); requires year"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return paginated SLA breach records for the account.

    Optionally filter to a specific year/month.  Only account admins may call
    this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_sla_breaches(
        db, account_id, year=year, month=month, limit=limit, offset=offset
    )


# ---------------------------------------------------------------------------
# Platform-admin: list all policies
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate/sla/all",
    response_model=SLAPolicyListResponse,
    summary="Platform admin: list all SLA policies",
)
async def admin_list_all_policies(
    account_id: Optional[int] = Query(None, description="Filter by account ID"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all SLA policies across all corporate accounts.

    Optionally filter by ``account_id``.  Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id)


# ---------------------------------------------------------------------------
# Platform-admin: compliance summary for any account
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate/sla/account/{account_id}/summary",
    response_model=SLAComplianceSummary,
    summary="Platform admin: get SLA compliance summary for any account",
)
async def admin_account_summary(
    account_id: int,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return SLA compliance summary for any corporate account.

    Platform admin only.
    """
    return await get_sla_compliance_summary(db, account_id, year=year, month=month)
