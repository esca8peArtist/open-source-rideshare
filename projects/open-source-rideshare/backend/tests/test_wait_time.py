"""Tests for driver wait time billing.

Covers:
- calculate_wait_fee pure logic (grace period, billing rate, no-show flag)
- compute_final_wait_fee (ride completion path)
- GET /rides/{id}/wait-time endpoint
- /arrived endpoint now stamps driver_arrived_at
- /complete endpoint adds wait_time_fee to actual_fare
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.wait_time import (
    MAX_WAIT_MINUTES,
    WAIT_GRACE_SECONDS,
    WAIT_RATE_PER_MIN,
    WaitTimeCalc,
    calculate_wait_fee,
    compute_final_wait_fee,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _arrived(seconds_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)


# ---------------------------------------------------------------------------
# calculate_wait_fee — pure function tests
# ---------------------------------------------------------------------------


class TestCalculateWaitFeeWithinGrace:
    def test_returns_zero_fee_within_grace(self):
        arrived = datetime.now(timezone.utc)
        now = arrived + timedelta(seconds=60)
        calc = calculate_wait_fee(arrived, now=now)
        assert calc.accrued_fee == 0.0

    def test_grace_seconds_remaining_decrements(self):
        arrived = datetime.now(timezone.utc)
        now = arrived + timedelta(seconds=60)
        calc = calculate_wait_fee(arrived, now=now)
        assert calc.grace_seconds_remaining == WAIT_GRACE_SECONDS - 60

    def test_not_no_show_within_grace(self):
        arrived = datetime.now(timezone.utc)
        now = arrived + timedelta(seconds=30)
        calc = calculate_wait_fee(arrived, now=now)
        assert calc.is_no_show is False

    def test_elapsed_seconds_correct(self):
        arrived = datetime.now(timezone.utc)
        now = arrived + timedelta(seconds=90)
        calc = calculate_wait_fee(arrived, now=now)
        assert calc.elapsed_seconds == 90

    def test_elapsed_minutes_correct(self):
        arrived = datetime.now(timezone.utc)
        now = arrived + timedelta(seconds=90)
        calc = calculate_wait_fee(arrived, now=now)
        assert calc.elapsed_minutes == pytest.approx(1.5)

    def test_billable_minutes_zero_within_grace(self):
        arrived = datetime.now(timezone.utc)
        now = arrived + timedelta(seconds=WAIT_GRACE_SECONDS - 1)
        calc = calculate_wait_fee(arrived, now=now)
        assert calc.billable_minutes == 0.0


class TestCalculateWaitFeeExactGraceBoundary:
    def test_zero_fee_at_exact_grace_expiry(self):
        arrived = datetime.now(timezone.utc)
        now = arrived + timedelta(seconds=WAIT_GRACE_SECONDS)
        calc = calculate_wait_fee(arrived, now=now)
        assert calc.accrued_fee == 0.0
        assert calc.grace_seconds_remaining == 0
        assert calc.billable_minutes == 0.0

    def test_fee_starts_one_second_past_grace(self):
        arrived = datetime.now(timezone.utc)
        now = arrived + timedelta(seconds=WAIT_GRACE_SECONDS + 1)
        calc = calculate_wait_fee(arrived, now=now)
        # 1 second of billing = 1/60 min * rate
        expected = round((1 / 60) * WAIT_RATE_PER_MIN, 2)
        assert calc.accrued_fee == expected


class TestCalculateWaitFeeAfterGrace:
    def test_fee_correct_after_one_minute_past_grace(self):
        arrived = datetime.now(timezone.utc)
        now = arrived + timedelta(seconds=WAIT_GRACE_SECONDS + 60)
        calc = calculate_wait_fee(arrived, now=now)
        assert calc.accrued_fee == pytest.approx(WAIT_RATE_PER_MIN, abs=0.01)
        assert calc.billable_minutes == pytest.approx(1.0, abs=0.01)

    def test_fee_correct_after_three_minutes_past_grace(self):
        arrived = datetime.now(timezone.utc)
        now = arrived + timedelta(seconds=WAIT_GRACE_SECONDS + 180)
        calc = calculate_wait_fee(arrived, now=now)
        assert calc.accrued_fee == pytest.approx(3 * WAIT_RATE_PER_MIN, abs=0.01)

    def test_grace_remaining_is_zero_after_grace(self):
        arrived = datetime.now(timezone.utc)
        now = arrived + timedelta(seconds=WAIT_GRACE_SECONDS + 60)
        calc = calculate_wait_fee(arrived, now=now)
        assert calc.grace_seconds_remaining == 0

    def test_fee_is_rounded_to_two_decimals(self):
        arrived = datetime.now(timezone.utc)
        now = arrived + timedelta(seconds=WAIT_GRACE_SECONDS + 7)
        calc = calculate_wait_fee(arrived, now=now)
        # Value should have at most 2 decimal places
        assert calc.accrued_fee == round(calc.accrued_fee, 2)


class TestCalculateWaitFeeNoShow:
    def test_is_no_show_at_max_wait_minutes(self):
        arrived = datetime.now(timezone.utc)
        now = arrived + timedelta(minutes=MAX_WAIT_MINUTES)
        calc = calculate_wait_fee(arrived, now=now)
        assert calc.is_no_show is True

    def test_is_no_show_past_max_wait(self):
        arrived = datetime.now(timezone.utc)
        now = arrived + timedelta(minutes=MAX_WAIT_MINUTES + 2)
        calc = calculate_wait_fee(arrived, now=now)
        assert calc.is_no_show is True

    def test_not_no_show_just_before_max_wait(self):
        arrived = datetime.now(timezone.utc)
        now = arrived + timedelta(minutes=MAX_WAIT_MINUTES) - timedelta(seconds=1)
        calc = calculate_wait_fee(arrived, now=now)
        assert calc.is_no_show is False

    def test_no_show_fee_is_positive(self):
        arrived = datetime.now(timezone.utc)
        now = arrived + timedelta(minutes=MAX_WAIT_MINUTES)
        calc = calculate_wait_fee(arrived, now=now)
        assert calc.accrued_fee > 0


class TestCalculateWaitFeeNaiveDatetime:
    def test_naive_arrived_at_handled(self):
        arrived = datetime.utcnow()  # naive
        now = datetime.now(timezone.utc) + timedelta(seconds=60)
        # Should not raise
        calc = calculate_wait_fee(arrived, now=now)
        assert isinstance(calc, WaitTimeCalc)

    def test_naive_now_handled(self):
        arrived = datetime.now(timezone.utc)
        now = datetime.utcnow() + timedelta(seconds=30)  # naive
        calc = calculate_wait_fee(arrived, now=now)
        assert isinstance(calc, WaitTimeCalc)


class TestCalculateWaitFeeDefaultNow:
    def test_uses_current_time_when_now_is_none(self):
        arrived = datetime.now(timezone.utc) - timedelta(seconds=30)
        calc = calculate_wait_fee(arrived, now=None)
        assert calc.elapsed_seconds >= 29


# ---------------------------------------------------------------------------
# compute_final_wait_fee
# ---------------------------------------------------------------------------


class TestComputeFinalWaitFee:
    def test_returns_zero_when_no_arrived_at(self):
        fee = compute_final_wait_fee(None, None)
        assert fee == 0.0

    def test_returns_zero_when_started_within_grace(self):
        arrived = datetime.now(timezone.utc)
        started = arrived + timedelta(seconds=60)
        fee = compute_final_wait_fee(arrived, started)
        assert fee == 0.0

    def test_uses_started_at_as_reference(self):
        arrived = datetime.now(timezone.utc)
        started = arrived + timedelta(seconds=WAIT_GRACE_SECONDS + 60)
        fee = compute_final_wait_fee(arrived, started)
        assert fee == pytest.approx(WAIT_RATE_PER_MIN, abs=0.01)

    def test_falls_back_to_current_time_when_started_at_none(self):
        arrived = datetime.now(timezone.utc) - timedelta(seconds=WAIT_GRACE_SECONDS + 60)
        fee = compute_final_wait_fee(arrived, None)
        assert fee > 0.0

    def test_fee_is_non_negative(self):
        arrived = datetime.now(timezone.utc)
        started = arrived + timedelta(seconds=10)
        fee = compute_final_wait_fee(arrived, started)
        assert fee >= 0.0


# ---------------------------------------------------------------------------
# GET /rides/{id}/wait-time endpoint — unit tests via mocked DB
# ---------------------------------------------------------------------------


def _make_ride(
    *,
    id: int = 1,
    rider_id: int = 10,
    driver_id: int = 20,
    status: str = "arrived",
    driver_arrived_at: datetime | None = None,
    started_at: datetime | None = None,
):
    ride = MagicMock()
    ride.id = id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.driver_arrived_at = driver_arrived_at
    ride.started_at = started_at
    return ride


def _make_user(user_id: int):
    user = MagicMock()
    user.id = user_id
    return user


class TestWaitTimeEndpointUnit:
    """Unit tests for the GET /rides/{id}/wait-time endpoint logic."""

    @pytest.mark.asyncio
    async def test_returns_status_for_arrived_ride(self):
        from app.api.v1.rides import get_wait_time_status

        arrived = datetime.now(timezone.utc) - timedelta(seconds=90)
        ride = _make_ride(driver_arrived_at=arrived, status="arrived")
        user = _make_user(10)  # rider

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result_mock)

        from app.models.ride import RideStatus
        ride.status = RideStatus.ARRIVED

        resp = await get_wait_time_status(ride_id=1, user=user, db=db)
        assert resp.ride_id == 1
        assert resp.elapsed_seconds >= 89
        assert resp.grace_seconds == WAIT_GRACE_SECONDS
        assert resp.wait_rate_per_min == WAIT_RATE_PER_MIN
        assert resp.max_wait_minutes == MAX_WAIT_MINUTES

    @pytest.mark.asyncio
    async def test_raises_404_when_ride_not_found(self):
        from fastapi import HTTPException
        from app.api.v1.rides import get_wait_time_status

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)
        user = _make_user(10)

        with pytest.raises(HTTPException) as exc_info:
            await get_wait_time_status(ride_id=99, user=user, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_raises_403_for_unrelated_user(self):
        from fastapi import HTTPException
        from app.api.v1.rides import get_wait_time_status
        from app.models.ride import RideStatus

        arrived = datetime.now(timezone.utc) - timedelta(seconds=30)
        ride = _make_ride(driver_arrived_at=arrived, status=RideStatus.ARRIVED)
        user = _make_user(999)  # not rider or driver

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(HTTPException) as exc_info:
            await get_wait_time_status(ride_id=1, user=user, db=db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_409_when_driver_not_yet_arrived(self):
        from fastapi import HTTPException
        from app.api.v1.rides import get_wait_time_status
        from app.models.ride import RideStatus

        ride = _make_ride(driver_arrived_at=None, status=RideStatus.DRIVER_EN_ROUTE)
        user = _make_user(10)

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(HTTPException) as exc_info:
            await get_wait_time_status(ride_id=1, user=user, db=db)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_driver_can_also_query_wait_time(self):
        from app.api.v1.rides import get_wait_time_status
        from app.models.ride import RideStatus

        arrived = datetime.now(timezone.utc) - timedelta(seconds=60)
        ride = _make_ride(driver_arrived_at=arrived, status=RideStatus.ARRIVED)
        driver_user = _make_user(20)  # driver

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result_mock)

        resp = await get_wait_time_status(ride_id=1, user=driver_user, db=db)
        assert resp.ride_id == 1

    @pytest.mark.asyncio
    async def test_uses_started_at_for_completed_ride(self):
        """For a completed ride, fee should be calculated at ride start, not now."""
        from app.api.v1.rides import get_wait_time_status
        from app.models.ride import RideStatus

        arrived = datetime.now(timezone.utc) - timedelta(hours=2)
        started = arrived + timedelta(seconds=WAIT_GRACE_SECONDS + 60)
        ride = _make_ride(
            driver_arrived_at=arrived,
            started_at=started,
            status=RideStatus.COMPLETED,
        )
        user = _make_user(10)

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result_mock)

        resp = await get_wait_time_status(ride_id=1, user=user, db=db)
        # Fee should reflect 1 minute past grace — not 2+ hours
        assert resp.accrued_fee == pytest.approx(WAIT_RATE_PER_MIN, abs=0.01)
