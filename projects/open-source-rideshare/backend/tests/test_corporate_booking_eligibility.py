"""Tests for the Corporate Booking Eligibility Check feature.

Service layer (async, mocked DB with patched dependencies):
  1.  All checks pass, no approval chain → eligible=True, requires_approval=False, auto_approved=False
  2.  All checks pass, approval chain found → eligible=True, requires_approval=True
  3.  All checks pass, auto-approved → eligible=True, auto_approved=True, requires_approval=False
  4.  Policy fails: vehicle category not in allowed list → eligible=False, denial_reasons contains vehicle message
  5.  Policy fails: cost exceeds max_per_ride_usd → eligible=False
  6.  Policy fails: purpose required but trip_purpose_code=None → eligible=False
  7.  Policy fails: purpose not in approved_purposes → eligible=False
  8.  Policy fails: business_hours_only but ride_dt is 2am UTC Saturday → eligible=False
  9.  Policy passes: business_hours_only but ride_dt is Monday 08:00 UTC → passes
  10. Blackout: in blackout, override_allowed=False → eligible=False, in_blackout=True
  11. Blackout: in blackout, override_allowed=True → eligible=True, in_blackout=True
  12. Blackout: in blackout, override_requires_approval=True → blackout_requires_approval=True
  13. Daily quota exceeded → eligible=False, any_quota_exceeded=True
  14. Weekly quota exceeded → eligible=False
  15. Monthly quota exceeded → eligible=False
  16. Spend limit exceeded → eligible=False
  17. Spend limit not set → spend_limit_exceeded=False, spend_remaining_usd=None
  18. Multiple failures → denial_reasons has multiple entries, eligible=False
  19. Member not found → raises HTTP 404
  20. Quota checks: all three periods collected in response
  21. auto_approval_rule_id = matched_rule.id when auto_approved
  22. approval_chain_id = chain.id when requires_approval

Schema validation:
  23. BookingRideParams: estimated_cost_usd must be > 0
  24. BookingRideParams: all optional fields default to None
  25. BookingEligibilityResponse: construction with all fields
  26. QuotaCheckSummary: construction

API layer (service functions patched):
  27. POST self-check → 200, eligible response
  28. POST self-check → 404 when not corporate member
  29. POST admin check for member → 200 (admin role)
  30. POST admin check → 403 when not admin
  31. POST admin check → 404 when member not in account
  32. POST platform check → 200 (require_admin dependency mocked)
  33. POST self-check with eligible=False → still returns 200 (not an HTTP error)
  34. POST self-check with all optional fields → 200
  35. POST with requires_approval=True → 200 with requires_approval in response
  36. POST with auto_approved=True → 200 with auto_approved in response
  37. POST self-check returns denial_reasons list in response
  38. POST admin check validates member belongs to account
  39. POST platform check passes correct account_id and member_id to service
  40. POST self-check: quota_checks list has three entries (daily/weekly/monthly)
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.corporate_booking_eligibility import (
    BookingEligibilityResponse,
    BookingRideParams,
    QuotaCheckSummary,
)
from app.services.corporate_booking_eligibility import (
    _get_current_month_member_spend,
    check_booking_eligibility,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 10
MEMBER_ID = 5
USER_ID = 1
ADMIN_USER_ID = 2
CHAIN_ID = 7
RULE_ID = 3

_SERVICE = "app.services.corporate_booking_eligibility"
_ROUTER = "app.api.v1.corporate_booking_eligibility"

_NOW = datetime(2026, 4, 16, 9, 0, 0, tzinfo=timezone.utc)  # Thursday 09:00 UTC
_SAT_2AM = datetime(2026, 4, 18, 2, 0, 0, tzinfo=timezone.utc)  # Saturday 02:00 UTC
_MON_8AM = datetime(2026, 4, 20, 8, 0, 0, tzinfo=timezone.utc)  # Monday 08:00 UTC


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_member(
    member_id: int = MEMBER_ID,
    user_id: int = USER_ID,
    account_id: int = ACCOUNT_ID,
    monthly_spend_limit: Decimal | None = None,
    is_active: bool = True,
) -> MagicMock:
    m = MagicMock()
    m.id = member_id
    m.user_id = user_id
    m.account_id = account_id
    m.monthly_spend_limit = monthly_spend_limit
    m.is_active = is_active
    return m


def _make_effective_policy(
    allowed_vehicle_categories=None,
    max_per_ride_usd=None,
    max_per_member_monthly_usd=None,
    require_purpose=False,
    approved_purposes=None,
    business_hours_only=False,
) -> MagicMock:
    p = MagicMock()
    p.allowed_vehicle_categories = allowed_vehicle_categories
    p.max_per_ride_usd = max_per_ride_usd
    p.max_per_member_monthly_usd = max_per_member_monthly_usd
    p.require_purpose = require_purpose
    p.approved_purposes = approved_purposes
    p.business_hours_only = business_hours_only
    return p


def _make_blackout(
    bp_id=1,
    override_allowed=False,
    override_requires_approval=False,
) -> MagicMock:
    bp = MagicMock()
    bp.id = bp_id
    bp.override_allowed = override_allowed
    bp.override_requires_approval = override_requires_approval
    return bp


def _make_quota_check(
    period="daily",
    quota_active=False,
    max_rides=0,
    current_period_rides=0,
    remaining_rides=0,
    quota_exceeded=False,
) -> MagicMock:
    q = MagicMock()
    q.period = period
    q.quota_active = quota_active
    q.max_rides = max_rides
    q.current_period_rides = current_period_rides
    q.remaining_rides = remaining_rides
    q.quota_exceeded = quota_exceeded
    return q


def _make_chain(chain_id: int = CHAIN_ID) -> MagicMock:
    c = MagicMock()
    c.id = chain_id
    return c


def _make_rule(rule_id: int = RULE_ID) -> MagicMock:
    r = MagicMock()
    r.id = rule_id
    return r


def _default_params(**kwargs) -> BookingRideParams:
    defaults = dict(
        vehicle_category="standard",
        estimated_cost_usd=Decimal("25.00"),
        trip_purpose_id=None,
        trip_purpose_code=None,
        cost_center_id=None,
        ride_dt=_NOW,
    )
    defaults.update(kwargs)
    return BookingRideParams(**defaults)


def _make_db(member=None) -> AsyncMock:
    """Build a minimal mock AsyncSession for service tests."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = member
    # scalar_one for spend query
    result.scalar_one.return_value = 0
    db.execute = AsyncMock(return_value=result)
    return db


