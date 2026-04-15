"""Corporate Account Contract model.

Tracks the service agreement between the platform and a corporate client.
One contract can be active per account at a time; historical contracts are
kept for audit purposes.

ContractStatus enum: draft / active / expired / terminated
CorporateAccountContract model
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ContractStatus(str, enum.Enum):
    """Lifecycle state of a corporate account contract."""

    draft = "draft"
    active = "active"
    expired = "expired"
    terminated = "terminated"


class CorporateAccountContract(Base):
    """Service agreement between the platform and a corporate client.

    One contract may be active per account at a time.  Historical (expired or
    terminated) contracts are retained for audit purposes.  Draft contracts may
    be edited freely; once activated they become immutable except via the
    dedicated activate/terminate operations.

    Attributes:
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        contract_number: Unique human-readable reference; auto-generated when
            not supplied by the caller.
        status: ContractStatus lifecycle state.
        contract_start_date: Inclusive start date of the agreement term.
        contract_end_date: Inclusive end date; null means open-ended.
        auto_renews: When True the contract renews automatically near expiry.
        renewal_term_days: Duration of each renewal in days (e.g. 365).
        renewal_notice_days: Days before end_date the platform sends renewal
            notice (default 30).
        committed_monthly_rides: Optional minimum ride commitment per month.
        committed_monthly_spend_usd: Optional minimum spend commitment (USD).
        negotiated_discount_pct: Percentage discount negotiated for this account
            (0.00–100.00).
        account_manager_name: Name of the assigned platform account manager.
        account_manager_email: Email of the assigned platform account manager.
        contract_document_url: URL to the signed contract PDF or DocuSign link.
        notes: Free-text internal notes.
        signed_by_name: Name of the corporate signatory.
        signed_at: When the contract was signed.
        activated_at: When the contract was moved to active status.
        terminated_at: When the contract was terminated.
        termination_reason: Admin-supplied reason for early termination.
        created_by_id: FK to users — admin who created the contract.
        updated_by_id: FK to users — admin who last updated the contract.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_account_contracts"
    __table_args__ = (
        Index("ix_corp_contracts_account_id", "account_id"),
        Index("ix_corp_contracts_status", "status"),
        Index("ix_corp_contracts_account_status", "account_id", "status"),
        Index("ix_corp_contracts_end_date", "contract_end_date"),
        UniqueConstraint("contract_number", name="uq_corp_contracts_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    contract_number: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True
    )

    status: Mapped[ContractStatus] = mapped_column(
        Enum(ContractStatus, name="contractstatus"),
        nullable=False,
        default=ContractStatus.draft,
    )

    contract_start_date: Mapped[date] = mapped_column(Date, nullable=False)

    contract_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    auto_renews: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    renewal_term_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    renewal_notice_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )

    committed_monthly_rides: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    committed_monthly_spend_usd: Mapped[float | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    negotiated_discount_pct: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    account_manager_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )

    account_manager_email: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )

    contract_document_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    signed_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    terminated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    termination_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    account = relationship("BusinessAccount", foreign_keys=[account_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    updated_by = relationship("User", foreign_keys=[updated_by_id])
