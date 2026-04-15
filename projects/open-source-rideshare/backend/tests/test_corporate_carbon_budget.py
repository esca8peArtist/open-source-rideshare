"""Tests for the Corporate Carbon Budget & ESG Reporting feature.

Service layer (async, mocked DB):
  1.  get_or_create_carbon_budget — creates default record when absent
  2.  get_or_create_carbon_budget — returns existing budget without creating
  3.  update_carbon_budget — creates new budget when none exists
  4.  update_carbon_budget — updates existing budget (partial fields)
  5.  update_carbon_budget — only supplied fields are written (exclude_unset)
  6.  get_account_carbon_summary — 403 when user is not a member
  7.  get_account_carbon_summary — 403 when tracking disabled and non-admin
  8.  get_account_carbon_summary — success: summary with no budget ceiling
  9.  get_account_carbon_summary — success: budget utilisation computed correctly
  10. get_account_carbon_summary — alert_triggered when utilisation >= threshold
  11. get_account_carbon_summary — alert not triggered when utilisation < threshold
  12. get_carbon_trend — 400 when months out of range (0)
  13. get_carbon_trend — 400 when months out of range (25)
  14. get_carbon_trend — 403 when tracking disabled and non-admin
  15. get_carbon_trend — success with ride data
  16. get_carbon_trend — success with empty data (no rides)
  17. get_employee_carbon_breakdown — 400 when period_end before period_start
  18. get_employee_carbon_breakdown — 403 when non-admin
  19. get_employee_carbon_breakdown — success with ride data
  20. get_employee_carbon_breakdown — success with empty list
  21. get_platform_esg_report — 400 when months out of range
  22. get_platform_esg_report — success with data

Schema validation:
  23. CarbonBudgetUpsert — valid (all fields optional)
  24. CarbonBudgetUpsert — monthly_budget_co2_kg must be > 0
  25. CarbonBudgetUpsert — offset_budget_usd must be >= 0
  26. CarbonBudgetUpsert — alert_threshold_pct must be 1–100
  27. CarbonBudgetResponse — from_attributes construction
  28. CarbonSummaryResponse — valid construction with budget
  29. CarbonTrendResponse — valid with data points
  30. EmployeeCarbonBreakdownResponse — valid with employees list
  31. ESGReportResponse — valid with monthly trend

API layer (service functions patched):
  32. GET /corporate/accounts/me/carbon-budget — 200
  33. GET /corporate/accounts/me/carbon-budget — 404 no account
  34. PUT /corporate/accounts/me/carbon-budget — 200
  35. GET /corporate/accounts/me/carbon-summary — 200
  36. GET /corporate/accounts/me/carbon-trend — 200
  37. GET /corporate/accounts/me/carbon/employees — 200
  38. GET /admin/corporate/accounts/{id}/carbon-budget — 200
  39. GET /admin/corporate/carbon/esg-report — 200
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_carbon_budget import CorporateCarbonBudget
from app.schemas.corporate_carbon_budget import (
    CarbonBudgetResponse,
    CarbonBudgetUpsert,
    CarbonSummaryResponse,
    CarbonTrendPoint,
    CarbonTrendResponse,
    EmployeeCarbonBreakdownResponse,
    EmployeeCarbonItem,
    ESGMonthPoint,
    ESGReportResponse,
)
from app.services.corporate_carbon_budget import (
    get_account_carbon_summary,
    get_carbon_trend,
    get_employee_carbon_breakdown,
    get_or_create_carbon_budget,
    get_platform_esg_report,
    update_carbon_budget,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 10
USER_ID = 1
ADMIN_ID = 2
PERIOD_START = date(2026, 4, 1)
PERIOD_END = date(2026, 4, 30)

_SERVICE = "app.services.corporate_carbon_budget"
_ROUTER = "app.api.v1.corporate_carbon_budget"

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_budget(
    account_id: int = ACCOUNT_ID,
    monthly_budget_co2_kg: float | None = None,
    offset_budget_usd: float | None = None,
    tracking_enabled: bool = True,
    alert_threshold_pct: int = 80,
    notes: str | None = None,
    updated_by_id: int | None = None,
) -> CorporateCarbonBudget:
    """Build a minimal CorporateCarbonBudget model instance for testing."""
    b = CorporateCarbonBudget()
    b.id = 1
    b.account_id = account_id
    b.monthly_budget_co2_kg = monthly_budget_co2_kg
    b.offset_budget_usd = offset_budget_usd
    b.tracking_enabled = tracking_enabled
    b.alert_threshold_pct = alert_threshold_pct
    b.notes = notes
    b.updated_by_id = updated_by_id
    b.created_at = _NOW
    b.updated_at = _NOW
    return b


def _make_budget_response(
    account_id: int = ACCOUNT_ID,
    monthly_budget_co2_kg: float | None = None,
    tracking_enabled: bool = True,
    alert_threshold_pct: int = 80,
) -> CarbonBudgetResponse:
    return CarbonBudgetResponse(
        id=1,
        account_id=account_id,
        monthly_budget_co2_kg=Decimal(str(monthly_budget_co2_kg)) if monthly_budget_co2_kg else None,
        offset_budget_usd=None,
        tracking_enabled=tracking_enabled,
        alert_threshold_pct=alert_threshold_pct,
        notes=None,
        updated_by_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_member(
    account_id: int = ACCOUNT_ID,
    user_id: int = USER_ID,
    role: MemberRole = MemberRole.MEMBER,
    is_active: bool = True,
) -> MagicMock:
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = account_id
    m.user_id = user_id
    m.role = role
    m.is_active = is_active
    return m


def _make_admin_member(
    account_id: int = ACCOUNT_ID, user_id: int = ADMIN_ID
) -> MagicMock:
    return _make_member(account_id=account_id, user_id=user_id, role=MemberRole.ADMIN)


def _scalar_result(value) -> MagicMock:
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    return res


def _one_result(**kwargs) -> MagicMock:
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    res = MagicMock()
    res.one.return_value = row
    return res


def _all_result(rows: list) -> MagicMock:
    res = MagicMock()
    res.all.return_value = rows
    return res


def _make_carbon_row(
    total_rides: int = 0,
    total_co2_grams: int = 0,
    green_rides: int = 0,
    offset_paid_rides: int = 0,
    offset_paid_cents: int = 0,
) -> MagicMock:
    row = MagicMock()
    row.total_rides = total_rides
    row.total_co2_grams = total_co2_grams
    row.green_rides = green_rides
    row.offset_paid_rides = offset_paid_rides
    row.offset_paid_cents = offset_paid_cents
    return row


def _make_trend_row(
    month: str,
    rides: int = 0,
    co2_grams: int = 0,
    green_rides: int = 0,
    offset_cents: int = 0,
) -> MagicMock:
    row = MagicMock()
    row.month = month
    row.rides = rides
    row.co2_grams = co2_grams
    row.green_rides = green_rides
    row.offset_cents = offset_cents
    return row


def _make_employee_row(
    user_id: int,
    rides: int = 0,
    co2_grams: int = 0,
    green_rides: int = 0,
    offset_cents: int = 0,
) -> MagicMock:
    row = MagicMock()
    row.user_id = user_id
    row.rides = rides
    row.co2_grams = co2_grams
    row.green_rides = green_rides
    row.offset_cents = offset_cents
    return row


def _make_esg_row(
    month: str,
    total_rides: int = 0,
    co2_grams: int = 0,
    green_rides: int = 0,
    offset_cents: int = 0,
    active_accounts: int = 1,
) -> MagicMock:
    row = MagicMock()
    row.month = month
    row.total_rides = total_rides
    row.co2_grams = co2_grams
    row.green_rides = green_rides
    row.offset_cents = offset_cents
    row.active_accounts = active_accounts
    return row


def _mock_user(user_id: int = USER_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


# ---------------------------------------------------------------------------
# 1. get_or_create_carbon_budget — creates default when absent
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_or_create_carbon_budget_creates_default():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)  # not found

    added = []
    db.add = lambda x: added.append(x)

    async def _fake_refresh(obj):
        obj.id = 1
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _fake_refresh

    result = await get_or_create_carbon_budget(db, ACCOUNT_ID)

    assert len(added) == 1
    new_budget = added[0]
    assert new_budget.account_id == ACCOUNT_ID
    assert new_budget.tracking_enabled is True
    assert new_budget.alert_threshold_pct == 80
    assert new_budget.monthly_budget_co2_kg is None
    assert result.id == 1


# ---------------------------------------------------------------------------
# 2. get_or_create_carbon_budget — returns existing budget
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_or_create_carbon_budget_returns_existing():
    db = AsyncMock()
    existing = _make_budget(monthly_budget_co2_kg=500.0, alert_threshold_pct=75)
    db.execute.return_value = _scalar_result(existing)

    result = await get_or_create_carbon_budget(db, ACCOUNT_ID)

    # No new row added
    db.add.assert_not_called()
    assert result.monthly_budget_co2_kg == Decimal("500.0")
    assert result.alert_threshold_pct == 75


# ---------------------------------------------------------------------------
# 3. update_carbon_budget — creates new when none exists
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_carbon_budget_creates_new():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)  # not found

    added = []
    db.add = lambda x: added.append(x)

    async def _fake_refresh(obj):
        obj.id = 1
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _fake_refresh

    data = CarbonBudgetUpsert(monthly_budget_co2_kg=Decimal("1000.0"), alert_threshold_pct=90)
    result = await update_carbon_budget(db, ACCOUNT_ID, data, ADMIN_ID)

    assert len(added) == 1
    created = added[0]
    assert created.monthly_budget_co2_kg == Decimal("1000.0")
    assert created.alert_threshold_pct == 90
    assert created.updated_by_id == ADMIN_ID


# ---------------------------------------------------------------------------
# 4. update_carbon_budget — updates existing budget
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_carbon_budget_updates_existing():
    db = AsyncMock()
    existing = _make_budget(monthly_budget_co2_kg=500.0, alert_threshold_pct=80)
    db.execute.return_value = _scalar_result(existing)
    db.refresh = AsyncMock()

    data = CarbonBudgetUpsert(monthly_budget_co2_kg=Decimal("750.0"), notes="Updated cap")
    await update_carbon_budget(db, ACCOUNT_ID, data, ADMIN_ID)

    assert existing.monthly_budget_co2_kg == Decimal("750.0")
    assert existing.notes == "Updated cap"
    assert existing.updated_by_id == ADMIN_ID


# ---------------------------------------------------------------------------
# 5. update_carbon_budget — only supplied fields written
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_carbon_budget_partial_fields_only():
    db = AsyncMock()
    existing = _make_budget(monthly_budget_co2_kg=500.0, alert_threshold_pct=80, notes="original")
    db.execute.return_value = _scalar_result(existing)
    db.refresh = AsyncMock()

    # Only update notes; do NOT supply monthly_budget_co2_kg or alert_threshold_pct
    data = CarbonBudgetUpsert(notes="changed")
    await update_carbon_budget(db, ACCOUNT_ID, data, ADMIN_ID)

    # Fields not in payload remain unchanged
    assert existing.monthly_budget_co2_kg == 500.0  # unchanged
    assert existing.alert_threshold_pct == 80        # unchanged
    assert existing.notes == "changed"


# ---------------------------------------------------------------------------
# 6. get_account_carbon_summary — 403 when not a member
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_carbon_summary_not_member():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)  # member check fails

    with pytest.raises(HTTPException) as exc:
        await get_account_carbon_summary(db, ACCOUNT_ID, requesting_user_id=99)
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 7. get_account_carbon_summary — 403 when tracking disabled and non-admin
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_carbon_summary_tracking_disabled_non_admin():
    db = AsyncMock()
    member = _make_member(role=MemberRole.MEMBER)  # not admin
    budget = _make_budget(tracking_enabled=False)

    db.execute.side_effect = [
        _scalar_result(member),   # _require_account_member
        _scalar_result(budget),   # get_or_create_carbon_budget
    ]

    with pytest.raises(HTTPException) as exc:
        await get_account_carbon_summary(db, ACCOUNT_ID, requesting_user_id=USER_ID)
    assert exc.value.status_code == 403
    assert "Carbon tracking is not enabled" in exc.value.detail


# ---------------------------------------------------------------------------
# 8. get_account_carbon_summary — success: no budget ceiling
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_carbon_summary_success_no_budget():
    db = AsyncMock()
    member = _make_member()
    budget = _make_budget(monthly_budget_co2_kg=None, tracking_enabled=True)
    # 12,000 grams = 12 kg CO2, 2 green rides
    carbon_row = _make_carbon_row(
        total_rides=5, total_co2_grams=12000,
        green_rides=2, offset_paid_rides=1, offset_paid_cents=120
    )

    db.execute.side_effect = [
        _scalar_result(member),     # _require_account_member
        _scalar_result(budget),     # get_or_create (inner execute)
        _one_result(
            total_rides=5, total_co2_grams=12000,
            green_rides=2, offset_paid_rides=1, offset_paid_cents=120,
        ),                          # main carbon join query
    ]

    result = await get_account_carbon_summary(db, ACCOUNT_ID, requesting_user_id=USER_ID)

    assert result.account_id == ACCOUNT_ID
    assert result.total_rides == 5
    assert result.total_co2_kg == Decimal("12.000")
    assert result.green_rides == 2
    assert result.green_ride_pct == Decimal("40.00")
    assert result.offset_paid_rides == 1
    assert result.total_offset_paid_usd == Decimal("1.20")
    assert result.monthly_budget_co2_kg is None
    assert result.budget_used_pct is None
    assert result.alert_triggered is False
    assert result.tracking_enabled is True


# ---------------------------------------------------------------------------
# 9. get_account_carbon_summary — budget utilisation computed
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_carbon_summary_budget_utilisation():
    db = AsyncMock()
    member = _make_member()
    # Budget = 100 kg, used = 75 kg → 75%
    budget = _make_budget(monthly_budget_co2_kg=100.0, alert_threshold_pct=80)

    db.execute.side_effect = [
        _scalar_result(member),
        _scalar_result(budget),
        _one_result(
            total_rides=10, total_co2_grams=75000,  # 75 kg
            green_rides=0, offset_paid_rides=0, offset_paid_cents=0,
        ),
    ]

    result = await get_account_carbon_summary(db, ACCOUNT_ID, requesting_user_id=USER_ID)

    assert result.monthly_budget_co2_kg == Decimal("100.0")
    assert result.budget_used_pct == Decimal("75.00")
    assert result.alert_triggered is False  # 75 < 80


# ---------------------------------------------------------------------------
# 10. get_account_carbon_summary — alert triggered at/above threshold
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_carbon_summary_alert_triggered():
    db = AsyncMock()
    member = _make_member()
    # Budget = 100 kg, used = 90 kg → 90% ≥ 80 → alert
    budget = _make_budget(monthly_budget_co2_kg=100.0, alert_threshold_pct=80)

    db.execute.side_effect = [
        _scalar_result(member),
        _scalar_result(budget),
        _one_result(
            total_rides=15, total_co2_grams=90000,  # 90 kg
            green_rides=0, offset_paid_rides=0, offset_paid_cents=0,
        ),
    ]

    result = await get_account_carbon_summary(db, ACCOUNT_ID, requesting_user_id=USER_ID)

    assert result.budget_used_pct == Decimal("90.00")
    assert result.alert_triggered is True


# ---------------------------------------------------------------------------
# 11. get_account_carbon_summary — alert not triggered below threshold
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_carbon_summary_alert_not_triggered():
    db = AsyncMock()
    member = _make_member()
    budget = _make_budget(monthly_budget_co2_kg=100.0, alert_threshold_pct=80)

    db.execute.side_effect = [
        _scalar_result(member),
        _scalar_result(budget),
        _one_result(
            total_rides=5, total_co2_grams=30000,   # 30 kg → 30%
            green_rides=5, offset_paid_rides=0, offset_paid_cents=0,
        ),
    ]

    result = await get_account_carbon_summary(db, ACCOUNT_ID, requesting_user_id=USER_ID)

    assert result.alert_triggered is False


# ---------------------------------------------------------------------------
# 12. get_carbon_trend — 400 when months = 0
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_carbon_trend_months_too_low():
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await get_carbon_trend(db, ACCOUNT_ID, requesting_user_id=USER_ID, months=0)
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# 13. get_carbon_trend — 400 when months = 25
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_carbon_trend_months_too_high():
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await get_carbon_trend(db, ACCOUNT_ID, requesting_user_id=USER_ID, months=25)
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# 14. get_carbon_trend — 403 when tracking disabled and non-admin
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_carbon_trend_tracking_disabled_non_admin():
    db = AsyncMock()
    member = _make_member(role=MemberRole.MEMBER)
    budget = _make_budget(tracking_enabled=False)

    db.execute.side_effect = [
        _scalar_result(member),
        _scalar_result(budget),
    ]

    with pytest.raises(HTTPException) as exc:
        await get_carbon_trend(db, ACCOUNT_ID, requesting_user_id=USER_ID, months=6)
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 15. get_carbon_trend — success with ride data
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_carbon_trend_success():
    db = AsyncMock()
    member = _make_member()
    budget = _make_budget(tracking_enabled=True)

    trend_rows = [
        _make_trend_row("2026-04", rides=10, co2_grams=20000, green_rides=3, offset_cents=500),
        _make_trend_row("2026-03", rides=8, co2_grams=15000, green_rides=1, offset_cents=200),
    ]

    db.execute.side_effect = [
        _scalar_result(member),
        _scalar_result(budget),
        _all_result(trend_rows),
    ]

    result = await get_carbon_trend(db, ACCOUNT_ID, requesting_user_id=USER_ID, months=6)

    assert result.account_id == ACCOUNT_ID
    assert result.months_requested == 6
    assert len(result.data) == 2
    # Most recent month first
    assert result.data[0].month == "2026-04"
    assert result.data[0].rides == 10
    assert result.data[0].co2_kg == Decimal("20.000")
    assert result.data[0].green_rides == 3
    assert result.data[0].offset_paid_usd == Decimal("5.00")
    assert result.data[1].month == "2026-03"


# ---------------------------------------------------------------------------
# 16. get_carbon_trend — success with no data
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_carbon_trend_empty():
    db = AsyncMock()
    member = _make_member()
    budget = _make_budget(tracking_enabled=True)

    db.execute.side_effect = [
        _scalar_result(member),
        _scalar_result(budget),
        _all_result([]),
    ]

    result = await get_carbon_trend(db, ACCOUNT_ID, requesting_user_id=USER_ID, months=3)

    assert result.data == []
    assert result.months_requested == 3


# ---------------------------------------------------------------------------
# 17. get_employee_carbon_breakdown — 400 when period_end before period_start
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_employee_breakdown_bad_period():
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await get_employee_carbon_breakdown(
            db, ACCOUNT_ID, requesting_user_id=ADMIN_ID,
            period_start=PERIOD_END, period_end=PERIOD_START,  # reversed
        )
    assert exc.value.status_code == 400
    assert "period_end" in exc.value.detail


# ---------------------------------------------------------------------------
# 18. get_employee_carbon_breakdown — 403 when non-admin
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_employee_breakdown_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)  # admin check fails

    with pytest.raises(HTTPException) as exc:
        await get_employee_carbon_breakdown(
            db, ACCOUNT_ID, requesting_user_id=USER_ID,
            period_start=PERIOD_START, period_end=PERIOD_END,
        )
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 19. get_employee_carbon_breakdown — success with ride data
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_employee_breakdown_success():
    db = AsyncMock()
    admin = _make_admin_member()

    employee_rows = [
        _make_employee_row(101, rides=8, co2_grams=10000, green_rides=2, offset_cents=100),
        _make_employee_row(102, rides=5, co2_grams=6000, green_rides=5, offset_cents=60),
    ]

    db.execute.side_effect = [
        _scalar_result(admin),
        _all_result(employee_rows),
    ]

    result = await get_employee_carbon_breakdown(
        db, ACCOUNT_ID, requesting_user_id=ADMIN_ID,
        period_start=PERIOD_START, period_end=PERIOD_END,
    )

    assert result.account_id == ACCOUNT_ID
    assert result.period_start == PERIOD_START
    assert result.period_end == PERIOD_END
    assert len(result.employees) == 2
    # Ordered by co2_kg desc
    assert result.employees[0].user_id == 101
    assert result.employees[0].co2_kg == Decimal("10.000")
    assert result.employees[0].green_rides == 2
    assert result.employees[1].user_id == 102
    assert result.employees[1].co2_kg == Decimal("6.000")
    # All greens for employee 102
    assert result.employees[1].green_rides == 5
    # Totals
    assert result.account_total_rides == 13
    assert result.account_total_co2_kg == Decimal("16.000")


# ---------------------------------------------------------------------------
# 20. get_employee_carbon_breakdown — empty result
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_employee_breakdown_empty():
    db = AsyncMock()
    admin = _make_admin_member()

    db.execute.side_effect = [
        _scalar_result(admin),
        _all_result([]),
    ]

    result = await get_employee_carbon_breakdown(
        db, ACCOUNT_ID, requesting_user_id=ADMIN_ID,
        period_start=PERIOD_START, period_end=PERIOD_END,
    )

    assert result.employees == []
    assert result.account_total_rides == 0
    assert result.account_total_co2_kg == Decimal("0")


# ---------------------------------------------------------------------------
# 21. get_platform_esg_report — 400 when months out of range
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_esg_report_months_out_of_range():
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await get_platform_esg_report(db, months=0)
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        await get_platform_esg_report(db, months=25)
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# 22. get_platform_esg_report — success with data
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_esg_report_success():
    db = AsyncMock()
    esg_rows = [
        _make_esg_row("2026-04", total_rides=50, co2_grams=60000, green_rides=10, offset_cents=600, active_accounts=3),
        _make_esg_row("2026-03", total_rides=40, co2_grams=48000, green_rides=8, offset_cents=480, active_accounts=2),
    ]

    db.execute.return_value = _all_result(esg_rows)

    result = await get_platform_esg_report(db, months=12)

    assert result.months_requested == 12
    assert result.cumulative_rides == 90
    assert result.cumulative_co2_kg == Decimal("108.000")
    assert result.cumulative_green_rides == 18
    assert result.cumulative_offset_paid_usd == Decimal("10.80")
    assert result.overall_green_pct == Decimal("20.00")  # 18/90 = 20%
    assert len(result.monthly_trend) == 2
    assert result.monthly_trend[0].month == "2026-04"
    assert result.monthly_trend[0].active_corporate_accounts == 3
    assert result.monthly_trend[0].green_ride_pct == Decimal("20.00")  # 10/50


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_carbon_budget_upsert_all_optional():
    """23. CarbonBudgetUpsert — valid with all fields omitted."""
    u = CarbonBudgetUpsert()
    assert u.monthly_budget_co2_kg is None
    assert u.offset_budget_usd is None
    assert u.tracking_enabled is None
    assert u.alert_threshold_pct is None
    assert u.notes is None


def test_carbon_budget_upsert_budget_zero_invalid():
    """24. monthly_budget_co2_kg must be > 0."""
    with pytest.raises(ValidationError):
        CarbonBudgetUpsert(monthly_budget_co2_kg=Decimal("0"))

    with pytest.raises(ValidationError):
        CarbonBudgetUpsert(monthly_budget_co2_kg=Decimal("-10"))


def test_carbon_budget_upsert_offset_negative_invalid():
    """25. offset_budget_usd must be >= 0."""
    with pytest.raises(ValidationError):
        CarbonBudgetUpsert(offset_budget_usd=Decimal("-1"))


def test_carbon_budget_upsert_threshold_out_of_range():
    """26. alert_threshold_pct must be 1–100."""
    with pytest.raises(ValidationError):
        CarbonBudgetUpsert(alert_threshold_pct=0)

    with pytest.raises(ValidationError):
        CarbonBudgetUpsert(alert_threshold_pct=101)

    # Valid boundary values
    u_low = CarbonBudgetUpsert(alert_threshold_pct=1)
    u_high = CarbonBudgetUpsert(alert_threshold_pct=100)
    assert u_low.alert_threshold_pct == 1
    assert u_high.alert_threshold_pct == 100


def test_carbon_budget_response_from_attributes():
    """27. CarbonBudgetResponse — model_config from_attributes."""
    resp = _make_budget_response(monthly_budget_co2_kg=200.0, alert_threshold_pct=75)
    assert resp.account_id == ACCOUNT_ID
    assert resp.monthly_budget_co2_kg == Decimal("200.0")
    assert resp.tracking_enabled is True
    assert resp.alert_threshold_pct == 75
    assert isinstance(resp.created_at, datetime)


def test_carbon_summary_response_valid():
    """28. CarbonSummaryResponse — valid with budget."""
    r = CarbonSummaryResponse(
        account_id=ACCOUNT_ID,
        month="2026-04",
        total_rides=10,
        total_co2_kg=Decimal("20.000"),
        green_rides=4,
        green_ride_pct=Decimal("40.00"),
        offset_paid_rides=2,
        total_offset_paid_usd=Decimal("2.00"),
        monthly_budget_co2_kg=Decimal("100.0"),
        budget_used_pct=Decimal("20.00"),
        alert_triggered=False,
        tracking_enabled=True,
    )
    assert r.total_co2_kg == Decimal("20.000")
    assert r.budget_used_pct == Decimal("20.00")
    assert r.alert_triggered is False


def test_carbon_trend_response_valid():
    """29. CarbonTrendResponse — valid with data points."""
    r = CarbonTrendResponse(
        account_id=ACCOUNT_ID,
        months_requested=6,
        data=[
            CarbonTrendPoint(
                month="2026-04",
                rides=5,
                co2_kg=Decimal("10.000"),
                green_rides=2,
                offset_paid_usd=Decimal("1.00"),
            ),
        ],
    )
    assert r.months_requested == 6
    assert len(r.data) == 1
    assert r.data[0].co2_kg == Decimal("10.000")


def test_employee_carbon_breakdown_response_valid():
    """30. EmployeeCarbonBreakdownResponse — valid with employees list."""
    r = EmployeeCarbonBreakdownResponse(
        account_id=ACCOUNT_ID,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        account_total_co2_kg=Decimal("16.000"),
        account_total_rides=13,
        employees=[
            EmployeeCarbonItem(
                user_id=101,
                rides=8,
                co2_kg=Decimal("10.000"),
                green_rides=2,
                offset_paid_usd=Decimal("1.00"),
            ),
        ],
    )
    assert len(r.employees) == 1
    assert r.account_total_co2_kg == Decimal("16.000")


def test_esg_report_response_valid():
    """31. ESGReportResponse — valid with monthly trend."""
    r = ESGReportResponse(
        months_requested=12,
        cumulative_co2_kg=Decimal("108.000"),
        cumulative_green_rides=18,
        cumulative_rides=90,
        cumulative_offset_paid_usd=Decimal("10.80"),
        overall_green_pct=Decimal("20.00"),
        monthly_trend=[
            ESGMonthPoint(
                month="2026-04",
                total_rides=50,
                total_co2_kg=Decimal("60.000"),
                green_rides=10,
                green_ride_pct=Decimal("20.00"),
                total_offset_paid_usd=Decimal("6.00"),
                active_corporate_accounts=3,
            ),
        ],
    )
    assert r.cumulative_rides == 90
    assert len(r.monthly_trend) == 1


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_get_my_carbon_budget_200():
    """32. GET /corporate/accounts/me/carbon-budget — 200."""
    from app.api.v1.corporate_carbon_budget import get_my_carbon_budget

    user = _mock_user()
    db = AsyncMock()
    mock_resp = _make_budget_response()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}.get_or_create_carbon_budget", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await get_my_carbon_budget(user=user, db=db)

    assert result.account_id == ACCOUNT_ID
    assert result.tracking_enabled is True


@pytest.mark.asyncio
async def test_api_get_my_carbon_budget_no_account():
    """33. GET /corporate/accounts/me/carbon-budget — 404 when no account."""
    from app.api.v1.corporate_carbon_budget import get_my_carbon_budget

    user = _mock_user()
    db = AsyncMock()

    with patch(
        f"{_ROUTER}._resolve_account_id",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="No account")),
    ):
        with pytest.raises(HTTPException) as exc:
            await get_my_carbon_budget(user=user, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_set_my_carbon_budget_200():
    """34. PUT /corporate/accounts/me/carbon-budget — 200."""
    from app.api.v1.corporate_carbon_budget import set_my_carbon_budget

    user = _mock_user()
    db = AsyncMock()
    payload = CarbonBudgetUpsert(monthly_budget_co2_kg=Decimal("500.0"), alert_threshold_pct=85)
    mock_resp = _make_budget_response(monthly_budget_co2_kg=500.0, alert_threshold_pct=85)

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}.update_carbon_budget", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await set_my_carbon_budget(payload=payload, user=user, db=db)

    assert result.monthly_budget_co2_kg == Decimal("500.0")
    assert result.alert_threshold_pct == 85


@pytest.mark.asyncio
async def test_api_get_my_carbon_summary_200():
    """35. GET /corporate/accounts/me/carbon-summary — 200."""
    from app.api.v1.corporate_carbon_budget import get_my_carbon_summary

    user = _mock_user()
    db = AsyncMock()
    mock_resp = CarbonSummaryResponse(
        account_id=ACCOUNT_ID,
        month="2026-04",
        total_rides=5,
        total_co2_kg=Decimal("10.000"),
        green_rides=2,
        green_ride_pct=Decimal("40.00"),
        offset_paid_rides=0,
        total_offset_paid_usd=Decimal("0.00"),
        monthly_budget_co2_kg=None,
        budget_used_pct=None,
        alert_triggered=False,
        tracking_enabled=True,
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}.get_account_carbon_summary", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await get_my_carbon_summary(user=user, db=db)

    assert result.account_id == ACCOUNT_ID
    assert result.total_rides == 5
    assert result.green_ride_pct == Decimal("40.00")


@pytest.mark.asyncio
async def test_api_get_my_carbon_trend_200():
    """36. GET /corporate/accounts/me/carbon-trend — 200."""
    from app.api.v1.corporate_carbon_budget import get_my_carbon_trend

    user = _mock_user()
    db = AsyncMock()
    mock_resp = CarbonTrendResponse(
        account_id=ACCOUNT_ID, months_requested=6, data=[]
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}.get_carbon_trend", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await get_my_carbon_trend(months=6, user=user, db=db)

    assert result.months_requested == 6
    assert result.data == []


@pytest.mark.asyncio
async def test_api_get_my_employee_carbon_200():
    """37. GET /corporate/accounts/me/carbon/employees — 200."""
    from app.api.v1.corporate_carbon_budget import get_my_employee_carbon

    user = _mock_user()
    db = AsyncMock()
    mock_resp = EmployeeCarbonBreakdownResponse(
        account_id=ACCOUNT_ID,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        account_total_co2_kg=Decimal("0"),
        account_total_rides=0,
        employees=[],
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}.get_employee_carbon_breakdown", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await get_my_employee_carbon(
            period_start=PERIOD_START, period_end=PERIOD_END, user=user, db=db
        )

    assert result.account_id == ACCOUNT_ID
    assert result.employees == []


@pytest.mark.asyncio
async def test_api_admin_get_carbon_budget_200():
    """38. GET /admin/corporate/accounts/{id}/carbon-budget — 200."""
    from app.api.v1.corporate_carbon_budget import admin_get_carbon_budget

    admin_user = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    mock_resp = _make_budget_response(account_id=ACCOUNT_ID)

    with patch(f"{_ROUTER}.get_or_create_carbon_budget", new=AsyncMock(return_value=mock_resp)):
        result = await admin_get_carbon_budget(
            account_id=ACCOUNT_ID, _admin=admin_user, db=db
        )

    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_api_admin_get_esg_report_200():
    """39. GET /admin/corporate/carbon/esg-report — 200."""
    from app.api.v1.corporate_carbon_budget import admin_get_esg_report

    admin_user = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    mock_resp = ESGReportResponse(
        months_requested=12,
        cumulative_co2_kg=Decimal("0"),
        cumulative_green_rides=0,
        cumulative_rides=0,
        cumulative_offset_paid_usd=Decimal("0"),
        overall_green_pct=Decimal("0"),
        monthly_trend=[],
    )

    with patch(f"{_ROUTER}.get_platform_esg_report", new=AsyncMock(return_value=mock_resp)):
        result = await admin_get_esg_report(months=12, _admin=admin_user, db=db)

    assert result.months_requested == 12
    assert result.monthly_trend == []