async def _run_check(
    member=None,
    effective_policy=None,
    blackout_periods=None,
    quota_daily=None,
    quota_weekly=None,
    quota_monthly=None,
    spend_usd=Decimal("0"),
    auto_approved=False,
    matched_rule=None,
    applicable_chain=None,
    params=None,
    account_id=ACCOUNT_ID,
    member_id=MEMBER_ID,
):
    """Helper that patches all service dependencies and calls check_booking_eligibility."""
    if member is None:
        member = _make_member()
    if effective_policy is None:
        effective_policy = _make_effective_policy()
    if blackout_periods is None:
        blackout_periods = []
    if quota_daily is None:
        quota_daily = _make_quota_check(period="daily")
    if quota_weekly is None:
        quota_weekly = _make_quota_check(period="weekly")
    if quota_monthly is None:
        quota_monthly = _make_quota_check(period="monthly")
    if params is None:
        params = _default_params()

    db = AsyncMock()

    # _get_member_or_404: first execute returns member (scalar_one_or_none)
    member_result = MagicMock()
    member_result.scalar_one_or_none.return_value = member

    # _get_current_month_member_spend: execute returns scalar_one = spend_usd
    spend_result = MagicMock()
    spend_result.scalar_one.return_value = spend_usd

    db.execute = AsyncMock(side_effect=[member_result, spend_result])

    quota_map = {"daily": quota_daily, "weekly": quota_weekly, "monthly": quota_monthly}

    async def _fake_get_quota(db, acct_id, uid, period):
        return quota_map[period]

    with (
        patch(f"{_SERVICE}.get_effective_policy_for_member", new_callable=AsyncMock, return_value=effective_policy),
        patch(f"{_SERVICE}.check_booking_blackout", new_callable=AsyncMock, return_value=blackout_periods),
        patch(f"{_SERVICE}.get_quota_usage", side_effect=_fake_get_quota),
        patch(f"{_SERVICE}.evaluate_auto_approval", new_callable=AsyncMock, return_value=(auto_approved, matched_rule)),
        patch(f"{_SERVICE}.find_applicable_chain", new_callable=AsyncMock, return_value=applicable_chain),
    ):
        return await check_booking_eligibility(db, account_id, member_id, params)


