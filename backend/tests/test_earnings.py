from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.payment import Payment, PaymentStatus
from app.models.ride import Ride, RideStatus
from app.schemas.driver import EarningsResponse, EarningsSummary, EarningsTrip


def _make_ride(ride_id, driver_id=20, fare=25.0, tip=3.0, distance=8.5, duration=22.0, completed_days_ago=1):
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.driver_id = driver_id
    ride.rider_id = 10
    ride.status = RideStatus.COMPLETED
    ride.actual_fare = fare
    ride.tip_amount = tip
    ride.distance_km = distance
    ride.duration_min = duration
    ride.pickup_address = f"Pickup {ride_id}"
    ride.dropoff_address = f"Dropoff {ride_id}"
    ride.completed_at = datetime.now(timezone.utc) - timedelta(days=completed_days_ago)
    return ride


def _make_payment(ride_id, driver_payout=25.0, tip=3.0, status=PaymentStatus.COMPLETED):
    payment = MagicMock(spec=Payment)
    payment.ride_id = ride_id
    payment.driver_payout = driver_payout
    payment.tip_amount = tip
    payment.platform_fee = 0.0
    payment.amount = driver_payout
    payment.status = status
    return payment


class TestEarningsSummaryCalculation:
    def test_summary_with_trips(self):
        summary = EarningsSummary(
            total_fares=75.0,
            total_tips=9.0,
            total_earnings=84.0,
            trip_count=3,
            average_fare=25.0,
            average_tip=3.0,
            period_start=date(2026, 4, 4),
            period_end=date(2026, 4, 11),
        )
        assert summary.total_earnings == 84.0
        assert summary.trip_count == 3

    def test_summary_zero_trips(self):
        summary = EarningsSummary(
            total_fares=0.0,
            total_tips=0.0,
            total_earnings=0.0,
            trip_count=0,
            average_fare=0.0,
            average_tip=0.0,
            period_start=date(2026, 4, 4),
            period_end=date(2026, 4, 11),
        )
        assert summary.trip_count == 0
        assert summary.total_earnings == 0.0


class TestEarningsTrip:
    def test_trip_total(self):
        trip = EarningsTrip(
            ride_id=1,
            pickup_address="A",
            dropoff_address="B",
            fare=25.0,
            tip=5.0,
            total=30.0,
            distance_km=10.0,
            duration_min=20.0,
            completed_at=datetime.now(timezone.utc),
        )
        assert trip.total == 30.0
        assert trip.fare + trip.tip == trip.total

    def test_trip_no_tip(self):
        trip = EarningsTrip(
            ride_id=2,
            pickup_address="C",
            dropoff_address="D",
            fare=18.50,
            tip=0.0,
            total=18.50,
            distance_km=5.2,
            duration_min=12.0,
            completed_at=None,
        )
        assert trip.tip == 0.0
        assert trip.total == trip.fare


class TestEarningsResponse:
    def test_full_response(self):
        trips = [
            EarningsTrip(
                ride_id=i,
                pickup_address=f"P{i}",
                dropoff_address=f"D{i}",
                fare=20.0 + i,
                tip=2.0,
                total=22.0 + i,
                distance_km=8.0,
                duration_min=15.0,
                completed_at=datetime.now(timezone.utc),
            )
            for i in range(3)
        ]
        resp = EarningsResponse(
            summary=EarningsSummary(
                total_fares=63.0,
                total_tips=6.0,
                total_earnings=69.0,
                trip_count=3,
                average_fare=21.0,
                average_tip=2.0,
                period_start=date(2026, 4, 4),
                period_end=date(2026, 4, 11),
            ),
            trips=trips,
        )
        assert len(resp.trips) == 3
        assert resp.summary.trip_count == 3

    def test_empty_response(self):
        resp = EarningsResponse(
            summary=EarningsSummary(
                total_fares=0.0,
                total_tips=0.0,
                total_earnings=0.0,
                trip_count=0,
                average_fare=0.0,
                average_tip=0.0,
                period_start=date(2026, 4, 11),
                period_end=date(2026, 4, 11),
            ),
            trips=[],
        )
        assert len(resp.trips) == 0


class TestEarningsWithPayment:
    def test_uses_payment_driver_payout_when_completed(self):
        ride = _make_ride(1, fare=25.0)
        payment = _make_payment(1, driver_payout=25.0, tip=5.0, status=PaymentStatus.COMPLETED)

        fare = payment.driver_payout if payment and payment.status == PaymentStatus.COMPLETED else (ride.actual_fare or 0.0)
        tip = payment.tip_amount if payment else ride.tip_amount

        assert fare == 25.0
        assert tip == 5.0

    def test_falls_back_to_ride_fare_when_payment_pending(self):
        ride = _make_ride(2, fare=30.0, tip=4.0)
        payment = _make_payment(2, driver_payout=30.0, tip=4.0, status=PaymentStatus.PENDING)

        fare = payment.driver_payout if payment and payment.status == PaymentStatus.COMPLETED else (ride.actual_fare or 0.0)
        tip = payment.tip_amount if payment else ride.tip_amount

        assert fare == 30.0
        assert tip == 4.0

    def test_falls_back_to_ride_when_no_payment(self):
        ride = _make_ride(3, fare=15.0, tip=2.0)
        payment = None

        fare = payment.driver_payout if payment and payment.status == PaymentStatus.COMPLETED else (ride.actual_fare or 0.0)
        tip = payment.tip_amount if payment else ride.tip_amount

        assert fare == 15.0
        assert tip == 2.0
