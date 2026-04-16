"""Service layer for Corporate Driver Performance SLA.

Enterprise accounts track individual driver performance against KPI thresholds.
Policies define the thresholds and are enforced as a rolling-window evaluation.

Public functions
----------------
create_sla_policy           — create a new policy (409 on name collision; deactivates existing active).
get_sla_policy              — fetch one policy (404 if missing or wrong account).
list_sla_policies           — filtered list for an account.
update_sla_policy           — partial update (409 on name collision or invalid active transition).
activate_sla_policy         — activate a policy (deactivates others; 409 if already active).
deactivate_sla_policy       — deactivate a policy (409 if already inactive).
delete_sla_policy           — delete a policy (409 if currently active).
record_driver_evaluation    — compute per-dimension pass/fail and persist a record.
get_driver_sla_summary      — recent records + summary stats for a driver.
list_all_platform           — platform-admin cross-account listing.
flag_driver_for_review      — flag a record for review (409 if already flagged).
list_flagged_drivers        — list all flagged records for an account.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_driver_performance_sla import (
    CorporateDriverPerformanceSLA,
    CorporateDriverSLARecord,
)
from app.schemas.corporate_driver_performance_sla import (
    DriverEvaluationInput,
    DriverSLASummaryResponse,
    SLAPolicyCreate,
    SLAPolicyResponse,
    SLAPolicyUpdate,
    SLARecordResponse,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _policy_to_response(row: CorporateDriverPerformanceSLA) -> SLAPolicyResponse:
    return SLAPolicyResponse(
        id=row.id,
        account_id=row.account_id,
        name=row.name,
        description=row.description,
        min_on_time_rate_pct=float(row.min_on_time_rate_pct)
        if row.min_on_time_rate_pct is not None
        else None,
        min_avg_rating=float(row.min_avg_rating) if row.min_avg_rating is not None else None,
        max_cancellation_rate_pct=float(row.max_cancellation_rate_pct)
        if row.max_cancellation_rate_pct is not None
        else None,
        min_acceptance_rate_pct=float(row.min_acceptance_rate_pct)
        if row.min_acceptance_rate_pct is not None
        else None,
        evaluation_window_days=row.evaluation_window_days,
        is_active=row.is_active,
        created_by_id=row.created_by_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _record_to_response(row: CorporateDriverSLARecord) -> SLARecordResponse:
    return SLARecordResponse(
        id=row.id,
        account_id=row.account_id,
        sla_policy_id=row.sla_policy_id,
        driver_profile_id=row.driver_profile_id,
        evaluated_at=row.evaluated_at,
        evaluation_window_days=row.evaluation_window_days,
        total_corporate_rides=row.total_corporate_rides,
        on_time_rate_pct=float(row.on_time_rate_pct)
        if row.on_time_rate_pct is not None
        else None,
        avg_rating=float(row.avg_rating) if row.avg_rating is not None else None,
        cancellation_rate_pct=float(row.cancellation_rate_pct)
        if row.cancellation_rate_pct is not None
        else None,
        acceptance_rate_pct=float(row.acceptance_rate_pct)
        if row.acceptance_rate_pct is not None
        else None,
        on_time_met=row.on_time_met,
        rating_met=row.rating_met,
        cancellation_met=row.cancellation_met,
        acceptance_met=row.acceptance_met,
        overall_sla_met=row.overall_sla_met,
        flagged_for_review=row.flagged_for_review,
        flagged_by_id=row.flagged_by_id,
        flagged_at=row.flagged_at,
        flag_reason=row.flag_reason,
    )


async def _fetch_policy(
    db: AsyncSession,
    policy_id: uuid.UUID,
    account_id: int,
) -> CorporateDriverPerformanceSLA:
    """Return a SLA policy verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        policy_id: UUID of the policy.
        account_id: Corporate account ID.

    Returns:
        ``CorporateDriverPerformanceSLA`` ORM instance.

    Raises:
        HTTPException 404: Policy not found or does not belong to this account.
    """
    stmt = select(CorporateDriverPerformanceSLA).where(
        CorporateDriverPerformanceSLA.id == policy_id,
        CorporateDriverPerformanceSLA.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver performance SLA policy not found for this account.",
        )
    return row


async def _fetch_record(
    db: AsyncSession,
    record_id: uuid.UUID,
    account_id: int,
) -> CorporateDriverSLARecord:
    """Return a SLA record verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        record_id: UUID of the SLA record.
        account_id: Corporate account ID.

    Returns:
        ``CorporateDriverSLARecord`` ORM instance.

    Raises:
        HTTPException 404: Record not found or does not belong to this account.
    """
    stmt = select(CorporateDriverSLARecord).where(
        CorporateDriverSLARecord.id == record_id,
        CorporateDriverSLARecord.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver SLA record not found for this account.",
        )
    return row


async def _deactivate_all_for_account(db: AsyncSession, account_id: int) -> None:
    """Set is_active=False for every policy belonging to this account."""
    stmt = select(CorporateDriverPerformanceSLA).where(
        CorporateDriverPerformanceSLA.account_id == account_id,
        CorporateDriverPerformanceSLA.is_active == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    for row in result.scalars().all():
        row.is_active = False


# ---------------------------------------------------------------------------
# create_sla_policy
# ---------------------------------------------------------------------------


async def create_sla_policy(
    db: AsyncSession,
    account_id: int,
    data: SLAPolicyCreate,
    created_by_id: Optional[int] = None,
) -> SLAPolicyResponse:
    """Create a new driver performance SLA policy for a corporate account.

    Deactivates any existing active policy first (only one active per account).

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        data: Policy creation payload.
        created_by_id: ID of the admin creating the policy.

    Returns:
        ``SLAPolicyResponse`` for the new policy.

    Raises:
        HTTPException 409: A policy with this name already exists for the account.
    """
    # 409 on name collision within the account
    name_check_stmt = select(CorporateDriverPerformanceSLA).where(
        CorporateDriverPerformanceSLA.account_id == account_id,
        CorporateDriverPerformanceSLA.name == data.name,
    )
    name_result = await db.execute(name_check_stmt)
    if name_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A driver performance SLA policy named '{data.name}' already exists for this account.",
        )

    # Deactivate any currently-active policy
    await _deactivate_all_for_account(db, account_id)

    policy = CorporateDriverPerformanceSLA(
        id=uuid.uuid4(),
        account_id=account_id,
        name=data.name,
        description=data.description,
        min_on_time_rate_pct=data.min_on_time_rate_pct,
        min_avg_rating=data.min_avg_rating,
        max_cancellation_rate_pct=data.max_cancellation_rate_pct,
        min_acceptance_rate_pct=data.min_acceptance_rate_pct,
        evaluation_window_days=data.evaluation_window_days,
        is_active=True,
        created_by_id=created_by_id,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return _policy_to_response(policy)


# ---------------------------------------------------------------------------
# get_sla_policy
# ---------------------------------------------------------------------------


async def get_sla_policy(
    db: AsyncSession,
    policy_id: uuid.UUID,
    account_id: int,
) -> SLAPolicyResponse:
    """Return a single driver performance SLA policy.

    Args:
        db: Async SQLAlchemy session.
        policy_id: UUID of the policy.
        account_id: Corporate account ID.

    Returns:
        ``SLAPolicyResponse``.

    Raises:
        HTTPException 404: Policy not found or wrong account.
    """
    row = await _fetch_policy(db, policy_id, account_id)
    return _policy_to_response(row)


# ---------------------------------------------------------------------------
# list_sla_policies
# ---------------------------------------------------------------------------


async def list_sla_policies(
    db: AsyncSession,
    account_id: int,
    *,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[SLAPolicyResponse]:
    """Return a filtered list of driver performance SLA policies for an account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        is_active: Optional filter by active status.
        skip: Records to skip (default 0).
        limit: Max records to return (default 50).

    Returns:
        List of ``SLAPolicyResponse``.
    """
    conditions = [CorporateDriverPerformanceSLA.account_id == account_id]
    if is_active is not None:
        conditions.append(CorporateDriverPerformanceSLA.is_active == is_active)

    stmt = (
        select(CorporateDriverPerformanceSLA)
        .where(and_(*conditions))
        .order_by(CorporateDriverPerformanceSLA.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_policy_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# update_sla_policy
# ---------------------------------------------------------------------------


async def update_sla_policy(
    db: AsyncSession,
    policy_id: uuid.UUID,
    account_id: int,
    data: SLAPolicyUpdate,
) -> SLAPolicyResponse:
    """Partially update a driver performance SLA policy.

    Args:
        db: Async SQLAlchemy session.
        policy_id: UUID of the policy.
        account_id: Corporate account ID.
        data: Fields to update (None values are ignored).

    Returns:
        Updated ``SLAPolicyResponse``.

    Raises:
        HTTPException 404: Policy not found or wrong account.
        HTTPException 409: Name collision with another policy for this account.
        HTTPException 409: Attempting to activate an already-inactive policy
            (use activate_sla_policy instead).
    """
    row = await _fetch_policy(db, policy_id, account_id)

    update_data = data.model_dump(exclude_none=True)

    # Name collision check
    if "name" in update_data and update_data["name"] != row.name:
        name_check_stmt = select(CorporateDriverPerformanceSLA).where(
            CorporateDriverPerformanceSLA.account_id == account_id,
            CorporateDriverPerformanceSLA.name == update_data["name"],
        )
        name_result = await db.execute(name_check_stmt)
        if name_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A driver performance SLA policy named '{update_data['name']}' already exists for this account.",
            )

    # Guard: cannot reactivate via update if already inactive
    if "is_active" in update_data and update_data["is_active"] is True and not row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Use the activate endpoint to reactivate an inactive policy.",
        )

    for field, value in update_data.items():
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    return _policy_to_response(row)


# ---------------------------------------------------------------------------
# activate_sla_policy
# ---------------------------------------------------------------------------


async def activate_sla_policy(
    db: AsyncSession,
    policy_id: uuid.UUID,
    account_id: int,
) -> SLAPolicyResponse:
    """Activate a driver performance SLA policy, deactivating all others first.

    Args:
        db: Async SQLAlchemy session.
        policy_id: UUID of the policy to activate.
        account_id: Corporate account ID.

    Returns:
        Updated ``SLAPolicyResponse``.

    Raises:
        HTTPException 404: Policy not found or wrong account.
        HTTPException 409: Policy is already active.
    """
    row = await _fetch_policy(db, policy_id, account_id)

    if row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Driver performance SLA policy is already active.",
        )

    await _deactivate_all_for_account(db, account_id)
    row.is_active = True
    await db.commit()
    await db.refresh(row)
    return _policy_to_response(row)


# ---------------------------------------------------------------------------
# deactivate_sla_policy
# ---------------------------------------------------------------------------


async def deactivate_sla_policy(
    db: AsyncSession,
    policy_id: uuid.UUID,
    account_id: int,
) -> SLAPolicyResponse:
    """Deactivate a driver performance SLA policy.

    Args:
        db: Async SQLAlchemy session.
        policy_id: UUID of the policy to deactivate.
        account_id: Corporate account ID.

    Returns:
        Updated ``SLAPolicyResponse``.

    Raises:
        HTTPException 404: Policy not found or wrong account.
        HTTPException 409: Policy is already inactive.
    """
    row = await _fetch_policy(db, policy_id, account_id)

    if not row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Driver performance SLA policy is already inactive.",
        )

    row.is_active = False
    await db.commit()
    await db.refresh(row)
    return _policy_to_response(row)


# ---------------------------------------------------------------------------
# delete_sla_policy
# ---------------------------------------------------------------------------


async def delete_sla_policy(
    db: AsyncSession,
    policy_id: uuid.UUID,
    account_id: int,
) -> None:
    """Delete a driver performance SLA policy.

    Active policies must be deactivated before deletion.

    Args:
        db: Async SQLAlchemy session.
        policy_id: UUID of the policy to delete.
        account_id: Corporate account ID.

    Raises:
        HTTPException 404: Policy not found or wrong account.
        HTTPException 409: Policy is currently active — deactivate it first.
    """
    row = await _fetch_policy(db, policy_id, account_id)

    if row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete an active driver performance SLA policy. Deactivate it first.",
        )

    await db.delete(row)
    await db.commit()


# ---------------------------------------------------------------------------
# record_driver_evaluation
# ---------------------------------------------------------------------------


async def record_driver_evaluation(
    db: AsyncSession,
    account_id: int,
    driver_profile_id: int,
    metrics: DriverEvaluationInput,
) -> Optional[SLARecordResponse]:
    """Evaluate a driver against the account's active SLA policy and persist the result.

    If no active policy exists for the account, returns None without persisting.

    Per-dimension logic:
        - on_time_met: True if on_time_rate_pct >= min_on_time_rate_pct (null → null)
        - rating_met: True if avg_rating >= min_avg_rating (null → null)
        - cancellation_met: True if cancellation_rate_pct <= max_cancellation_rate_pct (null → null)
        - acceptance_met: True if acceptance_rate_pct >= min_acceptance_rate_pct (null → null)
        - overall_sla_met: True if every configured (non-null threshold) dimension passed.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        driver_profile_id: Driver's profile ID.
        metrics: Computed metrics for the evaluation window.

    Returns:
        ``SLARecordResponse`` for the new record, or None if no active policy.
    """
    # Find the active policy
    stmt = select(CorporateDriverPerformanceSLA).where(
        CorporateDriverPerformanceSLA.account_id == account_id,
        CorporateDriverPerformanceSLA.is_active == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    policy = result.scalar_one_or_none()

    if policy is None:
        return None

    window = metrics.evaluation_window_days or policy.evaluation_window_days

    # Per-dimension pass/fail
    on_time_met: Optional[bool] = None
    if policy.min_on_time_rate_pct is not None and metrics.on_time_rate_pct is not None:
        on_time_met = metrics.on_time_rate_pct >= float(policy.min_on_time_rate_pct)

    rating_met: Optional[bool] = None
    if policy.min_avg_rating is not None and metrics.avg_rating is not None:
        rating_met = metrics.avg_rating >= float(policy.min_avg_rating)

    cancellation_met: Optional[bool] = None
    if (
        policy.max_cancellation_rate_pct is not None
        and metrics.cancellation_rate_pct is not None
    ):
        cancellation_met = metrics.cancellation_rate_pct <= float(
            policy.max_cancellation_rate_pct
        )

    acceptance_met: Optional[bool] = None
    if (
        policy.min_acceptance_rate_pct is not None
        and metrics.acceptance_rate_pct is not None
    ):
        acceptance_met = metrics.acceptance_rate_pct >= float(
            policy.min_acceptance_rate_pct
        )

    # overall_sla_met: all configured dimensions must pass (None = not configured)
    dimension_results = [on_time_met, rating_met, cancellation_met, acceptance_met]
    evaluated = [d for d in dimension_results if d is not None]
    overall_sla_met = all(evaluated) if evaluated else True

    record = CorporateDriverSLARecord(
        id=uuid.uuid4(),
        account_id=account_id,
        sla_policy_id=policy.id,
        driver_profile_id=driver_profile_id,
        evaluated_at=datetime.now(tz=timezone.utc),
        evaluation_window_days=window,
        total_corporate_rides=metrics.total_corporate_rides,
        on_time_rate_pct=metrics.on_time_rate_pct,
        avg_rating=metrics.avg_rating,
        cancellation_rate_pct=metrics.cancellation_rate_pct,
        acceptance_rate_pct=metrics.acceptance_rate_pct,
        on_time_met=on_time_met,
        rating_met=rating_met,
        cancellation_met=cancellation_met,
        acceptance_met=acceptance_met,
        overall_sla_met=overall_sla_met,
        flagged_for_review=False,
        flagged_by_id=None,
        flagged_at=None,
        flag_reason=None,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return _record_to_response(record)


# ---------------------------------------------------------------------------
# get_driver_sla_summary
# ---------------------------------------------------------------------------


async def get_driver_sla_summary(
    db: AsyncSession,
    account_id: int,
    driver_profile_id: int,
    last_n_records: int = 10,
) -> DriverSLASummaryResponse:
    """Return recent SLA evaluation records and summary stats for a driver.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        driver_profile_id: Driver's profile ID.
        last_n_records: Number of most recent records to return (default 10).

    Returns:
        ``DriverSLASummaryResponse`` with pass rate, flagged count, and recent records.
    """
    stmt = (
        select(CorporateDriverSLARecord)
        .where(
            CorporateDriverSLARecord.account_id == account_id,
            CorporateDriverSLARecord.driver_profile_id == driver_profile_id,
        )
        .order_by(CorporateDriverSLARecord.evaluated_at.desc())
        .limit(last_n_records)
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    total = len(rows)
    pass_count = sum(1 for r in rows if r.overall_sla_met)
    fail_count = total - pass_count
    pass_rate_pct = round((pass_count / total * 100) if total > 0 else 0.0, 2)
    flagged_count = sum(1 for r in rows if r.flagged_for_review)

    return DriverSLASummaryResponse(
        driver_profile_id=driver_profile_id,
        account_id=account_id,
        total_evaluations=total,
        pass_count=pass_count,
        fail_count=fail_count,
        pass_rate_pct=pass_rate_pct,
        flagged_count=flagged_count,
        recent_records=[_record_to_response(r) for r in rows],
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
) -> list[SLARecordResponse]:
    """Return driver SLA records across all corporate accounts (platform admin).

    Args:
        db: Async SQLAlchemy session.
        account_id: Optional filter to a specific account.
        skip: Records to skip (default 0).
        limit: Max records to return (default 100).

    Returns:
        List of ``SLARecordResponse``.
    """
    conditions = []
    if account_id is not None:
        conditions.append(CorporateDriverSLARecord.account_id == account_id)

    base = select(CorporateDriverSLARecord)
    if conditions:
        base = base.where(and_(*conditions))

    stmt = (
        base.order_by(
            CorporateDriverSLARecord.account_id,
            CorporateDriverSLARecord.evaluated_at.desc(),
        )
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_record_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# flag_driver_for_review
# ---------------------------------------------------------------------------


async def flag_driver_for_review(
    db: AsyncSession,
    record_id: uuid.UUID,
    account_id: int,
    flagged_by_id: int,
    reason: Optional[str] = None,
) -> SLARecordResponse:
    """Flag a driver SLA record for review.

    Args:
        db: Async SQLAlchemy session.
        record_id: UUID of the SLA record.
        account_id: Corporate account ID.
        flagged_by_id: ID of the admin flagging the record.
        reason: Optional free-text reason.

    Returns:
        Updated ``SLARecordResponse``.

    Raises:
        HTTPException 404: Record not found or wrong account.
        HTTPException 409: Record is already flagged for review.
    """
    row = await _fetch_record(db, record_id, account_id)

    if row.flagged_for_review:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Driver SLA record is already flagged for review.",
        )

    row.flagged_for_review = True
    row.flagged_by_id = flagged_by_id
    row.flagged_at = datetime.now(tz=timezone.utc)
    row.flag_reason = reason

    await db.commit()
    await db.refresh(row)
    return _record_to_response(row)


# ---------------------------------------------------------------------------
# list_flagged_drivers
# ---------------------------------------------------------------------------


async def list_flagged_drivers(
    db: AsyncSession,
    account_id: int,
    *,
    skip: int = 0,
    limit: int = 100,
) -> list[SLARecordResponse]:
    """Return all flagged driver SLA records for a corporate account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        skip: Records to skip (default 0).
        limit: Max records to return (default 100).

    Returns:
        List of ``SLARecordResponse`` where flagged_for_review is True.
    """
    stmt = (
        select(CorporateDriverSLARecord)
        .where(
            CorporateDriverSLARecord.account_id == account_id,
            CorporateDriverSLARecord.flagged_for_review == True,  # noqa: E712
        )
        .order_by(CorporateDriverSLARecord.flagged_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_record_to_response(r) for r in rows]
