"""Service layer for Corporate Account Health Score.

Computes a 0–100 composite health score for a corporate account by querying
six data domains:

  Payment     — invoice payment history (unpaid/overdue finalized invoices)
  Compliance  — policy-violation ride approval denials and blackout breaches
  Credit      — prepaid credit balance vs. low-balance threshold
  Dispute     — open invoice disputes
  Contract    — active service contract coverage
  Suspension  — past suspension events

Each domain returns an integer sub-score (0–100).  The overall score is a
weighted average.  Every computation is persisted as an immutable snapshot so
historical trend data is preserved.

Public surface
--------------
compute_health_score(db, account_id, computed_by_id=None) -> HealthScoreResponse
get_latest_health_score(db, account_id) -> HealthScoreResponse | None
get_health_score_history(db, account_id, limit) -> list[HealthScoreResponse]
list_accounts_by_health(db, risk_level=None, below_score=None, skip, limit) -> list[HealthScoreResponse]
get_at_risk_summary(db) -> AtRiskSummaryResponse
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_account_contract import ContractStatus, CorporateAccountContract
from app.models.corporate_account_suspension import CorporateAccountSuspension
from app.models.corporate_credit_account import CorporateCreditAccount
from app.models.corporate_health_score import (
    CorporateAccountHealthScore,
    HealthRiskLevel,
    _risk_level_from_score,
)
from app.models.corporate_invoice import CorporateInvoice, InvoiceStatus
from app.models.corporate_invoice_dispute import DisputeStatus, CorporateInvoiceDispute
from app.models.corporate_ride_approval import (
    ApprovalStatus,
    CorporateRideApproval,
)
from app.schemas.corporate_health_score import (
    AtRiskSummaryResponse,
    HealthScoreResponse,
    RiskDistribution,
)


# ---------------------------------------------------------------------------
# Score weights (must sum to 1.0)
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "payment": 0.30,
    "compliance": 0.20,
    "credit": 0.20,
    "dispute": 0.15,
    "contract": 0.10,
    "suspension": 0.05,
}


# ---------------------------------------------------------------------------
# Sub-score computation helpers
# ---------------------------------------------------------------------------


async def _compute_payment_score(db: AsyncSession, account_id: int) -> tuple[int, dict]:
    """Score based on finalized invoices that remain unpaid.

    100 — no unpaid finalized invoices.
    Deduct 20 points per unpaid finalized invoice, floor 0.

    Returns (score, evidence_dict).
    """
    result = await db.execute(
        select(func.count()).where(
            CorporateInvoice.account_id == account_id,
            CorporateInvoice.status == InvoiceStatus.FINALIZED,
        )
    )
    unpaid_count = result.scalar_one()

    score = max(0, 100 - (unpaid_count * 20))
    evidence = {"unpaid_finalized_invoices": unpaid_count}
    return score, evidence


async def _compute_compliance_score(db: AsyncSession, account_id: int) -> tuple[int, dict]:
    """Score based on denied ride approvals (policy violations).

    Looks at the last 30 ride approvals for the account.
    100 — no denials.
    Deduct 15 points per denial in the last 30 approvals, floor 0.

    Returns (score, evidence_dict).
    """
    result = await db.execute(
        select(func.count()).where(
            CorporateRideApproval.account_id == account_id,
        )
    )
    total = result.scalar_one()

    denied_result = await db.execute(
        select(func.count()).where(
            CorporateRideApproval.account_id == account_id,
            CorporateRideApproval.status == ApprovalStatus.DENIED,
        )
    )
    denied = denied_result.scalar_one()

    score = max(0, 100 - (denied * 15))
    evidence = {
        "total_ride_approvals": total,
        "denied_ride_approvals": denied,
    }
    return score, evidence


async def _compute_credit_score(db: AsyncSession, account_id: int) -> tuple[int, dict]:
    """Score based on prepaid credit account balance.

    100 — no credit account (not using prepaid; N/A).
    100 — balance > 2× low_balance_threshold or threshold not set.
     70 — balance between 1–2× threshold (caution zone).
     40 — balance below threshold (low balance alert).
      0 — balance is zero or negative.

    Returns (score, evidence_dict).
    """
    result = await db.execute(
        select(CorporateCreditAccount).where(
            CorporateCreditAccount.account_id == account_id
        )
    )
    credit = result.scalar_one_or_none()

    if credit is None:
        return 100, {"credit_account": "not_configured"}

    balance = float(credit.balance_usd)
    threshold = (
        float(credit.low_balance_threshold_usd)
        if credit.low_balance_threshold_usd is not None
        else None
    )

    if balance <= 0:
        score = 0
    elif threshold is None:
        score = 100
    elif balance >= threshold * 2:
        score = 100
    elif balance >= threshold:
        score = 70
    else:
        score = 40

    evidence = {
        "balance_usd": balance,
        "low_balance_threshold_usd": threshold,
    }
    return score, evidence


async def _compute_dispute_score(db: AsyncSession, account_id: int) -> tuple[int, dict]:
    """Score based on open invoice disputes.

    100 — no open disputes.
    Deduct 25 points per open dispute (submitted or under_review), floor 0.

    Returns (score, evidence_dict).
    """
    result = await db.execute(
        select(func.count()).where(
            CorporateInvoiceDispute.account_id == account_id,
            CorporateInvoiceDispute.status.in_(
                [DisputeStatus.submitted, DisputeStatus.under_review]
            ),
        )
    )
    open_disputes = result.scalar_one()

    score = max(0, 100 - (open_disputes * 25))
    evidence = {"open_disputes": open_disputes}
    return score, evidence


async def _compute_contract_score(db: AsyncSession, account_id: int) -> tuple[int, dict]:
    """Score based on active service contract coverage.

    100 — has an active contract.
     70 — has a draft contract (in negotiation).
     50 — expired contract (no renewal yet).
      0 — terminated contract.
     80 — no contract at all (non-enterprise; N/A by default).

    Returns (score, evidence_dict).
    """
    result = await db.execute(
        select(CorporateAccountContract)
        .where(CorporateAccountContract.account_id == account_id)
        .order_by(CorporateAccountContract.created_at.desc())
        .limit(1)
    )
    contract = result.scalar_one_or_none()

    if contract is None:
        return 80, {"contract_status": "none"}

    mapping = {
        ContractStatus.active: 100,
        ContractStatus.draft: 70,
        ContractStatus.expired: 50,
        ContractStatus.terminated: 0,
    }
    score = mapping.get(contract.status, 80)
    evidence = {
        "contract_status": contract.status.value if hasattr(contract.status, "value") else contract.status,
        "contract_id": contract.id,
    }
    return score, evidence


async def _compute_suspension_score(db: AsyncSession, account_id: int) -> tuple[int, dict]:
    """Score based on suspension history.

    100 — never suspended.
     70 — suspended in the past but currently active.
      0 — currently suspended.

    Returns (score, evidence_dict).
    """
    # Check active suspension
    active_result = await db.execute(
        select(func.count()).where(
            CorporateAccountSuspension.account_id == account_id,
            CorporateAccountSuspension.is_active.is_(True),
        )
    )
    active_count = active_result.scalar_one()

    if active_count > 0:
        return 0, {"currently_suspended": True, "past_suspensions": None}

    # Count historical suspensions (resolved ones)
    history_result = await db.execute(
        select(func.count()).where(
            CorporateAccountSuspension.account_id == account_id,
            CorporateAccountSuspension.is_active.is_(False),
        )
    )
    past_count = history_result.scalar_one()

    score = 70 if past_count > 0 else 100
    evidence = {"currently_suspended": False, "past_suspensions": past_count}
    return score, evidence


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


async def compute_health_score(
    db: AsyncSession,
    account_id: int,
    computed_by_id: Optional[int] = None,
) -> HealthScoreResponse:
    """Compute, persist, and return a health score snapshot for the account.

    Queries six data domains, weights the sub-scores, and inserts an immutable
    snapshot row.  Callers may pass computed_by_id when the computation was
    explicitly requested by an admin.

    Args:
        db:               Async database session.
        account_id:       Corporate account to evaluate.
        computed_by_id:   ID of the admin who triggered this computation, or
                          None for automatic/scheduled computation.

    Returns:
        HealthScoreResponse for the newly created snapshot.
    """
    payment_score, payment_evidence = await _compute_payment_score(db, account_id)
    compliance_score, compliance_evidence = await _compute_compliance_score(db, account_id)
    credit_score, credit_evidence = await _compute_credit_score(db, account_id)
    dispute_score, dispute_evidence = await _compute_dispute_score(db, account_id)
    contract_score, contract_evidence = await _compute_contract_score(db, account_id)
    suspension_score, suspension_evidence = await _compute_suspension_score(db, account_id)

    overall_score = round(
        payment_score * _WEIGHTS["payment"]
        + compliance_score * _WEIGHTS["compliance"]
        + credit_score * _WEIGHTS["credit"]
        + dispute_score * _WEIGHTS["dispute"]
        + contract_score * _WEIGHTS["contract"]
        + suspension_score * _WEIGHTS["suspension"]
    )
    overall_score = max(0, min(100, overall_score))

    score_details = {
        "payment": payment_evidence,
        "compliance": compliance_evidence,
        "credit": credit_evidence,
        "dispute": dispute_evidence,
        "contract": contract_evidence,
        "suspension": suspension_evidence,
    }

    snapshot = CorporateAccountHealthScore(
        account_id=account_id,
        overall_score=overall_score,
        risk_level=_risk_level_from_score(overall_score),
        payment_score=payment_score,
        compliance_score=compliance_score,
        credit_score=credit_score,
        dispute_score=dispute_score,
        contract_score=contract_score,
        suspension_score=suspension_score,
        score_details=score_details,
        computed_at=datetime.now(timezone.utc),
        computed_by_id=computed_by_id,
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)
    return _to_response(snapshot)


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


async def get_latest_health_score(
    db: AsyncSession,
    account_id: int,
) -> HealthScoreResponse | None:
    """Return the most recent health score snapshot for an account.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.

    Returns:
        HealthScoreResponse for the latest snapshot, or None if no snapshot
        has ever been computed for this account.
    """
    result = await db.execute(
        select(CorporateAccountHealthScore)
        .where(CorporateAccountHealthScore.account_id == account_id)
        .order_by(CorporateAccountHealthScore.computed_at.desc())
        .limit(1)
    )
    snapshot = result.scalar_one_or_none()
    return _to_response(snapshot) if snapshot is not None else None


async def get_health_score_history(
    db: AsyncSession,
    account_id: int,
    limit: int = 30,
) -> Sequence[HealthScoreResponse]:
    """Return health score history for an account, most recent first.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.
        limit:      Maximum number of snapshots to return (default 30).

    Returns:
        List of HealthScoreResponse objects ordered newest-first.
    """
    result = await db.execute(
        select(CorporateAccountHealthScore)
        .where(CorporateAccountHealthScore.account_id == account_id)
        .order_by(CorporateAccountHealthScore.computed_at.desc())
        .limit(limit)
    )
    snapshots = result.scalars().all()
    return [_to_response(s) for s in snapshots]


async def list_accounts_by_health(
    db: AsyncSession,
    risk_level: Optional[HealthRiskLevel] = None,
    below_score: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[HealthScoreResponse]:
    """Return the latest health score per account, optionally filtered.

    Uses a subquery to find the most recent snapshot per account, then applies
    optional filters before returning.

    Args:
        db:          Async database session.
        risk_level:  If set, only return accounts with this risk level.
        below_score: If set, only return accounts with overall_score < this.
        skip:        Pagination offset.
        limit:       Maximum number of accounts to return.

    Returns:
        List of HealthScoreResponse objects for matching accounts, ordered by
        overall_score ascending (worst first).
    """
    # Subquery: latest computed_at per account
    latest_sub = (
        select(
            CorporateAccountHealthScore.account_id,
            func.max(CorporateAccountHealthScore.computed_at).label("max_computed_at"),
        )
        .group_by(CorporateAccountHealthScore.account_id)
        .subquery()
    )

    query = (
        select(CorporateAccountHealthScore)
        .join(
            latest_sub,
            (CorporateAccountHealthScore.account_id == latest_sub.c.account_id)
            & (CorporateAccountHealthScore.computed_at == latest_sub.c.max_computed_at),
        )
    )

    if risk_level is not None:
        query = query.where(CorporateAccountHealthScore.risk_level == risk_level)
    if below_score is not None:
        query = query.where(CorporateAccountHealthScore.overall_score < below_score)

    query = (
        query.order_by(CorporateAccountHealthScore.overall_score.asc())
        .offset(skip)
        .limit(limit)
    )

    result = await db.execute(query)
    snapshots = result.scalars().all()
    return [_to_response(s) for s in snapshots]


async def get_at_risk_summary(db: AsyncSession) -> AtRiskSummaryResponse:
    """Return a platform-level summary of account health distribution.

    Counts the latest score per account across all risk levels.  Used for
    platform-admin overview dashboards.

    Args:
        db: Async database session.

    Returns:
        AtRiskSummaryResponse with counts per risk level and total.
    """
    latest_sub = (
        select(
            CorporateAccountHealthScore.account_id,
            func.max(CorporateAccountHealthScore.computed_at).label("max_computed_at"),
        )
        .group_by(CorporateAccountHealthScore.account_id)
        .subquery()
    )

    result = await db.execute(
        select(
            CorporateAccountHealthScore.risk_level,
            func.count().label("cnt"),
        )
        .join(
            latest_sub,
            (CorporateAccountHealthScore.account_id == latest_sub.c.account_id)
            & (CorporateAccountHealthScore.computed_at == latest_sub.c.max_computed_at),
        )
        .group_by(CorporateAccountHealthScore.risk_level)
    )
    rows = result.all()

    counts: dict[str, int] = {lvl.value: 0 for lvl in HealthRiskLevel}
    for row in rows:
        level_key = row.risk_level.value if hasattr(row.risk_level, "value") else row.risk_level
        counts[level_key] = row.cnt

    total = sum(counts.values())

    return AtRiskSummaryResponse(
        total_accounts_scored=total,
        distribution=RiskDistribution(
            excellent=counts["excellent"],
            good=counts["good"],
            fair=counts["fair"],
            poor=counts["poor"],
            critical=counts["critical"],
        ),
        at_risk_count=counts["poor"] + counts["critical"],
    )


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _to_response(snapshot: CorporateAccountHealthScore) -> HealthScoreResponse:
    """Convert a model instance to a HealthScoreResponse schema object."""
    return HealthScoreResponse(
        id=snapshot.id,
        account_id=snapshot.account_id,
        overall_score=snapshot.overall_score,
        risk_level=snapshot.risk_level,
        payment_score=snapshot.payment_score,
        compliance_score=snapshot.compliance_score,
        credit_score=snapshot.credit_score,
        dispute_score=snapshot.dispute_score,
        contract_score=snapshot.contract_score,
        suspension_score=snapshot.suspension_score,
        score_details=snapshot.score_details,
        computed_at=snapshot.computed_at,
        computed_by_id=snapshot.computed_by_id,
    )
