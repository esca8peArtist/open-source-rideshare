"""Driver expense tracking service.

Provides CRUD operations and summary aggregation for DriverExpense records.
All queries are scoped to the authenticated driver_id so drivers can only
access their own expense data.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_expense import DriverExpense, ExpenseCategory
from app.schemas.driver_expense import (
    CategoryBreakdown,
    ExpenseCreate,
    ExpenseSummaryResponse,
)


async def create_expense(
    db: AsyncSession,
    driver_id: int,
    data: ExpenseCreate,
) -> DriverExpense:
    """Persist a new expense record for the given driver.

    Args:
        db:        Async database session.
        driver_id: ID of the authenticated driver.
        data:      Validated request payload.

    Returns:
        The newly created DriverExpense ORM instance.
    """
    expense = DriverExpense(
        driver_id=driver_id,
        category=data.category,
        amount=data.amount,
        description=data.description,
        expense_date=data.expense_date,
        is_deductible=data.is_deductible,
    )
    db.add(expense)
    await db.flush()
    await db.refresh(expense)
    return expense


async def get_expenses(
    db: AsyncSession,
    driver_id: int,
    start_date: date,
    end_date: date,
    category: Optional[ExpenseCategory] = None,
) -> list[DriverExpense]:
    """Return expenses for a driver filtered by date range and optional category.

    Args:
        db:         Async database session.
        driver_id:  ID of the authenticated driver.
        start_date: Inclusive start of the date range.
        end_date:   Inclusive end of the date range.
        category:   When supplied, only return expenses with this category.

    Returns:
        List of DriverExpense records ordered by expense_date descending.
    """
    query = select(DriverExpense).where(
        DriverExpense.driver_id == driver_id,
        DriverExpense.expense_date >= start_date,
        DriverExpense.expense_date <= end_date,
    )
    if category is not None:
        query = query.where(DriverExpense.category == category)
    query = query.order_by(DriverExpense.expense_date.desc(), DriverExpense.id.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def delete_expense(
    db: AsyncSession,
    driver_id: int,
    expense_id: int,
) -> bool:
    """Delete an expense record owned by the driver.

    Args:
        db:         Async database session.
        driver_id:  ID of the authenticated driver.
        expense_id: Primary key of the expense to delete.

    Returns:
        True on successful deletion.

    Raises:
        HTTPException(404): If the expense does not exist or belongs to a
            different driver.
    """
    result = await db.execute(
        select(DriverExpense).where(
            DriverExpense.id == expense_id,
            DriverExpense.driver_id == driver_id,
        )
    )
    expense = result.scalar_one_or_none()
    if expense is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense not found.",
        )
    await db.delete(expense)
    await db.flush()
    return True


async def get_expense_summary(
    db: AsyncSession,
    driver_id: int,
    start_date: date,
    end_date: date,
) -> ExpenseSummaryResponse:
    """Return a category-level summary of expenses for the given period.

    Computes per-category subtotals plus a grand total and a deductible-only
    total for the specified date range.

    Args:
        db:         Async database session.
        driver_id:  ID of the authenticated driver.
        start_date: Inclusive start of the summary period.
        end_date:   Inclusive end of the summary period.

    Returns:
        ExpenseSummaryResponse with category breakdowns and totals.
    """
    expenses = await get_expenses(db, driver_id=driver_id, start_date=start_date, end_date=end_date)

    # Aggregate per category
    cat_totals: dict[ExpenseCategory, dict] = {}
    grand_total = 0.0
    deductible_total = 0.0

    for exp in expenses:
        amount = float(exp.amount)
        grand_total += amount
        if exp.is_deductible:
            deductible_total += amount

        if exp.category not in cat_totals:
            cat_totals[exp.category] = {"total_amount": 0.0, "count": 0}
        cat_totals[exp.category]["total_amount"] += amount
        cat_totals[exp.category]["count"] += 1

    categories = [
        CategoryBreakdown(
            category=cat,
            total_amount=round(data["total_amount"], 2),
            count=data["count"],
        )
        for cat, data in cat_totals.items()
    ]

    return ExpenseSummaryResponse(
        period_start=start_date,
        period_end=end_date,
        categories=categories,
        grand_total=round(grand_total, 2),
        deductible_total=round(deductible_total, 2),
    )
