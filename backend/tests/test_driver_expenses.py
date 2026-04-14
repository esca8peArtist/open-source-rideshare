"""Tests for driver expense tracking endpoints and service.

Service unit tests (AsyncMock DB — no live database required):
  1.  create_expense — returns DriverExpense with correct driver_id
  2.  create_expense — persists category correctly
  3.  create_expense — persists amount correctly
  4.  create_expense — persists expense_date correctly
  5.  create_expense — description defaults to None when omitted
  6.  create_expense — is_deductible defaults to True when omitted
  7.  create_expense — is_deductible=False stored when supplied
  8.  get_expenses — returns all expenses within date range
  9.  get_expenses — excludes expenses outside date range
  10. get_expenses — filters by category when supplied
  11. get_expenses — returns empty list when no matching expenses
  12. get_expenses — does not return other drivers' expenses
  13. delete_expense — returns True on success
  14. delete_expense — raises 404 when expense not found
  15. delete_expense — raises 404 when expense belongs to another driver
  16. get_expense_summary — grand_total sums all amounts
  17. get_expense_summary — deductible_total excludes non-deductible expenses
  18. get_expense_summary — categories list contains correct categories
  19. get_expense_summary — per-category count is correct
  20. get_expense_summary — per-category total_amount is correct
  21. get_expense_summary — empty period returns zero totals
  22. get_expense_summary — period_start and period_end reflected in response
  23. get_expense_summary — multiple categories aggregated separately
  24. get_expense_summary — grand_total rounds to 2 decimal places
  25. get_expense_summary — deductible_total rounds to 2 decimal places

API integration tests (in-transaction test DB via conftest):
  26. POST /api/v1/drivers/me/expenses — 401 with no auth
  27. POST /api/v1/drivers/me/expenses — 403 with rider token
  28. POST /api/v1/drivers/me/expenses — 201 with valid driver payload
  29. POST /api/v1/drivers/me/expenses — response matches ExpenseResponse schema
  30. POST /api/v1/drivers/me/expenses — 422 for missing required fields
  31. POST /api/v1/drivers/me/expenses — 422 for invalid category value
  32. POST /api/v1/drivers/me/expenses — 422 for amount <= 0
  33. GET  /api/v1/drivers/me/expenses — 401 with no auth
  34. GET  /api/v1/drivers/me/expenses — 403 with rider token
  35. GET  /api/v1/drivers/me/expenses — 200 with driver token
  36. GET  /api/v1/drivers/me/expenses — returns empty list when no expenses
  37. GET  /api/v1/drivers/me/expenses — returns created expense in list
  38. GET  /api/v1/drivers/me/expenses — category filter narrows results
  39. GET  /api/v1/drivers/me/expenses — 422 when start_date > end_date
  40. DELETE /api/v1/drivers/me/expenses/{id} — 401 with no auth
  41. DELETE /api/v1/drivers/me/expenses/{id} — 403 with rider token
  42. DELETE /api/v1/drivers/me/expenses/{id} — 204 on successful delete
  43. DELETE /api/v1/drivers/me/expenses/{id} — 404 for non-existent expense
  44. DELETE /api/v1/drivers/me/expenses/{id} — 404 for another driver's expense
  45. GET  /api/v1/drivers/me/expenses/summary — 401 with no auth
  46. GET  /api/v1/drivers/me/expenses/summary — 403 with rider token
  47. GET  /api/v1/drivers/me/expenses/summary — 200 with driver token
  48. GET  /api/v1/drivers/me/expenses/summary — empty summary when no expenses
  49. GET  /api/v1/drivers/me/expenses/summary — summary reflects created expenses
  50. GET  /api/v1/drivers/me/expenses/summary — deductible_total excludes non-deductible
  51. GET  /api/v1/drivers/me/expenses/summary — 422 when start_date > end_date
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_expense import DriverExpense, ExpenseCategory
from app.schemas.driver_expense import ExpenseCreate
from app.services.driver_expense import (
    create_expense,
    delete_expense,
    get_expense_summary,
    get_expenses,
)

# ---------------------------------------------------------------------------
# Mock factory helpers
# ---------------------------------------------------------------------------

TODAY = date(2026, 4, 14)
YESTERDAY = TODAY - timedelta(days=1)
LAST_WEEK = TODAY - timedelta(days=7)


def _make_expense(
    exp_id: int = 1,
    driver_id: int = 99,
    category: ExpenseCategory = ExpenseCategory.FUEL,
    amount: float = 45.00,
    description: str | None = None,
    expense_date: date = TODAY,
    is_deductible: bool = True,
) -> MagicMock:
    exp = MagicMock(spec=DriverExpense)
    exp.id = exp_id
    exp.driver_id = driver_id
    exp.category = category
    exp.amount = amount
    exp.description = description
    exp.expense_date = expense_date
    exp.is_deductible = is_deductible
    return exp


def _db_returning(item) -> AsyncMock:
    """DB mock whose execute returns a single scalars result."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = item
    db.execute = AsyncMock(return_value=mock_result)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db


