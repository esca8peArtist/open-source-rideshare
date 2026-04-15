"""Tests for the Corporate Cost Centers feature.

Service layer (async, mocked DB):
  1.  create_cost_center — creates cost center for account admin
  2.  create_cost_center — raises 403 when caller is not an account admin
  3.  create_cost_center — raises 400 on duplicate code within account
  4.  create_cost_center — raises 400 when max cost centers reached
  5.  get_cost_center — returns cost center by ID and account
  6.  get_cost_center — raises 404 when not found
  7.  get_cost_center — raises 404 on account_id mismatch
  8.  list_cost_centers — returns active cost centers only (default)
  9.  list_cost_centers — returns all when active_only=False
  10. update_cost_center — updates name and monthly_budget
  11. update_cost_center — raises 403 when caller is not admin
  12. update_cost_center — raises 404 when not found
  13. deactivate_cost_center — sets is_active=False
  14. deactivate_cost_center — raises 400 when already inactive
  15. deactivate_cost_center — raises 403 when caller is not admin
  16. deactivate_cost_center — raises 404 when not found
  17. get_cost_center_spend — returns spend totals for a cost center
  18. get_cost_center_spend — computes budget_utilization_pct when budget set
  19. get_cost_center_spend — budget_utilization_pct is None when no budget
  20. get_cost_center_spend — raises 404 for unknown cost center
  21. list_account_spend_by_cost_center — returns list ordered by spend desc
  22. list_account_spend_by_cost_center — returns empty list for account with no cost centers
  23. list_account_spend_by_cost_center — includes cost centers with zero rides

Schema validation:
  24. CorporateCostCenterCreate — valid minimal payload accepted
  25. CorporateCostCenterCreate — code normalised to UPPER
  26. CorporateCostCenterCreate — code with invalid characters raises ValidationError
  27. CorporateCostCenterCreate — monthly_budget must be > 0
  28. CorporateCostCenterCreate — name too long raises ValidationError
  29. CorporateCostCenterUpdate — all fields optional; partial updates accepted
  30. CostCenterSpendSummary — serialises correctly

API layer (service functions patched):
  31. POST /corporate/accounts/me/cost-centers — calls create_cost_center (201)
  32. GET  /corporate/accounts/me/cost-centers — calls list_cost_centers (200)
  33. GET  /corporate/accounts/me/cost-centers/{id} — calls get_cost_center (200)
  34. PATCH /corporate/accounts/me/cost-centers/{id} — calls update_cost_center (200)
  35. DELETE /corporate/accounts/me/cost-centers/{id} — calls deactivate_cost_center (204)
  36. GET  /corporate/accounts/me/cost-centers/{id}/spend — calls get_cost_center_spend (200)
  37. GET  /corporate/accounts/me/cost-centers/spend — calls list_account_spend_by_cost_center (200)
  38. GET  /admin/corporate/accounts/{id}/cost-centers — admin list (200)
  39. GET  /admin/corporate/accounts/{id}/cost-centers/spend — admin spend breakdown (200)
  40. GET  /admin/corporate/accounts/{id}/cost-centers/{cid}/spend — admin single spend (200)
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_cost_center import CorporateCostCenter
from app.schemas.corporate_cost_center import (
    CorporateCostCenterCreate,
    CorporateCostCenterResponse,
    CorporateCostCenterUpdate,
    CostCenterSpendSummary,
)
from app.services.corporate_cost_center import (
    MAX_COST_CENTERS_PER_ACCOUNT,
    create_cost_center,
    deactivate_cost_center,
    get_cost_center,
    get_cost_center_spend,
    list_account_spend_by_cost_center,
    list_cost_centers,
    update_cost_center,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_cc(
    id: int = 1,
    account_id: int = 10,
    name: str = "Engineering",
    code: str = "ENG",
    description: str | None = None,
    is_active: bool = True,
    monthly_budget: Decimal | None = None,
) -> CorporateCostCenter:
    cc = MagicMock(spec=CorporateCostCenter)
    cc.id = id
    cc.account_id = account_id
    cc.name = name
    cc.code = code
    cc.description = description
    cc.is_active = is_active
    cc.monthly_budget = monthly_budget
    cc.created_at = NOW
    cc.updated_at = NOW
    return cc


def _make_admin_member(account_id: int = 10, user_id: int = 1):
    from app.models.corporate import BusinessAccountMember, MemberRole
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = account_id
    m.user_id = user_id
    m.role = MemberRole.ADMIN
    m.is_active = True
    return m


def _scalar_result(value):
    """Mock execute().scalar_one_or_none() → value."""
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    res.scalar.return_value = value
    res.scalars.return_value.all.return_value = [value] if value is not None else []
    return res


def _scalars_result(items: list):
    res = MagicMock()
    res.scalars.return_value.all.return_value = items
    res.scalar_one_or_none.return_value = items[0] if items else None
    res.scalar.return_value = len(items)
    return res


def _count_result(n: int):
    res = MagicMock()
    res.scalar.return_value = n
    res.scalar_one.return_value = n
    return res


# ---------------------------------------------------------------------------
# 1. create_cost_center — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_cost_center_success():
    db = AsyncMock()
    admin_member = _make_admin_member(account_id=10, user_id=1)
    cc = _make_cc(id=1, account_id=10)

    db.execute.side_effect = [
        _scalar_result(admin_member),  # _require_account_admin
        _scalar_result(None),          # duplicate code check
        _count_result(0),              # max count check
    ]
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    data = CorporateCostCenterCreate(name="Engineering", code="ENG")
    result = await create_cost_center(db, account_id=10, data=data, requesting_user_id=1)
    db.add.assert_called_once()
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 2. create_cost_center — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_cost_center_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)  # no admin member found

    data = CorporateCostCenterCreate(name="Finance", code="FIN")
    with pytest.raises(HTTPException) as exc_info:
        await create_cost_center(db, account_id=10, data=data, requesting_user_id=99)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 3. create_cost_center — duplicate code → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_cost_center_duplicate_code():
    db = AsyncMock()
    admin_member = _make_admin_member()
    existing_cc = _make_cc(code="ENG")

    db.execute.side_effect = [
        _scalar_result(admin_member),   # _require_account_admin
        _scalar_result(existing_cc),    # duplicate code check → found
    ]

    data = CorporateCostCenterCreate(name="Engineering 2", code="ENG")
    with pytest.raises(HTTPException) as exc_info:
        await create_cost_center(db, account_id=10, data=data, requesting_user_id=1)
    assert exc_info.value.status_code == 400
    assert "already exists" in exc_info.value.detail


# ---------------------------------------------------------------------------
# 4. create_cost_center — max count reached → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_cost_center_max_count():
    db = AsyncMock()
    admin_member = _make_admin_member()

    db.execute.side_effect = [
        _scalar_result(admin_member),          # _require_account_admin
        _scalar_result(None),                  # no duplicate
        _count_result(MAX_COST_CENTERS_PER_ACCOUNT),  # at max
    ]

    data = CorporateCostCenterCreate(name="New Dept", code="NEW")
    with pytest.raises(HTTPException) as exc_info:
        await create_cost_center(db, account_id=10, data=data, requesting_user_id=1)
    assert exc_info.value.status_code == 400
    assert "maximum" in exc_info.value.detail


# ---------------------------------------------------------------------------
# 5. get_cost_center — returns cost center
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_cost_center_found():
    db = AsyncMock()
    cc = _make_cc(id=1, account_id=10)
    db.execute.return_value = _scalar_result(cc)

    result = await get_cost_center(db, cost_center_id=1, account_id=10)
    assert result.id == 1
    assert result.account_id == 10


# ---------------------------------------------------------------------------
# 6. get_cost_center — not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_cost_center_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_cost_center(db, cost_center_id=999, account_id=10)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 7. get_cost_center — account_id mismatch → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_cost_center_account_mismatch():
    db = AsyncMock()
    # The query includes account_id in the WHERE, so mismatch returns None
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_cost_center(db, cost_center_id=1, account_id=99)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 8. list_cost_centers — active_only=True (default)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_cost_centers_active_only():
    db = AsyncMock()
    cc1 = _make_cc(id=1, name="Engineering", code="ENG")
    cc2 = _make_cc(id=2, name="Marketing", code="MKT")
    db.execute.return_value = _scalars_result([cc1, cc2])

    results = await list_cost_centers(db, account_id=10, active_only=True)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# 9. list_cost_centers — active_only=False
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_cost_centers_all():
    db = AsyncMock()
    cc1 = _make_cc(id=1, is_active=True)
    cc2 = _make_cc(id=2, is_active=False)
    db.execute.return_value = _scalars_result([cc1, cc2])

    results = await list_cost_centers(db, account_id=10, active_only=False)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# 10. update_cost_center — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_cost_center_success():
    db = AsyncMock()
    admin_member = _make_admin_member()
    cc = _make_cc(id=1, name="Old Name", monthly_budget=None)

    db.execute.side_effect = [
        _scalar_result(admin_member),  # _require_account_admin
        _scalar_result(cc),            # _get_cost_center
    ]
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    data = CorporateCostCenterUpdate(name="New Name", monthly_budget=Decimal("500.00"))
    result = await update_cost_center(
        db, cost_center_id=1, account_id=10, data=data, requesting_user_id=1
    )
    assert cc.name == "New Name"
    assert cc.monthly_budget == Decimal("500.00")
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 11. update_cost_center — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_cost_center_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    data = CorporateCostCenterUpdate(name="Attempted Update")
    with pytest.raises(HTTPException) as exc_info:
        await update_cost_center(
            db, cost_center_id=1, account_id=10, data=data, requesting_user_id=99
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 12. update_cost_center — not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_cost_center_not_found():
    db = AsyncMock()
    admin_member = _make_admin_member()
    db.execute.side_effect = [
        _scalar_result(admin_member),  # _require_account_admin
        _scalar_result(None),          # _get_cost_center → 404
    ]

    data = CorporateCostCenterUpdate(name="Ghost Update")
    with pytest.raises(HTTPException) as exc_info:
        await update_cost_center(
            db, cost_center_id=999, account_id=10, data=data, requesting_user_id=1
        )
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 13. deactivate_cost_center — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deactivate_cost_center_success():
    db = AsyncMock()
    admin_member = _make_admin_member()
    cc = _make_cc(id=1, is_active=True)

    db.execute.side_effect = [
        _scalar_result(admin_member),
        _scalar_result(cc),
    ]
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    result = await deactivate_cost_center(
        db, cost_center_id=1, account_id=10, requesting_user_id=1
    )
    assert cc.is_active is False
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 14. deactivate_cost_center — already inactive → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deactivate_cost_center_already_inactive():
    db = AsyncMock()
    admin_member = _make_admin_member()
    cc = _make_cc(id=1, is_active=False)

    db.execute.side_effect = [
        _scalar_result(admin_member),
        _scalar_result(cc),
    ]

    with pytest.raises(HTTPException) as exc_info:
        await deactivate_cost_center(
            db, cost_center_id=1, account_id=10, requesting_user_id=1
        )
    assert exc_info.value.status_code == 400
    assert "already inactive" in exc_info.value.detail


# ---------------------------------------------------------------------------
# 15. deactivate_cost_center — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deactivate_cost_center_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await deactivate_cost_center(
            db, cost_center_id=1, account_id=10, requesting_user_id=99
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 16. deactivate_cost_center — not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deactivate_cost_center_not_found():
    db = AsyncMock()
    admin_member = _make_admin_member()
    db.execute.side_effect = [
        _scalar_result(admin_member),
        _scalar_result(None),  # _get_cost_center → 404
    ]

    with pytest.raises(HTTPException) as exc_info:
        await deactivate_cost_center(
            db, cost_center_id=999, account_id=10, requesting_user_id=1
        )
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 17. get_cost_center_spend — returns totals
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_cost_center_spend_basic():
    db = AsyncMock()
    cc = _make_cc(id=1, name="Engineering", code="ENG", monthly_budget=None)

    spend_row = MagicMock()
    spend_row.total_rides = 5
    spend_row.total_spend = Decimal("320.75")

    spend_result = MagicMock()
    spend_result.one.return_value = spend_row

    db.execute.side_effect = [
        _scalar_result(cc),   # _get_cost_center
        spend_result,         # spend query
    ]

    result = await get_cost_center_spend(db, cost_center_id=1, account_id=10)
    assert result["total_rides"] == 5
    assert result["total_spend"] == Decimal("320.75")
    assert result["budget_utilization_pct"] is None


# ---------------------------------------------------------------------------
# 18. get_cost_center_spend — budget_utilization_pct computed
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_cost_center_spend_with_budget():
    db = AsyncMock()
    cc = _make_cc(id=1, monthly_budget=Decimal("1000.00"))

    spend_row = MagicMock()
    spend_row.total_rides = 3
    spend_row.total_spend = Decimal("250.00")

    spend_result = MagicMock()
    spend_result.one.return_value = spend_row

    db.execute.side_effect = [
        _scalar_result(cc),
        spend_result,
    ]

    result = await get_cost_center_spend(db, cost_center_id=1, account_id=10)
    assert result["budget_utilization_pct"] == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# 19. get_cost_center_spend — no budget → pct is None
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_cost_center_spend_no_budget_pct_none():
    db = AsyncMock()
    cc = _make_cc(id=1, monthly_budget=None)

    spend_row = MagicMock()
    spend_row.total_rides = 0
    spend_row.total_spend = Decimal("0.00")

    spend_result = MagicMock()
    spend_result.one.return_value = spend_row

    db.execute.side_effect = [
        _scalar_result(cc),
        spend_result,
    ]

    result = await get_cost_center_spend(db, cost_center_id=1, account_id=10)
    assert result["budget_utilization_pct"] is None


# ---------------------------------------------------------------------------
# 20. get_cost_center_spend — 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_cost_center_spend_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_cost_center_spend(db, cost_center_id=999, account_id=10)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 21. list_account_spend_by_cost_center — ordered by spend desc
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_account_spend_ordered_by_spend():
    db = AsyncMock()
    cc_eng = _make_cc(id=1, name="Engineering", code="ENG", monthly_budget=None)
    cc_mkt = _make_cc(id=2, name="Marketing", code="MKT", monthly_budget=None)

    # Build spend rows
    row_eng = MagicMock()
    row_eng.cost_center_id = 1
    row_eng.total_rides = 10
    row_eng.total_spend = Decimal("800.00")

    row_mkt = MagicMock()
    row_mkt.cost_center_id = 2
    row_mkt.total_rides = 3
    row_mkt.total_spend = Decimal("200.00")

    spend_res = MagicMock()
    spend_res.all.return_value = [row_eng, row_mkt]

    cc_list_res = MagicMock()
    cc_list_res.scalars.return_value.all.return_value = [cc_eng, cc_mkt]

    db.execute.side_effect = [cc_list_res, spend_res]

    results = await list_account_spend_by_cost_center(db, account_id=10)
    assert len(results) == 2
    # Engineering has higher spend → comes first
    assert results[0]["cost_center_code"] == "ENG"
    assert results[1]["cost_center_code"] == "MKT"


# ---------------------------------------------------------------------------
# 22. list_account_spend_by_cost_center — empty when no cost centers
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_account_spend_empty():
    db = AsyncMock()
    cc_list_res = MagicMock()
    cc_list_res.scalars.return_value.all.return_value = []

    db.execute.return_value = cc_list_res

    results = await list_account_spend_by_cost_center(db, account_id=10)
    assert results == []


# ---------------------------------------------------------------------------
# 23. list_account_spend_by_cost_center — zero rides for a cost center
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_account_spend_zero_rides():
    db = AsyncMock()
    cc_new = _make_cc(id=5, name="R&D", code="RD", monthly_budget=None)

    spend_res = MagicMock()
    spend_res.all.return_value = []  # No rides for any cost center

    cc_list_res = MagicMock()
    cc_list_res.scalars.return_value.all.return_value = [cc_new]

    db.execute.side_effect = [cc_list_res, spend_res]

    results = await list_account_spend_by_cost_center(db, account_id=10)
    assert len(results) == 1
    assert results[0]["total_rides"] == 0
    assert results[0]["total_spend"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_schema_create_valid_minimal():
    data = CorporateCostCenterCreate(name="Engineering", code="ENG")
    assert data.name == "Engineering"
    assert data.code == "ENG"
    assert data.description is None
    assert data.monthly_budget is None


def test_schema_create_code_normalised_to_upper():
    data = CorporateCostCenterCreate(name="Engineering", code="eng")
    assert data.code == "ENG"


def test_schema_create_code_invalid_characters():
    with pytest.raises(ValidationError):
        CorporateCostCenterCreate(name="Bad", code="ENG @#")


def test_schema_create_monthly_budget_must_be_positive():
    with pytest.raises(ValidationError):
        CorporateCostCenterCreate(name="Finance", code="FIN", monthly_budget=Decimal("-100"))


def test_schema_create_name_too_long():
    with pytest.raises(ValidationError):
        CorporateCostCenterCreate(name="X" * 101, code="TOO")


def test_schema_update_partial():
    data = CorporateCostCenterUpdate(name="New Name")
    assert data.name == "New Name"
    assert data.description is None
    assert data.monthly_budget is None
    assert data.is_active is None


def test_schema_spend_summary_serialises():
    summary = CostCenterSpendSummary(
        cost_center_id=1,
        cost_center_name="Engineering",
        cost_center_code="ENG",
        period_start="2026-04-01",
        period_end="2026-04-30",
        total_rides=5,
        total_spend=Decimal("320.75"),
        monthly_budget=Decimal("1000.00"),
        budget_utilization_pct=32.075,
    )
    assert summary.cost_center_id == 1
    assert summary.budget_utilization_pct == pytest.approx(32.075)


# ---------------------------------------------------------------------------
# API layer — handler functions called directly, services patched
# ---------------------------------------------------------------------------


def _mock_user(user_id: int = 1) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


def _mock_membership(account_id: int = 10, user_id: int = 1) -> MagicMock:
    m = MagicMock()
    m.account_id = account_id
    m.user_id = user_id
    m.is_active = True
    return m


def _mock_cc():
    cc = _make_cc(id=1, account_id=10)
    return cc


def _mock_spend_dict():
    return {
        "cost_center_id": 1,
        "cost_center_name": "Engineering",
        "cost_center_code": "ENG",
        "period_start": None,
        "period_end": None,
        "total_rides": 5,
        "total_spend": Decimal("320.75"),
        "monthly_budget": None,
        "budget_utilization_pct": None,
    }


_SVC = "app.services.corporate_cost_center"
_ROUTER = "app.api.v1.corporate_cost_center"


@pytest.mark.asyncio
async def test_api_create_cost_center():
    """31. POST /corporate/accounts/me/cost-centers calls create_cost_center (201)."""
    from app.api.v1.corporate_cost_center import create_my_cost_center

    user = _mock_user()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=_mock_membership())))
    data = CorporateCostCenterCreate(name="Engineering", code="ENG")

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=10)), \
         patch(f"{_ROUTER}.create_cost_center", new=AsyncMock(return_value=_mock_cc())):
        result = await create_my_cost_center(data=data, db=db, current_user=user)
    assert result.id == 1


@pytest.mark.asyncio
async def test_api_list_cost_centers():
    """32. GET /corporate/accounts/me/cost-centers calls list_cost_centers."""
    from app.api.v1.corporate_cost_center import list_my_cost_centers

    user = _mock_user()
    db = AsyncMock()
    cc = _mock_cc()

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=10)), \
         patch(f"{_ROUTER}.list_cost_centers", new=AsyncMock(return_value=[cc])):
        result = await list_my_cost_centers(active_only=True, db=db, current_user=user)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_api_get_cost_center():
    """33. GET /corporate/accounts/me/cost-centers/{id} calls get_cost_center."""
    from app.api.v1.corporate_cost_center import get_my_cost_center

    user = _mock_user()
    db = AsyncMock()
    cc = _mock_cc()

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=10)), \
         patch(f"{_ROUTER}.get_cost_center", new=AsyncMock(return_value=cc)):
        result = await get_my_cost_center(cost_center_id=1, db=db, current_user=user)
    assert result.id == 1


@pytest.mark.asyncio
async def test_api_update_cost_center():
    """34. PATCH /corporate/accounts/me/cost-centers/{id} calls update_cost_center."""
    from app.api.v1.corporate_cost_center import update_my_cost_center

    user = _mock_user()
    db = AsyncMock()
    cc = _mock_cc()
    data = CorporateCostCenterUpdate(name="New Name")

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=10)), \
         patch(f"{_ROUTER}.update_cost_center", new=AsyncMock(return_value=cc)):
        result = await update_my_cost_center(
            cost_center_id=1, data=data, db=db, current_user=user
        )
    assert result.id == 1


@pytest.mark.asyncio
async def test_api_deactivate_cost_center():
    """35. DELETE /corporate/accounts/me/cost-centers/{id} calls deactivate_cost_center (204)."""
    from app.api.v1.corporate_cost_center import deactivate_my_cost_center

    user = _mock_user()
    db = AsyncMock()
    cc = _mock_cc()

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=10)), \
         patch(f"{_ROUTER}.deactivate_cost_center", new=AsyncMock(return_value=cc)):
        result = await deactivate_my_cost_center(
            cost_center_id=1, db=db, current_user=user
        )
    # 204 route returns None
    assert result is None


@pytest.mark.asyncio
async def test_api_cost_center_spend():
    """36. GET /corporate/accounts/me/cost-centers/{id}/spend calls get_cost_center_spend."""
    from app.api.v1.corporate_cost_center import get_my_cost_center_spend

    user = _mock_user()
    db = AsyncMock()
    spend = _mock_spend_dict()

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=10)), \
         patch(f"{_SVC}._require_account_admin", new=AsyncMock()), \
         patch(f"{_ROUTER}.get_cost_center_spend", new=AsyncMock(return_value=spend)):
        result = await get_my_cost_center_spend(
            cost_center_id=1, period_start=None, period_end=None, db=db, current_user=user
        )
    assert result["cost_center_id"] == 1


@pytest.mark.asyncio
async def test_api_account_spend_breakdown():
    """37. GET /corporate/accounts/me/cost-centers/spend calls list_account_spend_by_cost_center."""
    from app.api.v1.corporate_cost_center import my_account_spend_breakdown

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=10)), \
         patch(f"{_SVC}._require_account_admin", new=AsyncMock()), \
         patch(f"{_ROUTER}.list_account_spend_by_cost_center", new=AsyncMock(return_value=[_mock_spend_dict()])):
        result = await my_account_spend_breakdown(
            period_start=None, period_end=None, db=db, current_user=user
        )
    assert len(result) == 1


@pytest.mark.asyncio
async def test_api_admin_list_cost_centers():
    """38. GET /admin/corporate/accounts/{id}/cost-centers admin list."""
    from app.api.v1.corporate_cost_center import admin_list_cost_centers

    db = AsyncMock()
    cc = _mock_cc()

    with patch(f"{_ROUTER}.list_cost_centers", new=AsyncMock(return_value=[cc])):
        result = await admin_list_cost_centers(account_id=10, active_only=False, db=db)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_api_admin_account_spend_breakdown():
    """39. GET /admin/corporate/accounts/{id}/cost-centers/spend admin spend breakdown."""
    from app.api.v1.corporate_cost_center import admin_account_spend_breakdown

    db = AsyncMock()

    with patch(
        f"{_ROUTER}.list_account_spend_by_cost_center",
        new=AsyncMock(return_value=[_mock_spend_dict()]),
    ):
        result = await admin_account_spend_breakdown(
            account_id=10, period_start=None, period_end=None, db=db
        )
    assert len(result) == 1


@pytest.mark.asyncio
async def test_api_admin_single_cost_center_spend():
    """40. GET /admin/corporate/accounts/{id}/cost-centers/{cid}/spend admin single."""
    from app.api.v1.corporate_cost_center import admin_cost_center_spend

    db = AsyncMock()
    spend = _mock_spend_dict()

    with patch(f"{_ROUTER}.get_cost_center_spend", new=AsyncMock(return_value=spend)):
        result = await admin_cost_center_spend(
            account_id=10, cost_center_id=1, period_start=None, period_end=None, db=db
        )
    assert result["cost_center_id"] == 1
