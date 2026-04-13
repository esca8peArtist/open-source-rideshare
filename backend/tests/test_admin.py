from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.models.driver import DriverProfile
from app.models.payment import Payment, PaymentStatus
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.schemas.admin import (
    AdminDriverResponse,
    AdminPaymentResponse,
    AdminRideResponse,
    DashboardStats,
    DriversListResponse,
    PaginationResponse,
    PaymentsListResponse,
    PlatformSettings,
    RevenueDataPoint,
    RideActivityDataPoint,
    RidesListResponse,
    SuspendRequest,
)


def _make_user(user_id=1, name="Test User", phone="5551234567", role=UserRole.RIDER):
    user = MagicMock(spec=User)
    user.id = user_id
    user.name = name
    user.phone = phone
    user.role = role
    user.is_active = True
    return user


def _make_ride(ride_id=1, rider_id=1, driver_id=2, status=RideStatus.COMPLETED):
    rider = _make_user(rider_id, "Rider One", "5551111111")
    driver = _make_user(driver_id, "Driver One", "5552222222", UserRole.DRIVER)
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.pickup_address = "123 Main St"
    ride.dropoff_address = "456 Oak Ave"
    ride.estimated_fare = 15.50
    ride.actual_fare = 14.25
    ride.distance_km = 8.3
    ride.duration_min = 18.0
    ride.tip_amount = 3.00
    ride.rider_rating = 5
    ride.driver_rating = 4
    ride.cancellation_reason = None
    ride.requested_at = datetime.now(timezone.utc) - timedelta(hours=2)
    ride.matched_at = datetime.now(timezone.utc) - timedelta(hours=1, minutes=55)
    ride.started_at = datetime.now(timezone.utc) - timedelta(hours=1, minutes=50)
    ride.completed_at = datetime.now(timezone.utc) - timedelta(hours=1, minutes=30)
    ride.cancelled_at = None
    ride.rider = rider
    ride.driver = driver
    return ride


def _make_driver_profile(profile_id=1, user_id=10, is_approved=True, is_online=False):
    user = _make_user(user_id, "Driver Name", "5553333333", UserRole.DRIVER)
    profile = MagicMock(spec=DriverProfile)
    profile.id = profile_id
    profile.user_id = user_id
    profile.user = user
    profile.vehicle_type = "sedan"
    profile.vehicle_make = "Toyota"
    profile.vehicle_model = "Camry"
    profile.vehicle_year = 2022
    profile.vehicle_color = "Silver"
    profile.license_plate = "ABC1234"
    profile.license_number = "DL123456"
    profile.insurance_policy = "INS-789"
    profile.background_check_status = "approved"
    profile.rating_avg = 4.8
    profile.total_trips = 150
    profile.is_online = is_online
    profile.is_approved = is_approved
    profile.created_at = datetime.now(timezone.utc) - timedelta(days=30)
    profile.updated_at = datetime.now(timezone.utc) - timedelta(days=1)
    return profile


def _make_payment(payment_id=1, ride_id=1, status=PaymentStatus.COMPLETED):
    ride = _make_ride(ride_id)
    payment = MagicMock(spec=Payment)
    payment.id = payment_id
    payment.ride_id = ride_id
    payment.amount = 14.25
    payment.platform_fee = 0.0
    payment.driver_payout = 14.25
    payment.tip_amount = 3.00
    payment.status = status
    payment.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
    payment.ride = ride
    return payment