# ===========================================================================
# Service layer tests
# ===========================================================================


@pytest.mark.asyncio
async def test_all_checks_pass_no_chain():
    """Test 1: All checks pass, no approval chain → eligible, no approval needed."""
    result = await _run_check()

    assert result.eligible is True
    assert result.requires_approval is False
    assert result.auto_approved is False
    assert result.policy_check_passed is True
    assert result.in_blackout is False
    assert result.any_quota_exceeded is False
    assert result.spend_limit_exceeded is False
    assert result.denial_reasons == []


@pytest.mark.asyncio
async def test_all_checks_pass_approval_chain_found():
    """Test 2: All checks pass, approval chain found → eligible, requires_approval=True."""
    chain = _make_chain()
    result = await _run_check(applicable_chain=chain)

    assert result.eligible is True
    assert result.requires_approval is True
    assert result.auto_approved is False
    assert result.approval_chain_id == CHAIN_ID


@pytest.mark.asyncio
async def test_all_checks_pass_auto_approved():
    """Test 3: All checks pass, auto-approved → auto_approved=True, requires_approval=False."""
    rule = _make_rule()
    result = await _run_check(auto_approved=True, matched_rule=rule)

    assert result.eligible is True
    assert result.auto_approved is True
    assert result.requires_approval is False
    assert result.auto_approval_rule_id == RULE_ID


@pytest.mark.asyncio
async def test_policy_fails_vehicle_category():
    """Test 4: Vehicle category not in allowed list → eligible=False."""
    policy = _make_effective_policy(allowed_vehicle_categories=["xl", "black"])
    params = _default_params(vehicle_category="standard")
    result = await _run_check(effective_policy=policy, params=params)

    assert result.eligible is False
    assert result.policy_check_passed is False
    assert any("vehicle" in r.lower() or "category" in r.lower() for r in result.denial_reasons)
    assert result.policy_violation_reason is not None


@pytest.mark.asyncio
async def test_policy_fails_cost_exceeds_max():
    """Test 5: Cost exceeds max_per_ride_usd → eligible=False."""
    policy = _make_effective_policy(max_per_ride_usd=Decimal("20.00"))
    params = _default_params(estimated_cost_usd=Decimal("30.00"))
    result = await _run_check(effective_policy=policy, params=params)

    assert result.eligible is False
    assert result.policy_check_passed is False
    assert any("limit" in r.lower() or "cost" in r.lower() or "per-ride" in r.lower() for r in result.denial_reasons)


@pytest.mark.asyncio
async def test_policy_fails_purpose_required_but_missing():
    """Test 6: Purpose required but trip_purpose_code=None → eligible=False."""
    policy = _make_effective_policy(require_purpose=True)
    params = _default_params(trip_purpose_code=None)
    result = await _run_check(effective_policy=policy, params=params)

    assert result.eligible is False
    assert result.policy_check_passed is False
    assert any("purpose" in r.lower() for r in result.denial_reasons)


@pytest.mark.asyncio
async def test_policy_fails_purpose_not_in_approved():
    """Test 7: Purpose not in approved_purposes → eligible=False."""
    policy = _make_effective_policy(
        approved_purposes=["CLIENT_MEETING", "CONFERENCE"],
        require_purpose=True,
    )
    params = _default_params(trip_purpose_code="PERSONAL")
    result = await _run_check(effective_policy=policy, params=params)

    assert result.eligible is False
    assert result.policy_check_passed is False


