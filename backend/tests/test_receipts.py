"""Unit tests for ride receipt feature.

Tests cover:
- Receipt service logic (generate_receipt)
- Receipt endpoint (GET /rides/{ride_id}/receipt)
- Edge cases: non-completed rides, unauthorized access, missing driver/payment
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.driver import DriverProfile
from app.models.payment import Payment, PaymentStatus, PaymentType
from app.models.promo import PromoCode
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.services.pricing import FareBreakdown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id=1, role=UserRole.RIDER, name="Test Rider"):
    user = MagicMock(spec=User)
    user.id = user_id
    user.role = role
    user.name = name
    return user


def _make_driver_profile(
    user_id=20,
    rating_avg=4.8,
    vehicle_color="Silver",
    vehicle_make="Toyota",
    vehicle_model="Camry",
    license_plate="TEST-123",
):
    profile = MagicMock(spec=DriverProfile)
    profile.user_id = user_id
    profile.rating_avg = rating_avg
    profile.vehicle_color = vehicle_color
    profile.vehicle_make = vehicle_make
    profile.vehicle_model = vehicle_model
    profile.license_plate = license_plate
    return profile


def _make_completed_ride(
    ride_id=1,
    rider_id=10,
    driver_id=20,
    pickup_address="123 Main St",
    dropoff_address="456 Oak Ave",
    estimated_fare=15.50,
    actual_fare=15.50,
    distance_km=8.5,
    duration_min=12.0,
    tip_amount=3.0,
    promo_code_id=None,
    promo_discount=0.0,
    driver_rating=5,
    requested_at=None,
    started_at=None,
    completed_at=None,
    driver=None,
    rider=None,
):
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = RideStatus.COMPLETED
    ride.pickup_address = pickup_address
    ride.dropoff_address = dropoff_address
    ride.estimated_fare = estimated_fare
    ride.actual_fare = actual_fare
    ride.distance_km = distance_km
    ride.duration_min = duration_min
    ride.tip_amount = tip_amount
    ride.promo_code_id = promo_code_id
    ride.promo_discount = promo_discount
    ride.driver_rating = driver_rating
    ride.requested_at = requested_at or datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc)
    ride.started_at = started_at or datetime(2026, 4, 12, 10, 5, tzinfo=timezone.utc)
    ride.completed_at = completed_at or datetime(2026, 4, 12, 10, 17, tzinfo=timezone.utc)
    ride.driver = driver
    ride.rider = rider
    return ride


def _make_payment(
    ride_id=1,
    amount=15.50,
    platform_fee=0.0,
    driver_payout=15.50,
    tip_amount=3.0,
    status=PaymentStatus.COMPLETED,
):
    payment = MagicMock(spec=Payment)
    payment.ride_id = ride_id
    payment.payment_type = PaymentType.RIDE_FARE
    payment.amount = amount
    payment.platform_fee = platform_fee
    payment.driver_payout = driver_payout
    payment.tip_amount = tip_amount
    payment.status = status
    return payment


# ---------------------------------------------------------------------------
# Receipt service tests
# ---------------------------------------------------------------------------

class TestGenerateReceipt:
    """Tests for app.services.receipts.generate_receipt."""

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_ride(self):
        from app.services.receipts import generate_receipt

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.unique.return_value = result_mock
        result_mock.scalar_one_or_none.return_value = None
        db.execute.return_value = result_mock

        receipt = await generate_receipt(999, user_id=10, db=db)
        assert receipt is None

    @pytest.mark.asyncio
    async def test_returns_none_for_non_completed_ride(self):
        from app.services.receipts import generate_receipt

        ride = _make_completed_ride()
        ride.status = RideStatus.IN_PROGRESS

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.unique.return_value = result_mock
        result_mock.scalar_one_or_none.return_value = ride
        db.execute.return_value = result_mock

        receipt = await generate_receipt(1, user_id=10, db=db)
        assert receipt is None

    @pytest.mark.asyncio
    async def test_returns_none_for_unauthorized_user(self):
        from app.services.receipts import generate_receipt

        ride = _make_completed_ride(rider_id=10, driver_id=20)

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.unique.return_value = result_mock
        result_mock.scalar_one_or_none.return_value = ride
        db.execute.return_value = result_mock

        receipt = await generate_receipt(1, user_id=999, db=db)
        assert receipt is None

    @pytest.mark.asyncio
    async def test_basic_receipt_for_rider(self):
        from app.services.receipts import generate_receipt

        driver_user = _make_user(user_id=20, name="Driver Dan")
        ride = _make_completed_ride(
            rider_id=10,
            driver_id=20,
            actual_fare=15.50,
            tip_amount=3.0,
            driver=driver_user,
        )

        profile = _make_driver_profile(user_id=20)
        payment = _make_payment(amount=15.50, tip_amount=3.0)

        # Build a db mock that returns different things for different queries
        call_count = 0
        async def mock_execute(query, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()

            if call_count == 1:  # Ride query (with joinedload)
                result.unique.return_value = result
                result.scalar_one_or_none.return_value = ride
            elif call_count == 2:  # Payment query
                result.scalar_one_or_none.return_value = payment
            elif call_count == 3:  # DriverProfile query
                result.scalar_one_or_none.return_value = profile
            else:
                result.scalar_one_or_none.return_value = None
            return result

        db = AsyncMock()
        db.execute = mock_execute

        receipt = await generate_receipt(1, user_id=10, db=db)

        assert receipt is not None
        assert receipt["ride_id"] == 1
        assert receipt["receipt_number"] == "OR-00000001"
        assert receipt["status"] == "completed"
        assert receipt["pickup_address"] == "123 Main St"
        assert receipt["dropoff_address"] == "456 Oak Ave"
        assert receipt["distance_km"] == 8.5
        assert receipt["duration_min"] == 12.0
        assert receipt["tip"] == 3.0
        assert receipt["rider_rating_given"] == 5
        assert receipt["cooperative_name"] == "OpenRide"
        assert receipt["currency"] == "USD"

        # Fare breakdown present
        assert "fare_breakdown" in receipt
        assert receipt["fare_breakdown"]["base"] >= 0

        # Driver info
        assert receipt["driver"] is not None
        assert receipt["driver"]["name"] == "Driver Dan"
        assert receipt["driver"]["license_plate"] == "TEST-123"
        assert receipt["driver"]["vehicle"] == "Silver Toyota Camry"

        # Payment info
        assert receipt["payment"] is not None
        assert receipt["payment"]["amount_charged"] == 15.50
        assert receipt["payment"]["tip"] == 3.0

    @pytest.mark.asyncio
    async def test_receipt_without_payment_record(self):
        """Receipt should still work if no Payment row exists yet."""
        from app.services.receipts import generate_receipt

        ride = _make_completed_ride(rider_id=10, driver_id=None, driver=None)

        call_count = 0
        async def mock_execute(query, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.unique.return_value = result
                result.scalar_one_or_none.return_value = ride
            else:
                result.scalar_one_or_none.return_value = None
            return result

        db = AsyncMock()
        db.execute = mock_execute

        receipt = await generate_receipt(1, user_id=10, db=db)
        assert receipt is not None
        assert receipt["payment"] is None
        assert receipt["driver"] is None

    @pytest.mark.asyncio
    async def test_receipt_with_promo_discount(self):
        from app.services.receipts import generate_receipt

        ride = _make_completed_ride(
            rider_id=10,
            driver_id=20,
            actual_fare=10.50,
            promo_code_id=42,
            promo_discount=5.0,
            tip_amount=2.0,
            driver=_make_user(user_id=20, name="Driver"),
        )

        profile = _make_driver_profile(user_id=20)

        call_count = 0
        async def mock_execute(query, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.unique.return_value = result
                result.scalar_one_or_none.return_value = ride
            elif call_count == 2:  # Payment
                result.scalar_one_or_none.return_value = None
            elif call_count == 3:  # DriverProfile
                result.scalar_one_or_none.return_value = profile
            elif call_count == 4:  # PromoCode.code
                result.scalar_one_or_none.return_value = "WELCOME5"
            else:
                result.scalar_one_or_none.return_value = None
            return result

        db = AsyncMock()
        db.execute = mock_execute

        receipt = await generate_receipt(1, user_id=10, db=db)
        assert receipt is not None
        assert receipt["promo_code"] == "WELCOME5"
        assert receipt["promo_discount"] == 5.0
        assert receipt["total_charged"] == round(10.50 + 2.0 - 5.0, 2)

    @pytest.mark.asyncio
    async def test_driver_can_view_receipt(self):
        from app.services.receipts import generate_receipt

        ride = _make_completed_ride(rider_id=10, driver_id=20, driver=None)

        call_count = 0
        async def mock_execute(query, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.unique.return_value = result
                result.scalar_one_or_none.return_value = ride
            else:
                result.scalar_one_or_none.return_value = None
            return result

        db = AsyncMock()
        db.execute = mock_execute

        receipt = await generate_receipt(1, user_id=20, db=db)
        assert receipt is not None
        assert receipt["ride_id"] == 1

    @pytest.mark.asyncio
    async def test_receipt_number_format(self):
        from app.services.receipts import generate_receipt

        ride = _make_completed_ride(ride_id=42, rider_id=10, driver=None)

        call_count = 0
        async def mock_execute(query, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.unique.return_value = result
                result.scalar_one_or_none.return_value = ride
            else:
                result.scalar_one_or_none.return_value = None
            return result

        db = AsyncMock()
        db.execute = mock_execute

        receipt = await generate_receipt(42, user_id=10, db=db)
        assert receipt["receipt_number"] == "OR-00000042"


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------

class TestReceiptEndpoint:
    """Tests for GET /rides/{ride_id}/receipt."""

    @pytest.mark.asyncio
    async def test_returns_receipt(self):
        from app.api.v1.rides import get_receipt

        user = _make_user(user_id=10)
        db = AsyncMock()

        mock_receipt = {
            "ride_id": 1,
            "status": "completed",
            "receipt_number": "OR-00000001",
            "pickup_address": "123 Main St",
            "dropoff_address": "456 Oak Ave",
            "distance_km": 8.5,
            "duration_min": 12.0,
            "fare_breakdown": {
                "base": 2.50,
                "distance": 8.50,
                "time": 2.40,
                "multiplier": 1.0,
                "multiplier_label": None,
                "subtotal": 13.40,
                "platform_fee": 0.0,
                "total": 13.40,
            },
            "promo_code": None,
            "promo_discount": 0.0,
            "tip": 3.0,
            "total_charged": 16.40,
            "payment": None,
            "driver": None,
            "requested_at": datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc),
            "started_at": datetime(2026, 4, 12, 10, 5, tzinfo=timezone.utc),
            "completed_at": datetime(2026, 4, 12, 10, 17, tzinfo=timezone.utc),
            "rider_rating_given": 5,
            "cooperative_name": "OpenRide",
            "currency": "USD",
        }

        with patch("app.services.receipts.generate_receipt", new_callable=AsyncMock, return_value=mock_receipt) as mock_gen:
            result = await get_receipt(ride_id=1, user=user, db=db)
            mock_gen.assert_awaited_once_with(1, 10, db)
            assert result.ride_id == 1
            assert result.receipt_number == "OR-00000001"
            assert result.total_charged == 16.40

    @pytest.mark.asyncio
    async def test_returns_404_when_no_receipt(self):
        from app.api.v1.rides import get_receipt

        user = _make_user(user_id=10)
        db = AsyncMock()

        with patch("app.services.receipts.generate_receipt", new_callable=AsyncMock, return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await get_receipt(ride_id=999, user=user, db=db)
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_receipt_with_payment_and_driver(self):
        from app.api.v1.rides import get_receipt

        user = _make_user(user_id=10)
        db = AsyncMock()

        mock_receipt = {
            "ride_id": 5,
            "status": "completed",
            "receipt_number": "OR-00000005",
            "pickup_address": "A",
            "dropoff_address": "B",
            "distance_km": 5.0,
            "duration_min": 8.0,
            "fare_breakdown": {
                "base": 2.50, "distance": 5.0, "time": 1.6,
                "multiplier": 1.0, "multiplier_label": None,
                "subtotal": 9.10, "platform_fee": 0.0, "total": 9.10,
            },
            "promo_code": "SAVE10",
            "promo_discount": 1.0,
            "tip": 2.0,
            "total_charged": 10.10,
            "payment": {
                "payment_method": "card",
                "payment_status": "completed",
                "amount_charged": 9.10,
                "platform_fee": 0.0,
                "driver_payout": 9.10,
                "tip": 2.0,
                "promo_discount": 1.0,
                "total_charged": 10.10,
            },
            "driver": {
                "name": "Driver Dan",
                "rating": 4.8,
                "vehicle": "Silver Toyota Camry",
                "license_plate": "TEST-123",
            },
            "requested_at": datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc),
            "started_at": datetime(2026, 4, 12, 10, 5, tzinfo=timezone.utc),
            "completed_at": datetime(2026, 4, 12, 10, 13, tzinfo=timezone.utc),
            "rider_rating_given": 4,
            "cooperative_name": "OpenRide",
            "currency": "USD",
        }

        with patch("app.services.receipts.generate_receipt", new_callable=AsyncMock, return_value=mock_receipt):
            result = await get_receipt(ride_id=5, user=user, db=db)
            assert result.payment is not None
            assert result.payment.amount_charged == 9.10
            assert result.driver is not None
            assert result.driver.name == "Driver Dan"
            assert result.promo_code == "SAVE10"
            assert result.promo_discount == 1.0


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

class TestReceiptSchema:

    def test_receipt_response_minimal(self):
        from app.schemas.ride import RideReceiptResponse

        data = RideReceiptResponse(
            ride_id=1,
            status="completed",
            receipt_number="OR-00000001",
            pickup_address="A",
            dropoff_address="B",
            distance_km=5.0,
            duration_min=8.0,
            fare_breakdown={
                "base": 2.50, "distance": 5.0, "time": 1.6,
                "multiplier": 1.0, "subtotal": 9.10, "total": 9.10,
            },
            total_charged=9.10,
            requested_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
        )
        assert data.ride_id == 1
        assert data.payment is None
        assert data.driver is None
        assert data.promo_code is None
        assert data.cooperative_name == "OpenRide"
        assert data.currency == "USD"

    def test_receipt_response_full(self):
        from app.schemas.ride import RideReceiptResponse

        data = RideReceiptResponse(
            ride_id=5,
            status="completed",
            receipt_number="OR-00000005",
            pickup_address="123 Main",
            dropoff_address="456 Oak",
            distance_km=8.5,
            duration_min=12.0,
            fare_breakdown={
                "base": 2.50, "distance": 8.50, "time": 2.40,
                "multiplier": 1.25, "multiplier_label": "Late night",
                "subtotal": 16.75, "platform_fee": 0.50, "total": 17.25,
            },
            promo_code="FIRST5",
            promo_discount=5.0,
            tip=3.0,
            total_charged=15.25,
            payment={
                "payment_method": "card",
                "payment_status": "completed",
                "amount_charged": 17.25,
                "platform_fee": 0.50,
                "driver_payout": 16.75,
                "tip": 3.0,
                "promo_discount": 5.0,
                "total_charged": 15.25,
            },
            driver={
                "name": "Dan",
                "rating": 4.9,
                "vehicle": "White Tesla 3",
                "license_plate": "EV-001",
            },
            requested_at=datetime(2026, 4, 12, 22, 0, tzinfo=timezone.utc),
            started_at=datetime(2026, 4, 12, 22, 5, tzinfo=timezone.utc),
            completed_at=datetime(2026, 4, 12, 22, 17, tzinfo=timezone.utc),
            rider_rating_given=5,
        )
        assert data.fare_breakdown.multiplier == 1.25
        assert data.fare_breakdown.multiplier_label == "Late night"
        assert data.payment.driver_payout == 16.75
        assert data.driver.license_plate == "EV-001"