class TestAdminRideResponse:
    def test_from_ride_model(self):
        ride = _make_ride()
        resp = AdminRideResponse(
            id=ride.id,
            status=ride.status.value,
            pickup_address=ride.pickup_address,
            dropoff_address=ride.dropoff_address,
            estimated_fare=ride.estimated_fare,
            actual_fare=ride.actual_fare,
            distance_km=ride.distance_km,
            duration_min=ride.duration_min,
            tip_amount=ride.tip_amount,
            rider_id=ride.rider_id,
            driver_id=ride.driver_id,
            rider_name=ride.rider.name,
            driver_name=ride.driver.name,
            rider_rating=ride.rider_rating,
            driver_rating=ride.driver_rating,
            cancellation_reason=ride.cancellation_reason,
            requested_at=ride.requested_at,
            matched_at=ride.matched_at,
            started_at=ride.started_at,
            completed_at=ride.completed_at,
            cancelled_at=ride.cancelled_at,
        )
        assert resp.id == 1
        assert resp.status == "completed"
        assert resp.rider_name == "Rider One"
        assert resp.driver_name == "Driver One"
        assert resp.estimated_fare == 15.50
        assert resp.actual_fare == 14.25
        assert resp.tip_amount == 3.00

    def test_cancelled_ride(self):
        ride = _make_ride(status=RideStatus.CANCELLED)
        ride.cancellation_reason = "Rider changed plans"
        ride.cancelled_at = datetime.now(timezone.utc)
        ride.completed_at = None
        ride.actual_fare = None
        resp = AdminRideResponse(
            id=ride.id,
            status=ride.status.value,
            pickup_address=ride.pickup_address,
            dropoff_address=ride.dropoff_address,
            estimated_fare=ride.estimated_fare,
            actual_fare=ride.actual_fare,
            rider_id=ride.rider_id,
            driver_id=ride.driver_id,
            rider_name=ride.rider.name,
            driver_name=ride.driver.name,
            cancellation_reason=ride.cancellation_reason,
            requested_at=ride.requested_at,
            cancelled_at=ride.cancelled_at,
        )
        assert resp.status == "cancelled"
        assert resp.cancellation_reason == "Rider changed plans"
        assert resp.actual_fare is None

    def test_ride_without_driver(self):
        ride = _make_ride(status=RideStatus.REQUESTED)
        ride.driver = None
        ride.driver_id = None
        resp = AdminRideResponse(
            id=ride.id,
            status=ride.status.value,
            pickup_address=ride.pickup_address,
            dropoff_address=ride.dropoff_address,
            estimated_fare=ride.estimated_fare,
            rider_id=ride.rider_id,
            driver_id=None,
            rider_name=ride.rider.name,
            driver_name=None,
            requested_at=ride.requested_at,
        )
        assert resp.driver_id is None
        assert resp.driver_name is None


class TestRidesListResponse:
    def test_with_rides(self):
        rides = [
            AdminRideResponse(
                id=i,
                status="completed",
                pickup_address=f"Pickup {i}",
                dropoff_address=f"Dropoff {i}",
                estimated_fare=10.0 + i,
                rider_id=1,
                requested_at=datetime.now(timezone.utc),
            )
            for i in range(3)
        ]
        resp = RidesListResponse(
            rides=rides,
            pagination=PaginationResponse(page=1, per_page=20, total=3),
        )
        assert len(resp.rides) == 3
        assert resp.pagination.total == 3

    def test_empty_list(self):
        resp = RidesListResponse(
            rides=[],
            pagination=PaginationResponse(page=1, per_page=20, total=0),
        )
        assert len(resp.rides) == 0
        assert resp.pagination.total == 0


class TestAdminDriverResponse:
    def test_from_driver_profile(self):
        profile = _make_driver_profile()
        resp = AdminDriverResponse(
            id=profile.id,
            user_id=profile.user_id,
            user_name=profile.user.name,
            user_phone=profile.user.phone,
            vehicle_type=profile.vehicle_type,
            vehicle_make=profile.vehicle_make,
            vehicle_model=profile.vehicle_model,
            vehicle_year=profile.vehicle_year,
            vehicle_color=profile.vehicle_color,
            license_plate=profile.license_plate,
            license_number=profile.license_number,
            insurance_policy=profile.insurance_policy,
            background_check_status=profile.background_check_status,
            rating_avg=profile.rating_avg,
            total_trips=profile.total_trips,
            is_online=profile.is_online,
            is_approved=profile.is_approved,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )
        assert resp.user_name == "Driver Name"
        assert resp.vehicle_make == "Toyota"
        assert resp.is_approved is True
        assert resp.total_trips == 150

    def test_pending_driver(self):
        profile = _make_driver_profile(is_approved=False)
        profile.background_check_status = "pending"
        resp = AdminDriverResponse(
            id=profile.id,
            user_id=profile.user_id,
            user_name=profile.user.name,
            user_phone=profile.user.phone,
            vehicle_type=profile.vehicle_type,
            vehicle_make=profile.vehicle_make,
            vehicle_model=profile.vehicle_model,
            vehicle_year=profile.vehicle_year,
            vehicle_color=profile.vehicle_color,
            license_plate=profile.license_plate,
            license_number=profile.license_number,
            background_check_status=profile.background_check_status,
            rating_avg=profile.rating_avg,
            total_trips=profile.total_trips,
            is_online=profile.is_online,
            is_approved=profile.is_approved,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )
        assert resp.is_approved is False
        assert resp.background_check_status == "pending"


