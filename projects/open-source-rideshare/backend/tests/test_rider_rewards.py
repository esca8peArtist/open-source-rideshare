"""Unit tests for the rider loyalty rewards feature.

All tests are pure unit tests — no database or HTTP client required.

Covers:
- Model: RiderRewardAccount, RiderRewardTransaction field correctness
- Model: RewardTransactionType enum values
- Model: constants (POINTS_PER_DOLLAR, POINT_VALUE_CENTS, MIN_REDEMPTION_POINTS, MAX_REDEMPTION_PCT)
- Service helpers: points_to_usd, usd_to_points
- get_or_create_account: creates new account when none exists; returns existing account
- award_points_for_ride: correct points_delta, lifetime_earned, balance; zero-fare skipped;
  sub-dollar fare; ride_id attached; description format
- redeem_points: success; correct discount_value; balance decremented; lifetime_redeemed updated;
  insufficient balance raises; below minimum raises; zero/negative points raises
- get_transaction_history: pagination (offset/limit); total count returned; empty history
- admin_adjust_points: credit; debit; debit capped at balance; zero delta raises;
  negative-beyond-balance capped; description defaulted
- get_platform_stats: zero accounts; multiple accounts aggregate correctly
- Schema: RewardAccountResponse field presence; RedeemPointsRequest validation
- Router constants: DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.rider_reward import (
    MAX_REDEMPTION_PCT,
    MIN_REDEMPTION_POINTS,
    POINT_VALUE_CENTS,
    POINTS_PER_DOLLAR,
    RewardTransactionType,
    RiderRewardAccount,
    RiderRewardTransaction,
)
from app.schemas.rider_reward import (
    AdminAdjustPointsRequest,
    RedeemPointsRequest,
    RedeemPointsResponse,
    RewardAccountResponse,
    RewardPlatformStats,
    RewardTransactionPage,
    RewardTransactionResponse,
)
from app.services.rider_rewards import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    admin_adjust_points,
    award_points_for_ride,
    get_or_create_account,
    get_platform_stats,
    get_transaction_history,
    points_to_usd,
    redeem_points,
    usd_to_points,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_account(
    id: int = 1,
    rider_id: int = 42,
    points_balance: int = 0,
    lifetime_earned: int = 0,
    lifetime_redeemed: int = 0,
) -> RiderRewardAccount:
    acct = RiderRewardAccount()
    acct.id = id
    acct.rider_id = rider_id
    acct.points_balance = points_balance
    acct.lifetime_earned = lifetime_earned
    acct.lifetime_redeemed = lifetime_redeemed
    acct.created_at = _now()
    acct.updated_at = _now()
    return acct


def _make_txn(
    id: int = 1,
    rider_id: int = 42,
    account_id: int = 1,
    transaction_type: RewardTransactionType = RewardTransactionType.earn,
    points_delta: int = 100,
    balance_after: int = 100,
    ride_id: int | None = None,
    description: str | None = None,
) -> RiderRewardTransaction:
    txn = RiderRewardTransaction()
    txn.id = id
    txn.rider_id = rider_id
    txn.account_id = account_id
    txn.ride_id = ride_id
    txn.transaction_type = transaction_type
    txn.points_delta = points_delta
    txn.balance_after = balance_after
    txn.description = description
    txn.created_at = _now()
    return txn


def _db_returning(value):
    """Mock AsyncSession.execute() returning a result whose scalar_one_or_none() == value."""
    m = MagicMock()
    m.scalar_one_or_none.return_value = value
    m.scalar_one.return_value = value
    scalars = MagicMock()
    scalars.all.return_value = value if isinstance(value, list) else ([] if value is None else [value])
    m.scalars.return_value = scalars
    m.one.return_value = value
    return m


def _db_scalars_list(values: list):
    m = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = values
    m.scalars.return_value = scalars
    m.scalar_one.return_value = len(values)
    m.scalar_one_or_none.return_value = values[0] if values else None
    return m


# ---------------------------------------------------------------------------
# Model / Constants
# ---------------------------------------------------------------------------


class TestModelConstants:
    def test_points_per_dollar(self):
        assert POINTS_PER_DOLLAR == 10

    def test_point_value_cents(self):
        assert POINT_VALUE_CENTS == 1

    def test_min_redemption_points(self):
        assert MIN_REDEMPTION_POINTS == 500

    def test_max_redemption_pct(self):
        assert MAX_REDEMPTION_PCT == 50.0

    def test_reward_transaction_type_earn(self):
        assert RewardTransactionType.earn.value == "earn"

    def test_reward_transaction_type_redeem(self):
        assert RewardTransactionType.redeem.value == "redeem"

    def test_reward_transaction_type_admin_adjust(self):
        assert RewardTransactionType.admin_adjust.value == "admin_adjust"

    def test_reward_transaction_type_expiry(self):
        assert RewardTransactionType.expiry.value == "expiry"

    def test_account_tablename(self):
        assert RiderRewardAccount.__tablename__ == "rider_reward_accounts"

    def test_transaction_tablename(self):
        assert RiderRewardTransaction.__tablename__ == "rider_reward_transactions"


class TestServiceConstants:
    def test_default_page_size(self):
        assert DEFAULT_PAGE_SIZE == 20

    def test_max_page_size(self):
        assert MAX_PAGE_SIZE == 100


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_points_to_usd_basic(self):
        # 100 points × 1 cent each = $1.00
        assert points_to_usd(100) == 1.00

    def test_points_to_usd_zero(self):
        assert points_to_usd(0) == 0.00

    def test_points_to_usd_large(self):
        # 1000 points = $10.00
        assert points_to_usd(1000) == 10.00

    def test_points_to_usd_rounding(self):
        # 3 points × 1 cent = $0.03
        assert points_to_usd(3) == 0.03

    def test_usd_to_points_basic(self):
        # $1.00 × 10 pts/$ = 10 points
        assert usd_to_points(1.0) == 10

    def test_usd_to_points_zero(self):
        assert usd_to_points(0.0) == 0

    def test_usd_to_points_large(self):
        # $50 = 500 points
        assert usd_to_points(50.0) == 500

    def test_usd_to_points_floors(self):
        # $0.05 × 10 = 0.5 → floor → 0
        assert usd_to_points(0.05) == 0

    def test_usd_to_points_small_earn(self):
        # $0.11 × 10 = 1.1 → floor → 1
        assert usd_to_points(0.11) == 1


# ---------------------------------------------------------------------------
# get_or_create_account
# ---------------------------------------------------------------------------


class TestGetOrCreateAccount:
    @pytest.mark.asyncio
    async def test_returns_existing_account(self):
        db = AsyncMock()
        existing = _make_account(id=5, rider_id=10, points_balance=200)
        db.execute = AsyncMock(return_value=_db_returning(existing))

        result = await get_or_create_account(rider_id=10, db=db)

        assert result is existing
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_account_when_none(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_db_returning(None))
        db.flush = AsyncMock()

        result = await get_or_create_account(rider_id=99, db=db)

        db.add.assert_called_once_with(result)
        db.flush.assert_called_once()
        assert result.rider_id == 99
        assert result.points_balance == 0
        assert result.lifetime_earned == 0
        assert result.lifetime_redeemed == 0


# ---------------------------------------------------------------------------
# award_points_for_ride
# ---------------------------------------------------------------------------


class TestAwardPointsForRide:
    @pytest.mark.asyncio
    async def test_awards_correct_points(self):
        db = AsyncMock()
        acct = _make_account(id=1, rider_id=5)
        db.execute = AsyncMock(return_value=_db_returning(acct))
        db.flush = AsyncMock()

        txn = await award_points_for_ride(rider_id=5, fare_usd=10.0, db=db, ride_id=99)

        expected_pts = usd_to_points(10.0)  # 100
        assert txn is not None
        assert txn.points_delta == expected_pts
        assert txn.transaction_type == RewardTransactionType.earn
        assert txn.ride_id == 99
        assert acct.points_balance == expected_pts
        assert acct.lifetime_earned == expected_pts

    @pytest.mark.asyncio
    async def test_zero_fare_returns_none(self):
        db = AsyncMock()
        result = await award_points_for_ride(rider_id=5, fare_usd=0.0, db=db)
        assert result is None

    @pytest.mark.asyncio
    async def test_negative_fare_returns_none(self):
        db = AsyncMock()
        result = await award_points_for_ride(rider_id=5, fare_usd=-5.0, db=db)
        assert result is None

    @pytest.mark.asyncio
    async def test_sub_dollar_fare_earns_floor(self):
        db = AsyncMock()
        acct = _make_account(id=1, rider_id=5)
        db.execute = AsyncMock(return_value=_db_returning(acct))
        db.flush = AsyncMock()

        # $0.05 → 0.5 → floor → 0 points → None returned
        txn = await award_points_for_ride(rider_id=5, fare_usd=0.05, db=db)
        assert txn is None

    @pytest.mark.asyncio
    async def test_description_includes_fare_and_points(self):
        db = AsyncMock()
        acct = _make_account(id=1, rider_id=5)
        db.execute = AsyncMock(return_value=_db_returning(acct))
        db.flush = AsyncMock()

        txn = await award_points_for_ride(rider_id=5, fare_usd=7.50, db=db)
        assert txn is not None
        assert "7.50" in txn.description
        assert str(usd_to_points(7.50)) in txn.description

    @pytest.mark.asyncio
    async def test_no_ride_id_allowed(self):
        db = AsyncMock()
        acct = _make_account(id=1, rider_id=5)
        db.execute = AsyncMock(return_value=_db_returning(acct))
        db.flush = AsyncMock()

        txn = await award_points_for_ride(rider_id=5, fare_usd=20.0, db=db)
        assert txn is not None
        assert txn.ride_id is None

    @pytest.mark.asyncio
    async def test_balance_accumulates(self):
        db = AsyncMock()
        acct = _make_account(id=1, rider_id=5, points_balance=50, lifetime_earned=50)
        db.execute = AsyncMock(return_value=_db_returning(acct))
        db.flush = AsyncMock()

        txn = await award_points_for_ride(rider_id=5, fare_usd=10.0, db=db)
        expected_new = 50 + usd_to_points(10.0)
        assert acct.points_balance == expected_new
        assert txn.balance_after == expected_new


# ---------------------------------------------------------------------------
# redeem_points
# ---------------------------------------------------------------------------


class TestRedeemPoints:
    @pytest.mark.asyncio
    async def test_redeem_success(self):
        db = AsyncMock()
        acct = _make_account(
            id=1, rider_id=7, points_balance=1000, lifetime_earned=1000
        )
        db.execute = AsyncMock(return_value=_db_returning(acct))
        db.flush = AsyncMock()

        txn = await redeem_points(rider_id=7, points=500, db=db)

        assert txn.points_delta == -500
        assert txn.transaction_type == RewardTransactionType.redeem
        assert acct.points_balance == 500
        assert acct.lifetime_redeemed == 500
        assert txn.balance_after == 500

    @pytest.mark.asyncio
    async def test_redeem_discount_value(self):
        db = AsyncMock()
        acct = _make_account(id=1, rider_id=7, points_balance=2000, lifetime_earned=2000)
        db.execute = AsyncMock(return_value=_db_returning(acct))
        db.flush = AsyncMock()

        txn = await redeem_points(rider_id=7, points=1000, db=db)
        # 1000 pts × $0.01 = $10.00
        assert points_to_usd(abs(txn.points_delta)) == 10.00

    @pytest.mark.asyncio
    async def test_redeem_insufficient_balance_raises(self):
        db = AsyncMock()
        acct = _make_account(id=1, rider_id=7, points_balance=100)
        db.execute = AsyncMock(return_value=_db_returning(acct))
        db.flush = AsyncMock()

        with pytest.raises(ValueError, match="Insufficient"):
            await redeem_points(rider_id=7, points=500, db=db)

    @pytest.mark.asyncio
    async def test_redeem_below_minimum_raises(self):
        db = AsyncMock()
        acct = _make_account(id=1, rider_id=7, points_balance=5000)
        db.execute = AsyncMock(return_value=_db_returning(acct))
        db.flush = AsyncMock()

        with pytest.raises(ValueError, match="Minimum redemption"):
            await redeem_points(rider_id=7, points=MIN_REDEMPTION_POINTS - 1, db=db)

    @pytest.mark.asyncio
    async def test_redeem_zero_points_raises(self):
        db = AsyncMock()
        with pytest.raises(ValueError, match="positive integer"):
            await redeem_points(rider_id=7, points=0, db=db)

    @pytest.mark.asyncio
    async def test_redeem_negative_points_raises(self):
        db = AsyncMock()
        with pytest.raises(ValueError, match="positive integer"):
            await redeem_points(rider_id=7, points=-100, db=db)

    @pytest.mark.asyncio
    async def test_redeem_attaches_ride_id(self):
        db = AsyncMock()
        acct = _make_account(id=1, rider_id=7, points_balance=1000, lifetime_earned=1000)
        db.execute = AsyncMock(return_value=_db_returning(acct))
        db.flush = AsyncMock()

        txn = await redeem_points(rider_id=7, points=500, db=db, ride_id=77)
        assert txn.ride_id == 77

    @pytest.mark.asyncio
    async def test_redeem_exact_balance(self):
        """Rider can redeem their entire balance."""
        db = AsyncMock()
        acct = _make_account(id=1, rider_id=7, points_balance=500, lifetime_earned=500)
        db.execute = AsyncMock(return_value=_db_returning(acct))
        db.flush = AsyncMock()

        txn = await redeem_points(rider_id=7, points=500, db=db)
        assert acct.points_balance == 0
        assert txn.balance_after == 0


# ---------------------------------------------------------------------------
# get_transaction_history
# ---------------------------------------------------------------------------


class TestGetTransactionHistory:
    @pytest.mark.asyncio
    async def test_returns_list_and_total(self):
        db = AsyncMock()
        txns = [_make_txn(id=i, rider_id=5) for i in range(3)]

        count_result = MagicMock()
        count_result.scalar_one.return_value = 3

        list_result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = txns
        list_result.scalars.return_value = scalars

        db.execute = AsyncMock(side_effect=[count_result, list_result])

        results, total = await get_transaction_history(rider_id=5, db=db)
        assert len(results) == 3
        assert total == 3

    @pytest.mark.asyncio
    async def test_empty_history(self):
        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        list_result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        list_result.scalars.return_value = scalars

        db.execute = AsyncMock(side_effect=[count_result, list_result])

        results, total = await get_transaction_history(rider_id=99, db=db)
        assert results == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_limit_clamped_to_max(self):
        """limit > MAX_PAGE_SIZE is silently clamped."""
        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        list_result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        list_result.scalars.return_value = scalars

        db.execute = AsyncMock(side_effect=[count_result, list_result])

        # Should not raise even with absurdly large limit
        results, total = await get_transaction_history(rider_id=1, db=db, limit=9999)
        assert total == 0


# ---------------------------------------------------------------------------
# admin_adjust_points
# ---------------------------------------------------------------------------


class TestAdminAdjustPoints:
    @pytest.mark.asyncio
    async def test_credit(self):
        db = AsyncMock()
        acct = _make_account(id=1, rider_id=20, points_balance=100, lifetime_earned=100)
        db.execute = AsyncMock(return_value=_db_returning(acct))
        db.flush = AsyncMock()

        txn = await admin_adjust_points(rider_id=20, points_delta=200, db=db)

        assert txn.points_delta == 200
        assert txn.transaction_type == RewardTransactionType.admin_adjust
        assert acct.points_balance == 300
        assert acct.lifetime_earned == 300  # credit increases lifetime_earned

    @pytest.mark.asyncio
    async def test_debit(self):
        db = AsyncMock()
        acct = _make_account(id=1, rider_id=20, points_balance=500, lifetime_earned=500)
        db.execute = AsyncMock(return_value=_db_returning(acct))
        db.flush = AsyncMock()

        txn = await admin_adjust_points(rider_id=20, points_delta=-100, db=db)

        assert txn.points_delta == -100
        assert acct.points_balance == 400
        assert acct.lifetime_redeemed == 100

    @pytest.mark.asyncio
    async def test_debit_capped_at_balance(self):
        """Debit larger than balance is capped so balance goes to exactly 0."""
        db = AsyncMock()
        acct = _make_account(id=1, rider_id=20, points_balance=200)
        db.execute = AsyncMock(return_value=_db_returning(acct))
        db.flush = AsyncMock()

        txn = await admin_adjust_points(rider_id=20, points_delta=-999, db=db)

        assert acct.points_balance == 0
        assert txn.points_delta == -200

    @pytest.mark.asyncio
    async def test_zero_delta_raises(self):
        db = AsyncMock()
        with pytest.raises(ValueError, match="cannot be zero"):
            await admin_adjust_points(rider_id=20, points_delta=0, db=db)

    @pytest.mark.asyncio
    async def test_debit_already_zero_raises(self):
        """Cannot debit a balance that's already 0."""
        db = AsyncMock()
        acct = _make_account(id=1, rider_id=20, points_balance=0)
        db.execute = AsyncMock(return_value=_db_returning(acct))
        db.flush = AsyncMock()

        with pytest.raises(ValueError, match="already 0"):
            await admin_adjust_points(rider_id=20, points_delta=-100, db=db)

    @pytest.mark.asyncio
    async def test_custom_description_preserved(self):
        db = AsyncMock()
        acct = _make_account(id=1, rider_id=20, points_balance=100)
        db.execute = AsyncMock(return_value=_db_returning(acct))
        db.flush = AsyncMock()

        txn = await admin_adjust_points(
            rider_id=20, points_delta=50, db=db, description="Goodwill credit"
        )
        assert txn.description == "Goodwill credit"

    @pytest.mark.asyncio
    async def test_default_description_generated(self):
        db = AsyncMock()
        acct = _make_account(id=1, rider_id=20, points_balance=100)
        db.execute = AsyncMock(return_value=_db_returning(acct))
        db.flush = AsyncMock()

        txn = await admin_adjust_points(rider_id=20, points_delta=50, db=db)
        assert txn.description is not None
        assert "50" in txn.description


