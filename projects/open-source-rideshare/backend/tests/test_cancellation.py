"""Tests for the ride cancellation policy and fee system.

Part 1 — Legacy stateless engine (evaluate_cancellation):
  Tests for the original pure-function evaluate_cancellation() which is used
  by the dispatch layer. Kept intact.

Part 2 — DB-backed policy & fee system (new):
  Service layer (unit tests with mocked DB):
    1.  get_active_policy — returns DB policy when one exists
    2.  get_active_policy — returns default policy when none in DB
    3.  calculate_rider_fee — returns 0 when within grace period
    4.  calculate_rider_fee — returns flat fee when grace period expired
    5.  calculate_rider_fee — adds percent of fare when rider_fee_percent > 0
    6.  calculate_rider_fee — grace_period_expired=False when within window
    7.  calculate_rider_fee — grace_period_expired=True when expired
    8.  calculate_rider_fee — exactly at grace boundary is still free
    9.  calculate_rider_fee — zero flat + zero percent still yields 0
    10. calculate_driver_fee — returns 0 when under daily free limit
    11. calculate_driver_fee — returns 0 at exactly the free limit
    12. calculate_driver_fee — returns penalty when over daily free limit
    13. calculate_driver_fee — penalty rounds to 2 decimal places
    14. record_cancellation — raises 404 when ride not found
    15. record_cancellation — raises 409 when record already exists
    16. record_cancellation — creates record with no fee for rider within grace
    17. record_cancellation — creates record with fee for rider after grace
    18. record_cancellation — creates record with no fee for driver under limit
    19. record_cancellation — creates record with penalty for driver over limit
    20. record_cancellation — admin cancellation has no fee
    21. record_cancellation — system cancellation has no fee
    22. record_cancellation — fee_status is waived when fee=0
    23. record_cancellation — fee_status is pending when fee>0
    24. record_cancellation — fee_charged_to=rider when rider over grace
    25. record_cancellation — fee_charged_to=none when rider within grace
    26. record_cancellation — fee_charged_to=driver when driver over limit
    27. waive_fee — raises 404 when record not found
    28. waive_fee — raises 409 when fee already waived
    29. waive_fee — raises 409 when fee already refunded
    30. waive_fee — sets fee_status=waived, records admin and reason
    31. admin_get_all — returns all records when no filter
    32. admin_get_all — applies fee_status_filter
    33. admin_get_summary — returns correct structure with expected keys

  API layer (integration-style tests against test DB):
    34. POST /rides/{id}/cancel — 200 for rider within grace (no fee)
    35. POST /rides/{id}/cancel — 200 for rider after grace (fee applied)
    36. POST /rides/{id}/cancel — 401/403 when unauthenticated
    37. POST /rides/{id}/cancel — 403 when rider is not owner of ride
    38. POST /rides/{id}/cancel — 404 when ride not found
    39. POST /rides/{id}/cancel — 409 when ride already cancelled
    40. POST /rides/{id}/cancel — 409 when ride completed
    41. POST /rides/{id}/cancel — 409 when called twice (ride is already CANCELLED)
    42. GET  /riders/me/cancellations — 200 with rider's records
    43. GET  /riders/me/cancellations — 401/403 when unauthenticated
    44. GET  /riders/me/cancellations — does not return other riders' records
    45. POST /drivers/me/rides/{id}/cancel — 200 for driver under limit
    46. POST /drivers/me/rides/{id}/cancel — 403 when driver is not assigned
    47. POST /drivers/me/rides/{id}/cancel — 404 when ride not found
    48. POST /drivers/me/rides/{id}/cancel — 409 when ride already cancelled
    49. GET  /drivers/me/cancellations — 200 with driver's records
    50. GET  /drivers/me/cancellations — 403 when rider tries
    51. GET  /admin/cancellation-policy — 200 with active policy
    52. GET  /admin/cancellation-policy — 403 for non-admin
    53. POST /admin/cancellation-policy — 201 creates new policy
    54. POST /admin/cancellation-policy — 201 deactivates previous policy
    55. POST /admin/cancellation-policy — 422 with invalid rider_fee_percent > 1
    56. POST /admin/cancellation-policy — 422 with negative grace period
    57. GET  /admin/cancellations — 200 returns all records
    58. GET  /admin/cancellations — 403 for non-admin
    59. GET  /admin/cancellations?fee_status=pending — filtered results
    60. GET  /admin/cancellations?fee_status=waived — filtered results
    61. POST /admin/cancellations/{id}/waive — 200 waives the fee
    62. POST /admin/cancellations/{id}/waive — 404 when record not found
    63. POST /admin/cancellations/{id}/waive — 409 when already waived
    64. GET  /admin/cancellations/summary — 200 with aggregate stats
    65. GET  /admin/cancellations/summary — 403 for non-admin
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.cancellation import (
    CancelledBy,
    CancellationPolicy,
    CancellationRecord,
    FeeChargedTo,
    FeeStatus,
)
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.services.auth import create_access_token, hash_password
from app.services.cancellation import (
    ARRIVED_CANCEL_FEE,
    CancellationError,
    CancellationResult,
    EN_ROUTE_CANCEL_FEE,
    FREE_CANCEL_GRACE_SECONDS,
    MAX_CANCEL_FEE_PERCENT,
    admin_get_all,
    admin_get_summary,
    calculate_driver_fee,
    calculate_rider_fee,
    evaluate_cancellation,
    get_active_policy,
    record_cancellation,
    waive_fee,
)


# ===========================================================================
# PART 1 — Legacy stateless engine
# ===========================================================================

NOW = datetime(2026, 4, 12, 14, 0, 0, tzinfo=timezone.utc)


class TestPreMatchCancellation:
    def test_requested_ride_free_cancel(self):
        result = evaluate_cancellation(
            ride_status=RideStatus.REQUESTED,
            cancelled_by="rider",
            estimated_fare=20.0,
            matched_at=None,
            now=NOW,
        )
        assert result.allowed is True
        assert result.fee == 0.0

    def test_requested_ride_driver_cancel(self):
        result = evaluate_cancellation(
            ride_status=RideStatus.REQUESTED,
            cancelled_by="driver",
            estimated_fare=20.0,
            matched_at=None,
            now=NOW,
        )
        assert result.allowed is True
        assert result.fee == 0.0


class TestGracePeriod:
    def test_within_grace_period_free(self):
        matched = NOW - timedelta(seconds=FREE_CANCEL_GRACE_SECONDS - 10)
        result = evaluate_cancellation(
            ride_status=RideStatus.MATCHED,
            cancelled_by="rider",
            estimated_fare=20.0,
            matched_at=matched,
            now=NOW,
        )
        assert result.allowed is True
        assert result.fee == 0.0
        assert "grace period" in result.reason.lower()

    def test_exactly_at_grace_boundary_free(self):
        matched = NOW - timedelta(seconds=FREE_CANCEL_GRACE_SECONDS)
        result = evaluate_cancellation(
            ride_status=RideStatus.MATCHED,
            cancelled_by="rider",
            estimated_fare=20.0,
            matched_at=matched,
            now=NOW,
        )
        assert result.allowed is True
        assert result.fee == 0.0

    def test_past_grace_period_has_fee(self):
        matched = NOW - timedelta(seconds=FREE_CANCEL_GRACE_SECONDS + 1)
        result = evaluate_cancellation(
            ride_status=RideStatus.MATCHED,
            cancelled_by="rider",
            estimated_fare=20.0,
            matched_at=matched,
            now=NOW,
        )
        assert result.allowed is True
        assert result.fee == EN_ROUTE_CANCEL_FEE


class TestStatusBasedFees:
    def test_matched_fee(self):
        matched = NOW - timedelta(minutes=5)
        result = evaluate_cancellation(
            ride_status=RideStatus.MATCHED,
            cancelled_by="rider",
            estimated_fare=20.0,
            matched_at=matched,
            now=NOW,
        )
        assert result.fee == EN_ROUTE_CANCEL_FEE

    def test_en_route_fee(self):
        matched = NOW - timedelta(minutes=5)
        result = evaluate_cancellation(
            ride_status=RideStatus.DRIVER_EN_ROUTE,
            cancelled_by="rider",
            estimated_fare=20.0,
            matched_at=matched,
            now=NOW,
        )
        assert result.fee == EN_ROUTE_CANCEL_FEE

    def test_arrived_fee(self):
        matched = NOW - timedelta(minutes=10)
        result = evaluate_cancellation(
            ride_status=RideStatus.ARRIVED,
            cancelled_by="rider",
            estimated_fare=20.0,
            matched_at=matched,
            now=NOW,
        )
        assert result.fee == ARRIVED_CANCEL_FEE


class TestCancellationDuringRetry:
    def test_cancel_during_first_retry(self):
        result = evaluate_cancellation(
            ride_status=RideStatus.REQUESTED,
            cancelled_by="rider",
            estimated_fare=20.0,
            matched_at=None,
            now=NOW,
            dispatch_retry_count=1,
        )
        assert result.allowed is True
        assert result.fee == 0.0
        assert "dispatch retry" in result.reason.lower()
        assert "attempt 1" in result.reason

    def test_cancel_during_later_retry(self):
        result = evaluate_cancellation(
            ride_status=RideStatus.REQUESTED,
            cancelled_by="rider",
            estimated_fare=20.0,
            matched_at=None,
            now=NOW,
            dispatch_retry_count=4,
        )
        assert result.allowed is True
        assert result.fee == 0.0
        assert "attempt 4" in result.reason

    def test_cancel_pre_retry_still_generic(self):
        result = evaluate_cancellation(
            ride_status=RideStatus.REQUESTED,
            cancelled_by="rider",
            estimated_fare=20.0,
            matched_at=None,
            now=NOW,
            dispatch_retry_count=0,
        )
        assert result.allowed is True
        assert result.fee == 0.0
        assert "no driver matched" in result.reason.lower()

    def test_driver_cancel_during_retry(self):
        result = evaluate_cancellation(
            ride_status=RideStatus.REQUESTED,
            cancelled_by="driver",
            estimated_fare=20.0,
            matched_at=None,
            now=NOW,
            dispatch_retry_count=3,
        )
        assert result.allowed is True
        assert result.fee == 0.0

    def test_retry_count_ignored_for_matched_status(self):
        matched = NOW - timedelta(minutes=5)
        result = evaluate_cancellation(
            ride_status=RideStatus.MATCHED,
            cancelled_by="rider",
            estimated_fare=20.0,
            matched_at=matched,
            now=NOW,
            dispatch_retry_count=3,
        )
        assert result.allowed is True
        assert result.fee == EN_ROUTE_CANCEL_FEE


class TestDriverCancellation:
    def test_driver_cancel_always_free(self):
        matched = NOW - timedelta(minutes=10)
        for status in [RideStatus.MATCHED, RideStatus.DRIVER_EN_ROUTE, RideStatus.ARRIVED]:
            result = evaluate_cancellation(
                ride_status=status,
                cancelled_by="driver",
                estimated_fare=20.0,
                matched_at=matched,
                now=NOW,
            )
            assert result.allowed is True
            assert result.fee == 0.0


class TestNotAllowed:
    def test_completed_not_cancellable(self):
        result = evaluate_cancellation(
            ride_status=RideStatus.COMPLETED,
            cancelled_by="rider",
            estimated_fare=20.0,
            matched_at=None,
            now=NOW,
        )
        assert result.allowed is False

    def test_already_cancelled_not_cancellable(self):
        result = evaluate_cancellation(
            ride_status=RideStatus.CANCELLED,
            cancelled_by="rider",
            estimated_fare=20.0,
            matched_at=None,
            now=NOW,
        )
        assert result.allowed is False

    def test_in_progress_not_cancellable(self):
        result = evaluate_cancellation(
            ride_status=RideStatus.IN_PROGRESS,
            cancelled_by="rider",
            estimated_fare=20.0,
            matched_at=None,
            now=NOW,
        )
        assert result.allowed is False


class TestFeeCapping:
    def test_fee_capped_at_max_percent(self):
        matched = NOW - timedelta(minutes=10)
        result = evaluate_cancellation(
            ride_status=RideStatus.ARRIVED,
            cancelled_by="rider",
            estimated_fare=2.00,
            matched_at=matched,
            now=NOW,
        )
        max_fee = 2.00 * (MAX_CANCEL_FEE_PERCENT / 100.0)
        assert result.fee == max_fee
        assert result.fee < ARRIVED_CANCEL_FEE

    def test_fee_not_capped_for_normal_fare(self):
        matched = NOW - timedelta(minutes=10)
        result = evaluate_cancellation(
            ride_status=RideStatus.ARRIVED,
            cancelled_by="rider",
            estimated_fare=50.0,
            matched_at=matched,
            now=NOW,
        )
        assert result.fee == ARRIVED_CANCEL_FEE


class TestCancellationResultDataclass:
    def test_fields(self):
        r = CancellationResult(allowed=True, fee=3.0, reason="test")
        assert r.allowed is True
        assert r.fee == 3.0
        assert r.reason == "test"

    def test_frozen(self):
        r = CancellationResult(allowed=True, fee=0.0, reason="test")
        with pytest.raises(AttributeError):
            r.fee = 5.0


# ===========================================================================
# PART 2 — DB-backed policy & fee system
# ===========================================================================

_NOW = datetime.now(timezone.utc)
_BOOKING_TIME = _NOW - timedelta(seconds=300)   # booked 5 minutes ago
_RECENT_BOOKING = _NOW - timedelta(seconds=30)  # booked 30 seconds ago


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_policy(
    grace: int = 120,
    flat: float = 5.00,
    pct: float = 0.0,
    free_cancels: int = 3,
    penalty: float = 2.00,
    is_active: bool = True,
) -> CancellationPolicy:
    p = CancellationPolicy(
        rider_grace_period_seconds=grace,
        rider_fee_flat=Decimal(str(flat)),
        rider_fee_percent=Decimal(str(pct)),
        driver_free_cancels_per_day=free_cancels,
        driver_cancel_penalty=Decimal(str(penalty)),
        is_active=is_active,
    )
    p.id = 1
    return p


def _make_record(
    record_id: int = 1,
    ride_id: int = 10,
    cancelled_by: CancelledBy = CancelledBy.rider,
    fee: float = 5.00,
    fee_status: FeeStatus = FeeStatus.pending,
    fee_charged_to: FeeChargedTo = FeeChargedTo.rider,
) -> MagicMock:
    r = MagicMock(spec=CancellationRecord)
    r.id = record_id
    r.ride_id = ride_id
    r.cancelled_by = cancelled_by
    r.cancellation_reason = None
    r.cancelled_at = _NOW
    r.grace_period_expired = False
    r.fee_applied = Decimal(str(fee))
    r.fee_charged_to = fee_charged_to
    r.fee_status = fee_status
    r.waived_by_admin_id = None
    r.waive_reason = None
    r.created_at = _NOW
    return r


def _make_ride_mock(
    ride_id: int = 10,
    rider_id: int = 1,
    driver_id: int = 2,
    status: RideStatus = RideStatus.MATCHED,
    estimated_fare: float = 20.00,
    requested_at: datetime | None = None,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.estimated_fare = estimated_fare
    ride.requested_at = requested_at or _BOOKING_TIME
    ride.cancellation_reason = None
    return ride


def _single_db(obj) -> AsyncMock:
    """DB mock returning obj from scalar_one_or_none."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    result.scalar.return_value = 0
    scalars = MagicMock()
    scalars.all.return_value = [obj] if obj is not None else []
    result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _multi_db(*objects) -> AsyncMock:
    """DB mock where successive execute() calls return each object in order."""
    db = AsyncMock()
    results = []
    for obj in objects:
        r = MagicMock()
        r.scalar_one_or_none.return_value = obj
        r.scalar.return_value = obj if isinstance(obj, int) else 0
        r.one.return_value = MagicMock(total=0, total_fees=Decimal("0"))
        scalars = MagicMock()
        scalars.all.return_value = [obj] if obj is not None else []
        r.scalars.return_value = scalars
        results.append(r)
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _scalars_db(items: list) -> AsyncMock:
    """DB mock where execute returns scalars().all() = items."""
    db = AsyncMock()
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    result.scalars.return_value = scalars
    result.scalar_one_or_none.return_value = items[0] if items else None
    result.scalar.return_value = 0
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Service tests: get_active_policy
# ---------------------------------------------------------------------------


