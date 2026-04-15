"""Pydantic v2 schemas for Corporate Account Health Score.

A computed 0–100 composite score that aggregates six data domains —
payment history, policy compliance, credit balance, open disputes, contract
status, and suspension history — into a single health indicator.

Public surface
--------------
HealthScoreResponse     — full snapshot record returned by the API.
HealthScoreListResponse — paginated list of health score records.
RiskDistribution        — count-per-risk-level breakdown.
AtRiskSummaryResponse   — platform-level health distribution summary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator

from app.models.corporate_health_score import HealthRiskLevel


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class HealthScoreResponse(BaseModel):
    """Full health score snapshot returned by the API.

    Attributes:
        id:                Primary key of the snapshot.
        account_id:        Corporate account this snapshot belongs to.
        overall_score:     Composite 0–100 score; higher is healthier.
        risk_level:        Categorical risk label (excellent/good/fair/poor/critical).
        payment_score:     Sub-score from invoice payment history (0–100).
        compliance_score:  Sub-score from policy compliance (0–100).
        credit_score:      Sub-score from prepaid credit balance (0–100).
        dispute_score:     Sub-score from open invoice disputes (0–100).
        contract_score:    Sub-score from active contract status (0–100).
        suspension_score:  Sub-score from suspension history (0–100).
        score_details:     Per-domain evidence JSON used to compute sub-scores.
        computed_at:       When this snapshot was generated.
        computed_by_id:    Admin who triggered recomputation; null if automatic.
    """

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    overall_score: int
    risk_level: HealthRiskLevel
    payment_score: int
    compliance_score: int
    credit_score: int
    dispute_score: int
    contract_score: int
    suspension_score: int
    score_details: Dict[str, Any]
    computed_at: datetime
    computed_by_id: Optional[int]


class HealthScoreListResponse(BaseModel):
    """Paginated list of health score snapshots.

    Attributes:
        scores: List of health score snapshot records.
        total:  Total count of records in the result.
    """

    scores: List[HealthScoreResponse]
    total: int


# ---------------------------------------------------------------------------
# At-risk summary schemas
# ---------------------------------------------------------------------------


class RiskDistribution(BaseModel):
    """Count of accounts at each risk level.

    Attributes:
        excellent: Accounts scored 90–100.
        good:      Accounts scored 70–89.
        fair:      Accounts scored 50–69.
        poor:      Accounts scored 25–49.
        critical:  Accounts scored 0–24.
    """

    excellent: int
    good: int
    fair: int
    poor: int
    critical: int


class AtRiskSummaryResponse(BaseModel):
    """Platform-level health distribution summary for admin dashboards.

    Attributes:
        total_accounts_scored: Total number of accounts with at least one
                               health score snapshot.
        distribution:          Breakdown of current-score counts per risk level.
        at_risk_count:         Accounts in poor or critical condition
                               (distribution.poor + distribution.critical).
    """

    total_accounts_scored: int
    distribution: RiskDistribution
    at_risk_count: int