@pytest.mark.asyncio
async def test_policy_fails_business_hours_only_weekend():
    """Test 8: business_hours_only but ride_dt is 2am UTC Saturday → eligible=False."""
    policy = _make_effective_policy(business_hours_only=True)
    params = _default_params(ride_dt=_SAT_2AM)
    result = await _run_check(effective_policy=policy, params=params)

    assert result.eligible is False
    assert result.policy_check_passed is False
    assert any("business hours" in r.lower() for r in result.denial_reasons)


@pytest.mark.asyncio
async def test_policy_passes_business_hours_only_monday_morning():
    """Test 9: business_hours_only but ride_dt is Monday 08:00 UTC → passes."""
    policy = _make_effective_policy(business_hours_only=True)
    params = _default_params(ride_dt=_MON_8AM)
    result = await _run_check(effective_policy=policy, params=params)

    assert result.policy_check_passed is True
    assert result.eligible is True


@pytest.mark.asyncio
async def test_blackout_hard_block():
    """Test 10: In blackout, override_allowed=False → eligible=False, in_blackout=True."""
    bp = _make_blackout(bp_id=11, override_allowed=False)
    result = await _run_check(blackout_periods=[bp])

    assert result.eligible is False
    assert result.in_blackout is True
    assert result.blackout_override_allowed is False
    assert 11 in result.blackout_period_ids
    assert any("blackout" in r.lower() for r in result.denial_reasons)


@pytest.mark.asyncio
async def test_blackout_override_allowed():
    """Test 11: In blackout, override_allowed=True → eligible=True, in_blackout=True."""
    bp = _make_blackout(bp_id=12, override_allowed=True, override_requires_approval=False)
    result = await _run_check(blackout_periods=[bp])

    assert result.eligible is True
    assert result.in_blackout is True
    assert result.blackout_override_allowed is True


@pytest.mark.asyncio
async def test_blackout_override_requires_approval():
    """Test 12: Blackout with override_requires_approval=True sets flag."""
    bp = _make_blackout(bp_id=13, override_allowed=True, override_requires_approval=True)
    result = await _run_check(blackout_periods=[bp])

    assert result.blackout_requires_approval is True
    assert result.in_blackout is True


@pytest.mark.asyncio
async def test_daily_quota_exceeded():
    """Test 13: Daily quota exceeded → eligible=False, any_quota_exceeded=True."""
    daily = _make_quota_check(period="daily", quota_active=True, max_rides=3, current_period_rides=3, remaining_rides=0, quota_exceeded=True)
    result = await _run_check(quota_daily=daily)

    assert result.eligible is False
    assert result.any_quota_exceeded is True
    assert any("daily" in r.lower() for r in result.denial_reasons)


@pytest.mark.asyncio
async def test_weekly_quota_exceeded():
    """Test 14: Weekly quota exceeded → eligible=False."""
    weekly = _make_quota_check(period="weekly", quota_active=True, max_rides=10, current_period_rides=10, remaining_rides=0, quota_exceeded=True)
    result = await _run_check(quota_weekly=weekly)

    assert result.eligible is False
    assert result.any_quota_exceeded is True
    assert any("weekly" in r.lower() for r in result.denial_reasons)


@pytest.mark.asyncio
async def test_monthly_quota_exceeded():
    """Test 15: Monthly quota exceeded → eligible=False."""
    monthly = _make_quota_check(period="monthly", quota_active=True, max_rides=30, current_period_rides=30, remaining_rides=0, quota_exceeded=True)
    result = await _run_check(quota_monthly=monthly)

    assert result.eligible is False
    assert result.any_quota_exceeded is True
    assert any("monthly" in r.lower() for r in result.denial_reasons)


@pytest.mark.asyncio
async def test_spend_limit_exceeded():
    """Test 16: Monthly spend limit exceeded → eligible=False."""
    member = _make_member(monthly_spend_limit=Decimal("100.00"))
    result = await _run_check(member=member, spend_usd=Decimal("100.00"))

    assert result.eligible is False
    assert result.spend_limit_exceeded is True
    assert result.monthly_spend_limit_usd == Decimal("100.00")
    assert any("spend" in r.lower() or "limit" in r.lower() for r in result.denial_reasons)