class TestGetActivePolicy:
    @pytest.mark.asyncio
    async def test_returns_db_policy_when_exists(self):
        policy = _make_policy(grace=180)
        db = _single_db(policy)
        result = await get_active_policy(db)
        assert result is policy

    @pytest.mark.asyncio
    async def test_returns_default_when_none_in_db(self):
        db = _single_db(None)
        result = await get_active_policy(db)
        assert result.rider_grace_period_seconds == 120
        assert result.is_active is True


# ---------------------------------------------------------------------------
# Service tests: calculate_rider_fee
# ---------------------------------------------------------------------------


class TestCalculateRiderFee:
    def test_zero_fee_within_grace(self):
        policy = _make_policy(grace=120, flat=5.00)
        booking = _NOW - timedelta(seconds=60)
        fee, expired = calculate_rider_fee(policy, 20.0, booking, _NOW)
        assert fee == Decimal("0.00")
        assert expired is False

    def test_flat_fee_after_grace(self):
        policy = _make_policy(grace=120, flat=5.00, pct=0.0)
        booking = _NOW - timedelta(seconds=200)
        fee, expired = calculate_rider_fee(policy, 20.0, booking, _NOW)
        assert fee == Decimal("5.00")
        assert expired is True

    def test_flat_plus_percent_after_grace(self):
        policy = _make_policy(grace=120, flat=2.00, pct=0.10)
        booking = _NOW - timedelta(seconds=200)
        # flat=2.00 + 20.00 * 0.10 = 2.00 + 2.00 = 4.00
        fee, expired = calculate_rider_fee(policy, 20.0, booking, _NOW)
        assert fee == Decimal("4.00")
        assert expired is True

    def test_grace_expired_false_within_window(self):
        policy = _make_policy(grace=120)
        booking = _NOW - timedelta(seconds=30)
        _, expired = calculate_rider_fee(policy, 20.0, booking, _NOW)
        assert expired is False

    def test_grace_expired_true_after_window(self):
        policy = _make_policy(grace=120)
        booking = _NOW - timedelta(seconds=150)
        _, expired = calculate_rider_fee(policy, 20.0, booking, _NOW)
        assert expired is True

    def test_exactly_at_boundary_is_free(self):
        # elapsed == grace → NOT expired (uses strict > comparison)
        policy = _make_policy(grace=120)
        booking = _NOW - timedelta(seconds=120)
        fee, expired = calculate_rider_fee(policy, 20.0, booking, _NOW)
        assert fee == Decimal("0.00")
        assert expired is False

    def test_zero_flat_and_zero_percent_yields_zero(self):
        policy = _make_policy(grace=0, flat=0.0, pct=0.0)
        booking = _NOW - timedelta(seconds=5)
        fee, expired = calculate_rider_fee(policy, 20.0, booking, _NOW)
        assert fee == Decimal("0.00")
        assert expired is True


