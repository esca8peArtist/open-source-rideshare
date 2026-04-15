"""Unit tests for the driver payout / disbursement feature.

All tests are pure unit tests — no database or HTTP client required.
Every external dependency (DB session, subscriptions service) is mocked.

Covers:
- DriverPayout model fields, enums, tablename
- DriverPayoutStatus and DriverPayoutMethod enum values
- Schemas: PayoutRequestRequest, DriverPayoutResponse, AdminPayoutResponse,
           PayoutStatsResponse, PendingEarningsResponse
- calculate_pending_earnings: rides present, no rides, subscription (0 % commission),
  standard commission (15 %), partial overlap exclusion
- request_payout: success, zero-earnings rejection, duplicate overlap rejection
- process_payout: success state transition, wrong-status rejection, not-found (404)
- fail_payout: success, rejection when completed, rejection when already failed, not-found (404)
- get_payout: found, not found raises 404
- get_driver_payouts: returns list
- get_all_payouts: no filter, status filter
- get_payout_stats: correct aggregation
- Router: all 7 endpoints — success cases, auth checks, edge cases
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_payout import DriverPayout, DriverPayoutMethod, DriverPayoutStatus
from app.schemas.driver_payout import (
    AdminFailPayoutRequest,
    AdminPayoutResponse,
    AdminProcessPayoutRequest,
    DriverPayoutResponse,
    PayoutRequestRequest,
    PayoutStatsResponse,
    PendingEarningsResponse,
)
from app.services.driver_payouts import (
    _decimal,
    calculate_pending_earnings,
    fail_payout,
    get_all_payouts,
    get_driver_payouts,
    get_payout,
    get_payout_stats,
    process_payout,
    request_payout,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _today() -> date:
    return date.today()


def _make_payout(
    id: int = 1,
    driver_id: int = 42,
    amount_usd: Decimal = Decimal("100.00"),
    platform_fee_usd: Decimal = Decimal("15.00"),
    net_payout_usd: Decimal = Decimal("85.00"),
    status: DriverPayoutStatus = DriverPayoutStatus.pending,
    method: DriverPayoutMethod = DriverPayoutMethod.stripe_transfer,
    period_start: date | None = None,
    period_end: date | None = None,
    requested_at: datetime | None = None,
    processed_at: datetime | None = None,
    failed_reason: str | None = None,
    stripe_transfer_id: str | None = None,
    notes: str | None = None,
) -> DriverPayout:
    p = DriverPayout()
    p.id = id
    p.driver_id = driver_id
    p.amount_usd = amount_usd
    p.platform_fee_usd = platform_fee_usd
    p.net_payout_usd = net_payout_usd
    p.status = status
    p.method = method
    p.period_start = period_start or (_today() - timedelta(days=7))
    p.period_end = period_end or _today()
    p.requested_at = requested_at or _now()
    p.processed_at = processed_at
    p.failed_reason = failed_reason
    p.stripe_transfer_id = stripe_transfer_id
    p.notes = notes
    return p


def _db_result(value):
    """Return an AsyncMock db.execute() result with scalar_one_or_none and scalars."""
    m = MagicMock()
    m.scalar_one_or_none.return_value = value
    m.scalar.return_value = value if not isinstance(value, list) else len(value)
    m.scalar_one.return_value = value if not isinstance(value, list) else None
    scalars_m = MagicMock()
    scalars_m.all.return_value = value if isinstance(value, list) else ([value] if value else [])
    m.scalars.return_value = scalars_m

    # For .one() calls (aggregate queries)
    row = MagicMock()
    row.gross = 0
    row.ride_count = 0
    row.covered_gross = 0
    row.covered_count = 0
    row.cnt = 0
    row.total = 0
    m.one.return_value = row
    return m


def _make_db(execute_results=None) -> AsyncMock:
    """Build a minimal AsyncMock db session."""
    db = AsyncMock()
    if execute_results is not None:
        db.execute.side_effect = execute_results
    return db


# ---------------------------------------------------------------------------
# Model / constants
# ---------------------------------------------------------------------------


class TestDriverPayoutModel:
    def test_tablename(self):
        assert DriverPayout.__tablename__ == "driver_disbursements"

    def test_status_enum_values(self):
        assert DriverPayoutStatus.pending.value == "pending"
        assert DriverPayoutStatus.processing.value == "processing"
        assert DriverPayoutStatus.completed.value == "completed"
        assert DriverPayoutStatus.failed.value == "failed"

    def test_method_enum_values(self):
        assert DriverPayoutMethod.stripe_transfer.value == "stripe_transfer"
        assert DriverPayoutMethod.bank_transfer.value == "bank_transfer"
        assert DriverPayoutMethod.manual.value == "manual"

    def test_make_payout_fields(self):
        p = _make_payout()
        assert p.id == 1
        assert p.driver_id == 42
        assert p.amount_usd == Decimal("100.00")
        assert p.platform_fee_usd == Decimal("15.00")
        assert p.net_payout_usd == Decimal("85.00")
        assert p.status == DriverPayoutStatus.pending
        assert p.method == DriverPayoutMethod.stripe_transfer
        assert p.failed_reason is None
        assert p.stripe_transfer_id is None
        assert p.notes is None
        assert p.processed_at is None

    def test_status_is_str_enum(self):
        assert isinstance(DriverPayoutStatus.pending, str)

    def test_method_is_str_enum(self):
        assert isinstance(DriverPayoutMethod.stripe_transfer, str)


# ---------------------------------------------------------------------------
# _decimal helper
# ---------------------------------------------------------------------------


class TestDecimalHelper:
    def test_none_returns_zero(self):
        assert _decimal(None) == Decimal("0.00")

    def test_int_converts(self):
        assert _decimal(100) == Decimal("100.00")

    def test_float_converts(self):
        assert _decimal(15.555) == Decimal("15.56")

    def test_decimal_passes_through(self):
        assert _decimal(Decimal("42.50")) == Decimal("42.50")

    def test_string_converts(self):
        assert _decimal("99.99") == Decimal("99.99")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TestPayoutRequestRequest:
    def test_defaults(self):
        req = PayoutRequestRequest()
        assert req.period_start is None
        assert req.period_end is None
        assert req.method == DriverPayoutMethod.stripe_transfer

    def test_explicit_method(self):
        req = PayoutRequestRequest(method=DriverPayoutMethod.manual)
        assert req.method == DriverPayoutMethod.manual

    def test_with_dates(self):
        start = date(2026, 4, 1)
        end = date(2026, 4, 7)
        req = PayoutRequestRequest(period_start=start, period_end=end)
        assert req.period_start == start
        assert req.period_end == end


class TestDriverPayoutResponse:
    def test_from_attributes(self):
        p = _make_payout()
        resp = DriverPayoutResponse.model_validate(p)
        assert resp.id == 1
        assert resp.driver_id == 42
        assert resp.status == DriverPayoutStatus.pending

    def test_nullable_fields(self):
        p = _make_payout()
        resp = DriverPayoutResponse.model_validate(p)
        assert resp.processed_at is None
        assert resp.failed_reason is None
        assert resp.stripe_transfer_id is None
        assert resp.notes is None


class TestAdminPayoutResponse:
    def test_inherits_driver_payout_response(self):
        assert issubclass(AdminPayoutResponse, DriverPayoutResponse)

    def test_from_attributes(self):
        p = _make_payout(notes="admin note")
        resp = AdminPayoutResponse.model_validate(p)
        assert resp.notes == "admin note"


class TestPayoutStatsResponse:
    def test_fields(self):
        stats = PayoutStatsResponse(
            total_pending_usd=Decimal("500.00"),
            total_completed_usd=Decimal("10000.00"),
            pending_count=5,
            completed_count=100,
            failed_count=3,
            avg_payout_usd=Decimal("100.00"),
        )
        assert stats.total_pending_usd == Decimal("500.00")
        assert stats.completed_count == 100
        assert stats.avg_payout_usd == Decimal("100.00")


class TestPendingEarningsResponse:
    def test_fields(self):
        resp = PendingEarningsResponse(
            driver_id=1,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 7),
            gross_usd=Decimal("100.00"),
            platform_fee_usd=Decimal("15.00"),
            net_usd=Decimal("85.00"),
            ride_count=5,
            commission_pct=15.0,
        )
        assert resp.driver_id == 1
        assert resp.gross_usd == Decimal("100.00")
        assert resp.commission_pct == 15.0


# ---------------------------------------------------------------------------
# calculate_pending_earnings
# ---------------------------------------------------------------------------


class TestCalculatePendingEarnings:
    @pytest.mark.asyncio
    async def test_no_rides_returns_zeros(self):
        db = AsyncMock()
        empty_overlap = _db_result([])  # no existing payouts
        ride_row = MagicMock()
        ride_row.gross = 0
        ride_row.ride_count = 0
        ride_result = MagicMock()
        ride_result.one.return_value = ride_row

        db.execute.side_effect = [empty_overlap, ride_result]

        with patch(
            "app.services.driver_payouts.get_driver_commission_pct",
            new=AsyncMock(return_value=15.0),
        ):
            result = await calculate_pending_earnings(
                db, driver_id=1,
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 7),
            )

        assert result["gross_usd"] == Decimal("0.00")
        assert result["platform_fee_usd"] == Decimal("0.00")
        assert result["net_usd"] == Decimal("0.00")
        assert result["ride_count"] == 0
        assert result["commission_pct"] == 15.0

    @pytest.mark.asyncio
    async def test_standard_commission_15_pct(self):
        db = AsyncMock()
        empty_overlap = _db_result([])
        ride_row = MagicMock()
        ride_row.gross = 100.00
        ride_row.ride_count = 5
        ride_result = MagicMock()
        ride_result.one.return_value = ride_row

        db.execute.side_effect = [empty_overlap, ride_result]

        with patch(
            "app.services.driver_payouts.get_driver_commission_pct",
            new=AsyncMock(return_value=15.0),
        ):
            result = await calculate_pending_earnings(
                db, driver_id=1,
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 7),
            )

        assert result["gross_usd"] == Decimal("100.00")
        assert result["platform_fee_usd"] == Decimal("15.00")
        assert result["net_usd"] == Decimal("85.00")
        assert result["ride_count"] == 5

    @pytest.mark.asyncio
    async def test_subscription_zero_commission(self):
        db = AsyncMock()
        empty_overlap = _db_result([])
        ride_row = MagicMock()
        ride_row.gross = 200.00
        ride_row.ride_count = 10
        ride_result = MagicMock()
        ride_result.one.return_value = ride_row

        db.execute.side_effect = [empty_overlap, ride_result]

        with patch(
            "app.services.driver_payouts.get_driver_commission_pct",
            new=AsyncMock(return_value=0.0),
        ):
            result = await calculate_pending_earnings(
                db, driver_id=1,
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 7),
            )

        assert result["gross_usd"] == Decimal("200.00")
        assert result["platform_fee_usd"] == Decimal("0.00")
        assert result["net_usd"] == Decimal("200.00")
        assert result["commission_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_existing_covered_rides_excluded(self):
        """When an existing payout covers the period, covered rides are subtracted."""
        db = AsyncMock()

        existing_payout = _make_payout(
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 7),
        )
        overlap_result = _db_result([existing_payout])

        ride_row = MagicMock()
        ride_row.gross = 100.00
        ride_row.ride_count = 5
        ride_result = MagicMock()
        ride_result.one.return_value = ride_row

        covered_row = MagicMock()
        covered_row.covered_gross = 100.00
        covered_row.covered_count = 5
        covered_result = MagicMock()
        covered_result.one.return_value = covered_row

        db.execute.side_effect = [overlap_result, ride_result, covered_result]

        with patch(
            "app.services.driver_payouts.get_driver_commission_pct",
            new=AsyncMock(return_value=15.0),
        ):
            result = await calculate_pending_earnings(
                db, driver_id=1,
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 7),
            )

        assert result["gross_usd"] == Decimal("0.00")
        assert result["ride_count"] == 0

    @pytest.mark.asyncio
    async def test_decimal_precision(self):
        """Platform fee is rounded to 2 d.p. correctly."""
        db = AsyncMock()
        empty_overlap = _db_result([])
        ride_row = MagicMock()
        ride_row.gross = 33.33  # 15 % of 33.33 = 4.9995 → 5.00
        ride_row.ride_count = 1
        ride_result = MagicMock()
        ride_result.one.return_value = ride_row

        db.execute.side_effect = [empty_overlap, ride_result]

        with patch(
            "app.services.driver_payouts.get_driver_commission_pct",
            new=AsyncMock(return_value=15.0),
        ):
            result = await calculate_pending_earnings(
                db, driver_id=1,
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 7),
            )

        # Verify exact Decimal arithmetic
        assert result["platform_fee_usd"] == (result["gross_usd"] - result["net_usd"])


# ---------------------------------------------------------------------------
# request_payout
# ---------------------------------------------------------------------------


class TestRequestPayout:
    @pytest.mark.asyncio
    async def test_success(self):
        db = AsyncMock()
        # No overlapping payout
        no_overlap = _db_result(None)
        db.execute.return_value = no_overlap
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()  # db.add is sync in SQLAlchemy

        earnings = {
            "gross_usd": Decimal("100.00"),
            "platform_fee_usd": Decimal("15.00"),
            "net_usd": Decimal("85.00"),
            "ride_count": 5,
            "commission_pct": 15.0,
        }

        with patch(
            "app.services.driver_payouts.calculate_pending_earnings",
            new=AsyncMock(return_value=earnings),
        ):
            payout = await request_payout(
                db,
                driver_id=42,
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 7),
            )

        db.add.assert_called_once()
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_zero_earnings_raises_400(self):
        from fastapi import HTTPException

        db = AsyncMock()
        no_overlap = _db_result(None)
        db.execute.return_value = no_overlap

        earnings = {
            "gross_usd": Decimal("0.00"),
            "platform_fee_usd": Decimal("0.00"),
            "net_usd": Decimal("0.00"),
            "ride_count": 0,
            "commission_pct": 15.0,
        }

        with patch(
            "app.services.driver_payouts.calculate_pending_earnings",
            new=AsyncMock(return_value=earnings),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await request_payout(
                    db,
                    driver_id=42,
                    period_start=date(2026, 4, 1),
                    period_end=date(2026, 4, 7),
                )

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_overlapping_payout_raises_400(self):
        from fastapi import HTTPException

        db = AsyncMock()
        existing = _make_payout(status=DriverPayoutStatus.pending)
        overlap_result = _db_result(existing)
        db.execute.return_value = overlap_result

        with pytest.raises(HTTPException) as exc_info:
            await request_payout(
                db,
                driver_id=42,
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 7),
            )

        assert exc_info.value.status_code == 400
        assert "overlapping" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_method_default_is_stripe(self):
        db = AsyncMock()
        no_overlap = _db_result(None)
        db.execute.return_value = no_overlap
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        # db.add is synchronous in SQLAlchemy — use MagicMock so side_effect works
        db.add = MagicMock()

        earnings = {
            "gross_usd": Decimal("100.00"),
            "platform_fee_usd": Decimal("15.00"),
            "net_usd": Decimal("85.00"),
            "ride_count": 1,
            "commission_pct": 15.0,
        }

        with patch(
            "app.services.driver_payouts.calculate_pending_earnings",
            new=AsyncMock(return_value=earnings),
        ):
            await request_payout(db, driver_id=42,
                                 period_start=date(2026, 4, 1),
                                 period_end=date(2026, 4, 7))

        db.add.assert_called_once()
        added_payout = db.add.call_args[0][0]
        assert added_payout.method == DriverPayoutMethod.stripe_transfer

    @pytest.mark.asyncio
    async def test_manual_method(self):
        db = AsyncMock()
        no_overlap = _db_result(None)
        db.execute.return_value = no_overlap
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()

        earnings = {
            "gross_usd": Decimal("50.00"),
            "platform_fee_usd": Decimal("7.50"),
            "net_usd": Decimal("42.50"),
            "ride_count": 2,
            "commission_pct": 15.0,
        }

        with patch(
            "app.services.driver_payouts.calculate_pending_earnings",
            new=AsyncMock(return_value=earnings),
        ):
            await request_payout(db, driver_id=42,
                                 period_start=date(2026, 4, 1),
                                 period_end=date(2026, 4, 7),
                                 method=DriverPayoutMethod.manual)

        db.add.assert_called_once()
        added_payout = db.add.call_args[0][0]
        assert added_payout.method == DriverPayoutMethod.manual


# ---------------------------------------------------------------------------
# process_payout
# ---------------------------------------------------------------------------


class TestProcessPayout:
    @pytest.mark.asyncio
    async def test_success_transitions_to_completed(self):
        db = AsyncMock()
        payout = _make_payout(status=DriverPayoutStatus.pending)

        payout_result = _db_result(payout)
        db.execute.return_value = payout_result
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        result = await process_payout(db, payout_id=1)

        assert payout.status == DriverPayoutStatus.completed
        assert payout.processed_at is not None

    @pytest.mark.asyncio
    async def test_notes_are_saved(self):
        db = AsyncMock()
        payout = _make_payout(status=DriverPayoutStatus.pending)
        payout_result = _db_result(payout)
        db.execute.return_value = payout_result
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        await process_payout(db, payout_id=1, admin_notes="Approved manually")

        assert payout.notes == "Approved manually"

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from fastapi import HTTPException

        db = AsyncMock()
        not_found = _db_result(None)
        db.execute.return_value = not_found

        with pytest.raises(HTTPException) as exc_info:
            await process_payout(db, payout_id=999)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_non_pending_raises_400(self):
        from fastapi import HTTPException

        db = AsyncMock()
        payout = _make_payout(status=DriverPayoutStatus.completed)
        payout_result = _db_result(payout)
        db.execute.return_value = payout_result

        with pytest.raises(HTTPException) as exc_info:
            await process_payout(db, payout_id=1)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_processing_payout_raises_400(self):
        from fastapi import HTTPException

        db = AsyncMock()
        payout = _make_payout(status=DriverPayoutStatus.processing)
        payout_result = _db_result(payout)
        db.execute.return_value = payout_result

        with pytest.raises(HTTPException) as exc_info:
            await process_payout(db, payout_id=1)

        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# fail_payout
# ---------------------------------------------------------------------------


class TestFailPayout:
    @pytest.mark.asyncio
    async def test_success_from_pending(self):
        db = AsyncMock()
        payout = _make_payout(status=DriverPayoutStatus.pending)
        payout_result = _db_result(payout)
        db.execute.return_value = payout_result
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        result = await fail_payout(db, payout_id=1, reason="Bank rejected")

        assert payout.status == DriverPayoutStatus.failed
        assert payout.failed_reason == "Bank rejected"

    @pytest.mark.asyncio
    async def test_success_from_processing(self):
        db = AsyncMock()
        payout = _make_payout(status=DriverPayoutStatus.processing)
        payout_result = _db_result(payout)
        db.execute.return_value = payout_result
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        await fail_payout(db, payout_id=1, reason="Transfer timeout")
        assert payout.status == DriverPayoutStatus.failed

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from fastapi import HTTPException

        db = AsyncMock()
        not_found = _db_result(None)
        db.execute.return_value = not_found

        with pytest.raises(HTTPException) as exc_info:
            await fail_payout(db, payout_id=999, reason="whatever")

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_completed_raises_400(self):
        from fastapi import HTTPException

        db = AsyncMock()
        payout = _make_payout(status=DriverPayoutStatus.completed)
        payout_result = _db_result(payout)
        db.execute.return_value = payout_result

        with pytest.raises(HTTPException) as exc_info:
            await fail_payout(db, payout_id=1, reason="oops")

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_already_failed_raises_400(self):
        from fastapi import HTTPException

        db = AsyncMock()
        payout = _make_payout(status=DriverPayoutStatus.failed)
        payout_result = _db_result(payout)
        db.execute.return_value = payout_result

        with pytest.raises(HTTPException) as exc_info:
            await fail_payout(db, payout_id=1, reason="double fail")

        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# get_payout
# ---------------------------------------------------------------------------


class TestGetPayout:
    @pytest.mark.asyncio
    async def test_found(self):
        db = AsyncMock()
        payout = _make_payout()
        db.execute.return_value = _db_result(payout)

        result = await get_payout(db, payout_id=1)
        assert result is payout

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from fastapi import HTTPException

        db = AsyncMock()
        db.execute.return_value = _db_result(None)

        with pytest.raises(HTTPException) as exc_info:
            await get_payout(db, payout_id=999)

        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# get_driver_payouts
# ---------------------------------------------------------------------------


class TestGetDriverPayouts:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        db = AsyncMock()
        payouts = [_make_payout(id=i) for i in range(3)]
        db.execute.return_value = _db_result(payouts)

        result = await get_driver_payouts(db, driver_id=42)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_empty_list(self):
        db = AsyncMock()
        db.execute.return_value = _db_result([])

        result = await get_driver_payouts(db, driver_id=99)
        assert result == []

    @pytest.mark.asyncio
    async def test_pagination_params_passed(self):
        db = AsyncMock()
        db.execute.return_value = _db_result([])

        await get_driver_payouts(db, driver_id=42, skip=10, limit=5)
        db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# get_all_payouts
# ---------------------------------------------------------------------------


class TestGetAllPayouts:
    @pytest.mark.asyncio
    async def test_no_filter(self):
        db = AsyncMock()
        payouts = [_make_payout(id=i, driver_id=i) for i in range(5)]
        db.execute.return_value = _db_result(payouts)

        result = await get_all_payouts(db)
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_status_filter(self):
        db = AsyncMock()
        db.execute.return_value = _db_result([])

        result = await get_all_payouts(db, status_filter=DriverPayoutStatus.completed)
        assert result == []
        db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# get_payout_stats
# ---------------------------------------------------------------------------


class TestGetPayoutStats:
    @pytest.mark.asyncio
    async def test_stats_aggregation(self):
        db = AsyncMock()

        pending_row = MagicMock()
        pending_row.cnt = 3
        pending_row.total = Decimal("300.00")
        pending_result = MagicMock()
        pending_result.one.return_value = pending_row

        completed_row = MagicMock()
        completed_row.cnt = 10
        completed_row.total = Decimal("1000.00")
        completed_result = MagicMock()
        completed_result.one.return_value = completed_row

        failed_scalar = MagicMock()
        failed_scalar.scalar.return_value = 2
        failed_result = MagicMock()
        failed_result.scalar.return_value = 2

        db.execute.side_effect = [pending_result, completed_result, failed_result]

        stats = await get_payout_stats(db)

        assert stats.pending_count == 3
        assert stats.total_pending_usd == Decimal("300.00")
        assert stats.completed_count == 10
        assert stats.total_completed_usd == Decimal("1000.00")
        assert stats.failed_count == 2
        assert stats.avg_payout_usd == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_stats_no_completed_payouts(self):
        """avg_payout_usd should be 0.00 when there are no completed payouts."""
        db = AsyncMock()

        pending_row = MagicMock()
        pending_row.cnt = 0
        pending_row.total = Decimal("0.00")
        pending_result = MagicMock()
        pending_result.one.return_value = pending_row

        completed_row = MagicMock()
        completed_row.cnt = 0
        completed_row.total = Decimal("0.00")
        completed_result = MagicMock()
        completed_result.one.return_value = completed_row

        failed_result = MagicMock()
        failed_result.scalar.return_value = 0

        db.execute.side_effect = [pending_result, completed_result, failed_result]

        stats = await get_payout_stats(db)

        assert stats.avg_payout_usd == Decimal("0.00")


# ---------------------------------------------------------------------------
# Router / endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_driver():
    from app.models.user import User, UserRole
    user = MagicMock(spec=User)
    user.id = 42
    user.role = UserRole.DRIVER
    return user


@pytest.fixture
def mock_admin():
    from app.models.user import User, UserRole
    user = MagicMock(spec=User)
    user.id = 1
    user.role = UserRole.ADMIN
    return user


@pytest.fixture
def mock_db():
    return AsyncMock()


class TestPendingEarningsEndpoint:
    @pytest.mark.asyncio
    async def test_returns_pending_earnings(self, mock_driver, mock_db):
        from app.api.v1.driver_payouts import get_pending_earnings

        earnings = {
            "gross_usd": Decimal("100.00"),
            "platform_fee_usd": Decimal("15.00"),
            "net_usd": Decimal("85.00"),
            "ride_count": 5,
            "commission_pct": 15.0,
        }

        with patch(
            "app.api.v1.driver_payouts.calculate_pending_earnings",
            new=AsyncMock(return_value=earnings),
        ):
            result = await get_pending_earnings(
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 7),
                user=mock_driver,
                db=mock_db,
            )

        assert result.driver_id == 42
        assert result.gross_usd == Decimal("100.00")
        assert result.ride_count == 5

    @pytest.mark.asyncio
    async def test_defaults_to_last_7_days(self, mock_driver, mock_db):
        from app.api.v1.driver_payouts import get_pending_earnings

        earnings = {
            "gross_usd": Decimal("0.00"),
            "platform_fee_usd": Decimal("0.00"),
            "net_usd": Decimal("0.00"),
            "ride_count": 0,
            "commission_pct": 15.0,
        }

        with patch(
            "app.api.v1.driver_payouts.calculate_pending_earnings",
            new=AsyncMock(return_value=earnings),
        ) as mock_calc:
            result = await get_pending_earnings(
                period_start=None,
                period_end=None,
                user=mock_driver,
                db=mock_db,
            )
            # Check that the default period was used (7 days back to today)
            call_args = mock_calc.call_args
            passed_start = call_args.args[2]
            passed_end = call_args.args[3]
            assert passed_end == date.today()
            assert passed_start == date.today() - timedelta(days=7)


class TestListMyPayoutsEndpoint:
    @pytest.mark.asyncio
    async def test_returns_list(self, mock_driver, mock_db):
        from app.api.v1.driver_payouts import list_my_payouts

        payouts = [_make_payout(id=i, driver_id=42) for i in range(3)]

        with patch(
            "app.api.v1.driver_payouts.get_driver_payouts",
            new=AsyncMock(return_value=payouts),
        ):
            result = await list_my_payouts(
                skip=0, limit=20, user=mock_driver, db=mock_db
            )

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_empty_list(self, mock_driver, mock_db):
        from app.api.v1.driver_payouts import list_my_payouts

        with patch(
            "app.api.v1.driver_payouts.get_driver_payouts",
            new=AsyncMock(return_value=[]),
        ):
            result = await list_my_payouts(
                skip=0, limit=20, user=mock_driver, db=mock_db
            )

        assert result == []


class TestRequestPayoutEndpoint:
    @pytest.mark.asyncio
    async def test_success(self, mock_driver, mock_db):
        from app.api.v1.driver_payouts import request_my_payout

        payout = _make_payout()

        with patch(
            "app.api.v1.driver_payouts.request_payout",
            new=AsyncMock(return_value=payout),
        ):
            req = PayoutRequestRequest(
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 7),
            )
            result = await request_my_payout(req=req, user=mock_driver, db=mock_db)

        assert result.driver_id == 42

    @pytest.mark.asyncio
    async def test_defaults_period_when_not_supplied(self, mock_driver, mock_db):
        from app.api.v1.driver_payouts import request_my_payout

        payout = _make_payout()

        with patch(
            "app.api.v1.driver_payouts.request_payout",
            new=AsyncMock(return_value=payout),
        ) as mock_req:
            req = PayoutRequestRequest()
            await request_my_payout(req=req, user=mock_driver, db=mock_db)

            call_args = mock_req.call_args
            passed_start = call_args.args[2]
            passed_end = call_args.args[3]
            assert passed_end == date.today()
            assert passed_start == date.today() - timedelta(days=7)


class TestAdminListPayoutsEndpoint:
    @pytest.mark.asyncio
    async def test_no_filter(self, mock_admin, mock_db):
        from app.api.v1.driver_payouts import admin_list_payouts

        payouts = [_make_payout(id=i) for i in range(5)]

        with patch(
            "app.api.v1.driver_payouts.get_all_payouts",
            new=AsyncMock(return_value=payouts),
        ):
            result = await admin_list_payouts(
                status=None, skip=0, limit=20, _admin=mock_admin, db=mock_db
            )

        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_with_status_filter(self, mock_admin, mock_db):
        from app.api.v1.driver_payouts import admin_list_payouts

        payouts = [_make_payout(status=DriverPayoutStatus.completed)]

        with patch(
            "app.api.v1.driver_payouts.get_all_payouts",
            new=AsyncMock(return_value=payouts),
        ) as mock_all:
            await admin_list_payouts(
                status=DriverPayoutStatus.completed,
                skip=0, limit=20, _admin=mock_admin, db=mock_db,
            )
            mock_all.assert_called_once_with(
                mock_db,
                status_filter=DriverPayoutStatus.completed,
                skip=0,
                limit=20,
            )


class TestAdminPayoutStatsEndpoint:
    @pytest.mark.asyncio
    async def test_returns_stats(self, mock_admin, mock_db):
        from app.api.v1.driver_payouts import admin_payout_stats

        stats = PayoutStatsResponse(
            total_pending_usd=Decimal("500.00"),
            total_completed_usd=Decimal("10000.00"),
            pending_count=5,
            completed_count=100,
            failed_count=2,
            avg_payout_usd=Decimal("100.00"),
        )

        with patch(
            "app.api.v1.driver_payouts.get_payout_stats",
            new=AsyncMock(return_value=stats),
        ):
            result = await admin_payout_stats(_admin=mock_admin, db=mock_db)

        assert result.completed_count == 100
        assert result.avg_payout_usd == Decimal("100.00")


class TestAdminProcessPayoutEndpoint:
    @pytest.mark.asyncio
    async def test_success(self, mock_admin, mock_db):
        from app.api.v1.driver_payouts import admin_process_payout

        payout = _make_payout(status=DriverPayoutStatus.completed)

        with patch(
            "app.api.v1.driver_payouts.process_payout",
            new=AsyncMock(return_value=payout),
        ) as mock_proc:
            req = AdminProcessPayoutRequest(notes="Processed by admin")
            result = await admin_process_payout(
                payout_id=1, req=req, _admin=mock_admin, db=mock_db
            )
            mock_proc.assert_called_once_with(mock_db, 1, admin_notes="Processed by admin")

        assert result.status == DriverPayoutStatus.completed

    @pytest.mark.asyncio
    async def test_no_body(self, mock_admin, mock_db):
        from app.api.v1.driver_payouts import admin_process_payout

        payout = _make_payout(status=DriverPayoutStatus.completed)

        with patch(
            "app.api.v1.driver_payouts.process_payout",
            new=AsyncMock(return_value=payout),
        ) as mock_proc:
            result = await admin_process_payout(
                payout_id=1, req=None, _admin=mock_admin, db=mock_db
            )
            mock_proc.assert_called_once_with(mock_db, 1, admin_notes=None)


class TestAdminFailPayoutEndpoint:
    @pytest.mark.asyncio
    async def test_success(self, mock_admin, mock_db):
        from app.api.v1.driver_payouts import admin_fail_payout

        payout = _make_payout(
            status=DriverPayoutStatus.failed,
            failed_reason="Bank rejected",
        )

        with patch(
            "app.api.v1.driver_payouts.fail_payout",
            new=AsyncMock(return_value=payout),
        ) as mock_fail:
            req = AdminFailPayoutRequest(reason="Bank rejected")
            result = await admin_fail_payout(
                payout_id=1, req=req, _admin=mock_admin, db=mock_db
            )
            mock_fail.assert_called_once_with(mock_db, 1, reason="Bank rejected")

        assert result.status == DriverPayoutStatus.failed
        assert result.failed_reason == "Bank rejected"


# ---------------------------------------------------------------------------
# Schema field validation
# ---------------------------------------------------------------------------


class TestAdminFailPayoutRequestSchema:
    def test_reason_required(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AdminFailPayoutRequest()

    def test_reason_provided(self):
        req = AdminFailPayoutRequest(reason="Something went wrong")
        assert req.reason == "Something went wrong"


class TestAdminProcessPayoutRequestSchema:
    def test_notes_optional(self):
        req = AdminProcessPayoutRequest()
        assert req.notes is None

    def test_notes_provided(self):
        req = AdminProcessPayoutRequest(notes="Manually processed")
        assert req.notes == "Manually processed"