@pytest.mark.asyncio
async def test_spend_limit_not_set():
    """Test 17: No spend limit → spend_limit_exceeded=False, spend_remaining_usd=None."""
    member = _make_member(monthly_spend_limit=None)
    result = await _run_check(member=member, spend_usd=Decimal("500.00"))

    assert result.spend_limit_exceeded is False
    assert result.spend_remaining_usd is None
    assert result.monthly_spend_limit_usd is None
    assert result.eligible is True


@pytest.mark.asyncio
async def test_multiple_failures_accumulate_denial_reasons():
    """Test 18: Multiple failures → denial_reasons has multiple entries, eligible=False."""
    policy = _make_effective_policy(
        allowed_vehicle_categories=["xl"],
        max_per_ride_usd=Decimal("10.00"),
    )
    daily = _make_quota_check(period="daily", quota_active=True, max_rides=2, current_period_rides=2, remaining_rides=0, quota_exceeded=True)
    params = _default_params(vehicle_category="standard", estimated_cost_usd=Decimal("50.00"))
    result = await _run_check(effective_policy=policy, quota_daily=daily, params=params)

    assert result.eligible is False
    assert len(result.denial_reasons) >= 2


@pytest.mark.asyncio
async def test_member_not_found_raises_404():
    """Test 19: Member not found → raises HTTP 404."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    params = _default_params()
    with pytest.raises(HTTPException) as exc_info:
        await check_booking_eligibility(db, ACCOUNT_ID, 9999, params)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_quota_checks_all_three_periods():
    """Test 20: Quota checks list contains entries for daily, weekly, monthly."""
    result = await _run_check()

    assert len(result.quota_checks) == 3
    periods = {qc.period for qc in result.quota_checks}
    assert periods == {"daily", "weekly", "monthly"}


@pytest.mark.asyncio
async def test_auto_approval_rule_id_set():
    """Test 21: auto_approval_rule_id = matched_rule.id when auto_approved."""
    rule = _make_rule(rule_id=42)
    result = await _run_check(auto_approved=True, matched_rule=rule)

    assert result.auto_approval_rule_id == 42


@pytest.mark.asyncio
async def test_approval_chain_id_set():
    """Test 22: approval_chain_id = chain.id when requires_approval."""
    chain = _make_chain(chain_id=99)
    result = await _run_check(applicable_chain=chain)

    assert result.approval_chain_id == 99
    assert result.requires_approval is True


# ===========================================================================
# Schema validation tests
# ===========================================================================


def test_booking_ride_params_cost_must_be_positive():
    """Test 23: BookingRideParams: estimated_cost_usd must be > 0."""
    with pytest.raises(ValidationError):
        BookingRideParams(vehicle_category="standard", estimated_cost_usd=Decimal("0"))

    with pytest.raises(ValidationError):
        BookingRideParams(vehicle_category="standard", estimated_cost_usd=Decimal("-5"))


def test_booking_ride_params_optional_fields_default_none():
    """Test 24: BookingRideParams: all optional fields default to None."""
    params = BookingRideParams(vehicle_category="standard", estimated_cost_usd=Decimal("10"))
    assert params.trip_purpose_id is None
    assert params.trip_purpose_code is None
    assert params.cost_center_id is None
    assert params.ride_dt is None


def test_booking_eligibility_response_construction():
    """Test 25: BookingEligibilityResponse: construction with all fields."""
    quota = QuotaCheckSummary(
        period="daily",
        quota_active=False,
        max_rides=0,
        current_period_rides=0,
        remaining_rides=0,
        quota_exceeded=False,
    )
    resp = BookingEligibilityResponse(
        eligible=True,
        requires_approval=False,
        auto_approved=False,
        auto_approval_rule_id=None,
        approval_chain_id=None,
        policy_check_passed=True,
        policy_violation_reason=None,
        in_blackout=False,
        blackout_override_allowed=False,
        blackout_requires_approval=False,
        blackout_period_ids=[],
        quota_checks=[quota],
        any_quota_exceeded=False,
        monthly_spend_limit_usd=Decimal("500.00"),
        current_month_spend_usd=Decimal("50.00"),
        spend_remaining_usd=Decimal("450.00"),
        spend_limit_exceeded=False,
        denial_reasons=[],
    )
    assert resp.eligible is True
    assert resp.monthly_spend_limit_usd == Decimal("500.00")
    assert len(resp.quota_checks) == 1


def test_quota_check_summary_construction():
    """Test 26: QuotaCheckSummary: construction with all fields."""
    q = QuotaCheckSummary(
        period="weekly",
        quota_active=True,
        max_rides=10,
        current_period_rides=7,
        remaining_rides=3,
        quota_exceeded=False,
    )
    assert q.period == "weekly"
    assert q.remaining_rides == 3
    assert q.quota_exceeded is False


# ===========================================================================
# API layer tests
# ===========================================================================

_SELF_CHECK_URL = "/api/v1/corporate/accounts/me/rides/check-eligibility"
_ADMIN_CHECK_URL = f"/api/v1/corporate/accounts/me/members/{MEMBER_ID}/rides/check-eligibility"
_PLATFORM_URL = f"/api/v1/platform/corporate/accounts/{ACCOUNT_ID}/members/{MEMBER_ID}/rides/check-eligibility"

_ELIGIBLE_RESPONSE = BookingEligibilityResponse(
    eligible=True,
    requires_approval=False,
    auto_approved=False,
    auto_approval_rule_id=None,
    approval_chain_id=None,
    policy_check_passed=True,
    policy_violation_reason=None,
    in_blackout=False,
    blackout_override_allowed=False,
    blackout_requires_approval=False,
    blackout_period_ids=[],
    quota_checks=[
        QuotaCheckSummary(period="daily", quota_active=False, max_rides=0, current_period_rides=0, remaining_rides=0, quota_exceeded=False),
        QuotaCheckSummary(period="weekly", quota_active=False, max_rides=0, current_period_rides=0, remaining_rides=0, quota_exceeded=False),
        QuotaCheckSummary(period="monthly", quota_active=False, max_rides=0, current_period_rides=0, remaining_rides=0, quota_exceeded=False),
    ],
    any_quota_exceeded=False,
    monthly_spend_limit_usd=None,
    current_month_spend_usd=Decimal("0"),
    spend_remaining_usd=None,
    spend_limit_exceeded=False,
    denial_reasons=[],
)

_INELIGIBLE_RESPONSE = BookingEligibilityResponse(
    eligible=False,
    requires_approval=False,
    auto_approved=False,
    auto_approval_rule_id=None,
    approval_chain_id=None,
    policy_check_passed=False,
    policy_violation_reason="Vehicle category not allowed.",
    in_blackout=False,
    blackout_override_allowed=False,
    blackout_requires_approval=False,
    blackout_period_ids=[],
    quota_checks=[
        QuotaCheckSummary(period="daily", quota_active=False, max_rides=0, current_period_rides=0, remaining_rides=0, quota_exceeded=False),
        QuotaCheckSummary(period="weekly", quota_active=False, max_rides=0, current_period_rides=0, remaining_rides=0, quota_exceeded=False),
        QuotaCheckSummary(period="monthly", quota_active=False, max_rides=0, current_period_rides=0, remaining_rides=0, quota_exceeded=False),
    ],
    any_quota_exceeded=False,
    monthly_spend_limit_usd=None,
    current_month_spend_usd=Decimal("0"),
    spend_remaining_usd=None,
    spend_limit_exceeded=False,
    denial_reasons=["Vehicle category not allowed."],
)

_APPROVAL_RESPONSE = BookingEligibilityResponse(
    **{**_ELIGIBLE_RESPONSE.model_dump(), "requires_approval": True, "approval_chain_id": CHAIN_ID}
)

_AUTO_APPROVED_RESPONSE = BookingEligibilityResponse(
    **{**_ELIGIBLE_RESPONSE.model_dump(), "auto_approved": True, "auto_approval_rule_id": RULE_ID}
)

_VALID_BODY = {"vehicle_category": "standard", "estimated_cost_usd": "25.00"}


def _mock_account(account_id: int = ACCOUNT_ID):
    a = MagicMock()
    a.id = account_id
    return a


def _mock_user(user_id: int = USER_ID):
    u = MagicMock()
    u.id = user_id
    u.is_active = True
    return u


@pytest.mark.anyio
async def test_api_self_check_200():
    """Test 27: POST self-check → 200, eligible response."""
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
            patch(f"{_ROUTER}._resolve_member_id", new_callable=AsyncMock, return_value=MEMBER_ID),
            patch(f"{_ROUTER}.check_booking_eligibility", new_callable=AsyncMock, return_value=_ELIGIBLE_RESPONSE),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(_SELF_CHECK_URL, json=_VALID_BODY)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["eligible"] is True


@pytest.mark.anyio
async def test_api_self_check_404_not_corporate_member():
    """Test 28: POST self-check → 404 when not corporate member."""
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
                resp = await ac.post(_SELF_CHECK_URL, json=_VALID_BODY)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


@pytest.mark.anyio
async def test_api_admin_check_200():
    """Test 29: POST admin check for member → 200 (admin role)."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user(user_id=ADMIN_USER_ID)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account()),
            patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock),
            patch(f"{_ROUTER}._verify_member_in_account", new_callable=AsyncMock),
            patch(f"{_ROUTER}.check_booking_eligibility", new_callable=AsyncMock, return_value=_ELIGIBLE_RESPONSE),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(_ADMIN_CHECK_URL, json=_VALID_BODY)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_api_admin_check_403_not_admin():
    """Test 30: POST admin check → 403 when not admin."""
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
                f"{_ROUTER}._require_account_admin",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=403, detail="Not admin."),
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(_ADMIN_CHECK_URL, json=_VALID_BODY)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403