# ---------------------------------------------------------------------------
# Service tests: calculate_driver_fee
# ---------------------------------------------------------------------------


class TestCalculateDriverFee:
    def test_zero_fee_under_daily_limit(self):
        policy = _make_policy(free_cancels=3, penalty=2.00)
        # 1 existing + 1 this = 2, under limit of 3
        fee = calculate_driver_fee(policy, driver_cancel_count_today=1)
        assert fee == Decimal("0.00")

    def test_zero_fee_at_exactly_free_limit(self):
        policy = _make_policy(free_cancels=3, penalty=2.00)
        # 2 existing + 1 this = 3, equals limit → still free
        fee = calculate_driver_fee(policy, driver_cancel_count_today=2)
        assert fee == Decimal("0.00")

    def test_penalty_over_daily_limit(self):
        policy = _make_policy(free_cancels=3, penalty=2.00)
        # 3 existing + 1 this = 4 > 3 → penalty
        fee = calculate_driver_fee(policy, driver_cancel_count_today=3)
        assert fee == Decimal("2.00")

    def test_penalty_rounds_to_two_decimals(self):
        policy = _make_policy(free_cancels=1, penalty=2.555)
        fee = calculate_driver_fee(policy, driver_cancel_count_today=1)
        assert fee == Decimal("2.56")


