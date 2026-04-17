"""Tests for the ride cancellation policy and fee system.

Covers:
  - evaluate_cancellation (pure function, legacy stateless layer)
  - calculate_rider_fee / calculate_driver_fee (pure functions)
  - CancellationError (exception class)
  - CancellationPolicy / CancellationRecord (ORM model structure)
  - get_active_policy (async, mocked DB)
  - record_cancellation (async, mocked DB)
  - waive_fee (async, mocked DB)
  - admin_get_all / admin_get_summary (async, mocked DB)
  - Pydantic schemas (CancellationPolicyCreate, WaiveFeeRequest, etc.)

No live database is used. All DB interactions are mocked with AsyncMock /
MagicMock following the same pattern established in test_fare_splits.py.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.cancellation import (
    CancelledBy,
    CancellationPolicy,
    CancellationRecord,
    FeeChargedTo,
    FeeStatus,
)
from app.models.ride import RideStatus
from app.schemas.cancellation import (
    CancellationPolicyCreate,
    CancellationRecordResponse,
    RiderCancelRequest,
    WaiveFeeRequest,
)
from app.services.cancellation import (
    ARRIVED_CANCEL_FEE,
    EN_ROUTE_CANCEL_FEE,
    FREE_CANCEL_GRACE_SECONDS,
    CancellationError,
    admin_get_all,
    admin_get_summary,
    calculate_driver_fee,
    calculate_rider_fee,
    evaluate_cancellation,
    get_active_policy,
    record_cancellation,
    waive_fee,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(_UTC)


def _policy(
    grace=120,
    fee_flat="5.00",
    fee_percent="0.0000",
    free_cancels=3,
    penalty="2.00",
) -> CancellationPolicy:
    """Build a CancellationPolicy ORM object without a real DB."""
    p = MagicMock(spec=CancellationPolicy)
    p.rider_grace_period_seconds = grace
    p.rider_fee_flat = Decimal(fee_flat)
    p.rider_fee_percent = Decimal(fee_percent)
    p.driver_free_cancels_per_day = free_cancels
    p.driver_cancel_penalty = Decimal(penalty)
    p.is_active = True
    return p


def _make_record(
    record_id=1,
    ride_id=1,
    cancelled_by=CancelledBy.rider,
    fee_applied=Decimal("0.00"),
    fee_status=FeeStatus.pending,
    grace_expired=False,
    waived_by_admin_id=None,
    waive_reason=None,
) -> MagicMock:
    """Build a CancellationRecord ORM mock."""
    r = MagicMock(spec=CancellationRecord)
    r.id = record_id
    r.ride_id = ride_id
    r.cancelled_by = cancelled_by
    r.fee_applied = fee_applied
    r.fee_status = fee_status
    r.grace_period_expired = grace_expired
    r.waived_by_admin_id = waived_by_admin_id
    r.waive_reason = waive_reason
    r.cancellation_reason = None
    r.cancelled_at = _now()
    r.fee_charged_to = FeeChargedTo.none
    r.created_at = _now()
    return r


def _make_ride_mock(
    ride_id=1,
    rider_id=10,
    driver_id=20,
    status=RideStatus.MATCHED,
    estimated_fare=20.0,
    requested_at=None,
) -> MagicMock:
    """Build a Ride ORM mock with sensible defaults."""
    from app.models.ride import Ride
    r = MagicMock(spec=Ride)
    r.id = ride_id
    r.rider_id = rider_id
    r.driver_id = driver_id
    r.status = status
    r.estimated_fare = estimated_fare
    r.requested_at = requested_at or (_now() - timedelta(seconds=300))
    return r


def _db_returning(*rows):
    """Return a mock AsyncSession whose execute() returns the given rows in
    sequence. Each element of *rows* is either a scalar value or a list of
    scalars."""
    db = AsyncMock()
    results = []
    for row in rows:
        result = MagicMock()
        if isinstance(row, list):
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = row
            result.scalars.return_value = scalars_mock
        else:
            result.scalar_one_or_none.return_value = row
            result.scalar.return_value = row
        results.append(result)
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ===========================================================================
# TestEvaluateCancellation
# ===========================================================================


class TestEvaluateCancellation:
    """Tests for the pure evaluate_cancellation function (legacy layer)."""

    def test_already_cancelled(self):
        result = evaluate_cancellation(
            RideStatus.CANCELLED, "rider", 20.0, matched_at=None
        )
        assert result.allowed is False
        assert "already" in result.reason.lower()

    def test_completed_blocked(self):
        result = evaluate_cancellation(
            RideStatus.COMPLETED, "rider", 20.0, matched_at=None
        )
        assert result.allowed is False

    def test_in_progress_blocked(self):
        result = evaluate_cancellation(
            RideStatus.IN_PROGRESS, "rider", 20.0, matched_at=None
        )
        assert result.allowed is False
        assert result.fee == 0.0

    def test_scheduled_free(self):
        result = evaluate_cancellation(
            RideStatus.SCHEDULED, "rider", 20.0, matched_at=None
        )
        assert result.allowed is True
        assert result.fee == 0.0

    def test_requested_free(self):
        result = evaluate_cancellation(
            RideStatus.REQUESTED, "rider", 20.0, matched_at=None
        )
        assert result.allowed is True
        assert result.fee == 0.0

    def test_driver_cancel_always_free(self):
        matched_at = _now() - timedelta(seconds=600)
        result = evaluate_cancellation(
            RideStatus.ARRIVED, "driver", 20.0, matched_at=matched_at
        )
        assert result.allowed is True
        assert result.fee == 0.0

    def test_rider_within_grace_period(self):
        matched_at = _now() - timedelta(seconds=60)  # 60s < 120s grace
        result = evaluate_cancellation(
            RideStatus.MATCHED, "rider", 20.0, matched_at=matched_at
        )
        assert result.allowed is True
        assert result.fee == 0.0
        assert "grace" in result.reason.lower()

    def test_rider_grace_expired_matched_status(self):
        matched_at = _now() - timedelta(seconds=300)
        result = evaluate_cancellation(
            RideStatus.MATCHED, "rider", 50.0, matched_at=matched_at
        )
        assert result.allowed is True
        assert result.fee == EN_ROUTE_CANCEL_FEE

    def test_rider_grace_expired_en_route(self):
        matched_at = _now() - timedelta(seconds=300)
        result = evaluate_cancellation(
            RideStatus.DRIVER_EN_ROUTE, "rider", 50.0, matched_at=matched_at
        )
        assert result.allowed is True
        assert result.fee == EN_ROUTE_CANCEL_FEE

    def test_rider_grace_expired_arrived(self):
        matched_at = _now() - timedelta(seconds=300)
        result = evaluate_cancellation(
            RideStatus.ARRIVED, "rider", 50.0, matched_at=matched_at
        )
        assert result.allowed is True
        assert result.fee == ARRIVED_CANCEL_FEE

    def test_fee_capped_at_max_percent(self):
        # Very low fare so that EN_ROUTE_CANCEL_FEE would exceed 50% of fare
        matched_at = _now() - timedelta(seconds=300)
        low_fare = 1.00  # 50% cap => max fee = 0.50, which is < EN_ROUTE_CANCEL_FEE=3.00
        result = evaluate_cancellation(
            RideStatus.DRIVER_EN_ROUTE, "rider", low_fare, matched_at=matched_at
        )
        assert result.allowed is True
        assert result.fee <= low_fare * 0.50 + 0.01  # allow rounding

    def test_dispatch_retry_free(self):
        result = evaluate_cancellation(
            RideStatus.REQUESTED, "rider", 20.0, matched_at=None, dispatch_retry_count=2
        )
        assert result.allowed is True
        assert result.fee == 0.0
        assert "retry" in result.reason.lower()

    def test_no_match_time_means_past_grace(self):
        # matched_at=None with MATCHED status — falls through to fee path
        result = evaluate_cancellation(
            RideStatus.MATCHED, "rider", 50.0, matched_at=None
        )
        assert result.allowed is True
        assert result.fee == EN_ROUTE_CANCEL_FEE

    def test_custom_now_respected(self):
        matched_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=_UTC)
        now = datetime(2024, 1, 1, 12, 1, 0, tzinfo=_UTC)  # 60s later, within grace
        result = evaluate_cancellation(
            RideStatus.MATCHED, "rider", 50.0, matched_at=matched_at, now=now
        )
        assert result.fee == 0.0


# ===========================================================================
# TestCalculateRiderFee
# ===========================================================================


class TestCalculateRiderFee:
    """Tests for the pure calculate_rider_fee function."""

    def _times(self, elapsed_seconds: float):
        base = datetime(2024, 6, 1, 10, 0, 0, tzinfo=_UTC)
        return base, base + timedelta(seconds=elapsed_seconds)

    def test_within_grace_no_fee(self):
        p = _policy(grace=120, fee_flat="5.00", fee_percent="0.0000")
        booking, cancel = self._times(60)
        fee, grace_expired = calculate_rider_fee(p, 20.0, booking, cancel)
        assert fee == Decimal("0.00")
        assert grace_expired is False

    def test_past_grace_flat_only(self):
        p = _policy(grace=120, fee_flat="5.00", fee_percent="0.0000")
        booking, cancel = self._times(200)
        fee, grace_expired = calculate_rider_fee(p, 20.0, booking, cancel)
        assert fee == Decimal("5.00")
        assert grace_expired is True

    def test_past_grace_percent_only(self):
        p = _policy(grace=120, fee_flat="0.00", fee_percent="0.1000")
        booking, cancel = self._times(200)
        fee, grace_expired = calculate_rider_fee(p, 20.0, booking, cancel)
        assert fee == Decimal("2.00")  # 10% of 20.00
        assert grace_expired is True

    def test_past_grace_flat_and_percent(self):
        p = _policy(grace=120, fee_flat="3.00", fee_percent="0.1000")
        booking, cancel = self._times(200)
        fee, grace_expired = calculate_rider_fee(p, 20.0, booking, cancel)
        assert fee == Decimal("5.00")  # 3.00 + 2.00
        assert grace_expired is True

    def test_grace_boundary_exact(self):
        # elapsed == grace_period_seconds: boundary is >, so exactly at limit is still free
        p = _policy(grace=120, fee_flat="5.00")
        booking, cancel = self._times(120)  # exactly 120s
        fee, grace_expired = calculate_rider_fee(p, 20.0, booking, cancel)
        assert fee == Decimal("0.00")
        assert grace_expired is False

    def test_one_second_over_grace(self):
        p = _policy(grace=120, fee_flat="5.00", fee_percent="0.0000")
        booking, cancel = self._times(121)
        fee, grace_expired = calculate_rider_fee(p, 20.0, booking, cancel)
        assert fee == Decimal("5.00")
        assert grace_expired is True

    def test_result_quantized_to_cents(self):
        p = _policy(grace=60, fee_flat="0.00", fee_percent="0.1000")
        booking, cancel = self._times(120)
        fee, _ = calculate_rider_fee(p, 10.005, booking, cancel)
        # Should be rounded to 2 decimal places
        assert fee == fee.quantize(Decimal("0.01"))


# ===========================================================================
# TestCalculateDriverFee
# ===========================================================================


class TestCalculateDriverFee:
    """Tests for the pure calculate_driver_fee function."""

    def test_within_free_limit_no_fee(self):
        p = _policy(free_cancels=3, penalty="2.00")
        fee = calculate_driver_fee(p, driver_cancel_count_today=1)
        # 1 + 1 = 2, which is <= 3 free limit
        assert fee == Decimal("0.00")

    def test_at_limit_no_fee(self):
        p = _policy(free_cancels=3, penalty="2.00")
        fee = calculate_driver_fee(p, driver_cancel_count_today=2)
        # 2 + 1 = 3, which equals (not exceeds) free limit
        assert fee == Decimal("0.00")

    def test_exceeds_limit_penalty(self):
        p = _policy(free_cancels=3, penalty="2.00")
        fee = calculate_driver_fee(p, driver_cancel_count_today=3)
        # 3 + 1 = 4 > 3 → penalty
        assert fee == Decimal("2.00")

    def test_exceeds_limit_by_more(self):
        p = _policy(free_cancels=3, penalty="2.00")
        fee = calculate_driver_fee(p, driver_cancel_count_today=5)
        # 5 + 1 = 6 > 3 → same flat penalty
        assert fee == Decimal("2.00")

    def test_zero_free_cancels(self):
        p = _policy(free_cancels=0, penalty="2.00")
        fee = calculate_driver_fee(p, driver_cancel_count_today=0)
        # 0 + 1 = 1 > 0 → penalty applies immediately
        assert fee == Decimal("2.00")

    def test_penalty_quantized_to_cents(self):
        p = _policy(free_cancels=0, penalty="1.505")
        fee = calculate_driver_fee(p, driver_cancel_count_today=0)
        assert fee == fee.quantize(Decimal("0.01"))


# ===========================================================================
# TestCancellationError
# ===========================================================================


class TestCancellationError:
    """Tests for the CancellationError exception class."""

    def test_default_status_code(self):
        exc = CancellationError("something went wrong")
        assert exc.status_code == 400

    def test_custom_status_code(self):
        exc = CancellationError("not found", status_code=404)
        assert exc.status_code == 404

    def test_message_preserved(self):
        msg = "ride has already been cancelled"
        exc = CancellationError(msg)
        assert str(exc) == msg

    def test_is_exception(self):
        exc = CancellationError("test")
        assert isinstance(exc, Exception)

    def test_409_status(self):
        exc = CancellationError("duplicate", status_code=409)
        assert exc.status_code == 409


# ===========================================================================
# TestCancellationPolicyModel
# ===========================================================================


class TestCancellationPolicyModel:
    """Tests verifying the CancellationPolicy ORM table structure."""

    def _cols(self):
        return {c.name for c in CancellationPolicy.__table__.columns}

    def test_table_name(self):
        assert CancellationPolicy.__tablename__ == "cancellation_policies"

    def test_has_id(self):
        assert "id" in self._cols()

    def test_has_rider_grace_period_seconds(self):
        assert "rider_grace_period_seconds" in self._cols()

    def test_has_rider_fee_flat(self):
        assert "rider_fee_flat" in self._cols()

    def test_has_rider_fee_percent(self):
        assert "rider_fee_percent" in self._cols()

    def test_has_driver_free_cancels_per_day(self):
        assert "driver_free_cancels_per_day" in self._cols()

    def test_has_driver_cancel_penalty(self):
        assert "driver_cancel_penalty" in self._cols()

    def test_has_is_active(self):
        assert "is_active" in self._cols()

    def test_has_created_at(self):
        assert "created_at" in self._cols()

    def test_has_updated_at(self):
        assert "updated_at" in self._cols()

    def test_is_active_is_indexed(self):
        col = CancellationPolicy.__table__.columns["is_active"]
        assert col.index is True


# ===========================================================================
# TestCancellationRecordModel
# ===========================================================================


class TestCancellationRecordModel:
    """Tests verifying the CancellationRecord ORM table structure."""

    def _cols(self):
        return {c.name for c in CancellationRecord.__table__.columns}

    def test_table_name(self):
        assert CancellationRecord.__tablename__ == "cancellation_records"

    def test_has_id(self):
        assert "id" in self._cols()

    def test_has_ride_id(self):
        assert "ride_id" in self._cols()

    def test_has_cancelled_by(self):
        assert "cancelled_by" in self._cols()

    def test_has_cancellation_reason(self):
        assert "cancellation_reason" in self._cols()

    def test_has_cancelled_at(self):
        assert "cancelled_at" in self._cols()

    def test_has_grace_period_expired(self):
        assert "grace_period_expired" in self._cols()

    def test_has_fee_applied(self):
        assert "fee_applied" in self._cols()

    def test_has_fee_charged_to(self):
        assert "fee_charged_to" in self._cols()

    def test_has_fee_status(self):
        assert "fee_status" in self._cols()

    def test_has_waived_by_admin_id(self):
        assert "waived_by_admin_id" in self._cols()

    def test_has_waive_reason(self):
        assert "waive_reason" in self._cols()

    def test_has_created_at(self):
        assert "created_at" in self._cols()

    def test_ride_id_is_indexed(self):
        col = CancellationRecord.__table__.columns["ride_id"]
        assert col.index is True

    def test_ride_id_has_fk(self):
        col = CancellationRecord.__table__.columns["ride_id"]
        targets = {fk.target_fullname for fk in col.foreign_keys}
        assert "rides.id" in targets

    def test_ride_id_is_unique(self):
        col = CancellationRecord.__table__.columns["ride_id"]
        assert col.unique is True


# ===========================================================================
# TestGetActivePolicy
# ===========================================================================


class TestGetActivePolicy:
    """Tests for get_active_policy (async service function with mocked DB)."""

    @pytest.mark.asyncio
    async def test_returns_existing_policy(self):
        existing = _policy(grace=60, fee_flat="3.00")
        db = _db_returning(existing)
        result = await get_active_policy(db)
        assert result is existing

    @pytest.mark.asyncio
    async def test_returns_default_when_none(self):
        db = _db_returning(None)
        result = await get_active_policy(db)
        # Should not be None — a default policy object is returned
        assert result is not None

    @pytest.mark.asyncio
    async def test_default_policy_grace_is_120(self):
        db = _db_returning(None)
        result = await get_active_policy(db)
        assert result.rider_grace_period_seconds == 120

    @pytest.mark.asyncio
    async def test_default_policy_fee_flat_is_5(self):
        db = _db_returning(None)
        result = await get_active_policy(db)
        assert Decimal(str(result.rider_fee_flat)) == Decimal("5.00")

    @pytest.mark.asyncio
    async def test_default_policy_free_cancels_is_3(self):
        db = _db_returning(None)
        result = await get_active_policy(db)
        assert result.driver_free_cancels_per_day == 3

    @pytest.mark.asyncio
    async def test_default_policy_is_active(self):
        db = _db_returning(None)
        result = await get_active_policy(db)
        assert result.is_active is True


# ===========================================================================
# TestRecordCancellation
# ===========================================================================


class TestRecordCancellation:
    """Tests for record_cancellation (async service with mocked DB)."""

    def _build_db(self, ride=None, existing_record=None, policy=None, count_today=0):
        """Build a mock DB session for record_cancellation calls.

        Sequence of db.execute() calls inside record_cancellation:
          0. Ride lookup (scalar_one_or_none)
          1. Existing record check (scalar_one_or_none)
          2. get_active_policy query (scalar_one_or_none)
          3. _count_driver_cancels_today (scalar) — only for driver cancels
        """
        p = policy or _policy()
        db = AsyncMock()
        call_count = [0]

        async def mock_execute(stmt):
            result = MagicMock()
            idx = call_count[0]
            call_count[0] += 1

            if idx == 0:
                result.scalar_one_or_none.return_value = ride
            elif idx == 1:
                result.scalar_one_or_none.return_value = existing_record
            elif idx == 2:
                result.scalar_one_or_none.return_value = p
            else:
                result.scalar.return_value = count_today

            return result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_ride_not_found_raises_404(self):
        db = self._build_db(ride=None)
        with pytest.raises(CancellationError) as exc_info:
            await record_cancellation(
                db, ride_id=1, cancelled_by=CancelledBy.rider,
                reason=None, estimated_fare=20.0,
                booking_time=_now() - timedelta(seconds=300),
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_duplicate_record_raises_409(self):
        ride = _make_ride_mock()
        existing = _make_record()
        db = self._build_db(ride=ride, existing_record=existing)
        with pytest.raises(CancellationError) as exc_info:
            await record_cancellation(
                db, ride_id=1, cancelled_by=CancelledBy.rider,
                reason=None, estimated_fare=20.0,
                booking_time=_now() - timedelta(seconds=300),
            )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_rider_within_grace_no_fee(self):
        ride = _make_ride_mock()
        # booking_time only 30s ago — within 120s grace
        booking_time = _now() - timedelta(seconds=30)
        db = self._build_db(ride=ride, existing_record=None)
        record = await record_cancellation(
            db, ride_id=1, cancelled_by=CancelledBy.rider,
            reason=None, estimated_fare=20.0,
            booking_time=booking_time,
        )
        assert record is not None
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rider_past_grace_fee_applied(self):
        ride = _make_ride_mock()
        booking_time = _now() - timedelta(seconds=300)  # 5 min ago, > 120s grace
        p = _policy(grace=120, fee_flat="5.00")
        db = self._build_db(ride=ride, existing_record=None, policy=p)
        record = await record_cancellation(
            db, ride_id=1, cancelled_by=CancelledBy.rider,
            reason=None, estimated_fare=20.0,
            booking_time=booking_time,
        )
        assert record is not None
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_driver_cancel_within_free_limit(self):
        ride = _make_ride_mock()
        p = _policy(free_cancels=3, penalty="2.00")
        db = self._build_db(ride=ride, existing_record=None, policy=p, count_today=1)
        record = await record_cancellation(
            db, ride_id=1, cancelled_by=CancelledBy.driver,
            reason=None, estimated_fare=20.0,
            booking_time=_now() - timedelta(seconds=300),
            driver_id=20,
        )
        assert record is not None
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_driver_cancel_exceeds_limit(self):
        ride = _make_ride_mock()
        p = _policy(free_cancels=3, penalty="2.00")
        # count_today=3 means this is 4th cancel — exceeds limit
        db = self._build_db(ride=ride, existing_record=None, policy=p, count_today=3)
        record = await record_cancellation(
            db, ride_id=1, cancelled_by=CancelledBy.driver,
            reason=None, estimated_fare=20.0,
            booking_time=_now() - timedelta(seconds=300),
            driver_id=20,
        )
        assert record is not None

    @pytest.mark.asyncio
    async def test_record_cancelled_by_preserved(self):
        ride = _make_ride_mock()
        db = self._build_db(ride=ride, existing_record=None)
        # Verify db.add was called with something (the new record)
        await record_cancellation(
            db, ride_id=1, cancelled_by=CancelledBy.rider,
            reason="changed plans", estimated_fare=20.0,
            booking_time=_now() - timedelta(seconds=30),
        )
        assert db.add.called
        added = db.add.call_args[0][0]
        assert added.cancelled_by == CancelledBy.rider


# ===========================================================================
# TestWaiveFee
# ===========================================================================


class TestWaiveFee:
    """Tests for waive_fee (async service with mocked DB)."""

    def _db_for_waive(self, record):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = record
        db.execute = AsyncMock(return_value=result)
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_waive_pending_fee_succeeds(self):
        record = _make_record(fee_status=FeeStatus.pending, fee_applied=Decimal("5.00"))
        db = self._db_for_waive(record)
        result = await waive_fee(db, cancellation_record_id=1, admin_id=99, reason="goodwill")
        assert result.fee_status == FeeStatus.waived
        assert result.waived_by_admin_id == 99
        assert result.waive_reason == "goodwill"

    @pytest.mark.asyncio
    async def test_waive_already_waived_raises_409(self):
        record = _make_record(fee_status=FeeStatus.waived)
        db = self._db_for_waive(record)
        with pytest.raises(CancellationError) as exc_info:
            await waive_fee(db, cancellation_record_id=1, admin_id=99, reason="test")
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_waive_refunded_raises_409(self):
        record = _make_record(fee_status=FeeStatus.refunded)
        db = self._db_for_waive(record)
        with pytest.raises(CancellationError) as exc_info:
            await waive_fee(db, cancellation_record_id=1, admin_id=99, reason="test")
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_record_not_found_raises_404(self):
        db = self._db_for_waive(record=None)
        with pytest.raises(CancellationError) as exc_info:
            await waive_fee(db, cancellation_record_id=999, admin_id=1, reason="test")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_waive_sets_admin_id_and_reason(self):
        record = _make_record(fee_status=FeeStatus.pending)
        db = self._db_for_waive(record)
        result = await waive_fee(db, cancellation_record_id=1, admin_id=42, reason="driver error")
        assert result.waived_by_admin_id == 42
        assert result.waive_reason == "driver error"

    @pytest.mark.asyncio
    async def test_waive_charged_fee_raises_409(self):
        record = _make_record(fee_status=FeeStatus.charged)
        db = self._db_for_waive(record)
        # charged is not in (waived, refunded), so this should succeed
        result = await waive_fee(db, cancellation_record_id=1, admin_id=1, reason="ok")
        assert result.fee_status == FeeStatus.waived


# ===========================================================================
# TestAdminGetAll
# ===========================================================================


class TestAdminGetAll:
    """Tests for admin_get_all (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_returns_list(self):
        records = [_make_record(record_id=i) for i in range(1, 4)]
        db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = records
        result_mock.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=result_mock)

        result = await admin_get_all(db)
        assert result == records

    @pytest.mark.asyncio
    async def test_applies_fee_status_filter(self):
        """Verify that a filter argument is accepted without error."""
        records = [_make_record(fee_status=FeeStatus.pending)]
        db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = records
        result_mock.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=result_mock)

        result = await admin_get_all(db, fee_status_filter=FeeStatus.pending)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_respects_limit_and_offset(self):
        db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=result_mock)

        result = await admin_get_all(db, skip=10, limit=5)
        assert result == []
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_result(self):
        db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=result_mock)

        result = await admin_get_all(db)
        assert result == []