@pytest.mark.anyio
async def test_api_admin_check_404_member_not_in_account():
    """Test 31: POST admin check → 404 when member not in account."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user(user_id=ADMIN_USER_ID)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account()),
            patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock),
            patch(
                f"{_ROUTER}._verify_member_in_account",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=404, detail="Member not found."),
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(_ADMIN_CHECK_URL, json=_VALID_BODY)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


@pytest.mark.anyio
async def test_api_platform_check_200():
    """Test 32: POST platform check → 200 (require_admin dependency mocked)."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin

    mock_db = AsyncMock()
    mock_admin = _mock_user(user_id=ADMIN_USER_ID)
    app.dependency_overrides[get_current_user] = lambda: mock_admin
    app.dependency_overrides[require_admin] = lambda: mock_admin
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._verify_member_in_account", new_callable=AsyncMock),
            patch(f"{_ROUTER}.check_booking_eligibility", new_callable=AsyncMock, return_value=_ELIGIBLE_RESPONSE),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(_PLATFORM_URL, json=_VALID_BODY)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_api_self_check_ineligible_returns_200():
    """Test 33: POST self-check with eligible=False → still returns 200."""
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
            patch(f"{_ROUTER}._resolve_member_id", new_callable=AsyncMock, return_value=MEMBER_ID),
            patch(f"{_ROUTER}.check_booking_eligibility", new_callable=AsyncMock, return_value=_INELIGIBLE_RESPONSE),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(_SELF_CHECK_URL, json=_VALID_BODY)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["eligible"] is False