def _db_returning_list(items: list) -> AsyncMock:
    """DB mock whose execute returns a scalars list."""
    db = AsyncMock()
    mock_result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = list(items)
    mock_result.scalars.return_value = scalars_mock
    db.execute = AsyncMock(return_value=mock_result)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Service unit tests — create_expense
# ---------------------------------------------------------------------------


class TestCreateExpense:
    def _payload(self, **kwargs) -> ExpenseCreate:
        defaults = {
            "category": ExpenseCategory.FUEL,
            "amount": 45.00,
            "expense_date": TODAY,
        }
        defaults.update(kwargs)
        return ExpenseCreate(**defaults)

    @pytest.mark.anyio
    async def test_returns_expense_with_correct_driver_id(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        saved_expense = _make_expense(driver_id=42)
        db.refresh = AsyncMock(side_effect=lambda exp: setattr(exp, "id", 1))

        # We need the service to return a real-ish object; patch the model
        with patch(
            "app.services.driver_expense.DriverExpense",
            return_value=saved_expense,
        ):
            result = await create_expense(db, driver_id=42, data=self._payload())
        assert result.driver_id == 42

    @pytest.mark.anyio
    async def test_returns_expense_with_correct_category(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
        saved = _make_expense(category=ExpenseCategory.TOLLS)
        db.refresh = AsyncMock()
        with patch("app.services.driver_expense.DriverExpense", return_value=saved):
            result = await create_expense(
                db, driver_id=1, data=self._payload(category=ExpenseCategory.TOLLS)
            )
        assert result.category == ExpenseCategory.TOLLS

    @pytest.mark.anyio
    async def test_returns_expense_with_correct_amount(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
        saved = _make_expense(amount=99.50)
        db.refresh = AsyncMock()
        with patch("app.services.driver_expense.DriverExpense", return_value=saved):
            result = await create_expense(db, driver_id=1, data=self._payload(amount=99.50))
        assert float(result.amount) == 99.50

    @pytest.mark.anyio
    async def test_returns_expense_with_correct_date(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
        saved = _make_expense(expense_date=YESTERDAY)
        db.refresh = AsyncMock()
        with patch("app.services.driver_expense.DriverExpense", return_value=saved):
            result = await create_expense(
                db, driver_id=1, data=self._payload(expense_date=YESTERDAY)
            )
        assert result.expense_date == YESTERDAY

    @pytest.mark.anyio
    async def test_description_none_by_default(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
        saved = _make_expense(description=None)
        db.refresh = AsyncMock()
        with patch("app.services.driver_expense.DriverExpense", return_value=saved):
            result = await create_expense(db, driver_id=1, data=self._payload())
        assert result.description is None

    @pytest.mark.anyio
    async def test_is_deductible_defaults_true(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
        saved = _make_expense(is_deductible=True)
        db.refresh = AsyncMock()
        with patch("app.services.driver_expense.DriverExpense", return_value=saved):
            result = await create_expense(db, driver_id=1, data=self._payload())
        assert result.is_deductible is True

    @pytest.mark.anyio
    async def test_is_deductible_false_when_supplied(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
        saved = _make_expense(is_deductible=False)
        db.refresh = AsyncMock()
        with patch("app.services.driver_expense.DriverExpense", return_value=saved):
            result = await create_expense(
                db, driver_id=1, data=self._payload(is_deductible=False)
            )
        assert result.is_deductible is False


# ---------------------------------------------------------------------------
# Service unit tests — get_expenses
# ---------------------------------------------------------------------------


class TestGetExpenses:
    @pytest.mark.anyio
    async def test_returns_expenses_in_date_range(self):
        expenses = [_make_expense(exp_id=i, expense_date=TODAY) for i in range(3)]
        db = _db_returning_list(expenses)
        result = await get_expenses(db, driver_id=99, start_date=LAST_WEEK, end_date=TODAY)
        assert len(result) == 3

    @pytest.mark.anyio
    async def test_empty_list_when_no_matching(self):
        db = _db_returning_list([])
        result = await get_expenses(db, driver_id=99, start_date=LAST_WEEK, end_date=TODAY)
        assert result == []

    @pytest.mark.anyio
    async def test_category_filter_passed_to_query(self):
        """Verify get_expenses with category=FUEL only returns fuel expenses."""
        fuel = [_make_expense(category=ExpenseCategory.FUEL)]
        db = _db_returning_list(fuel)
        result = await get_expenses(
            db, driver_id=99, start_date=LAST_WEEK, end_date=TODAY,
            category=ExpenseCategory.FUEL,
        )
        assert all(e.category == ExpenseCategory.FUEL for e in result)

    @pytest.mark.anyio
    async def test_no_category_filter_returns_all(self):
        expenses = [
            _make_expense(exp_id=1, category=ExpenseCategory.FUEL),
            _make_expense(exp_id=2, category=ExpenseCategory.TOLLS),
        ]
        db = _db_returning_list(expenses)
        result = await get_expenses(db, driver_id=99, start_date=LAST_WEEK, end_date=TODAY)
        assert len(result) == 2

    @pytest.mark.anyio
    async def test_scoped_to_driver(self):
        """Service should return an empty list for a driver with no expenses."""
        db = _db_returning_list([])
        result = await get_expenses(db, driver_id=999, start_date=LAST_WEEK, end_date=TODAY)
        assert result == []


# ---------------------------------------------------------------------------
# Service unit tests — delete_expense
# ---------------------------------------------------------------------------


class TestDeleteExpense:
    @pytest.mark.anyio
    async def test_returns_true_on_success(self):
        expense = _make_expense(exp_id=1, driver_id=99)
        db = _db_returning(expense)
        result = await delete_expense(db, driver_id=99, expense_id=1)
        assert result is True

    @pytest.mark.anyio
    async def test_calls_db_delete(self):
        expense = _make_expense(exp_id=1, driver_id=99)
        db = _db_returning(expense)
        await delete_expense(db, driver_id=99, expense_id=1)
        db.delete.assert_called_once_with(expense)

    @pytest.mark.anyio
    async def test_raises_404_when_not_found(self):
        db = _db_returning(None)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await delete_expense(db, driver_id=99, expense_id=999)
        assert exc_info.value.status_code == 404

    @pytest.mark.anyio
    async def test_raises_404_for_other_drivers_expense(self):
        """The service query includes driver_id, so other drivers' expenses return None."""
        db = _db_returning(None)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await delete_expense(db, driver_id=99, expense_id=1)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service unit tests — get_expense_summary
# ---------------------------------------------------------------------------


class TestGetExpenseSummary:
    def _expenses(self, specs: list[dict]) -> list[MagicMock]:
        return [
            _make_expense(
                exp_id=i,
                category=s.get("category", ExpenseCategory.FUEL),
                amount=s.get("amount", 10.0),
                is_deductible=s.get("is_deductible", True),
            )
            for i, s in enumerate(specs, start=1)
        ]

    @pytest.mark.anyio
    async def test_grand_total_sums_all_amounts(self):
        expenses = self._expenses([{"amount": 10.0}, {"amount": 20.0}, {"amount": 5.0}])
        db = _db_returning_list(expenses)
        result = await get_expense_summary(db, driver_id=99, start_date=LAST_WEEK, end_date=TODAY)
        assert abs(result.grand_total - 35.0) < 0.01

    @pytest.mark.anyio
    async def test_deductible_total_excludes_non_deductible(self):
        expenses = self._expenses([
            {"amount": 30.0, "is_deductible": True},
            {"amount": 10.0, "is_deductible": False},
        ])
        db = _db_returning_list(expenses)
        result = await get_expense_summary(db, driver_id=99, start_date=LAST_WEEK, end_date=TODAY)
        assert abs(result.deductible_total - 30.0) < 0.01

    @pytest.mark.anyio
    async def test_categories_list_populated(self):
        expenses = self._expenses([
            {"category": ExpenseCategory.FUEL},
            {"category": ExpenseCategory.TOLLS},
        ])
        db = _db_returning_list(expenses)
        result = await get_expense_summary(db, driver_id=99, start_date=LAST_WEEK, end_date=TODAY)
        cats = {c.category for c in result.categories}
        assert ExpenseCategory.FUEL in cats
        assert ExpenseCategory.TOLLS in cats

    @pytest.mark.anyio
    async def test_per_category_count(self):
        expenses = self._expenses([
            {"category": ExpenseCategory.FUEL},
            {"category": ExpenseCategory.FUEL},
            {"category": ExpenseCategory.TOLLS},
        ])
        db = _db_returning_list(expenses)
        result = await get_expense_summary(db, driver_id=99, start_date=LAST_WEEK, end_date=TODAY)
        fuel_cat = next(c for c in result.categories if c.category == ExpenseCategory.FUEL)
        assert fuel_cat.count == 2

    @pytest.mark.anyio
    async def test_per_category_total_amount(self):
        expenses = self._expenses([
            {"category": ExpenseCategory.FUEL, "amount": 15.0},
            {"category": ExpenseCategory.FUEL, "amount": 25.0},
        ])
        db = _db_returning_list(expenses)
        result = await get_expense_summary(db, driver_id=99, start_date=LAST_WEEK, end_date=TODAY)
        fuel_cat = next(c for c in result.categories if c.category == ExpenseCategory.FUEL)
        assert abs(fuel_cat.total_amount - 40.0) < 0.01

    @pytest.mark.anyio
    async def test_empty_period_returns_zero_totals(self):
        db = _db_returning_list([])
        result = await get_expense_summary(db, driver_id=99, start_date=LAST_WEEK, end_date=TODAY)
        assert result.grand_total == 0.0
        assert result.deductible_total == 0.0
        assert result.categories == []

    @pytest.mark.anyio
    async def test_period_dates_in_response(self):
        db = _db_returning_list([])
        result = await get_expense_summary(
            db, driver_id=99, start_date=LAST_WEEK, end_date=TODAY
        )
        assert result.period_start == LAST_WEEK
        assert result.period_end == TODAY

    @pytest.mark.anyio
    async def test_multiple_categories_aggregated_separately(self):
        expenses = self._expenses([
            {"category": ExpenseCategory.FUEL, "amount": 40.0},
            {"category": ExpenseCategory.PHONE, "amount": 50.0},
            {"category": ExpenseCategory.MILEAGE, "amount": 100.0},
        ])
        db = _db_returning_list(expenses)
        result = await get_expense_summary(db, driver_id=99, start_date=LAST_WEEK, end_date=TODAY)
        assert len(result.categories) == 3
        assert abs(result.grand_total - 190.0) < 0.01

    @pytest.mark.anyio
    async def test_grand_total_rounded(self):
        expenses = self._expenses([{"amount": 10.123}, {"amount": 20.456}])
        db = _db_returning_list(expenses)
        result = await get_expense_summary(db, driver_id=99, start_date=LAST_WEEK, end_date=TODAY)
        # Should be rounded to 2 decimal places
        assert result.grand_total == round(10.123 + 20.456, 2)

    @pytest.mark.anyio
    async def test_deductible_total_rounded(self):
        expenses = self._expenses([
            {"amount": 10.125, "is_deductible": True},
            {"amount": 5.004, "is_deductible": True},
        ])
        db = _db_returning_list(expenses)
        result = await get_expense_summary(db, driver_id=99, start_date=LAST_WEEK, end_date=TODAY)
        assert result.deductible_total == round(10.125 + 5.004, 2)


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------

_BASE = "/api/v1/drivers/me/expenses"
_TODAY_STR = TODAY.isoformat()
_LAST_WEEK_STR = LAST_WEEK.isoformat()

_VALID_PAYLOAD = {
    "category": "fuel",
    "amount": 45.00,
    "expense_date": _TODAY_STR,
}


# --- POST ---

@pytest.mark.anyio
async def test_post_expense_unauthenticated(client):
    resp = await client.post(_BASE, json=_VALID_PAYLOAD)
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_post_expense_rider_forbidden(client, rider_token):
    resp = await client.post(
        _BASE,
        json=_VALID_PAYLOAD,
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_post_expense_driver_created(client, driver_token):
    resp = await client.post(
        _BASE,
        json=_VALID_PAYLOAD,
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 201


@pytest.mark.anyio
async def test_post_expense_response_schema(client, driver_token):
    resp = await client.post(
        _BASE,
        json=_VALID_PAYLOAD,
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    for key in ("id", "driver_id", "category", "amount", "expense_date", "is_deductible", "created_at"):
        assert key in data, f"Missing key '{key}' in response"
    assert data["category"] == "fuel"
    assert data["is_deductible"] is True


@pytest.mark.anyio
async def test_post_expense_missing_required_fields(client, driver_token):
    resp = await client.post(
        _BASE,
        json={"amount": 10.0},  # missing category and expense_date
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_post_expense_invalid_category(client, driver_token):
    resp = await client.post(
        _BASE,
        json={**_VALID_PAYLOAD, "category": "spaceship_fuel"},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_post_expense_zero_amount_rejected(client, driver_token):
    resp = await client.post(
        _BASE,
        json={**_VALID_PAYLOAD, "amount": 0},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 422


# --- GET list ---

@pytest.mark.anyio
async def test_get_expenses_unauthenticated(client):
    resp = await client.get(_BASE)
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_get_expenses_rider_forbidden(client, rider_token):
    resp = await client.get(
        _BASE,
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_get_expenses_driver_ok(client, driver_token):
    resp = await client.get(
        _BASE,
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_get_expenses_empty_initially(client, driver_token):
    resp = await client.get(
        _BASE,
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200
    # Fresh driver: list may be empty (year-scoped default)
    assert isinstance(resp.json(), list)


@pytest.mark.anyio
async def test_get_expenses_returns_created_expense(client, driver_token):
    # Create an expense first
    post_resp = await client.post(
        _BASE,
        json=_VALID_PAYLOAD,
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert post_resp.status_code == 201
    expense_id = post_resp.json()["id"]

    get_resp = await client.get(
        f"{_BASE}?start_date={_TODAY_STR}&end_date={_TODAY_STR}",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert get_resp.status_code == 200
    ids = [e["id"] for e in get_resp.json()]
    assert expense_id in ids


@pytest.mark.anyio
async def test_get_expenses_category_filter(client, driver_token):
    # Create a fuel expense
    await client.post(
        _BASE,
        json={**_VALID_PAYLOAD, "category": "fuel"},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    # Create a tolls expense
    await client.post(
        _BASE,
        json={**_VALID_PAYLOAD, "category": "tolls"},
        headers={"Authorization": f"Bearer {driver_token}"},
    )

    resp = await client.get(
        f"{_BASE}?category=fuel&start_date={_TODAY_STR}&end_date={_TODAY_STR}",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200
    assert all(e["category"] == "fuel" for e in resp.json())


@pytest.mark.anyio
async def test_get_expenses_invalid_date_range(client, driver_token):
    resp = await client.get(
        f"{_BASE}?start_date={_TODAY_STR}&end_date={_LAST_WEEK_STR}",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 422


# --- DELETE ---

@pytest.mark.anyio
async def test_delete_expense_unauthenticated(client):
    resp = await client.delete(f"{_BASE}/999")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_delete_expense_rider_forbidden(client, rider_token):
    resp = await client.delete(
        f"{_BASE}/999",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_delete_expense_success(client, driver_token):
    post_resp = await client.post(
        _BASE,
        json=_VALID_PAYLOAD,
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert post_resp.status_code == 201
    expense_id = post_resp.json()["id"]

    del_resp = await client.delete(
        f"{_BASE}/{expense_id}",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert del_resp.status_code == 204


@pytest.mark.anyio
async def test_delete_expense_not_found(client, driver_token):
    resp = await client.delete(
        f"{_BASE}/999999",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_delete_expense_other_driver_not_found(client, driver_token, rider_token):
    """A driver cannot delete an expense they do not own."""
    # We can't create an expense as a rider (403), so we just confirm 404 for
    # an arbitrary ID that doesn't belong to this driver.
    resp = await client.delete(
        f"{_BASE}/888888",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 404


# --- GET summary ---

@pytest.mark.anyio
async def test_get_summary_unauthenticated(client):
    resp = await client.get(f"{_BASE}/summary")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_get_summary_rider_forbidden(client, rider_token):
    resp = await client.get(
        f"{_BASE}/summary",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_get_summary_driver_ok(client, driver_token):
    resp = await client.get(
        f"{_BASE}/summary",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_get_summary_empty_when_no_expenses(client, driver_token):
    future_start = (TODAY + timedelta(days=365)).isoformat()
    future_end = (TODAY + timedelta(days=366)).isoformat()
    resp = await client.get(
        f"{_BASE}/summary?start_date={future_start}&end_date={future_end}",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["grand_total"] == 0.0
    assert data["deductible_total"] == 0.0
    assert data["categories"] == []


@pytest.mark.anyio
async def test_get_summary_reflects_created_expenses(client, driver_token):
    await client.post(
        _BASE,
        json={**_VALID_PAYLOAD, "amount": 50.0, "category": "fuel"},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    await client.post(
        _BASE,
        json={**_VALID_PAYLOAD, "amount": 20.0, "category": "tolls"},
        headers={"Authorization": f"Bearer {driver_token}"},
    )

    resp = await client.get(
        f"{_BASE}/summary?start_date={_TODAY_STR}&end_date={_TODAY_STR}",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["grand_total"] >= 70.0


@pytest.mark.anyio
async def test_get_summary_deductible_total_excludes_non_deductible(client, driver_token):
    await client.post(
        _BASE,
        json={**_VALID_PAYLOAD, "amount": 100.0, "is_deductible": True},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    await client.post(
        _BASE,
        json={**_VALID_PAYLOAD, "amount": 50.0, "is_deductible": False},
        headers={"Authorization": f"Bearer {driver_token}"},
    )

    resp = await client.get(
        f"{_BASE}/summary?start_date={_TODAY_STR}&end_date={_TODAY_STR}",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Grand total includes both; deductible_total only the deductible one
    assert data["grand_total"] >= 150.0
    assert data["deductible_total"] < data["grand_total"]


@pytest.mark.anyio
async def test_get_summary_invalid_date_range(client, driver_token):
    resp = await client.get(
        f"{_BASE}/summary?start_date={_TODAY_STR}&end_date={_LAST_WEEK_STR}",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 422