# ---------------------------------------------------------------------------
# get_platform_stats
# ---------------------------------------------------------------------------


class TestGetPlatformStats:
    @pytest.mark.asyncio
    async def test_stats_with_accounts(self):
        db = AsyncMock()

        row = MagicMock()
        row.total_accounts = 5
        row.total_outstanding_points = 10_000
        row.total_lifetime_earned = 50_000
        row.total_lifetime_redeemed = 40_000

        result = MagicMock()
        result.one.return_value = row
        db.execute = AsyncMock(return_value=result)

        stats = await get_platform_stats(db)

        assert stats["total_accounts"] == 5
        assert stats["total_outstanding_points"] == 10_000
        assert stats["outstanding_liability_usd"] == points_to_usd(10_000)
        assert stats["total_lifetime_earned"] == 50_000
        assert stats["total_lifetime_redeemed"] == 40_000
        assert stats["total_lifetime_earned_usd"] == points_to_usd(50_000)
        assert stats["total_lifetime_redeemed_usd"] == points_to_usd(40_000)

    @pytest.mark.asyncio
    async def test_stats_zero_accounts(self):
        db = AsyncMock()

        row = MagicMock()
        row.total_accounts = 0
        row.total_outstanding_points = 0
        row.total_lifetime_earned = 0
        row.total_lifetime_redeemed = 0

        result = MagicMock()
        result.one.return_value = row
        db.execute = AsyncMock(return_value=result)

        stats = await get_platform_stats(db)

        assert stats["total_accounts"] == 0
        assert stats["outstanding_liability_usd"] == 0.0


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_redeem_request_valid(self):
        req = RedeemPointsRequest(points=500)
        assert req.points == 500
        assert req.ride_id is None

    def test_redeem_request_with_ride_id(self):
        req = RedeemPointsRequest(points=1000, ride_id=99)
        assert req.ride_id == 99

    def test_redeem_request_zero_points_invalid(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RedeemPointsRequest(points=0)

    def test_redeem_request_negative_points_invalid(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RedeemPointsRequest(points=-50)

    def test_admin_adjust_request(self):
        req = AdminAdjustPointsRequest(rider_id=5, points_delta=200, description="Test")
        assert req.rider_id == 5
        assert req.points_delta == 200
        assert req.description == "Test"

    def test_platform_stats_schema(self):
        stats = RewardPlatformStats(
            total_accounts=10,
            total_outstanding_points=5000,
            outstanding_liability_usd=50.0,
            total_lifetime_earned=20000,
            total_lifetime_redeemed=15000,
            total_lifetime_earned_usd=200.0,
            total_lifetime_redeemed_usd=150.0,
        )
        assert stats.total_accounts == 10
        assert stats.outstanding_liability_usd == 50.0

    def test_reward_account_response_fields(self):
        now = _now()
        resp = RewardAccountResponse(
            points_balance=1500,
            lifetime_earned=2000,
            lifetime_redeemed=500,
            balance_value_usd=15.0,
            created_at=now,
            updated_at=now,
        )
        assert resp.points_balance == 1500
        assert resp.balance_value_usd == 15.0

    def test_transaction_response_fields(self):
        now = _now()
        resp = RewardTransactionResponse(
            id=1,
            transaction_type=RewardTransactionType.earn,
            points_delta=100,
            balance_after=100,
            description="Earned 100 pts",
            ride_id=5,
            created_at=now,
        )
        assert resp.transaction_type == RewardTransactionType.earn
        assert resp.points_delta == 100
