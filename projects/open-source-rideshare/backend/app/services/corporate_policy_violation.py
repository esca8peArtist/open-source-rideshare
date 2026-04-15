"""Service layer for Corporate Policy Violations.

Violations are append-only audit records written when an employee's corporate
ride booking breaks the account's ride policy.  Admins can list, filter, and
acknowledge violations.  Platform-admins have cross-account views.

All functions are async and require a SQLAlchemy ``AsyncSession``.

Public surface
--------------
record_violation(db, account_id, member_id, violation_type, *, details,
                 ride_id, policy_snapshot)
    -> ViolationResponse
get_violation(db, violation_id, account_id)           -> ViolationResponse
list_violations(db, account_id, *, member_id, violation_type,
                is_acknowledged, from_dt, to_dt)       -> list[ViolationResponse]
acknowledge_violation(db, violation_id, account_id, acknowledged_by_id,
                      note)                            -> ViolationResponse
bulk_acknowledge_violations(db, account_id, violation_ids, acknowledged_by_id,
                            note)                      -> list[ViolationResponse]
get_violation_summary(db, account_id, *, period_days)  -> ViolationSummaryResponse
list_all_violations(db, *, account_id, violation_type,
                    is_acknowledged)                   -> list[ViolationResponse]
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_policy_violation import CorporatePolicyViolation
from app.schemas.corporate_policy_violation import (
    TopOffender,
    ViolationResponse,
    ViolationSummaryResponse,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(row: CorporatePolicyViolation) -> ViolationResponse:
    """Convert an ORM row to a ViolationResponse."""
    return ViolationResponse.model_validate(row)


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def record_violation(
    db: AsyncSession,
    *,
    account_id: int,
    member_id: int,
    violation_type: str,
    violation_details: Optional[Dict[str, Any]] = None,
    ride_id: Optional[int] = None,
    policy_snapshot: Optional[Dict[str, Any]] = None,
) -> ViolationResponse:
    """Write a new policy violation record.

    This function is intentionally permissive — it does not validate whether
    the violation_type string is a known enum value, to allow future extension
    without a service-layer change.  Schema validation at the API boundary
    ensures valid types for public endpoints.

    Args:
        db:               Async DB session.
        account_id:       Corporate account the violation belongs to.
        member_id:        Employee whose booking triggered the violation.
        violation_type:   Category string (see ViolationType enum).
        violation_details: Optional JSONB context blob.
        ride_id:          Optional FK to the ride that triggered the check.
        policy_snapshot:  Optional JSONB copy of the policy in effect.

    Returns:
        ViolationResponse with the newly created violation.
    """
    row = CorporatePolicyViolation(
        account_id=account_id,
        member_id=member_id,
        ride_id=ride_id,
        violation_type=violation_type,
        violation_details=violation_details,
        policy_snapshot=policy_snapshot,
        is_acknowledged=False,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


async def get_violation(
    db: AsyncSession,
    violation_id: int,
    account_id: int,
) -> ViolationResponse:
    """Return a single violation by ID, scoped to the given account.

    Raises HTTP 404 when the violation does not exist or belongs to a
    different account.
    """
    result = await db.execute(
        select(CorporatePolicyViolation).where(
            and_(
                CorporatePolicyViolation.id == violation_id,
                CorporatePolicyViolation.account_id == account_id,
            )
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy violation not found.",
        )
    return _to_response(row)


async def list_violations(
    db: AsyncSession,
    account_id: int,
    *,
    member_id: Optional[int] = None,
    violation_type: Optional[str] = None,
    is_acknowledged: Optional[bool] = None,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ViolationResponse]:
    """List violations for a corporate account with optional filters.

    Args:
        db:              Async DB session.
        account_id:      Corporate account to query.
        member_id:       Filter to a single employee.
        violation_type:  Filter by violation category.
        is_acknowledged: True/False to filter on acknowledgement status;
                         None returns all.
        from_dt:         Inclusive lower bound on created_at.
        to_dt:           Exclusive upper bound on created_at.
        limit:           Maximum rows to return (default 100).
        offset:          Skip this many rows (default 0).

    Returns:
        List of ViolationResponse sorted by created_at descending (newest first).
    """
    filters = [CorporatePolicyViolation.account_id == account_id]

    if member_id is not None:
        filters.append(CorporatePolicyViolation.member_id == member_id)
    if violation_type is not None:
        filters.append(CorporatePolicyViolation.violation_type == violation_type)
    if is_acknowledged is not None:
        filters.append(
            CorporatePolicyViolation.is_acknowledged.is_(is_acknowledged)
        )
    if from_dt is not None:
        filters.append(CorporatePolicyViolation.created_at >= from_dt)
    if to_dt is not None:
        filters.append(CorporatePolicyViolation.created_at < to_dt)

    result = await db.execute(
        select(CorporatePolicyViolation)
        .where(and_(*filters))
        .order_by(CorporatePolicyViolation.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


async def acknowledge_violation(
    db: AsyncSession,
    violation_id: int,
    account_id: int,
    acknowledged_by_id: int,
    note: Optional[str] = None,
) -> ViolationResponse:
    """Mark a violation as acknowledged by an admin.

    Raises HTTP 404 if the violation does not exist or is not on this account.
    Raises HTTP 409 if the violation is already acknowledged.

    Args:
        db:                  Async DB session.
        violation_id:        ID of the violation to acknowledge.
        account_id:          Corporate account scope guard.
        acknowledged_by_id:  User ID of the admin acknowledging.
        note:                Optional note to record alongside acknowledgement.

    Returns:
        Updated ViolationResponse.
    """
    result = await db.execute(
        select(CorporatePolicyViolation).where(
            and_(
                CorporatePolicyViolation.id == violation_id,
                CorporatePolicyViolation.account_id == account_id,
            )
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy violation not found.",
        )
    if row.is_acknowledged:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Policy violation is already acknowledged.",
        )

    row.is_acknowledged = True
    row.acknowledged_by_id = acknowledged_by_id
    row.acknowledged_at = datetime.now(tz=timezone.utc)
    row.acknowledgement_note = note

    await db.commit()
    await db.refresh(row)
    return _to_response(row)


async def bulk_acknowledge_violations(
    db: AsyncSession,
    account_id: int,
    violation_ids: list[int],
    acknowledged_by_id: int,
    note: Optional[str] = None,
) -> list[ViolationResponse]:
    """Acknowledge multiple violations in a single operation.

    Only acknowledges violations that belong to ``account_id`` and are not
    yet acknowledged.  Violations that are not found or are already
    acknowledged are silently skipped — no error is raised for them.

    Args:
        db:                  Async DB session.
        account_id:          Corporate account scope guard.
        violation_ids:       IDs of violations to acknowledge.
        acknowledged_by_id:  User ID of the admin acknowledging.
        note:                Note applied to all acknowledged violations.

    Returns:
        List of updated ViolationResponse for rows that were changed.
    """
    result = await db.execute(
        select(CorporatePolicyViolation).where(
            and_(
                CorporatePolicyViolation.id.in_(violation_ids),
                CorporatePolicyViolation.account_id == account_id,
                CorporatePolicyViolation.is_acknowledged.is_(False),
            )
        )
    )
    rows = result.scalars().all()

    now = datetime.now(tz=timezone.utc)
    acknowledged: list[ViolationResponse] = []
    for row in rows:
        row.is_acknowledged = True
        row.acknowledged_by_id = acknowledged_by_id
        row.acknowledged_at = now
        row.acknowledgement_note = note

    if rows:
        await db.commit()
        for row in rows:
            await db.refresh(row)
            acknowledged.append(_to_response(row))

    return acknowledged


async def get_violation_summary(
    db: AsyncSession,
    account_id: int,
    *,
    period_days: int = 30,
) -> ViolationSummaryResponse:
    """Compute aggregate violation statistics for an account.

    Args:
        db:          Async DB session.
        account_id:  Corporate account to summarise.
        period_days: How many days back to include (default 30).

    Returns:
        ViolationSummaryResponse with counts by type, unacknowledged total,
        and top offenders.
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=period_days)

    # Fetch all violations in the period
    result = await db.execute(
        select(CorporatePolicyViolation).where(
            and_(
                CorporatePolicyViolation.account_id == account_id,
                CorporatePolicyViolation.created_at >= cutoff,
            )
        )
    )
    rows = result.scalars().all()

    total = len(rows)
    unacknowledged = sum(1 for r in rows if not r.is_acknowledged)
    by_type: Counter = Counter(r.violation_type for r in rows)
    member_counts: Counter = Counter(r.member_id for r in rows)

    top_offenders = [
        TopOffender(member_id=mid, count=cnt)
        for mid, cnt in member_counts.most_common(5)
    ]

    return ViolationSummaryResponse(
        total_violations=total,
        unacknowledged=unacknowledged,
        by_type=dict(by_type),
        top_offenders=top_offenders,
        period_days=period_days,
    )


async def list_all_violations(
    db: AsyncSession,
    *,
    account_id: Optional[int] = None,
    violation_type: Optional[str] = None,
    is_acknowledged: Optional[bool] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[ViolationResponse]:
    """List violations across all accounts (platform-admin use).

    Args:
        db:              Async DB session.
        account_id:      Optional filter to a single account.
        violation_type:  Optional filter by violation category.
        is_acknowledged: Optional filter on acknowledgement status.
        limit:           Maximum rows (default 200).
        offset:          Pagination offset (default 0).

    Returns:
        List of ViolationResponse sorted by created_at descending.
    """
    filters = []

    if account_id is not None:
        filters.append(CorporatePolicyViolation.account_id == account_id)
    if violation_type is not None:
        filters.append(CorporatePolicyViolation.violation_type == violation_type)
    if is_acknowledged is not None:
        filters.append(
            CorporatePolicyViolation.is_acknowledged.is_(is_acknowledged)
        )

    query = select(CorporatePolicyViolation).order_by(
        CorporatePolicyViolation.created_at.desc()
    )
    if filters:
        query = query.where(and_(*filters))
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]