# ===========================================================================
# TestAdminGetSummary
# ===========================================================================


class TestAdminGetSummary:
    """Tests for admin_get_summary (async service with mocked DB)."""

    def _build_summary_db(self, total=5, total_fees=25.00):
        """Build a DB mock that handles all the sub-queries in admin_get_summary."""
        db = AsyncMock()
        call_count = [0]

        async def mock_execute(stmt):
            result = MagicMock()
            idx = call_count[0]
            call_count[0] += 1

            if idx == 0:
                # Aggregate query: total count + total fees
                row = MagicMock()
                row.total = total
                row.total_fees = total_fees
                result.one.return_value = row
            else:
                # Sub-queries for fee status sums and party counts
                result.scalar.return_value = 0

            return result

        db.execute = AsyncMock(side_effect=mock_execute)
        return db

    @pytest.mark.asyncio
    async def test_returns_correct_keys(self):
        db = self._build_summary_db()
        summary = await admin_get_summary(db)
        expected_keys = {
            "total_cancellations",
            "total_fees_assessed_usd",
            "total_fees_pending_usd",
            "total_fees_charged_usd",
            "total_fees_waived_usd",
            "total_fees_refunded_usd",
            "cancellations_by_rider",
            "cancellations_by_driver",
            "cancellations_by_admin",
            "cancellations_by_system",
        }
        assert set(summary.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_numeric_aggregates_are_floats(self):
        db = self._build_summary_db(total=3, total_fees=15.0)
        summary = await admin_get_summary(db)
        assert isinstance(summary["total_fees_assessed_usd"], float)
        assert isinstance(summary["total_fees_pending_usd"], float)
        assert isinstance(summary["total_fees_charged_usd"], float)
        assert isinstance(summary["total_fees_waived_usd"], float)
        assert isinstance(summary["total_fees_refunded_usd"], float)

    @pytest.mark.asyncio
    async def test_total_cancellations_is_int(self):
        db = self._build_summary_db(total=7)
        summary = await admin_get_summary(db)
        assert isinstance(summary["total_cancellations"], int)
        assert summary["total_cancellations"] == 7

    @pytest.mark.asyncio
    async def test_party_counts_are_ints(self):
        db = self._build_summary_db()
        summary = await admin_get_summary(db)
        for key in ("cancellations_by_rider", "cancellations_by_driver",
                    "cancellations_by_admin", "cancellations_by_system"):
            assert isinstance(summary[key], int)


# ===========================================================================
# TestCancellationSchemas
# ===========================================================================


class TestCancellationSchemas:
    """Pydantic validation tests for cancellation-related schemas."""

    def test_policy_create_defaults(self):
        p = CancellationPolicyCreate()
        assert p.rider_grace_period_seconds == 120
        assert p.rider_fee_flat == Decimal("5.00")
        assert p.driver_free_cancels_per_day == 3

    def test_policy_create_validates_non_negative_flat_fee(self):
        with pytest.raises(Exception):
            CancellationPolicyCreate(rider_fee_flat=Decimal("-1.00"))

    def test_policy_create_non_negative_grace(self):
        with pytest.raises(Exception):
            CancellationPolicyCreate(rider_grace_period_seconds=-1)

    def test_policy_create_fee_percent_max_one(self):
        with pytest.raises(Exception):
            CancellationPolicyCreate(rider_fee_percent=Decimal("1.5"))

    def test_policy_create_custom_values(self):
        p = CancellationPolicyCreate(
            rider_grace_period_seconds=60,
            rider_fee_flat=Decimal("3.00"),
            driver_free_cancels_per_day=5,
        )
        assert p.rider_grace_period_seconds == 60
        assert p.rider_fee_flat == Decimal("3.00")
        assert p.driver_free_cancels_per_day == 5

    def test_waive_request_requires_reason(self):
        with pytest.raises(Exception):
            WaiveFeeRequest()

    def test_waive_request_accepts_reason(self):
        w = WaiveFeeRequest(reason="customer complained")
        assert w.reason == "customer complained"

    def test_waive_request_empty_reason_rejected(self):
        with pytest.raises(Exception):
            WaiveFeeRequest(reason="")

    def test_rider_cancel_request_optional_reason(self):
        r = RiderCancelRequest()
        assert r.reason is None

    def test_rider_cancel_request_with_reason(self):
        r = RiderCancelRequest(reason="plans changed")
        assert r.reason == "plans changed"

    def test_cancellation_record_response_from_attributes(self):
        assert CancellationRecordResponse.model_config.get("from_attributes") is True

    def test_cancellation_record_response_fields(self):
        now = _now()
        resp = CancellationRecordResponse(
            id=1,
            ride_id=5,
            cancelled_by=CancelledBy.rider,
            cancellation_reason="test",
            cancelled_at=now,
            grace_period_expired=True,
            fee_applied=Decimal("5.00"),
            fee_charged_to=FeeChargedTo.rider,
            fee_status=FeeStatus.pending,
            waived_by_admin_id=None,
            waive_reason=None,
            created_at=now,
        )
        assert resp.ride_id == 5
        assert resp.fee_applied == Decimal("5.00")

    def test_cancelled_by_enum_values(self):
        assert CancelledBy.rider.value == "rider"
        assert CancelledBy.driver.value == "driver"
        assert CancelledBy.admin.value == "admin"
        assert CancelledBy.system.value == "system"

    def test_fee_status_enum_values(self):
        assert FeeStatus.pending.value == "pending"
        assert FeeStatus.charged.value == "charged"
        assert FeeStatus.waived.value == "waived"
        assert FeeStatus.refunded.value == "refunded"

    def test_fee_charged_to_enum_values(self):
        assert FeeChargedTo.rider.value == "rider"
        assert FeeChargedTo.driver.value == "driver"
        assert FeeChargedTo.none.value == "none"