@pytest.mark.anyio
async def test_api_self_check_all_optional_fields():
    """Test 34: POST self-check with all optional fields → 200."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    body = {
        "vehicle_category": "xl",
        "estimated_cost_usd": "50.00",
        "trip_purpose_id": 5,
        "trip_purpose_code": "CLIENT_MEETING",
        "cost_center_id": 3,
        "ride_dt": "2026-04-20T08:00:00Z",
    }

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account()),
            patch(f"{_ROUTER}._resolve_member_id", new_callable=AsyncMock, return_value=MEMBER_ID),
            patch(f"{_ROUTER}.check_booking_eligibility", new_callable=AsyncMock, return_value=_ELIGIBLE_RESPONSE),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(_SELF_CHECK_URL, json=body)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_api_self_check_requires_approval_in_response():
    """Test 35: POST with requires_approval=True → 200 with requires_approval in response."""
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
            patch(f"{_ROUTER}._resolve_member_id", new_callable=AsyncMock, return_value=MEMBER_ID),
            patch(f"{_ROUTER}.check_booking_eligibility", new_callable=AsyncMock, return_value=_APPROVAL_RESPONSE),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(_SELF_CHECK_URL, json=_VALID_BODY)
    finally:
        app.dependency_overrides.clear()

    data = resp.json()
    assert resp.status_code == 200
    assert data["requires_approval"] is True
    assert data["approval_chain_id"] == CHAIN_ID


@pytest.mark.anyio
async def test_api_self_check_auto_approved_in_response():
    """Test 36: POST with auto_approved=True → 200 with auto_approved in response."""
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
            patch(f"{_ROUTER}._resolve_member_id", new_callable=AsyncMock, return_value=MEMBER_ID),
            patch(f"{_ROUTER}.check_booking_eligibility", new_callable=AsyncMock, return_value=_AUTO_APPROVED_RESPONSE),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(_SELF_CHECK_URL, json=_VALID_BODY)
    finally:
        app.dependency_overrides.clear()

    data = resp.json()
    assert resp.status_code == 200
    assert data["auto_approved"] is True
    assert data["auto_approval_rule_id"] == RULE_ID


@pytest.mark.anyio
async def test_api_self_check_denial_reasons_in_response():
    """Test 37: POST self-check returns denial_reasons list in response."""
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
            patch(f"{_ROUTER}._resolve_member_id", new_callable=AsyncMock, return_value=MEMBER_ID),
            patch(f"{_ROUTER}.check_booking_eligibility", new_callable=AsyncMock, return_value=_INELIGIBLE_RESPONSE),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(_SELF_CHECK_URL, json=_VALID_BODY)
    finally:
        app.dependency_overrides.clear()

    data = resp.json()
    assert isinstance(data["denial_reasons"], list)
    assert len(data["denial_reasons"]) > 0


@pytest.mark.anyio
async def test_api_admin_check_validates_member_in_account():
    """Test 38: POST admin check validates member belongs to account."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_db = AsyncMock()
    mock_user = _mock_user(user_id=ADMIN_USER_ID)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with (
            patch(f"{_ROUTER}._resolve_account", new_callable=AsyncMock, return_value=_mock_account()),
            patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock),
            patch(
                f"{_ROUTER}._verify_member_in_account",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=404, detail="Not in account."),
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(_ADMIN_CHECK_URL, json=_VALID_BODY)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


