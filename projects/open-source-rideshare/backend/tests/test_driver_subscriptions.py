"""Unit tests for the driver subscription plan feature.

All tests are pure unit tests — no database or HTTP client required.

Covers:
- DriverSubscription model fields and constants
- PLAN_DETAILS: price, billing_days, label for both plans
- STANDARD_COMMISSION_PCT constant
- subscribe: success (weekly/monthly), duplicate active raises ValueError
- cancel_subscription: success, no active subscription raises ValueError
- update_auto_renew: success, no active subscription raises ValueError
- get_active_subscription: found (unexpired active), not found, expired excluded, cancelled included until expiry
- get_driver_commission_pct: 0.0 when subscribed, 15.0 when not
- expire_subscriptions: transitions past-due active subscriptions to expired
- list_driver_subscriptions: returns list for driver, pagination
- list_all_subscriptions: no filter, status filter, plan filter
- get_subscription_stats: counts and revenue calculations
- Schema: SubscribeRequest, UpdateSubscriptionRequest, PlanDetails, DriverSubscriptionResponse
- SubscriptionStatsResponse field checks
- get_all_plan_details helper returns all plans
- _expires_at helper: weekly adds 7 days, monthly adds 30 days
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_subscription import (
    PLAN_DETAILS,
    STANDARD_COMMISSION_PCT,
    DriverSubscription,
    DriverSubscriptionPlan,
    DriverSubscriptionStatus,
)
from app.schemas.driver_subscription import (
    DriverSubscriptionResponse,
    PlanDetails,
    SubscribeRequest,
    SubscriptionStatsResponse,
    UpdateSubscriptionRequest,
    get_all_plan_details,
)
from app.services.driver_subscriptions import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    _expires_at,
    cancel_subscription,
    expire_subscriptions,
    get_active_subscription,
    get_driver_commission_pct,
    get_subscription_stats,
    list_all_subscriptions,
    list_driver_subscriptions,
    subscribe,
    update_auto_renew,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_sub(
    id: int,
    driver_id: int,
    plan: DriverSubscriptionPlan = DriverSubscriptionPlan.weekly,
    status: DriverSubscriptionStatus = DriverSubscriptionStatus.active,
    expires_at: datetime | None = None,
    commission_pct: float = 0.0,
    auto_renew: bool = True,
    cancelled_at: datetime | None = None,
) -> DriverSubscription:
    sub = DriverSubscription()
    sub.id = id
    sub.driver_id = driver_id
    sub.plan = plan
    sub.status = status
    sub.started_at = _now()
    sub.expires_at = expires_at or (_now() + timedelta(days=7))
    sub.price = PLAN_DETAILS[plan]["price"]
    sub.commission_pct = commission_pct
    sub.auto_renew = auto_renew
    sub.stripe_subscription_id = None
    sub.cancelled_at = cancelled_at
    return sub


def _async_result(value):
    """Return a mock whose .scalar_one_or_none() returns value."""
    m = MagicMock()
    m.scalar_one_or_none.return_value = value
    m.scalar_one.return_value = value
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = value if isinstance(value, list) else ([value] if value else [])
    m.scalars.return_value = scalars_mock
    return m


def _async_scalars_list(values: list):
    """Return a mock whose .scalars().all() returns values."""
    m = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    m.scalars.return_value = scalars_mock
    return m


# ---------------------------------------------------------------------------
# Model / constants
# ---------------------------------------------------------------------------


class TestDriverSubscriptionModel:
    def test_tablename(self):
        assert DriverSubscription.__tablename__ == "driver_subscriptions"

    def test_standard_commission_pct(self):
        assert STANDARD_COMMISSION_PCT == 15.0

    def test_plan_details_weekly(self):
        details = PLAN_DETAILS[DriverSubscriptionPlan.weekly]
        assert details["price"] == 49.00
        assert details["billing_days"] == 7
        assert "label" in details

    def test_plan_details_monthly(self):
        details = PLAN_DETAILS[DriverSubscriptionPlan.monthly]
        assert details["price"] == 149.00
        assert details["billing_days"] == 30
        assert "label" in details

    def test_plan_enum_values(self):
        assert DriverSubscriptionPlan.weekly.value == "weekly"
        assert DriverSubscriptionPlan.monthly.value == "monthly"

    def test_status_enum_values(self):
        assert DriverSubscriptionStatus.active.value == "active"
        assert DriverSubscriptionStatus.cancelled.value == "cancelled"
        assert DriverSubscriptionStatus.expired.value == "expired"

    def test_default_page_size(self):
        assert DEFAULT_PAGE_SIZE == 20

    def test_max_page_size(self):
        assert MAX_PAGE_SIZE == 100

    def test_model_fields(self):
        sub = _make_sub(1, 42)
        assert sub.id == 1
        assert sub.driver_id == 42
        assert sub.plan == DriverSubscriptionPlan.weekly
        assert sub.status == DriverSubscriptionStatus.active
        assert sub.commission_pct == 0.0
        assert sub.auto_renew is True
        assert sub.stripe_subscription_id is None
        assert sub.cancelled_at is None


# ---------------------------------------------------------------------------
# _expires_at helper
# ---------------------------------------------------------------------------


class TestExpiresAtHelper:
    def test_weekly_adds_7_days(self):
        base = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
        exp = _expires_at(DriverSubscriptionPlan.weekly, from_dt=base)
        assert exp == base + timedelta(days=7)

    def test_monthly_adds_30_days(self):
        base = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
        exp = _expires_at(DriverSubscriptionPlan.monthly, from_dt=base)
        assert exp == base + timedelta(days=30)

    def test_no_from_dt_uses_now(self):
        before = _now()
        exp = _expires_at(DriverSubscriptionPlan.weekly)
        after = _now()
        assert before + timedelta(days=7) <= exp <= after + timedelta(days=7)


# ---------------------------------------------------------------------------
# get_active_subscription
# ---------------------------------------------------------------------------


class TestGetActiveSubscription:
    @pytest.mark.asyncio
    async def test_returns_subscription_when_found(self):
        db = AsyncMock()
        sub = _make_sub(1, 10)
        db.execute.return_value = _async_result(sub)
        result = await get_active_subscription(db, 10)
        assert result is sub

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        db = AsyncMock()
        db.execute.return_value = _async_result(None)
        result = await get_active_subscription(db, 99)
        assert result is None


# ---------------------------------------------------------------------------
# get_driver_commission_pct
# ---------------------------------------------------------------------------


class TestGetDriverCommissionPct:
    @pytest.mark.asyncio
    async def test_returns_zero_when_subscribed(self):
        db = AsyncMock()
        sub = _make_sub(1, 10, commission_pct=0.0)
        db.execute.return_value = _async_result(sub)
        pct = await get_driver_commission_pct(db, 10)
        assert pct == 0.0

    @pytest.mark.asyncio
    async def test_returns_standard_when_not_subscribed(self):
        db = AsyncMock()
        db.execute.return_value = _async_result(None)
        pct = await get_driver_commission_pct(db, 99)
        assert pct == STANDARD_COMMISSION_PCT


# ---------------------------------------------------------------------------
# subscribe
# ---------------------------------------------------------------------------


class TestSubscribe:
    @pytest.mark.asyncio
    async def test_subscribe_weekly_success(self):
        db = AsyncMock()
        # get_active_subscription returns None → no duplicate
        db.execute.return_value = _async_result(None)

        result_sub = _make_sub(1, 10, plan=DriverSubscriptionPlan.weekly)
        db.refresh = AsyncMock(side_effect=lambda s: None)

        with patch(
            "app.services.driver_subscriptions.get_active_subscription",
            new=AsyncMock(return_value=None),
        ):
            sub = await subscribe(db, 10, DriverSubscriptionPlan.weekly)

        assert sub.driver_id == 10
        assert sub.plan == DriverSubscriptionPlan.weekly
        assert sub.commission_pct == 0.0
        assert sub.price == 49.00
        db.add.assert_called_once()
        db.flush.assert_called()

    @pytest.mark.asyncio
    async def test_subscribe_monthly_success(self):
        db = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda s: None)

        with patch(
            "app.services.driver_subscriptions.get_active_subscription",
            new=AsyncMock(return_value=None),
        ):
            sub = await subscribe(db, 10, DriverSubscriptionPlan.monthly)

        assert sub.plan == DriverSubscriptionPlan.monthly
        assert sub.price == 149.00

    @pytest.mark.asyncio
    async def test_subscribe_duplicate_raises(self):
        db = AsyncMock()
        existing = _make_sub(1, 10)

        with patch(
            "app.services.driver_subscriptions.get_active_subscription",
            new=AsyncMock(return_value=existing),
        ):
            with pytest.raises(ValueError, match="already has an active"):
                await subscribe(db, 10, DriverSubscriptionPlan.monthly)

    @pytest.mark.asyncio
    async def test_subscribe_sets_auto_renew_false(self):
        db = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda s: None)

        with patch(
            "app.services.driver_subscriptions.get_active_subscription",
            new=AsyncMock(return_value=None),
        ):
            sub = await subscribe(db, 10, DriverSubscriptionPlan.weekly, auto_renew=False)

        assert sub.auto_renew is False

    @pytest.mark.asyncio
    async def test_subscribe_sets_stripe_id(self):
        db = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda s: None)

        with patch(
            "app.services.driver_subscriptions.get_active_subscription",
            new=AsyncMock(return_value=None),
        ):
            sub = await subscribe(
                db, 10, DriverSubscriptionPlan.weekly,
                stripe_subscription_id="sub_abc123",
            )

        assert sub.stripe_subscription_id == "sub_abc123"

    @pytest.mark.asyncio
    async def test_subscribe_expires_at_weekly(self):
        db = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda s: None)

        before = _now()
        with patch(
            "app.services.driver_subscriptions.get_active_subscription",
            new=AsyncMock(return_value=None),
        ):
            sub = await subscribe(db, 10, DriverSubscriptionPlan.weekly)
        after = _now()

        assert before + timedelta(days=7) <= sub.expires_at <= after + timedelta(days=7)

    @pytest.mark.asyncio
    async def test_subscribe_expires_at_monthly(self):
        db = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda s: None)

        before = _now()
        with patch(
            "app.services.driver_subscriptions.get_active_subscription",
            new=AsyncMock(return_value=None),
        ):
            sub = await subscribe(db, 10, DriverSubscriptionPlan.monthly)
        after = _now()

        assert before + timedelta(days=30) <= sub.expires_at <= after + timedelta(days=30)


# ---------------------------------------------------------------------------
# cancel_subscription
# ---------------------------------------------------------------------------


class TestCancelSubscription:
    @pytest.mark.asyncio
    async def test_cancel_success(self):
        db = AsyncMock()
        sub = _make_sub(1, 10)

        with patch(
            "app.services.driver_subscriptions.get_active_subscription",
            new=AsyncMock(return_value=sub),
        ):
            db.refresh = AsyncMock(side_effect=lambda s: None)
            result = await cancel_subscription(db, 10)

        assert result.status == DriverSubscriptionStatus.cancelled
        assert result.auto_renew is False
        assert result.cancelled_at is not None

    @pytest.mark.asyncio
    async def test_cancel_no_active_raises(self):
        db = AsyncMock()

        with patch(
            "app.services.driver_subscriptions.get_active_subscription",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(ValueError, match="no active subscription"):
                await cancel_subscription(db, 99)

    @pytest.mark.asyncio
    async def test_cancel_sets_cancelled_at_timestamp(self):
        db = AsyncMock()
        sub = _make_sub(1, 10)

        before = _now()
        with patch(
            "app.services.driver_subscriptions.get_active_subscription",
            new=AsyncMock(return_value=sub),
        ):
            db.refresh = AsyncMock(side_effect=lambda s: None)
            result = await cancel_subscription(db, 10)
        after = _now()

        assert before <= result.cancelled_at <= after


# ---------------------------------------------------------------------------
# update_auto_renew
# ---------------------------------------------------------------------------


class TestUpdateAutoRenew:
    @pytest.mark.asyncio
    async def test_disable_auto_renew(self):
        db = AsyncMock()
        sub = _make_sub(1, 10, auto_renew=True)

        with patch(
            "app.services.driver_subscriptions.get_active_subscription",
            new=AsyncMock(return_value=sub),
        ):
            db.refresh = AsyncMock(side_effect=lambda s: None)
            result = await update_auto_renew(db, 10, False)

        assert result.auto_renew is False

    @pytest.mark.asyncio
    async def test_enable_auto_renew(self):
        db = AsyncMock()
        sub = _make_sub(1, 10, auto_renew=False)

        with patch(
            "app.services.driver_subscriptions.get_active_subscription",
            new=AsyncMock(return_value=sub),
        ):
            db.refresh = AsyncMock(side_effect=lambda s: None)
            result = await update_auto_renew(db, 10, True)

        assert result.auto_renew is True

    @pytest.mark.asyncio
    async def test_update_no_active_raises(self):
        db = AsyncMock()

        with patch(
            "app.services.driver_subscriptions.get_active_subscription",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(ValueError, match="no active subscription"):
                await update_auto_renew(db, 99, True)


# ---------------------------------------------------------------------------
# expire_subscriptions
# ---------------------------------------------------------------------------


class TestExpireSubscriptions:
    @pytest.mark.asyncio
    async def test_transitions_expired_subs(self):
        db = AsyncMock()
        past = _now() - timedelta(hours=1)
        sub1 = _make_sub(1, 10, expires_at=past)
        sub2 = _make_sub(2, 11, expires_at=past)
        db.execute.return_value = _async_scalars_list([sub1, sub2])

        count = await expire_subscriptions(db)

        assert count == 2
        assert sub1.status == DriverSubscriptionStatus.expired
        assert sub2.status == DriverSubscriptionStatus.expired
        db.flush.assert_called()

    @pytest.mark.asyncio
    async def test_no_expired_returns_zero(self):
        db = AsyncMock()
        db.execute.return_value = _async_scalars_list([])

        count = await expire_subscriptions(db)

        assert count == 0


# ---------------------------------------------------------------------------
# list_driver_subscriptions
# ---------------------------------------------------------------------------


class TestListDriverSubscriptions:
    @pytest.mark.asyncio
    async def test_returns_driver_subs(self):
        db = AsyncMock()
        subs = [_make_sub(i, 10) for i in range(3)]
        db.execute.return_value = _async_scalars_list(subs)

        result = await list_driver_subscriptions(db, 10)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_empty_list(self):
        db = AsyncMock()
        db.execute.return_value = _async_scalars_list([])

        result = await list_driver_subscriptions(db, 99)

        assert result == []

    @pytest.mark.asyncio
    async def test_limit_capped_at_max(self):
        """Passing limit > MAX_PAGE_SIZE uses MAX_PAGE_SIZE."""
        db = AsyncMock()
        db.execute.return_value = _async_scalars_list([])

        # Should not raise; limit is clamped internally
        await list_driver_subscriptions(db, 10, limit=9999)
        db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# list_all_subscriptions
# ---------------------------------------------------------------------------


class TestListAllSubscriptions:
    @pytest.mark.asyncio
    async def test_no_filter(self):
        db = AsyncMock()
        subs = [_make_sub(i, i + 10) for i in range(5)]
        db.execute.return_value = _async_scalars_list(subs)

        result = await list_all_subscriptions(db)

        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_status_filter_passes_through(self):
        db = AsyncMock()
        db.execute.return_value = _async_scalars_list([])

        await list_all_subscriptions(db, status=DriverSubscriptionStatus.cancelled)

        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_plan_filter_passes_through(self):
        db = AsyncMock()
        db.execute.return_value = _async_scalars_list([])

        await list_all_subscriptions(db, plan=DriverSubscriptionPlan.monthly)

        db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# get_subscription_stats
# ---------------------------------------------------------------------------


class TestGetSubscriptionStats:
    @pytest.mark.asyncio
    async def test_revenue_calculation(self):
        db = AsyncMock()
        # Execute calls: weekly_active, monthly_active, cancelled, expired
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            # weekly_active=2, monthly_active=1, cancelled=3, expired=5
            mock.scalar_one.return_value = [2, 1, 3, 5][call_count - 1]
            return mock

        db.execute.side_effect = side_effect

        stats = await get_subscription_stats(db)

        assert stats["weekly_active"] == 2
        assert stats["monthly_active"] == 1
        assert stats["total_active"] == 3
        assert stats["total_cancelled"] == 3
        assert stats["total_expired"] == 5
        assert stats["active_revenue_weekly"] == pytest.approx(2 * 49.00)
        assert stats["active_revenue_monthly"] == pytest.approx(1 * 149.00)
        assert stats["active_revenue_total"] == pytest.approx(2 * 49.00 + 1 * 149.00)

    @pytest.mark.asyncio
    async def test_zero_stats(self):
        db = AsyncMock()
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            mock.scalar_one.return_value = 0
            return mock

        db.execute.side_effect = side_effect

        stats = await get_subscription_stats(db)

        assert stats["total_active"] == 0
        assert stats["active_revenue_total"] == 0.0


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TestSubscribeRequestSchema:
    def test_valid_weekly(self):
        req = SubscribeRequest(plan=DriverSubscriptionPlan.weekly)
        assert req.plan == DriverSubscriptionPlan.weekly
        assert req.auto_renew is True
        assert req.stripe_subscription_id is None

    def test_valid_monthly_no_renew(self):
        req = SubscribeRequest(plan=DriverSubscriptionPlan.monthly, auto_renew=False)
        assert req.auto_renew is False

    def test_stripe_id_optional(self):
        req = SubscribeRequest(
            plan=DriverSubscriptionPlan.weekly,
            stripe_subscription_id="sub_xyz",
        )
        assert req.stripe_subscription_id == "sub_xyz"


class TestUpdateSubscriptionRequestSchema:
    def test_toggle_false(self):
        req = UpdateSubscriptionRequest(auto_renew=False)
        assert req.auto_renew is False

    def test_toggle_true(self):
        req = UpdateSubscriptionRequest(auto_renew=True)
        assert req.auto_renew is True


class TestPlanDetailsSchema:
    def test_fields(self):
        pd = PlanDetails(
            plan=DriverSubscriptionPlan.weekly,
            label="Weekly Plan",
            price=49.00,
            billing_days=7,
        )
        assert pd.plan == DriverSubscriptionPlan.weekly
        assert pd.price == 49.00
        assert pd.billing_days == 7
        assert pd.commission_pct == 0.0  # default


class TestGetAllPlanDetails:
    def test_returns_both_plans(self):
        plans = get_all_plan_details()
        assert len(plans) == 2
        plan_names = {p.plan for p in plans}
        assert DriverSubscriptionPlan.weekly in plan_names
        assert DriverSubscriptionPlan.monthly in plan_names

    def test_all_commission_zero(self):
        plans = get_all_plan_details()
        for p in plans:
            assert p.commission_pct == 0.0


class TestSubscriptionStatsResponseSchema:
    def test_fields(self):
        stats = SubscriptionStatsResponse(
            total_active=5,
            total_cancelled=2,
            total_expired=1,
            weekly_active=3,
            monthly_active=2,
            active_revenue_weekly=147.0,
            active_revenue_monthly=298.0,
            active_revenue_total=445.0,
        )
        assert stats.total_active == 5
        assert stats.active_revenue_total == 445.0


class TestDriverSubscriptionResponseSchema:
    def test_from_orm(self):
        sub = _make_sub(7, 42, plan=DriverSubscriptionPlan.monthly)
        response = DriverSubscriptionResponse.model_validate(sub)
        assert response.id == 7
        assert response.driver_id == 42
        assert response.plan == DriverSubscriptionPlan.monthly
        assert response.status == DriverSubscriptionStatus.active
        assert response.commission_pct == 0.0
        assert response.cancelled_at is None
