"""Tests for Corporate Department-Level Ride Policies.

Service layer (async, mocked DB):
  1.  set_department_policy — create new policy (department has no existing)
  2.  set_department_policy — upsert replaces existing policy
  3.  set_department_policy — 403 when not account admin
  4.  set_department_policy — 404 when department not found
  5.  get_department_policy — returns row when exists
  6.  get_department_policy — returns None when not found
  7.  update_department_policy — success updates fields
  8.  update_department_policy — 404 when no policy exists
  9.  delete_department_policy — success hard-deletes row
  10. delete_department_policy — 404 when no policy exists
  11. activate_department_policy — success sets is_active=True
  12. activate_department_policy — 409 when already active
  13. deactivate_department_policy — success sets is_active=False
  14. deactivate_department_policy — 409 when already inactive
  15. list_department_policies — returns all policies for account
  16. list_department_policies — is_active=True filter
  17. list_department_policies — is_active=False filter
  18. get_effective_policy_for_member — 404 when member not found
  19. get_effective_policy_for_member — account policy only (no dept policies)
  20. get_effective_policy_for_member — single dept policy overrides account
  21. get_effective_policy_for_member — two dept policies merge (most restrictive)
  22. get_effective_policy_for_member — require_purpose: True wins over False
  23. get_effective_policy_for_member — business_hours_only: True wins over False
  24. get_effective_policy_for_member — max_per_ride_usd: lower value wins
  25. get_effective_policy_for_member — allowed_vehicle_categories intersection
  26. get_effective_policy_for_member — approved_purposes intersection
  27. get_effective_policy_for_member — member override wins over dept policy
  28. get_effective_policy_for_member — inactive member override not applied
  29. get_effective_policy_for_member — inactive dept policy not applied
  30. get_effective_policy_for_member — no account policy, dept policy used as base
  31. list_all_department_policies_platform — returns all policies newest-first

Schema validation:
  32. DepartmentRidePolicySet — all fields optional (empty body valid)
  33. DepartmentRidePolicySet — max_per_ride_usd must be >= 0
  34. DepartmentRidePolicySet — notes max 500 chars enforced
  35. DepartmentRidePolicyResponse — from_attributes construction
  36. EffectiveDepartmentPolicyResponse — construction with empty dept list

API layer (service functions patched):
  37. PUT set — 200 admin upserts department policy
  38. PUT set — 404 when not corporate member
  39. GET get — 200 member gets department policy
  40. GET get — 404 when no policy set
  41. PATCH update — 200 admin partial update
  42. DELETE delete — 204 admin deletes policy
  43. POST activate — 200 admin activates policy
  44. POST deactivate — 200 admin deactivates policy
  45. GET list — 200 member lists account policies
  46. GET effective — 200 member gets own effective policy
  47. GET platform list — 200 platform-admin lists all
  48. GET platform account list — 200 platform-admin account-specific list
  49. GET platform effective — 200 platform-admin effective policy for member
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_department_ride_policy import CorporateDepartmentRidePolicy
from app.schemas.corporate_department_ride_policy import (
    DepartmentRidePolicyListResponse,
    DepartmentRidePolicyResponse,
    DepartmentRidePolicySet,
    DepartmentRidePolicyUpdate,
    EffectiveDepartmentPolicyResponse,
)
from app.services.corporate_department_ride_policy import (
    activate_department_policy,
    deactivate_department_policy,
    delete_department_policy,
    get_department_policy,
    get_effective_policy_for_member,
    list_all_department_policies_platform,
    list_department_policies,
    set_department_policy,
    update_department_policy,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 10
OTHER_ACCOUNT_ID = 99
ADMIN_ID = 2
USER_ID = 1
MEMBER_ID = 5
DEPT_ID = 20
OTHER_DEPT_ID = 21
POLICY_ID = 42

_SERVICE = "app.services.corporate_department_ride_policy"
_ROUTER = "app.api.v1.corporate_department_ride_policy"

_NOW = datetime(2026, 4, 16, 9, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_policy(
    policy_id: int = POLICY_ID,
    account_id: int = ACCOUNT_ID,
    department_id: int = DEPT_ID,
    is_active: bool = True,
    allowed_vehicle_categories=None,
    max_per_ride_usd=None,
    require_purpose=None,
    approved_purposes=None,
    business_hours_only=None,
    notes=None,
    set_by_id: int | None = ADMIN_ID,
) -> CorporateDepartmentRidePolicy:
    """Build a minimal CorporateDepartmentRidePolicy for testing."""
    p = CorporateDepartmentRidePolicy()
    p.id = policy_id
    p.account_id = account_id
    p.department_id = department_id
    p.is_active = is_active
    p.allowed_vehicle_categories = allowed_vehicle_categories
    p.max_per_ride_usd = max_per_ride_usd
    p.require_purpose = require_purpose
    p.approved_purposes = approved_purposes
    p.business_hours_only = business_hours_only
    p.notes = notes
    p.set_by_id = set_by_id
    p.created_at = _NOW
    p.updated_at = _NOW
    return p


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


def _make_db(execute_side_effects: list) -> AsyncMock:
    """Build a mock AsyncSession that returns given results on successive execute calls."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute_side_effects)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db


