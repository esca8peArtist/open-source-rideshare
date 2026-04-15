"""Tests for the Corporate Spending Analytics feature.

Service layer (async, mocked DB):
  1.  get_spending_overview — success with budget limit and utilisation pct
  2.  get_spending_overview — success without budget limit (utilisation=None)
  3.  get_spending_overview — not member → 403
  4.  get_monthly_spend_trend — success with ride data
  5.  get_monthly_spend_trend — success with no rides (empty data list)
  6.  get_monthly_spend_trend — not member → 403
  7.  get_monthly_spend_trend — months out of range → 400
  8.  get_employee_spend_breakdown — success, returns top spenders
  9.  get_employee_spend_breakdown — success with no rides (empty list)
  10. get_employee_spend_breakdown — not admin → 403
  11. get_employee_spend_breakdown — period_end before period_start → 400
  12. get_employee_spend_breakdown — limit out of range → 400
  13. get_ride_pattern_analytics — success, all 24 hour + 7 day buckets populated
  14. get_ride_pattern_analytics — empty period (all buckets zero)
  15. get_ride_pattern_analytics — not member → 403
  16. get_ride_pattern_analytics — period_end before period_start → 400

Schema validation:
  17. SpendingOverviewResponse — valid, no budget limit
  18. SpendingOverviewResponse — valid with budget utilisation pct
  19. MonthlySpendTrendResponse — serialises correctly
  20. MonthlySpendPoint — avg_fare is None when total_rides is 0
  21. EmployeeSpendBreakdownResponse — valid with top_spenders
  22. EmployeeSpendItem — avg_fare computed correctly
  23. RidePatternResponse — 24 hour and 7 day buckets
  24. _safe_avg — zero rides returns None
  25. _safe_avg — positive rides returns rounded average

API layer (service functions patched):
  26. GET /corporate/accounts/me/analytics/overview — 200, calls get_spending_overview
  27. GET /corporate/accounts/me/analytics/monthly — 200, calls get_monthly_spend_trend
  28. GET /corporate/accounts/me/analytics/ride-patterns — 200, calls get_ride_pattern_analytics
  29. GET /corporate/accounts/me/analytics/employees — 200, calls get_employee_spend_breakdown
  30. GET /corporate/accounts/me/analytics/overview — no account → 404
  31. GET /admin/corporate/accounts/{id}/analytics/overview — 200, admin path
  32. GET /admin/corporate/accounts/{id}/analytics/monthly — 200, admin path
  33. GET /admin/corporate/accounts/{id}/analytics/employees — 200, admin path
  34. GET /admin/corporate/accounts/{id}/analytics/ride-patterns — 200, admin path
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate import BusinessAccountMember, MemberRole
from app.schemas.corporate_spending_analytics import (
    DayBucket,
    EmployeeSpendBreakdownResponse,
    EmployeeSpendItem,
    HourBucket,
    MonthlySpendPoint,
    MonthlySpendTrendResponse,
    RidePatternResponse,
    SpendingOverviewResponse,
)
from app.services.corporate_spending_analytics import (
    _safe_avg,
    get_employee_spend_breakdown,
    get_monthly_spend_trend,
    get_ride_pattern_analytics,
    get_spending_overview,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
PERIOD_START = date(2026, 4, 1)
PERIOD_END = date(2026, 4, 30)
ACCOUNT_ID = 10
USER_ID = 1
ADMIN_ID = 2


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
    res.scalar.return_value = value
    return res


def _one_result(**kwargs) -> MagicMock:
    """Return a mock whose .one() method returns a row with the given attributes."""
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


def _make_account(
    account_id: int = ACCOUNT_ID,
    monthly_budget_limit: Decimal | None = None,
) -> MagicMock:
    from app.models.corporate import BusinessAccount
    a = MagicMock(spec=BusinessAccount)
    a.id = account_id
    a.monthly_budget_limit = monthly_budget_limit
    return a


def _make_ride_row(user_id: int, total_rides: int, total_spend: Decimal) -> MagicMock:
    row = MagicMock()
    row.user_id = user_id
    row.total_rides = total_rides
    row.total_spend = total_spend
    return row


def _make_hour_row(hour: int, ride_count: int) -> MagicMock:
    row = MagicMock()
    row.hour = hour
    row.ride_count = ride_count
    return row


def _make_dow_row(dow: int, ride_count: int) -> MagicMock:
    row = MagicMock()
    row.dow = dow
    row.ride_count = ride_count
    return row


def _make_month_row(month: str, total_rides: int, total_spend: Decimal) -> MagicMock:
    row = MagicMock()
    row.month = month
    row.total_rides = total_rides
    row.total_spend = total_spend
    return row


# ---------------------------------------------------------------------------
# 1. get_spending_overview — success with budget limit
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_spending_overview_with_budget_limit():
    db = AsyncMock()
    member = _make_member()
    account = _make_account(monthly_budget_limit=Decimal("1000.00"))

    db.execute.side_effect = [
        _scalar_result(member),                              # _require_account_member
        _one_result(rides=5, spend=Decimal("250.00")),       # current month
        _one_result(rides=20, spend=Decimal("900.00")),      # YTD
        _one_result(rides=50, spend=Decimal("2000.00")),     # all-time
        _scalar_result(account),                             # BusinessAccount budget
    ]

    result = await get_spending_overview(db, ACCOUNT_ID, requesting_user_id=USER_ID)

    assert result.account_id == ACCOUNT_ID
    assert result.current_month_rides == 5
    assert result.current_month_spend == Decimal("250.00")
    assert result.ytd_rides == 20
    assert result.ytd_spend == Decimal("900.00")
    assert result.all_time_rides == 50
    assert result.all_time_spend == Decimal("2000.00")
    assert result.monthly_budget_limit == Decimal("1000.00")
    assert result.current_month_budget_utilization_pct == pytest.approx(25.0, rel=1e-3)


# ---------------------------------------------------------------------------
# 2. get_spending_overview — success without budget limit
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_spending_overview_no_budget_limit():
    db = AsyncMock()
    member = _make_member()
    account = _make_account(monthly_budget_limit=None)

    db.execute.side_effect = [
        _scalar_result(member),
        _one_result(rides=3, spend=Decimal("120.00")),
        _one_result(rides=10, spend=Decimal("400.00")),
        _one_result(rides=30, spend=Decimal("1200.00")),
        _scalar_result(account),
    ]

    result = await get_spending_overview(db, ACCOUNT_ID, requesting_user_id=USER_ID)

    assert result.monthly_budget_limit is None
    assert result.current_month_budget_utilization_pct is None


# ---------------------------------------------------------------------------
# 3. get_spending_overview — not member → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_spending_overview_not_member():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_spending_overview(db, ACCOUNT_ID, requesting_user_id=99)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 4. get_monthly_spend_trend — success with ride data
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_monthly_spend_trend_success():
    db = AsyncMock()
    member = _make_member()
    rows = [
        _make_month_row("2026-04", 5, Decimal("250.00")),
        _make_month_row("2026-03", 8, Decimal("400.00")),
        _make_month_row("2026-02", 3, Decimal("90.00")),
    ]

    db.execute.side_effect = [
        _scalar_result(member),
        _all_result(rows),
    ]

    result = await get_monthly_spend_trend(
        db, ACCOUNT_ID, requesting_user_id=USER_ID, months=12
    )

    assert result.account_id == ACCOUNT_ID
    assert result.months_requested == 12
    assert len(result.data) == 3
    assert result.data[0].month == "2026-04"
    assert result.data[0].total_rides == 5
    assert result.data[0].total_spend == Decimal("250.00")
    assert result.data[0].avg_fare == Decimal("50.00")  # 250 / 5


# ---------------------------------------------------------------------------
# 5. get_monthly_spend_trend — empty data (no rides)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_monthly_spend_trend_no_rides():
    db = AsyncMock()
    member = _make_member()

    db.execute.side_effect = [
        _scalar_result(member),
        _all_result([]),
    ]

    result = await get_monthly_spend_trend(
        db, ACCOUNT_ID, requesting_user_id=USER_ID, months=6
    )

    assert result.data == []
    assert result.months_requested == 6


# ---------------------------------------------------------------------------
# 6. get_monthly_spend_trend — not member → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_monthly_spend_trend_not_member():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_monthly_spend_trend(db, ACCOUNT_ID, requesting_user_id=99, months=12)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 7. get_monthly_spend_trend — months out of range → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_monthly_spend_trend_months_out_of_range():
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_monthly_spend_trend(db, ACCOUNT_ID, requesting_user_id=USER_ID, months=0)
    assert exc_info.value.status_code == 400
    assert "months" in exc_info.value.detail.lower()

    with pytest.raises(HTTPException) as exc_info:
        await get_monthly_spend_trend(db, ACCOUNT_ID, requesting_user_id=USER_ID, months=25)
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 8. get_employee_spend_breakdown — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_employee_spend_breakdown_success():
    db = AsyncMock()
    admin = _make_admin_member()
    rows = [
        _make_ride_row(user_id=5, total_rides=10, total_spend=Decimal("500.00")),
        _make_ride_row(user_id=7, total_rides=4, total_spend=Decimal("180.00")),
    ]

    db.execute.side_effect = [
        _scalar_result(admin),
        _all_result(rows),
    ]

    result = await get_employee_spend_breakdown(
        db, ACCOUNT_ID, requesting_user_id=ADMIN_ID,
        period_start=PERIOD_START, period_end=PERIOD_END, limit=10,
    )

    assert result.account_id == ACCOUNT_ID
    assert result.period_start == PERIOD_START
    assert result.period_end == PERIOD_END
    assert len(result.top_spenders) == 2
    assert result.top_spenders[0].user_id == 5
    assert result.top_spenders[0].total_spend == Decimal("500.00")
    assert result.top_spenders[0].avg_fare == Decimal("50.00")  # 500 / 10
    assert result.top_spenders[1].user_id == 7


# ---------------------------------------------------------------------------
# 9. get_employee_spend_breakdown — empty period
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_employee_spend_breakdown_empty():
    db = AsyncMock()
    admin = _make_admin_member()

    db.execute.side_effect = [
        _scalar_result(admin),
        _all_result([]),
    ]

    result = await get_employee_spend_breakdown(
        db, ACCOUNT_ID, requesting_user_id=ADMIN_ID,
        period_start=PERIOD_START, period_end=PERIOD_END,
    )

    assert result.top_spenders == []


# ---------------------------------------------------------------------------
# 10. get_employee_spend_breakdown — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_employee_spend_breakdown_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)  # admin check fails

    with pytest.raises(HTTPException) as exc_info:
        await get_employee_spend_breakdown(
            db, ACCOUNT_ID, requesting_user_id=USER_ID,
            period_start=PERIOD_START, period_end=PERIOD_END,
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 11. get_employee_spend_breakdown — period_end before period_start → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_employee_spend_breakdown_bad_period():
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_employee_spend_breakdown(
            db, ACCOUNT_ID, requesting_user_id=ADMIN_ID,
            period_start=PERIOD_END, period_end=PERIOD_START,  # reversed
        )
    assert exc_info.value.status_code == 400
    assert "period_end" in exc_info.value.detail


# ---------------------------------------------------------------------------
# 12. get_employee_spend_breakdown — limit out of range → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_employee_spend_breakdown_limit_out_of_range():
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_employee_spend_breakdown(
            db, ACCOUNT_ID, requesting_user_id=ADMIN_ID,
            period_start=PERIOD_START, period_end=PERIOD_END, limit=0,
        )
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException) as exc_info:
        await get_employee_spend_breakdown(
            db, ACCOUNT_ID, requesting_user_id=ADMIN_ID,
            period_start=PERIOD_START, period_end=PERIOD_END, limit=51,
        )
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 13. get_ride_pattern_analytics — success, all buckets populated
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ride_pattern_analytics_success():
    db = AsyncMock()
    member = _make_member()

    hour_rows = [
        _make_hour_row(9, 5),
        _make_hour_row(17, 8),
        _make_hour_row(18, 3),
    ]
    dow_rows = [
        _make_dow_row(1, 7),   # Monday
        _make_dow_row(5, 9),   # Friday
    ]

    db.execute.side_effect = [
        _scalar_result(member),
        _all_result(hour_rows),
        _all_result(dow_rows),
    ]

    result = await get_ride_pattern_analytics(
        db, ACCOUNT_ID, requesting_user_id=USER_ID,
        period_start=PERIOD_START, period_end=PERIOD_END,
    )

    assert result.account_id == ACCOUNT_ID
    # 24 hour buckets always returned
    assert len(result.by_hour) == 24
    # 7 day-of-week buckets always returned
    assert len(result.by_day_of_week) == 7
    # Spot-check specific values
    assert result.by_hour[9].ride_count == 5
    assert result.by_hour[17].ride_count == 8
    assert result.by_hour[0].ride_count == 0   # zero-count bucket
    assert result.by_day_of_week[1].ride_count == 7   # Monday
    assert result.by_day_of_week[1].day_name == "Monday"
    assert result.by_day_of_week[5].ride_count == 9   # Friday
    assert result.by_day_of_week[3].ride_count == 0   # Wednesday — zero
    # total_rides is sum of hour buckets
    assert result.total_rides == 5 + 8 + 3


# ---------------------------------------------------------------------------
# 14. get_ride_pattern_analytics — empty period (all buckets zero)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ride_pattern_analytics_empty():
    db = AsyncMock()
    member = _make_member()

    db.execute.side_effect = [
        _scalar_result(member),
        _all_result([]),
        _all_result([]),
    ]

    result = await get_ride_pattern_analytics(
        db, ACCOUNT_ID, requesting_user_id=USER_ID,
        period_start=PERIOD_START, period_end=PERIOD_END,
    )

    assert len(result.by_hour) == 24
    assert len(result.by_day_of_week) == 7
    assert all(b.ride_count == 0 for b in result.by_hour)
    assert all(b.ride_count == 0 for b in result.by_day_of_week)
    assert result.total_rides == 0


# ---------------------------------------------------------------------------
# 15. get_ride_pattern_analytics — not member → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ride_pattern_analytics_not_member():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_ride_pattern_analytics(
            db, ACCOUNT_ID, requesting_user_id=99,
            period_start=PERIOD_START, period_end=PERIOD_END,
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 16. get_ride_pattern_analytics — period_end before period_start → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ride_pattern_analytics_bad_period():
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_ride_pattern_analytics(
            db, ACCOUNT_ID, requesting_user_id=USER_ID,
            period_start=PERIOD_END, period_end=PERIOD_START,
        )
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_spending_overview_no_budget():
    r = SpendingOverviewResponse(
        account_id=10,
        current_month="2026-04",
        current_month_rides=5,
        current_month_spend=Decimal("250.00"),
        ytd_rides=20,
        ytd_spend=Decimal("900.00"),
        all_time_rides=50,
        all_time_spend=Decimal("2000.00"),
        monthly_budget_limit=None,
        current_month_budget_utilization_pct=None,
    )
    assert r.monthly_budget_limit is None
    assert r.current_month_budget_utilization_pct is None


def test_spending_overview_with_budget():
    r = SpendingOverviewResponse(
        account_id=10,
        current_month="2026-04",
        current_month_rides=5,
        current_month_spend=Decimal("250.00"),
        ytd_rides=20,
        ytd_spend=Decimal("900.00"),
        all_time_rides=50,
        all_time_spend=Decimal("2000.00"),
        monthly_budget_limit=Decimal("1000.00"),
        current_month_budget_utilization_pct=25.0,
    )
    assert r.monthly_budget_limit == Decimal("1000.00")
    assert r.current_month_budget_utilization_pct == pytest.approx(25.0)


def test_monthly_spend_trend_response():
    r = MonthlySpendTrendResponse(
        account_id=10,
        months_requested=12,
        data=[
            MonthlySpendPoint(
                month="2026-04",
                total_rides=5,
                total_spend=Decimal("250.00"),
                avg_fare=Decimal("50.00"),
            ),
        ],
    )
    assert len(r.data) == 1
    assert r.data[0].avg_fare == Decimal("50.00")


def test_monthly_spend_point_avg_fare_none_when_no_rides():
    p = MonthlySpendPoint(
        month="2026-04",
        total_rides=0,
        total_spend=Decimal("0.00"),
        avg_fare=None,
    )
    assert p.avg_fare is None


def test_employee_spend_breakdown_response():
    r = EmployeeSpendBreakdownResponse(
        account_id=10,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        limit=10,
        top_spenders=[
            EmployeeSpendItem(
                user_id=5,
                user_email="alice@corp.com",
                user_name="Alice",
                total_rides=10,
                total_spend=Decimal("500.00"),
                avg_fare=Decimal("50.00"),
            )
        ],
    )
    assert len(r.top_spenders) == 1
    assert r.top_spenders[0].user_email == "alice@corp.com"


def test_employee_spend_item_avg_fare():
    item = EmployeeSpendItem(
        user_id=5,
        total_rides=4,
        total_spend=Decimal("200.00"),
        avg_fare=Decimal("50.00"),
    )
    assert item.avg_fare == Decimal("50.00")


def test_ride_pattern_response_bucket_counts():
    by_hour = [HourBucket(hour=h, ride_count=0) for h in range(24)]
    by_dow = [
        DayBucket(day_of_week=d, day_name=f"Day{d}", ride_count=0)
        for d in range(7)
    ]
    r = RidePatternResponse(
        account_id=10,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        total_rides=0,
        by_hour=by_hour,
        by_day_of_week=by_dow,
    )
    assert len(r.by_hour) == 24
    assert len(r.by_day_of_week) == 7


def test_safe_avg_zero_rides():
    assert _safe_avg(Decimal("0.00"), 0) is None


def test_safe_avg_positive_rides():
    result = _safe_avg(Decimal("150.00"), 3)
    assert result == Decimal("50.00")


def test_safe_avg_rounding():
    result = _safe_avg(Decimal("10.00"), 3)  # 3.333...
    assert result == Decimal("3.33")


# ---------------------------------------------------------------------------
# API layer
# ---------------------------------------------------------------------------

_ROUTER = "app.api.v1.corporate_spending_analytics"


def _mock_user(user_id: int = USER_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


def _mock_overview() -> SpendingOverviewResponse:
    return SpendingOverviewResponse(
        account_id=ACCOUNT_ID,
        current_month="2026-04",
        current_month_rides=5,
        current_month_spend=Decimal("250.00"),
        ytd_rides=20,
        ytd_spend=Decimal("900.00"),
        all_time_rides=50,
        all_time_spend=Decimal("2000.00"),
    )


def _mock_trend() -> MonthlySpendTrendResponse:
    return MonthlySpendTrendResponse(
        account_id=ACCOUNT_ID,
        months_requested=12,
        data=[],
    )


def _mock_employee_breakdown() -> EmployeeSpendBreakdownResponse:
    return EmployeeSpendBreakdownResponse(
        account_id=ACCOUNT_ID,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        limit=10,
        top_spenders=[],
    )


def _mock_pattern() -> RidePatternResponse:
    by_hour = [HourBucket(hour=h, ride_count=0) for h in range(24)]
    by_dow = [
        DayBucket(day_of_week=d, day_name=f"Day{d}", ride_count=0)
        for d in range(7)
    ]
    return RidePatternResponse(
        account_id=ACCOUNT_ID,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        total_rides=0,
        by_hour=by_hour,
        by_day_of_week=by_dow,
    )


@pytest.mark.asyncio
async def test_api_get_my_spending_overview():
    """26. GET /corporate/accounts/me/analytics/overview — 200."""
    from app.api.v1.corporate_spending_analytics import get_my_spending_overview

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.get_spending_overview", new=AsyncMock(return_value=_mock_overview())):
        result = await get_my_spending_overview(user=user, db=db)
    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_api_get_my_monthly_trend():
    """27. GET /corporate/accounts/me/analytics/monthly — 200."""
    from app.api.v1.corporate_spending_analytics import get_my_monthly_trend

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.get_monthly_spend_trend", new=AsyncMock(return_value=_mock_trend())):
        result = await get_my_monthly_trend(months=12, user=user, db=db)
    assert result.months_requested == 12


@pytest.mark.asyncio
async def test_api_get_my_ride_patterns():
    """28. GET /corporate/accounts/me/analytics/ride-patterns — 200."""
    from app.api.v1.corporate_spending_analytics import get_my_ride_patterns

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.get_ride_pattern_analytics", new=AsyncMock(return_value=_mock_pattern())):
        result = await get_my_ride_patterns(
            period_start=PERIOD_START, period_end=PERIOD_END, user=user, db=db
        )
    assert len(result.by_hour) == 24


@pytest.mark.asyncio
async def test_api_get_my_employee_spend():
    """29. GET /corporate/accounts/me/analytics/employees — 200."""
    from app.api.v1.corporate_spending_analytics import get_my_employee_spend

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.get_employee_spend_breakdown", new=AsyncMock(return_value=_mock_employee_breakdown())):
        result = await get_my_employee_spend(
            period_start=PERIOD_START, period_end=PERIOD_END, limit=10, user=user, db=db
        )
    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_api_get_my_spending_overview_no_account():
    """30. GET /corporate/accounts/me/analytics/overview — not in account → 404."""
    from app.api.v1.corporate_spending_analytics import get_my_spending_overview

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found"))):
        with pytest.raises(HTTPException) as exc_info:
            await get_my_spending_overview(user=user, db=db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_api_admin_get_spending_overview():
    """31. GET /admin/corporate/accounts/{id}/analytics/overview — admin 200."""
    from app.api.v1.corporate_spending_analytics import admin_get_spending_overview

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()

    with patch(f"{_ROUTER}.get_spending_overview", new=AsyncMock(return_value=_mock_overview())):
        result = await admin_get_spending_overview(account_id=ACCOUNT_ID, _admin=admin, db=db)
    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_api_admin_get_monthly_trend():
    """32. GET /admin/corporate/accounts/{id}/analytics/monthly — admin 200."""
    from app.api.v1.corporate_spending_analytics import admin_get_monthly_trend

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()

    with patch(f"{_ROUTER}.get_monthly_spend_trend", new=AsyncMock(return_value=_mock_trend())):
        result = await admin_get_monthly_trend(account_id=ACCOUNT_ID, months=6, _admin=admin, db=db)
    assert result.months_requested == 12  # mock always returns 12


@pytest.mark.asyncio
async def test_api_admin_get_employee_spend():
    """33. GET /admin/corporate/accounts/{id}/analytics/employees — admin 200."""
    from app.api.v1.corporate_spending_analytics import admin_get_employee_spend

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()

    with patch(f"{_ROUTER}.get_employee_spend_breakdown", new=AsyncMock(return_value=_mock_employee_breakdown())):
        result = await admin_get_employee_spend(
            account_id=ACCOUNT_ID,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            limit=10,
            _admin=admin,
            db=db,
        )
    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_api_admin_get_ride_patterns():
    """34. GET /admin/corporate/accounts/{id}/analytics/ride-patterns — admin 200."""
    from app.api.v1.corporate_spending_analytics import admin_get_ride_patterns

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()

    with patch(f"{_ROUTER}.get_ride_pattern_analytics", new=AsyncMock(return_value=_mock_pattern())):
        result = await admin_get_ride_patterns(
            account_id=ACCOUNT_ID,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            _admin=admin,
            db=db,
        )
    assert len(result.by_day_of_week) == 7