# ---------------------------------------------------------------------------
# Service tests: record_cancellation
# ---------------------------------------------------------------------------


class TestRecordCancellation:
    @pytest.mark.asyncio
    async def test_raises_404_when_ride_not_found(self):
        db = _multi_db(None)
        with pytest.raises(CancellationError) as exc_info:
            await record_cancellation(
                db, ride_id=999, cancelled_by=CancelledBy.rider,
                reason=None, estimated_fare=20.0, booking_time=_BOOKING_TIME,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_raises_409_when_record_already_exists(self):
        ride = _make_ride_mock()
        existing_record = _make_record()
        db = _multi_db(ride, existing_record)
        with pytest.raises(CancellationError) as exc_info:
            await record_cancellation(
                db, ride_id=10, cancelled_by=CancelledBy.rider,
                reason=None, estimated_fare=20.0, booking_time=_BOOKING_TIME,
            )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_rider_no_fee_within_grace(self):
        ride = _make_ride_mock(requested_at=_RECENT_BOOKING)
        policy = _make_policy(grace=120)
        db = _multi_db(ride, None, policy)
        await record_cancellation(
            db, ride_id=10, cancelled_by=CancelledBy.rider,
            reason=None, estimated_fare=20.0, booking_time=_RECENT_BOOKING,
        )
        added = db.add.call_args[0][0]
        assert isinstance(added, CancellationRecord)
        assert added.fee_applied == Decimal("0.00")
        assert added.grace_period_expired is False
        assert added.fee_charged_to == FeeChargedTo.none
        assert added.fee_status == FeeStatus.waived

    @pytest.mark.asyncio
    async def test_rider_fee_after_grace(self):
        ride = _make_ride_mock(requested_at=_BOOKING_TIME)
        policy = _make_policy(grace=120, flat=5.00)
        db = _multi_db(ride, None, policy)
        await record_cancellation(
            db, ride_id=10, cancelled_by=CancelledBy.rider,
            reason=None, estimated_fare=20.0, booking_time=_BOOKING_TIME,
        )
        added = db.add.call_args[0][0]
        assert added.fee_applied == Decimal("5.00")
        assert added.grace_period_expired is True
        assert added.fee_charged_to == FeeChargedTo.rider
        assert added.fee_status == FeeStatus.pending

    @pytest.mark.asyncio
    async def test_driver_no_fee_under_limit(self):
        ride = _make_ride_mock(driver_id=2)
        policy = _make_policy(free_cancels=3, penalty=2.00)
        db = _multi_db(ride, None, policy, 0)
        await record_cancellation(
            db, ride_id=10, cancelled_by=CancelledBy.driver,
            reason=None, estimated_fare=20.0, booking_time=_BOOKING_TIME,
            driver_id=2,
        )
        added = db.add.call_args[0][0]
        assert added.fee_applied == Decimal("0.00")
        assert added.fee_charged_to == FeeChargedTo.none

    @pytest.mark.asyncio
    async def test_driver_penalty_over_limit(self):
        ride = _make_ride_mock(driver_id=2)
        policy = _make_policy(free_cancels=3, penalty=2.00)
        db = _multi_db(ride, None, policy, 3)
        await record_cancellation(
            db, ride_id=10, cancelled_by=CancelledBy.driver,
            reason=None, estimated_fare=20.0, booking_time=_BOOKING_TIME,
            driver_id=2,
        )
        added = db.add.call_args[0][0]
        assert added.fee_applied == Decimal("2.00")
        assert added.fee_charged_to == FeeChargedTo.driver
        assert added.fee_status == FeeStatus.pending

    @pytest.mark.asyncio
    async def test_admin_cancellation_no_fee(self):
        ride = _make_ride_mock()
        policy = _make_policy()
        db = _multi_db(ride, None, policy)
        await record_cancellation(
            db, ride_id=10, cancelled_by=CancelledBy.admin,
            reason="Admin override", estimated_fare=20.0, booking_time=_BOOKING_TIME,
        )
        added = db.add.call_args[0][0]
        assert added.fee_applied == Decimal("0.00")
        assert added.fee_charged_to == FeeChargedTo.none

    @pytest.mark.asyncio
    async def test_system_cancellation_no_fee(self):
        ride = _make_ride_mock()
        policy = _make_policy()
        db = _multi_db(ride, None, policy)
        await record_cancellation(
            db, ride_id=10, cancelled_by=CancelledBy.system,
            reason=None, estimated_fare=20.0, booking_time=_BOOKING_TIME,
        )
        added = db.add.call_args[0][0]
        assert added.fee_applied == Decimal("0.00")
        assert added.fee_status == FeeStatus.waived

    @pytest.mark.asyncio
    async def test_fee_status_waived_when_fee_zero(self):
        ride = _make_ride_mock(requested_at=_RECENT_BOOKING)
        policy = _make_policy(grace=120)
        db = _multi_db(ride, None, policy)
        await record_cancellation(
            db, ride_id=10, cancelled_by=CancelledBy.rider,
            reason=None, estimated_fare=20.0, booking_time=_RECENT_BOOKING,
        )
        added = db.add.call_args[0][0]
        assert added.fee_status == FeeStatus.waived

    @pytest.mark.asyncio
    async def test_fee_status_pending_when_fee_positive(self):
        ride = _make_ride_mock(requested_at=_BOOKING_TIME)
        policy = _make_policy(grace=120, flat=5.00)
        db = _multi_db(ride, None, policy)
        await record_cancellation(
            db, ride_id=10, cancelled_by=CancelledBy.rider,
            reason=None, estimated_fare=20.0, booking_time=_BOOKING_TIME,
        )
        added = db.add.call_args[0][0]
        assert added.fee_status == FeeStatus.pending

    @pytest.mark.asyncio
    async def test_fee_charged_to_none_within_grace(self):
        ride = _make_ride_mock(requested_at=_RECENT_BOOKING)
        policy = _make_policy(grace=120)
        db = _multi_db(ride, None, policy)
        await record_cancellation(
            db, ride_id=10, cancelled_by=CancelledBy.rider,
            reason=None, estimated_fare=20.0, booking_time=_RECENT_BOOKING,
        )
        added = db.add.call_args[0][0]
        assert added.fee_charged_to == FeeChargedTo.none

    @pytest.mark.asyncio
    async def test_fee_charged_to_rider_after_grace(self):
        ride = _make_ride_mock(requested_at=_BOOKING_TIME)
        policy = _make_policy(grace=120, flat=5.00)
        db = _multi_db(ride, None, policy)
        await record_cancellation(
            db, ride_id=10, cancelled_by=CancelledBy.rider,
            reason=None, estimated_fare=20.0, booking_time=_BOOKING_TIME,
        )
        added = db.add.call_args[0][0]
        assert added.fee_charged_to == FeeChargedTo.rider


# ---------------------------------------------------------------------------
# Service tests: waive_fee
# ---------------------------------------------------------------------------


class TestWaiveFee:
    @pytest.mark.asyncio
    async def test_raises_404_when_record_not_found(self):
        db = _single_db(None)
        with pytest.raises(CancellationError) as exc_info:
            await waive_fee(db, cancellation_record_id=999, admin_id=1, reason="test")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_raises_409_when_already_waived(self):
        record = _make_record(fee_status=FeeStatus.waived)
        db = _single_db(record)
        with pytest.raises(CancellationError) as exc_info:
            await waive_fee(db, cancellation_record_id=1, admin_id=1, reason="test")
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_raises_409_when_already_refunded(self):
        record = _make_record(fee_status=FeeStatus.refunded)
        db = _single_db(record)
        with pytest.raises(CancellationError) as exc_info:
            await waive_fee(db, cancellation_record_id=1, admin_id=1, reason="test")
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_waives_pending_fee(self):
        record = _make_record(fee_status=FeeStatus.pending)
        db = _single_db(record)
        result = await waive_fee(db, cancellation_record_id=1, admin_id=99, reason="Goodwill")
        assert result.fee_status == FeeStatus.waived
        assert result.waived_by_admin_id == 99
        assert result.waive_reason == "Goodwill"
        db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# Service tests: admin_get_all / admin_get_summary
# ---------------------------------------------------------------------------


class TestAdminGetAll:
    @pytest.mark.asyncio
    async def test_returns_list_without_filter(self):
        records = [_make_record(1), _make_record(2)]
        db = _scalars_db(records)
        result = await admin_get_all(db, skip=0, limit=50, fee_status_filter=None)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_applies_fee_status_filter(self):
        records = [_make_record(1, fee_status=FeeStatus.pending)]
        db = _scalars_db(records)
        result = await admin_get_all(db, skip=0, limit=50, fee_status_filter=FeeStatus.pending)
        assert isinstance(result, list)


class TestAdminGetSummary:
    @pytest.mark.asyncio
    async def test_returns_correct_structure(self):
        db = AsyncMock()
        agg_result = MagicMock()
        agg_row = MagicMock()
        agg_row.total = 10
        agg_row.total_fees = Decimal("50.00")
        agg_result.one.return_value = agg_row

        scalar_result = MagicMock()
        scalar_result.scalar.return_value = Decimal("0")

        db.execute = AsyncMock(side_effect=[agg_result] + [scalar_result] * 8)

        summary = await admin_get_summary(db)
        assert "total_cancellations" in summary
        assert "total_fees_assessed_usd" in summary
        assert "cancellations_by_rider" in summary
        assert "cancellations_by_driver" in summary
        assert "cancellations_by_admin" in summary
        assert "cancellations_by_system" in summary
        assert summary["total_cancellations"] == 10


# ===========================================================================
# PART 2 — API endpoint tests (integration-style, test DB)
# ===========================================================================

_PICKUP = "SRID=4326;POINT(-73.9857 40.7484)"
_DROPOFF = "SRID=4326;POINT(-74.0060 40.7128)"


def _insert_ride(
    db,
    rider_id: int,
    driver_id: int,
    status: RideStatus = RideStatus.MATCHED,
    estimated_fare: float = 20.00,
    requested_at: datetime | None = None,
) -> Ride:
    ride = Ride(
        rider_id=rider_id,
        driver_id=driver_id,
        status=status,
        pickup_location=_PICKUP,
        dropoff_location=_DROPOFF,
        pickup_address="123 Start St",
        dropoff_address="456 End Ave",
        estimated_fare=estimated_fare,
        requested_at=requested_at or (datetime.now(timezone.utc) - timedelta(seconds=300)),
    )
    db.add(ride)
    return ride


def _insert_cancellation_record(
    db,
    ride_id: int,
    cancelled_by: CancelledBy = CancelledBy.rider,
    fee: float = 5.00,
    fee_status: FeeStatus = FeeStatus.pending,
) -> CancellationRecord:
    r = CancellationRecord(
        ride_id=ride_id,
        cancelled_by=cancelled_by,
        cancellation_reason=None,
        cancelled_at=datetime.now(timezone.utc),
        grace_period_expired=True,
        fee_applied=Decimal(str(fee)),
        fee_charged_to=(
            FeeChargedTo.rider if cancelled_by == CancelledBy.rider
            else FeeChargedTo.driver if cancelled_by == CancelledBy.driver
            else FeeChargedTo.none
        ),
        fee_status=fee_status,
    )
    db.add(r)
    return r


# ---------------------------------------------------------------------------
# API: Rider cancel
# ---------------------------------------------------------------------------


class TestRiderCancelAPI:
    @pytest.mark.asyncio
    async def test_cancel_within_grace_200_no_fee(self, client, rider, rider_token, db):
        ride = _insert_ride(
            db,
            rider_id=rider.id,
            driver_id=1,
            status=RideStatus.MATCHED,
            requested_at=datetime.now(timezone.utc) - timedelta(seconds=30),
        )
        await db.flush()
        resp = await client.post(
            f"/api/v1/rides/{ride.id}/cancel",
            json={"reason": "Changed plans"},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert float(body["fee_applied"]) == 0.0
        assert body["grace_expired"] is False

    @pytest.mark.asyncio
    async def test_cancel_after_grace_200_with_fee(self, client, rider, rider_token, db):
        ride = _insert_ride(
            db,
            rider_id=rider.id,
            driver_id=1,
            status=RideStatus.MATCHED,
            requested_at=datetime.now(timezone.utc) - timedelta(seconds=300),
        )
        await db.flush()
        resp = await client.post(
            f"/api/v1/rides/{ride.id}/cancel",
            json={"reason": "Late cancel"},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert float(body["fee_applied"]) > 0
        assert body["grace_expired"] is True

    @pytest.mark.asyncio
    async def test_cancel_unauthenticated_401_or_403(self, client, rider, db):
        ride = _insert_ride(db, rider_id=rider.id, driver_id=1)
        await db.flush()
        resp = await client.post(f"/api/v1/rides/{ride.id}/cancel", json={})
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_cancel_not_own_ride_403(self, client, rider, db):
        other = User(
            phone="+15559990001",
            name="Other",
            email="other@canceltest.com",
            password_hash=hash_password("pass"),
            role=UserRole.RIDER,
            is_active=True,
        )
        db.add(other)
        await db.flush()
        other_token = create_access_token(other.id, other.role.value)

        ride = _insert_ride(db, rider_id=rider.id, driver_id=1)
        await db.flush()

        resp = await client.post(
            f"/api/v1/rides/{ride.id}/cancel",
            json={},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_ride_404(self, client, rider_token):
        resp = await client.post(
            "/api/v1/rides/99999/cancel",
            json={},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_ride_409(self, client, rider, rider_token, db):
        ride = _insert_ride(db, rider_id=rider.id, driver_id=1, status=RideStatus.CANCELLED)
        await db.flush()
        resp = await client.post(
            f"/api/v1/rides/{ride.id}/cancel",
            json={},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_cancel_completed_ride_409(self, client, rider, rider_token, db):
        ride = _insert_ride(db, rider_id=rider.id, driver_id=1, status=RideStatus.COMPLETED)
        await db.flush()
        resp = await client.post(
            f"/api/v1/rides/{ride.id}/cancel",
            json={},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_cancel_twice_second_is_409(self, client, rider, rider_token, db):
        ride = _insert_ride(db, rider_id=rider.id, driver_id=1, status=RideStatus.MATCHED)
        await db.flush()

        resp1 = await client.post(
            f"/api/v1/rides/{ride.id}/cancel",
            json={},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp1.status_code == 200

        # Ride is now CANCELLED → second attempt returns 409
        resp2 = await client.post(
            f"/api/v1/rides/{ride.id}/cancel",
            json={},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp2.status_code == 409


# ---------------------------------------------------------------------------
# API: Rider cancellation history
# ---------------------------------------------------------------------------


class TestRiderCancellationHistoryAPI:
    @pytest.mark.asyncio
    async def test_returns_own_cancellations(self, client, rider, rider_token, db):
        ride = _insert_ride(db, rider_id=rider.id, driver_id=1, status=RideStatus.MATCHED)
        await db.flush()
        _insert_cancellation_record(db, ride_id=ride.id, cancelled_by=CancelledBy.rider)
        await db.flush()

        resp = await client.get(
            "/api/v1/riders/me/cancellations",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_unauthenticated_401_or_403(self, client):
        resp = await client.get("/api/v1/riders/me/cancellations")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_does_not_return_other_riders_records(
        self, client, rider, rider_token, driver_user, db
    ):
        other = User(
            phone="+15559990002",
            name="Other Rider",
            email="other2@canceltest.com",
            password_hash=hash_password("pass"),
            role=UserRole.RIDER,
            is_active=True,
        )
        db.add(other)
        await db.flush()

        ride = _insert_ride(
            db, rider_id=other.id, driver_id=driver_user.id, status=RideStatus.CANCELLED
        )
        await db.flush()
        _insert_cancellation_record(db, ride_id=ride.id, cancelled_by=CancelledBy.rider)
        await db.flush()

        resp = await client.get(
            "/api/v1/riders/me/cancellations",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# API: Driver cancel
# ---------------------------------------------------------------------------


class TestDriverCancelAPI:
    @pytest.mark.asyncio
    async def test_driver_cancel_under_limit_200(
        self, client, driver_user, driver_token, driver_profile, db
    ):
        ride = _insert_ride(
            db, rider_id=1, driver_id=driver_user.id, status=RideStatus.MATCHED
        )
        await db.flush()
        resp = await client.post(
            f"/api/v1/drivers/me/rides/{ride.id}/cancel",
            json={"reason": "Car trouble"},
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert float(body["fee_applied"]) == 0.0

    @pytest.mark.asyncio
    async def test_driver_cancel_not_assigned_403(
        self, client, driver_user, driver_token, driver_profile, db
    ):
        ride = _insert_ride(db, rider_id=1, driver_id=99, status=RideStatus.MATCHED)
        await db.flush()
        resp = await client.post(
            f"/api/v1/drivers/me/rides/{ride.id}/cancel",
            json={},
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_driver_cancel_nonexistent_ride_404(
        self, client, driver_token, driver_profile
    ):
        resp = await client.post(
            "/api/v1/drivers/me/rides/99999/cancel",
            json={},
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_driver_cancel_already_cancelled_409(
        self, client, driver_user, driver_token, driver_profile, db
    ):
        ride = _insert_ride(
            db, rider_id=1, driver_id=driver_user.id, status=RideStatus.CANCELLED
        )
        await db.flush()
        resp = await client.post(
            f"/api/v1/drivers/me/rides/{ride.id}/cancel",
            json={},
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# API: Driver cancellation history
# ---------------------------------------------------------------------------


class TestDriverCancellationHistoryAPI:
    @pytest.mark.asyncio
    async def test_returns_own_cancellations(
        self, client, driver_user, driver_token, driver_profile, db
    ):
        ride = _insert_ride(
            db, rider_id=1, driver_id=driver_user.id, status=RideStatus.CANCELLED
        )
        await db.flush()
        _insert_cancellation_record(db, ride_id=ride.id, cancelled_by=CancelledBy.driver)
        await db.flush()

        resp = await client.get(
            "/api/v1/drivers/me/cancellations",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_rider_cannot_access_driver_history(self, client, rider_token):
        resp = await client.get(
            "/api/v1/drivers/me/cancellations",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# API: Admin policy
# ---------------------------------------------------------------------------


class TestAdminPolicyAPI:
    @pytest.mark.asyncio
    async def test_get_active_policy_200(self, client, admin_token):
        resp = await client.get(
            "/api/v1/admin/cancellation-policy",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "rider_grace_period_seconds" in body

    @pytest.mark.asyncio
    async def test_get_policy_403_for_non_admin(self, client, rider_token):
        resp = await client.get(
            "/api/v1/admin/cancellation-policy",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_policy_201(self, client, admin_token):
        resp = await client.post(
            "/api/v1/admin/cancellation-policy",
            json={
                "rider_grace_period_seconds": 90,
                "rider_fee_flat": "3.00",
                "rider_fee_percent": "0.0500",
                "driver_free_cancels_per_day": 5,
                "driver_cancel_penalty": "1.50",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["rider_grace_period_seconds"] == 90
        assert body["is_active"] is True

    @pytest.mark.asyncio
    async def test_create_policy_deactivates_previous(self, client, admin_token):
        await client.post(
            "/api/v1/admin/cancellation-policy",
            json={
                "rider_grace_period_seconds": 60,
                "rider_fee_flat": "2.00",
                "rider_fee_percent": "0.0000",
                "driver_free_cancels_per_day": 2,
                "driver_cancel_penalty": "1.00",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        await client.post(
            "/api/v1/admin/cancellation-policy",
            json={
                "rider_grace_period_seconds": 180,
                "rider_fee_flat": "7.00",
                "rider_fee_percent": "0.0000",
                "driver_free_cancels_per_day": 4,
                "driver_cancel_penalty": "3.00",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        resp = await client.get(
            "/api/v1/admin/cancellation-policy",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.json()["rider_grace_period_seconds"] == 180

    @pytest.mark.asyncio
    async def test_create_policy_invalid_fee_percent_422(self, client, admin_token):
        resp = await client.post(
            "/api/v1/admin/cancellation-policy",
            json={
                "rider_grace_period_seconds": 120,
                "rider_fee_flat": "5.00",
                "rider_fee_percent": "1.5000",
                "driver_free_cancels_per_day": 3,
                "driver_cancel_penalty": "2.00",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_policy_negative_grace_422(self, client, admin_token):
        resp = await client.post(
            "/api/v1/admin/cancellation-policy",
            json={
                "rider_grace_period_seconds": -1,
                "rider_fee_flat": "5.00",
                "rider_fee_percent": "0.0000",
                "driver_free_cancels_per_day": 3,
                "driver_cancel_penalty": "2.00",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# API: Admin cancellation records
# ---------------------------------------------------------------------------


class TestAdminCancellationsAPI:
    @pytest.mark.asyncio
    async def test_list_all_returns_200(self, client, admin_token):
        resp = await client.get(
            "/api/v1/admin/cancellations",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_list_403_for_non_admin(self, client, rider_token):
        resp = await client.get(
            "/api/v1/admin/cancellations",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_list_filtered_by_pending(self, client, admin_token, rider, db):
        ride = _insert_ride(db, rider_id=rider.id, driver_id=1, status=RideStatus.CANCELLED)
        await db.flush()
        _insert_cancellation_record(
            db, ride_id=ride.id, cancelled_by=CancelledBy.rider, fee_status=FeeStatus.pending
        )
        await db.flush()

        resp = await client.get(
            "/api/v1/admin/cancellations?fee_status=pending",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["fee_status"] == "pending" for r in data)

    @pytest.mark.asyncio
    async def test_list_filtered_by_waived(self, client, admin_token, rider, db):
        ride = _insert_ride(db, rider_id=rider.id, driver_id=1, status=RideStatus.CANCELLED)
        await db.flush()
        _insert_cancellation_record(
            db, ride_id=ride.id, cancelled_by=CancelledBy.rider,
            fee=0.0, fee_status=FeeStatus.waived
        )
        await db.flush()

        resp = await client.get(
            "/api/v1/admin/cancellations?fee_status=waived",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["fee_status"] == "waived" for r in data)

    @pytest.mark.asyncio
    async def test_waive_fee_200(self, client, admin_token, rider, db):
        ride = _insert_ride(db, rider_id=rider.id, driver_id=1, status=RideStatus.CANCELLED)
        await db.flush()
        record = _insert_cancellation_record(
            db, ride_id=ride.id, cancelled_by=CancelledBy.rider,
            fee=5.00, fee_status=FeeStatus.pending
        )
        await db.flush()

        resp = await client.post(
            f"/api/v1/admin/cancellations/{record.id}/waive",
            json={"reason": "Customer goodwill gesture"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["fee_status"] == "waived"
        assert body["waive_reason"] == "Customer goodwill gesture"

    @pytest.mark.asyncio
    async def test_waive_fee_404_not_found(self, client, admin_token):
        resp = await client.post(
            "/api/v1/admin/cancellations/99999/waive",
            json={"reason": "test"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_waive_fee_409_already_waived(self, client, admin_token, rider, db):
        ride = _insert_ride(db, rider_id=rider.id, driver_id=1, status=RideStatus.CANCELLED)
        await db.flush()
        record = _insert_cancellation_record(
            db, ride_id=ride.id, cancelled_by=CancelledBy.rider,
            fee=0.0, fee_status=FeeStatus.waived
        )
        await db.flush()

        resp = await client.post(
            f"/api/v1/admin/cancellations/{record.id}/waive",
            json={"reason": "Already waived"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_summary_200(self, client, admin_token):
        resp = await client.get(
            "/api/v1/admin/cancellations/summary",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "total_cancellations" in body
        assert "total_fees_assessed_usd" in body
        assert "cancellations_by_rider" in body

    @pytest.mark.asyncio
    async def test_summary_403_for_non_admin(self, client, rider_token):
        resp = await client.get(
            "/api/v1/admin/cancellations/summary",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403
