"""Tests for the Corporate Ride Policy feature.

Service layer (async, mocked DB):
  1.  get_policy — returns policy when one exists
  2.  get_policy — returns None when no policy is configured
  3.  set_policy — creates a new policy when none exists
  4.  set_policy — replaces existing policy (upsert)
  5.  set_policy — raises 403 when caller is not an account admin
  6.  set_policy — raises 404 when account does not exist
  7.  delete_policy — removes existing policy
  8.  delete_policy — raises 404 when no policy is configured
  9.  delete_policy — raises 403 when caller is not an account admin
  10. check_ride_allowed — returns allowed=True when no policy configured
  11. check_ride_allowed — denied when vehicle category is not permitted
  12. check_ride_allowed — denied when estimated cost exceeds per-ride cap
  13. check_ride_allowed — denied when purpose required but missing
  14. check_ride_allowed — denied when purpose not in approved list
  15. check_ride_allowed — denied when outside business hours (hour)
  16. check_ride_allowed — denied when outside business hours (weekday)
  17. check_ride_allowed — denied when business_hours_only but time info missing
  18. check_ride_allowed — returns allowed=True when all checks pass

Schema validation:
  19. CorporateRidePolicySet — valid full payload accepted
  20. CorporateRidePolicySet — empty (all defaults) is valid
  21. CorporateRidePolicySet — max_per_ride_usd must be > 0
  22. CorporateRidePolicySet — approved_purposes max 20 entries enforced
  23. CorporateRidePolicySet — each purpose string max 100 chars enforced
  24. RideCheckRequest — valid payload accepted
  25. RideCheckRequest — estimated_cost_usd must be > 0

API layer (service functions patched):
  26. GET /corporate/accounts/me/policy — returns policy when configured
  27. GET /corporate/accounts/me/policy — raises 404 when not configured
  28. PUT /corporate/accounts/me/policy — calls set_policy and returns result
  29. DELETE /corporate/accounts/me/policy — calls delete_policy (204)
  30. POST /corporate/accounts/me/policy/check — returns check result
  31. GET /admin/corporate/accounts/{id}/policy — admin view returns policy
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_ride_policy import CorporateRidePolicy
from app.schemas.corporate_ride_policy import (
    CorporateRidePolicyResponse,
    CorporateRidePolicySet,
    RideCheckRequest,
    RideCheckResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_policy(
    policy_id: int = 1,
    account_id: int = 10,
    allowed_vehicle_categories: list[str] | None = None,
    max_per_ride_usd: Decimal | None = None,
    max_per_member_monthly_usd: Decimal | None = None,
    require_purpose: bool = False,
    approved_purposes: list[str] | None = None,
    business_hours_only: bool = False,
) -> CorporateRidePolicy:
    policy = MagicMock(spec=CorporateRidePolicy)
    policy.id = policy_id
    policy.account_id = account_id
    policy.allowed_vehicle_categories = allowed_vehicle_categories
    policy.max_per_ride_usd = max_per_ride_usd
    policy.max_per_member_monthly_usd = max_per_member_monthly_usd
    policy.require_purpose = require_purpose
    policy.approved_purposes = approved_purposes
    policy.business_hours_only = business_hours_only
    policy.updated_at = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
    return policy


def _scalar_result(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _mock_user(user_id: int = 1, is_admin: bool = False):
    user = MagicMock()
    user.id = user_id
    user.is_admin = is_admin
    return user


def _make_membership(account_id: int = 10, user_id: int = 1, is_admin: bool = True):
    """Return a mock BusinessAccountMember."""
    from app.models.corporate import MemberRole
    m = MagicMock()
    m.account_id = account_id
    m.user_id = user_id
    m.is_active = True
    m.role = MemberRole.ADMIN if is_admin else MemberRole.MEMBER
    return m


# ---------------------------------------------------------------------------
# Service layer tests — 1–18
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_policy_returns_existing():
    """1. get_policy returns the policy when one exists."""
    from app.services.corporate_ride_policy import get_policy

    existing = _make_policy()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(existing))

    result = await get_policy(db, account_id=10)

    assert result is existing


@pytest.mark.asyncio
async def test_get_policy_returns_none_when_not_configured():
    """2. get_policy returns None when no policy is configured."""
    from app.services.corporate_ride_policy import get_policy

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(None))

    result = await get_policy(db, account_id=10)

    assert result is None


@pytest.mark.asyncio
async def test_set_policy_creates_new():
    """3. set_policy creates a new policy when none exists."""
    from app.services.corporate_ride_policy import set_policy

    account = MagicMock()
    account.id = 10
    admin_member = _make_membership(account_id=10, user_id=1, is_admin=True)

    # execute calls: _get_account_or_404, _require_account_admin, _fetch_policy
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(account),     # _get_account_or_404
            _scalar_result(admin_member), # _require_account_admin
            _scalar_result(None),         # _fetch_policy (no existing policy)
        ]
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    data = CorporateRidePolicySet(require_purpose=True)
    result = await set_policy(db, account_id=10, data=data, requesting_user_id=1)

    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_set_policy_updates_existing():
    """4. set_policy replaces (upserts) existing policy."""
    from app.services.corporate_ride_policy import set_policy

    account = MagicMock()
    account.id = 10
    admin_member = _make_membership(account_id=10, user_id=1, is_admin=True)
    existing = _make_policy(account_id=10, require_purpose=False)

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(account),
            _scalar_result(admin_member),
            _scalar_result(existing),
        ]
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    data = CorporateRidePolicySet(
        require_purpose=True,
        approved_purposes=["client meeting", "airport transfer"],
    )
    await set_policy(db, account_id=10, data=data, requesting_user_id=1)

    # No new row should be added — the existing object is mutated
    db.add.assert_not_called()
    assert existing.require_purpose is True
    assert existing.approved_purposes == ["client meeting", "airport transfer"]
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_set_policy_raises_403_for_non_admin():
    """5. set_policy raises 403 when caller is not an account admin."""
    from app.services.corporate_ride_policy import set_policy

    account = MagicMock()
    account.id = 10

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(account),    # _get_account_or_404
            _scalar_result(None),       # _require_account_admin — no admin membership
        ]
    )

    data = CorporateRidePolicySet()
    with pytest.raises(HTTPException) as exc_info:
        await set_policy(db, account_id=10, data=data, requesting_user_id=99)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_set_policy_raises_404_for_missing_account():
    """6. set_policy raises 404 when account does not exist."""
    from app.services.corporate_ride_policy import set_policy

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(None))  # account not found

    data = CorporateRidePolicySet()
    with pytest.raises(HTTPException) as exc_info:
        await set_policy(db, account_id=999, data=data, requesting_user_id=1)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_policy_removes_existing():
    """7. delete_policy removes an existing policy."""
    from app.services.corporate_ride_policy import delete_policy

    account = MagicMock()
    account.id = 10
    admin_member = _make_membership(account_id=10, user_id=1, is_admin=True)
    existing = _make_policy(account_id=10)

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(account),
            _scalar_result(admin_member),
            _scalar_result(existing),
        ]
    )
    db.delete = AsyncMock()
    db.commit = AsyncMock()

    await delete_policy(db, account_id=10, requesting_user_id=1)

    db.delete.assert_called_once_with(existing)
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_policy_raises_404_when_not_configured():
    """8. delete_policy raises 404 when no policy is configured."""
    from app.services.corporate_ride_policy import delete_policy

    account = MagicMock()
    account.id = 10
    admin_member = _make_membership(account_id=10, user_id=1, is_admin=True)

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(account),
            _scalar_result(admin_member),
            _scalar_result(None),   # no policy
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await delete_policy(db, account_id=10, requesting_user_id=1)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_policy_raises_403_for_non_admin():
    """9. delete_policy raises 403 when caller is not an account admin."""
    from app.services.corporate_ride_policy import delete_policy

    account = MagicMock()
    account.id = 10

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(account),
            _scalar_result(None),   # no admin membership
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await delete_policy(db, account_id=10, requesting_user_id=5)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_check_ride_allowed_no_policy():
    """10. check_ride_allowed returns allowed=True when no policy configured."""
    from app.services.corporate_ride_policy import check_ride_allowed

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(None))

    result = await check_ride_allowed(
        db=db,
        account_id=10,
        vehicle_category="standard",
        estimated_cost_usd=Decimal("20.00"),
        purpose=None,
        departure_utc_hour=None,
        departure_utc_weekday=None,
    )

    assert result.allowed is True
    assert result.reason is None


@pytest.mark.asyncio
async def test_check_ride_denied_vehicle_category():
    """11. check_ride_allowed denied when vehicle category not permitted."""
    from app.services.corporate_ride_policy import check_ride_allowed

    policy = _make_policy(allowed_vehicle_categories=["standard", "xl"])
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(policy))

    result = await check_ride_allowed(
        db=db,
        account_id=10,
        vehicle_category="luxury",
        estimated_cost_usd=Decimal("40.00"),
        purpose=None,
        departure_utc_hour=None,
        departure_utc_weekday=None,
    )

    assert result.allowed is False
    assert "luxury" in result.reason
    assert "allowed" in result.reason.lower()


@pytest.mark.asyncio
async def test_check_ride_denied_cost_exceeds_cap():
    """12. check_ride_allowed denied when estimated cost exceeds per-ride cap."""
    from app.services.corporate_ride_policy import check_ride_allowed

    policy = _make_policy(max_per_ride_usd=Decimal("30.00"))
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(policy))

    result = await check_ride_allowed(
        db=db,
        account_id=10,
        vehicle_category="standard",
        estimated_cost_usd=Decimal("45.00"),
        purpose=None,
        departure_utc_hour=None,
        departure_utc_weekday=None,
    )

    assert result.allowed is False
    assert "45.00" in result.reason
    assert "30.00" in result.reason


@pytest.mark.asyncio
async def test_check_ride_denied_purpose_required_but_missing():
    """13. check_ride_allowed denied when purpose required but not supplied."""
    from app.services.corporate_ride_policy import check_ride_allowed

    policy = _make_policy(require_purpose=True)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(policy))

    result = await check_ride_allowed(
        db=db,
        account_id=10,
        vehicle_category="standard",
        estimated_cost_usd=Decimal("15.00"),
        purpose=None,
        departure_utc_hour=None,
        departure_utc_weekday=None,
    )

    assert result.allowed is False
    assert "purpose" in result.reason.lower()


@pytest.mark.asyncio
async def test_check_ride_denied_purpose_not_in_approved_list():
    """14. check_ride_allowed denied when purpose not in approved list."""
    from app.services.corporate_ride_policy import check_ride_allowed

    policy = _make_policy(
        require_purpose=True,
        approved_purposes=["client meeting", "airport transfer"],
    )
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(policy))

    result = await check_ride_allowed(
        db=db,
        account_id=10,
        vehicle_category="standard",
        estimated_cost_usd=Decimal("15.00"),
        purpose="personal errand",
        departure_utc_hour=None,
        departure_utc_weekday=None,
    )

    assert result.allowed is False
    assert "personal errand" in result.reason


@pytest.mark.asyncio
async def test_check_ride_denied_outside_business_hours():
    """15. check_ride_allowed denied when outside business hours (hour check)."""
    from app.services.corporate_ride_policy import check_ride_allowed

    policy = _make_policy(business_hours_only=True)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(policy))

    # Monday at 22:00 UTC — weekday OK, hour too late
    result = await check_ride_allowed(
        db=db,
        account_id=10,
        vehicle_category="standard",
        estimated_cost_usd=Decimal("15.00"),
        purpose=None,
        departure_utc_hour=22,
        departure_utc_weekday=0,  # Monday
    )

    assert result.allowed is False
    assert "business hours" in result.reason.lower()


@pytest.mark.asyncio
async def test_check_ride_denied_on_weekend():
    """16. check_ride_allowed denied when on a weekend (weekday check)."""
    from app.services.corporate_ride_policy import check_ride_allowed

    policy = _make_policy(business_hours_only=True)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(policy))

    # Saturday at 10:00 UTC
    result = await check_ride_allowed(
        db=db,
        account_id=10,
        vehicle_category="standard",
        estimated_cost_usd=Decimal("15.00"),
        purpose=None,
        departure_utc_hour=10,
        departure_utc_weekday=5,  # Saturday
    )

    assert result.allowed is False
    assert "weekday" in result.reason.lower() or "monday" in result.reason.lower()


@pytest.mark.asyncio
async def test_check_ride_denied_business_hours_missing_time_info():
    """17. check_ride_allowed denied when business_hours_only but time info missing."""
    from app.services.corporate_ride_policy import check_ride_allowed

    policy = _make_policy(business_hours_only=True)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(policy))

    result = await check_ride_allowed(
        db=db,
        account_id=10,
        vehicle_category="standard",
        estimated_cost_usd=Decimal("15.00"),
        purpose=None,
        departure_utc_hour=None,      # not supplied
        departure_utc_weekday=None,
    )

    assert result.allowed is False
    assert "business hours" in result.reason.lower()


@pytest.mark.asyncio
async def test_check_ride_allowed_passes_all_checks():
    """18. check_ride_allowed returns allowed=True when all checks pass."""
    from app.services.corporate_ride_policy import check_ride_allowed

    policy = _make_policy(
        allowed_vehicle_categories=["standard", "xl"],
        max_per_ride_usd=Decimal("50.00"),
        require_purpose=True,
        approved_purposes=["client meeting", "airport transfer"],
        business_hours_only=True,
    )
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(policy))

    result = await check_ride_allowed(
        db=db,
        account_id=10,
        vehicle_category="standard",
        estimated_cost_usd=Decimal("25.00"),
        purpose="client meeting",
        departure_utc_hour=9,       # 09:00 UTC — within hours
        departure_utc_weekday=1,    # Tuesday
    )

    assert result.allowed is True
    assert result.reason is None


# ---------------------------------------------------------------------------
# Schema validation tests — 19–25
# ---------------------------------------------------------------------------


def test_schema_valid_full_payload():
    """19. CorporateRidePolicySet — valid full payload accepted."""
    schema = CorporateRidePolicySet(
        allowed_vehicle_categories=["standard", "xl"],
        max_per_ride_usd=Decimal("40.00"),
        max_per_member_monthly_usd=Decimal("300.00"),
        require_purpose=True,
        approved_purposes=["client meeting", "airport transfer"],
        business_hours_only=True,
    )
    assert schema.allowed_vehicle_categories == ["standard", "xl"]
    assert schema.max_per_ride_usd == Decimal("40.00")
    assert schema.require_purpose is True
    assert schema.business_hours_only is True


def test_schema_empty_defaults_are_valid():
    """20. CorporateRidePolicySet — empty (all defaults) is valid."""
    schema = CorporateRidePolicySet()
    assert schema.allowed_vehicle_categories is None
    assert schema.max_per_ride_usd is None
    assert schema.require_purpose is False
    assert schema.business_hours_only is False


def test_schema_max_per_ride_usd_must_be_positive():
    """21. CorporateRidePolicySet — max_per_ride_usd must be > 0."""
    with pytest.raises(ValidationError):
        CorporateRidePolicySet(max_per_ride_usd=Decimal("0"))

    with pytest.raises(ValidationError):
        CorporateRidePolicySet(max_per_ride_usd=Decimal("-10.00"))


def test_schema_approved_purposes_max_20():
    """22. CorporateRidePolicySet — approved_purposes limited to 20 entries."""
    with pytest.raises(ValidationError):
        CorporateRidePolicySet(
            require_purpose=True,
            approved_purposes=[f"purpose_{i}" for i in range(21)],  # 21 entries
        )

    # Exactly 20 is fine
    schema = CorporateRidePolicySet(
        require_purpose=True,
        approved_purposes=[f"purpose_{i}" for i in range(20)],
    )
    assert len(schema.approved_purposes) == 20


def test_schema_purpose_string_max_100_chars():
    """23. CorporateRidePolicySet — each purpose string max 100 chars."""
    long_purpose = "x" * 101
    with pytest.raises(ValidationError):
        CorporateRidePolicySet(
            require_purpose=True,
            approved_purposes=[long_purpose],
        )


def test_ride_check_request_valid():
    """24. RideCheckRequest — valid payload accepted."""
    req = RideCheckRequest(
        vehicle_category="xl",
        estimated_cost_usd=Decimal("22.50"),
        purpose="airport transfer",
        departure_utc_hour=14,
        departure_utc_weekday=2,
    )
    assert req.vehicle_category == "xl"
    assert req.estimated_cost_usd == Decimal("22.50")
    assert req.departure_utc_hour == 14


def test_ride_check_request_cost_must_be_positive():
    """25. RideCheckRequest — estimated_cost_usd must be > 0."""
    with pytest.raises(ValidationError):
        RideCheckRequest(
            vehicle_category="standard",
            estimated_cost_usd=Decimal("0"),
        )


# ---------------------------------------------------------------------------
# API layer tests — 26–31
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_get_my_policy_returns_policy():
    """26. GET /corporate/accounts/me/policy — returns policy when configured."""
    from app.api.v1.corporate_ride_policy import get_my_policy

    policy = _make_policy(account_id=10)
    user = _mock_user(user_id=1)
    membership = _make_membership(account_id=10, user_id=1)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(membership))

    with patch(
        "app.api.v1.corporate_ride_policy.get_policy",
        new=AsyncMock(return_value=policy),
    ):
        result = await get_my_policy(db=db, current_user=user)

    assert result.account_id == 10


@pytest.mark.asyncio
async def test_api_get_my_policy_raises_404_when_not_configured():
    """27. GET /corporate/accounts/me/policy — raises 404 when not configured."""
    from app.api.v1.corporate_ride_policy import get_my_policy

    user = _mock_user(user_id=1)
    membership = _make_membership(account_id=10, user_id=1)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(membership))

    with patch(
        "app.api.v1.corporate_ride_policy.get_policy",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_my_policy(db=db, current_user=user)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_api_set_my_policy():
    """28. PUT /corporate/accounts/me/policy — calls set_policy and returns result."""
    from app.api.v1.corporate_ride_policy import set_my_policy

    policy = _make_policy(account_id=10, require_purpose=True)
    user = _mock_user(user_id=1)
    membership = _make_membership(account_id=10, user_id=1)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(membership))

    data = CorporateRidePolicySet(require_purpose=True)

    with patch(
        "app.api.v1.corporate_ride_policy.set_policy",
        new=AsyncMock(return_value=policy),
    ):
        result = await set_my_policy(data=data, db=db, current_user=user)

    assert result.require_purpose is True
    assert result.account_id == 10


@pytest.mark.asyncio
async def test_api_delete_my_policy():
    """29. DELETE /corporate/accounts/me/policy — calls delete_policy (no content)."""
    from app.api.v1.corporate_ride_policy import delete_my_policy

    user = _mock_user(user_id=1)
    membership = _make_membership(account_id=10, user_id=1)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(membership))

    with patch(
        "app.api.v1.corporate_ride_policy.delete_policy",
        new=AsyncMock(return_value=None),
    ) as mock_delete:
        result = await delete_my_policy(db=db, current_user=user)

    mock_delete.assert_called_once()
    assert result is None


@pytest.mark.asyncio
async def test_api_check_my_policy():
    """30. POST /corporate/accounts/me/policy/check — returns check result."""
    from app.api.v1.corporate_ride_policy import check_my_policy

    check_result = RideCheckResponse(allowed=True)
    user = _mock_user(user_id=1)
    membership = _make_membership(account_id=10, user_id=1)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(membership))

    request = RideCheckRequest(
        vehicle_category="standard",
        estimated_cost_usd=Decimal("20.00"),
        purpose="client meeting",
        departure_utc_hour=10,
        departure_utc_weekday=1,
    )

    with patch(
        "app.api.v1.corporate_ride_policy.check_ride_allowed",
        new=AsyncMock(return_value=check_result),
    ):
        result = await check_my_policy(request=request, db=db, current_user=user)

    assert result.allowed is True


@pytest.mark.asyncio
async def test_api_admin_get_policy():
    """31. GET /admin/corporate/accounts/{id}/policy — admin view returns policy."""
    from app.api.v1.corporate_ride_policy import admin_get_policy

    policy = _make_policy(account_id=10)

    db = AsyncMock()

    with patch(
        "app.api.v1.corporate_ride_policy.get_policy",
        new=AsyncMock(return_value=policy),
    ):
        result = await admin_get_policy(account_id=10, db=db)

    assert result.account_id == 10
