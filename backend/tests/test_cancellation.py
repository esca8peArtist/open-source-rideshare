"""Unit tests for the ride cancellation policy engine."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.ride import RideStatus
from app.services.cancellation import (
    ARRIVED_CANCEL_FEE,
    EN_ROUTE_CANCEL_FEE,
    FREE_CANCEL_GRACE_SECONDS,
    MAX_CANCEL_FEE_PERCENT,
    CancellationResult,
    evaluate_cancellation,
)


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
    """Tests for rider cancellation while dispatch is actively retrying."""

    def test_cancel_during_first_retry(self):
        """Rider can cancel for free during the first retry attempt."""
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
        """Rider can cancel for free at any retry attempt."""
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
        """Before any retry (count=0), the reason is the generic pre-match message."""
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
        """Driver-initiated cancel during retry is also free (hits REQUESTED branch first)."""
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
        """dispatch_retry_count is irrelevant once ride is MATCHED (different branch)."""
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
        """For a very cheap ride, the fee should be capped at MAX_CANCEL_FEE_PERCENT of fare."""
        matched = NOW - timedelta(minutes=10)
        result = evaluate_cancellation(
            ride_status=RideStatus.ARRIVED,
            cancelled_by="rider",
            estimated_fare=2.00,  # $2 ride — 50% cap = $1.00
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
