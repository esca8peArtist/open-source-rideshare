"""Tests for the Corporate Budget Alerts feature.

Service tests (async, mocked DB):
  1.  create_budget_alert — account scope success
  2.  create_budget_alert — cost_center scope success
  3.  create_budget_alert — cost_center scope missing cost_center_id → 400
  4.  create_budget_alert — threshold_pct=0 → ValidationError (schema)
  5.  create_budget_alert — threshold_pct=101 → ValidationError (schema)
  6.  create_budget_alert — duplicate → 409
  7.  create_budget_alert — cost_center not found → 404
  8.  get_budget_alert — success
  9.  get_budget_alert — wrong account → 404
  10. list_budget_alerts — all returned, total correct
  11. list_budget_alerts — filter by scope
  12. list_budget_alerts — filter by status
  13. update_budget_alert — label update on active alert
  14. update_budget_alert — threshold_pct update on active alert
  15. update_budget_alert — triggered alert → 409
  16. update_budget_alert — acknowledged alert → 409
  17. update_budget_alert — not found → 404
  18. delete_budget_alert — success
  19. delete_budget_alert — not found → 404
  20. acknowledge_alert — happy path (triggered → acknowledged)
  21. acknowledge_alert — active alert → 409
  22. acknowledge_alert — already acknowledged → 409
  23. acknowledge_alert — not found → 404
  24. evaluate_budget_alerts — cost_center triggered (spend >= threshold)
  25. evaluate_budget_alerts — account-level triggered
  26. evaluate_budget_alerts — cost_center not triggered (spend < threshold)
  27. evaluate_budget_alerts — account not triggered (spend < threshold)
  28. evaluate_budget_alerts — already triggered alert skipped
  29. evaluate_budget_alerts — already acknowledged alert skipped
  30. evaluate_budget_alerts — correct fields recorded at trigger
  31. evaluate_budget_alerts — cost_center with no budget skipped
  32. evaluate_budget_alerts — account with no budget_limit skipped
  33. evaluate_budget_alerts — no active alerts returns empty list

Schema tests (sync):
  34. BudgetAlertCreate — valid account scope
  35. BudgetAlertCreate — threshold_pct bounds (1 and 100 valid)
  36. BudgetAlertCreate — threshold_pct=0 → ValidationError
  37. BudgetAlertCreate — threshold_pct=101 → ValidationError
  38. BudgetAlertUpdate — all fields optional
  39. BudgetAlertResponse — from_attributes pattern

API layer tests (asyncio, service patched):
  40. POST /corporate/accounts/me/budget-alerts — 201
  41. GET  /corporate/accounts/me/budget-alerts — 200 list
  42. GET  /corporate/accounts/me/budget-alerts/{id} — 200
  43. PATCH /corporate/accounts/me/budget-alerts/{id} — 200
  44. DELETE /corporate/accounts/me/budget-alerts/{id} — 204
  45. POST /corporate/accounts/me/budget-alerts/{id}/acknowledge — 200
  46. POST /corporate/accounts/me/budget-alerts/evaluate — 200
  47. GET  /admin/corporate/accounts/{id}/budget-alerts — 200
  48. POST /admin/corporate/accounts/{id}/budget-alerts/evaluate — 200
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_budget_alert import (
    BudgetAlertScope,
    BudgetAlertStatus,
    CorporateBudgetAlert,
)
from app.schemas.corporate_budget_alert import (
    BudgetAlertCreate,
    BudgetAlertListResponse,
    BudgetAlertResponse,
    BudgetAlertUpdate,
    EvaluateAlertsRequest,
    EvaluateAlertsResponse,
)
from app.services.corporate_budget_alert import (
    acknowledge_alert,
    create_budget_alert,
    delete_budget_alert,
    evaluate_budget_alerts,
    get_budget_alert,
    list_budget_alerts,
    update_budget_alert,
)


# ---------------------------------------------------------------------------
# Shared constants and helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
BILLING_MONTH = date(2026, 4, 1)
ACCOUNT_ID = 10
OTHER_ACCOUNT_ID = 20
COST_CENTER_ID = 5
USER_ID = 1
ALERT_ID = uuid.uuid4()
ALERT_ID_2 = uuid.uuid4()


def _make_alert(
    alert_id: uuid.UUID = ALERT_ID,
    account_id: int = ACCOUNT_ID,
    scope: BudgetAlertScope = BudgetAlertScope.account,
    cost_center_id: int | None = None,
    threshold_pct: int = 80,
    label: str | None = "80% Warning",
    status: BudgetAlertStatus = BudgetAlertStatus.active,
    triggered_at: datetime | None = None,
    acknowledged_at: datetime | None = None,
    acknowledged_by_id: int | None = None,
    billing_month: date | None = None,
    spend_at_trigger_usd: Decimal | None = None,
    budget_at_trigger_usd: Decimal | None = None,
    cost_center=None,
) -> MagicMock:
    a = MagicMock(spec=CorporateBudgetAlert)
    a.id = alert_id
    a.corporate_account_id = account_id
    a.scope = scope
    a.cost_center_id = cost_center_id
    a.threshold_pct = threshold_pct
    a.label = label
    a.status = status
    a.triggered_at = triggered_at
    a.acknowledged_at = acknowledged_at
    a.acknowledged_by_id = acknowledged_by_id
    a.billing_month = billing_month
    a.spend_at_trigger_usd = spend_at_trigger_usd
    a.budget_at_trigger_usd = budget_at_trigger_usd
    a.cost_center = cost_center
    a.created_at = NOW
    a.updated_at = NOW
    return a


def _make_cost_center(
    cc_id: int = COST_CENTER_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Engineering",
    code: str = "ENG",
    monthly_budget: Decimal | None = Decimal("1000.00"),
) -> MagicMock:
    cc = MagicMock()
    cc.id = cc_id
    cc.account_id = account_id
    cc.name = name
    cc.code = code
    cc.monthly_budget = monthly_budget
    return cc


def _make_account(
    account_id: int = ACCOUNT_ID,
    monthly_budget_limit: Decimal | None = Decimal("5000.00"),
) -> MagicMock:
    acc = MagicMock()
    acc.id = account_id
    acc.monthly_budget_limit = monthly_budget_limit
    return acc


def _scalar_result(value) -> MagicMock:
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    res.scalar.return_value = value
    return res


def _scalars_result(rows: list) -> MagicMock:
    res = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = rows
    res.scalars.return_value = scalars_mock
    return res


def _one_result(row) -> MagicMock:
    res = MagicMock()
    res.one.return_value = row
    res.scalar.return_value = row
    return res


# ---------------------------------------------------------------------------
# 1. create_budget_alert — account scope success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_budget_alert_account_scope():
    db = AsyncMock()
    db.add = MagicMock()
    # No duplicate found
    db.execute.return_value = _scalar_result(None)

    data = BudgetAlertCreate(scope="account", threshold_pct=80)
    result = await create_budget_alert(db, ACCOUNT_ID, data)

    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    assert result.corporate_account_id == ACCOUNT_ID
    assert result.scope == BudgetAlertScope.account
    assert result.threshold_pct == 80
    assert result.cost_center_id is None
    assert result.status == BudgetAlertStatus.active


# ---------------------------------------------------------------------------
# 2. create_budget_alert — cost_center scope success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_budget_alert_cost_center_scope():
    db = AsyncMock()
    db.add = MagicMock()
    cc = _make_cost_center()

    # First call: fetch cost center; second call: check duplicate
    db.execute.side_effect = [
        _scalar_result(cc),   # cost center lookup
        _scalar_result(None), # duplicate check
    ]

    data = BudgetAlertCreate(
        scope="cost_center", cost_center_id=COST_CENTER_ID, threshold_pct=75
    )
    result = await create_budget_alert(db, ACCOUNT_ID, data)

    assert result.scope == BudgetAlertScope.cost_center
    assert result.cost_center_id == COST_CENTER_ID
    assert result.threshold_pct == 75


# ---------------------------------------------------------------------------
# 3. create_budget_alert — cost_center scope missing cost_center_id → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_budget_alert_cost_center_missing_id():
    db = AsyncMock()

    data = BudgetAlertCreate(scope="cost_center", threshold_pct=80)
    with pytest.raises(HTTPException) as exc_info:
        await create_budget_alert(db, ACCOUNT_ID, data)

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 4. BudgetAlertCreate threshold_pct=0 → ValidationError
# ---------------------------------------------------------------------------


def test_create_schema_threshold_zero():
    with pytest.raises(ValidationError):
        BudgetAlertCreate(scope="account", threshold_pct=0)


# ---------------------------------------------------------------------------
# 5. BudgetAlertCreate threshold_pct=101 → ValidationError
# ---------------------------------------------------------------------------


def test_create_schema_threshold_over_100():
    with pytest.raises(ValidationError):
        BudgetAlertCreate(scope="account", threshold_pct=101)


# ---------------------------------------------------------------------------
# 6. create_budget_alert — duplicate → 409
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_budget_alert_duplicate_409():
    db = AsyncMock()
    existing = _make_alert()
    # First call (account scope): duplicate check returns existing
    db.execute.return_value = _scalar_result(existing)

    data = BudgetAlertCreate(scope="account", threshold_pct=80)
    with pytest.raises(HTTPException) as exc_info:
        await create_budget_alert(db, ACCOUNT_ID, data)

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 7. create_budget_alert — cost_center not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_budget_alert_cost_center_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    data = BudgetAlertCreate(
        scope="cost_center", cost_center_id=999, threshold_pct=80
    )
    with pytest.raises(HTTPException) as exc_info:
        await create_budget_alert(db, ACCOUNT_ID, data)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 8. get_budget_alert — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_budget_alert_success():
    db = AsyncMock()
    alert = _make_alert()
    db.execute.return_value = _scalar_result(alert)

    result = await get_budget_alert(db, ACCOUNT_ID, ALERT_ID)
    assert result is alert


# ---------------------------------------------------------------------------
# 9. get_budget_alert — wrong account → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_budget_alert_wrong_account():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_budget_alert(db, OTHER_ACCOUNT_ID, ALERT_ID)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 10. list_budget_alerts — all returned, total correct
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_budget_alerts_all():
    db = AsyncMock()
    alerts = [_make_alert(), _make_alert(alert_id=ALERT_ID_2)]

    count_res = MagicMock()
    count_res.scalar.return_value = 2
    scalars_res = _scalars_result(alerts)

    db.execute.side_effect = [count_res, scalars_res]

    result_alerts, total = await list_budget_alerts(db, ACCOUNT_ID)
    assert len(result_alerts) == 2
    assert total == 2


# ---------------------------------------------------------------------------
# 11. list_budget_alerts — filter by scope
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_budget_alerts_filter_scope():
    db = AsyncMock()
    alert = _make_alert(scope=BudgetAlertScope.account)

    count_res = MagicMock()
    count_res.scalar.return_value = 1
    db.execute.side_effect = [count_res, _scalars_result([alert])]

    results, total = await list_budget_alerts(db, ACCOUNT_ID, scope="account")
    assert total == 1
    assert results[0].scope == BudgetAlertScope.account


# ---------------------------------------------------------------------------
# 12. list_budget_alerts — filter by status
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_budget_alerts_filter_status():
    db = AsyncMock()
    alert = _make_alert(status=BudgetAlertStatus.triggered)

    count_res = MagicMock()
    count_res.scalar.return_value = 1
    db.execute.side_effect = [count_res, _scalars_result([alert])]

    results, total = await list_budget_alerts(db, ACCOUNT_ID, status_filter="triggered")
    assert results[0].status == BudgetAlertStatus.triggered


# ---------------------------------------------------------------------------
# 13. update_budget_alert — label update on active alert
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_budget_alert_label():
    db = AsyncMock()
    alert = _make_alert(status=BudgetAlertStatus.active, label="Old Label")
    db.execute.return_value = _scalar_result(alert)
    db.add = MagicMock()

    data = BudgetAlertUpdate(label="New Label")
    result = await update_budget_alert(db, ACCOUNT_ID, ALERT_ID, data)

    assert alert.label == "New Label"
    assert result is alert


# ---------------------------------------------------------------------------
# 14. update_budget_alert — threshold_pct update on active alert
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_budget_alert_threshold_pct():
    db = AsyncMock()
    alert = _make_alert(status=BudgetAlertStatus.active, threshold_pct=80)
    db.execute.return_value = _scalar_result(alert)
    db.add = MagicMock()

    data = BudgetAlertUpdate(threshold_pct=90)
    result = await update_budget_alert(db, ACCOUNT_ID, ALERT_ID, data)

    assert alert.threshold_pct == 90
    assert result is alert


# ---------------------------------------------------------------------------
# 15. update_budget_alert — triggered alert → 409
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_triggered_alert_rejected():
    db = AsyncMock()
    alert = _make_alert(status=BudgetAlertStatus.triggered)
    db.execute.return_value = _scalar_result(alert)

    with pytest.raises(HTTPException) as exc_info:
        await update_budget_alert(db, ACCOUNT_ID, ALERT_ID, BudgetAlertUpdate(label="X"))

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 16. update_budget_alert — acknowledged alert → 409
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_acknowledged_alert_rejected():
    db = AsyncMock()
    alert = _make_alert(status=BudgetAlertStatus.acknowledged)
    db.execute.return_value = _scalar_result(alert)

    with pytest.raises(HTTPException) as exc_info:
        await update_budget_alert(db, ACCOUNT_ID, ALERT_ID, BudgetAlertUpdate(label="X"))

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 17. update_budget_alert — not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_budget_alert_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await update_budget_alert(db, ACCOUNT_ID, ALERT_ID, BudgetAlertUpdate())

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 18. delete_budget_alert — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_budget_alert_success():
    db = AsyncMock()
    alert = _make_alert()
    db.execute.return_value = _scalar_result(alert)
    db.delete = AsyncMock()

    await delete_budget_alert(db, ACCOUNT_ID, ALERT_ID)

    db.delete.assert_awaited_once_with(alert)
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 19. delete_budget_alert — not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_budget_alert_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await delete_budget_alert(db, ACCOUNT_ID, ALERT_ID)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 20. acknowledge_alert — happy path (triggered → acknowledged)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_acknowledge_alert_success():
    db = AsyncMock()
    alert = _make_alert(status=BudgetAlertStatus.triggered)
    db.execute.return_value = _scalar_result(alert)
    db.add = MagicMock()

    result = await acknowledge_alert(db, ACCOUNT_ID, ALERT_ID, USER_ID)

    assert alert.status == BudgetAlertStatus.acknowledged
    assert alert.acknowledged_by_id == USER_ID
    assert alert.acknowledged_at is not None
    assert result is alert


# ---------------------------------------------------------------------------
# 21. acknowledge_alert — active alert → 409
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_acknowledge_active_alert_rejected():
    db = AsyncMock()
    alert = _make_alert(status=BudgetAlertStatus.active)
    db.execute.return_value = _scalar_result(alert)

    with pytest.raises(HTTPException) as exc_info:
        await acknowledge_alert(db, ACCOUNT_ID, ALERT_ID, USER_ID)

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 22. acknowledge_alert — already acknowledged → 409
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_acknowledge_already_acknowledged():
    db = AsyncMock()
    alert = _make_alert(
        status=BudgetAlertStatus.acknowledged,
        acknowledged_at=NOW,
        acknowledged_by_id=USER_ID,
    )
    db.execute.return_value = _scalar_result(alert)

    with pytest.raises(HTTPException) as exc_info:
        await acknowledge_alert(db, ACCOUNT_ID, ALERT_ID, USER_ID)

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 23. acknowledge_alert — not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_acknowledge_alert_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await acknowledge_alert(db, ACCOUNT_ID, ALERT_ID, USER_ID)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# evaluate_budget_alerts helpers
# ---------------------------------------------------------------------------


def _make_row(value) -> MagicMock:
    """A mock query row with a total_spend attribute."""
    row = MagicMock()
    row.total_spend = value
    return row


# ---------------------------------------------------------------------------
# 24. evaluate_budget_alerts — cost_center triggered (spend >= threshold)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_cost_center_triggered():
    db = AsyncMock()
    db.add = MagicMock()

    account = _make_account(monthly_budget_limit=Decimal("5000.00"))
    cc = _make_cost_center(monthly_budget=Decimal("1000.00"))
    alert = _make_alert(
        scope=BudgetAlertScope.cost_center,
        cost_center_id=COST_CENTER_ID,
        threshold_pct=80,
        status=BudgetAlertStatus.active,
    )

    spend_row = _make_row(Decimal("850.00"))  # 85% >= 80%

    db.execute.side_effect = [
        _scalar_result(account),           # _get_account
        _scalars_result([alert]),           # active alerts
        _scalar_result(cc),                 # cost center lookup
        _one_result(spend_row),             # _get_cost_center_spend
    ]

    triggered = await evaluate_budget_alerts(db, ACCOUNT_ID, BILLING_MONTH)

    assert len(triggered) == 1
    assert triggered[0] is alert
    assert alert.status == BudgetAlertStatus.triggered
    assert alert.triggered_at is not None


# ---------------------------------------------------------------------------
# 25. evaluate_budget_alerts — account-level triggered
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_account_level_triggered():
    db = AsyncMock()
    db.add = MagicMock()

    account = _make_account(monthly_budget_limit=Decimal("5000.00"))
    alert = _make_alert(
        scope=BudgetAlertScope.account,
        threshold_pct=75,
        status=BudgetAlertStatus.active,
    )

    spend_row = _make_row(Decimal("4000.00"))  # 80% >= 75%

    db.execute.side_effect = [
        _scalar_result(account),       # _get_account
        _scalars_result([alert]),       # active alerts
        _one_result(spend_row),         # _get_account_spend
    ]

    triggered = await evaluate_budget_alerts(db, ACCOUNT_ID, BILLING_MONTH)

    assert len(triggered) == 1
    assert triggered[0].status == BudgetAlertStatus.triggered


# ---------------------------------------------------------------------------
# 26. evaluate_budget_alerts — cost_center not triggered (spend < threshold)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_cost_center_not_triggered():
    db = AsyncMock()

    account = _make_account()
    cc = _make_cost_center(monthly_budget=Decimal("1000.00"))
    alert = _make_alert(
        scope=BudgetAlertScope.cost_center,
        cost_center_id=COST_CENTER_ID,
        threshold_pct=80,
        status=BudgetAlertStatus.active,
    )

    spend_row = _make_row(Decimal("700.00"))  # 70% < 80%

    db.execute.side_effect = [
        _scalar_result(account),
        _scalars_result([alert]),
        _scalar_result(cc),
        _one_result(spend_row),
    ]

    triggered = await evaluate_budget_alerts(db, ACCOUNT_ID, BILLING_MONTH)

    assert len(triggered) == 0
    assert alert.status == BudgetAlertStatus.active


# ---------------------------------------------------------------------------
# 27. evaluate_budget_alerts — account not triggered (spend < threshold)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_account_not_triggered():
    db = AsyncMock()

    account = _make_account(monthly_budget_limit=Decimal("5000.00"))
    alert = _make_alert(
        scope=BudgetAlertScope.account,
        threshold_pct=90,
        status=BudgetAlertStatus.active,
    )

    spend_row = _make_row(Decimal("2000.00"))  # 40% < 90%

    db.execute.side_effect = [
        _scalar_result(account),
        _scalars_result([alert]),
        _one_result(spend_row),
    ]

    triggered = await evaluate_budget_alerts(db, ACCOUNT_ID, BILLING_MONTH)

    assert len(triggered) == 0


# ---------------------------------------------------------------------------
# 28. evaluate_budget_alerts — already triggered alert skipped
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_triggered_alert_skipped():
    db = AsyncMock()

    account = _make_account()
    # No active alerts — the triggered one should not appear in active query
    db.execute.side_effect = [
        _scalar_result(account),
        _scalars_result([]),  # no active alerts
    ]

    triggered = await evaluate_budget_alerts(db, ACCOUNT_ID, BILLING_MONTH)
    assert len(triggered) == 0


# ---------------------------------------------------------------------------
# 29. evaluate_budget_alerts — already acknowledged alert skipped
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_acknowledged_alert_skipped():
    db = AsyncMock()

    account = _make_account()
    db.execute.side_effect = [
        _scalar_result(account),
        _scalars_result([]),  # acknowledged alert not in active set
    ]

    triggered = await evaluate_budget_alerts(db, ACCOUNT_ID, BILLING_MONTH)
    assert len(triggered) == 0


# ---------------------------------------------------------------------------
# 30. evaluate_budget_alerts — correct fields recorded at trigger
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_fields_recorded_at_trigger():
    db = AsyncMock()
    db.add = MagicMock()

    account = _make_account(monthly_budget_limit=Decimal("5000.00"))
    alert = _make_alert(
        scope=BudgetAlertScope.account,
        threshold_pct=75,
        status=BudgetAlertStatus.active,
    )

    spend_row = _make_row(Decimal("4000.00"))

    db.execute.side_effect = [
        _scalar_result(account),
        _scalars_result([alert]),
        _one_result(spend_row),
    ]

    triggered = await evaluate_budget_alerts(db, ACCOUNT_ID, BILLING_MONTH)

    assert len(triggered) == 1
    a = triggered[0]
    assert a.billing_month == BILLING_MONTH
    assert a.spend_at_trigger_usd == Decimal("4000.00")
    assert a.budget_at_trigger_usd == Decimal("5000.00")
    assert a.triggered_at is not None


# ---------------------------------------------------------------------------
# 31. evaluate_budget_alerts — cost_center with no budget skipped
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_cost_center_no_budget_skipped():
    db = AsyncMock()

    account = _make_account()
    cc = _make_cost_center(monthly_budget=None)  # No budget set
    alert = _make_alert(
        scope=BudgetAlertScope.cost_center,
        cost_center_id=COST_CENTER_ID,
        threshold_pct=80,
        status=BudgetAlertStatus.active,
    )

    db.execute.side_effect = [
        _scalar_result(account),
        _scalars_result([alert]),
        _scalar_result(cc),
    ]

    triggered = await evaluate_budget_alerts(db, ACCOUNT_ID, BILLING_MONTH)
    assert len(triggered) == 0


# ---------------------------------------------------------------------------
# 32. evaluate_budget_alerts — account with no budget_limit skipped
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_account_no_budget_limit_skipped():
    db = AsyncMock()

    account = _make_account(monthly_budget_limit=None)
    alert = _make_alert(
        scope=BudgetAlertScope.account,
        threshold_pct=75,
        status=BudgetAlertStatus.active,
    )

    db.execute.side_effect = [
        _scalar_result(account),
        _scalars_result([alert]),
    ]

    triggered = await evaluate_budget_alerts(db, ACCOUNT_ID, BILLING_MONTH)
    assert len(triggered) == 0


# ---------------------------------------------------------------------------
# 33. evaluate_budget_alerts — no active alerts returns empty list
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_no_active_alerts():
    db = AsyncMock()

    account = _make_account()
    db.execute.side_effect = [
        _scalar_result(account),
        _scalars_result([]),
    ]

    triggered = await evaluate_budget_alerts(db, ACCOUNT_ID, BILLING_MONTH)
    assert triggered == []


# ---------------------------------------------------------------------------
# 34. BudgetAlertCreate — valid account scope
# ---------------------------------------------------------------------------


def test_schema_create_account_scope_valid():
    data = BudgetAlertCreate(scope="account", threshold_pct=50)
    assert data.threshold_pct == 50
    assert data.scope == "account"
    assert data.cost_center_id is None
    assert data.label is None


# ---------------------------------------------------------------------------
# 35. BudgetAlertCreate — threshold_pct bounds (1 and 100 valid)
# ---------------------------------------------------------------------------


def test_schema_create_threshold_boundary_valid():
    d1 = BudgetAlertCreate(scope="account", threshold_pct=1)
    d2 = BudgetAlertCreate(scope="account", threshold_pct=100)
    assert d1.threshold_pct == 1
    assert d2.threshold_pct == 100


# ---------------------------------------------------------------------------
# 36. BudgetAlertCreate — threshold_pct=0 → ValidationError
# ---------------------------------------------------------------------------


def test_schema_create_threshold_zero_invalid():
    with pytest.raises(ValidationError):
        BudgetAlertCreate(scope="account", threshold_pct=0)


# ---------------------------------------------------------------------------
# 37. BudgetAlertCreate — threshold_pct=101 → ValidationError
# ---------------------------------------------------------------------------


def test_schema_create_threshold_101_invalid():
    with pytest.raises(ValidationError):
        BudgetAlertCreate(scope="account", threshold_pct=101)


# ---------------------------------------------------------------------------
# 38. BudgetAlertUpdate — all fields optional
# ---------------------------------------------------------------------------


def test_schema_update_all_optional():
    data = BudgetAlertUpdate()
    assert data.label is None
    assert data.threshold_pct is None

    data2 = BudgetAlertUpdate(label="Test", threshold_pct=90)
    assert data2.label == "Test"
    assert data2.threshold_pct == 90


# ---------------------------------------------------------------------------
# 39. BudgetAlertResponse — from_attributes pattern
# ---------------------------------------------------------------------------


def test_schema_response_from_attributes():
    alert = _make_alert()
    resp = BudgetAlertResponse(
        id=alert.id,
        corporate_account_id=alert.corporate_account_id,
        scope=alert.scope,
        cost_center_id=alert.cost_center_id,
        threshold_pct=alert.threshold_pct,
        label=alert.label,
        status=alert.status,
        triggered_at=alert.triggered_at,
        acknowledged_at=alert.acknowledged_at,
        acknowledged_by_id=alert.acknowledged_by_id,
        billing_month=alert.billing_month,
        spend_at_trigger_usd=alert.spend_at_trigger_usd,
        budget_at_trigger_usd=alert.budget_at_trigger_usd,
        created_at=alert.created_at,
        updated_at=alert.updated_at,
    )
    assert resp.id == alert.id
    assert resp.corporate_account_id == ACCOUNT_ID
    assert resp.threshold_pct == 80


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

MEMBERSHIP_MODULE = "app.api.v1.corporate_budget_alerts"


def _make_membership(account_id: int = ACCOUNT_ID) -> MagicMock:
    m = MagicMock()
    m.account_id = account_id
    return m


def _alert_response_payload(alert_id: uuid.UUID = ALERT_ID) -> dict:
    return {
        "id": str(alert_id),
        "corporate_account_id": ACCOUNT_ID,
        "scope": "account",
        "cost_center_id": None,
        "cost_center_code": None,
        "cost_center_name": None,
        "threshold_pct": 80,
        "label": "80% Warning",
        "status": "active",
        "triggered_at": None,
        "acknowledged_at": None,
        "acknowledged_by_id": None,
        "billing_month": None,
        "spend_at_trigger_usd": None,
        "budget_at_trigger_usd": None,
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }


def _api_alert_mock(alert_id: uuid.UUID = ALERT_ID) -> MagicMock:
    a = MagicMock()
    a.id = alert_id
    a.corporate_account_id = ACCOUNT_ID
    a.scope = BudgetAlertScope.account
    a.cost_center_id = None
    a.cost_center = None
    a.threshold_pct = 80
    a.label = "80% Warning"
    a.status = BudgetAlertStatus.active
    a.triggered_at = None
    a.acknowledged_at = None
    a.acknowledged_by_id = None
    a.billing_month = None
    a.spend_at_trigger_usd = None
    a.budget_at_trigger_usd = None
    a.created_at = NOW
    a.updated_at = NOW
    return a


# ---------------------------------------------------------------------------
# 40. POST /corporate/accounts/me/budget-alerts — 201
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_create_budget_alert():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    alert = _api_alert_mock()
    membership = _make_membership()

    async def mock_db():
        db = AsyncMock()
        db.execute.return_value = _scalar_result(membership)
        yield db

    mock_user = MagicMock()
    mock_user.id = USER_ID

    with patch(f"{MEMBERSHIP_MODULE}.create_budget_alert", new=AsyncMock(return_value=alert)):
        with patch(f"{MEMBERSHIP_MODULE}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = mock_db
            try:
                client = TestClient(app)
                response = client.post(
                    "/api/v1/corporate/accounts/me/budget-alerts",
                    json={"scope": "account", "threshold_pct": 80},
                )
                assert response.status_code == 201
            finally:
                app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 41. GET /corporate/accounts/me/budget-alerts — 200 list
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_list_budget_alerts():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    alerts = [_api_alert_mock(), _api_alert_mock(ALERT_ID_2)]
    mock_user = MagicMock()
    mock_user.id = USER_ID

    async def mock_db():
        yield AsyncMock()

    with patch(f"{MEMBERSHIP_MODULE}.list_budget_alerts", new=AsyncMock(return_value=(alerts, 2))):
        with patch(f"{MEMBERSHIP_MODULE}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = mock_db
            try:
                client = TestClient(app)
                response = client.get("/api/v1/corporate/accounts/me/budget-alerts")
                assert response.status_code == 200
                data = response.json()
                assert data["total"] == 2
                assert len(data["items"]) == 2
            finally:
                app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 42. GET /corporate/accounts/me/budget-alerts/{id} — 200
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_get_budget_alert():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    alert = _api_alert_mock()
    mock_user = MagicMock()
    mock_user.id = USER_ID

    async def mock_db():
        yield AsyncMock()

    with patch(f"{MEMBERSHIP_MODULE}.get_budget_alert", new=AsyncMock(return_value=alert)):
        with patch(f"{MEMBERSHIP_MODULE}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = mock_db
            try:
                client = TestClient(app)
                response = client.get(f"/api/v1/corporate/accounts/me/budget-alerts/{ALERT_ID}")
                assert response.status_code == 200
            finally:
                app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 43. PATCH /corporate/accounts/me/budget-alerts/{id} — 200
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_update_budget_alert():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    alert = _api_alert_mock()
    mock_user = MagicMock()
    mock_user.id = USER_ID

    async def mock_db():
        yield AsyncMock()

    with patch(f"{MEMBERSHIP_MODULE}.update_budget_alert", new=AsyncMock(return_value=alert)):
        with patch(f"{MEMBERSHIP_MODULE}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = mock_db
            try:
                client = TestClient(app)
                response = client.patch(
                    f"/api/v1/corporate/accounts/me/budget-alerts/{ALERT_ID}",
                    json={"label": "Updated"},
                )
                assert response.status_code == 200
            finally:
                app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 44. DELETE /corporate/accounts/me/budget-alerts/{id} — 204
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_delete_budget_alert():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_user = MagicMock()
    mock_user.id = USER_ID

    async def mock_db():
        yield AsyncMock()

    with patch(f"{MEMBERSHIP_MODULE}.delete_budget_alert", new=AsyncMock(return_value=None)):
        with patch(f"{MEMBERSHIP_MODULE}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = mock_db
            try:
                client = TestClient(app)
                response = client.delete(f"/api/v1/corporate/accounts/me/budget-alerts/{ALERT_ID}")
                assert response.status_code == 204
            finally:
                app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 45. POST /corporate/accounts/me/budget-alerts/{id}/acknowledge — 200
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_acknowledge_alert():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    alert = _api_alert_mock()
    alert.status = BudgetAlertStatus.acknowledged
    alert.acknowledged_at = NOW
    alert.acknowledged_by_id = USER_ID

    mock_user = MagicMock()
    mock_user.id = USER_ID

    async def mock_db():
        yield AsyncMock()

    with patch(f"{MEMBERSHIP_MODULE}.acknowledge_alert", new=AsyncMock(return_value=alert)):
        with patch(f"{MEMBERSHIP_MODULE}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = mock_db
            try:
                client = TestClient(app)
                response = client.post(
                    f"/api/v1/corporate/accounts/me/budget-alerts/{ALERT_ID}/acknowledge"
                )
                assert response.status_code == 200
            finally:
                app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 46. POST /corporate/accounts/me/budget-alerts/evaluate — 200
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_evaluate_alerts():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    alert = _api_alert_mock()
    alert.status = BudgetAlertStatus.triggered
    alert.triggered_at = NOW

    mock_user = MagicMock()
    mock_user.id = USER_ID

    async def mock_db():
        yield AsyncMock()

    with patch(f"{MEMBERSHIP_MODULE}.evaluate_budget_alerts", new=AsyncMock(return_value=[alert])):
        with patch(f"{MEMBERSHIP_MODULE}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = mock_db
            try:
                client = TestClient(app)
                response = client.post(
                    "/api/v1/corporate/accounts/me/budget-alerts/evaluate",
                    json={"billing_month": "2026-04-01"},
                )
                assert response.status_code == 200
                data = response.json()
                assert data["triggered_count"] == 1
                assert len(data["triggered_alerts"]) == 1
            finally:
                app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 47. GET /admin/corporate/accounts/{id}/budget-alerts — 200
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_admin_list_budget_alerts():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin

    alerts = [_api_alert_mock()]

    async def mock_db():
        yield AsyncMock()

    with patch(f"{MEMBERSHIP_MODULE}.list_budget_alerts", new=AsyncMock(return_value=(alerts, 1))):
        app.dependency_overrides[require_admin] = lambda: None
        app.dependency_overrides[get_db] = mock_db
        try:
            client = TestClient(app)
            response = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/budget-alerts")
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 1
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 48. POST /admin/corporate/accounts/{id}/budget-alerts/evaluate — 200
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_admin_evaluate_budget_alerts():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_db, require_admin

    async def mock_db():
        yield AsyncMock()

    with patch(f"{MEMBERSHIP_MODULE}.evaluate_budget_alerts", new=AsyncMock(return_value=[])):
        app.dependency_overrides[require_admin] = lambda: None
        app.dependency_overrides[get_db] = mock_db
        try:
            client = TestClient(app)
            response = client.post(
                f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/budget-alerts/evaluate",
                json={"billing_month": "2026-04-01"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["triggered_count"] == 0
            assert data["triggered_alerts"] == []
        finally:
            app.dependency_overrides.clear()
