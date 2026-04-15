"""Corporate cost center model.

Companies can create named cost centers (departments, projects, teams) and
tag corporate rides to them for per-department expense tracking.

CorporateCostCenter — one row per named cost center within an account
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateCostCenter(Base):
    """A named department, project, or team within a corporate account.

    Attributes:
        account_id: FK to corporate_accounts_v2.
        name: Human-readable label (e.g. "Engineering", "Sales – EMEA").
        code: Short alphanumeric identifier, unique per account (e.g. "ENG").
            Used in reports and ride tagging.
        description: Optional longer description.
        is_active: Soft-delete flag. Inactive centres cannot receive new rides
            but historical rides retain their assignment.
        monthly_budget: Optional monthly spend cap for this cost centre.
            NULL means no cap.
        created_at: Creation timestamp.
        updated_at: Last modification timestamp.
    """

    __tablename__ = "corporate_cost_centers"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "code", name="uq_corp_cost_center_account_code"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    monthly_budget: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
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
