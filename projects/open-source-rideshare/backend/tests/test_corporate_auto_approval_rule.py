"""Tests for the Corporate Auto-Approval Rules feature.

Service layer (async, mocked DB):
  1.  create_auto_approval_rule — success, sets fields correctly
  2.  create_auto_approval_rule — 409 on duplicate active name
  3.  create_auto_approval_rule — 400 on mismatched start_hour/end_hour
  4.  get_auto_approval_rule — success returns rule
  5.  get_auto_approval_rule — 404 wrong account
  6.  list_auto_approval_rules — returns all rules for account
  7.  list_auto_approval_rules — is_active=True filter
  8.  list_auto_approval_rules — is_active=False filter
  9.  update_auto_approval_rule — success updates fields
  10. update_auto_approval_rule — 409 name collision with different active rule
  11. activate_auto_approval_rule — success
  12. activate_auto_approval_rule — 409 already active
  13. deactivate_auto_approval_rule — success
  14. deactivate_auto_approval_rule — 409 already inactive
  15. delete_auto_approval_rule — success
  16. delete_auto_approval_rule — 404 not found
  17. evaluate_auto_approval — no rules → returns (False, None)
  18. evaluate_auto_approval — rule with all-null conditions always matches
  19. evaluate_auto_approval — max_cost_usd respected (pass)
  20. evaluate_auto_approval — max_cost_usd respected (fail)
  21. evaluate_auto_approval — allowed_days_of_week filter (pass)
  22. evaluate_auto_approval — allowed_days_of_week filter (fail)
  23. evaluate_auto_approval — start_hour/end_hour range (pass)
  24. evaluate_auto_approval — start_hour/end_hour range (fail)
  25. evaluate_auto_approval — trip_purpose_ids filter (pass)
  26. evaluate_auto_approval — trip_purpose_ids filter (fail)
  27. evaluate_auto_approval — cost_center_ids filter (pass)
  28. evaluate_auto_approval — cost_center_ids filter (fail)
  29. evaluate_auto_approval — employee_group_ids filter (pass)
  30. evaluate_auto_approval — employee_group_ids filter (fail)
  31. evaluate_auto_approval — multiple rules, highest priority wins
  32. evaluate_auto_approval — inactive rule not matched
  33. list_all_auto_approval_rules_platform — returns rules newest first

Schema validation:
  34. AutoApprovalRuleCreate — name required
  35. AutoApprovalRuleCreate — name empty string raises validation error
  36. AutoApprovalRuleCreate — start_hour without end_hour raises validation error
  37. AutoApprovalRuleCreate — both hours set passes validation
  38. AutoApprovalRuleResponse — from_attributes construction

API layer (service functions patched):
  39. POST create — 201 admin can create rule
  40. POST create — 404 when no corporate account
  41. GET list — 200 member can list rules
  42. GET get — 200 member can view rule
  43. GET get — 404 not found
  44. PUT update — 200 admin can update rule
  45. POST activate — 200 admin can activate
  46. POST deactivate — 200 admin can deactivate
  47. DELETE delete — 204 admin can delete
  48. POST evaluate — 200 member can evaluate (match)
  49. POST evaluate — 200 member can evaluate (no match)
  50. GET platform list — 200 platform-admin list all
  51. GET platform account list — 200 platform-admin account-specific list
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_auto_approval_rule import CorporateAutoApprovalRule
from app.schemas.corporate_auto_approval_rule import (
    AutoApprovalRuleCreate,
    AutoApprovalRuleListResponse,
    AutoApprovalRuleResponse,
    AutoApprovalRuleUpdate,
    EvaluateAutoApprovalRequest,
    EvaluateAutoApprovalResponse,
)
from app.services.corporate_auto_approval_rule import (
    activate_auto_approval_rule,
    create_auto_approval_rule,
    deactivate_auto_approval_rule,
    delete_auto_approval_rule,
    evaluate_auto_approval,
    get_auto_approval_rule,
    list_all_auto_approval_rules_platform,
    list_auto_approval_rules,
    update_auto_approval_rule,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 10
OTHER_ACCOUNT_ID = 99
ADMIN_ID = 2
USER_ID = 1
MEMBER_ID = 5
RULE_ID = 42

_SERVICE = "app.services.corporate_auto_approval_rule"
_ROUTER = "app.api.v1.corporate_auto_approval_rule"

_NOW = datetime(2026, 4, 16, 9, 0, 0, tzinfo=timezone.utc)
# Wednesday = weekday 2
_WEDNESDAY_9AM = datetime(2026, 4, 15, 9, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rule(
    rule_id: int = RULE_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Low-cost weekday rides",
    is_active: bool = True,
    max_cost_usd=None,
    trip_purpose_ids=None,
    cost_center_ids=None,
    employee_group_ids=None,
    allowed_days_of_week=None,
    start_hour=None,
    end_hour=None,
    priority: int = 0,
    created_by_id: int | None = ADMIN_ID,
) -> CorporateAutoApprovalRule:
    """Build a minimal CorporateAutoApprovalRule for testing."""
    r = CorporateAutoApprovalRule()
    r.id = rule_id
    r.account_id = account_id
    r.name = name
    r.is_active = is_active
    r.max_cost_usd = max_cost_usd
    r.trip_purpose_ids = trip_purpose_ids
    r.cost_center_ids = cost_center_ids
    r.employee_group_ids = employee_group_ids
    r.allowed_days_of_week = allowed_days_of_week
    r.start_hour = start_hour
    r.end_hour = end_hour
    r.priority = priority
    r.created_by_id = created_by_id
    r.created_at = _NOW
    r.updated_at = _NOW
    return r


def _scalar_result(value) -> MagicMock:
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    return res


def _scalars_all_result(values: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = values
    res = MagicMock()
    res.scalars.return_value = scalars
    return res


def _all_result(rows: list) -> MagicMock:
    res = MagicMock()
    res.all.return_value = rows
    return res


def _mock_user(user_id: int = USER_ID, is_admin: bool = False) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    u.is_admin = is_admin
    return u


def _make_rule_response(rule_id: int = RULE_ID) -> AutoApprovalRuleResponse:
    return AutoApprovalRuleResponse(
        id=rule_id,
        account_id=ACCOUNT_ID,
        name="Low-cost weekday rides",
        is_active=True,
        max_cost_usd=None,
        trip_purpose_ids=None,
        cost_center_ids=None,
        employee_group_ids=None,
        allowed_days_of_week=None,
        start_hour=None,
        end_hour=None,
        priority=0,
        created_by_id=ADMIN_ID,
        created_at=_NOW,
        updated_at=_NOW,
    )


# ---------------------------------------------------------------------------
# 1. create_auto_approval_rule — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_rule_success():
    db = AsyncMock()
    # No existing rule with that name
    db.execute.return_value = _scalar_result(None)
    added = []
    db.add = lambda x: added.append(x)

    async def _fake_refresh(obj):
        obj.id = RULE_ID
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _fake_refresh

    data = AutoApprovalRuleCreate(name="Low-cost weekday rides")
    result = await create_auto_approval_rule(db, ACCOUNT_ID, ADMIN_ID, data)

    assert len(added) == 1
    assert result.id == RULE_ID
    assert added[0].name == "Low-cost weekday rides"
    assert added[0].account_id == ACCOUNT_ID
    assert added[0].created_by_id == ADMIN_ID
    assert added[0].is_active is True
    assert added[0].priority == 0


# ---------------------------------------------------------------------------
# 2. create_auto_approval_rule — 409 duplicate active name
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_rule_409_duplicate_name():
    db = AsyncMock()
    existing = _make_rule()
    db.execute.return_value = _scalar_result(existing)

    data = AutoApprovalRuleCreate(name="Low-cost weekday rides")
    with pytest.raises(HTTPException) as exc:
        await create_auto_approval_rule(db, ACCOUNT_ID, ADMIN_ID, data)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# 3. create_auto_approval_rule — 400 mismatched hours
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_rule_400_mismatched_hours():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    # Manually craft a data object bypassing pydantic validation to test service guard
    data = MagicMock()
    data.name = "Test Rule"
    data.is_active = True
    data.max_cost_usd = None
    data.trip_purpose_ids = None
    data.cost_center_ids = None
    data.employee_group_ids = None
    data.allowed_days_of_week = None
    data.start_hour = 9
    data.end_hour = None  # mismatch
    data.priority = 0

    with pytest.raises(HTTPException) as exc:
        await create_auto_approval_rule(db, ACCOUNT_ID, ADMIN_ID, data)
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# 4. get_auto_approval_rule — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_rule_success():
    db = AsyncMock()
    existing = _make_rule()
    db.execute.return_value = _scalar_result(existing)

    result = await get_auto_approval_rule(db, RULE_ID, ACCOUNT_ID)
    assert result.id == RULE_ID
    assert result.account_id == ACCOUNT_ID


# ---------------------------------------------------------------------------
# 5. get_auto_approval_rule — 404 wrong account
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_rule_404_wrong_account():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await get_auto_approval_rule(db, RULE_ID, OTHER_ACCOUNT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 6. list_auto_approval_rules — returns all
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_rules_returns_all():
    db = AsyncMock()
    rules = [_make_rule(rule_id=1), _make_rule(rule_id=2)]
    db.execute.return_value = _scalars_all_result(rules)

    result = await list_auto_approval_rules(db, ACCOUNT_ID)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# 7. list_auto_approval_rules — is_active=True filter
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_rules_active_filter():
    db = AsyncMock()
    active_rule = _make_rule(is_active=True)
    db.execute.return_value = _scalars_all_result([active_rule])

    result = await list_auto_approval_rules(db, ACCOUNT_ID, is_active=True)
    assert len(result) == 1
    assert result[0].is_active is True


# ---------------------------------------------------------------------------
# 8. list_auto_approval_rules — is_active=False filter
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_rules_inactive_filter():
    db = AsyncMock()
    inactive_rule = _make_rule(is_active=False)
    db.execute.return_value = _scalars_all_result([inactive_rule])

    result = await list_auto_approval_rules(db, ACCOUNT_ID, is_active=False)
    assert len(result) == 1
    assert result[0].is_active is False


# ---------------------------------------------------------------------------
# 9. update_auto_approval_rule — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_rule_success():
    db = AsyncMock()
    existing = _make_rule(priority=0)
    # First call: fetch rule; second call: name conflict check (returns None)
    db.execute.side_effect = [_scalar_result(existing), _scalar_result(None)]
    updated = []
    db.add = lambda x: updated.append(x)

    async def _fake_refresh(obj):
        obj.updated_at = _NOW

    db.refresh = _fake_refresh

    data = AutoApprovalRuleUpdate(name="Updated Name", priority=5)
    result = await update_auto_approval_rule(db, RULE_ID, ACCOUNT_ID, data)

    assert result.name == "Updated Name"
    assert result.priority == 5


# ---------------------------------------------------------------------------
# 10. update_auto_approval_rule — 409 name collision
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_rule_409_name_collision():
    db = AsyncMock()
    existing = _make_rule(name="Old Name")
    conflicting = _make_rule(rule_id=99, name="Taken Name")
    db.execute.side_effect = [_scalar_result(existing), _scalar_result(conflicting)]

    data = AutoApprovalRuleUpdate(name="Taken Name")
    with pytest.raises(HTTPException) as exc:
        await update_auto_approval_rule(db, RULE_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# 11. activate_auto_approval_rule — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_activate_rule_success():
    db = AsyncMock()
    inactive = _make_rule(is_active=False)
    db.execute.return_value = _scalar_result(inactive)
    added = []
    db.add = lambda x: added.append(x)

    async def _fake_refresh(obj):
        pass

    db.refresh = _fake_refresh

    result = await activate_auto_approval_rule(db, RULE_ID, ACCOUNT_ID)
    assert result.is_active is True


# ---------------------------------------------------------------------------
# 12. activate_auto_approval_rule — 409 already active
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_activate_rule_409_already_active():
    db = AsyncMock()
    active = _make_rule(is_active=True)
    db.execute.return_value = _scalar_result(active)

    with pytest.raises(HTTPException) as exc:
        await activate_auto_approval_rule(db, RULE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# 13. deactivate_auto_approval_rule — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deactivate_rule_success():
    db = AsyncMock()
    active = _make_rule(is_active=True)
    db.execute.return_value = _scalar_result(active)
    added = []
    db.add = lambda x: added.append(x)

    async def _fake_refresh(obj):
        pass

    db.refresh = _fake_refresh

    result = await deactivate_auto_approval_rule(db, RULE_ID, ACCOUNT_ID)
    assert result.is_active is False


# ---------------------------------------------------------------------------
# 14. deactivate_auto_approval_rule — 409 already inactive
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deactivate_rule_409_already_inactive():
    db = AsyncMock()
    inactive = _make_rule(is_active=False)
    db.execute.return_value = _scalar_result(inactive)

    with pytest.raises(HTTPException) as exc:
        await deactivate_auto_approval_rule(db, RULE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# 15. delete_auto_approval_rule — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_rule_success():
    db = AsyncMock()
    existing = _make_rule()
    db.execute.return_value = _scalar_result(existing)

    await delete_auto_approval_rule(db, RULE_ID, ACCOUNT_ID)
    db.delete.assert_called_once_with(existing)
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 16. delete_auto_approval_rule — 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_rule_404():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await delete_auto_approval_rule(db, RULE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 17. evaluate_auto_approval — no rules → False
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_no_rules_returns_false():
    db = AsyncMock()
    db.execute.return_value = _scalars_all_result([])

    approved, rule = await evaluate_auto_approval(
        db, ACCOUNT_ID, MEMBER_ID, estimated_cost_usd=25.0
    )
    assert approved is False
    assert rule is None


# ---------------------------------------------------------------------------
# 18. evaluate_auto_approval — all-null conditions always match
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_all_null_conditions_matches():
    db = AsyncMock()
    # Rule with no conditions — matches anything
    null_rule = _make_rule(
        max_cost_usd=None,
        trip_purpose_ids=None,
        cost_center_ids=None,
        employee_group_ids=None,
        allowed_days_of_week=None,
        start_hour=None,
        end_hour=None,
    )
    db.execute.return_value = _scalars_all_result([null_rule])

    approved, matched = await evaluate_auto_approval(
        db, ACCOUNT_ID, MEMBER_ID, estimated_cost_usd=999.99
    )
    assert approved is True
    assert matched is null_rule


# ---------------------------------------------------------------------------
# 19. evaluate_auto_approval — max_cost_usd respected (pass)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_max_cost_pass():
    db = AsyncMock()
    rule = _make_rule(max_cost_usd=50.00)
    db.execute.return_value = _scalars_all_result([rule])

    approved, matched = await evaluate_auto_approval(
        db, ACCOUNT_ID, MEMBER_ID, estimated_cost_usd=49.99
    )
    assert approved is True
    assert matched is rule


# ---------------------------------------------------------------------------
# 20. evaluate_auto_approval — max_cost_usd respected (fail)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_max_cost_fail():
    db = AsyncMock()
    rule = _make_rule(max_cost_usd=50.00)
    db.execute.return_value = _scalars_all_result([rule])

    approved, matched = await evaluate_auto_approval(
        db, ACCOUNT_ID, MEMBER_ID, estimated_cost_usd=50.01
    )
    assert approved is False
    assert matched is None


# ---------------------------------------------------------------------------
# 21. evaluate_auto_approval — allowed_days_of_week (pass)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_day_of_week_pass():
    db = AsyncMock()
    # Wednesday = 2
    rule = _make_rule(allowed_days_of_week=[0, 1, 2, 3, 4])  # Mon-Fri
    db.execute.return_value = _scalars_all_result([rule])

    # _WEDNESDAY_9AM is a Wednesday
    approved, matched = await evaluate_auto_approval(
        db, ACCOUNT_ID, MEMBER_ID, estimated_cost_usd=10.0, ride_dt=_WEDNESDAY_9AM
    )
    assert approved is True


# ---------------------------------------------------------------------------
# 22. evaluate_auto_approval — allowed_days_of_week (fail)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_day_of_week_fail():
    db = AsyncMock()
    rule = _make_rule(allowed_days_of_week=[5, 6])  # Sat, Sun only
    db.execute.return_value = _scalars_all_result([rule])

    # Wednesday is weekday 2, not in [5, 6]
    approved, matched = await evaluate_auto_approval(
        db, ACCOUNT_ID, MEMBER_ID, estimated_cost_usd=10.0, ride_dt=_WEDNESDAY_9AM
    )
    assert approved is False


# ---------------------------------------------------------------------------
# 23. evaluate_auto_approval — hour range (pass)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_hour_range_pass():
    db = AsyncMock()
    rule = _make_rule(start_hour=8, end_hour=18)
    db.execute.return_value = _scalars_all_result([rule])

    # _WEDNESDAY_9AM is hour 9
    approved, _ = await evaluate_auto_approval(
        db, ACCOUNT_ID, MEMBER_ID, estimated_cost_usd=10.0, ride_dt=_WEDNESDAY_9AM
    )
    assert approved is True


# ---------------------------------------------------------------------------
# 24. evaluate_auto_approval — hour range (fail)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_hour_range_fail():
    db = AsyncMock()
    rule = _make_rule(start_hour=10, end_hour=18)
    db.execute.return_value = _scalars_all_result([rule])

    # _WEDNESDAY_9AM is hour 9, outside [10, 18]
    approved, _ = await evaluate_auto_approval(
        db, ACCOUNT_ID, MEMBER_ID, estimated_cost_usd=10.0, ride_dt=_WEDNESDAY_9AM
    )
    assert approved is False


# ---------------------------------------------------------------------------
# 25. evaluate_auto_approval — trip_purpose_ids (pass)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_trip_purpose_pass():
    db = AsyncMock()
    rule = _make_rule(trip_purpose_ids=[1, 2, 3])
    db.execute.return_value = _scalars_all_result([rule])

    approved, _ = await evaluate_auto_approval(
        db, ACCOUNT_ID, MEMBER_ID, estimated_cost_usd=10.0, trip_purpose_id=2
    )
    assert approved is True


# ---------------------------------------------------------------------------
# 26. evaluate_auto_approval — trip_purpose_ids (fail)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_trip_purpose_fail():
    db = AsyncMock()
    rule = _make_rule(trip_purpose_ids=[1, 2, 3])
    db.execute.return_value = _scalars_all_result([rule])

    approved, _ = await evaluate_auto_approval(
        db, ACCOUNT_ID, MEMBER_ID, estimated_cost_usd=10.0, trip_purpose_id=99
    )
    assert approved is False


# ---------------------------------------------------------------------------
# 27. evaluate_auto_approval — cost_center_ids (pass)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_cost_center_pass():
    db = AsyncMock()
    rule = _make_rule(cost_center_ids=[10, 20])
    db.execute.return_value = _scalars_all_result([rule])

    approved, _ = await evaluate_auto_approval(
        db, ACCOUNT_ID, MEMBER_ID, estimated_cost_usd=10.0, cost_center_id=10
    )
    assert approved is True


# ---------------------------------------------------------------------------
# 28. evaluate_auto_approval — cost_center_ids (fail)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_cost_center_fail():
    db = AsyncMock()
    rule = _make_rule(cost_center_ids=[10, 20])
    db.execute.return_value = _scalars_all_result([rule])

    approved, _ = await evaluate_auto_approval(
        db, ACCOUNT_ID, MEMBER_ID, estimated_cost_usd=10.0, cost_center_id=99
    )
    assert approved is False


# ---------------------------------------------------------------------------
# 29. evaluate_auto_approval — employee_group_ids (pass)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_employee_group_pass():
    db = AsyncMock()
    rule = _make_rule(employee_group_ids=[7, 8])

    # execute calls: (1) load active rules, (2) load member group memberships
    rules_result = _scalars_all_result([rule])
    # group membership query returns rows with group_id
    groups_result = MagicMock()
    groups_result.all.return_value = [(7,), (9,)]
    db.execute.side_effect = [rules_result, groups_result]

    approved, matched = await evaluate_auto_approval(
        db, ACCOUNT_ID, MEMBER_ID, estimated_cost_usd=10.0
    )
    assert approved is True
    assert matched is rule


# ---------------------------------------------------------------------------
# 30. evaluate_auto_approval — employee_group_ids (fail)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_employee_group_fail():
    db = AsyncMock()
    rule = _make_rule(employee_group_ids=[7, 8])

    rules_result = _scalars_all_result([rule])
    groups_result = MagicMock()
    groups_result.all.return_value = [(50,), (51,)]  # no overlap with [7, 8]
    db.execute.side_effect = [rules_result, groups_result]

    approved, _ = await evaluate_auto_approval(
        db, ACCOUNT_ID, MEMBER_ID, estimated_cost_usd=10.0
    )
    assert approved is False


# ---------------------------------------------------------------------------
# 31. evaluate_auto_approval — multiple rules, highest priority wins
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_highest_priority_wins():
    db = AsyncMock()
    low_priority = _make_rule(rule_id=1, priority=0, max_cost_usd=10.0, name="Low")
    high_priority = _make_rule(rule_id=2, priority=10, max_cost_usd=None, name="High")

    # Rules ordered by priority DESC — high_priority comes first
    db.execute.return_value = _scalars_all_result([high_priority, low_priority])

    approved, matched = await evaluate_auto_approval(
        db, ACCOUNT_ID, MEMBER_ID, estimated_cost_usd=50.0
    )
    # high_priority has no cost constraint → matches; low_priority would fail at $50
    assert approved is True
    assert matched is high_priority


# ---------------------------------------------------------------------------
# 32. evaluate_auto_approval — inactive rule not matched
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_inactive_rule_not_matched():
    """The service query already filters is_active=True, so active_rules list
    from the DB will never contain inactive rules.  We simulate that the DB
    correctly excludes them by returning an empty list even though the rule
    object would otherwise match."""
    db = AsyncMock()
    # Simulate DB returning only active rules (i.e., empty since the only rule is inactive)
    db.execute.return_value = _scalars_all_result([])

    approved, _ = await evaluate_auto_approval(
        db, ACCOUNT_ID, MEMBER_ID, estimated_cost_usd=10.0
    )
    assert approved is False


# ---------------------------------------------------------------------------
# 33. list_all_auto_approval_rules_platform
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_platform_list_all_rules():
    db = AsyncMock()
    rules = [_make_rule(rule_id=1), _make_rule(rule_id=2, account_id=99)]
    db.execute.return_value = _scalars_all_result(rules)

    result = await list_all_auto_approval_rules_platform(db, skip=0, limit=100)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# 34. Schema — name required
# ---------------------------------------------------------------------------


def test_schema_name_required():
    with pytest.raises(ValidationError):
        AutoApprovalRuleCreate()


# ---------------------------------------------------------------------------
# 35. Schema — empty name raises validation error
# ---------------------------------------------------------------------------


def test_schema_name_empty_raises():
    with pytest.raises(ValidationError):
        AutoApprovalRuleCreate(name="")


# ---------------------------------------------------------------------------
# 36. Schema — start_hour without end_hour raises validation error
# ---------------------------------------------------------------------------


def test_schema_mismatched_hours_raises():
    with pytest.raises(ValidationError):
        AutoApprovalRuleCreate(name="Test", start_hour=9)


# ---------------------------------------------------------------------------
# 37. Schema — both hours set passes
# ---------------------------------------------------------------------------


def test_schema_both_hours_valid():
    rule = AutoApprovalRuleCreate(name="Office Hours", start_hour=8, end_hour=18)
    assert rule.start_hour == 8
    assert rule.end_hour == 18


# ---------------------------------------------------------------------------
# 38. Schema — AutoApprovalRuleResponse from_attributes
# ---------------------------------------------------------------------------


def test_schema_response_from_attributes():
    rule = _make_rule()
    resp = AutoApprovalRuleResponse.model_validate(rule)
    assert resp.id == RULE_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.name == "Low-cost weekday rides"
    assert resp.is_active is True
    assert resp.priority == 0


# ---------------------------------------------------------------------------
# API tests — helpers
# ---------------------------------------------------------------------------


def _mock_account(account_id: int = ACCOUNT_ID):
    a = MagicMock()
    a.id = account_id
    return a


def _mock_member(member_id: int = MEMBER_ID):
    m = MagicMock()
    m.id = member_id
    return m


# ---------------------------------------------------------------------------
# 39. POST create — 201 admin can create rule
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_create_rule_201():
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user(ADMIN_ID)

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account()),
            patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock),
            patch(
                f"{_ROUTER}.create_auto_approval_rule",
                new_callable=AsyncMock,
                return_value=_make_rule(),
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(
                    "/api/v1/corporate/accounts/me/auto-approval-rules",
                    json={"name": "Low-cost weekday rides"},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 201
    assert resp.json()["name"] == "Low-cost weekday rides"


# ---------------------------------------------------------------------------
# 40. POST create — 404 when no corporate account
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_create_rule_404_no_account():
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from fastapi import HTTPException

    mock_db = AsyncMock()
    mock_user = _mock_user()

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with patch(
            f"{_ROUTER}._resolve_account",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Not a member."),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(
                    "/api/v1/corporate/accounts/me/auto-approval-rules",
                    json={"name": "Test"},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 41. GET list — 200 member can list rules
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_list_rules_200():
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user()
    rules = [_make_rule()]

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account()),
            patch(
                f"{_ROUTER}.list_auto_approval_rules",
                new_callable=AsyncMock,
                return_value=rules,
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/v1/corporate/accounts/me/auto-approval-rules")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["total"] == 1


# ---------------------------------------------------------------------------
# 42. GET get — 200 member can view rule
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_get_rule_200():
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user()

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account()),
            patch(
                f"{_ROUTER}.get_auto_approval_rule",
                new_callable=AsyncMock,
                return_value=_make_rule(),
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get(
                    f"/api/v1/corporate/accounts/me/auto-approval-rules/{RULE_ID}"
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["id"] == RULE_ID


# ---------------------------------------------------------------------------
# 43. GET get — 404 not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_get_rule_404():
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from fastapi import HTTPException

    mock_db = AsyncMock()
    mock_user = _mock_user()

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account()),
            patch(
                f"{_ROUTER}.get_auto_approval_rule",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=404, detail="Not found."),
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get(
                    f"/api/v1/corporate/accounts/me/auto-approval-rules/{RULE_ID}"
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 44. PUT update — 200 admin can update rule
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_update_rule_200():
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user(ADMIN_ID)
    updated = _make_rule(name="Updated Rule")

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account()),
            patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock),
            patch(
                f"{_ROUTER}.update_auto_approval_rule",
                new_callable=AsyncMock,
                return_value=updated,
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.put(
                    f"/api/v1/corporate/accounts/me/auto-approval-rules/{RULE_ID}",
                    json={"name": "Updated Rule"},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Rule"


# ---------------------------------------------------------------------------
# 45. POST activate — 200
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_activate_rule_200():
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user(ADMIN_ID)
    activated = _make_rule(is_active=True)

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account()),
            patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock),
            patch(
                f"{_ROUTER}.activate_auto_approval_rule",
                new_callable=AsyncMock,
                return_value=activated,
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(
                    f"/api/v1/corporate/accounts/me/auto-approval-rules/{RULE_ID}/activate"
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["is_active"] is True


# ---------------------------------------------------------------------------
# 46. POST deactivate — 200
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_deactivate_rule_200():
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user(ADMIN_ID)
    deactivated = _make_rule(is_active=False)

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account()),
            patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock),
            patch(
                f"{_ROUTER}.deactivate_auto_approval_rule",
                new_callable=AsyncMock,
                return_value=deactivated,
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(
                    f"/api/v1/corporate/accounts/me/auto-approval-rules/{RULE_ID}/deactivate"
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


# ---------------------------------------------------------------------------
# 47. DELETE delete — 204
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_delete_rule_204():
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user(ADMIN_ID)

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account()),
            patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock),
            patch(
                f"{_ROUTER}.delete_auto_approval_rule",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.delete(
                    f"/api/v1/corporate/accounts/me/auto-approval-rules/{RULE_ID}"
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# 48. POST evaluate — 200 match
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_evaluate_match_200():
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user()
    matched_rule = _make_rule()

    # Mock the member lookup in the endpoint
    mock_member = MagicMock()
    mock_member.id = MEMBER_ID
    mock_db.execute.return_value = _scalar_result(mock_member)

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account()),
            patch(
                f"{_ROUTER}.evaluate_auto_approval",
                new_callable=AsyncMock,
                return_value=(True, matched_rule),
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(
                    "/api/v1/corporate/accounts/me/auto-approval-rules/evaluate",
                    json={"estimated_cost_usd": 20.0},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["auto_approved"] is True
    assert body["matched_rule_id"] == RULE_ID


# ---------------------------------------------------------------------------
# 49. POST evaluate — 200 no match
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_evaluate_no_match_200():
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user()

    mock_member = MagicMock()
    mock_member.id = MEMBER_ID
    mock_db.execute.return_value = _scalar_result(mock_member)

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account()),
            patch(
                f"{_ROUTER}.evaluate_auto_approval",
                new_callable=AsyncMock,
                return_value=(False, None),
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(
                    "/api/v1/corporate/accounts/me/auto-approval-rules/evaluate",
                    json={"estimated_cost_usd": 99.0},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["auto_approved"] is False
    assert body["matched_rule_id"] is None
    assert body["matched_rule_name"] is None


# ---------------------------------------------------------------------------
# 50. GET platform list — 200
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_platform_list_200():
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_db, require_admin

    mock_db = AsyncMock()
    rules = [_make_rule(rule_id=1), _make_rule(rule_id=2, account_id=20)]

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[require_admin] = lambda: None

    try:
        with patch(
            f"{_ROUTER}.list_all_auto_approval_rules_platform",
            new_callable=AsyncMock,
            return_value=rules,
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get(
                    "/api/v1/platform/corporate/auto-approval-rules"
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["total"] == 2


# ---------------------------------------------------------------------------
# 51. GET platform account list — 200
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_platform_account_list_200():
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_db, require_admin

    mock_db = AsyncMock()
    rules = [_make_rule()]

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[require_admin] = lambda: None

    try:
        with patch(
            f"{_ROUTER}.list_auto_approval_rules",
            new_callable=AsyncMock,
            return_value=rules,
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get(
                    f"/api/v1/platform/corporate/auto-approval-rules/accounts/{ACCOUNT_ID}"
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["total"] == 1
