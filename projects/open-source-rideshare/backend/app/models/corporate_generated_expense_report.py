"""ORM model for pre-generated aggregated expense reports.

A CorporateGeneratedExpenseReport is created when an admin triggers the
"generate expense report" action.  It stores the aggregated totals (by
member and by category) so that the same report can be retrieved and
exported multiple times without re-querying the rides table.

This is distinct from CorporateExpenseReport (corporate_expense_reports),
which represents individual employee expense submissions.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class CorporateGeneratedExpenseReport(Base):
    """A snapshot of aggregated ride expenses for a corporate account.

    Attributes:
        id: Integer primary key.
        corp_id: FK to corporate_accounts_v2.id (CASCADE delete, indexed).
        title: Human-readable report title (max 200 chars).
        start_date: Inclusive start of the reporting period.
        end_date: Inclusive end of the reporting period.
        total_rides: Total number of rides included in the report.
        total_amount_usd: Sum of all ride fares in USD.
        generated_at: When the report was created (server default = now()).
        generated_by_id: FK to users.id — admin who generated the report.
        by_member: JSON array of MemberExpenseSummary dicts.
        by_category: JSON array of CategoryExpenseSummary dicts.
    """

    __tablename__ = "corporate_generated_expense_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    corp_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    total_rides: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    total_amount_usd: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0
    )

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    generated_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    by_member: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )

    by_category: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )
