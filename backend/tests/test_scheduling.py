"""Unit tests for the scheduled rides service logic."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.ride import RideStatus
from app.services.cancellation import evaluate_cancellation
from app.services.scheduling import (
    OVERLAP_WINDOW_MINUTES,
    ScheduleValidation,
    check_overlap,
    is_ready_for_dispatch,
    validate_schedule_time,
)


NOW = datetime(2026, 4, 12, 14, 0, 0, tzinfo=timezone.utc)


class TestValidateScheduleTime:
    def test_valid_schedule_in_2_hours(self):
        scheduled = NOW + timedelta(hours=2)
        result = validate_schedule_time(scheduled, now=NOW)
        assert result.valid is True

    def test_too_soon_rejected(self):
        scheduled = NOW + timedelta(minutes=10)  # < 30 min minimum
        result = validate_schedule_time(scheduled, now=NOW)
        assert result.valid is False
        assert "30 minutes" in result.reason

    def test_exactly_at_minimum_boundary(self):
        scheduled = NOW + timedelta(minutes=30)
        result = validate_schedule_time(scheduled, now=NOW)
        assert result.valid is True

    def test_too_far_in_future_rejected(self):
        scheduled = NOW + timedelta(hours=169)  # > 168 hours (7 days)
        result = validate_schedule_time(scheduled, now=NOW)
        assert result.valid is False
        assert "168 hours" in result.reason

    def test_exactly_at_maximum_boundary(self):
        scheduled = NOW + timedelta(hours=168)
        result = validate_schedule_time(scheduled, now=NOW)
        assert result.valid is True

    def test_past_time_rejected(self):
        scheduled = NOW - timedelta(hours=1)
        result = validate_schedule_time(scheduled, now=NOW)
        assert result.valid is False

    def test_naive_datetime_rejected(self):
        naive = datetime(2026, 4, 13, 14, 0, 0)  # no tzinfo
        result = validate_schedule_time(naive, now=NOW)
        assert result.valid is False
        assert "timezone" in result.reason.lower()

    def test_schedule_validation_dataclass(self):
        v = ScheduleValidation(valid=True, reason="OK")
        assert v.valid is True
        assert v.reason == "OK"


class TestCheckOverlap:
    def test_no_existing_rides(self):
        scheduled = NOW + timedelta(hours=2)
        result = check_overlap(scheduled, [])
        assert result.valid is True

    def test_overlapping_ride_rejected(self):
        existing = NOW + timedelta(hours=2)
        scheduled = existing + timedelta(minutes=10)  # within 30 min window
        result = check_overlap(scheduled, [existing])
        assert result.valid is False
        assert str(OVERLAP_WINDOW_MINUTES) in result.reason

    def test_non_overlapping_ride_allowed(self):
        existing = NOW + timedelta(hours=2)
        scheduled = existing + timedelta(minutes=45)  # beyond 30 min window
        result = check_overlap(scheduled, [existing])
        assert result.valid is True

    def test_exactly_at_overlap_boundary(self):
        existing = NOW + timedelta(hours=2)
        scheduled = existing + timedelta(minutes=OVERLAP_WINDOW_MINUTES)
        result = check_overlap(scheduled, [existing])
        assert result.valid is True

    def test_multiple_existing_rides(self):
        times = [
            NOW + timedelta(hours=2),
            NOW + timedelta(hours=5),
            NOW + timedelta(hours=8),
        ]
        # Schedule between existing rides — no overlap
        scheduled = NOW + timedelta(hours=3, minutes=30)
        result = check_overlap(scheduled, times)
        assert result.valid is True

    def test_overlaps_with_second_ride(self):
        times = [
            NOW + timedelta(hours=2),
            NOW + timedelta(hours=5),
        ]
        scheduled = NOW + timedelta(hours=5, minutes=10)
        result = check_overlap(scheduled, times)
        assert result.valid is False


class TestIsReadyForDispatch:
    def test_not_ready_well_before(self):
        scheduled = NOW + timedelta(hours=2)
        assert is_ready_for_dispatch(scheduled, now=NOW) is False

    def test_ready_within_dispatch_window(self):
        scheduled = NOW + timedelta(minutes=10)  # within 15 min dispatch window
        assert is_ready_for_dispatch(scheduled, now=NOW) is True

    def test_ready_at_exact_dispatch_time(self):
        scheduled = NOW + timedelta(minutes=15)
        assert is_ready_for_dispatch(scheduled, now=NOW) is True

    def test_ready_when_past_scheduled_time(self):
        scheduled = NOW - timedelta(minutes=5)
        assert is_ready_for_dispatch(scheduled, now=NOW) is True


class TestCancellationWithScheduledStatus:
    def test_scheduled_ride_free_cancel_by_rider(self):
        result = evaluate_cancellation(
            ride_status=RideStatus.SCHEDULED,
            cancelled_by="rider",
            estimated_fare=25.0,
            matched_at=None,
            now=NOW,
        )
        assert result.allowed is True
        assert result.fee == 0.0
        assert "scheduled" in result.reason.lower()

    def test_scheduled_ride_free_cancel_by_driver(self):
        result = evaluate_cancellation(
            ride_status=RideStatus.SCHEDULED,
            cancelled_by="driver",
            estimated_fare=25.0,
            matched_at=None,
            now=NOW,
        )
        assert result.allowed is True
        assert result.fee == 0.0