def _make_account(account_id: int = ACCOUNT_ID):
    a = MagicMock()
    a.id = account_id
    return a


def _make_dept(dept_id: int = DEPT_ID, account_id: int = ACCOUNT_ID):
    d = MagicMock()
    d.id = dept_id
    d.account_id = account_id
    return d


def _make_member(member_id: int = MEMBER_ID, user_id: int = USER_ID, account_id: int = ACCOUNT_ID):
    m = MagicMock()
    m.id = member_id
    m.user_id = user_id
    m.account_id = account_id
    return m


def _make_ride_policy(
    account_id=ACCOUNT_ID,
    allowed_vehicle_categories=None,
    max_per_ride_usd=None,
    max_per_member_monthly_usd=None,
    require_purpose=False,
    approved_purposes=None,
    business_hours_only=False,
):
    rp = MagicMock()
    rp.account_id = account_id
    rp.allowed_vehicle_categories = allowed_vehicle_categories
    rp.max_per_ride_usd = max_per_ride_usd
    rp.max_per_member_monthly_usd = max_per_member_monthly_usd
    rp.require_purpose = require_purpose
    rp.approved_purposes = approved_purposes
    rp.business_hours_only = business_hours_only
    return rp


def _make_override(
    member_id=MEMBER_ID,
    is_active=True,
    allowed_vehicle_categories=None,
    max_per_ride_usd=None,
    require_purpose=None,
    approved_purposes=None,
    business_hours_only=None,
):
    o = MagicMock()
    o.member_id = member_id
    o.is_active = is_active
    o.allowed_vehicle_categories = allowed_vehicle_categories
    o.max_per_ride_usd = max_per_ride_usd
    o.require_purpose = require_purpose
    o.approved_purposes = approved_purposes
    o.business_hours_only = business_hours_only
    return o


def _make_dept_member(user_id=USER_ID, department_id=DEPT_ID):
    dm = MagicMock()
    dm.user_id = user_id
    dm.department_id = department_id
    return dm


# ---------------------------------------------------------------------------
# Service layer tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_department_policy_creates_new():
    """set_department_policy creates a new row when none exists."""
    admin_member = MagicMock()
    admin_member.role = "admin"

    db = _make_db([
        _scalar_result(_make_account()),       # _get_account_or_404
        _scalar_result(admin_member),          # _require_account_admin
        _scalar_result(_make_dept()),          # _get_department_or_404
        _scalar_result(None),                  # get_department_policy (no existing)
    ])

    data = DepartmentRidePolicySet(max_per_ride_usd=Decimal("30.00"), require_purpose=True)

    async def _refresh(obj):
        obj.id = POLICY_ID

    db.refresh = AsyncMock(side_effect=_refresh)

    result = await set_department_policy(db, ACCOUNT_ID, DEPT_ID, data, ADMIN_ID)

    db.add.assert_called_once()
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_set_department_policy_replaces_existing():
    """set_department_policy replaces an existing policy row (upsert)."""
    admin_member = MagicMock()
    admin_member.role = "admin"
    existing = _make_policy(max_per_ride_usd=Decimal("20.00"))

    db = _make_db([
        _scalar_result(_make_account()),
        _scalar_result(admin_member),
        _scalar_result(_make_dept()),
        _scalar_result(existing),             # get_department_policy returns existing
    ])

    data = DepartmentRidePolicySet(max_per_ride_usd=Decimal("50.00"), is_active=True)
    result = await set_department_policy(db, ACCOUNT_ID, DEPT_ID, data, ADMIN_ID)

    db.commit.assert_awaited()
    assert result.max_per_ride_usd == Decimal("50.00")


