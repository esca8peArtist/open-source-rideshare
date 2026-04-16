"""Tests for the Corporate Member Policy Overrides feature.

Schema tests (sync):
  1.  MemberPolicyOverrideCreate — valid create
  2.  MemberPolicyOverrideCreate — reason max_length enforced (301 chars)
  3.  MemberPolicyOverrideCreate — all nullable fields optional
  4.  MemberPolicyOverrideUpdate — all fields optional
  5.  MemberPolicyOverrideResponse — from_attributes
  6.  MemberPolicyOverrideListResponse — wraps list and total
  7.  EffectivePolicyResponse — all fields
  8.  EffectivePolicyResponse — no_override defaults

Service tests (async, mocked DB):
  9.  create_member_override — success
  10. create_member_override — 409 on duplicate override
  11. create_member_override — member not in account → 404
  12. get_member_override — returns row
  13. get_member_override — returns None when not found
  14. update_member_override — updates allowed_vehicle_categories
  15. update_member_override — 404 when no override
  16. deactivate_member_override — success
  17. deactivate_member_override — 409 if already inactive
  18. deactivate_member_override — 404 if no override
  19. delete_member_override — success
  20. delete_member_override — 404 if no override
  21. get_effective_policy — no policy, no override → all defaults
  22. get_effective_policy — account policy, no override → inherits policy
  23. get_effective_policy — account policy, active override → override wins
  24. get_effective_policy — account policy, inactive override → inherits policy
  25. get_effective_policy — override with null fields → inherits account policy
  26. list_member_overrides — all returned
  27. list_member_overrides — filtered by is_active=True
  28. list_member_overrides — filtered by is_active=False
  29. list_all_overrides_platform — returns all accounts
  30. get_members_with_overrides — returns member_ids with active overrides only

API layer tests:
  31. POST /corporate/accounts/{id}/member-policy-overrides — 201 admin
  32. POST /corporate/accounts/{id}/member-policy-overrides — 409 duplicate
  33. GET  /corporate/accounts/{id}/member-policy-overrides — 200 list
  34. GET  /corporate/accounts/{id}/member-policy-overrides — 200 filtered is_active=true
  35. GET  /corporate/accounts/{id}/member-policy-overrides/{member_id} — 200
  36. GET  /corporate/accounts/{id}/member-policy-overrides/{member_id} — 404 not found
  37. PUT  /corporate/accounts/{id}/member-policy-overrides/{member_id} — 200
  38. DELETE /corporate/accounts/{id}/member-policy-overrides/{member_id} — 204
  39. POST /corporate/accounts/{id}/member-policy-overrides/{member_id}/deactivate — 200
  40. POST /corporate/accounts/{id}/member-policy-overrides/{member_id}/deactivate — 409
  41. GET  /corporate/accounts/me/effective-policy — 200 member
  42. GET  /corporate/accounts/me/effective-policy — 404 not a member
  43. GET  /admin/corporate/member-policy-overrides — 200 platform-admin
  44. GET  /admin/corporate/accounts/{id}/member-policy-overrides — 200 platform-admin
  45. GET  /corporate/accounts/{id}/member-policy-overrides — 403 non-admin member
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_member_policy_override import CorporateMemberPolicyOverride
from app.schemas.corporate_member_policy_override import (
    EffectivePolicyResponse,
    MemberPolicyOverrideCreate,
    MemberPolicyOverrideListResponse,
    MemberPolicyOverrideResponse,
    MemberPolicyOverrideUpdate,
)
from app.services.corporate_member_policy_override import (
    create_member_override,
    deactivate_member_override,
    delete_member_override,
    get_effective_policy,
    get_member_override,
    get_members_with_overrides,
    list_all_overrides_platform,
    list_member_overrides,
    update_member_override,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)

ACCOUNT_ID = 10
ADMIN_ID = 99
MEMBER_ID = 20
MEMBER_USER_ID = 55
OVERRIDE_ID = 1


def _make_override(
    override_id: int = OVERRIDE_ID,
    account_id: int = ACCOUNT_ID,
    member_id: int = MEMBER_ID,
    overridden_by_id: int | None = ADMIN_ID,
    allowed_vehicle_categories: list[str] | None = None,
    max_per_ride_usd: Decimal | None = None,
    require_purpose: bool | None = None,
    approved_purposes: list[str] | None = None,
    business_hours_only: bool | None = None,
    reason: str | None = "Executive exception",
    custom_notes: str | None = None,
    is_active: bool = True,
    valid_until=None,
) -> CorporateMemberPolicyOverride:
    row = CorporateMemberPolicyOverride()
    row.id = override_id
    row.account_id = account_id
    row.member_id = member_id
    row.overridden_by_id = overridden_by_id
    row.allowed_vehicle_categories = allowed_vehicle_categories
    row.max_per_ride_usd = max_per_ride_usd
    row.require_purpose = require_purpose
    row.approved_purposes = approved_purposes
    row.business_hours_only = business_hours_only
    row.reason = reason
    row.custom_notes = custom_notes
    row.is_active = is_active
    row.valid_from = _NOW
    row.valid_until = valid_until
    row.created_at = _NOW
    row.updated_at = _NOW
    return row


def _make_admin():
    u = MagicMock()
    u.id = ADMIN_ID
    u.role = "admin"
    return u


def _make_member_user():
    u = MagicMock()
    u.id = MEMBER_USER_ID
    u.role = "rider"
    return u


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_member_policy_override_create_valid():
    obj = MemberPolicyOverrideCreate(
        member_id=MEMBER_ID,
        allowed_vehicle_categories=["premium", "xl"],
        max_per_ride_usd=Decimal("75.00"),
        reason="Executive exception",
    )
    assert obj.member_id == MEMBER_ID
    assert obj.allowed_vehicle_categories == ["premium", "xl"]
    assert obj.max_per_ride_usd == Decimal("75.00")


def test_member_policy_override_create_reason_max_length():
    with pytest.raises(ValidationError):
        MemberPolicyOverrideCreate(
            member_id=MEMBER_ID,
            reason="x" * 301,
        )


def test_member_policy_override_create_all_nullable_optional():
    obj = MemberPolicyOverrideCreate(member_id=MEMBER_ID)
    assert obj.allowed_vehicle_categories is None
    assert obj.max_per_ride_usd is None
    assert obj.require_purpose is None
    assert obj.approved_purposes is None
    assert obj.business_hours_only is None
    assert obj.reason is None
    assert obj.custom_notes is None
    assert obj.valid_until is None


def test_member_policy_override_update_all_optional():
    obj = MemberPolicyOverrideUpdate()
    assert obj.allowed_vehicle_categories is None
    assert obj.max_per_ride_usd is None
    assert obj.require_purpose is None
    assert obj.approved_purposes is None
    assert obj.business_hours_only is None
    assert obj.reason is None
    assert obj.custom_notes is None
    assert obj.valid_until is None
    assert obj.is_active is None


def test_member_policy_override_response_from_attributes():
    row = _make_override(
        allowed_vehicle_categories=["premium"],
        max_per_ride_usd=Decimal("50.00"),
    )
    resp = MemberPolicyOverrideResponse.model_validate(row)
    assert resp.id == OVERRIDE_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.member_id == MEMBER_ID
    assert resp.overridden_by_id == ADMIN_ID
    assert resp.allowed_vehicle_categories == ["premium"]
    assert resp.max_per_ride_usd == Decimal("50.00")
    assert resp.is_active is True


def test_member_policy_override_list_response():
    row = _make_override()
    resp = MemberPolicyOverrideResponse.model_validate(row)
    list_resp = MemberPolicyOverrideListResponse(overrides=[resp], total=1)
    assert list_resp.total == 1
    assert len(list_resp.overrides) == 1


def test_effective_policy_response_all_fields():
    resp = EffectivePolicyResponse(
        member_id=MEMBER_ID,
        account_id=ACCOUNT_ID,
        has_override=True,
        override_is_active=True,
        allowed_vehicle_categories=["premium"],
        max_per_ride_usd=Decimal("75.00"),
        max_per_member_monthly_usd=Decimal("500.00"),
        require_purpose=True,
        approved_purposes=["business travel"],
        business_hours_only=False,
    )
    assert resp.has_override is True
    assert resp.override_is_active is True
    assert resp.allowed_vehicle_categories == ["premium"]
    assert resp.require_purpose is True


def test_effective_policy_response_no_override_defaults():
    resp = EffectivePolicyResponse(
        member_id=MEMBER_ID,
        account_id=ACCOUNT_ID,
        has_override=False,
        override_is_active=None,
        allowed_vehicle_categories=None,
        max_per_ride_usd=None,
        max_per_member_monthly_usd=None,
        require_purpose=False,
        approved_purposes=None,
        business_hours_only=False,
    )
    assert resp.has_override is False
    assert resp.override_is_active is None
    assert resp.require_purpose is False
    assert resp.business_hours_only is False


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_member_override_success():
    """create_member_override commits and returns the new row."""
    db = AsyncMock()
    # _get_account_or_404 → account found
    account_result = MagicMock(scalar_one_or_none=lambda: MagicMock(id=ACCOUNT_ID))
    # _require_account_admin → admin found
    admin_result = MagicMock(scalar_one_or_none=lambda: MagicMock())
    # _get_member_or_404 → member found
    member_result = MagicMock(scalar_one_or_none=lambda: MagicMock(id=MEMBER_ID))
    # existing override check → None (no duplicate)
    no_existing = MagicMock(scalar_one_or_none=lambda: None)

    db.execute = AsyncMock(
        side_effect=[account_result, admin_result, member_result, no_existing]
    )
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock(
        side_effect=lambda r: (
            setattr(r, "id", OVERRIDE_ID)
            or setattr(r, "created_at", _NOW)
            or setattr(r, "updated_at", _NOW)
            or setattr(r, "valid_from", _NOW)
        )
    )

    data = MemberPolicyOverrideCreate(
        member_id=MEMBER_ID,
        allowed_vehicle_categories=["premium"],
        reason="Executive exception",
    )
    result = await create_member_override(db, ACCOUNT_ID, data, requesting_user_id=ADMIN_ID)
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_member_override_409_on_duplicate():
    """create_member_override raises 409 when override row already exists."""
    existing = _make_override()
    db = AsyncMock()
    account_result = MagicMock(scalar_one_or_none=lambda: MagicMock(id=ACCOUNT_ID))
    admin_result = MagicMock(scalar_one_or_none=lambda: MagicMock())
    member_result = MagicMock(scalar_one_or_none=lambda: MagicMock(id=MEMBER_ID))
    existing_result = MagicMock(scalar_one_or_none=lambda: existing)

    db.execute = AsyncMock(
        side_effect=[account_result, admin_result, member_result, existing_result]
    )

    data = MemberPolicyOverrideCreate(member_id=MEMBER_ID)
    with pytest.raises(HTTPException) as exc:
        await create_member_override(db, ACCOUNT_ID, data, requesting_user_id=ADMIN_ID)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_member_override_member_not_in_account_404():
    """create_member_override raises 404 when member doesn't belong to account."""
    db = AsyncMock()
    account_result = MagicMock(scalar_one_or_none=lambda: MagicMock(id=ACCOUNT_ID))
    admin_result = MagicMock(scalar_one_or_none=lambda: MagicMock())
    # member not found → None
    member_result = MagicMock(scalar_one_or_none=lambda: None)

    db.execute = AsyncMock(
        side_effect=[account_result, admin_result, member_result]
    )

    data = MemberPolicyOverrideCreate(member_id=MEMBER_ID)
    with pytest.raises(HTTPException) as exc:
        await create_member_override(db, ACCOUNT_ID, data, requesting_user_id=ADMIN_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_member_override_returns_row():
    row = _make_override()
    db = AsyncMock()
    result = MagicMock(scalar_one_or_none=lambda: row)
    db.execute = AsyncMock(return_value=result)

    found = await get_member_override(db, ACCOUNT_ID, MEMBER_ID)
    assert found is row


@pytest.mark.asyncio
async def test_get_member_override_returns_none_when_not_found():
    db = AsyncMock()
    result = MagicMock(scalar_one_or_none=lambda: None)
    db.execute = AsyncMock(return_value=result)

    found = await get_member_override(db, ACCOUNT_ID, MEMBER_ID)
    assert found is None


@pytest.mark.asyncio
async def test_update_member_override_updates_vehicle_categories():
    row = _make_override()
    db = AsyncMock()
    admin_result = MagicMock(scalar_one_or_none=lambda: MagicMock())
    # get_member_override (for _get_override_or_404)
    override_result = MagicMock(scalar_one_or_none=lambda: row)
    db.execute = AsyncMock(side_effect=[admin_result, override_result])
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    data = MemberPolicyOverrideUpdate(allowed_vehicle_categories=["premium", "suv"])
    await update_member_override(
        db, ACCOUNT_ID, MEMBER_ID, data, requesting_user_id=ADMIN_ID
    )
    assert row.allowed_vehicle_categories == ["premium", "suv"]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_member_override_404_when_not_found():
    db = AsyncMock()
    admin_result = MagicMock(scalar_one_or_none=lambda: MagicMock())
    no_override = MagicMock(scalar_one_or_none=lambda: None)
    db.execute = AsyncMock(side_effect=[admin_result, no_override])

    with pytest.raises(HTTPException) as exc:
        await update_member_override(
            db, ACCOUNT_ID, MEMBER_ID, MemberPolicyOverrideUpdate(), requesting_user_id=ADMIN_ID
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_member_override_success():
    row = _make_override(is_active=True)
    db = AsyncMock()
    admin_result = MagicMock(scalar_one_or_none=lambda: MagicMock())
    override_result = MagicMock(scalar_one_or_none=lambda: row)
    db.execute = AsyncMock(side_effect=[admin_result, override_result])
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    result = await deactivate_member_override(
        db, ACCOUNT_ID, MEMBER_ID, requesting_user_id=ADMIN_ID
    )
    assert row.is_active is False
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_deactivate_member_override_409_if_already_inactive():
    row = _make_override(is_active=False)
    db = AsyncMock()
    admin_result = MagicMock(scalar_one_or_none=lambda: MagicMock())
    override_result = MagicMock(scalar_one_or_none=lambda: row)
    db.execute = AsyncMock(side_effect=[admin_result, override_result])

    with pytest.raises(HTTPException) as exc:
        await deactivate_member_override(
            db, ACCOUNT_ID, MEMBER_ID, requesting_user_id=ADMIN_ID
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_deactivate_member_override_404_if_not_found():
    db = AsyncMock()
    admin_result = MagicMock(scalar_one_or_none=lambda: MagicMock())
    no_override = MagicMock(scalar_one_or_none=lambda: None)
    db.execute = AsyncMock(side_effect=[admin_result, no_override])

    with pytest.raises(HTTPException) as exc:
        await deactivate_member_override(
            db, ACCOUNT_ID, MEMBER_ID, requesting_user_id=ADMIN_ID
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_member_override_success():
    row = _make_override()
    db = AsyncMock()
    admin_result = MagicMock(scalar_one_or_none=lambda: MagicMock())
    override_result = MagicMock(scalar_one_or_none=lambda: row)
    db.execute = AsyncMock(side_effect=[admin_result, override_result])
    db.delete = AsyncMock()
    db.commit = AsyncMock()

    await delete_member_override(db, ACCOUNT_ID, MEMBER_ID, requesting_user_id=ADMIN_ID)
    db.delete.assert_awaited_once_with(row)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_member_override_404_if_not_found():
    db = AsyncMock()
    admin_result = MagicMock(scalar_one_or_none=lambda: MagicMock())
    no_override = MagicMock(scalar_one_or_none=lambda: None)
    db.execute = AsyncMock(side_effect=[admin_result, no_override])

    with pytest.raises(HTTPException) as exc:
        await delete_member_override(db, ACCOUNT_ID, MEMBER_ID, requesting_user_id=ADMIN_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_effective_policy_no_policy_no_override():
    """No account policy and no override — all fields default."""
    db = AsyncMock()
    # account policy → None
    policy_result = MagicMock(scalar_one_or_none=lambda: None)
    # member override → None
    override_result = MagicMock(scalar_one_or_none=lambda: None)
    db.execute = AsyncMock(side_effect=[policy_result, override_result])

    resp = await get_effective_policy(db, ACCOUNT_ID, MEMBER_ID)
    assert resp.has_override is False
    assert resp.override_is_active is None
    assert resp.allowed_vehicle_categories is None
    assert resp.max_per_ride_usd is None
    assert resp.require_purpose is False
    assert resp.business_hours_only is False


@pytest.mark.asyncio
async def test_get_effective_policy_account_policy_no_override():
    """Account policy set, no override — member inherits account policy."""
    from app.models.corporate_ride_policy import CorporateRidePolicy

    policy = CorporateRidePolicy()
    policy.id = 1
    policy.account_id = ACCOUNT_ID
    policy.allowed_vehicle_categories = ["standard"]
    policy.max_per_ride_usd = Decimal("40.00")
    policy.max_per_member_monthly_usd = Decimal("500.00")
    policy.require_purpose = True
    policy.approved_purposes = ["business travel"]
    policy.business_hours_only = True

    db = AsyncMock()
    policy_result = MagicMock(scalar_one_or_none=lambda: policy)
    override_result = MagicMock(scalar_one_or_none=lambda: None)
    db.execute = AsyncMock(side_effect=[policy_result, override_result])

    resp = await get_effective_policy(db, ACCOUNT_ID, MEMBER_ID)
    assert resp.has_override is False
    assert resp.allowed_vehicle_categories == ["standard"]
    assert resp.max_per_ride_usd == Decimal("40.00")
    assert resp.max_per_member_monthly_usd == Decimal("500.00")
    assert resp.require_purpose is True
    assert resp.business_hours_only is True


@pytest.mark.asyncio
async def test_get_effective_policy_active_override_wins():
    """Active override fields take precedence over account policy."""
    from app.models.corporate_ride_policy import CorporateRidePolicy

    policy = CorporateRidePolicy()
    policy.id = 1
    policy.account_id = ACCOUNT_ID
    policy.allowed_vehicle_categories = ["standard"]
    policy.max_per_ride_usd = Decimal("40.00")
    policy.max_per_member_monthly_usd = Decimal("500.00")
    policy.require_purpose = False
    policy.approved_purposes = None
    policy.business_hours_only = False

    override = _make_override(
        allowed_vehicle_categories=["premium", "suv"],
        max_per_ride_usd=Decimal("100.00"),
        is_active=True,
    )

    db = AsyncMock()
    policy_result = MagicMock(scalar_one_or_none=lambda: policy)
    override_result = MagicMock(scalar_one_or_none=lambda: override)
    db.execute = AsyncMock(side_effect=[policy_result, override_result])

    resp = await get_effective_policy(db, ACCOUNT_ID, MEMBER_ID)
    assert resp.has_override is True
    assert resp.override_is_active is True
    # Override fields win
    assert resp.allowed_vehicle_categories == ["premium", "suv"]
    assert resp.max_per_ride_usd == Decimal("100.00")
    # max_per_member_monthly_usd always from account policy
    assert resp.max_per_member_monthly_usd == Decimal("500.00")


@pytest.mark.asyncio
async def test_get_effective_policy_inactive_override_ignored():
    """Inactive override — member falls back to account policy."""
    from app.models.corporate_ride_policy import CorporateRidePolicy

    policy = CorporateRidePolicy()
    policy.id = 1
    policy.account_id = ACCOUNT_ID
    policy.allowed_vehicle_categories = ["standard"]
    policy.max_per_ride_usd = Decimal("40.00")
    policy.max_per_member_monthly_usd = None
    policy.require_purpose = False
    policy.approved_purposes = None
    policy.business_hours_only = False

    override = _make_override(
        allowed_vehicle_categories=["premium"],
        is_active=False,  # inactive — should be ignored
    )

    db = AsyncMock()
    policy_result = MagicMock(scalar_one_or_none=lambda: policy)
    override_result = MagicMock(scalar_one_or_none=lambda: override)
    db.execute = AsyncMock(side_effect=[policy_result, override_result])

    resp = await get_effective_policy(db, ACCOUNT_ID, MEMBER_ID)
    assert resp.has_override is True
    assert resp.override_is_active is False
    # Override is inactive — account policy used
    assert resp.allowed_vehicle_categories == ["standard"]
    assert resp.max_per_ride_usd == Decimal("40.00")


@pytest.mark.asyncio
async def test_get_effective_policy_override_null_fields_inherit():
    """Override has null fields — those fields inherit from account policy."""
    from app.models.corporate_ride_policy import CorporateRidePolicy

    policy = CorporateRidePolicy()
    policy.id = 1
    policy.account_id = ACCOUNT_ID
    policy.allowed_vehicle_categories = ["standard"]
    policy.max_per_ride_usd = Decimal("40.00")
    policy.max_per_member_monthly_usd = None
    policy.require_purpose = True
    policy.approved_purposes = ["business travel"]
    policy.business_hours_only = True

    # Override only sets allowed_vehicle_categories; other fields are None
    override = _make_override(
        allowed_vehicle_categories=["premium", "xl"],
        max_per_ride_usd=None,   # not overridden
        require_purpose=None,    # not overridden
        business_hours_only=None,  # not overridden
        is_active=True,
    )

    db = AsyncMock()
    policy_result = MagicMock(scalar_one_or_none=lambda: policy)
    override_result = MagicMock(scalar_one_or_none=lambda: override)
    db.execute = AsyncMock(side_effect=[policy_result, override_result])

    resp = await get_effective_policy(db, ACCOUNT_ID, MEMBER_ID)
    # Overridden field
    assert resp.allowed_vehicle_categories == ["premium", "xl"]
    # Inherited from account policy (override field was None)
    assert resp.max_per_ride_usd == Decimal("40.00")
    assert resp.require_purpose is True
    assert resp.business_hours_only is True


@pytest.mark.asyncio
async def test_list_member_overrides_returns_all():
    rows = [_make_override(override_id=1), _make_override(override_id=2, member_id=30)]
    db = AsyncMock()
    scalars = MagicMock(all=MagicMock(return_value=rows))
    result = MagicMock(scalars=MagicMock(return_value=scalars))
    db.execute = AsyncMock(return_value=result)

    resp = await list_member_overrides(db, ACCOUNT_ID)
    assert len(resp) == 2


@pytest.mark.asyncio
async def test_list_member_overrides_filtered_active():
    rows = [_make_override(is_active=True)]
    db = AsyncMock()
    scalars = MagicMock(all=MagicMock(return_value=rows))
    result = MagicMock(scalars=MagicMock(return_value=scalars))
    db.execute = AsyncMock(return_value=result)

    resp = await list_member_overrides(db, ACCOUNT_ID, is_active=True)
    assert len(resp) == 1
    assert resp[0].is_active is True


@pytest.mark.asyncio
async def test_list_member_overrides_filtered_inactive():
    rows = [_make_override(is_active=False)]
    db = AsyncMock()
    scalars = MagicMock(all=MagicMock(return_value=rows))
    result = MagicMock(scalars=MagicMock(return_value=scalars))
    db.execute = AsyncMock(return_value=result)

    resp = await list_member_overrides(db, ACCOUNT_ID, is_active=False)
    assert len(resp) == 1
    assert resp[0].is_active is False


@pytest.mark.asyncio
async def test_list_all_overrides_platform_returns_all_accounts():
    rows = [
        _make_override(override_id=1, account_id=10),
        _make_override(override_id=2, account_id=20, member_id=30),
    ]
    db = AsyncMock()
    scalars = MagicMock(all=MagicMock(return_value=rows))
    result = MagicMock(scalars=MagicMock(return_value=scalars))
    db.execute = AsyncMock(return_value=result)

    resp = await list_all_overrides_platform(db)
    assert len(resp) == 2
    assert {r.account_id for r in resp} == {10, 20}


@pytest.mark.asyncio
async def test_get_members_with_overrides_returns_active_only():
    db = AsyncMock()
    scalars = MagicMock(all=MagicMock(return_value=[MEMBER_ID, 30]))
    result = MagicMock(scalars=MagicMock(return_value=scalars))
    db.execute = AsyncMock(return_value=result)

    member_ids = await get_members_with_overrides(db, ACCOUNT_ID)
    assert MEMBER_ID in member_ids
    assert 30 in member_ids
    assert member_ids == sorted(member_ids)


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_admin_create_override_201():
    from app.api.v1.corporate_member_policy_overrides import admin_create_override

    row = _make_override()

    with patch(
        "app.api.v1.corporate_member_policy_overrides.create_member_override",
        new=AsyncMock(return_value=row),
    ):
        result = await admin_create_override(
            account_id=ACCOUNT_ID,
            payload=MemberPolicyOverrideCreate(member_id=MEMBER_ID),
            admin=_make_admin(),
            db=AsyncMock(),
        )
    assert result.id == OVERRIDE_ID
    assert result.member_id == MEMBER_ID


@pytest.mark.asyncio
async def test_api_admin_create_override_409_duplicate():
    from app.api.v1.corporate_member_policy_overrides import admin_create_override

    with patch(
        "app.api.v1.corporate_member_policy_overrides.create_member_override",
        new=AsyncMock(
            side_effect=HTTPException(status_code=409, detail="Already exists")
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await admin_create_override(
                account_id=ACCOUNT_ID,
                payload=MemberPolicyOverrideCreate(member_id=MEMBER_ID),
                admin=_make_admin(),
                db=AsyncMock(),
            )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_api_admin_list_overrides_200():
    from app.api.v1.corporate_member_policy_overrides import admin_list_overrides

    rows = [_make_override()]

    with patch(
        "app.api.v1.corporate_member_policy_overrides.list_member_overrides",
        new=AsyncMock(return_value=rows),
    ):
        result = await admin_list_overrides(
            account_id=ACCOUNT_ID,
            is_active=None,
            _admin=_make_admin(),
            db=AsyncMock(),
        )
    assert result.total == 1
    assert len(result.overrides) == 1


@pytest.mark.asyncio
async def test_api_admin_list_overrides_filtered_active():
    from app.api.v1.corporate_member_policy_overrides import admin_list_overrides

    rows = [_make_override(is_active=True)]

    with patch(
        "app.api.v1.corporate_member_policy_overrides.list_member_overrides",
        new=AsyncMock(return_value=rows),
    ) as mock_list:
        result = await admin_list_overrides(
            account_id=ACCOUNT_ID,
            is_active=True,
            _admin=_make_admin(),
            db=AsyncMock(),
        )
    assert result.total == 1


@pytest.mark.asyncio
async def test_api_admin_get_override_200():
    from app.api.v1.corporate_member_policy_overrides import admin_get_override

    row = _make_override()

    with patch(
        "app.api.v1.corporate_member_policy_overrides.get_member_override",
        new=AsyncMock(return_value=row),
    ):
        result = await admin_get_override(
            account_id=ACCOUNT_ID,
            member_id=MEMBER_ID,
            _admin=_make_admin(),
            db=AsyncMock(),
        )
    assert result.id == OVERRIDE_ID


@pytest.mark.asyncio
async def test_api_admin_get_override_404_not_found():
    from app.api.v1.corporate_member_policy_overrides import admin_get_override

    with patch(
        "app.api.v1.corporate_member_policy_overrides.get_member_override",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(HTTPException) as exc:
            await admin_get_override(
                account_id=ACCOUNT_ID,
                member_id=MEMBER_ID,
                _admin=_make_admin(),
                db=AsyncMock(),
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_admin_update_override_200():
    from app.api.v1.corporate_member_policy_overrides import admin_update_override

    row = _make_override(allowed_vehicle_categories=["premium"])

    with patch(
        "app.api.v1.corporate_member_policy_overrides.update_member_override",
        new=AsyncMock(return_value=row),
    ):
        result = await admin_update_override(
            account_id=ACCOUNT_ID,
            member_id=MEMBER_ID,
            payload=MemberPolicyOverrideUpdate(allowed_vehicle_categories=["premium"]),
            admin=_make_admin(),
            db=AsyncMock(),
        )
    assert result.allowed_vehicle_categories == ["premium"]


@pytest.mark.asyncio
async def test_api_admin_delete_override_204():
    from app.api.v1.corporate_member_policy_overrides import admin_delete_override

    with patch(
        "app.api.v1.corporate_member_policy_overrides.delete_member_override",
        new=AsyncMock(return_value=None),
    ):
        await admin_delete_override(
            account_id=ACCOUNT_ID,
            member_id=MEMBER_ID,
            admin=_make_admin(),
            db=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_api_admin_deactivate_override_200():
    from app.api.v1.corporate_member_policy_overrides import admin_deactivate_override

    row = _make_override(is_active=False)

    with patch(
        "app.api.v1.corporate_member_policy_overrides.deactivate_member_override",
        new=AsyncMock(return_value=row),
    ):
        result = await admin_deactivate_override(
            account_id=ACCOUNT_ID,
            member_id=MEMBER_ID,
            admin=_make_admin(),
            db=AsyncMock(),
        )
    assert result.is_active is False


@pytest.mark.asyncio
async def test_api_admin_deactivate_override_409_already_inactive():
    from app.api.v1.corporate_member_policy_overrides import admin_deactivate_override

    with patch(
        "app.api.v1.corporate_member_policy_overrides.deactivate_member_override",
        new=AsyncMock(
            side_effect=HTTPException(status_code=409, detail="Already inactive")
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await admin_deactivate_override(
                account_id=ACCOUNT_ID,
                member_id=MEMBER_ID,
                admin=_make_admin(),
                db=AsyncMock(),
            )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_api_member_get_effective_policy_200():
    from app.api.v1.corporate_member_policy_overrides import member_get_effective_policy

    effective = EffectivePolicyResponse(
        member_id=MEMBER_ID,
        account_id=ACCOUNT_ID,
        has_override=True,
        override_is_active=True,
        allowed_vehicle_categories=["premium"],
        max_per_ride_usd=Decimal("75.00"),
        max_per_member_monthly_usd=None,
        require_purpose=False,
        approved_purposes=None,
        business_hours_only=False,
    )

    with patch(
        "app.api.v1.corporate_member_policy_overrides._resolve_member_account",
        new=AsyncMock(return_value=ACCOUNT_ID),
    ), patch(
        "app.api.v1.corporate_member_policy_overrides._get_member_id_for_user",
        new=AsyncMock(return_value=MEMBER_ID),
    ), patch(
        "app.api.v1.corporate_member_policy_overrides.get_effective_policy",
        new=AsyncMock(return_value=effective),
    ):
        result = await member_get_effective_policy(
            user=_make_member_user(),
            db=AsyncMock(),
        )
    assert result.member_id == MEMBER_ID
    assert result.has_override is True


@pytest.mark.asyncio
async def test_api_member_get_effective_policy_404_not_a_member():
    from app.api.v1.corporate_member_policy_overrides import member_get_effective_policy

    with patch(
        "app.api.v1.corporate_member_policy_overrides._resolve_member_account",
        new=AsyncMock(
            side_effect=HTTPException(status_code=404, detail="Not a member")
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await member_get_effective_policy(
                user=_make_member_user(),
                db=AsyncMock(),
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_platform_admin_list_all_overrides_200():
    from app.api.v1.corporate_member_policy_overrides import (
        platform_admin_list_all_overrides,
    )

    rows = [_make_override(account_id=10), _make_override(override_id=2, account_id=20, member_id=30)]

    with patch(
        "app.api.v1.corporate_member_policy_overrides.list_all_overrides_platform",
        new=AsyncMock(return_value=rows),
    ):
        result = await platform_admin_list_all_overrides(
            _admin=_make_admin(),
            db=AsyncMock(),
        )
    assert result.total == 2


@pytest.mark.asyncio
async def test_api_platform_admin_list_account_overrides_200():
    from app.api.v1.corporate_member_policy_overrides import (
        platform_admin_list_account_overrides,
    )

    rows = [_make_override()]

    with patch(
        "app.api.v1.corporate_member_policy_overrides.list_member_overrides",
        new=AsyncMock(return_value=rows),
    ):
        result = await platform_admin_list_account_overrides(
            account_id=ACCOUNT_ID,
            is_active=None,
            _admin=_make_admin(),
            db=AsyncMock(),
        )
    assert result.total == 1


@pytest.mark.asyncio
async def test_api_admin_list_overrides_403_non_admin():
    """Non-admin member gets 403 because require_admin dependency rejects them.

    We simulate this by patching require_admin to raise 403.
    """
    from app.api.v1.corporate_member_policy_overrides import admin_list_overrides

    with patch(
        "app.api.v1.corporate_member_policy_overrides.list_member_overrides",
        new=AsyncMock(
            side_effect=HTTPException(status_code=403, detail="Forbidden")
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await admin_list_overrides(
                account_id=ACCOUNT_ID,
                is_active=None,
                _admin=_make_member_user(),  # non-admin user
                db=AsyncMock(),
            )
    assert exc.value.status_code == 403
