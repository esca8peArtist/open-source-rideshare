"""Unit tests for the ride receipt endpoint.

Tests cover:
  - GET /rides/{id}/receipt — returns receipt for a completed ride (rider)
  - GET /rides/{id}/receipt — returns receipt for a completed ride (driver)
  - GET /rides/{id}/receipt — 404 when ride does not exist
  - GET /rides/{id}/receipt — 404 when ride is not completed
  - GET /rides/{id}/receipt — 403 when user is not participant
  - Receipt totals computed correctly (subtotal, total_charged)
  - Receipt works with no payment record (platform_fee/driver_payout None)
  - Receipt works with no driver assigned
  - Requires authentication (401)
  - Schema serialises correctly
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.main import app
from app.models.ride import RideStatus
from app.schemas.ride_receipt import RideReceiptResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 18, 14, 0, 0, tzinfo=timezone.utc)
RIDER_ID = 10
DRIVER_ID = 20
RIDE_ID = 99


def _fake_ride(
    id: int = RIDE_ID,
    rider_id: int = RIDER_ID,
    driver_id: int | None = DRIVER_ID,
    status: RideStatus = RideStatus.COMPLETED,
    actual_fare: float | None = 18.50,
    estimated_fare: float = 17.00,
    promo_discount: float = 2.00,
    tip_amount: float = 3.00,
    distance_km: float | None = 12.4,
    duration_min: float | None = 22.0,
) -> MagicMock:
    r = MagicMock()
    r.id = id
    r.rider_id = rider_id
    r.driver_id = driver_id
    r.status = status
    r.requested_at = _NOW
    r.completed_at = _NOW
    r.pickup_address = "123 Main St"
    r.dropoff_address = "456 Oak Ave"
    r.distance_km = distance_km
    r.duration_min = duration_min
    r.estimated_fare = estimated_fare
    r.actual_fare = actual_fare
    r.promo_discount = promo_discount
    r.tip_amount = tip_amount
    r.promo_code_id = None
    return r


def _fake_payment(ride_id: int = RIDE_ID) -> MagicMock:
    p = MagicMock()
    p.ride_id = ride_id
    p.amount = 16.50
    p.platform_fee = 2.48
    p.driver_payout = 14.02
    p.tip_amount = 3.00
    p.status = MagicMock()
    p.status.value = "completed"
    return p


def _fake_driver_user(id: int = DRIVER_ID, name: str = "Jordan Smith") -> MagicMock:
    u = MagicMock()
    u.id = id
    u.name = name
    u.role = "driver"
    return u


def _fake_driver_profile(user_id: int = DRIVER_ID) -> MagicMock:
    p = MagicMock()
    p.user_id = user_id
    p.vehicle_make = "Toyota"
    p.vehicle_model = "Camry"
    p.vehicle_color = "Silver"
    p.vehicle_year = 2022
    p.license_plate = "ABC-1234"
    return p


def _fake_user(id: int = RIDER_ID) -> MagicMock:
    u = MagicMock()
    u.id = id
    u.role = "rider"
    return u


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestRideReceiptSchema:
    def test_serialises_full_receipt(self):
        receipt = RideReceiptResponse(
            ride_id=RIDE_ID,
            requested_at=_NOW,
            completed_at=_NOW,
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            distance_km=12.4,
            duration_min=22.0,
            estimated_fare=17.00,
            actual_fare=18.50,
            promo_discount=2.00,
            tip_amount=3.00,
            subtotal=16.50,
            total_charged=19.50,
            platform_fee=2.48,
            driver_payout=14.02,
            payment_status="completed",
            driver_name="Jordan",
            vehicle_make="Toyota",
            vehicle_model="Camry",
            vehicle_color="Silver",
            vehicle_year=2022,
            license_plate="ABC-1234",
        )
        data = receipt.model_dump()
        assert data["ride_id"] == RIDE_ID
        assert data["total_charged"] == 19.50
        assert data["driver_name"] == "Jordan"

    def test_serialises_with_nulls(self):
        receipt = RideReceiptResponse(
            ride_id=RIDE_ID,
            requested_at=_NOW,
            completed_at=_NOW,
            pickup_address="A",
            dropoff_address="B",
            distance_km=None,
            duration_min=None,
            estimated_fare=10.00,
            actual_fare=10.00,
            promo_discount=0.0,
            tip_amount=0.0,
            subtotal=10.00,
            total_charged=10.00,
            platform_fee=None,
            driver_payout=None,
            payment_status=None,
            driver_name=None,
            vehicle_make=None,
            vehicle_model=None,
            vehicle_color=None,
            vehicle_year=None,
            license_plate=None,
        )
        data = receipt.model_dump()
        assert data["platform_fee"] is None
        assert data["driver_name"] is None


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


class TestRideReceiptEndpoint:
    @pytest.mark.asyncio
    async def test_returns_receipt_for_rider(self):
        from app.api.v1.ride_receipt import get_ride_receipt

        ride = _fake_ride()
        payment = _fake_payment()
        driver_user = _fake_driver_user()
        driver_profile = _fake_driver_profile()
        rider = _fake_user(id=RIDER_ID)

        db = AsyncMock()
        # execute calls: ride, payment, driver_user, driver_profile
        results = [
            MagicMock(**{"scalar_one_or_none.return_value": ride}),
            MagicMock(**{"scalar_one_or_none.return_value": payment}),
            MagicMock(**{"scalar_one_or_none.return_value": driver_user}),
            MagicMock(**{"scalar_one_or_none.return_value": driver_profile}),
        ]
        db.execute = AsyncMock(side_effect=results)

        receipt = await get_ride_receipt(ride_id=RIDE_ID, current_user=rider, db=db)

        assert receipt.ride_id == RIDE_ID
        assert receipt.pickup_address == "123 Main St"
        assert receipt.driver_name == "Jordan"
        assert receipt.vehicle_make == "Toyota"
        assert receipt.platform_fee == payment.platform_fee

    @pytest.mark.asyncio
    async def test_returns_receipt_for_driver(self):
        from app.api.v1.ride_receipt import get_ride_receipt

        ride = _fake_ride()
        payment = _fake_payment()
        driver_user = _fake_driver_user()
        driver_profile = _fake_driver_profile()
        driver = _fake_driver_user()

        db = AsyncMock()
        results = [
            MagicMock(**{"scalar_one_or_none.return_value": ride}),
            MagicMock(**{"scalar_one_or_none.return_value": payment}),
            MagicMock(**{"scalar_one_or_none.return_value": driver_user}),
            MagicMock(**{"scalar_one_or_none.return_value": driver_profile}),
        ]
        db.execute = AsyncMock(side_effect=results)

        receipt = await get_ride_receipt(ride_id=RIDE_ID, current_user=driver, db=db)
        assert receipt.ride_id == RIDE_ID

    @pytest.mark.asyncio
    async def test_returns_404_when_ride_not_found(self):
        from fastapi import HTTPException

        from app.api.v1.ride_receipt import get_ride_receipt

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc:
            await get_ride_receipt(ride_id=999, current_user=_fake_user(), db=db)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_404_when_ride_not_completed(self):
        from fastapi import HTTPException

        from app.api.v1.ride_receipt import get_ride_receipt

        ride = _fake_ride(status=RideStatus.IN_PROGRESS)
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc:
            await get_ride_receipt(ride_id=RIDE_ID, current_user=_fake_user(), db=db)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_403_when_not_participant(self):
        from fastapi import HTTPException

        from app.api.v1.ride_receipt import get_ride_receipt

        ride = _fake_ride(rider_id=RIDER_ID, driver_id=DRIVER_ID)
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result)

        outsider = _fake_user(id=999)

        with pytest.raises(HTTPException) as exc:
            await get_ride_receipt(ride_id=RIDE_ID, current_user=outsider, db=db)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_receipt_without_payment_record(self):
        from app.api.v1.ride_receipt import get_ride_receipt

        ride = _fake_ride()
        driver_user = _fake_driver_user()
        driver_profile = _fake_driver_profile()
        rider = _fake_user(id=RIDER_ID)

        db = AsyncMock()
        results = [
            MagicMock(**{"scalar_one_or_none.return_value": ride}),
            MagicMock(**{"scalar_one_or_none.return_value": None}),   # no payment
            MagicMock(**{"scalar_one_or_none.return_value": driver_user}),
            MagicMock(**{"scalar_one_or_none.return_value": driver_profile}),
        ]
        db.execute = AsyncMock(side_effect=results)

        receipt = await get_ride_receipt(ride_id=RIDE_ID, current_user=rider, db=db)
        assert receipt.platform_fee is None
        assert receipt.driver_payout is None
        assert receipt.payment_status is None

    @pytest.mark.asyncio
    async def test_totals_computed_correctly(self):
        from app.api.v1.ride_receipt import get_ride_receipt

        ride = _fake_ride(actual_fare=18.50, promo_discount=2.00, tip_amount=3.00)
        rider = _fake_user(id=RIDER_ID)

        db = AsyncMock()
        results = [
            MagicMock(**{"scalar_one_or_none.return_value": ride}),
            MagicMock(**{"scalar_one_or_none.return_value": None}),
            MagicMock(**{"scalar_one_or_none.return_value": None}),
            MagicMock(**{"scalar_one_or_none.return_value": None}),
        ]
        db.execute = AsyncMock(side_effect=results)

        receipt = await get_ride_receipt(ride_id=RIDE_ID, current_user=rider, db=db)
        assert receipt.subtotal == pytest.approx(16.50)
        assert receipt.total_charged == pytest.approx(19.50)

    @pytest.mark.asyncio
    async def test_falls_back_to_estimated_fare_when_no_actual(self):
        from app.api.v1.ride_receipt import get_ride_receipt

        ride = _fake_ride(actual_fare=None, estimated_fare=15.00, promo_discount=0.0, tip_amount=0.0)
        rider = _fake_user(id=RIDER_ID)

        db = AsyncMock()
        results = [
            MagicMock(**{"scalar_one_or_none.return_value": ride}),
            MagicMock(**{"scalar_one_or_none.return_value": None}),
            MagicMock(**{"scalar_one_or_none.return_value": None}),
            MagicMock(**{"scalar_one_or_none.return_value": None}),
        ]
        db.execute = AsyncMock(side_effect=results)

        receipt = await get_ride_receipt(ride_id=RIDE_ID, current_user=rider, db=db)
        assert receipt.actual_fare == 15.00
        assert receipt.total_charged == 15.00

    def test_requires_auth(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get(f"/api/v1/rides/{RIDE_ID}/receipt")
        assert resp.status_code == 401