@pytest.mark.anyio
async def test_api_platform_check_passes_correct_ids():
    """Test 39: POST platform check passes correct account_id and member_id to service."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin

    mock_db = AsyncMock()
    mock_admin = _mock_user(user_id=ADMIN_USER_ID)
    app.dependency_overrides[get_current_user] = lambda: mock_admin
    app.dependency_overrides[require_admin] = lambda: mock_admin
    app.dependency_overrides[get_db] = lambda: mock_db

    captured_args = {}

    async def _fake_check(db, acct_id, mem_id, params):
        captured_args["account_id"] = acct_id
        captured_args["member_id"] = mem_id
        return _ELIGIBLE_RESPONSE

    try:
        with (
            patch(f"{_ROUTER}._verify_member_in_account", new_callable=AsyncMock),
            patch(f"{_ROUTER}.check_booking_eligibility", side_effect=_fake_check),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                await ac.post(_PLATFORM_URL, json=_VALID_BODY)
    finally:
        app.dependency_overrides.clear()

    assert captured_args["account_id"] == ACCOUNT_ID
    assert captured_args["member_id"] == MEMBER_ID


@pytest.mark.anyio
async def test_api_self_check_quota_checks_three_entries():
    """Test 40: POST self-check: quota_checks list has three entries (daily/weekly/monthly)."""
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
            patch(f"{_ROUTER}._resolve_member_id", new_callable=AsyncMock, return_value=MEMBER_ID),
            patch(f"{_ROUTER}.check_booking_eligibility", new_callable=AsyncMock, return_value=_ELIGIBLE_RESPONSE),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(_SELF_CHECK_URL, json=_VALID_BODY)
    finally:
        app.dependency_overrides.clear()

    data = resp.json()
    assert len(data["quota_checks"]) == 3
    periods = {qc["period"] for qc in data["quota_checks"]}
    assert periods == {"daily", "weekly", "monthly"}
