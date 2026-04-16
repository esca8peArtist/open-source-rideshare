"""Service layer for Corporate Fleet Insurance Tracking.

Fleet managers track insurance policies for company vehicles — liability,
collision, comprehensive coverage — with expiry date alerts.

Public functions
----------------
add_policy              — create a new insurance policy (404 vehicle; 409 inactive/duplicate).
get_policy              — fetch one policy (404 if missing or wrong account).
list_vehicle_policies   — all policies for a specific fleet vehicle.
list_account_policies   — filtered, paginated list for an account.
update_policy           — partial update (404; 409 number collision).
deactivate_policy       — mark as inactive (409 if already inactive).
reactivate_policy       — mark as active (409 if already active).
get_expiring_policies   — active policies expiring within N days.
get_insurance_summary   — aggregate stats for an account.
list_all_platform       — platform-admin cross-account listing.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
from app.models.corporate_fleet_insurance import (
    CorporateFleetInsurancePolicy,
    InsuranceType,
)
from app.schemas.corporate_fleet_insurance import (
    InsuranceExpiringResponse,
    InsurancePolicyCreate,
    InsurancePolicyResponse,
    InsuranceSummaryResponse,
    InsurancePolicyUpdate,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(row: CorporateFleetInsurancePolicy) -> InsurancePolicyResponse:
    return InsurancePolicyResponse.model_validate(row)


async def _fetch_vehicle(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: uuid.UUID,
) -> CorporateFleetVehicle:
    """Return a fleet vehicle verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        fleet_vehicle_id: UUID of the fleet vehicle.

    Returns:
        ``CorporateFleetVehicle`` ORM instance.

    Raises:
        HTTPException 404: Vehicle not found or does not belong to this account.
    """
    stmt = select(CorporateFleetVehicle).where(
        CorporateFleetVehicle.id == fleet_vehicle_id,
        CorporateFleetVehicle.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fleet vehicle not found for this account.",
        )
    return row


async def _fetch_policy(
    db: AsyncSession,
    account_id: int,
    policy_id: uuid.UUID,
) -> CorporateFleetInsurancePolicy:
    """Return an insurance policy verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        policy_id: UUID of the insurance policy.

    Returns:
        ``CorporateFleetInsurancePolicy`` ORM instance.

    Raises:
        HTTPException 404: Policy not found or wrong account.
    """
    stmt = select(CorporateFleetInsurancePolicy).where(
        CorporateFleetInsurancePolicy.id == policy_id,
        CorporateFleetInsurancePolicy.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Insurance policy not found.",
        )
    return row


async def _check_policy_number_unique(
    db: AsyncSession,
    account_id: int,
    policy_number: str,
    exclude_id: Optional[uuid.UUID] = None,
) -> None:
    """Raise 409 if policy_number already exists in this account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        policy_number: Policy number to check.
        exclude_id: UUID to exclude from the check (used on updates).

    Raises:
        HTTPException 409: Policy number already in use for this account.
    """
    conditions = [
        CorporateFleetInsurancePolicy.account_id == account_id,
        CorporateFleetInsurancePolicy.policy_number == policy_number,
    ]
    if exclude_id is not None:
        conditions.append(CorporateFleetInsurancePolicy.id != exclude_id)

    stmt = select(CorporateFleetInsurancePolicy).where(and_(*conditions)).limit(1)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A policy with this number already exists for this account.",
        )


# ---------------------------------------------------------------------------
# add_policy
# ---------------------------------------------------------------------------


async def add_policy(
    db: AsyncSession,
    account_id: int,
    data: InsurancePolicyCreate,
    created_by_id: Optional[int] = None,
) -> InsurancePolicyResponse:
    """Create a new insurance policy for a corporate fleet vehicle.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        data: Insurance policy creation payload.
        created_by_id: ID of the user creating the record.

    Returns:
        ``InsurancePolicyResponse`` for the new policy.

    Raises:
        HTTPException 404: Fleet vehicle not found for this account.
        HTTPException 409: Fleet vehicle is inactive.
        HTTPException 409: Policy number already in use for this account.
    """
    vehicle = await _fetch_vehicle(db, account_id, data.fleet_vehicle_id)

    if not vehicle.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Fleet vehicle is not active.",
        )

    await _check_policy_number_unique(db, account_id, data.policy_number)

    policy = CorporateFleetInsurancePolicy(
        id=uuid.uuid4(),
        account_id=account_id,
        fleet_vehicle_id=data.fleet_vehicle_id,
        policy_number=data.policy_number,
        insurance_type=data.insurance_type,
        provider_name=data.provider_name,
        coverage_amount_usd=float(data.coverage_amount_usd)
        if data.coverage_amount_usd is not None
        else None,
        deductible_usd=float(data.deductible_usd)
        if data.deductible_usd is not None
        else None,
        premium_annual_usd=float(data.premium_annual_usd)
        if data.premium_annual_usd is not None
        else None,
        policy_start_date=data.policy_start_date,
        policy_end_date=data.policy_end_date,
        is_active=True,
        notes=data.notes,
        created_by_id=created_by_id,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return _to_response(policy)


# ---------------------------------------------------------------------------
# get_policy
# ---------------------------------------------------------------------------


async def get_policy(
    db: AsyncSession,
    account_id: int,
    policy_id: uuid.UUID,
) -> InsurancePolicyResponse:
    """Return a single insurance policy.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        policy_id: UUID of the insurance policy.

    Returns:
        ``InsurancePolicyResponse``.

    Raises:
        HTTPException 404: Policy not found or wrong account.
    """
    row = await _fetch_policy(db, account_id, policy_id)
    return _to_response(row)


# ---------------------------------------------------------------------------
# list_vehicle_policies
# ---------------------------------------------------------------------------


async def list_vehicle_policies(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: uuid.UUID,
    *,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[InsurancePolicyResponse]:
    """Return all insurance policies for a specific fleet vehicle.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        fleet_vehicle_id: UUID of the vehicle.
        is_active: Optional filter by active status.
        skip: Records to skip (default 0).
        limit: Max records to return (default 50).

    Returns:
        List of ``InsurancePolicyResponse``.

    Raises:
        HTTPException 404: Vehicle not found for this account.
    """
    await _fetch_vehicle(db, account_id, fleet_vehicle_id)

    conditions = [
        CorporateFleetInsurancePolicy.account_id == account_id,
        CorporateFleetInsurancePolicy.fleet_vehicle_id == fleet_vehicle_id,
    ]
    if is_active is not None:
        conditions.append(CorporateFleetInsurancePolicy.is_active == is_active)

    stmt = (
        select(CorporateFleetInsurancePolicy)
        .where(and_(*conditions))
        .order_by(CorporateFleetInsurancePolicy.policy_end_date.asc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# list_account_policies
# ---------------------------------------------------------------------------


async def list_account_policies(
    db: AsyncSession,
    account_id: int,
    *,
    is_active: Optional[bool] = None,
    insurance_type: Optional[InsuranceType] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[InsurancePolicyResponse]:
    """Return a filtered, paginated list of insurance policies for an account.

    Results are ordered by policy_end_date ascending (soonest expiry first).

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        is_active: Optional filter by active status.
        insurance_type: Optional filter by insurance category.
        skip: Records to skip (default 0).
        limit: Max records to return (default 50).

    Returns:
        List of ``InsurancePolicyResponse``.
    """
    conditions = [CorporateFleetInsurancePolicy.account_id == account_id]
    if is_active is not None:
        conditions.append(CorporateFleetInsurancePolicy.is_active == is_active)
    if insurance_type is not None:
        conditions.append(
            CorporateFleetInsurancePolicy.insurance_type == insurance_type
        )

    stmt = (
        select(CorporateFleetInsurancePolicy)
        .where(and_(*conditions))
        .order_by(CorporateFleetInsurancePolicy.policy_end_date.asc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# update_policy
# ---------------------------------------------------------------------------


async def update_policy(
    db: AsyncSession,
    account_id: int,
    policy_id: uuid.UUID,
    data: InsurancePolicyUpdate,
) -> InsurancePolicyResponse:
    """Partially update an insurance policy.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        policy_id: UUID of the insurance policy.
        data: Fields to update (None values are ignored).

    Returns:
        Updated ``InsurancePolicyResponse``.

    Raises:
        HTTPException 404: Policy not found or wrong account.
        HTTPException 409: Policy number already in use by another policy.
    """
    row = await _fetch_policy(db, account_id, policy_id)

    update_data = data.model_dump(exclude_none=True)

    if "policy_number" in update_data:
        await _check_policy_number_unique(
            db, account_id, update_data["policy_number"], exclude_id=policy_id
        )

    for field, value in update_data.items():
        if field in ("coverage_amount_usd", "deductible_usd", "premium_annual_usd"):
            value = float(value) if value is not None else None
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# deactivate_policy
# ---------------------------------------------------------------------------


async def deactivate_policy(
    db: AsyncSession,
    account_id: int,
    policy_id: uuid.UUID,
) -> InsurancePolicyResponse:
    """Mark an insurance policy as inactive.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        policy_id: UUID of the insurance policy.

    Returns:
        Updated ``InsurancePolicyResponse``.

    Raises:
        HTTPException 404: Policy not found or wrong account.
        HTTPException 409: Policy is already inactive.
    """
    row = await _fetch_policy(db, account_id, policy_id)

    if not row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Insurance policy is already inactive.",
        )

    row.is_active = False
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# reactivate_policy
# ---------------------------------------------------------------------------


async def reactivate_policy(
    db: AsyncSession,
    account_id: int,
    policy_id: uuid.UUID,
) -> InsurancePolicyResponse:
    """Mark an insurance policy as active.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        policy_id: UUID of the insurance policy.

    Returns:
        Updated ``InsurancePolicyResponse``.

    Raises:
        HTTPException 404: Policy not found or wrong account.
        HTTPException 409: Policy is already active.
    """
    row = await _fetch_policy(db, account_id, policy_id)

    if row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Insurance policy is already active.",
        )

    row.is_active = True
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# get_expiring_policies
# ---------------------------------------------------------------------------


async def get_expiring_policies(
    db: AsyncSession,
    account_id: int,
    *,
    days_ahead: int = 30,
    fleet_vehicle_id: Optional[uuid.UUID] = None,
) -> list[InsuranceExpiringResponse]:
    """Return active policies expiring within the next N days.

    Only active policies with policy_end_date between today and today+days_ahead
    are included.  Results are ordered by policy_end_date ascending.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        days_ahead: Look-ahead window in days (default 30).
        fleet_vehicle_id: Optional filter to a specific vehicle.

    Returns:
        List of ``InsuranceExpiringResponse``.
    """
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)

    conditions = [
        CorporateFleetInsurancePolicy.account_id == account_id,
        CorporateFleetInsurancePolicy.is_active == True,  # noqa: E712
        CorporateFleetInsurancePolicy.policy_end_date >= today,
        CorporateFleetInsurancePolicy.policy_end_date <= cutoff,
    ]
    if fleet_vehicle_id is not None:
        conditions.append(
            CorporateFleetInsurancePolicy.fleet_vehicle_id == fleet_vehicle_id
        )

    stmt = (
        select(CorporateFleetInsurancePolicy)
        .where(and_(*conditions))
        .order_by(CorporateFleetInsurancePolicy.policy_end_date.asc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    alerts = []
    for row in rows:
        days_until = (row.policy_end_date - today).days
        alerts.append(
            InsuranceExpiringResponse(
                policy_id=row.id,
                fleet_vehicle_id=row.fleet_vehicle_id,
                policy_number=row.policy_number,
                insurance_type=row.insurance_type.value
                if hasattr(row.insurance_type, "value")
                else str(row.insurance_type),
                provider_name=row.provider_name,
                policy_end_date=row.policy_end_date,
                days_until_expiry=days_until,
            )
        )
    return alerts


# ---------------------------------------------------------------------------
# get_insurance_summary
# ---------------------------------------------------------------------------


async def get_insurance_summary(
    db: AsyncSession,
    account_id: int,
) -> InsuranceSummaryResponse:
    """Return aggregate insurance statistics for a corporate account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.

    Returns:
        ``InsuranceSummaryResponse`` with counts and premium totals.
    """
    today = date.today()
    cutoff_30 = today + timedelta(days=30)

    stmt = select(CorporateFleetInsurancePolicy).where(
        CorporateFleetInsurancePolicy.account_id == account_id
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    total = len(rows)
    active = sum(1 for r in rows if r.is_active)
    inactive = total - active

    expiring_30 = sum(
        1
        for r in rows
        if r.is_active
        and r.policy_end_date >= today
        and r.policy_end_date <= cutoff_30
    )

    total_premium = sum(
        float(r.premium_annual_usd)
        for r in rows
        if r.is_active and r.premium_annual_usd is not None
    )

    by_type: dict[str, int] = {t.value: 0 for t in InsuranceType}
    for row in rows:
        key = (
            row.insurance_type.value
            if hasattr(row.insurance_type, "value")
            else str(row.insurance_type)
        )
        by_type[key] = by_type.get(key, 0) + 1

    return InsuranceSummaryResponse(
        total_policies=total,
        active_policies=active,
        inactive_policies=inactive,
        expiring_within_30_days=expiring_30,
        total_annual_premium_usd=round(total_premium, 2),
        by_type=by_type,
    )


# ---------------------------------------------------------------------------
# list_all_platform
# ---------------------------------------------------------------------------


async def list_all_platform(
    db: AsyncSession,
    *,
    account_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
) -> list[InsurancePolicyResponse]:
    """Return insurance policies across all corporate accounts (platform admin).

    Args:
        db: Async SQLAlchemy session.
        account_id: Optional filter to a specific account.
        skip: Records to skip (default 0).
        limit: Max records to return (default 100).

    Returns:
        List of ``InsurancePolicyResponse``.
    """
    conditions = []
    if account_id is not None:
        conditions.append(CorporateFleetInsurancePolicy.account_id == account_id)

    base = select(CorporateFleetInsurancePolicy)
    if conditions:
        base = base.where(and_(*conditions))

    stmt = (
        base.order_by(
            CorporateFleetInsurancePolicy.account_id,
            CorporateFleetInsurancePolicy.policy_end_date.asc(),
        )
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]
