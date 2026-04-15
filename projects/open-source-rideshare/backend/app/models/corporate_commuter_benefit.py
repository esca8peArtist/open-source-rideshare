"""Corporate Commuter Benefit models.

Companies define a monthly ride subsidy program that gives employees a monthly
credit specifically for qualifying rides.  This is distinct from prepaid credit
account pools (account-level) and spend limits (caps) — commuter benefits are
per-employee monthly allotments tied to eligible trip purposes and groups.

CorporateCommuterProgram  — one program per corporate account.
CorporateCommuterAllotment — monthly per-employee allotment record, created
    lazily when a qualifying ride occurs or proactively by an admin.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
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


class CorporateCommuterProgram(Base):
    """Monthly commuter benefit program for a corporate account.

    One program per account (unique constraint on ``account_id``).  Admins
    configure a monthly allowance that eligible employees receive.  Eligibility
    can be scoped to specific trip purposes and/or employee groups.

    Attributes:
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        name: Display name (max 100 chars), e.g. "Employee Commuter Benefit".
        description: Optional human-readable description (max 500 chars).
        monthly_allowance_usd: Amount given to each eligible employee per month.
        rollover_enabled: When True unused balance carries forward to next month.
        max_rollover_usd: Optional cap on rollover amount.
        eligible_trip_purpose_ids: JSONB list of CorporateTripPurpose IDs that
            qualify; ``null`` means all purposes qualify.
        eligible_group_ids: JSONB list of CorporateEmployeeGroup IDs that receive
            the benefit; ``null`` means all account members receive it.
        is_active: Soft-delete flag.
        valid_from: Optional date the program becomes effective.
        valid_until: Optional expiry date of the program.
        created_by_id: FK to users — admin who created this program (SET NULL on
            user delete so the program survives admin departure).
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_commuter_programs"
    __table_args__ = (
        UniqueConstraint(
            "account_id", name="uq_corp_commuter_program_account_id"
        ),
        Index("ix_corp_commuter_program_account_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    monthly_allowance_usd: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False
    )

    rollover_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    max_rollover_usd: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    eligible_trip_purpose_ids: Mapped[list | None] = mapped_column(
        JSONB, nullable=True
    )

    eligible_group_ids: Mapped[list | None] = mapped_column(
        JSONB, nullable=True
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)

    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(
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
    allotments: Mapped[list["CorporateCommuterAllotment"]] = relationship(
        "CorporateCommuterAllotment",
        back_populates="program",
        cascade="all, delete-orphan",
    )


class CorporateCommuterAllotment(Base):
    """Monthly per-employee allotment record for a commuter benefit program.

    Created lazily when a qualifying ride occurs or proactively by an admin.
    Rollover from the prior month is applied at creation time when the program
    has ``rollover_enabled=True``.

    Attributes:
        program_id: FK to corporate_commuter_programs (CASCADE delete).
        member_id: FK to corporate_account_members (CASCADE delete).
        period_year: Calendar year of the allotment period, e.g. 2026.
        period_month: Calendar month (1–12) of the allotment period.
        allotted_usd: Allowance copied from the program at allotment creation.
        used_usd: Running total of commuter ride charges applied against this
            allotment.
        rolled_over_usd: Amount carried forward from the prior month's unused
            balance (0 when rollover is disabled).
        created_at: UTC creation timestamp.
    """

    __tablename__ = "corporate_commuter_allotments"
    __table_args__ = (
        UniqueConstraint(
            "program_id",
            "member_id",
            "period_year",
            "period_month",
            name="uq_corp_commuter_allotment_program_member_period",
        ),
        Index("ix_corp_commuter_allotment_program_id", "program_id"),
        Index("ix_corp_commuter_allotment_member_id", "member_id"),
        Index(
            "ix_corp_commuter_allotment_period",
            "program_id",
            "period_year",
            "period_month",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    program_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_commuter_programs.id", ondelete="CASCADE"),
        nullable=False,
    )

    member_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_account_members.id", ondelete="CASCADE"),
        nullable=False,
    )

    period_year: Mapped[int] = mapped_column(Integer, nullable=False)

    period_month: Mapped[int] = mapped_column(Integer, nullable=False)

    allotted_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    used_usd: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=0
    )

    rolled_over_usd: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=0
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    program: Mapped["CorporateCommuterProgram"] = relationship(
        "CorporateCommuterProgram", back_populates="allotments"
    )
    member = relationship("BusinessAccountMember", foreign_keys=[member_id])
