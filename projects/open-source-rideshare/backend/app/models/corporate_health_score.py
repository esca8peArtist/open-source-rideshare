"""Corporate Account Health Score model.

Platform admins and corporate account members can view a computed risk/health
assessment for their account.  The score aggregates signals from payment
history, policy compliance, credit balance, open disputes, active contracts,
and suspension history into a single 0–100 composite score.

Scores are cached as snapshots; each recomputation creates a new row, so
historical trend data is preserved.

Tables:
  corporate_account_health_scores — one row per computation event; the most
                                    recent row for an account is the current
                                    health score.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class HealthRiskLevel(str, enum.Enum):
    """Categorical risk level derived from the overall health score.

    Thresholds:
      excellent — 90–100
      good      — 70–89
      fair      — 50–69
      poor      — 25–49
      critical  —  0–24
    """

    excellent = "excellent"
    good = "good"
    fair = "fair"
    poor = "poor"
    critical = "critical"


def _risk_level_from_score(score: int) -> HealthRiskLevel:
    """Derive a HealthRiskLevel from a 0–100 integer score."""
    if score >= 90:
        return HealthRiskLevel.excellent
    if score >= 70:
        return HealthRiskLevel.good
    if score >= 50:
        return HealthRiskLevel.fair
    if score >= 25:
        return HealthRiskLevel.poor
    return HealthRiskLevel.critical


class CorporateAccountHealthScore(Base):
    """Cached health score snapshot for a corporate account.

    A new row is inserted every time the score is recomputed, so historical
    trend data is preserved.  Callers should always use the row with the
    highest computed_at timestamp as the "current" score.

    Attributes:
        account_id:          FK to corporate_accounts_v2 (CASCADE delete).
        overall_score:       Composite 0–100 score; higher is healthier.
        risk_level:          Categorical risk label derived from overall_score.
        payment_score:       Sub-score based on invoice payment history (0–100).
        compliance_score:    Sub-score based on policy compliance rate (0–100).
        credit_score:        Sub-score based on prepaid credit balance (0–100).
        dispute_score:       Sub-score based on open invoice disputes (0–100).
        contract_score:      Sub-score based on active contract status (0–100).
        suspension_score:    Sub-score based on suspension history (0–100).
        score_details:       JSON object with per-factor evidence used to
                             compute each sub-score.
        computed_at:         When this snapshot was generated.
        computed_by_id:      FK to users — admin who triggered recomputation.
                             Null when computed automatically.
    """

    __tablename__ = "corporate_account_health_scores"
    __table_args__ = (
        CheckConstraint("overall_score >= 0 AND overall_score <= 100", name="ck_health_overall_range"),
        CheckConstraint("payment_score >= 0 AND payment_score <= 100", name="ck_health_payment_range"),
        CheckConstraint("compliance_score >= 0 AND compliance_score <= 100", name="ck_health_compliance_range"),
        CheckConstraint("credit_score >= 0 AND credit_score <= 100", name="ck_health_credit_range"),
        CheckConstraint("dispute_score >= 0 AND dispute_score <= 100", name="ck_health_dispute_range"),
        CheckConstraint("contract_score >= 0 AND contract_score <= 100", name="ck_health_contract_range"),
        CheckConstraint("suspension_score >= 0 AND suspension_score <= 100", name="ck_health_suspension_range"),
        Index("ix_corp_health_account_id", "account_id"),
        Index("ix_corp_health_computed_at", "computed_at"),
        Index("ix_corp_health_risk_level", "risk_level"),
        Index("ix_corp_health_account_computed", "account_id", "computed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[HealthRiskLevel] = mapped_column(
        Enum(HealthRiskLevel, name="healthrisklevel"),
        nullable=False,
    )

    # Sub-scores (0–100 each)
    payment_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    compliance_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    credit_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    dispute_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    contract_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    suspension_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    # Evidence JSON: keys per sub-score showing the data points that drove it
    score_details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    computed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    account = relationship("BusinessAccount", foreign_keys=[account_id])
    computed_by = relationship("User", foreign_keys=[computed_by_id])
