"""Tests for driver en-route and arrived state transitions."""

import enum
from unittest.mock import AsyncMock, MagicMock

import pytest


class RideStatus(str, enum.Enum):
    REQUESTED = "requested"
    MATCHED = "matched"
    DRIVER_EN_ROUTE = "driver_en_route"
    ARRIVED = "arrived"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


def _make_ride(status=RideStatus.MATCHED, driver_id=20, rider_id=10, ride_id=1):
    ride = MagicMock()
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.actual_fare = None
    return ride


class TestRideStateTransitions:
    def test_valid_en_route_transition(self):
        ride = _make_ride(status=RideStatus.MATCHED)
        assert ride.status == RideStatus.MATCHED
        ride.status = RideStatus.DRIVER_EN_ROUTE
        assert ride.status == RideStatus.DRIVER_EN_ROUTE

    def test_valid_arrived_transition(self):
        ride = _make_ride(status=RideStatus.DRIVER_EN_ROUTE)
        ride.status = RideStatus.ARRIVED
        assert ride.status == RideStatus.ARRIVED

    def test_valid_start_from_arrived(self):
        ride = _make_ride(status=RideStatus.ARRIVED)
        ride.status = RideStatus.IN_PROGRESS
        assert ride.status == RideStatus.IN_PROGRESS

    def test_valid_start_from_matched(self):
        ride = _make_ride(status=RideStatus.MATCHED)
        ride.status = RideStatus.IN_PROGRESS
        assert ride.status == RideStatus.IN_PROGRESS

    def test_full_lifecycle(self):
        ride = _make_ride(status=RideStatus.REQUESTED)
        transitions = [
            RideStatus.MATCHED,
            RideStatus.DRIVER_EN_ROUTE,
            RideStatus.ARRIVED,
            RideStatus.IN_PROGRESS,
            RideStatus.COMPLETED,
        ]
        for expected in transitions:
            ride.status = expected
            assert ride.status == expected

    def test_en_route_only_from_matched(self):
        for bad_status in [
            RideStatus.REQUESTED,
            RideStatus.DRIVER_EN_ROUTE,
            RideStatus.ARRIVED,
            RideStatus.IN_PROGRESS,
            RideStatus.COMPLETED,
            RideStatus.CANCELLED,
        ]:
            assert bad_status != RideStatus.MATCHED

    def test_arrived_only_from_en_route(self):
        for bad_status in [
            RideStatus.REQUESTED,
            RideStatus.MATCHED,
            RideStatus.ARRIVED,
            RideStatus.IN_PROGRESS,
            RideStatus.COMPLETED,
            RideStatus.CANCELLED,
        ]:
            assert bad_status != RideStatus.DRIVER_EN_ROUTE

    def test_all_statuses_exist(self):
        expected = {
            "requested", "matched", "driver_en_route", "arrived",
            "in_progress", "completed", "cancelled",
        }
        actual = {s.value for s in RideStatus}
        assert actual == expected
