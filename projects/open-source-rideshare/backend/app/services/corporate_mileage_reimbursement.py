"""Service functions for corporate mileage reimbursement.

Employees submit personal-vehicle mileage claims; admins configure per-mile
rates and approval thresholds; claims flow through a full lifecycle.

Public API
----------
get_or_create_policy        — upsert-on-read policy for an account
update_policy               — partial update of policy fields
get_policy                  — fetch policy; 404 if absent
create_claim                — create a draft claim with computed amount
get_claim                   — fetch one claim by id; 404 if not in account
list_member_claims          — claims for a specific member; optional status filter
update_claim                — update a draft claim; 409 if not draft
submit_claim                — submit a claim; auto-approves when under thresholds
review_claim                — approve or reject a submitted claim
mark_claim_paid             — mark an approved claim as paid
get_account_claim_summary   — aggregate stats for an account
list_all_platform           — platform-admin cross-account listing
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_mileage_reimbursement import (
    ClaimStatus,
    CorporateMileageClaim,
    CorporateMileagePolicy,
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _compute_amount(miles: Decimal, rate: Decimal) -> Decimal:
    return (Decimal(str(miles)) * Decimal(str(rate))).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


async def get_or_create_policy(
    db: AsyncSession,
    account_id: int,
    created_by_id: int,
) -> CorporateMileagePolicy:
    """Return the mileage policy for *account_id*, creating one with defaults if absent.

    Uses upsert-on-read semantics: the first call creates the row with the
    2024 IRS standard rate (0.6700 USD/mile); subsequent calls return the
    existing row.
    """
    result = await db.execute(
        select(CorporateMileagePolicy).where(
            CorporateMileagePolicy.account_id == account_id
        )
    )
    policy = result.scalar_one_or_none()
    if policy is not None:
        return policy

    policy = CorporateMileagePolicy(
        account_id=account_id,
        rate_per_mile=Decimal("0.6700"),
        created_by_id=created_by_id,
    )
    db.add(policy)
    await db.flush()
    return policy


async def update_policy(
    db: AsyncSession,
    account_id: int,
    **kwargs,
) -> CorporateMileagePolicy:
    """Partially update the mileage policy for *account_id*.

    Only keys present in *kwargs* are written.  Returns the updated policy.
    """
    result = await db.execute(
        select(CorporateMileagePolicy).where(
            CorporateMileagePolicy.account_id == account_id
        )
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mileage policy not found for this account.",
        )
    for key, value in kwargs.items():
        if value is not None or key in kwargs:
            setattr(policy, key, value)
    await db.flush()
    return policy


async def get_policy(
    db: AsyncSession,
    account_id: int,
) -> CorporateMileagePolicy:
    """Return the mileage policy for *account_id*.

    Raises 404 if no policy has been created yet.
    """
    result = await db.execute(
        select(CorporateMileagePolicy).where(
            CorporateMileagePolicy.account_id == account_id
        )
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mileage policy not found for this account.",
        )
    return policy


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


async def create_claim(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    trip_date,
    miles: Decimal,
    description: str,
    trip_purpose_id: Optional[int] = None,
    cost_center_id: Optional[int] = None,
) -> CorporateMileageClaim:
    """Create a draft mileage claim.

    Snapshots the current policy rate and computes amount_usd = miles × rate.
    Raises 422 if *miles* exceeds the policy max_miles_per_claim cap.
    """
    policy = await get_or_create_policy(db, account_id, member_id)

    if policy.max_miles_per_claim is not None:
        if Decimal(str(miles)) > Decimal(str(policy.max_miles_per_claim)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Claim exceeds max miles per claim ({policy.max_miles_per_claim})",
            )

    rate = Decimal(str(policy.rate_per_mile))
    amount = _compute_amount(Decimal(str(miles)), rate)

    claim = CorporateMileageClaim(
        account_id=account_id,
        member_id=member_id,
        trip_date=trip_date,
        miles=Decimal(str(miles)),
        rate_used_usd=rate,
        amount_usd=amount,
        description=description,
        trip_purpose_id=trip_purpose_id,
        cost_center_id=cost_center_id,
        status=ClaimStatus.DRAFT,
    )
    db.add(claim)
    await db.flush()
    return claim


async def get_claim(
    db: AsyncSession,
    account_id: int,
    claim_id: int,
) -> CorporateMileageClaim:
    """Return a claim by id within *account_id*.

    Raises 404 if not found.
    """
    result = await db.execute(
        select(CorporateMileageClaim).where(
            CorporateMileageClaim.id == claim_id,
            CorporateMileageClaim.account_id == account_id,
        )
    )
    claim = result.scalar_one_or_none()
    if claim is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mileage claim not found.",
        )
    return claim


async def list_member_claims(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    status_filter: Optional[ClaimStatus] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[CorporateMileageClaim]:
    """Return claims for *member_id* within *account_id*.

    Optionally filtered to a single *status_filter*.  Ordered by trip_date
    descending.
    """
    query = (
        select(CorporateMileageClaim)
        .where(
            CorporateMileageClaim.account_id == account_id,
            CorporateMileageClaim.member_id == member_id,
        )
        .order_by(CorporateMileageClaim.trip_date.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_filter is not None:
        query = query.where(CorporateMileageClaim.status == status_filter)
    result = await db.execute(query)
    return list(result.scalars().all())


async def update_claim(
    db: AsyncSession,
    account_id: int,
    claim_id: int,
    **kwargs,
) -> CorporateMileageClaim:
    """Update a draft claim.

    Raises 409 if the claim is not in draft status.
    Recomputes amount_usd when miles is updated.
    """
    claim = await get_claim(db, account_id, claim_id)
    if claim.status != ClaimStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft claims can be updated.",
        )
    for key, value in kwargs.items():
        setattr(claim, key, value)

    if "miles" in kwargs and kwargs["miles"] is not None:
        claim.amount_usd = _compute_amount(
            Decimal(str(claim.miles)), Decimal(str(claim.rate_used_usd))
        )

    await db.flush()
    return claim


async def submit_claim(
    db: AsyncSession,
    account_id: int,
    claim_id: int,
    member_id: int,
) -> CorporateMileageClaim:
    """Submit a draft claim.

    Raises 409 if the claim is not draft.
    Raises 422 if the policy requires a trip purpose and none is set.
    Auto-approves if amount_usd and miles are both under their respective
    policy thresholds (or when no thresholds are configured).
    """
    claim = await get_claim(db, account_id, claim_id)
    if claim.status != ClaimStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft claims can be submitted.",
        )

    policy = await get_or_create_policy(db, account_id, member_id)

    if policy.require_trip_purpose and claim.trip_purpose_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Trip purpose is required by policy",
        )

    claim.submitted_at = _now_utc()

    # Determine whether auto-approval applies.
    amount_ok = (
        policy.requires_approval_above_usd is None
        or Decimal(str(claim.amount_usd)) <= Decimal(str(policy.requires_approval_above_usd))
    )
    miles_ok = (
        policy.requires_approval_above_miles is None
        or Decimal(str(claim.miles)) <= Decimal(str(policy.requires_approval_above_miles))
    )

    if amount_ok and miles_ok:
        claim.status = ClaimStatus.APPROVED
    else:
        claim.status = ClaimStatus.SUBMITTED

    await db.flush()
    return claim


async def review_claim(
    db: AsyncSession,
    account_id: int,
    claim_id: int,
    reviewer_id: int,
    action: str,
    note: Optional[str] = None,
) -> CorporateMileageClaim:
    """Approve or reject a submitted claim.

    Raises 409 if the claim is not in submitted status.
    *action* must be 'approve' or 'reject'.
    """
    claim = await get_claim(db, account_id, claim_id)
    if claim.status != ClaimStatus.SUBMITTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only submitted claims can be reviewed.",
        )

    if action == "approve":
        claim.status = ClaimStatus.APPROVED
    else:
        claim.status = ClaimStatus.REJECTED

    claim.reviewed_by_id = reviewer_id
    claim.reviewed_at = _now_utc()
    claim.review_note = note
    await db.flush()
    return claim


async def mark_claim_paid(
    db: AsyncSession,
    account_id: int,
    claim_id: int,
    paid_by_id: int,
) -> CorporateMileageClaim:
    """Mark an approved claim as paid.

    Raises 409 if the claim is not in approved status.
    """
    claim = await get_claim(db, account_id, claim_id)
    if claim.status != ClaimStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only approved claims can be marked as paid.",
        )

    claim.status = ClaimStatus.PAID
    claim.paid_at = _now_utc()
    await db.flush()
    return claim


async def get_account_claim_summary(
    db: AsyncSession,
    account_id: int,
) -> dict:
    """Return aggregate statistics for *account_id*.

    Includes total claims, miles, amount, pending-approval counts, and a
    per-status breakdown.
    """
    # Per-status breakdown
    rows = await db.execute(
        select(
            CorporateMileageClaim.status,
            func.count(CorporateMileageClaim.id).label("cnt"),
            func.coalesce(func.sum(CorporateMileageClaim.miles), 0).label("total_miles"),
            func.coalesce(func.sum(CorporateMileageClaim.amount_usd), 0).label("total_amount"),
        )
        .where(CorporateMileageClaim.account_id == account_id)
        .group_by(CorporateMileageClaim.status)
    )
    by_status = []
    total_claims = 0
    total_miles = Decimal("0")
    total_amount = Decimal("0")
    pending_count = 0
    pending_amount = Decimal("0")

    for row in rows:
        s, cnt, miles_sum, amount_sum = row
        by_status.append(
            {
                "status": s,
                "count": cnt,
                "total_amount_usd": Decimal(str(amount_sum)),
            }
        )
        total_claims += cnt
        total_miles += Decimal(str(miles_sum))
        total_amount += Decimal(str(amount_sum))
        if s == ClaimStatus.SUBMITTED:
            pending_count = cnt
            pending_amount = Decimal(str(amount_sum))

    return {
        "account_id": account_id,
        "total_claims": total_claims,
        "total_miles": total_miles,
        "total_amount_usd": total_amount,
        "pending_approval_count": pending_count,
        "pending_approval_amount_usd": pending_amount,
        "by_status": by_status,
    }


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
    status_filter: Optional[ClaimStatus] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[CorporateMileageClaim]:
    """Platform-admin: list mileage claims across all accounts.

    Optionally filtered by *account_id* or *status_filter*.
    """
    query = (
        select(CorporateMileageClaim)
        .order_by(
            CorporateMileageClaim.account_id,
            CorporateMileageClaim.trip_date.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    if account_id is not None:
        query = query.where(CorporateMileageClaim.account_id == account_id)
    if status_filter is not None:
        query = query.where(CorporateMileageClaim.status == status_filter)
    result = await db.execute(query)
    return list(result.scalars().all())
