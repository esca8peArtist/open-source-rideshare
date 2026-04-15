"""Corporate Multi-Level Approval Chain models.

Corporate account admins can define named approval chains where rides matching
certain criteria must be approved by a sequence of users or any admin before
the employee can book.  For example: rides over $100 require approval from the
employee's manager *and then* a finance admin.

This feature is completely separate from the simpler one-step CorporateRideApproval
system.  It provides configurable multi-step chains, per-step decisions, and
timeout/escalation handling.

Tables:
  corporate_approval_chains             — named chain definition per account.
  corporate_approval_chain_steps        — ordered steps within a chain.
  corporate_approval_chain_requests     — a running multi-step approval request.
  corporate_approval_chain_step_decisions — per-step decisions recorded by approvers.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateApprovalChain(Base):
    """A named, configurable multi-step approval chain for a corporate account.

    Attributes:
        account_id:                 FK to corporate_accounts_v2 (CASCADE delete).
        name:                       Human-readable chain name (max 100 chars).
        description:                Optional description (max 300 chars).
        min_cost_usd:               Chain triggers when estimated ride cost >= this
                                    value; NULL means applies regardless of cost.
        applies_to_all_cost_centers: When False, chain only applies to cost centers
                                    listed in cost_center_ids.
        cost_center_ids:            JSONB list of cost center IDs this chain restricts
                                    to.  Relevant only when applies_to_all_cost_centers=False.
        is_active:                  Whether this chain is currently enforced.
        created_by_id:              FK to users — admin who created the chain (SET NULL).
        created_at:                 Immutable creation timestamp.
        updated_at:                 Last-modified timestamp (auto-updated).
    """

    __tablename__ = "corporate_approval_chains"
    __table_args__ = (
        Index("ix_corp_approval_chain_account_id", "account_id"),
        Index("ix_corp_approval_chain_account_active", "account_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    min_cost_usd: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    applies_to_all_cost_centers: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    cost_center_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    account = relationship("BusinessAccount", foreign_keys=[account_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    steps = relationship(
        "CorporateApprovalChainStep",
        back_populates="chain",
        cascade="all, delete-orphan",
        order_by="CorporateApprovalChainStep.step_order",
    )


class CorporateApprovalChainStep(Base):
    """An ordered step within a corporate approval chain.

    Attributes:
        chain_id:         FK to corporate_approval_chains (CASCADE delete).
        step_order:       1-based position of this step in the chain.
        approver_type:    "specific_user" or "any_admin".
        approver_user_id: FK to users (SET NULL) — set when approver_type=specific_user.
        timeout_hours:    Hours after step activation before escalation fires;
                          NULL means no timeout.
        escalation_action: What happens on timeout — "skip" (auto-approve this step)
                           or "deny" (auto-deny the whole request).
        description:      Optional note explaining this step.
    """

    __tablename__ = "corporate_approval_chain_steps"
    __table_args__ = (
        UniqueConstraint(
            "chain_id",
            "step_order",
            name="uq_corp_approval_chain_step_order",
        ),
        Index("ix_corp_approval_chain_step_chain_id", "chain_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    chain_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_approval_chains.id", ondelete="CASCADE"),
        nullable=False,
    )
    approver_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_type: Mapped[str] = mapped_column(String(20), nullable=False)
    timeout_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    escalation_action: Mapped[str] = mapped_column(
        String(10), default="deny", nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Relationships
    chain = relationship("CorporateApprovalChain", back_populates="steps")
    approver_user = relationship("User", foreign_keys=[approver_user_id])


class CorporateApprovalChainRequest(Base):
    """A running multi-step approval request.

    Tracks the lifecycle of a single employee's ride approval request as it
    moves through the steps of an approval chain.

    Attributes:
        chain_id:               FK to corporate_approval_chains (SET NULL) — kept
                                for history even if the chain is later deleted.
        account_id:             FK to corporate_accounts_v2 (CASCADE delete).
        requester_id:           FK to users (SET NULL) — the employee requesting.
        current_step_order:     The step that is currently awaiting a decision.
        status:                 "pending", "approved", "denied", or "cancelled".
        estimated_cost_usd:     Estimated ride cost submitted with the request.
        cost_center_id:         FK to corporate_cost_centers (SET NULL).
        purpose:                Optional purpose description.
        destination_description: Optional destination note.
        final_decision_at:      When the request reached a terminal status.
        final_decision_by_id:   FK to users (SET NULL) — who made the final decision.
        created_at:             Immutable creation timestamp.
    """

    __tablename__ = "corporate_approval_chain_requests"
    __table_args__ = (
        Index("ix_corp_approval_chain_req_account_id", "account_id"),
        Index("ix_corp_approval_chain_req_requester_id", "requester_id"),
        Index(
            "ix_corp_approval_chain_req_account_status",
            "account_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    chain_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_approval_chains.id", ondelete="SET NULL"),
        nullable=True,
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )
    requester_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    cost_center_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
        nullable=True,
    )
    final_decision_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    current_step_order: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )
    estimated_cost_usd: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    purpose: Mapped[str | None] = mapped_column(String(200), nullable=True)
    destination_description: Mapped[str | None] = mapped_column(
        String(300), nullable=True
    )
    final_decision_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    chain = relationship("CorporateApprovalChain", foreign_keys=[chain_id])
    account = relationship("BusinessAccount", foreign_keys=[account_id])
    requester = relationship("User", foreign_keys=[requester_id])
    final_decision_by = relationship("User", foreign_keys=[final_decision_by_id])
    decisions = relationship(
        "CorporateApprovalChainStepDecision",
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="CorporateApprovalChainStepDecision.step_order",
    )


class CorporateApprovalChainStepDecision(Base):
    """An individual per-step decision recorded by an approver.

    Attributes:
        request_id:  FK to corporate_approval_chain_requests (CASCADE delete).
        step_order:  Which step this decision corresponds to.
        approver_id: FK to users (SET NULL) — who made this decision.
        decision:    "approved", "denied", or "skipped".
        note:        Optional note from the approver (max 500 chars).
        decided_at:  When the decision was recorded.
    """

    __tablename__ = "corporate_approval_chain_step_decisions"
    __table_args__ = (
        UniqueConstraint(
            "request_id",
            "step_order",
            name="uq_corp_approval_step_decision",
        ),
        Index("ix_corp_approval_step_decision_request_id", "request_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    request_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_approval_chain_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    approver_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Relationships
    request = relationship(
        "CorporateApprovalChainRequest", back_populates="decisions"
    )
    approver = relationship("User", foreign_keys=[approver_id])
