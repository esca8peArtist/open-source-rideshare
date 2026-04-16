"""Corporate Mileage Reimbursement models.

Corporate employees sometimes use personal vehicles for work trips (client
visits, off-site meetings) and submit mileage claims for reimbursement at a
configured rate.  Admins configure the policy; employees create and submit
claims; admins review and mark paid.

Models
------
CorporateMileagePolicy  — table corporate_mileage_policies
CorporateMileageClaim   — table corporate_mileage_claims
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ClaimStatus(str, enum.Enum):
    """Lifecycle states for a mileage claim."""

    DRAFT = "draft"
    """Employee is still editing the claim."""

    SUBMITTED = "submitted"
    """Claim submitted and awaiting admin review."""

    APPROVED = "approved"
    """Claim approved by admin (or auto-approved)."""

    REJECTED = "rejected"
    """Claim rejected by admin."""

    PAID = "paid"
    """Reimbursement has been issued."""


class CorporateMileagePolicy(Base):
    """Per-account mileage reimbursement policy.

    Exactly one row per corporate account (unique constraint on account_id).
    Created on first access with IRS-standard defaults.

    Attributes:
        id: Integer primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete); unique.
        rate_per_mile: USD per mile reimbursed (default 0.6700 — 2024 IRS rate).
        max_miles_per_claim: Optional hard cap on miles per claim.
        requires_approval_above_usd: Claims above this USD amount require
            admin review; None means all claims auto-approve (subject to miles
            threshold).
        requires_approval_above_miles: Claims above this mileage require admin
            review; None means no miles-based approval gate.
        require_trip_purpose: If True, employees must select a trip purpose
            when submitting a claim.
        is_active: Soft-disable flag — when False, new claims cannot be
            submitted.
        created_by_id: FK to users — admin who first activated the policy
            (SET NULL if user is deleted).
    """

    __tablename__ = "corporate_mileage_policies"
    __table_args__ = (
        UniqueConstraint("account_id", name="uq_corp_mileage_policy_account_id"),
        Index("ix_corp_mileage_policy_account_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    rate_per_mile: Mapped[float] = mapped_column(
        Numeric(6, 4),
        nullable=False,
        default=0.6700,
        server_default="0.6700",
    )

    max_miles_per_claim: Mapped[int | None] = mapped_column(Integer, nullable=True)

    requires_approval_above_usd: Mapped[float | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )

    requires_approval_above_miles: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    require_trip_purpose: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    account = relationship("BusinessAccount", foreign_keys=[account_id])
    created_by = relationship("User", foreign_keys=[created_by_id])


class CorporateMileageClaim(Base):
    """A single employee mileage reimbursement claim.

    Attributes:
        id: Integer primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        member_id: FK to users — the employee submitting the claim
            (SET NULL if user is deleted).
        trip_date: Date of the trip.
        miles: Distance driven (Numeric for precision).
        rate_used_usd: Snapshot of policy.rate_per_mile at claim creation.
        amount_usd: Computed reimbursement amount (miles × rate_used_usd).
        description: Free-text trip description (max 500 chars).
        trip_purpose_id: Optional FK to corporate_trip_purposes (SET NULL).
        cost_center_id: Optional FK to corporate_cost_centers (SET NULL).
        status: Current claim lifecycle state.
        submitted_at: When the claim was submitted.
        reviewed_by_id: FK to users — admin who reviewed the claim (SET NULL).
        reviewed_at: When the claim was reviewed.
        review_note: Admin note explaining the review decision.
        paid_at: When the reimbursement was issued.
    """

    __tablename__ = "corporate_mileage_claims"
    __table_args__ = (
        Index("ix_corp_mileage_claim_account_id", "account_id"),
        Index("ix_corp_mileage_claim_member_id", "member_id"),
        Index("ix_corp_mileage_claim_status", "account_id", "status"),
        Index("ix_corp_mileage_claim_trip_date", "account_id", "trip_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    trip_date: Mapped[date] = mapped_column(Date, nullable=False)

    miles: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)

    rate_used_usd: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)

    amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    description: Mapped[str] = mapped_column(String(500), nullable=False)

    trip_purpose_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_trip_purposes.id", ondelete="SET NULL"),
        nullable=True,
    )

    cost_center_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[ClaimStatus] = mapped_column(
        SAEnum(ClaimStatus),
        nullable=False,
        default=ClaimStatus.DRAFT,
        server_default=ClaimStatus.DRAFT.value,
    )

    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    reviewed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    account = relationship("BusinessAccount", foreign_keys=[account_id])
    member = relationship("User", foreign_keys=[member_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])
    trip_purpose = relationship("CorporateTripPurpose", foreign_keys=[trip_purpose_id])
    cost_center = relationship("CorporateCostCenter", foreign_keys=[cost_center_id])
