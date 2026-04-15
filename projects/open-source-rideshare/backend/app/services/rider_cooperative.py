"""Rider cooperative membership, voting, and dividend service.

Provides:
  apply_for_membership     — rider applies to join the cooperative
  get_membership           — fetch a rider's membership record
  resign_membership        — rider voluntarily resigns
  approve_membership       — admin approves a pending application
  suspend_membership       — admin suspends an active member
  reinstate_membership     — admin reinstates a suspended member
  list_members             — admin: paginated list of all rider members
  get_summary              — admin: platform-wide stats

  list_open_proposals      — proposals rider-members can vote on
  cast_vote                — rider-member casts a vote on a proposal
  get_proposal_tally       — rider-side vote tally for a proposal
  get_my_vote              — fetch caller's vote on a proposal

  generate_rider_shares    — admin: compute rider dividend shares for a period
  list_my_dividends        — rider: list own dividend history
  list_dividend_shares     — admin: list all shares for a dividend
  mark_share_paid          — admin: mark a rider share as paid
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_dividend import CooperativeDividend, DividendStatus
from app.models.driver_proposal import DriverProposal, ProposalStatus
from app.models.ride import Ride, RideStatus
from app.models.rider_cooperative import (
    MAX_VOTING_WEIGHT,
    RiderCoopMembership,
    RiderCoopVote,
    RiderDividendShare,
    RiderDividendShareStatus,
    RiderMemberStatus,
    RiderVoteChoice,
)
from app.models.user import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_voting_weight(lifetime_rides: int) -> int:
    return min(1 + lifetime_rides // 100, MAX_VOTING_WEIGHT)


async def _get_membership_or_404(
    db: AsyncSession, rider_id: int
) -> RiderCoopMembership:
    result = await db.execute(
        select(RiderCoopMembership).where(
            RiderCoopMembership.rider_id == rider_id,
            RiderCoopMembership.status != RiderMemberStatus.resigned,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active cooperative membership found for this rider.",
        )
    return membership


# ---------------------------------------------------------------------------
# Membership lifecycle
# ---------------------------------------------------------------------------

async def apply_for_membership(db: AsyncSession, rider: User) -> RiderCoopMembership:
    """Rider submits a membership application. One pending/active per rider."""
    from fastapi import HTTPException, status as http_status

    existing = await db.execute(
        select(RiderCoopMembership).where(
            RiderCoopMembership.rider_id == rider.id,
            RiderCoopMembership.status.in_(
                [RiderMemberStatus.applicant, RiderMemberStatus.member, RiderMemberStatus.suspended]
            ),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Rider already has an active or pending cooperative membership.",
        )

    membership = RiderCoopMembership(
        rider_id=rider.id,
        status=RiderMemberStatus.applicant,
        lifetime_rides=0,
        voting_weight=1,
    )
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return membership


async def get_membership(db: AsyncSession, rider_id: int) -> Optional[RiderCoopMembership]:
    result = await db.execute(
        select(RiderCoopMembership).where(
            RiderCoopMembership.rider_id == rider_id,
            RiderCoopMembership.status != RiderMemberStatus.resigned,
        )
    )
    return result.scalar_one_or_none()


async def resign_membership(db: AsyncSession, rider: User) -> RiderCoopMembership:
    """Rider voluntarily leaves the cooperative."""
    from fastapi import HTTPException, status as http_status

    membership = await _get_membership_or_404(db, rider.id)
    if membership.status == RiderMemberStatus.applicant:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Cannot resign — application is still pending. Withdraw it instead.",
        )
    membership.status = RiderMemberStatus.resigned
    membership.resigned_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(membership)
    return membership


async def withdraw_application(db: AsyncSession, rider: User) -> RiderCoopMembership:
    """Rider withdraws a pending application."""
    from fastapi import HTTPException, status as http_status

    result = await db.execute(
        select(RiderCoopMembership).where(
            RiderCoopMembership.rider_id == rider.id,
            RiderCoopMembership.status == RiderMemberStatus.applicant,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="No pending application found.",
        )
    membership.status = RiderMemberStatus.resigned
    membership.resigned_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(membership)
    return membership


# ---------------------------------------------------------------------------
# Admin membership management
# ---------------------------------------------------------------------------

async def approve_membership(
    db: AsyncSession, membership_id: int, admin: User
) -> RiderCoopMembership:
    from fastapi import HTTPException, status as http_status

    result = await db.execute(
        select(RiderCoopMembership).where(RiderCoopMembership.id == membership_id)
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Membership not found.")
    if membership.status != RiderMemberStatus.applicant:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve — membership status is '{membership.status}'.",
        )
    membership.status = RiderMemberStatus.member
    membership.approved_at = datetime.now(timezone.utc)
    membership.reviewed_by_id = admin.id
    await db.commit()
    await db.refresh(membership)
    return membership


async def suspend_membership(
    db: AsyncSession, membership_id: int, admin: User, reason: Optional[str] = None
) -> RiderCoopMembership:
    from fastapi import HTTPException, status as http_status

    result = await db.execute(
        select(RiderCoopMembership).where(RiderCoopMembership.id == membership_id)
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Membership not found.")
    if membership.status != RiderMemberStatus.member:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot suspend — membership status is '{membership.status}'.",
        )
    membership.status = RiderMemberStatus.suspended
    membership.suspended_at = datetime.now(timezone.utc)
    membership.reviewed_by_id = admin.id
    membership.suspension_reason = reason
    await db.commit()
    await db.refresh(membership)
    return membership


async def reinstate_membership(
    db: AsyncSession, membership_id: int, admin: User
) -> RiderCoopMembership:
    from fastapi import HTTPException, status as http_status

    result = await db.execute(
        select(RiderCoopMembership).where(RiderCoopMembership.id == membership_id)
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Membership not found.")
    if membership.status != RiderMemberStatus.suspended:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reinstate — membership status is '{membership.status}'.",
        )
    membership.status = RiderMemberStatus.member
    membership.reviewed_by_id = admin.id
    membership.suspension_reason = None
    await db.commit()
    await db.refresh(membership)
    return membership


async def list_members(
    db: AsyncSession,
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[int, list[RiderCoopMembership]]:
    q = select(RiderCoopMembership)
    if status_filter:
        q = q.where(RiderCoopMembership.status == status_filter)
    count_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = count_result.scalar_one()
    result = await db.execute(
        q.order_by(RiderCoopMembership.applied_at.desc()).offset(skip).limit(limit)
    )
    return total, list(result.scalars().all())


async def get_summary(db: AsyncSession) -> dict:
    counts = await db.execute(
        select(RiderCoopMembership.status, func.count())
        .group_by(RiderCoopMembership.status)
    )
    by_status = {row[0]: row[1] for row in counts}

    paid_result = await db.execute(
        select(func.coalesce(func.sum(RiderDividendShare.amount_usd), 0)).where(
            RiderDividendShare.status == RiderDividendShareStatus.paid
        )
    )
    pending_result = await db.execute(
        select(func.coalesce(func.sum(RiderDividendShare.amount_usd), 0)).where(
            RiderDividendShare.status == RiderDividendShareStatus.pending
        )
    )

    return {
        "total_members": sum(by_status.values()),
        "active_members": by_status.get(RiderMemberStatus.member, 0),
        "applicants_pending": by_status.get(RiderMemberStatus.applicant, 0),
        "suspended_members": by_status.get(RiderMemberStatus.suspended, 0),
        "resigned_members": by_status.get(RiderMemberStatus.resigned, 0),
        "total_dividends_paid_usd": float(paid_result.scalar_one()),
        "total_dividends_pending_usd": float(pending_result.scalar_one()),
    }


# ---------------------------------------------------------------------------
# Voting
# ---------------------------------------------------------------------------

async def list_open_proposals(
    db: AsyncSession, skip: int = 0, limit: int = 20
) -> list[DriverProposal]:
    result = await db.execute(
        select(DriverProposal)
        .where(DriverProposal.status == ProposalStatus.open)
        .order_by(DriverProposal.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def cast_vote(
    db: AsyncSession, rider: User, proposal_id: int, choice: str
) -> RiderCoopVote:
    from fastapi import HTTPException, status as http_status

    # Must be an active member
    membership = await get_membership(db, rider.id)
    if membership is None or membership.status != RiderMemberStatus.member:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Only active cooperative members can vote.",
        )

    # Proposal must be open
    proposal = await db.get(DriverProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Proposal not found.")
    if proposal.status != ProposalStatus.open:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Voting is not open for this proposal (status: {proposal.status}).",
        )

    # No duplicate votes
    existing = await db.execute(
        select(RiderCoopVote).where(
            RiderCoopVote.proposal_id == proposal_id,
            RiderCoopVote.membership_id == membership.id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="You have already voted on this proposal.",
        )

    vote = RiderCoopVote(
        proposal_id=proposal_id,
        membership_id=membership.id,
        rider_id=rider.id,
        choice=RiderVoteChoice(choice),
        voting_weight=membership.voting_weight,
    )
    db.add(vote)
    await db.commit()
    await db.refresh(vote)
    return vote


async def get_my_vote(
    db: AsyncSession, rider: User, proposal_id: int
) -> Optional[RiderCoopVote]:
    membership = await get_membership(db, rider.id)
    if membership is None:
        return None
    result = await db.execute(
        select(RiderCoopVote).where(
            RiderCoopVote.proposal_id == proposal_id,
            RiderCoopVote.membership_id == membership.id,
        )
    )
    return result.scalar_one_or_none()


async def get_proposal_tally(
    db: AsyncSession, rider: User, proposal_id: int
) -> dict:
    rows = await db.execute(
        select(RiderCoopVote.choice, func.count(), func.sum(RiderCoopVote.voting_weight))
        .where(RiderCoopVote.proposal_id == proposal_id)
        .group_by(RiderCoopVote.choice)
    )
    counts: dict[str, int] = {}
    weights: dict[str, int] = {}
    total_voters = 0
    for row in rows:
        choice_val, cnt, wgt = row
        counts[choice_val] = cnt
        weights[choice_val] = int(wgt or 0)
        total_voters += cnt

    my_vote = await get_my_vote(db, rider, proposal_id)

    return {
        "proposal_id": proposal_id,
        "yes_votes": counts.get("yes", 0),
        "no_votes": counts.get("no", 0),
        "abstain_votes": counts.get("abstain", 0),
        "yes_weight": weights.get("yes", 0),
        "no_weight": weights.get("no", 0),
        "abstain_weight": weights.get("abstain", 0),
        "total_voters": total_voters,
        "my_vote": my_vote.choice if my_vote else None,
    }


# ---------------------------------------------------------------------------
# Dividend shares
# ---------------------------------------------------------------------------

async def generate_rider_shares(
    db: AsyncSession,
    dividend_id: int,
    rider_surplus_usd: float,
    admin: User,
) -> list[RiderDividendShare]:
    """Compute and persist rider dividend shares for an approved dividend period."""
    from fastapi import HTTPException, status as http_status

    dividend = await db.get(CooperativeDividend, dividend_id)
    if dividend is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Dividend not found.")
    if dividend.status not in (DividendStatus.approved, DividendStatus.distributed):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Dividend must be approved before generating rider shares (status: {dividend.status}).",
        )

    # Idempotency guard: don't double-generate
    existing_check = await db.execute(
        select(func.count()).select_from(
            select(RiderDividendShare)
            .where(RiderDividendShare.dividend_id == dividend_id)
            .subquery()
        )
    )
    if existing_check.scalar_one() > 0:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Rider shares for this dividend have already been generated.",
        )

    # Quarter date range for qualifying rides
    q_start_month = (dividend.quarter - 1) * 3 + 1
    q_end_month = dividend.quarter * 3
    from datetime import date
    period_start = datetime(dividend.year, q_start_month, 1, tzinfo=timezone.utc)
    if q_end_month == 12:
        period_end = datetime(dividend.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        period_end = datetime(dividend.year, q_end_month + 1, 1, tzinfo=timezone.utc)

    # Fetch active members
    members_result = await db.execute(
        select(RiderCoopMembership).where(
            RiderCoopMembership.status == RiderMemberStatus.member
        )
    )
    members = list(members_result.scalars().all())
    if not members:
        return []

    # Count completed rides per rider in the period
    rider_ids = [m.rider_id for m in members]
    ride_counts_result = await db.execute(
        select(Ride.rider_id, func.count())
        .where(
            Ride.rider_id.in_(rider_ids),
            Ride.status == RideStatus.completed,
            Ride.created_at >= period_start,
            Ride.created_at < period_end,
        )
        .group_by(Ride.rider_id)
    )
    ride_counts: dict[int, int] = {row[0]: row[1] for row in ride_counts_result}

    total_qualifying_rides = sum(ride_counts.values())
    if total_qualifying_rides == 0:
        return []

    shares: list[RiderDividendShare] = []
    membership_by_rider = {m.rider_id: m for m in members}

    for rider_id, rides in ride_counts.items():
        if rides == 0:
            continue
        membership = membership_by_rider[rider_id]
        share_pct = rides / total_qualifying_rides
        amount_usd = round(rider_surplus_usd * share_pct, 2)

        # Update lifetime rides on membership
        membership.lifetime_rides = (membership.lifetime_rides or 0) + rides
        membership.voting_weight = _compute_voting_weight(membership.lifetime_rides)

        share = RiderDividendShare(
            dividend_id=dividend_id,
            membership_id=membership.id,
            rider_id=rider_id,
            qualifying_rides=rides,
            share_pct=round(share_pct * 100, 4),
            amount_usd=amount_usd,
            status=RiderDividendShareStatus.pending,
        )
        db.add(share)
        shares.append(share)

    await db.commit()
    for share in shares:
        await db.refresh(share)
    return shares


async def list_my_dividends(
    db: AsyncSession, rider: User, skip: int = 0, limit: int = 20
) -> tuple[int, list[RiderDividendShare]]:
    q = select(RiderDividendShare).where(RiderDividendShare.rider_id == rider.id)
    count_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = count_result.scalar_one()
    result = await db.execute(
        q.order_by(RiderDividendShare.id.desc()).offset(skip).limit(limit)
    )
    return total, list(result.scalars().all())


async def list_dividend_shares(
    db: AsyncSession, dividend_id: int, skip: int = 0, limit: int = 50
) -> tuple[int, list[RiderDividendShare]]:
    q = select(RiderDividendShare).where(RiderDividendShare.dividend_id == dividend_id)
    count_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = count_result.scalar_one()
    result = await db.execute(
        q.order_by(RiderDividendShare.id).offset(skip).limit(limit)
    )
    return total, list(result.scalars().all())


async def mark_share_paid(
    db: AsyncSession, share_id: int, admin: User
) -> RiderDividendShare:
    from fastapi import HTTPException, status as http_status

    result = await db.execute(
        select(RiderDividendShare).where(RiderDividendShare.id == share_id)
    )
    share = result.scalar_one_or_none()
    if share is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Dividend share not found.")
    if share.status != RiderDividendShareStatus.pending:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Share status is '{share.status}' — cannot mark as paid.",
        )
    share.status = RiderDividendShareStatus.paid
    share.paid_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(share)
    return share
