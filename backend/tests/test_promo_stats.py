"""Tests for promo stats analytics endpoint and schemas.

Covers:
- PromoTopEntry and PromoStats schema construction
- promo_stats endpoint with mocked DB:
  - default period (month)
  - all-time period
  - empty platform (no redemptions)
  - referral vs non-referral breakdown
  - top promos by usage and by discount
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.promo import PromoStats, PromoTopEntry


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestPromoTopEntry:
    def test_basic_construction(self):
        entry = PromoTopEntry(
            promo_code_id=1,
            code="SAVE10",
            description="10% off your first ride",
            promo_type="percent",
            is_referral=False,
            redemptions=42,
            total_discount_given=187.50,
        )
        assert entry.promo_code_id == 1
        assert entry.code == "SAVE10"
        assert entry.promo_type == "percent"
        assert entry.is_referral is False
        assert entry.redemptions == 42
        assert entry.total_discount_given == pytest.approx(187.50)

    def test_referral_entry(self):
        entry = PromoTopEntry(
            promo_code_id=5,
            code="REF8A2B3C",
            description="",
            promo_type="flat",
            is_referral=True,
            redemptions=10,
            total_discount_given=50.0,
        )
        assert entry.is_referral is True
        assert entry.description == ""

    def test_zero_redemptions(self):
        entry = PromoTopEntry(
            promo_code_id=2,
            code="SUMMER25",
            description="Summer sale",
            promo_type="flat",
            is_referral=False,
            redemptions=0,
            total_discount_given=0.0,
        )
        assert entry.redemptions == 0
        assert entry.total_discount_given == 0.0


class TestPromoStats:
    def _make_entry(self, code: str = "TEST", redemptions: int = 5) -> PromoTopEntry:
        return PromoTopEntry(
            promo_code_id=1,
            code=code,
            description="",
            promo_type="flat",
            is_referral=False,
            redemptions=redemptions,
            total_discount_given=float(redemptions * 5),
        )

    def test_full_stats(self):
        entries = [self._make_entry(f"CODE{i}", i * 10) for i in range(1, 4)]
        stats = PromoStats(
            period="month",
            total_redemptions=60,
            total_discount_given=300.00,
            unique_riders_used=45,
            active_promo_count=8,
            referral_redemptions=15,
            non_referral_redemptions=45,
            top_promos_by_usage=entries,
            top_promos_by_discount=entries,
        )
        assert stats.period == "month"
        assert stats.total_redemptions == 60
        assert stats.total_discount_given == pytest.approx(300.00)
        assert stats.unique_riders_used == 45
        assert stats.active_promo_count == 8
        assert stats.referral_redemptions == 15
        assert stats.non_referral_redemptions == 45
        assert len(stats.top_promos_by_usage) == 3
        assert len(stats.top_promos_by_discount) == 3

    def test_empty_platform(self):
        stats = PromoStats(
            period="all",
            total_redemptions=0,
            total_discount_given=0.0,
            unique_riders_used=0,
            active_promo_count=0,
            referral_redemptions=0,
            non_referral_redemptions=0,
            top_promos_by_usage=[],
            top_promos_by_discount=[],
        )
        assert stats.total_redemptions == 0
        assert stats.top_promos_by_usage == []
        assert stats.top_promos_by_discount == []

    def test_referral_plus_non_referral_matches_total(self):
        stats = PromoStats(
            period="week",
            total_redemptions=30,
            total_discount_given=120.0,
            unique_riders_used=28,
            active_promo_count=3,
            referral_redemptions=10,
            non_referral_redemptions=20,
            top_promos_by_usage=[],
            top_promos_by_discount=[],
        )
        assert stats.referral_redemptions + stats.non_referral_redemptions == 30


# ---------------------------------------------------------------------------
# Endpoint logic tests (mock DB)
# ---------------------------------------------------------------------------

class TestPromoStatsEndpoint:
    def _make_summary_row(self, total=0, discount_total=0.0, unique_users=0):
        row = MagicMock()
        row.total = total
        row.discount_total = discount_total
        row.unique_users = unique_users
        return row

    @pytest.mark.asyncio
    async def test_empty_platform_returns_zeros(self):
        """promo_stats returns zero counts when no redemptions exist."""
        from app.api.v1.promos import promo_stats

        mock_db = AsyncMock()

        summary_result = MagicMock()
        summary_result.one.return_value = self._make_summary_row()

        active_result = MagicMock()
        active_result.scalar.return_value = 0

        ref_result = MagicMock()
        ref_result.all.return_value = []

        top_usage_result = MagicMock()
        top_usage_result.all.return_value = []

        top_discount_result = MagicMock()
        top_discount_result.all.return_value = []

        mock_db.execute = AsyncMock(
            side_effect=[summary_result, active_result, ref_result, top_usage_result, top_discount_result]
        )

        stats = await promo_stats(period="month", db=mock_db)

        assert stats.total_redemptions == 0
        assert stats.total_discount_given == 0.0
        assert stats.unique_riders_used == 0
        assert stats.active_promo_count == 0
        assert stats.referral_redemptions == 0
        assert stats.non_referral_redemptions == 0
        assert stats.top_promos_by_usage == []
        assert stats.top_promos_by_discount == []

    @pytest.mark.asyncio
    async def test_with_redemptions(self):
        """promo_stats aggregates summary stats correctly."""
        from app.api.v1.promos import promo_stats

        mock_db = AsyncMock()

        summary_result = MagicMock()
        summary_result.one.return_value = self._make_summary_row(
            total=100, discount_total=350.50, unique_users=80
        )

        active_result = MagicMock()
        active_result.scalar.return_value = 5

        # Referral breakdown: 20 referral, 80 non-referral
        ref_row_referral = MagicMock()
        ref_row_referral.is_referral = True
        ref_row_referral.cnt = 20

        ref_row_non = MagicMock()
        ref_row_non.is_referral = False
        ref_row_non.cnt = 80

        ref_result = MagicMock()
        ref_result.all.return_value = [ref_row_referral, ref_row_non]

        top_usage_result = MagicMock()
        top_usage_result.all.return_value = []

        top_discount_result = MagicMock()
        top_discount_result.all.return_value = []

        mock_db.execute = AsyncMock(
            side_effect=[summary_result, active_result, ref_result, top_usage_result, top_discount_result]
        )

        stats = await promo_stats(period="month", db=mock_db)

        assert stats.total_redemptions == 100
        assert stats.total_discount_given == pytest.approx(350.50)
        assert stats.unique_riders_used == 80
        assert stats.active_promo_count == 5
        assert stats.referral_redemptions == 20
        assert stats.non_referral_redemptions == 80
        assert stats.period == "month"

    @pytest.mark.asyncio
    async def test_top_promos_populated(self):
        """promo_stats populates top_promos lists from DB rows."""
        from app.models.promo import PromoType
        from app.api.v1.promos import promo_stats

        mock_db = AsyncMock()

        summary_result = MagicMock()
        summary_result.one.return_value = self._make_summary_row(total=5)

        active_result = MagicMock()
        active_result.scalar.return_value = 2

        ref_result = MagicMock()
        ref_result.all.return_value = []

        # Build a fake top promo row
        top_row = MagicMock()
        top_row.promo_code_id = 1
        top_row.code = "BEST10"
        top_row.description = "Best promo"
        top_row.promo_type = PromoType.FLAT
        top_row.is_referral = False
        top_row.redemptions = 5
        top_row.total_discount_given = 25.00

        top_usage_result = MagicMock()
        top_usage_result.all.return_value = [top_row]

        top_discount_result = MagicMock()
        top_discount_result.all.return_value = [top_row]

        mock_db.execute = AsyncMock(
            side_effect=[summary_result, active_result, ref_result, top_usage_result, top_discount_result]
        )

        stats = await promo_stats(period="month", db=mock_db)

        assert len(stats.top_promos_by_usage) == 1
        assert stats.top_promos_by_usage[0].code == "BEST10"
        assert stats.top_promos_by_usage[0].promo_type == "flat"
        assert stats.top_promos_by_usage[0].redemptions == 5
        assert stats.top_promos_by_usage[0].total_discount_given == pytest.approx(25.0)

        assert len(stats.top_promos_by_discount) == 1
        assert stats.top_promos_by_discount[0].code == "BEST10"

    @pytest.mark.asyncio
    async def test_all_time_period(self):
        """promo_stats with period='all' executes without date filter."""
        from app.api.v1.promos import promo_stats

        mock_db = AsyncMock()

        summary_result = MagicMock()
        summary_result.one.return_value = self._make_summary_row(total=500)

        active_result = MagicMock()
        active_result.scalar.return_value = 10

        ref_result = MagicMock()
        ref_result.all.return_value = []

        top_usage_result = MagicMock()
        top_usage_result.all.return_value = []

        top_discount_result = MagicMock()
        top_discount_result.all.return_value = []

        mock_db.execute = AsyncMock(
            side_effect=[summary_result, active_result, ref_result, top_usage_result, top_discount_result]
        )

        stats = await promo_stats(period="all", db=mock_db)

        assert stats.period == "all"
        assert stats.total_redemptions == 500
        assert stats.active_promo_count == 10

    @pytest.mark.asyncio
    async def test_only_referral_redemptions(self):
        """promo_stats handles all redemptions being referrals."""
        from app.api.v1.promos import promo_stats

        mock_db = AsyncMock()

        summary_result = MagicMock()
        summary_result.one.return_value = self._make_summary_row(total=25)

        active_result = MagicMock()
        active_result.scalar.return_value = 1

        ref_row = MagicMock()
        ref_row.is_referral = True
        ref_row.cnt = 25

        ref_result = MagicMock()
        ref_result.all.return_value = [ref_row]

        top_usage_result = MagicMock()
        top_usage_result.all.return_value = []

        top_discount_result = MagicMock()
        top_discount_result.all.return_value = []

        mock_db.execute = AsyncMock(
            side_effect=[summary_result, active_result, ref_result, top_usage_result, top_discount_result]
        )

        stats = await promo_stats(period="week", db=mock_db)

        assert stats.referral_redemptions == 25
        assert stats.non_referral_redemptions == 0
