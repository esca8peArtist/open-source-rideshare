"""Unit tests for surge price lock feature.

All tests are pure unit tests — no database, no Redis, no HTTP client required.

Covers:
- SurgePriceLock model field defaults and lifecycle
- is_lock_active: active, expired, used, cancelled
- seconds_remaining: active, at-expiry, past-expiry
- build_response: correct field mapping
- create_lock service function (mocked DB)
- get_active_lock service function (mocked DB)
- cancel_lock service function (mocked DB)
- consume_lock service function (mocked DB)
- Schema validation (SurgePriceLockRequest, SurgePriceLockResponse)
- create_lock replaces an existing active lock
- consume_lock sets used_at and ride_id
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.surge_price_lock import SurgePriceLock
from app.schemas.surge_price_lock import (
    SurgePriceLockCancelResponse,
    SurgePriceLockRequest,
    SurgePriceLockResponse,
)
from app.services.surge_price_lock import (
    LOCK_DURATION_MINUTES,
    build_response,
    cancel_lock,
    consume_lock,
    create_lock,
    get_active_lock,
    is_lock_active,
    seconds_remaining,
)


# ===========================================================================
# Helpers
# ===========================================================================

_NOW = datetime(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc)
_EXPIRES = _NOW + timedelta(minutes=LOCK_DURATION_MINUTES)


def _make_lock(
    *,
    id: int = 1,
    rider_id: int = 42,
    pickup_lat: float = 37.7749,
    pickup_lon: float = -122.4194,
    pickup_address: str | None = "123 Main St",
    locked_multiplier: float = 1.8,
    locked_at: datetime = _NOW,
    expires_at: datetime = _EXPIRES,
    used_at: datetime | None = None,
    ride_id: int | None = None,
    cancelled_at: datetime | None = None,
) -> SurgePriceLock:
    lock = SurgePriceLock()
    lock.id = id
    lock.rider_id = rider_id
    lock.pickup_lat = pickup_lat
    lock.pickup_lon = pickup_lon
    lock.pickup_address = pickup_address
    lock.locked_multiplier = locked_multiplier
    lock.locked_at = locked_at
    lock.expires_at = expires_at
    lock.used_at = used_at
    lock.ride_id = ride_id
    lock.cancelled_at = cancelled_at
    return lock


# ===========================================================================
# is_lock_active
# ===========================================================================


class TestIsLockActive:
    def test_active_lock_returns_true(self):
        lock = _make_lock()
        now = _NOW + timedelta(minutes=1)
        assert is_lock_active(lock, now=now) is True

    def test_expired_lock_returns_false(self):
        lock = _make_lock()
        now = _EXPIRES + timedelta(seconds=1)
        assert is_lock_active(lock, now=now) is False

    def test_exactly_at_expiry_is_inactive(self):
        lock = _make_lock()
        assert is_lock_active(lock, now=_EXPIRES) is False

    def test_used_lock_returns_false(self):
        lock = _make_lock(used_at=_NOW + timedelta(minutes=1))
        assert is_lock_active(lock, now=_NOW + timedelta(minutes=2)) is False

    def test_cancelled_lock_returns_false(self):
        lock = _make_lock(cancelled_at=_NOW + timedelta(seconds=30))
        assert is_lock_active(lock, now=_NOW + timedelta(minutes=1)) is False

    def test_naive_now_treated_as_utc(self):
        lock = _make_lock()
        naive_now = _NOW.replace(tzinfo=None) + timedelta(minutes=1)
        # Should not raise; naive datetime handled gracefully.
        result = is_lock_active(lock, now=naive_now)
        assert result is True

    def test_naive_expires_at_treated_as_utc(self):
        lock = _make_lock(expires_at=_EXPIRES.replace(tzinfo=None))
        now = _NOW + timedelta(minutes=1)
        result = is_lock_active(lock, now=now)
        assert result is True


# ===========================================================================
# seconds_remaining
# ===========================================================================


class TestSecondsRemaining:
    def test_full_window_at_creation(self):
        lock = _make_lock()
        secs = seconds_remaining(lock, now=_NOW)
        assert secs == LOCK_DURATION_MINUTES * 60

    def test_one_minute_elapsed(self):
        lock = _make_lock()
        now = _NOW + timedelta(minutes=1)
        secs = seconds_remaining(lock, now=now)
        assert secs == (LOCK_DURATION_MINUTES - 1) * 60

    def test_past_expiry_returns_zero(self):
        lock = _make_lock()
        now = _EXPIRES + timedelta(minutes=1)
        assert seconds_remaining(lock, now=now) == 0

    def test_exactly_at_expiry_returns_zero(self):
        lock = _make_lock()
        assert seconds_remaining(lock, now=_EXPIRES) == 0

    def test_naive_expires_at(self):
        lock = _make_lock(expires_at=_EXPIRES.replace(tzinfo=None))
        secs = seconds_remaining(lock, now=_NOW)
        assert secs == LOCK_DURATION_MINUTES * 60


# ===========================================================================
# build_response
# ===========================================================================


class TestBuildResponse:
    def test_active_lock_response_fields(self):
        lock = _make_lock()
        now = _NOW + timedelta(minutes=1)
        resp = build_response(lock, now=now)

        assert isinstance(resp, SurgePriceLockResponse)
        assert resp.id == 1
        assert resp.rider_id == 42
        assert resp.pickup_lat == 37.7749
        assert resp.pickup_lon == -122.4194
        assert resp.pickup_address == "123 Main St"
        assert resp.locked_multiplier == 1.8
        assert resp.locked_at == _NOW
        assert resp.expires_at == _EXPIRES
        assert resp.seconds_remaining == (LOCK_DURATION_MINUTES - 1) * 60
        assert resp.is_active is True
        assert resp.used_at is None
        assert resp.cancelled_at is None

    def test_expired_lock_is_not_active(self):
        lock = _make_lock()
        now = _EXPIRES + timedelta(seconds=60)
        resp = build_response(lock, now=now)
        assert resp.is_active is False
        assert resp.seconds_remaining == 0

    def test_used_lock_fields(self):
        used_at = _NOW + timedelta(minutes=2)
        lock = _make_lock(used_at=used_at, ride_id=99)
        resp = build_response(lock, now=_NOW + timedelta(minutes=3))
        assert resp.is_active is False
        assert resp.used_at == used_at

    def test_cancelled_lock_fields(self):
        cancelled_at = _NOW + timedelta(seconds=45)
        lock = _make_lock(cancelled_at=cancelled_at)
        resp = build_response(lock, now=_NOW + timedelta(minutes=1))
        assert resp.is_active is False
        assert resp.cancelled_at == cancelled_at

    def test_no_address(self):
        lock = _make_lock(pickup_address=None)
        resp = build_response(lock, now=_NOW)
        assert resp.pickup_address is None

    def test_multiplier_1_0_no_surge(self):
        lock = _make_lock(locked_multiplier=1.0)
        resp = build_response(lock, now=_NOW)
        assert resp.locked_multiplier == 1.0


# ===========================================================================
# Schema validation
# ===========================================================================


class TestSurgePriceLockRequestSchema:
    def test_valid_request(self):
        req = SurgePriceLockRequest(
            pickup_lat=37.7749,
            pickup_lon=-122.4194,
            pickup_address="123 Main St",
        )
        assert req.pickup_lat == 37.7749
        assert req.pickup_lon == -122.4194

    def test_optional_address(self):
        req = SurgePriceLockRequest(pickup_lat=0.0, pickup_lon=0.0)
        assert req.pickup_address is None

    def test_invalid_lat_too_high(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            SurgePriceLockRequest(pickup_lat=91.0, pickup_lon=0.0)

    def test_invalid_lat_too_low(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            SurgePriceLockRequest(pickup_lat=-91.0, pickup_lon=0.0)

    def test_invalid_lon_too_high(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            SurgePriceLockRequest(pickup_lat=0.0, pickup_lon=181.0)

    def test_invalid_lon_too_low(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            SurgePriceLockRequest(pickup_lat=0.0, pickup_lon=-181.0)


class TestSurgePriceLockCancelResponse:
    def test_cancel_response(self):
        resp = SurgePriceLockCancelResponse(
            cancelled=True, message="Surge price lock cancelled successfully."
        )
        assert resp.cancelled is True
        assert "cancelled" in resp.message.lower()


# ===========================================================================
# Async service functions (mocked DB)
# ===========================================================================


def _mock_db(scalar_result=None):
    """Build a minimal AsyncSession mock for service tests."""
    db = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = scalar_result
    db.execute.return_value = execute_result
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


class TestGetActiveLock:
    @pytest.mark.asyncio
    async def test_returns_lock_when_found(self):
        lock = _make_lock()
        db = _mock_db(scalar_result=lock)
        result = await get_active_lock(db, rider_id=42)
        assert result is lock

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        db = _mock_db(scalar_result=None)
        result = await get_active_lock(db, rider_id=42)
        assert result is None


class TestCreateLock:
    @pytest.mark.asyncio
    async def test_creates_lock_no_existing(self):
        db = _mock_db(scalar_result=None)

        async def fake_refresh(obj):
            obj.id = 1
            obj.locked_at = _NOW
            obj.expires_at = _EXPIRES

        db.refresh = fake_refresh

        lock = await create_lock(
            db,
            rider_id=42,
            pickup_lat=37.7749,
            pickup_lon=-122.4194,
            pickup_address="123 Main St",
            multiplier=1.8,
            now=_NOW,
        )

        assert lock.rider_id == 42
        assert lock.locked_multiplier == 1.8
        assert lock.expires_at == _EXPIRES
        assert lock.used_at is None
        assert lock.cancelled_at is None
        db.add.assert_called()
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_cancels_existing_lock_before_creating_new(self):
        existing = _make_lock(rider_id=42)
        # First call returns existing lock; subsequent get_active_lock returns None
        call_count = 0

        async def fake_execute(*args, **kwargs):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = existing
            else:
                result.scalar_one_or_none.return_value = None
            call_count += 1
            return result

        db = AsyncMock()
        db.execute = fake_execute
        db.commit = AsyncMock()

        async def fake_refresh(obj):
            obj.id = 2
            obj.locked_at = _NOW
            obj.expires_at = _EXPIRES

        db.refresh = fake_refresh
        db.add = MagicMock()

        new_lock = await create_lock(
            db,
            rider_id=42,
            pickup_lat=40.0,
            pickup_lon=-74.0,
            pickup_address="New Location",
            multiplier=2.1,
            now=_NOW,
        )

        # The existing lock must have been cancelled.
        assert existing.cancelled_at == _NOW
        assert new_lock.locked_multiplier == 2.1

    @pytest.mark.asyncio
    async def test_lock_duration_applied(self):
        db = _mock_db(scalar_result=None)

        async def fake_refresh(obj):
            pass

        db.refresh = fake_refresh

        lock = await create_lock(
            db,
            rider_id=1,
            pickup_lat=0.0,
            pickup_lon=0.0,
            pickup_address=None,
            multiplier=1.5,
            now=_NOW,
        )

        expected_expiry = _NOW + timedelta(minutes=LOCK_DURATION_MINUTES)
        assert lock.expires_at == expected_expiry


class TestCancelLock:
    @pytest.mark.asyncio
    async def test_cancels_active_lock(self):
        lock = _make_lock()
        db = _mock_db(scalar_result=lock)

        result = await cancel_lock(db, rider_id=42)

        assert result is True
        assert lock.cancelled_at is not None
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_returns_false_when_no_active_lock(self):
        db = _mock_db(scalar_result=None)

        result = await cancel_lock(db, rider_id=42)

        assert result is False
        db.commit.assert_not_awaited()


class TestConsumeLock:
    @pytest.mark.asyncio
    async def test_sets_used_at_and_ride_id(self):
        lock = _make_lock()
        db = AsyncMock()
        db.add = MagicMock()

        await consume_lock(db, lock, ride_id=77)

        assert lock.used_at is not None
        assert lock.ride_id == 77
        db.add.assert_called_once_with(lock)
        # Caller is responsible for committing — consume_lock does NOT commit.
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_used_at_is_utc(self):
        lock = _make_lock()
        db = AsyncMock()
        db.add = MagicMock()

        await consume_lock(db, lock, ride_id=1)

        assert lock.used_at.tzinfo is not None


# ===========================================================================
# Policy constant
# ===========================================================================


class TestPolicyConstants:
    def test_lock_duration_is_positive(self):
        assert LOCK_DURATION_MINUTES > 0

    def test_lock_duration_value(self):
        # 5-minute lock window is the stated product decision.
        assert LOCK_DURATION_MINUTES == 5
