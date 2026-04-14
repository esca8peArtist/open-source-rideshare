"""Driver expense tracking API endpoints.

Drivers can log, list, delete, and summarize their business expenses for
tax and bookkeeping purposes.

Endpoints:
  POST   /drivers/me/expenses              — log a new expense
  GET    /drivers/me/expenses              — list expenses (date range + category filter)
  DELETE /drivers/me/expenses/{expense_id} — delete an expense
  GET    /drivers/me/expenses/summary      — category-level summary for a period
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver
from app.db.database import get_db
from app.models.driver_expense import ExpenseCategory
from app.models.user import User
from app.schemas.driver_expense import ExpenseCreate, ExpenseResponse, ExpenseSummaryResponse
from app.services.driver_expense import (
    create_expense,
    delete_expense,
    get_expense_summary,
    get_expenses,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["driver-expenses"])


def _current_year_start() -> date:
    return date(datetime.now(tz=timezone.utc).year, 1, 1)


def _current_year_end() -> date:
    return date(datetime.now(tz=timezone.utc).year, 12, 31)


# ---------------------------------------------------------------------------
# POST /drivers/me/expenses
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/expenses",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log a driver business expense",
    description=(
        "Creates a new expense record for the authenticated driver. "
        "Supported categories: mileage, fuel, vehicle_maintenance, phone, "
        "tolls, insurance, other. "
        "For the 'mileage' category, supply miles driven in the amount field; "
        "for all other categories supply the dollar amount. "
        "Expenses are flagged as deductible by default."
    ),
)
async def log_expense(
    payload: ExpenseCreate,
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> ExpenseResponse:
    """Log a new business expense for the authenticated driver."""
    expense = await create_expense(db, driver_id=current_user.id, data=payload)
    return ExpenseResponse.model_validate(expense)


# ---------------------------------------------------------------------------
# GET /drivers/me/expenses
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/expenses",
    response_model=list[ExpenseResponse],
    summary="List driver expenses",
    description=(
        "Returns a list of expense records for the authenticated driver "
        "filtered by date range. Both start_date and end_date are inclusive. "
        "Optionally filter by a single category. "
        "Results are ordered by expense_date descending (most recent first). "
        "Defaults to the current calendar year when dates are not supplied."
    ),
)
async def list_expenses(
    start_date: date = Query(
        default=None,
        description="Inclusive start date (YYYY-MM-DD). Defaults to Jan 1 of the current year.",
    ),
    end_date: date = Query(
        default=None,
        description="Inclusive end date (YYYY-MM-DD). Defaults to Dec 31 of the current year.",
    ),
    category: Optional[ExpenseCategory] = Query(
        default=None,
        description="Filter by expense category.",
    ),
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> list[ExpenseResponse]:
    """List expenses for the authenticated driver."""
    if start_date is None:
        start_date = _current_year_start()
    if end_date is None:
        end_date = _current_year_end()
    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_date must not be after end_date.",
        )
    expenses = await get_expenses(
        db, driver_id=current_user.id, start_date=start_date, end_date=end_date, category=category
    )
    return [ExpenseResponse.model_validate(e) for e in expenses]


# ---------------------------------------------------------------------------
# GET /drivers/me/expenses/summary  (must be declared before the {expense_id} route)
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/expenses/summary",
    response_model=ExpenseSummaryResponse,
    summary="Get driver expense summary by category",
    description=(
        "Returns a category-level summary of the authenticated driver's expenses "
        "for the requested period, including per-category totals (amount + count), "
        "a grand total across all categories, and a deductible-only total. "
        "Defaults to the current calendar year."
    ),
)
async def expense_summary(
    start_date: date = Query(
        default=None,
        description="Inclusive start date (YYYY-MM-DD). Defaults to Jan 1 of the current year.",
    ),
    end_date: date = Query(
        default=None,
        description="Inclusive end date (YYYY-MM-DD). Defaults to Dec 31 of the current year.",
    ),
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> ExpenseSummaryResponse:
    """Category-level expense summary for the authenticated driver."""
    if start_date is None:
        start_date = _current_year_start()
    if end_date is None:
        end_date = _current_year_end()
    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_date must not be after end_date.",
        )
    return await get_expense_summary(
        db, driver_id=current_user.id, start_date=start_date, end_date=end_date
    )


# ---------------------------------------------------------------------------
# DELETE /drivers/me/expenses/{expense_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/drivers/me/expenses/{expense_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a driver expense",
    description=(
        "Permanently deletes the specified expense record. "
        "Returns 404 if the expense does not exist or belongs to a different driver."
    ),
)
async def remove_expense(
    expense_id: int,
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an expense owned by the authenticated driver."""
    await delete_expense(db, driver_id=current_user.id, expense_id=expense_id)
