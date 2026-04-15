"""Tests for the Corporate Employee Spend Limits feature.

Service layer (async, mocked DB):
  1.  get_my_spend_summary — success with limit set (utilization computed)
  2.  get_my_spend_summary — success with no limit (utilization=None)
  3.  get_my_spend_summary — not a member → 403
  4.  get_my_spend_history — success with ride data
  5.  get_my_spend_history — success with no rides (empty data list)
  6.  get_my_spend_history — months out of range → 400
  7.  get_my_spend_history — not a member → 403
  8.  get_member_spend_summary — admin success
  9.  get_member_spend_summary — not admin → 403
  10. get_member_spend_summary — target member not found → 404
  11. list_members_spend_summary — success, multiple members
  12. list_members_spend_summary — empty account (no members)
  13. list_members_spend_summary — not admin → 403
  14. set_member_spend_limit — success, limit updated
  15. set_member_spend_limit — zero limit → 400
  16. set_member_spend_limit — negative limit → 400
  17. set_member_spend_limit — not admin → 403
  18. set_member_spend_limit — member not found → 404
  19. remove_member_spend_limit — success, limit set to None
  20. remove_member_spend_limit — not admin → 403
  21. remove_member_spend_limit — member not found → 404

Schema validation:
  22. SetSpendLimitRequest — valid value
  23. SetSpendLimitRequest — zero value → ValidationError
  24. SetSpendLimitRequest — negative value → ValidationError
  25. MySpendSummaryResponse — with limit, utilization computed
  26. MySpendSummaryResponse — no limit, utilization=None
  27. MySpendHistoryResponse — serialises correctly
  28. MySpendHistoryPoint — avg_fare is None when total_rides is 0
  29. MemberSpendLimitsResponse — multiple members
  30. MemberSpendSummaryResponse — with and without limit
  31. SpendLimitResponse — set and remove messages
  32. _utilization_pct — zero spend returns 0.0
  33. _utilization_pct — None limit returns None
  34. _utilization_pct — rounds to 2 decimal places

API layer (service functions patched):
  35. GET  /corporate/accounts/me/my-spending — 200
  36. GET  /corporate/accounts/me/my-spending — no account → 404
  37. GET  /corporate/accounts/me/my-spending/history — 200
  38. GET  /corporate/accounts/me/members/spend-limits — 200
  39. GET  /corporate/accounts/me/members/{uid}/spend-limit — 200
  40. PUT  /corporate/accounts/me/members/{uid}/spend-limit — 200
  41. DELETE /corporate/accounts/me/members/{uid}/spend-limit — 200
  42. GET  /admin/corporate/accounts/{id}/members/spend-limits — 200
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate import BusinessAccountMember, MemberRole
from app.schemas.corporate_employee_expense import (
    MemberSpendItem,
    MemberSpendLimitsResponse,
    MemberSpendSummaryResponse,
    MySpendHistoryPoint,
    MySpendHistoryResponse,
    MySpendSummaryResponse,
    SetSpendLimitRequest,
    SpendLimitResponse,
)
from app.services.corporate_employee_expense import (
    _utilization_pct,
    get_member_spend_summary,
    get_my_spend_history,
    get_my_spend_summary,
    list_members_spend_summary,
    remove_member_spend_limit,
    set_member_spend_limit,
)


# ---------------------------------------------------------------------------
# Shared constants and helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 10
USER_ID = 1
ADMIN_ID = 2
OTHER_USER_ID = 3


def _make_member(
    account_id: int = ACCOUNT_ID,
    user_id: int = USER_ID,
    role: MemberRole = MemberRole.MEMBER,
    is_active: bool = True,
    monthly_spend_limit: Decimal | None = None,
) -> MagicMock:
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = account_id
    m.user_id = user_id
    m.role = role
    m.is_active = is_active
    m.monthly_spend_limit = monthly_spend_limit
    return m


def _make_admin(
    account_id: int = ACCOUNT_ID,
    user_id: int = ADMIN_ID,
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


def _scalars_result(values: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = values
    res = MagicMock()
    res.scalars.return_value = scalars
    return res


def _all_result(rows: list) -> MagicMock:
    res = MagicMock()
    res.all.return_value = rows
    return res


def _make_month_row(month: str, total_rides: int, total_spend: Decimal) -> MagicMock:
    row = MagicMock()
    row.month = month
    row.total_rides = total_rides
    row.total_spend = total_spend
    return row


def _make_spend_row(user_id: int, rides: int, spend: Decimal) -> MagicMock:
    row = MagicMock()
    row.user_id = user_id
    row.rides = rides
    row.spend = spend
    return row


# ---------------------------------------------------------------------------
# 1. get_my_spend_summary — success with limit set
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_my_spend_summary_with_limit():
    db = AsyncMock()
    member = _make_member(monthly_spend_limit=Decimal("500.00"))

    db.execute.side_effect = [
        _scalar_result(member),                                    # _require_active_member
        _one_result(rides=4, spend=Decimal("200.00")),             # current month
        _one_result(rides=15, spend=Decimal("750.00")),            # YTD
    ]

    result = await get_my_spend_summary(db, ACCOUNT_ID, USER_ID)

    assert result.account_id == ACCOUNT_ID
    assert result.user_id == USER_ID
    assert result.current_month_rides == 4
    assert result.current_month_spend == Decimal("200.00")
    assert result.monthly_spend_limit == Decimal("500.00")
    assert result.limit_utilization_pct == pytest.approx(40.0, rel=1e-3)
    assert result.ytd_rides == 15
    assert result.ytd_spend == Decimal("750.00")


# ---------------------------------------------------------------------------
# 2. get_my_spend_summary — success with no limit
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_my_spend_summary_no_limit():
    db = AsyncMock()
    member = _make_member(monthly_spend_limit=None)

    db.execute.side_effect = [
        _scalar_result(member),
        _one_result(rides=2, spend=Decimal("80.00")),
        _one_result(rides=8, spend=Decimal("320.00")),
    ]

    result = await get_my_spend_summary(db, ACCOUNT_ID, USER_ID)

    assert result.monthly_spend_limit is None
    assert result.limit_utilization_pct is None


# ---------------------------------------------------------------------------
# 3. get_my_spend_summary — not a member → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_my_spend_summary_not_member():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_my_spend_summary(db, ACCOUNT_ID, 99)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 4. get_my_spend_history — success with ride data
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_my_spend_history_with_data():
    db = AsyncMock()
    member = _make_member()
    rows = [
        _make_month_row("2026-04", 3, Decimal("120.00")),
        _make_month_row("2026-03", 5, Decimal("200.00")),
    ]

    db.execute.side_effect = [
        _scalar_result(member),    # _require_active_member
        _all_result(rows),         # monthly query
    ]

    result = await get_my_spend_history(db, ACCOUNT_ID, USER_ID, months=6)

    assert result.months_requested == 6
    assert len(result.data) == 2
    assert result.data[0].month == "2026-04"
    assert result.data[0].total_rides == 3
    assert result.data[0].total_spend == Decimal("120.00")
    assert result.data[0].avg_fare == Decimal("40.00")
    assert result.data[1].month == "2026-03"


# ---------------------------------------------------------------------------
# 5. get_my_spend_history — success with no rides
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_my_spend_history_no_rides():
    db = AsyncMock()
    member = _make_member()

    db.execute.side_effect = [
        _scalar_result(member),
        _all_result([]),
    ]

    result = await get_my_spend_history(db, ACCOUNT_ID, USER_ID)

    assert result.data == []


# ---------------------------------------------------------------------------
# 6. get_my_spend_history — months out of range → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_my_spend_history_months_out_of_range():
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_my_spend_history(db, ACCOUNT_ID, USER_ID, months=25)
    assert exc_info.value.status_code == 400


@pytest.mark.anyio
async def test_get_my_spend_history_months_zero():
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_my_spend_history(db, ACCOUNT_ID, USER_ID, months=0)
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 7. get_my_spend_history — not a member → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_my_spend_history_not_member():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_my_spend_history(db, ACCOUNT_ID, 99)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 8. get_member_spend_summary — admin success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_member_spend_summary_admin_success():
    db = AsyncMock()
    admin = _make_admin()
    target = _make_member(
        user_id=OTHER_USER_ID,
        monthly_spend_limit=Decimal("300.00"),
    )

    db.execute.side_effect = [
        _scalar_result(admin),                                      # _require_admin
        _scalar_result(target),                                     # _fetch_target_member
        _one_result(rides=2, spend=Decimal("60.00")),               # current month
        _one_result(rides=8, spend=Decimal("240.00")),              # YTD
    ]

    result = await get_member_spend_summary(
        db, ACCOUNT_ID, OTHER_USER_ID, requesting_user_id=ADMIN_ID
    )

    assert result.user_id == OTHER_USER_ID
    assert result.current_month_rides == 2
    assert result.current_month_spend == Decimal("60.00")
    assert result.monthly_spend_limit == Decimal("300.00")
    assert result.limit_utilization_pct == pytest.approx(20.0, rel=1e-3)
    assert result.is_active is True


# ---------------------------------------------------------------------------
# 9. get_member_spend_summary — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_member_spend_summary_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_member_spend_summary(db, ACCOUNT_ID, OTHER_USER_ID, requesting_user_id=USER_ID)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 10. get_member_spend_summary — target member not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_member_spend_summary_target_not_found():
    db = AsyncMock()
    admin = _make_admin()

    db.execute.side_effect = [
        _scalar_result(admin),    # _require_admin
        _scalar_result(None),     # _fetch_target_member → not found
    ]

    with pytest.raises(HTTPException) as exc_info:
        await get_member_spend_summary(db, ACCOUNT_ID, 999, requesting_user_id=ADMIN_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 11. list_members_spend_summary — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_members_spend_summary_success():
    db = AsyncMock()
    admin = _make_admin()
    m1 = _make_member(user_id=USER_ID, monthly_spend_limit=Decimal("400.00"))
    m2 = _make_member(user_id=OTHER_USER_ID, monthly_spend_limit=None)

    spend_rows = [
        _make_spend_row(USER_ID, 3, Decimal("120.00")),
    ]

    db.execute.side_effect = [
        _scalar_result(admin),          # _require_admin
        _scalars_result([m1, m2]),       # members query
        _all_result(spend_rows),         # bulk spend query
    ]

    result = await list_members_spend_summary(db, ACCOUNT_ID, ADMIN_ID)

    assert result.account_id == ACCOUNT_ID
    assert len(result.members) == 2

    item1 = next(i for i in result.members if i.user_id == USER_ID)
    assert item1.monthly_spend_limit == Decimal("400.00")
    assert item1.current_month_rides == 3
    assert item1.current_month_spend == Decimal("120.00")
    assert item1.limit_utilization_pct == pytest.approx(30.0, rel=1e-3)

    item2 = next(i for i in result.members if i.user_id == OTHER_USER_ID)
    assert item2.monthly_spend_limit is None
    assert item2.current_month_rides == 0
    assert item2.current_month_spend == Decimal("0")
    assert item2.limit_utilization_pct is None


# ---------------------------------------------------------------------------
# 12. list_members_spend_summary — empty account
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_members_spend_summary_empty():
    db = AsyncMock()
    admin = _make_admin()

    db.execute.side_effect = [
        _scalar_result(admin),
        _scalars_result([]),
    ]

    result = await list_members_spend_summary(db, ACCOUNT_ID, ADMIN_ID)

    assert result.members == []


# ---------------------------------------------------------------------------
# 13. list_members_spend_summary — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_members_spend_summary_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await list_members_spend_summary(db, ACCOUNT_ID, USER_ID)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 14. set_member_spend_limit — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_set_member_spend_limit_success():
    db = AsyncMock()
    admin = _make_admin()
    target = _make_member(user_id=OTHER_USER_ID)

    db.execute.side_effect = [
        _scalar_result(admin),
        _scalar_result(target),
    ]

    result = await set_member_spend_limit(
        db, ACCOUNT_ID, OTHER_USER_ID, ADMIN_ID, Decimal("250.00")
    )

    assert result.monthly_spend_limit == Decimal("250.00")
    assert result.user_id == OTHER_USER_ID
    assert "250.00" in result.message
    assert target.monthly_spend_limit == Decimal("250.00")


# ---------------------------------------------------------------------------
# 15. set_member_spend_limit — zero limit → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_set_member_spend_limit_zero():
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await set_member_spend_limit(db, ACCOUNT_ID, OTHER_USER_ID, ADMIN_ID, Decimal("0"))
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 16. set_member_spend_limit — negative limit → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_set_member_spend_limit_negative():
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await set_member_spend_limit(
            db, ACCOUNT_ID, OTHER_USER_ID, ADMIN_ID, Decimal("-50.00")
        )
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 17. set_member_spend_limit — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_set_member_spend_limit_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await set_member_spend_limit(
            db, ACCOUNT_ID, OTHER_USER_ID, USER_ID, Decimal("200.00")
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 18. set_member_spend_limit — member not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_set_member_spend_limit_not_found():
    db = AsyncMock()
    admin = _make_admin()

    db.execute.side_effect = [
        _scalar_result(admin),
        _scalar_result(None),
    ]

    with pytest.raises(HTTPException) as exc_info:
        await set_member_spend_limit(
            db, ACCOUNT_ID, 999, ADMIN_ID, Decimal("200.00")
        )
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 19. remove_member_spend_limit — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_remove_member_spend_limit_success():
    db = AsyncMock()
    admin = _make_admin()
    target = _make_member(user_id=OTHER_USER_ID, monthly_spend_limit=Decimal("300.00"))

    db.execute.side_effect = [
        _scalar_result(admin),
        _scalar_result(target),
    ]

    result = await remove_member_spend_limit(db, ACCOUNT_ID, OTHER_USER_ID, ADMIN_ID)

    assert result.monthly_spend_limit is None
    assert result.user_id == OTHER_USER_ID
    assert "removed" in result.message.lower()
    assert target.monthly_spend_limit is None


# ---------------------------------------------------------------------------
# 20. remove_member_spend_limit — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_remove_member_spend_limit_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await remove_member_spend_limit(db, ACCOUNT_ID, OTHER_USER_ID, USER_ID)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 21. remove_member_spend_limit — member not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_remove_member_spend_limit_not_found():
    db = AsyncMock()
    admin = _make_admin()

    db.execute.side_effect = [
        _scalar_result(admin),
        _scalar_result(None),
    ]

    with pytest.raises(HTTPException) as exc_info:
        await remove_member_spend_limit(db, ACCOUNT_ID, 999, ADMIN_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_set_spend_limit_request_valid():
    req = SetSpendLimitRequest(monthly_limit_usd=Decimal("150.00"))
    assert req.monthly_limit_usd == Decimal("150.00")


def test_set_spend_limit_request_zero_raises():
    with pytest.raises(ValidationError):
        SetSpendLimitRequest(monthly_limit_usd=Decimal("0"))


def test_set_spend_limit_request_negative_raises():
    with pytest.raises(ValidationError):
        SetSpendLimitRequest(monthly_limit_usd=Decimal("-10.00"))


def test_my_spend_summary_with_limit():
    r = MySpendSummaryResponse(
        account_id=1,
        user_id=2,
        current_month="2026-04",
        current_month_rides=5,
        current_month_spend=Decimal("100.00"),
        monthly_spend_limit=Decimal("500.00"),
        limit_utilization_pct=20.0,
        ytd_rides=20,
        ytd_spend=Decimal("400.00"),
    )
    assert r.limit_utilization_pct == 20.0
    assert r.monthly_spend_limit == Decimal("500.00")


def test_my_spend_summary_no_limit():
    r = MySpendSummaryResponse(
        account_id=1,
        user_id=2,
        current_month="2026-04",
        current_month_rides=3,
        current_month_spend=Decimal("75.00"),
        monthly_spend_limit=None,
        limit_utilization_pct=None,
        ytd_rides=12,
        ytd_spend=Decimal("300.00"),
    )
    assert r.monthly_spend_limit is None
    assert r.limit_utilization_pct is None


def test_my_spend_history_response():
    points = [
        MySpendHistoryPoint(month="2026-04", total_rides=3, total_spend=Decimal("90.00"), avg_fare=Decimal("30.00")),
        MySpendHistoryPoint(month="2026-03", total_rides=0, total_spend=Decimal("0.00"), avg_fare=None),
    ]
    r = MySpendHistoryResponse(account_id=1, user_id=2, months_requested=6, data=points)
    assert r.data[1].avg_fare is None


def test_member_spend_limits_response():
    items = [
        MemberSpendItem(
            user_id=1,
            monthly_spend_limit=Decimal("200.00"),
            current_month_rides=2,
            current_month_spend=Decimal("50.00"),
            limit_utilization_pct=25.0,
            is_active=True,
        ),
        MemberSpendItem(
            user_id=2,
            monthly_spend_limit=None,
            current_month_rides=0,
            current_month_spend=Decimal("0.00"),
            limit_utilization_pct=None,
            is_active=False,
        ),
    ]
    r = MemberSpendLimitsResponse(account_id=10, current_month="2026-04", members=items)
    assert len(r.members) == 2
    assert r.members[1].is_active is False


def test_spend_limit_response_set():
    r = SpendLimitResponse(
        account_id=10,
        user_id=5,
        monthly_spend_limit=Decimal("300.00"),
        message="Monthly spend limit set to $300.00.",
    )
    assert r.monthly_spend_limit == Decimal("300.00")


def test_spend_limit_response_remove():
    r = SpendLimitResponse(
        account_id=10,
        user_id=5,
        monthly_spend_limit=None,
        message="Monthly spend limit removed.",
    )
    assert r.monthly_spend_limit is None


def test_utilization_pct_zero_spend():
    result = _utilization_pct(Decimal("0.00"), Decimal("500.00"))
    assert result == pytest.approx(0.0)


def test_utilization_pct_no_limit():
    result = _utilization_pct(Decimal("100.00"), None)
    assert result is None


def test_utilization_pct_rounds():
    # 1/3 * 100 = 33.333... → 33.33
    result = _utilization_pct(Decimal("100.00"), Decimal("300.00"))
    assert result == pytest.approx(33.33, rel=1e-3)


def test_utilization_pct_over_limit():
    result = _utilization_pct(Decimal("600.00"), Decimal("500.00"))
    assert result == pytest.approx(120.0, rel=1e-3)


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------


def _make_user(user_id: int = USER_ID, is_admin: bool = False) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.is_admin = is_admin
    return user


def _make_account_mock(account_id: int = ACCOUNT_ID) -> MagicMock:
    acct = MagicMock()
    acct.id = account_id
    return acct


def _summary_response() -> MySpendSummaryResponse:
    return MySpendSummaryResponse(
        account_id=ACCOUNT_ID,
        user_id=USER_ID,
        current_month="2026-04",
        current_month_rides=3,
        current_month_spend=Decimal("90.00"),
        monthly_spend_limit=Decimal("500.00"),
        limit_utilization_pct=18.0,
        ytd_rides=12,
        ytd_spend=Decimal("360.00"),
    )


def _history_response() -> MySpendHistoryResponse:
    return MySpendHistoryResponse(
        account_id=ACCOUNT_ID,
        user_id=USER_ID,
        months_requested=6,
        data=[],
    )


def _limits_response() -> MemberSpendLimitsResponse:
    return MemberSpendLimitsResponse(
        account_id=ACCOUNT_ID,
        current_month="2026-04",
        members=[],
    )


def _member_summary_response() -> MemberSpendSummaryResponse:
    return MemberSpendSummaryResponse(
        account_id=ACCOUNT_ID,
        user_id=OTHER_USER_ID,
        current_month="2026-04",
        current_month_rides=2,
        current_month_spend=Decimal("40.00"),
        monthly_spend_limit=Decimal("200.00"),
        limit_utilization_pct=20.0,
        ytd_rides=8,
        ytd_spend=Decimal("160.00"),
        is_active=True,
    )


def _limit_set_response() -> SpendLimitResponse:
    return SpendLimitResponse(
        account_id=ACCOUNT_ID,
        user_id=OTHER_USER_ID,
        monthly_spend_limit=Decimal("300.00"),
        message="Monthly spend limit set to $300.00.",
    )


def _limit_removed_response() -> SpendLimitResponse:
    return SpendLimitResponse(
        account_id=ACCOUNT_ID,
        user_id=OTHER_USER_ID,
        monthly_spend_limit=None,
        message="Monthly spend limit removed.",
    )


@pytest.mark.anyio
async def test_api_my_spend_summary_200():
    from app.api.v1.corporate_employee_expense import my_spend_summary

    user = _make_user()
    db = AsyncMock()

    with (
        patch(
            "app.api.v1.corporate_employee_expense.get_user_account",
            new=AsyncMock(return_value=_make_account_mock()),
        ),
        patch(
            "app.api.v1.corporate_employee_expense.get_my_spend_summary",
            new=AsyncMock(return_value=_summary_response()),
        ),
    ):
        result = await my_spend_summary(user=user, db=db)

    assert result.account_id == ACCOUNT_ID
    assert result.current_month_rides == 3


@pytest.mark.anyio
async def test_api_my_spend_summary_no_account_404():
    from app.api.v1.corporate_employee_expense import my_spend_summary

    user = _make_user()
    db = AsyncMock()

    with patch(
        "app.api.v1.corporate_employee_expense.get_user_account",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await my_spend_summary(user=user, db=db)
    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_api_my_spend_history_200():
    from app.api.v1.corporate_employee_expense import my_spend_history

    user = _make_user()
    db = AsyncMock()

    with (
        patch(
            "app.api.v1.corporate_employee_expense.get_user_account",
            new=AsyncMock(return_value=_make_account_mock()),
        ),
        patch(
            "app.api.v1.corporate_employee_expense.get_my_spend_history",
            new=AsyncMock(return_value=_history_response()),
        ),
    ):
        result = await my_spend_history(months=6, user=user, db=db)

    assert result.months_requested == 6


@pytest.mark.anyio
async def test_api_admin_list_member_spend_limits_200():
    from app.api.v1.corporate_employee_expense import admin_list_member_spend_limits

    user = _make_user(user_id=ADMIN_ID)
    db = AsyncMock()

    with (
        patch(
            "app.api.v1.corporate_employee_expense.get_user_account",
            new=AsyncMock(return_value=_make_account_mock()),
        ),
        patch(
            "app.api.v1.corporate_employee_expense.list_members_spend_summary",
            new=AsyncMock(return_value=_limits_response()),
        ),
    ):
        result = await admin_list_member_spend_limits(user=user, db=db)

    assert result.account_id == ACCOUNT_ID


@pytest.mark.anyio
async def test_api_admin_get_member_spend_200():
    from app.api.v1.corporate_employee_expense import admin_get_member_spend

    user = _make_user(user_id=ADMIN_ID)
    db = AsyncMock()

    with (
        patch(
            "app.api.v1.corporate_employee_expense.get_user_account",
            new=AsyncMock(return_value=_make_account_mock()),
        ),
        patch(
            "app.api.v1.corporate_employee_expense.get_member_spend_summary",
            new=AsyncMock(return_value=_member_summary_response()),
        ),
    ):
        result = await admin_get_member_spend(target_user_id=OTHER_USER_ID, user=user, db=db)

    assert result.user_id == OTHER_USER_ID


@pytest.mark.anyio
async def test_api_admin_set_spend_limit_200():
    from app.api.v1.corporate_employee_expense import admin_set_member_spend_limit

    user = _make_user(user_id=ADMIN_ID)
    db = AsyncMock()
    data = SetSpendLimitRequest(monthly_limit_usd=Decimal("300.00"))

    with (
        patch(
            "app.api.v1.corporate_employee_expense.get_user_account",
            new=AsyncMock(return_value=_make_account_mock()),
        ),
        patch(
            "app.api.v1.corporate_employee_expense.set_member_spend_limit",
            new=AsyncMock(return_value=_limit_set_response()),
        ),
    ):
        result = await admin_set_member_spend_limit(
            target_user_id=OTHER_USER_ID, data=data, user=user, db=db
        )

    assert result.monthly_spend_limit == Decimal("300.00")


@pytest.mark.anyio
async def test_api_admin_remove_spend_limit_200():
    from app.api.v1.corporate_employee_expense import admin_remove_member_spend_limit

    user = _make_user(user_id=ADMIN_ID)
    db = AsyncMock()

    with (
        patch(
            "app.api.v1.corporate_employee_expense.get_user_account",
            new=AsyncMock(return_value=_make_account_mock()),
        ),
        patch(
            "app.api.v1.corporate_employee_expense.remove_member_spend_limit",
            new=AsyncMock(return_value=_limit_removed_response()),
        ),
    ):
        result = await admin_remove_member_spend_limit(
            target_user_id=OTHER_USER_ID, user=user, db=db
        )

    assert result.monthly_spend_limit is None


@pytest.mark.anyio
async def test_api_platform_admin_list_200():
    from app.api.v1.corporate_employee_expense import platform_admin_list_member_spend_limits
    from app.models.corporate import BusinessAccountMember

    admin_user = _make_user(user_id=ADMIN_ID, is_admin=True)
    db = AsyncMock()

    m1 = _make_member(user_id=USER_ID, monthly_spend_limit=Decimal("400.00"))
    spend_rows = [_make_spend_row(USER_ID, 2, Decimal("80.00"))]

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [m1]
    members_result = MagicMock()
    members_result.scalars.return_value = scalars_mock

    all_mock = MagicMock()
    all_mock.all.return_value = spend_rows

    db.execute.side_effect = [members_result, all_mock]

    result = await platform_admin_list_member_spend_limits(
        account_id=ACCOUNT_ID, _admin=admin_user, db=db
    )

    assert result.account_id == ACCOUNT_ID
    assert len(result.members) == 1
    assert result.members[0].current_month_spend == Decimal("80.00")
