"""DriverExpense model — driver business expense tracking for tax purposes.

Rideshare drivers can log deductible business expenses (mileage, fuel,
vehicle maintenance, phone, tolls, insurance, and other costs) throughout
the year to simplify 1099 tax preparation.

For mileage entries, the ``amount`` field stores miles driven (not dollars),
so callers should apply the IRS standard mileage rate when computing
deduction values.
"""
from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ExpenseCategory(str, enum.Enum):
    MILEAGE = "mileage"
    FUEL = "fuel"
    VEHICLE_MAINTENANCE = "vehicle_maintenance"
    PHONE = "phone"
    TOLLS = "tolls"
    INSURANCE = "insurance"
    OTHER = "other"


class DriverExpense(Base):
    """A single logged business expense for a driver.

    Columns
    -------
    id               UUID primary key
    driver_id        FK → users.id (indexed for per-driver queries)
    category         ExpenseCategory enum
    amount           Dollar amount of the expense; for mileage entries this is
                     miles driven (callers apply the IRS standard rate)
    description      Optional free-text note (255 chars max)
    expense_date     Calendar date the expense occurred (not a timestamp)
    is_deductible    Whether the expense is considered tax-deductible
    created_at       Server-set creation timestamp
    """

    __tablename__ = "driver_expenses"

    __table_args__ = (
        Index("idx_driver_expenses_driver_id", "driver_id"),
        Index("idx_driver_expenses_expense_date", "expense_date"),
        Index("idx_driver_expenses_driver_date", "driver_id", "expense_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    category: Mapped[ExpenseCategory] = mapped_column(
        Enum(ExpenseCategory),
        nullable=False,
    )

    # For mileage: miles driven. For all other categories: dollar amount.
    amount: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    expense_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    is_deductible: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
