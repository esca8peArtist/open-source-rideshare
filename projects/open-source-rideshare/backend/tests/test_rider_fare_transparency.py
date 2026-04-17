"""Tests for the rider fare transparency feature.

Service unit tests (AsyncMock DB — no live DB required):
  1.  get_fare_breakdown — raises 404 when ride not found
  2.  get_fare_breakdown — raises 404 when ride is not COMPLETED
  3.  get_fare_breakdown — raises 403 when rider requests another rider's ride
  4.  get_fare_breakdown — admin can access any rider's ride
  5.  get_fare_breakdown — uses stored platform_fee from Payment record
  6.  get_fare_breakdown — uses stored driver_payout from Payment record
  7.  get_fare_breakdown — platform_fee_is_estimated=False when Payment record present
  8.  get_fare_breakdown — falls back to OPENRIDE_PLATFORM_FEE_RATE when no Payment
  9.  get_fare_breakdown — platform_fee_is_estimated=True when no Payment record
  10. get_fare_breakdown — driver_payout estimated = base_fare * (1 - rate) + tip
  11. get_fare_breakdown — tip_usd matches ride.tip_amount
  12. get_fare_breakdown — tip excluded from platform fee base
  13. get_fare_breakdown — taxes_usd is 0.0
  14. get_fare_breakdown — taxes_pct is 0.0
  15. get_fare_breakdown — driver_payout_pct correct
  16. get_fare_breakdown — platform_fee_pct correct
  17. get_fare_breakdown — ride_id echoed in response
  18. get_fare_breakdown — total_fare from actual_fare field
  19. get_fare_breakdown — falls back to estimated_fare when actual_fare is None
  20. get_fare_breakdown — uber_comparison fee rate is ~0.265 (midpoint 25-28%)
  21. get_fare_breakdown — lyft_comparison fee rate is ~0.225 (midpoint 20-25%)
  22. get_fare_breakdown — uber estimated_platform_fee = base_fare * uber_rate
  23. get_fare_breakdown — uber estimated_driver_payout = base_fare * (1 - uber_rate)
  24. get_fare_breakdown — driver_received_more_than_uber positive when openride better
  25. get_fare_breakdown — driver_received_more_than_lyft positive when openride better
  26. get_fare_breakdown — driver_received_more_than_uber negative when uber would pay more
  27. get_fare_breakdown — transparency_note contains dollar amounts
  28. get_fare_breakdown — transparency_note mentions tip when tip > 0
  29. get_fare_breakdown — transparency_note no tip mention when tip is 0
  30. get_fare_breakdown — methodology_note present and non-empty
  31. get_fare_breakdown — openride_rate_used reflects stored fee when Payment present
  32. get_fare_breakdown — openride_rate_used is OPENRIDE_PLATFORM_FEE_RATE when estimated

API integration tests (in-transaction test DB via conftest):
  33. GET /api/v1/rides/{id}/fare-breakdown — 401 with no auth
  34. GET /api/v1/rides/{id}/fare-breakdown — 404 for non-existent ride
  35. GET /api/v1/rides/{id}/fare-breakdown — 200 for rider accessing own completed ride
  36. GET /api/v1/rides/{id}/fare-breakdown — 403 for rider accessing another rider's ride
  37. GET /api/v1/rides/{id}/fare-breakdown — 200 for admin accessing any ride
  38. GET /api/v1/rides/{id}/fare-breakdown — 404 for ride not yet COMPLETED
  39. GET /api/v1/rides/{id}/fare-breakdown — response contains all required schema fields
  40. GET /api/v1/rides/{id}/fare-breakdown — driver token returns 200 (drivers are users too)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.models.payment import Payment, PaymentStatus, PaymentType
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.services.rider_fare_transparency import (
    OPENRIDE_PLATFORM_FEE_RATE,
    _LYFT_PLATFORM_FEE_RATE,
    _UBER_PLATFORM_FEE_RATE,
    _build_competitor_comparison,
    _build_transparency_note,
    _safe_pct,
    get_fare_breakdown,
)

# ---------------------------------------------------------------------------
# Shared constants and factory helpers
# ---------------------------------------------------------------------------

RIDER_ID = 10
OTHER_RIDER_ID = 99
ADMIN_ID = 1
DRIVER_ID = 20
RIDE_ID = 42


def _make_user(user_id: int, role: UserRole) -> MagicMock:
    user = MagicMock(spec=User)
    user.id = user_id
    user.role = role
    return user


def _make_ride(
    ride_id: int = RIDE_ID,
    rider_id: int = RIDER_ID,
    driver_id: int = DRIVER_ID,
    status: RideStatus = RideStatus.COMPLETED,
    actual_fare: float | None = 20.00,
    estimated_fare: float = 18.00,
    tip_amount: float = 0.0,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.actual_fare = actual_fare
    ride.estimated_fare = estimated_fare
    ride.tip_amount = tip_amount
    ride.completed_at = datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc)
    return ride


def _make_payment(
    ride_id: int = RIDE_ID,
    amount: float = 20.00,
    platform_fee: float = 2.00,
    driver_payout: float = 18.00,
) -> MagicMock:
    payment = MagicMock(spec=Payment)
    payment.ride_id = ride_id
    payment.payment_type = PaymentType.RIDE_FARE
    payment.status = PaymentStatus.COMPLETED
    payment.amount = amount
    payment.platform_fee = platform_fee
    payment.driver_payout = driver_payout
    return payment


def _make_db_two_calls(ride: MagicMock | None, payment: MagicMock | None) -> AsyncMock:
    """Build a DB mock with two sequential execute() results:
    1. _fetch_ride   → scalar_one_or_none returning ride
    2. _fetch_payment → scalar_one_or_none returning payment
    """
    def _scalar_result(obj):
        result = MagicMock()
        result.scalar_one_or_none.return_value = obj
        return result

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(ride),
            _scalar_result(payment),
        ]
    )
    return db


# ---------------------------------------------------------------------------
# Helper / pure-function unit tests
# ---------------------------------------------------------------------------


class TestSafePct:
    def test_normal_fraction(self):
        assert _safe_pct(2.0, 20.0) == pytest.approx(10.0)

    def test_zero_total_returns_zero(self):
        assert _safe_pct(5.0, 0.0) == 0.0

    def test_full_amount(self):
        assert _safe_pct(20.0, 20.0) == pytest.approx(100.0)


class TestBuildCompetitorComparison:
    def test_uber_fee_correct(self):
        comp = _build_competitor_comparison("Uber", _UBER_PLATFORM_FEE_RATE, 20.0, "note")
        assert comp.estimated_platform_fee_usd == pytest.approx(20.0 * _UBER_PLATFORM_FEE_RATE, rel=1e-4)

    def test_uber_driver_payout_correct(self):
        comp = _build_competitor_comparison("Uber", _UBER_PLATFORM_FEE_RATE, 20.0, "note")
        assert comp.estimated_driver_payout_usd == pytest.approx(20.0 * (1 - _UBER_PLATFORM_FEE_RATE), rel=1e-4)

    def test_zero_fare_gives_zero_fee(self):
        comp = _build_competitor_comparison("Lyft", _LYFT_PLATFORM_FEE_RATE, 0.0, "note")
        assert comp.estimated_platform_fee_usd == 0.0
        assert comp.estimated_driver_payout_usd == 0.0


class TestBuildTransparencyNote:
    def test_contains_dollar_amounts(self):
        note = _build_transparency_note(20.0, 18.0, 90.0, 2.0, 10.0, 0.0, False)
        assert "$20.00" in note
        assert "$18.00" in note
        assert "$2.00" in note

    def test_tip_line_present_when_tip_nonzero(self):
        note = _build_transparency_note(25.0, 22.0, 88.0, 2.0, 8.0, 5.0, False)
        assert "$5.00 tip" in note

    def test_tip_line_absent_when_tip_zero(self):
        note = _build_transparency_note(20.0, 18.0, 90.0, 2.0, 10.0, 0.0, False)
        assert "tip" not in note.lower()

    def test_estimated_qualifier_present_when_estimated(self):
        note = _build_transparency_note(20.0, 18.0, 90.0, 2.0, 10.0, 0.0, True)
        assert "estimated" in note


# ---------------------------------------------------------------------------
# Service unit tests — get_fare_breakdown
# ---------------------------------------------------------------------------


class TestGetFareBreakdown:

    @pytest.mark.anyio
    async def test_raises_404_when_ride_not_found(self):
        db = _make_db_two_calls(None, None)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_fare_breakdown(db, RIDE_ID, user)
        assert exc_info.value.status_code == 404

    @pytest.mark.anyio
    async def test_raises_404_when_ride_not_completed(self):
        ride = _make_ride(status=RideStatus.IN_PROGRESS)
        db = _make_db_two_calls(ride, None)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_fare_breakdown(db, RIDE_ID, user)
        assert exc_info.value.status_code == 404

    @pytest.mark.anyio
    async def test_raises_403_when_rider_accesses_other_ride(self):
        ride = _make_ride(rider_id=OTHER_RIDER_ID)
        db = _make_db_two_calls(ride, None)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_fare_breakdown(db, RIDE_ID, user)
        assert exc_info.value.status_code == 403

    @pytest.mark.anyio
    async def test_admin_can_access_any_ride(self):
        ride = _make_ride(rider_id=OTHER_RIDER_ID)
        payment = _make_payment(platform_fee=2.0, driver_payout=18.0)
        db = _make_db_two_calls(ride, payment)
        admin = _make_user(ADMIN_ID, UserRole.ADMIN)
        result = await get_fare_breakdown(db, RIDE_ID, admin)
        assert result.ride_id == RIDE_ID

    @pytest.mark.anyio
    async def test_uses_stored_platform_fee_from_payment(self):
        ride = _make_ride(actual_fare=20.0, tip_amount=0.0)
        payment = _make_payment(platform_fee=3.00, driver_payout=17.00)
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert result.platform_fee_usd == pytest.approx(3.00, rel=1e-4)

    @pytest.mark.anyio
    async def test_uses_stored_driver_payout_from_payment(self):
        ride = _make_ride(actual_fare=20.0, tip_amount=0.0)
        payment = _make_payment(platform_fee=2.50, driver_payout=17.50)
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert result.driver_payout_usd == pytest.approx(17.50, rel=1e-4)

    @pytest.mark.anyio
    async def test_platform_fee_is_estimated_false_when_payment_present(self):
        ride = _make_ride()
        payment = _make_payment()
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert result.platform_fee_is_estimated is False

    @pytest.mark.anyio
    async def test_falls_back_to_rate_constant_when_no_payment(self):
        ride = _make_ride(actual_fare=20.0, tip_amount=0.0)
        db = _make_db_two_calls(ride, None)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        expected_fee = round(20.0 * OPENRIDE_PLATFORM_FEE_RATE, 2)
        assert result.platform_fee_usd == pytest.approx(expected_fee, rel=1e-4)

    @pytest.mark.anyio
    async def test_platform_fee_is_estimated_true_when_no_payment(self):
        ride = _make_ride()
        db = _make_db_two_calls(ride, None)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert result.platform_fee_is_estimated is True

    @pytest.mark.anyio
    async def test_estimated_driver_payout_equals_base_minus_fee_plus_tip(self):
        tip = 3.00
        fare = 20.00
        base = fare - tip  # 17.00
        ride = _make_ride(actual_fare=fare, tip_amount=tip)
        db = _make_db_two_calls(ride, None)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        expected_fee = round(base * OPENRIDE_PLATFORM_FEE_RATE, 2)
        expected_driver = round(base - expected_fee + tip, 2)
        assert result.driver_payout_usd == pytest.approx(expected_driver, rel=1e-4)

    @pytest.mark.anyio
    async def test_tip_usd_matches_ride_tip_amount(self):
        ride = _make_ride(actual_fare=20.0, tip_amount=4.00)
        payment = _make_payment(platform_fee=1.60, driver_payout=18.40)
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert result.tip_usd == pytest.approx(4.00, rel=1e-4)

    @pytest.mark.anyio
    async def test_tip_excluded_from_platform_fee_base(self):
        # Fare = $20 total, tip = $5; platform fee should be on base $15 only.
        tip = 5.00
        fare = 20.00
        base = fare - tip
        ride = _make_ride(actual_fare=fare, tip_amount=tip)
        db = _make_db_two_calls(ride, None)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        expected_fee = round(base * OPENRIDE_PLATFORM_FEE_RATE, 2)
        assert result.platform_fee_usd == pytest.approx(expected_fee, rel=1e-4)

    @pytest.mark.anyio
    async def test_taxes_usd_is_zero(self):
        ride = _make_ride()
        payment = _make_payment()
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert result.taxes_usd == 0.0

    @pytest.mark.anyio
    async def test_taxes_pct_is_zero(self):
        ride = _make_ride()
        payment = _make_payment()
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert result.taxes_pct == 0.0

    @pytest.mark.anyio
    async def test_driver_payout_pct_correct(self):
        fare = 20.0
        driver_payout = 18.0
        ride = _make_ride(actual_fare=fare, tip_amount=0.0)
        payment = _make_payment(platform_fee=2.0, driver_payout=driver_payout)
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        expected_pct = round((driver_payout / fare) * 100, 2)
        assert result.driver_payout_pct == pytest.approx(expected_pct, rel=1e-3)

    @pytest.mark.anyio
    async def test_platform_fee_pct_correct(self):
        fare = 20.0
        platform_fee = 2.0
        ride = _make_ride(actual_fare=fare, tip_amount=0.0)
        payment = _make_payment(platform_fee=platform_fee, driver_payout=18.0)
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        expected_pct = round((platform_fee / fare) * 100, 2)
        assert result.platform_fee_pct == pytest.approx(expected_pct, rel=1e-3)

    @pytest.mark.anyio
    async def test_ride_id_echoed(self):
        ride = _make_ride(ride_id=55)
        payment = _make_payment(ride_id=55)
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, 55, user)
        assert result.ride_id == 55

    @pytest.mark.anyio
    async def test_total_fare_from_actual_fare(self):
        ride = _make_ride(actual_fare=22.50)
        payment = _make_payment(amount=22.50, platform_fee=2.25, driver_payout=20.25)
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert result.total_fare_usd == pytest.approx(22.50, rel=1e-4)

    @pytest.mark.anyio
    async def test_falls_back_to_estimated_fare_when_actual_none(self):
        ride = _make_ride(actual_fare=None, estimated_fare=18.00)
        db = _make_db_two_calls(ride, None)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert result.total_fare_usd == pytest.approx(18.00, rel=1e-4)

    @pytest.mark.anyio
    async def test_uber_comparison_fee_rate_is_midpoint(self):
        ride = _make_ride()
        payment = _make_payment()
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert result.uber_comparison.platform_fee_rate == pytest.approx(_UBER_PLATFORM_FEE_RATE, rel=1e-4)

    @pytest.mark.anyio
    async def test_lyft_comparison_fee_rate_is_midpoint(self):
        ride = _make_ride()
        payment = _make_payment()
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert result.lyft_comparison.platform_fee_rate == pytest.approx(_LYFT_PLATFORM_FEE_RATE, rel=1e-4)

    @pytest.mark.anyio
    async def test_uber_estimated_platform_fee_correct(self):
        fare = 20.0
        tip = 0.0
        base = fare - tip
        ride = _make_ride(actual_fare=fare, tip_amount=tip)
        payment = _make_payment()
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        expected = round(base * _UBER_PLATFORM_FEE_RATE, 2)
        assert result.uber_comparison.estimated_platform_fee_usd == pytest.approx(expected, rel=1e-4)

    @pytest.mark.anyio
    async def test_uber_estimated_driver_payout_correct(self):
        fare = 20.0
        tip = 0.0
        base = fare - tip
        ride = _make_ride(actual_fare=fare, tip_amount=tip)
        payment = _make_payment()
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        expected = round(base * (1.0 - _UBER_PLATFORM_FEE_RATE), 2)
        assert result.uber_comparison.estimated_driver_payout_usd == pytest.approx(expected, rel=1e-4)

    @pytest.mark.anyio
    async def test_driver_received_more_than_uber_positive_when_openride_better(self):
        # OpenRide driver payout = $18 on $20 fare (90% take)
        # Uber would give ~73.5% → ~$14.70 on $20
        ride = _make_ride(actual_fare=20.0, tip_amount=0.0)
        payment = _make_payment(platform_fee=2.0, driver_payout=18.0)
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert result.driver_received_more_than_uber_usd > 0

    @pytest.mark.anyio
    async def test_driver_received_more_than_lyft_positive_when_openride_better(self):
        ride = _make_ride(actual_fare=20.0, tip_amount=0.0)
        payment = _make_payment(platform_fee=2.0, driver_payout=18.0)
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert result.driver_received_more_than_lyft_usd > 0

    @pytest.mark.anyio
    async def test_driver_received_more_than_uber_negative_when_uber_better(self):
        # OpenRide driver payout = $1 (tiny fee for testing)
        ride = _make_ride(actual_fare=20.0, tip_amount=0.0)
        payment = _make_payment(platform_fee=19.0, driver_payout=1.0)
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert result.driver_received_more_than_uber_usd < 0

    @pytest.mark.anyio
    async def test_transparency_note_contains_dollar_amounts(self):
        ride = _make_ride(actual_fare=20.0, tip_amount=0.0)
        payment = _make_payment(platform_fee=2.0, driver_payout=18.0)
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert "$20.00" in result.transparency_note
        assert "$18.00" in result.transparency_note

    @pytest.mark.anyio
    async def test_transparency_note_mentions_tip(self):
        ride = _make_ride(actual_fare=25.0, tip_amount=5.0)
        payment = _make_payment(platform_fee=2.0, driver_payout=23.0)
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert "tip" in result.transparency_note.lower()

    @pytest.mark.anyio
    async def test_transparency_note_no_tip_mention_when_zero(self):
        ride = _make_ride(actual_fare=20.0, tip_amount=0.0)
        payment = _make_payment(platform_fee=2.0, driver_payout=18.0)
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert "tip" not in result.transparency_note.lower()

    @pytest.mark.anyio
    async def test_methodology_note_present_and_non_empty(self):
        ride = _make_ride()
        payment = _make_payment()
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert len(result.methodology_note) > 20

    @pytest.mark.anyio
    async def test_openride_rate_used_reflects_stored_payment(self):
        # platform_fee = 2.00, base = 20.00, so rate = 0.10
        ride = _make_ride(actual_fare=20.0, tip_amount=0.0)
        payment = _make_payment(platform_fee=2.0, driver_payout=18.0)
        db = _make_db_two_calls(ride, payment)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert result.openride_platform_fee_rate_used == pytest.approx(0.10, rel=1e-4)

    @pytest.mark.anyio
    async def test_openride_rate_used_is_constant_when_estimated(self):
        ride = _make_ride()
        db = _make_db_two_calls(ride, None)
        user = _make_user(RIDER_ID, UserRole.RIDER)
        result = await get_fare_breakdown(db, RIDE_ID, user)
        assert result.openride_platform_fee_rate_used == pytest.approx(
            OPENRIDE_PLATFORM_FEE_RATE, rel=1e-4
        )


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def rider2(db):
    """A second rider used to test cross-rider access denial."""
    from app.models.user import User, UserRole
    from app.services.auth import hash_password
    user = User(
        phone="+15551111111",
        name="Second Rider",
        email="rider2@test.com",
        password_hash=hash_password("testpass123"),
        role=UserRole.RIDER,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
def rider2_token(rider2):
    from app.services.auth import create_access_token
    return create_access_token(rider2.id, rider2.role.value)


@pytest.fixture
async def completed_ride(db, rider, driver_user):
    """A completed ride owned by the `rider` fixture user."""
    from sqlalchemy import text
    # Insert a minimal geometry for pickup/dropoff
    ride = Ride(
        rider_id=rider.id,
        driver_id=driver_user.id,
        status=RideStatus.COMPLETED,
        pickup_address="123 Main St",
        dropoff_address="456 Oak Ave",
        estimated_fare=15.00,
        actual_fare=16.50,
        distance_km=8.0,
        duration_min=12.0,
        tip_amount=0.0,
    )
    # Minimal PostGIS point values
    from geoalchemy2.elements import WKTElement
    ride.pickup_location = WKTElement("POINT(-122.4 37.7)", srid=4326)
    ride.dropoff_location = WKTElement("POINT(-122.5 37.8)", srid=4326)
    db.add(ride)
    await db.flush()
    return ride


@pytest.fixture
async def completed_ride_with_payment(db, completed_ride):
    """A completed ride that also has a completed Payment record."""
    payment = Payment(
        ride_id=completed_ride.id,
        payment_type=PaymentType.RIDE_FARE,
        amount=16.50,
        platform_fee=1.65,
        driver_payout=14.85,
        status=PaymentStatus.COMPLETED,
    )
    db.add(payment)
    await db.flush()
    return completed_ride


@pytest.mark.anyio
async def test_api_fare_breakdown_no_auth(client):
    resp = await client.get("/api/v1/rides/999/fare-breakdown")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_api_fare_breakdown_not_found(client, rider_token):
    resp = await client.get(
        "/api/v1/rides/999999/fare-breakdown",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_api_fare_breakdown_rider_own_ride_ok(client, rider_token, completed_ride_with_payment):
    resp = await client.get(
        f"/api/v1/rides/{completed_ride_with_payment.id}/fare-breakdown",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_api_fare_breakdown_rider_other_ride_forbidden(
    client, rider2_token, completed_ride_with_payment
):
    resp = await client.get(
        f"/api/v1/rides/{completed_ride_with_payment.id}/fare-breakdown",
        headers={"Authorization": f"Bearer {rider2_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_api_fare_breakdown_admin_any_ride_ok(client, admin_token, completed_ride_with_payment):
    resp = await client.get(
        f"/api/v1/rides/{completed_ride_with_payment.id}/fare-breakdown",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_api_fare_breakdown_incomplete_ride_404(client, rider_token, db, rider, driver_user):
    """A ride that is not COMPLETED should return 404."""
    from geoalchemy2.elements import WKTElement
    ride = Ride(
        rider_id=rider.id,
        driver_id=driver_user.id,
        status=RideStatus.IN_PROGRESS,
        pickup_address="1 Start St",
        dropoff_address="1 End St",
        estimated_fare=12.00,
        actual_fare=None,
        tip_amount=0.0,
    )
    ride.pickup_location = WKTElement("POINT(-122.4 37.7)", srid=4326)
    ride.dropoff_location = WKTElement("POINT(-122.5 37.8)", srid=4326)
    db.add(ride)
    await db.flush()

    resp = await client.get(
        f"/api/v1/rides/{ride.id}/fare-breakdown",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_api_fare_breakdown_schema_fields(client, rider_token, completed_ride_with_payment):
    resp = await client.get(
        f"/api/v1/rides/{completed_ride_with_payment.id}/fare-breakdown",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    required_fields = {
        "ride_id",
        "total_fare_usd",
        "driver_payout_usd",
        "driver_payout_pct",
        "platform_fee_usd",
        "platform_fee_pct",
        "tip_usd",
        "taxes_usd",
        "taxes_pct",
        "platform_fee_is_estimated",
        "openride_platform_fee_rate_used",
        "uber_comparison",
        "lyft_comparison",
        "driver_received_more_than_uber_usd",
        "driver_received_more_than_lyft_usd",
        "transparency_note",
        "methodology_note",
    }
    for field in required_fields:
        assert field in body, f"Missing field: {field}"


@pytest.mark.anyio
async def test_api_fare_breakdown_driver_token_ok(client, driver_token, completed_ride_with_payment):
    """Drivers are users too; if they somehow request this endpoint, it should
    return 403 (not their ride) rather than 401 — they are authenticated."""
    resp = await client.get(
        f"/api/v1/rides/{completed_ride_with_payment.id}/fare-breakdown",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    # Driver is not the rider on this ride, so 403 is the correct response.
    assert resp.status_code == 403
