"""Service layer for Corporate SLA Policies & Compliance Reporting.

Enterprise corporate accounts define SLA policies with contractual quality
targets.  Each ride is evaluated against the active policy and the result
is stored as an immutable snapshot.  Admins can query compliance summaries,
monthly trends, and breach lists.

Public surface
--------------
create_sla_policy(db, account_id, data, created_by_id) -> SLAPolicyResponse
get_sla_policy(db, policy_id, account_id) -> SLAPolicyResponse
list_sla_policies(db, account_id, *, is_active) -> SLAPolicyListResponse
update_sla_policy(db, policy_id, account_id, data) -> SLAPolicyResponse
activate_sla_policy(db, policy_id, account_id) -> SLAPolicyResponse
deactivate_sla_policy(db, policy_id, account_id) -> SLAPolicyResponse
delete_sla_policy(db, policy_id, account_id) -> None
record_sla_evaluation(db, account_id, ride_id, member_id, *, ...) -> SLARideRecordResponse
get_sla_compliance_summary(db, account_id, *, year, month) -> SLAComplianceSummary
get_sla_compliance_trend(db, account_id, *, months) -> SLATrendResponse
list_sla_breaches(db, account_id, *, year, month, limit, offset) -> SLARideRecordListResponse
list_all_platform(db, *, account_id) -> SLAPolicyListResponse
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import extract, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_sla_policy import CorporateSLAPolicy, CorporateSLARideRecord
from app.schemas.corporate_sla_policy import (
    DimensionSummary,
    SLAComplianceSummary,
    SLAEvaluationCreate,
    SLAPolicyCreate,
    SLAPolicyListResponse,
    SLAPolicyResponse,
    SLAPolicyUpdate,
    SLARideRecordListResponse,
    SLARideRecordResponse,
    SLATrendEntry,
    SLATrendResponse,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _policy_to_response(policy: CorporateSLAPolicy) -> SLAPolicyResponse:
    """Convert a CorporateSLAPolicy ORM instance to a response schema."""
    return SLAPolicyResponse(
        id=policy.id,
        account_id=policy.account_id,
        name=policy.name,
        max_wait_time_minutes=policy.max_wait_time_minutes,
        min_driver_rating=(
            Decimal(str(policy.min_driver_rating))
            if policy.min_driver_rating is not None
            else None
        ),
        on_time_window_minutes=policy.on_time_window_minutes,
        target_completion_rate_pct=(
            Decimal(str(policy.target_completion_rate_pct))
            if policy.target_completion_rate_pct is not None
            else None
        ),
        is_active=policy.is_active,
        effective_from=policy.effective_from,
        effective_until=policy.effective_until,
        created_by_id=policy.created_by_id,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _record_to_response(record: CorporateSLARideRecord) -> SLARideRecordResponse:
    """Convert a CorporateSLARideRecord ORM instance to a response schema."""
    def _dec(v) -> Optional[Decimal]:
        return Decimal(str(v)) if v is not None else None

    return SLARideRecordResponse(
        id=record.id,
        account_id=record.account_id,
        policy_id=record.policy_id,
        ride_id=record.ride_id,
        member_id=record.member_id,
        wait_time_minutes=_dec(record.wait_time_minutes),
        driver_rating_at_time=_dec(record.driver_rating_at_time),
        was_scheduled_ride=record.was_scheduled_ride,
        scheduled_pickup_at=record.scheduled_pickup_at,
        actual_pickup_at=record.actual_pickup_at,
        arrival_delta_minutes=_dec(record.arrival_delta_minutes),
        wait_time_met=record.wait_time_met,
        driver_rating_met=record.driver_rating_met,
        on_time_met=record.on_time_met,
        overall_sla_met=record.overall_sla_met,
        evaluated_at=record.evaluated_at,
    )


async def _get_policy_row(
    db: AsyncSession,
    policy_id: uuid.UUID,
    account_id: int,
) -> CorporateSLAPolicy | None:
    """Return the policy for this (account, id) pair or None."""
    result = await db.execute(
        select(CorporateSLAPolicy).where(
            CorporateSLAPolicy.id == policy_id,
            CorporateSLAPolicy.account_id == account_id,
        )
    )
    return result.scalar_one_or_none()


async def _get_policy_or_404(
    db: AsyncSession,
    policy_id: uuid.UUID,
    account_id: int,
) -> CorporateSLAPolicy:
    """Return the policy or raise HTTP 404."""
    policy = await _get_policy_row(db, policy_id, account_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SLA policy not found.",
        )
    return policy


# ---------------------------------------------------------------------------
# Public service functions — policies
# ---------------------------------------------------------------------------


async def create_sla_policy(
    db: AsyncSession,
    account_id: int,
    data: SLAPolicyCreate,
    created_by_id: Optional[int] = None,
) -> SLAPolicyResponse:
    """Create a new SLA policy for the account.

    Raises HTTP 409 if an active policy with the same name already exists in
    the account.
    """
    existing = await db.execute(
        select(CorporateSLAPolicy).where(
            CorporateSLAPolicy.account_id == account_id,
            CorporateSLAPolicy.name == data.name,
            CorporateSLAPolicy.is_active.is_(True),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active SLA policy with this name already exists for the account.",
        )

    policy = CorporateSLAPolicy(
        account_id=account_id,
        name=data.name,
        max_wait_time_minutes=data.max_wait_time_minutes,
        min_driver_rating=data.min_driver_rating,
        on_time_window_minutes=data.on_time_window_minutes,
        target_completion_rate_pct=data.target_completion_rate_pct,
        is_active=data.is_active,
        effective_from=data.effective_from,
        effective_until=data.effective_until,
        created_by_id=created_by_id,
    )

    # If creating as active, deactivate any currently-active policy first.
    if data.is_active:
        await _deactivate_current_active(db, account_id, exclude_id=None)

    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return _policy_to_response(policy)


async def get_sla_policy(
    db: AsyncSession,
    policy_id: uuid.UUID,
    account_id: int,
) -> SLAPolicyResponse:
    """Return a specific SLA policy by ID.

    Raises HTTP 404 if not found or belongs to a different account.
    """
    policy = await _get_policy_or_404(db, policy_id, account_id)
    return _policy_to_response(policy)


async def list_sla_policies(
    db: AsyncSession,
    account_id: int,
    *,
    is_active: Optional[bool] = None,
) -> SLAPolicyListResponse:
    """List all SLA policies for the account, sorted by name.

    Optional filter:
      - ``is_active``: True → active only; False → inactive only.
    """
    stmt = select(CorporateSLAPolicy).where(
        CorporateSLAPolicy.account_id == account_id
    )
    if is_active is not None:
        stmt = stmt.where(CorporateSLAPolicy.is_active == is_active)
    stmt = stmt.order_by(CorporateSLAPolicy.name)

    result = await db.execute(stmt)
    policies = result.scalars().all()
    return SLAPolicyListResponse(
        items=[_policy_to_response(p) for p in policies],
        total=len(policies),
    )


async def update_sla_policy(
    db: AsyncSession,
    policy_id: uuid.UUID,
    account_id: int,
    data: SLAPolicyUpdate,
) -> SLAPolicyResponse:
    """Partially update an SLA policy.

    Raises HTTP 404 if not found.
    Raises HTTP 409 on name collision with another policy in the same account.
    """
    policy = await _get_policy_or_404(db, policy_id, account_id)

    update_data = data.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] != policy.name:
        collision = await db.execute(
            select(CorporateSLAPolicy).where(
                CorporateSLAPolicy.account_id == account_id,
                CorporateSLAPolicy.name == update_data["name"],
                CorporateSLAPolicy.id != policy_id,
            )
        )
        if collision.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An SLA policy with this name already exists for the account.",
            )

    for field, value in update_data.items():
        setattr(policy, field, value)

    await db.commit()
    await db.refresh(policy)
    return _policy_to_response(policy)


async def _deactivate_current_active(
    db: AsyncSession,
    account_id: int,
    exclude_id: Optional[uuid.UUID],
) -> None:
    """Deactivate any currently-active policy for the account.

    ``exclude_id`` allows the caller to skip a specific policy (used when
    a policy is being activated so it is not immediately re-deactivated).
    """
    stmt = select(CorporateSLAPolicy).where(
        CorporateSLAPolicy.account_id == account_id,
        CorporateSLAPolicy.is_active.is_(True),
    )
    if exclude_id is not None:
        stmt = stmt.where(CorporateSLAPolicy.id != exclude_id)
    result = await db.execute(stmt)
    for p in result.scalars().all():
        p.is_active = False


async def activate_sla_policy(
    db: AsyncSession,
    policy_id: uuid.UUID,
    account_id: int,
) -> SLAPolicyResponse:
    """Activate an SLA policy.

    Deactivates any currently-active policy for the account first.

    Raises HTTP 404 if not found.
    Raises HTTP 409 if the policy is already active.
    """
    policy = await _get_policy_or_404(db, policy_id, account_id)
    if policy.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SLA policy is already active.",
        )
    await _deactivate_current_active(db, account_id, exclude_id=policy_id)
    policy.is_active = True
    await db.commit()
    await db.refresh(policy)
    return _policy_to_response(policy)


async def deactivate_sla_policy(
    db: AsyncSession,
    policy_id: uuid.UUID,
    account_id: int,
) -> SLAPolicyResponse:
    """Deactivate an active SLA policy.

    Raises HTTP 404 if not found.
    Raises HTTP 409 if already inactive.
    """
    policy = await _get_policy_or_404(db, policy_id, account_id)
    if not policy.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SLA policy is already inactive.",
        )
    policy.is_active = False
    await db.commit()
    await db.refresh(policy)
    return _policy_to_response(policy)


async def delete_sla_policy(
    db: AsyncSession,
    policy_id: uuid.UUID,
    account_id: int,
) -> None:
    """Hard-delete an SLA policy.

    Raises HTTP 404 if not found.
    Raises HTTP 409 if the policy is active — deactivate it first.
    """
    policy = await _get_policy_or_404(db, policy_id, account_id)
    if policy.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete an active SLA policy. Deactivate it first.",
        )
    await db.delete(policy)
    await db.commit()


# ---------------------------------------------------------------------------
# Public service functions — ride evaluation
# ---------------------------------------------------------------------------


async def record_sla_evaluation(
    db: AsyncSession,
    account_id: int,
    ride_id: Optional[int],
    member_id: Optional[int],
    *,
    wait_time_minutes: Optional[Decimal] = None,
    driver_rating: Optional[Decimal] = None,
    was_scheduled_ride: bool = False,
    scheduled_pickup_at: Optional[datetime] = None,
    actual_pickup_at: Optional[datetime] = None,
) -> SLARideRecordResponse:
    """Record a per-ride SLA evaluation snapshot.

    Finds the active policy for the account (if any) and evaluates each
    configured dimension.  If no active policy exists all threshold fields
    are NULL/False and ``overall_sla_met`` is True (no SLA in force).
    """
    # Find active policy.
    policy_result = await db.execute(
        select(CorporateSLAPolicy).where(
            CorporateSLAPolicy.account_id == account_id,
            CorporateSLAPolicy.is_active.is_(True),
        )
    )
    policy: CorporateSLAPolicy | None = policy_result.scalar_one_or_none()

    # Compute arrival delta if both timestamps are present.
    arrival_delta: Optional[Decimal] = None
    if scheduled_pickup_at is not None and actual_pickup_at is not None:
        delta_seconds = (
            actual_pickup_at - scheduled_pickup_at
        ).total_seconds()
        arrival_delta = Decimal(str(round(delta_seconds / 60, 2)))

    wait_time_met: Optional[bool] = None
    driver_rating_met: Optional[bool] = None
    on_time_met: Optional[bool] = None
    overall_sla_met: bool = True

    if policy is not None:
        # Evaluate wait-time dimension.
        if policy.max_wait_time_minutes is not None:
            if wait_time_minutes is not None:
                wait_time_met = float(wait_time_minutes) <= float(
                    policy.max_wait_time_minutes
                )
            else:
                wait_time_met = None  # Data not available; do not penalise.

        # Evaluate driver-rating dimension.
        if policy.min_driver_rating is not None:
            if driver_rating is not None:
                driver_rating_met = float(driver_rating) >= float(
                    policy.min_driver_rating
                )
            else:
                driver_rating_met = None

        # Evaluate on-time dimension (scheduled rides only).
        if policy.on_time_window_minutes is not None and was_scheduled_ride:
            if arrival_delta is not None:
                on_time_met = float(arrival_delta) <= float(
                    policy.on_time_window_minutes
                )
            else:
                on_time_met = None

        # overall_sla_met is True only if every *evaluated* (non-None) dimension is met.
        dimension_results = [
            v for v in (wait_time_met, driver_rating_met, on_time_met)
            if v is not None
        ]
        overall_sla_met = all(dimension_results) if dimension_results else True

    record = CorporateSLARideRecord(
        account_id=account_id,
        policy_id=policy.id if policy is not None else None,
        ride_id=ride_id,
        member_id=member_id,
        wait_time_minutes=wait_time_minutes,
        driver_rating_at_time=driver_rating,
        was_scheduled_ride=was_scheduled_ride,
        scheduled_pickup_at=scheduled_pickup_at,
        actual_pickup_at=actual_pickup_at,
        arrival_delta_minutes=arrival_delta,
        wait_time_met=wait_time_met,
        driver_rating_met=driver_rating_met,
        on_time_met=on_time_met,
        overall_sla_met=overall_sla_met,
        evaluated_at=datetime.now(tz=timezone.utc),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return _record_to_response(record)


# ---------------------------------------------------------------------------
# Public service functions — compliance reporting
# ---------------------------------------------------------------------------


async def get_sla_compliance_summary(
    db: AsyncSession,
    account_id: int,
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> SLAComplianceSummary:
    """Return overall SLA compliance summary for the account.

    When ``year`` and ``month`` are both provided, restricts to that calendar
    month; otherwise returns all-time figures.
    """
    stmt = select(CorporateSLARideRecord).where(
        CorporateSLARideRecord.account_id == account_id
    )
    if year is not None and month is not None:
        stmt = stmt.where(
            extract("year", CorporateSLARideRecord.evaluated_at) == year,
            extract("month", CorporateSLARideRecord.evaluated_at) == month,
        )

    result = await db.execute(stmt)
    records = result.scalars().all()

    total = len(records)
    met_count = sum(1 for r in records if r.overall_sla_met)
    breach_count = total - met_count
    compliance_pct = (met_count / total * 100.0) if total > 0 else None

    # Per-dimension summaries.
    def _dim(attr: str) -> DimensionSummary:
        applicable = [r for r in records if getattr(r, attr) is not None]
        dim_total = len(applicable)
        dim_met = sum(1 for r in applicable if getattr(r, attr) is True)
        dim_pct = (dim_met / dim_total * 100.0) if dim_total > 0 else None
        return DimensionSummary(total=dim_total, met=dim_met, pct=dim_pct)

    return SLAComplianceSummary(
        total_rides=total,
        sla_met_count=met_count,
        sla_breach_count=breach_count,
        compliance_pct=compliance_pct,
        by_dimension={
            "wait_time": _dim("wait_time_met"),
            "driver_rating": _dim("driver_rating_met"),
            "on_time": _dim("on_time_met"),
        },
    )


async def get_sla_compliance_trend(
    db: AsyncSession,
    account_id: int,
    *,
    months: int = 6,
) -> SLATrendResponse:
    """Return monthly SLA compliance trend for the most recent N months.

    Returns a list ordered from oldest to newest month.
    """
    stmt = select(CorporateSLARideRecord).where(
        CorporateSLARideRecord.account_id == account_id
    )
    result = await db.execute(stmt)
    records = result.scalars().all()

    # Group by (year, month).
    from collections import defaultdict

    bucket: dict[tuple[int, int], list[CorporateSLARideRecord]] = defaultdict(list)
    for r in records:
        key = (r.evaluated_at.year, r.evaluated_at.month)
        bucket[key].append(r)

    # Take the most recent `months` buckets.
    sorted_keys = sorted(bucket.keys(), reverse=True)[:months]
    sorted_keys = sorted(sorted_keys)  # oldest → newest for the response

    entries = []
    for year, month in sorted_keys:
        month_records = bucket[(year, month)]
        total = len(month_records)
        met = sum(1 for r in month_records if r.overall_sla_met)
        pct = (met / total * 100.0) if total > 0 else None
        entries.append(
            SLATrendEntry(
                year=year,
                month=month,
                total_rides=total,
                compliance_pct=pct,
            )
        )

    return SLATrendResponse(items=entries)


async def list_sla_breaches(
    db: AsyncSession,
    account_id: int,
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> SLARideRecordListResponse:
    """Return SLA breach records (overall_sla_met=False) for the account.

    Optionally filtered to a specific year/month.  Supports pagination via
    ``limit`` and ``offset``.
    """
    stmt = select(CorporateSLARideRecord).where(
        CorporateSLARideRecord.account_id == account_id,
        CorporateSLARideRecord.overall_sla_met.is_(False),
    )
    if year is not None and month is not None:
        stmt = stmt.where(
            extract("year", CorporateSLARideRecord.evaluated_at) == year,
            extract("month", CorporateSLARideRecord.evaluated_at) == month,
        )
    stmt = stmt.order_by(CorporateSLARideRecord.evaluated_at.desc())
    stmt = stmt.offset(offset).limit(limit)

    result = await db.execute(stmt)
    records = result.scalars().all()
    return SLARideRecordListResponse(
        items=[_record_to_response(r) for r in records],
        total=len(records),
    )


async def list_all_platform(
    db: AsyncSession,
    *,
    account_id: Optional[int] = None,
) -> SLAPolicyListResponse:
    """Platform-admin: list all SLA policies, optionally filtered by account."""
    stmt = select(CorporateSLAPolicy)
    if account_id is not None:
        stmt = stmt.where(CorporateSLAPolicy.account_id == account_id)
    stmt = stmt.order_by(
        CorporateSLAPolicy.account_id,
        CorporateSLAPolicy.name,
    )
    result = await db.execute(stmt)
    policies = result.scalars().all()
    return SLAPolicyListResponse(
        items=[_policy_to_response(p) for p in policies],
        total=len(policies),
    )
