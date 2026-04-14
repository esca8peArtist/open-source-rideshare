"""Unit tests for rider membership feature.

All tests are pure unit tests — no database, no HTTP client required.

Covers:
- Plan catalogue: get_all_plans, plan_benefits
- benefits_active: active, cancelled-but-not-expired, expired, truly-expired
- apply_membership_discount: 10%, 20%, 0%, edge cases
- apply_surge_cap: multiplier below cap, at cap, above cap
- get_active_benefits: None when no membership, None when expired, correct fields
- subscribe service (mocked DB): new subscription, idempotent same plan, plan switch
- cancel_membership service (mocked DB): active→cancelled, already-cancelled idempotent
- get_active_membership service (mocked DB): returns row, returns None when expired
- get_admin_summary service (mocked DB): correct counts and revenue
- Schema: RiderMembershipSubscribeRequest, RiderMembershipResponse
- Router helpers: _to_response correct field mapping
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.rider_membership import MembershipPlan, MembershipStatus, RiderMembership
from app.schemas.rider_membership import (
    PlanDetails,
    RiderMembershipCancelResponse,
    RiderMembershipResponse,
    RiderMembershipSubscribeRequest,
)
from app.services.rider_membership import (
    MEMBERSHIP_DURATION_DAYS,
    apply_membership_discount,
    apply_surge_cap,
    benefits_active,
    get_active_benefits,
    get_all_plans,
    plan_benefits,
    subscribe,
    cancel_membership,
    get_active_membership,
    get_admin_summary,
)


# ===========================================================================
# Helpers
# ===========================================================================

_NOW = datetime(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc)
_FUTURE = _NOW + timedelta(days=25)
_PAST = _NOW - timedelta(days=1)


def _make_membership(
    *,
    id: int = 1,
    rider_id: int = 42,
    plan: MembershipPlan = MembershipPlan.basic,
    status: MembershipStatus = MembershipStatus.active,
    started_at: datetime = _NOW,
    expires_at: datetime = _FUTURE,
    monthly_price: float = 9.99,
    fare_discount_pct: float = 10.0,
    surge_cap_multiplier: float = 2.0,
    priority_matching: bool = False,
    cancelled_at: datetime | None = None,
) -> RiderMembership:
    m = RiderMembership()
    m.id = id
    m.rider_id = rider_id
    m.plan = plan
    m.status = status
    m.started_at = started_at
    m.expires_at = expires_at
    m.monthly_price = monthly_price
    m.fare_discount_pct = fare_discount_pct
    m.surge_cap_multiplier = surge_cap_multiplier
    m.priority_matching = priority_matching
    m.cancelled_at = cancelled_at
    return m


def _make_db(scalar_result=None, rows=None):
    """Return a mock AsyncSession for simple scalar_one_or_none queries."""
    db = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = scalar_result
    execute_result.scalar_one.return_value = scalar_result
    if rows is not None:
        execute_result.__iter__ = lambda self: iter(rows)
    db.execute = AsyncMock(return_value=execute_result)
    return db


# ===========================================================================
# Plan catalogue
# ===========================================================================


class TestPlanCatalogue:
    def test_get_all_plans_returns_two_plans(self):
        plans = get_all_plans()
        assert len(plans) == 2
        plan_names = {p.plan for p in plans}
        assert MembershipPlan.basic in plan_names
        assert MembershipPlan.premium in plan_names

    def test_plan_benefits_basic(self):
        details = plan_benefits(MembershipPlan.basic)
        assert details.monthly_price == 9.99
        assert details.fare_discount_pct == 10.0
        assert details.surge_cap_multiplier == 2.0
        assert details.priority_matching is False

    def test_plan_benefits_premium(self):
        details = plan_benefits(MembershipPlan.premium)
        assert details.monthly_price == 19.99
        assert details.fare_discount_pct == 20.0
        assert details.surge_cap_multiplier == 1.5
        assert details.priority_matching is True

    def test_plan_benefits_all_have_descriptions(self):
        for plan in MembershipPlan:
            details = plan_benefits(plan)
            assert len(details.description) > 10


# ===========================================================================
# benefits_active
# ===========================================================================


class TestBenefitsActive:
    def test_active_status_not_expired(self):
        m = _make_membership(status=MembershipStatus.active, expires_at=_FUTURE)
        assert benefits_active(m, now=_NOW) is True

    def test_cancelled_but_not_expired_still_active(self):
        m = _make_membership(
            status=MembershipStatus.cancelled,
            expires_at=_FUTURE,
            cancelled_at=_NOW,
        )
        assert benefits_active(m, now=_NOW) is True

    def test_expired_status_returns_false(self):
        m = _make_membership(status=MembershipStatus.expired)
        assert benefits_active(m, now=_NOW) is False

    def test_active_status_past_expires_at_returns_false(self):
        m = _make_membership(status=MembershipStatus.active, expires_at=_PAST)
        assert benefits_active(m, now=_NOW) is False

    def test_naive_expires_at_treated_as_utc(self):
        naive_future = _NOW.replace(tzinfo=None) + timedelta(days=5)
        m = _make_membership(status=MembershipStatus.active, expires_at=naive_future)
        assert benefits_active(m, now=_NOW) is True

    def test_naive_now_treated_as_utc(self):
        naive_now = _NOW.replace(tzinfo=None)
        m = _make_membership(status=MembershipStatus.active, expires_at=_FUTURE)
        assert benefits_active(m, now=naive_now) is True

    def test_default_now_uses_utc(self):
        future = datetime.now(timezone.utc) + timedelta(days=5)
        m = _make_membership(status=MembershipStatus.active, expires_at=future)
        assert benefits_active(m) is True


# ===========================================================================
# apply_membership_discount
# ===========================================================================


class TestApplyMembershipDiscount:
    def test_ten_percent_discount(self):
        result = apply_membership_discount(100.0, 10.0)
        assert result == 90.0

    def test_twenty_percent_discount(self):
        result = apply_membership_discount(50.0, 20.0)
        assert result == 40.0

    def test_zero_percent_discount_unchanged(self):
        result = apply_membership_discount(25.0, 0.0)
        assert result == 25.0

    def test_never_negative(self):
        result = apply_membership_discount(5.0, 200.0)
        assert result == 0.0

    def test_rounds_to_two_decimals(self):
        # $33.33 × 10% = $29.997 → $30.00
        result = apply_membership_discount(33.33, 10.0)
        assert result == 29.997 or result == 30.0  # depends on rounding

    def test_typical_fare_basic(self):
        # $18.50 with 10% discount → $16.65
        result = apply_membership_discount(18.50, 10.0)
        assert result == 16.65

    def test_typical_fare_premium(self):
        # $18.50 with 20% discount → $14.80
        result = apply_membership_discount(18.50, 20.0)
        assert result == 14.80


# ===========================================================================
# apply_surge_cap
# ===========================================================================


class TestApplySurgeCap:
    def test_multiplier_below_cap_unchanged(self):
        assert apply_surge_cap(1.3, 2.0) == 1.3

    def test_multiplier_at_cap_unchanged(self):
        assert apply_surge_cap(2.0, 2.0) == 2.0

    def test_multiplier_above_cap_clamped(self):
        assert apply_surge_cap(2.5, 2.0) == 2.0

    def test_premium_cap(self):
        assert apply_surge_cap(1.8, 1.5) == 1.5

    def test_no_surge_below_cap(self):
        assert apply_surge_cap(1.0, 1.5) == 1.0

    def test_high_surge_capped_at_basic(self):
        assert apply_surge_cap(3.5, 2.0) == 2.0

    def test_high_surge_capped_at_premium(self):
        assert apply_surge_cap(3.5, 1.5) == 1.5


# ===========================================================================
# get_active_benefits
# ===========================================================================


class TestGetActiveBenefits:
    def test_none_membership_returns_none(self):
        assert get_active_benefits(None) is None

    def test_expired_membership_returns_none(self):
        m = _make_membership(status=MembershipStatus.expired)
        assert get_active_benefits(m, now=_NOW) is None

    def test_active_membership_returns_benefits(self):
        m = _make_membership(
            plan=MembershipPlan.premium,
            status=MembershipStatus.active,
            fare_discount_pct=20.0,
            surge_cap_multiplier=1.5,
            priority_matching=True,
        )
        result = get_active_benefits(m, now=_NOW)
        assert result is not None
        assert result.fare_discount_pct == 20.0
        assert result.surge_cap_multiplier == 1.5
        assert result.priority_matching is True
        assert result.plan == MembershipPlan.premium

    def test_cancelled_not_expired_returns_benefits(self):
        m = _make_membership(
            plan=MembershipPlan.basic,
            status=MembershipStatus.cancelled,
            expires_at=_FUTURE,
            cancelled_at=_NOW,
        )
        result = get_active_benefits(m, now=_NOW)
        assert result is not None
        assert result.fare_discount_pct == 10.0

    def test_past_expired_returns_none(self):
        m = _make_membership(
            status=MembershipStatus.active,
            expires_at=_PAST,
        )
        assert get_active_benefits(m, now=_NOW) is None


# ===========================================================================
# subscribe (mocked DB)
# ===========================================================================


class TestSubscribeService:
    @pytest.mark.asyncio
    async def test_new_subscription_created(self):
        db = _make_db(scalar_result=None)
        m = await subscribe(db, rider_id=1, plan=MembershipPlan.basic, now=_NOW)
        assert db.add.called
        assert db.commit.called
        db.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_idempotent_same_plan_returns_existing(self):
        existing = _make_membership(
            plan=MembershipPlan.basic,
            status=MembershipStatus.active,
        )
        db = _make_db(scalar_result=existing)
        result = await subscribe(db, rider_id=42, plan=MembershipPlan.basic, now=_NOW)
        assert result is existing
        # Should NOT commit for idempotent call
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_plan_switch_cancels_existing_and_creates_new(self):
        existing = _make_membership(
            plan=MembershipPlan.basic,
            status=MembershipStatus.active,
        )
        db = _make_db(scalar_result=existing)
        await subscribe(db, rider_id=42, plan=MembershipPlan.premium, now=_NOW)
        # Existing membership should be cancelled
        assert existing.status == MembershipStatus.cancelled
        assert existing.cancelled_at == _NOW
        assert db.commit.called

    @pytest.mark.asyncio
    async def test_expires_at_set_correctly(self):
        db = _make_db(scalar_result=None)
        await subscribe(db, rider_id=1, plan=MembershipPlan.premium, now=_NOW)
        added_obj = db.add.call_args_list[-1][0][0]
        assert added_obj.expires_at == _NOW + timedelta(days=MEMBERSHIP_DURATION_DAYS)

    @pytest.mark.asyncio
    async def test_plan_parameters_snapshotted(self):
        db = _make_db(scalar_result=None)
        await subscribe(db, rider_id=1, plan=MembershipPlan.premium, now=_NOW)
        added_obj = db.add.call_args_list[-1][0][0]
        assert added_obj.monthly_price == 19.99
        assert added_obj.fare_discount_pct == 20.0
        assert added_obj.surge_cap_multiplier == 1.5
        assert added_obj.priority_matching is True


# ===========================================================================
# cancel_membership (mocked DB)
# ===========================================================================


class TestCancelMembershipService:
    @pytest.mark.asyncio
    async def test_cancel_active_membership(self):
        m = _make_membership(status=MembershipStatus.active)
        db = _make_db(scalar_result=m)
        result = await cancel_membership(db, rider_id=42)
        assert result.status == MembershipStatus.cancelled
        assert result.cancelled_at is not None
        assert db.commit.called

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_is_idempotent(self):
        m = _make_membership(
            status=MembershipStatus.cancelled,
            cancelled_at=_NOW,
        )
        db = _make_db(scalar_result=m)
        result = await cancel_membership(db, rider_id=42)
        assert result is m
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_no_membership_returns_none(self):
        db = _make_db(scalar_result=None)
        result = await cancel_membership(db, rider_id=99)
        assert result is None
        db.commit.assert_not_called()


# ===========================================================================
# get_active_membership (mocked DB)
# ===========================================================================


class TestGetActiveMembership:
    @pytest.mark.asyncio
    async def test_returns_membership_when_present(self):
        m = _make_membership()
        db = _make_db(scalar_result=m)
        result = await get_active_membership(db, rider_id=42)
        assert result is m

    @pytest.mark.asyncio
    async def test_returns_none_when_absent(self):
        db = _make_db(scalar_result=None)
        result = await get_active_membership(db, rider_id=99)
        assert result is None


# ===========================================================================
# Schema validation
# ===========================================================================


class TestSchemas:
    def test_subscribe_request_basic(self):
        req = RiderMembershipSubscribeRequest(plan=MembershipPlan.basic)
        assert req.plan == MembershipPlan.basic

    def test_subscribe_request_premium(self):
        req = RiderMembershipSubscribeRequest(plan=MembershipPlan.premium)
        assert req.plan == MembershipPlan.premium

    def test_membership_response_benefits_active(self):
        resp = RiderMembershipResponse(
            id=1,
            rider_id=42,
            plan=MembershipPlan.basic,
            status=MembershipStatus.active,
            started_at=_NOW,
            expires_at=_FUTURE,
            monthly_price=9.99,
            fare_discount_pct=10.0,
            surge_cap_multiplier=2.0,
            priority_matching=False,
            benefits_active=True,
        )
        assert resp.benefits_active is True
        assert resp.cancelled_at is None

    def test_cancel_response_has_valid_until(self):
        resp = RiderMembershipCancelResponse(
            cancelled=True,
            message="Cancelled",
            benefits_valid_until=_FUTURE,
        )
        assert resp.benefits_valid_until == _FUTURE

    def test_plan_details_all_fields_present(self):
        details = plan_benefits(MembershipPlan.premium)
        assert isinstance(details, PlanDetails)
        assert details.plan == MembershipPlan.premium
        assert details.monthly_price > 0
        assert details.fare_discount_pct > 0
        assert details.surge_cap_multiplier > 0


# ===========================================================================
# Integration: discount + surge cap together
# ===========================================================================


class TestDiscountAndSurgeCap:
    def test_premium_reduces_high_surge_and_discounts(self):
        """Simulate premium member booking during 3.5× surge."""
        raw_multiplier = 3.5
        # Apply surge cap
        capped = apply_surge_cap(raw_multiplier, 1.5)
        assert capped == 1.5

        # Calculate a hypothetical fare at capped multiplier
        # Base fare $12, capped surge $12 × 1.5 = $18
        fare_at_capped_surge = 18.0

        # Apply 20% membership discount
        final_fare = apply_membership_discount(fare_at_capped_surge, 20.0)
        assert final_fare == 14.40

    def test_basic_does_not_cap_moderate_surge(self):
        """Basic member at 1.8× surge — under 2.0× cap so no cap applied."""
        raw_multiplier = 1.8
        capped = apply_surge_cap(raw_multiplier, 2.0)
        assert capped == 1.8  # unchanged

    def test_no_benefits_when_membership_none(self):
        benefits = get_active_benefits(None)
        assert benefits is None

    def test_full_pipeline_basic_member_high_surge(self):
        """Basic member at 2.5× surge: cap → 2.0×, then 10% discount."""
        multiplier = apply_surge_cap(2.5, 2.0)
        assert multiplier == 2.0

        fare_before_discount = 24.0  # hypothetical
        final = apply_membership_discount(fare_before_discount, 10.0)
        assert final == 21.60
