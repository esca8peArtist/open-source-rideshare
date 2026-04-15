"""Corporate Expense Report model.

Employees submit rides (or manual expenses) for corporate reimbursement.
Admins review and approve or reject each report.  This is distinct from
direct corporate billing — it handles the case where an employee paid
personally and needs to expense it back to the company.

CorporateExpenseReport — table corporate_expense_reports
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ExpenseStatus(str, enum.Enum):
    """Lifecycle states for an expense report."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class CorporateExpenseReport(Base):
    """An employee-submitted expense report awaiting corporate reimbursement.

    Attributes:
        id: Integer primary key.
        account_id: FK to corporate_accounts_v2.id (CASCADE delete).
        submitted_by_id: FK to users.id — employee who submitted the report.
        ride_id: Optional FK to rides.id (SET NULL on ride deletion).
            Links the report to a specific platform ride.
        amount_usd: Claimed reimbursement amount in USD.
        description: What the expense was for.
        cost_center_id: Optional FK to corporate_cost_centers.id (SET NULL).
        trip_purpose_id: Optional FK to corporate_trip_purposes.id (SET NULL).
        receipt_url: Optional URL of an attached receipt image/document.
        status: Current lifecycle state (pending/approved/rejected/withdrawn).
        reviewed_by_id: FK to users.id — admin who reviewed the report.
        reviewed_at: Timestamp of admin review decision.
        review_note: Optional admin feedback on approval or rejection.
        submitted_at: When the report was submitted.
        created_at: Row creation timestamp.
    """

    __tablename__ = "corporate_expense_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    submitted_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    ride_id: Mapped[int | None] = mapped_column(
        ForeignKey("rides.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    amount_usd: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(Text, nullable=False)

    cost_center_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
        nullable=True,
    )

    trip_purpose_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_trip_purposes.id", ondelete="SET NULL"),
        nullable=True,
    )

    receipt_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[ExpenseStatus] = mapped_column(
        SAEnum(ExpenseStatus),
        nullable=False,
        default=ExpenseStatus.PENDING,
    )

    reviewed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    account = relationship("BusinessAccount", foreign_keys=[account_id])
    submitted_by = relationship("User", foreign_keys=[submitted_by_id])
    ride = relationship("Ride", foreign_keys=[ride_id])
    cost_center = relationship("CorporateCostCenter", foreign_keys=[cost_center_id])
    trip_purpose = relationship("CorporateTripPurpose", foreign_keys=[trip_purpose_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])
