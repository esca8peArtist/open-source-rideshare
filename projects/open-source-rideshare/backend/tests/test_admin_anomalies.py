"""Tests for admin trip anomaly detection schema and helpers."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.models.ride import CancellationCategory, Ride, RideStatus
from app.models.user import User
from app.schemas.admin import TripAnomalyEntry, TripAnomalyListResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)


def _make_ride(
    ride_id: int = 1,
    rider_id: int = 10,
    driver_id: int | None = 20,
    status: RideStatus = RideStatus.COMPLETED,
    estimated_fare: float = 20.0,
    actual_fare: float | None = 22.0,
    duration_min: float | None = 30.0,
    route_deviation_flagged_at: datetime | None = None,
    driver_no_show_reported_at: datetime | None = None,
    cancellation_category: CancellationCategory | None = None,
    cancelled_at: datetime | None = None,
    completed_at: datetime | None = None,
    rider_name: str = "Alice",
    driver_name: str | None = "Bob",
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.pickup_address = "123 Main St"
    ride.dropoff_address = "456 Oak Ave"
    ride.estimated_fare = estimated_fare
    ride.actual_fare = actual_fare
    ride.duration_min = duration_min
    ride.route_deviation_flagged_at = route_deviation_flagged_at
    ride.driver_no_show_reported_at = driver_no_show_reported_at
    ride.cancellation_category = cancellation_category
    ride.cancelled_at = cancelled_at
    ride.completed_at = completed_at or _NOW
    ride.requested_at = _NOW - timedelta(hours=2)

    rider = MagicMock(spec=User)
    rider.name = rider_name
    ride.rider = rider

    if driver_name is not None:
        driver = MagicMock(spec=User)
        driver.name = driver_name
        ride.driver = driver
    else:
        ride.driver = None

    return ride


# ---------------------------------------------------------------------------
# Import the helper functions under test
# ---------------------------------------------------------------------------

from app.api.v1.admin import _anomaly_detected_at, _detect_anomaly_types


# ---------------------------------------------------------------------------
# _detect_anomaly_types
# ---------------------------------------------------------------------------


class TestDetectAnomalyTypes:
    def test_route_deviation(self):
        ride = _make_ride(route_deviation_flagged_at=_NOW)
        types = _detect_anomaly_types(ride)
        assert "route_deviation" in types

    def test_driver_no_show(self):
        ride = _make_ride(driver_no_show_reported_at=_NOW)
        types = _detect_anomaly_types(ride)
        assert "driver_no_show" in types

    def test_safety_cancellation_safety_concern(self):
        ride = _make_ride(cancellation_category=CancellationCategory.SAFETY_CONCERN)
        types = _detect_anomaly_types(ride)
        assert "safety_cancellation" in types

    def test_safety_cancellation_driver_no_show_category(self):
        ride = _make_ride(cancellation_category=CancellationCategory.DRIVER_NO_SHOW)
        types = _detect_anomaly_types(ride)
        assert "safety_cancellation" in types

    def test_safety_cancellation_driver_not_acceptable(self):
        ride = _make_ride(cancellation_category=CancellationCategory.DRIVER_NOT_ACCEPTABLE)
        types = _detect_anomaly_types(ride)
        assert "safety_cancellation" in types

    def test_non_safety_cancellation_not_flagged(self):
        ride = _make_ride(cancellation_category=CancellationCategory.PLANS_CHANGED)
        types = _detect_anomaly_types(ride)
        assert "safety_cancellation" not in types

    def test_excessive_fare(self):
        ride = _make_ride(estimated_fare=20.0, actual_fare=35.0)
        types = _detect_anomaly_types(ride)
        assert "excessive_fare" in types

    def test_fare_just_under_threshold_not_flagged(self):
        ride = _make_ride(estimated_fare=20.0, actual_fare=29.9)
        types = _detect_anomaly_types(ride)
        assert "excessive_fare" not in types

    def test_excessive_fare_exactly_at_threshold_not_flagged(self):
        ride = _make_ride(estimated_fare=20.0, actual_fare=30.0)
        types = _detect_anomaly_types(ride)
        assert "excessive_fare" not in types

    def test_long_duration(self):
        ride = _make_ride(duration_min=120.0)
        types = _detect_anomaly_types(ride)
        assert "long_duration" in types

    def test_duration_at_threshold_not_flagged(self):
        ride = _make_ride(duration_min=90.0)
        types = _detect_anomaly_types(ride)
        assert "long_duration" not in types

    def test_normal_ride_no_anomalies(self):
        ride = _make_ride()
        assert _detect_anomaly_types(ride) == []

    def test_multiple_anomalies_detected(self):
        ride = _make_ride(
            route_deviation_flagged_at=_NOW,
            estimated_fare=20.0,
            actual_fare=40.0,
            duration_min=100.0,
        )
        types = _detect_anomaly_types(ride)
        assert "route_deviation" in types
        assert "excessive_fare" in types
        assert "long_duration" in types


# ---------------------------------------------------------------------------
# _anomaly_detected_at
# ---------------------------------------------------------------------------


class TestAnomalyDetectedAt:
    def test_route_deviation_timestamp_used(self):
        flagged = _NOW - timedelta(hours=1)
        ride = _make_ride(route_deviation_flagged_at=flagged)
        assert _anomaly_detected_at(ride) == flagged

    def test_driver_no_show_timestamp_used(self):
        reported = _NOW - timedelta(minutes=30)
        ride = _make_ride(driver_no_show_reported_at=reported)
        assert _anomaly_detected_at(ride) == reported

    def test_safety_cancellation_uses_cancelled_at(self):
        cancelled = _NOW - timedelta(hours=2)
        ride = _make_ride(
            cancellation_category=CancellationCategory.SAFETY_CONCERN,
            cancelled_at=cancelled,
        )
        result = _anomaly_detected_at(ride)
        assert result == cancelled

    def test_earliest_timestamp_chosen(self):
        early = _NOW - timedelta(hours=3)
        late = _NOW - timedelta(hours=1)
        ride = _make_ride(
            route_deviation_flagged_at=late,
            driver_no_show_reported_at=early,
        )
        assert _anomaly_detected_at(ride) == early

    def test_fallback_to_requested_at_when_no_timestamps(self):
        # Ride has no anomaly-specific timestamps (all candidates None);
        # actual_fare is below the excessive-fare threshold.
        ride = _make_ride(actual_fare=25.0, estimated_fare=20.0, duration_min=30.0)
        result = _anomaly_detected_at(ride)
        assert result == ride.requested_at


# ---------------------------------------------------------------------------
# TripAnomalyEntry schema
# ---------------------------------------------------------------------------


class TestTripAnomalyEntry:
    def test_required_fields(self):
        entry = TripAnomalyEntry(
            ride_id=1,
            rider_id=10,
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            status="completed",
            estimated_fare=20.0,
            anomaly_types=["route_deviation"],
            detected_at=_NOW,
            requested_at=_NOW - timedelta(hours=1),
        )
        assert entry.ride_id == 1
        assert entry.anomaly_types == ["route_deviation"]

    def test_optional_fields_default_none(self):
        entry = TripAnomalyEntry(
            ride_id=2,
            rider_id=11,
            pickup_address="A",
            dropoff_address="B",
            status="cancelled",
            estimated_fare=15.0,
            anomaly_types=["safety_cancellation"],
            detected_at=_NOW,
            requested_at=_NOW,
        )
        assert entry.rider_name is None
        assert entry.driver_id is None
        assert entry.driver_name is None
        assert entry.actual_fare is None
        assert entry.duration_min is None

    def test_multiple_anomaly_types(self):
        entry = TripAnomalyEntry(
            ride_id=3,
            rider_id=12,
            pickup_address="A",
            dropoff_address="B",
            status="completed",
            estimated_fare=10.0,
            actual_fare=20.0,
            duration_min=95.0,
            anomaly_types=["excessive_fare", "long_duration"],
            detected_at=_NOW,
            requested_at=_NOW,
        )
        assert len(entry.anomaly_types) == 2
        assert "excessive_fare" in entry.anomaly_types
        assert "long_duration" in entry.anomaly_types


# ---------------------------------------------------------------------------
# TripAnomalyListResponse schema
# ---------------------------------------------------------------------------


class TestTripAnomalyListResponse:
    def test_empty_response(self):
        resp = TripAnomalyListResponse(anomalies=[], total=0, page=1, per_page=20)
        assert resp.total == 0
        assert resp.anomalies == []

    def test_total_reflects_database_count_not_page_size(self):
        entry = TripAnomalyEntry(
            ride_id=1,
            rider_id=1,
            pickup_address="A",
            dropoff_address="B",
            status="completed",
            estimated_fare=10.0,
            anomaly_types=["long_duration"],
            detected_at=_NOW,
            requested_at=_NOW,
        )
        resp = TripAnomalyListResponse(anomalies=[entry], total=150, page=1, per_page=20)
        assert resp.total == 150
        assert len(resp.anomalies) == 1

    def test_pagination_fields_preserved(self):
        resp = TripAnomalyListResponse(anomalies=[], total=0, page=3, per_page=50)
        assert resp.page == 3
        assert resp.per_page == 50