@pytest.mark.asyncio
async def test_set_department_policy_403_not_admin():
    """set_department_policy raises HTTP 403 when caller is not admin."""
    db = _make_db([
        _scalar_result(_make_account()),
        _scalar_result(None),                 # no admin membership → 403
    ])

    data = DepartmentRidePolicySet()
    with pytest.raises(HTTPException) as exc:
        await set_department_policy(db, ACCOUNT_ID, DEPT_ID, data, USER_ID)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_set_department_policy_404_department_not_found():
    """set_department_policy raises HTTP 404 when department not found."""
    admin_member = MagicMock()

    db = _make_db([
        _scalar_result(_make_account()),
        _scalar_result(admin_member),         # admin check passes
        _scalar_result(None),                 # department not found → 404
    ])

    data = DepartmentRidePolicySet()
    with pytest.raises(HTTPException) as exc:
        await set_department_policy(db, ACCOUNT_ID, DEPT_ID, data, ADMIN_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_department_policy_returns_row():
    """get_department_policy returns the policy when it exists."""
    policy = _make_policy()
    db = _make_db([_scalar_result(policy)])
    result = await get_department_policy(db, ACCOUNT_ID, DEPT_ID)
    assert result is policy


@pytest.mark.asyncio
async def test_get_department_policy_returns_none_when_missing():
    """get_department_policy returns None when no row exists."""
    db = _make_db([_scalar_result(None)])
    result = await get_department_policy(db, ACCOUNT_ID, DEPT_ID)
    assert result is None


@pytest.mark.asyncio
async def test_update_department_policy_success():
    """update_department_policy updates only the provided fields."""
    admin_member = MagicMock()
    policy = _make_policy(max_per_ride_usd=Decimal("20.00"), require_purpose=False)

    db = _make_db([
        _scalar_result(admin_member),         # _require_account_admin
        _scalar_result(policy),               # _get_policy_or_404 via get_department_policy
    ])

    data = DepartmentRidePolicyUpdate(max_per_ride_usd=Decimal("35.00"), require_purpose=True)
    result = await update_department_policy(db, ACCOUNT_ID, DEPT_ID, data, ADMIN_ID)

    db.commit.assert_awaited()
    assert result.max_per_ride_usd == Decimal("35.00")
    assert result.require_purpose is True


@pytest.mark.asyncio
async def test_update_department_policy_404_not_found():
    """update_department_policy raises HTTP 404 when no policy exists."""
    admin_member = MagicMock()

    db = _make_db([
        _scalar_result(admin_member),
        _scalar_result(None),                 # policy not found → 404
    ])

    data = DepartmentRidePolicyUpdate(notes="Update me")
    with pytest.raises(HTTPException) as exc:
        await update_department_policy(db, ACCOUNT_ID, DEPT_ID, data, ADMIN_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_department_policy_success():
    """delete_department_policy hard-deletes the row."""
    admin_member = MagicMock()
    policy = _make_policy()

    db = _make_db([
        _scalar_result(admin_member),
        _scalar_result(policy),
    ])

    await delete_department_policy(db, ACCOUNT_ID, DEPT_ID, ADMIN_ID)

    db.delete.assert_awaited_with(policy)
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_delete_department_policy_404():
    """delete_department_policy raises 404 when no policy found."""
    admin_member = MagicMock()

    db = _make_db([
        _scalar_result(admin_member),
        _scalar_result(None),
    ])

    with pytest.raises(HTTPException) as exc:
        await delete_department_policy(db, ACCOUNT_ID, DEPT_ID, ADMIN_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_activate_department_policy_success():
    """activate_department_policy sets is_active=True."""
    admin_member = MagicMock()
    policy = _make_policy(is_active=False)

    db = _make_db([
        _scalar_result(admin_member),
        _scalar_result(policy),
    ])

    result = await activate_department_policy(db, ACCOUNT_ID, DEPT_ID, ADMIN_ID)

    db.commit.assert_awaited()
    assert result.is_active is True


@pytest.mark.asyncio
async def test_activate_department_policy_409_already_active():
    """activate_department_policy raises 409 when already active."""
    admin_member = MagicMock()
    policy = _make_policy(is_active=True)

    db = _make_db([
        _scalar_result(admin_member),
        _scalar_result(policy),
    ])

    with pytest.raises(HTTPException) as exc:
        await activate_department_policy(db, ACCOUNT_ID, DEPT_ID, ADMIN_ID)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_deactivate_department_policy_success():
    """deactivate_department_policy sets is_active=False."""
    admin_member = MagicMock()
    policy = _make_policy(is_active=True)

    db = _make_db([
        _scalar_result(admin_member),
        _scalar_result(policy),
    ])

    result = await deactivate_department_policy(db, ACCOUNT_ID, DEPT_ID, ADMIN_ID)

    db.commit.assert_awaited()
    assert result.is_active is False


@pytest.mark.asyncio
async def test_deactivate_department_policy_409_already_inactive():
    """deactivate_department_policy raises 409 when already inactive."""
    admin_member = MagicMock()
    policy = _make_policy(is_active=False)

    db = _make_db([
        _scalar_result(admin_member),
        _scalar_result(policy),
    ])

    with pytest.raises(HTTPException) as exc:
        await deactivate_department_policy(db, ACCOUNT_ID, DEPT_ID, ADMIN_ID)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_list_department_policies_returns_all():
    """list_department_policies returns all policies for the account."""
    p1 = _make_policy(policy_id=1, department_id=20)
    p2 = _make_policy(policy_id=2, department_id=21)

    db = _make_db([_scalars_all_result([p1, p2])])
    result = await list_department_policies(db, ACCOUNT_ID)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_department_policies_active_filter():
    """list_department_policies with is_active=True returns only active."""
    active = _make_policy(is_active=True)

    db = _make_db([_scalars_all_result([active])])
    result = await list_department_policies(db, ACCOUNT_ID, is_active=True)
    assert all(p.is_active for p in result)


@pytest.mark.asyncio
async def test_list_department_policies_inactive_filter():
    """list_department_policies with is_active=False returns only inactive."""
    inactive = _make_policy(is_active=False)

    db = _make_db([_scalars_all_result([inactive])])
    result = await list_department_policies(db, ACCOUNT_ID, is_active=False)
    assert all(not p.is_active for p in result)


@pytest.mark.asyncio
async def test_get_effective_policy_404_member_not_found():
    """get_effective_policy_for_member raises 404 when member not found."""
    db = _make_db([_scalar_result(None)])  # member query returns nothing

    with pytest.raises(HTTPException) as exc:
        await get_effective_policy_for_member(db, ACCOUNT_ID, MEMBER_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_effective_policy_account_policy_only():
    """get_effective_policy_for_member returns account policy when no dept policies."""
    member = _make_member()
    account_policy = _make_ride_policy(
        max_per_ride_usd=Decimal("25.00"), require_purpose=True
    )

    db = _make_db([
        _scalar_result(member),               # member lookup
        _scalar_result(account_policy),       # account ride policy
        _scalars_all_result([]),              # dept memberships (none)
        _scalar_result(None),                 # member override (none)
    ])

    result = await get_effective_policy_for_member(db, ACCOUNT_ID, MEMBER_ID)

    assert result.max_per_ride_usd == Decimal("25.00")
    assert result.require_purpose is True
    assert result.department_ids_applied == []
    assert result.has_member_override is False


@pytest.mark.asyncio
async def test_get_effective_policy_single_dept_policy():
    """get_effective_policy_for_member applies a single dept policy over account base."""
    member = _make_member()
    account_policy = _make_ride_policy(max_per_ride_usd=Decimal("50.00"))
    dept_member = _make_dept_member()
    dept_policy = _make_policy(
        department_id=DEPT_ID,
        max_per_ride_usd=Decimal("30.00"),  # more restrictive
        is_active=True,
    )

    db = _make_db([
        _scalar_result(member),
        _scalar_result(account_policy),
        _scalars_all_result([dept_member]),          # dept memberships
        _scalars_all_result([dept_policy]),           # dept policies
        _scalar_result(None),                         # member override (none)
    ])

    result = await get_effective_policy_for_member(db, ACCOUNT_ID, MEMBER_ID)

    assert result.max_per_ride_usd == Decimal("30.00")
    assert DEPT_ID in result.department_ids_applied


@pytest.mark.asyncio
async def test_get_effective_policy_two_dept_policies_merge():
    """get_effective_policy_for_member merges two dept policies (most restrictive)."""
    member = _make_member()
    account_policy = _make_ride_policy(max_per_ride_usd=Decimal("100.00"))
    dm1 = _make_dept_member(department_id=DEPT_ID)
    dm2 = _make_dept_member(department_id=OTHER_DEPT_ID)
    # Dept 1: max $40
    dp1 = _make_policy(department_id=DEPT_ID, max_per_ride_usd=Decimal("40.00"), is_active=True)
    # Dept 2: max $60 — less restrictive than dept 1
    dp2 = _make_policy(policy_id=43, department_id=OTHER_DEPT_ID, max_per_ride_usd=Decimal("60.00"), is_active=True)

    db = _make_db([
        _scalar_result(member),
        _scalar_result(account_policy),
        _scalars_all_result([dm1, dm2]),
        _scalars_all_result([dp1, dp2]),
        _scalar_result(None),
    ])

    result = await get_effective_policy_for_member(db, ACCOUNT_ID, MEMBER_ID)

    # min(40, 60) = 40 is most restrictive
    assert result.max_per_ride_usd == Decimal("40.00")


@pytest.mark.asyncio
async def test_get_effective_policy_require_purpose_true_wins():
    """require_purpose=True from any dept policy wins over False."""
    member = _make_member()
    account_policy = _make_ride_policy(require_purpose=False)
    dm = _make_dept_member()
    dp = _make_policy(department_id=DEPT_ID, require_purpose=True, is_active=True)

    db = _make_db([
        _scalar_result(member),
        _scalar_result(account_policy),
        _scalars_all_result([dm]),
        _scalars_all_result([dp]),
        _scalar_result(None),
    ])

    result = await get_effective_policy_for_member(db, ACCOUNT_ID, MEMBER_ID)
    assert result.require_purpose is True


@pytest.mark.asyncio
async def test_get_effective_policy_business_hours_true_wins():
    """business_hours_only=True from any dept policy wins over False."""
    member = _make_member()
    account_policy = _make_ride_policy(business_hours_only=False)
    dm = _make_dept_member()
    dp = _make_policy(department_id=DEPT_ID, business_hours_only=True, is_active=True)

    db = _make_db([
        _scalar_result(member),
        _scalar_result(account_policy),
        _scalars_all_result([dm]),
        _scalars_all_result([dp]),
        _scalar_result(None),
    ])

    result = await get_effective_policy_for_member(db, ACCOUNT_ID, MEMBER_ID)
    assert result.business_hours_only is True


@pytest.mark.asyncio
async def test_get_effective_policy_max_per_ride_lower_wins():
    """Lower max_per_ride_usd wins when merging two department policies."""
    member = _make_member()
    account_policy = _make_ride_policy()
    dm1 = _make_dept_member(department_id=DEPT_ID)
    dm2 = _make_dept_member(department_id=OTHER_DEPT_ID)
    dp1 = _make_policy(department_id=DEPT_ID, max_per_ride_usd=Decimal("15.00"), is_active=True)
    dp2 = _make_policy(policy_id=43, department_id=OTHER_DEPT_ID, max_per_ride_usd=Decimal("25.00"), is_active=True)

    db = _make_db([
        _scalar_result(member),
        _scalar_result(account_policy),
        _scalars_all_result([dm1, dm2]),
        _scalars_all_result([dp1, dp2]),
        _scalar_result(None),
    ])

    result = await get_effective_policy_for_member(db, ACCOUNT_ID, MEMBER_ID)
    assert result.max_per_ride_usd == Decimal("15.00")


@pytest.mark.asyncio
async def test_get_effective_policy_vehicle_categories_intersection():
    """allowed_vehicle_categories: intersection of all dept policy lists."""
    member = _make_member()
    account_policy = _make_ride_policy(allowed_vehicle_categories=["standard", "xl", "black"])
    dm1 = _make_dept_member(department_id=DEPT_ID)
    dm2 = _make_dept_member(department_id=OTHER_DEPT_ID)
    dp1 = _make_policy(department_id=DEPT_ID, allowed_vehicle_categories=["standard", "xl"], is_active=True)
    dp2 = _make_policy(policy_id=43, department_id=OTHER_DEPT_ID, allowed_vehicle_categories=["standard", "black"], is_active=True)

    db = _make_db([
        _scalar_result(member),
        _scalar_result(account_policy),
        _scalars_all_result([dm1, dm2]),
        _scalars_all_result([dp1, dp2]),
        _scalar_result(None),
    ])

    result = await get_effective_policy_for_member(db, ACCOUNT_ID, MEMBER_ID)
    # Intersection of ["standard","xl"] and ["standard","black"] = ["standard"]
    assert result.allowed_vehicle_categories == ["standard"]


@pytest.mark.asyncio
async def test_get_effective_policy_approved_purposes_intersection():
    """approved_purposes: intersection of all dept policy lists."""
    member = _make_member()
    account_policy = _make_ride_policy(approved_purposes=["business", "conference", "airport"])
    dm1 = _make_dept_member(department_id=DEPT_ID)
    dm2 = _make_dept_member(department_id=OTHER_DEPT_ID)
    dp1 = _make_policy(department_id=DEPT_ID, approved_purposes=["business", "conference"], is_active=True)
    dp2 = _make_policy(policy_id=43, department_id=OTHER_DEPT_ID, approved_purposes=["business", "airport"], is_active=True)

    db = _make_db([
        _scalar_result(member),
        _scalar_result(account_policy),
        _scalars_all_result([dm1, dm2]),
        _scalars_all_result([dp1, dp2]),
        _scalar_result(None),
    ])

    result = await get_effective_policy_for_member(db, ACCOUNT_ID, MEMBER_ID)
    assert result.approved_purposes == ["business"]


@pytest.mark.asyncio
async def test_get_effective_policy_member_override_wins():
    """Member override takes highest precedence over dept policy."""
    member = _make_member()
    account_policy = _make_ride_policy(max_per_ride_usd=Decimal("20.00"))
    dm = _make_dept_member()
    dp = _make_policy(department_id=DEPT_ID, max_per_ride_usd=Decimal("15.00"), is_active=True)
    # Member override sets higher cap than department
    override = _make_override(max_per_ride_usd=Decimal("75.00"), is_active=True)

    db = _make_db([
        _scalar_result(member),
        _scalar_result(account_policy),
        _scalars_all_result([dm]),
        _scalars_all_result([dp]),
        _scalar_result(override),
    ])

    result = await get_effective_policy_for_member(db, ACCOUNT_ID, MEMBER_ID)
    # Override wins: $75
    assert result.max_per_ride_usd == Decimal("75.00")
    assert result.has_member_override is True
    assert result.member_override_is_active is True


@pytest.mark.asyncio
async def test_get_effective_policy_inactive_override_not_applied():
    """Inactive member override does not affect effective policy."""
    member = _make_member()
    account_policy = _make_ride_policy(max_per_ride_usd=Decimal("20.00"))
    dm = _make_dept_member()
    dp = _make_policy(department_id=DEPT_ID, max_per_ride_usd=Decimal("10.00"), is_active=True)
    override = _make_override(max_per_ride_usd=Decimal("75.00"), is_active=False)

    db = _make_db([
        _scalar_result(member),
        _scalar_result(account_policy),
        _scalars_all_result([dm]),
        _scalars_all_result([dp]),
        _scalar_result(override),
    ])

    result = await get_effective_policy_for_member(db, ACCOUNT_ID, MEMBER_ID)
    # Inactive override not applied; dept wins (min of 20, 10)
    assert result.max_per_ride_usd == Decimal("10.00")
    assert result.has_member_override is True
    assert result.member_override_is_active is False


@pytest.mark.asyncio
async def test_get_effective_policy_inactive_dept_policy_not_applied():
    """Inactive department policy is excluded from resolution."""
    member = _make_member()
    account_policy = _make_ride_policy(max_per_ride_usd=Decimal("50.00"))
    dm = _make_dept_member()
    # Policy exists but is inactive — service queries active only, returns empty list
    db = _make_db([
        _scalar_result(member),
        _scalar_result(account_policy),
        _scalars_all_result([dm]),          # dept membership found
        _scalars_all_result([]),            # active dept policies: none
        _scalar_result(None),              # member override: none
    ])

    result = await get_effective_policy_for_member(db, ACCOUNT_ID, MEMBER_ID)
    assert result.max_per_ride_usd == Decimal("50.00")
    assert result.department_ids_applied == []


@pytest.mark.asyncio
async def test_get_effective_policy_no_account_policy():
    """get_effective_policy_for_member works with no account-level policy set."""
    member = _make_member()
    dm = _make_dept_member()
    dp = _make_policy(department_id=DEPT_ID, max_per_ride_usd=Decimal("40.00"), require_purpose=True, is_active=True)

    db = _make_db([
        _scalar_result(member),
        _scalar_result(None),              # no account policy
        _scalars_all_result([dm]),
        _scalars_all_result([dp]),
        _scalar_result(None),
    ])

    result = await get_effective_policy_for_member(db, ACCOUNT_ID, MEMBER_ID)
    assert result.max_per_ride_usd == Decimal("40.00")
    assert result.require_purpose is True


@pytest.mark.asyncio
async def test_list_all_department_policies_platform():
    """list_all_department_policies_platform returns newest-first."""
    p1 = _make_policy(policy_id=1)
    p2 = _make_policy(policy_id=2)

    db = _make_db([_scalars_all_result([p2, p1])])  # newest first
    result = await list_all_department_policies_platform(db)
    assert len(result) == 2
    assert result[0].id == 2


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_department_ride_policy_set_all_optional():
    """DepartmentRidePolicySet accepts an empty body — all fields optional."""
    data = DepartmentRidePolicySet()
    assert data.allowed_vehicle_categories is None
    assert data.max_per_ride_usd is None
    assert data.require_purpose is None
    assert data.is_active is True


def test_department_ride_policy_set_max_per_ride_non_negative():
    """DepartmentRidePolicySet rejects negative max_per_ride_usd."""
    with pytest.raises(ValidationError):
        DepartmentRidePolicySet(max_per_ride_usd=Decimal("-1.00"))


def test_department_ride_policy_set_notes_max_500():
    """DepartmentRidePolicySet rejects notes longer than 500 chars."""
    with pytest.raises(ValidationError):
        DepartmentRidePolicySet(notes="x" * 501)


def test_department_ride_policy_response_from_attributes():
    """DepartmentRidePolicyResponse constructs from ORM object."""
    policy = _make_policy(
        max_per_ride_usd=Decimal("30.00"),
        require_purpose=True,
        notes="Sales team",
    )
    resp = DepartmentRidePolicyResponse.model_validate(policy)
    assert resp.id == POLICY_ID
    assert resp.department_id == DEPT_ID
    assert resp.max_per_ride_usd == Decimal("30.00")
    assert resp.require_purpose is True
    assert resp.notes == "Sales team"


def test_effective_department_policy_response_empty_dept_list():
    """EffectiveDepartmentPolicyResponse constructs with empty department list."""
    resp = EffectiveDepartmentPolicyResponse(
        member_id=MEMBER_ID,
        account_id=ACCOUNT_ID,
        department_ids_applied=[],
        has_member_override=False,
        member_override_is_active=None,
        allowed_vehicle_categories=None,
        max_per_ride_usd=None,
        max_per_member_monthly_usd=None,
        require_purpose=False,
        approved_purposes=None,
        business_hours_only=False,
    )
    assert resp.department_ids_applied == []
    assert resp.has_member_override is False


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

_DEPT_URL = f"/api/v1/corporate/accounts/me/departments/{DEPT_ID}/ride-policy"
_LIST_URL = "/api/v1/corporate/accounts/me/department-ride-policies"
_EFFECTIVE_URL = "/api/v1/corporate/accounts/me/effective-department-policy"
_PLATFORM_LIST_URL = "/api/v1/platform/corporate/department-ride-policies"
_PLATFORM_ACCT_URL = f"/api/v1/platform/corporate/accounts/{ACCOUNT_ID}/department-ride-policies"
_PLATFORM_EFFECTIVE_URL = (
    f"/api/v1/platform/corporate/accounts/{ACCOUNT_ID}/members/{MEMBER_ID}/effective-department-policy"
)

_MOCK_EFFECTIVE_DICT = {
    "member_id": MEMBER_ID,
    "account_id": ACCOUNT_ID,
    "department_ids_applied": [],
    "has_member_override": False,
    "member_override_is_active": None,
    "allowed_vehicle_categories": None,
    "max_per_ride_usd": None,
    "max_per_member_monthly_usd": None,
    "require_purpose": False,
    "approved_purposes": None,
    "business_hours_only": False,
}


def _mock_user(is_admin=False):
    u = MagicMock()
    u.id = ADMIN_ID if is_admin else USER_ID
    u.is_superuser = is_admin
    return u


def _mock_account_obj():
    a = MagicMock()
    a.id = ACCOUNT_ID
    return a


@pytest.mark.anyio
async def test_api_upsert_department_policy_200():
    """PUT /departments/{id}/ride-policy → 200 for admin."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user(is_admin=True)

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account_obj()),
            patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock),
            patch(f"{_ROUTER}.set_department_policy", new_callable=AsyncMock, return_value=_make_policy()),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.put(_DEPT_URL, json={})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_api_upsert_not_corporate_member_404():
    """PUT /departments/{id}/ride-policy → 404 when not a corporate member."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

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
                resp = await ac.put(_DEPT_URL, json={})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


@pytest.mark.anyio
async def test_api_get_policy_200():
    """GET /departments/{id}/ride-policy → 200 for member."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user()

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account_obj()),
            patch(f"{_ROUTER}.get_department_policy", new_callable=AsyncMock, return_value=_make_policy()),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get(_DEPT_URL)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_api_get_policy_404_not_set():
    """GET /departments/{id}/ride-policy → 404 when no policy set."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user()

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account_obj()),
            patch(f"{_ROUTER}.get_department_policy", new_callable=AsyncMock, return_value=None),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get(_DEPT_URL)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


@pytest.mark.anyio
async def test_api_patch_policy_200():
    """PATCH /departments/{id}/ride-policy → 200 for admin."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user(is_admin=True)

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account_obj()),
            patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock),
            patch(f"{_ROUTER}.update_department_policy", new_callable=AsyncMock, return_value=_make_policy(notes="updated")),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.patch(_DEPT_URL, json={"notes": "updated"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_api_delete_policy_204():
    """DELETE /departments/{id}/ride-policy → 204 for admin."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user(is_admin=True)

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account_obj()),
            patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock),
            patch(f"{_ROUTER}.delete_department_policy", new_callable=AsyncMock, return_value=None),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.delete(_DEPT_URL)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 204


@pytest.mark.anyio
async def test_api_activate_policy_200():
    """POST .../activate → 200 for admin."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user(is_admin=True)

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account_obj()),
            patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock),
            patch(f"{_ROUTER}.activate_department_policy", new_callable=AsyncMock, return_value=_make_policy(is_active=True)),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(f"{_DEPT_URL}/activate")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_api_deactivate_policy_200():
    """POST .../deactivate → 200 for admin."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user(is_admin=True)

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account_obj()),
            patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock),
            patch(f"{_ROUTER}.deactivate_department_policy", new_callable=AsyncMock, return_value=_make_policy(is_active=False)),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(f"{_DEPT_URL}/deactivate")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_api_list_policies_200():
    """GET /department-ride-policies → 200 returns list for member."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user()

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account_obj()),
            patch(f"{_ROUTER}.list_department_policies", new_callable=AsyncMock, return_value=[_make_policy()]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get(_LIST_URL)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["total"] == 1


@pytest.mark.anyio
async def test_api_effective_policy_200():
    """GET /effective-department-policy → 200 for member."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user()
    eff = EffectiveDepartmentPolicyResponse(**_MOCK_EFFECTIVE_DICT)

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account_obj()),
            patch(f"{_ROUTER}._resolve_member_id", new_callable=AsyncMock, return_value=MEMBER_ID),
            patch(f"{_ROUTER}.get_effective_policy_for_member", new_callable=AsyncMock, return_value=eff),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get(_EFFECTIVE_URL)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_api_platform_list_all_200():
    """GET /platform/corporate/department-ride-policies → 200 for platform admin."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_db, require_admin

    mock_db = AsyncMock()

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[require_admin] = lambda: None

    try:
        with patch(
            f"{_ROUTER}.list_all_department_policies_platform",
            new_callable=AsyncMock,
            return_value=[_make_policy()],
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get(_PLATFORM_LIST_URL)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["total"] == 1


@pytest.mark.anyio
async def test_api_platform_account_list_200():
    """GET /platform/corporate/accounts/{id}/department-ride-policies → 200."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_db, require_admin

    mock_db = AsyncMock()

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[require_admin] = lambda: None

    try:
        with patch(
            f"{_ROUTER}.list_department_policies",
            new_callable=AsyncMock,
            return_value=[_make_policy()],
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get(_PLATFORM_ACCT_URL)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_api_platform_effective_policy_200():
    """GET /platform/.../effective-department-policy → 200 for platform admin."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_db, require_admin

    mock_db = AsyncMock()
    eff = EffectiveDepartmentPolicyResponse(**_MOCK_EFFECTIVE_DICT)

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[require_admin] = lambda: None

    try:
        with patch(
            f"{_ROUTER}.get_effective_policy_for_member",
            new_callable=AsyncMock,
            return_value=eff,
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get(_PLATFORM_EFFECTIVE_URL)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