class TestAdminPaymentResponse:
    def test_completed_payment(self):
        payment = _make_payment()
        resp = AdminPaymentResponse(
            id=payment.id,
            ride_id=payment.ride_id,
            amount=payment.amount,
            platform_fee=payment.platform_fee,
            driver_payout=payment.driver_payout,
            tip_amount=payment.tip_amount,
            status=payment.status.value,
            created_at=payment.created_at,
            rider_name=payment.ride.rider.name,
            driver_name=payment.ride.driver.name,
            pickup_address=payment.ride.pickup_address,
            dropoff_address=payment.ride.dropoff_address,
        )
        assert resp.status == "completed"
        assert resp.amount == 14.25
        assert resp.platform_fee == 0.0
        assert resp.driver_payout == 14.25
        assert resp.rider_name == "Rider One"

    def test_refunded_payment(self):
        payment = _make_payment(status=PaymentStatus.REFUNDED)
        resp = AdminPaymentResponse(
            id=payment.id,
            ride_id=payment.ride_id,
            amount=payment.amount,
            platform_fee=payment.platform_fee,
            driver_payout=payment.driver_payout,
            tip_amount=payment.tip_amount,
            status=payment.status.value,
            created_at=payment.created_at,
        )
        assert resp.status == "refunded"


class TestDashboardStats:
    def test_active_platform(self):
        stats = DashboardStats(
            active_rides=12,
            online_drivers=8,
            revenue_today=1234.56,
            total_users=500,
            rides_today=45,
            completed_today=38,
            cancelled_today=3,
        )
        assert stats.active_rides == 12
        assert stats.online_drivers == 8
        assert stats.revenue_today == 1234.56
        assert stats.completed_today + stats.cancelled_today <= stats.rides_today

    def test_empty_platform(self):
        stats = DashboardStats(
            active_rides=0,
            online_drivers=0,
            revenue_today=0.0,
            total_users=0,
            rides_today=0,
            completed_today=0,
            cancelled_today=0,
        )
        assert stats.active_rides == 0
        assert stats.revenue_today == 0.0


class TestRevenueDataPoint:
    def test_data_point(self):
        point = RevenueDataPoint(date="2026-04-11", revenue=523.75, rides=42, tips=67.50)
        assert point.date == "2026-04-11"
        assert point.revenue == 523.75
        assert point.rides == 42
        assert point.tips == 67.50


class TestRideActivityDataPoint:
    def test_data_point(self):
        point = RideActivityDataPoint(hour="14:00", rides=23)
        assert point.hour == "14:00"
        assert point.rides == 23


class TestPlatformSettings:
    def test_defaults(self):
        s = PlatformSettings(
            base_fare=2.50,
            per_km_rate=1.50,
            per_min_rate=0.25,
            platform_fee_percent=0.0,
            max_search_radius_km=8.0,
            surge_multiplier=1.0,
        )
        assert s.base_fare == 2.50
        assert s.platform_fee_percent == 0.0
        assert s.surge_multiplier == 1.0

    def test_surge_pricing(self):
        s = PlatformSettings(
            base_fare=2.50,
            per_km_rate=1.50,
            per_min_rate=0.25,
            platform_fee_percent=0.0,
            max_search_radius_km=8.0,
            surge_multiplier=2.5,
        )
        assert s.surge_multiplier == 2.5

    def test_roundtrip_serialization(self):
        original = PlatformSettings(
            base_fare=3.00,
            per_km_rate=2.00,
            per_min_rate=0.30,
            platform_fee_percent=5.0,
            max_search_radius_km=10.0,
            surge_multiplier=1.5,
        )
        data = original.model_dump()
        restored = PlatformSettings(**data)
        assert restored == original


class TestSuspendRequest:
    def test_with_reason(self):
        req = SuspendRequest(reason="Failed background check")
        assert req.reason == "Failed background check"


class TestPaginationResponse:
    def test_first_page(self):
        p = PaginationResponse(page=1, per_page=20, total=55)
        assert p.page == 1
        assert p.total == 55

    def test_last_page(self):
        p = PaginationResponse(page=3, per_page=20, total=55)
        assert p.page == 3


class TestDriversListResponse:
    def test_with_drivers(self):
        drivers = [
            AdminDriverResponse(
                id=i,
                user_id=i + 10,
                vehicle_type="sedan",
                vehicle_make="Honda",
                vehicle_model="Civic",
                vehicle_year=2023,
                vehicle_color="Blue",
                license_plate=f"XY{i}",
                license_number=f"DL{i}",
                background_check_status="approved",
                rating_avg=4.5,
                total_trips=50,
                is_online=True,
                is_approved=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            for i in range(2)
        ]
        resp = DriversListResponse(
            drivers=drivers,
            pagination=PaginationResponse(page=1, per_page=20, total=2),
        )
        assert len(resp.drivers) == 2


class TestPaymentsListResponse:
    def test_with_payments(self):
        payments = [
            AdminPaymentResponse(
                id=1,
                ride_id=1,
                amount=20.0,
                platform_fee=0.0,
                driver_payout=20.0,
                tip_amount=3.0,
                status="completed",
                created_at=datetime.now(timezone.utc),
            )
        ]
        resp = PaymentsListResponse(
            payments=payments,
            pagination=PaginationResponse(page=1, per_page=20, total=1),
        )
        assert len(resp.payments) == 1
        assert resp.payments[0].amount == 20.0
