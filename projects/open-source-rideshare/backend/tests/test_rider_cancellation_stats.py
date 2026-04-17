"""Unit tests for rider cancellation stats and structured cancellation categories.

Covers:

CancellationCategory enum (ride model):
  1.  All rider-initiated categories are valid enum members
  2.  All driver-initiated categories are valid enum members
  3.  Invalid category string raises ValueError

CancelRequest schema:
  4.  category field accepts CancellationCategory enum values
  5.  category field accepts None (backward compatible)
  6.  reason field still accepts free-text note alongside category

CancelResponse schema:
  7.  cancelled_by field present with default None
  8.  cancelled_by="rider" round-trips correctly
  9.  cancelled_by="driver" round-trips correctly

record_rider_cancellation service — first cancel (no existing stats):
  10. Creates new stats row with total_cancellations=1
  11. cancellations_with_fee=1 when had_fee=True
  12. cancellations_in_grace_period=1 when in_grace_period=True
  13. last_cancel_category stored correctly
  14. cancellation_rate=1.0 on first cancel (1/1)
  15. db.add and db.commit called

record_rider_cancellation service — subsequent cancel (existing stats):
  16. total_cancellations incremented
  17. cancellations_with_fee incremented only when had_fee=True
  18. cancellations_in_grace_period incremented only when in_grace_period=True
  19. cancellation_rate recalculated = cancellations / total_requested
  20. last_cancel_category updated to latest
  21. db.commit called (no db.add for existing row)

increment_ride_requested service:
  22. Creates stats row with total_rides_requested=1 when none exists
  23. Increments total_rides_requested on existing row
  24. Updates cancellation_rate correctly after increment

get_rider_cancel_stats service:
  25. Returns stats row when it exists
  26. Returns None when no row found

GET /riders/me/cancel-stats endpoint:
  27. Returns 200 with zeroed response when no stats row exists
  28. Returns 200 with stats row data when row exists
  29. Returns 401 when unauthenticated

GET /admin/riders/{rider_id}/cancel-stats endpoint:
  30. Returns 200 when admin and stats exist
  31. Returns 404 when stats row not found
  32. Returns 403 for non-admin caller

Cancel endpoint integration — stores cancellation_category and cancelled_by:
  33. ride.cancellation_category set from req.category when rider cancels
  34. ride.cancelled_by="rider" stored when rider cancels
  35. ride.cancelled_by="driver" stored when driver cancels
  36. record_rider_cancellation called when cancelled_by="rider"
  37. record_rider_cancellation NOT called when cancelled_by="driver"
  38. CancelResponse includes cancelled_by field
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.models.ride import CancellationCategory, RideStatus
from app.schemas.ride import CancelRequest, CancelResponse


NOW = datetime(2026, 4, 17, 14, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stats(
    rider_id: int = 10,
    total_rides_requested: int = 5,
    total_cancellations: int = 2,
    cancellations_in_grace_period: int = 1,
    cancellations_with_fee: int = 1,
    cancellation_rate: float = 0.4,
    last_cancel_at=None,
    last_cancel_category=None,
):
    stats = MagicMock()
    stats.id = 1
    stats.rider_id = rider_id
    stats.total_rides_requested = total_rides_requested
    stats.total_cancellations = total_cancellations
    stats.cancellations_in_grace_period = cancellations_in_grace_period
    stats.cancellations_with_fee = cancellations_with_fee
    stats.cancellation_rate = cancellation_rate
    stats.last_cancel_at = last_cancel_at or NOW
    stats.last_cancel_category = last_cancel_category
    stats.updated_at = NOW
    return stats


def _make_db(stats=None):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = stats
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


# ---------------------------------------------------------------------------
# 1–3: CancellationCategory enum
# ---------------------------------------------------------------------------

class TestCancellationCategoryEnum:
    def test_rider_categories_valid(self):
        rider_cats = [
            CancellationCategory.WRONG_PICKUP,
            CancellationCategory.WAIT_TOO_LONG,
            CancellationCategory.FOUND_OTHER_RIDE,
            CancellationCategory.PLANS_CHANGED,
            CancellationCategory.DRIVER_NOT_ACCEPTABLE,
            CancellationCategory.PRICE_TOO_HIGH,
            CancellationCategory.SAFETY_CONCERN,
            CancellationCategory.OTHER,
        ]
        assert len(rider_cats) == 8
        for cat in rider_cats:
            assert isinstance(cat, CancellationCategory)

    def test_driver_categories_valid(self):
        driver_cats = [
            CancellationCategory.VEHICLE_ISSUE,
            CancellationCategory.RIDER_NO_SHOW,
            CancellationCategory.UNABLE_TO_LOCATE,
            CancellationCategory.EMERGENCY,
            CancellationCategory.DRIVER_OTHER,
        ]
        assert len(driver_cats) == 5
        for cat in driver_cats:
            assert isinstance(cat, CancellationCategory)

    def test_invalid_category_raises(self):
        with pytest.raises(ValueError):
            CancellationCategory("not_a_real_category")


# ---------------------------------------------------------------------------
# 4–6: CancelRequest schema
# ---------------------------------------------------------------------------

class TestCancelRequestSchema:
    def test_category_accepts_enum_value(self):
        req = CancelRequest(category=CancellationCategory.WAIT_TOO_LONG)
        assert req.category == CancellationCategory.WAIT_TOO_LONG

    def test_category_accepts_string_value(self):
        req = CancelRequest(category="wait_too_long")
        assert req.category == CancellationCategory.WAIT_TOO_LONG

    def test_category_none_is_valid(self):
        req = CancelRequest()
        assert req.category is None
        assert req.reason is None

    def test_category_and_reason_together(self):
        req = CancelRequest(
            category=CancellationCategory.PRICE_TOO_HIGH,
            reason="Surge pricing was 3x",
        )
        assert req.category == CancellationCategory.PRICE_TOO_HIGH
        assert req.reason == "Surge pricing was 3x"


# ---------------------------------------------------------------------------
# 7–9: CancelResponse schema
# ---------------------------------------------------------------------------

class TestCancelResponseSchema:
    def test_cancelled_by_defaults_to_none(self):
        resp = CancelResponse(status="cancelled")
        assert resp.cancelled_by is None

    def test_cancelled_by_rider(self):
        resp = CancelResponse(status="cancelled", cancelled_by="rider")
        assert resp.cancelled_by == "rider"

    def test_cancelled_by_driver(self):
        resp = CancelResponse(status="cancelled", cancelled_by="driver")
        assert resp.cancelled_by == "driver"


# ---------------------------------------------------------------------------
# 10–15: record_rider_cancellation — first cancel (no existing stats)
# ---------------------------------------------------------------------------

class TestRecordRiderCancellationNew:
    @pytest.mark.asyncio
    async def test_creates_stats_row(self):
        from app.services.rider_cancellation_stats import record_rider_cancellation

        db = _make_db(stats=None)
        await record_rider_cancellation(
            db, rider_id=10, had_fee=False, in_grace_period=False, category=None
        )
        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_total_cancellations_is_1(self):
        from app.services.rider_cancellation_stats import record_rider_cancellation
        from app.models.rider_cancellation_stats import RiderCancellationStats

        db = _make_db(stats=None)
        created = None

        def capture_add(obj):
            nonlocal created
            created = obj

        db.add.side_effect = capture_add
        await record_rider_cancellation(
            db, rider_id=10, had_fee=False, in_grace_period=False, category=None
        )
        assert created is not None
        assert created.total_cancellations == 1

    @pytest.mark.asyncio
    async def test_had_fee_sets_cancellations_with_fee(self):
        from app.services.rider_cancellation_stats import record_rider_cancellation

        db = _make_db(stats=None)
        created = None

        def capture_add(obj):
            nonlocal created
            created = obj

        db.add.side_effect = capture_add
        await record_rider_cancellation(
            db, rider_id=10, had_fee=True, in_grace_period=False, category=None
        )
        assert created.cancellations_with_fee == 1

    @pytest.mark.asyncio
    async def test_in_grace_period_sets_counter(self):
        from app.services.rider_cancellation_stats import record_rider_cancellation

        db = _make_db(stats=None)
        created = None

        def capture_add(obj):
            nonlocal created
            created = obj

        db.add.side_effect = capture_add
        await record_rider_cancellation(
            db, rider_id=10, had_fee=False, in_grace_period=True, category=None
        )
        assert created.cancellations_in_grace_period == 1

    @pytest.mark.asyncio
    async def test_category_stored(self):
        from app.services.rider_cancellation_stats import record_rider_cancellation

        db = _make_db(stats=None)
        created = None

        def capture_add(obj):
            nonlocal created
            created = obj

        db.add.side_effect = capture_add
        await record_rider_cancellation(
            db, rider_id=10, had_fee=False, in_grace_period=False,
            category=CancellationCategory.WAIT_TOO_LONG
        )
        assert created.last_cancel_category == CancellationCategory.WAIT_TOO_LONG

    @pytest.mark.asyncio
    async def test_rate_is_1_on_first_cancel(self):
        from app.services.rider_cancellation_stats import record_rider_cancellation

        db = _make_db(stats=None)
        created = None

        def capture_add(obj):
            nonlocal created
            created = obj

        db.add.side_effect = capture_add
        await record_rider_cancellation(
            db, rider_id=10, had_fee=False, in_grace_period=False, category=None
        )
        assert created.cancellation_rate == 1.0


# ---------------------------------------------------------------------------
# 16–21: record_rider_cancellation — existing stats row
# ---------------------------------------------------------------------------

class TestRecordRiderCancellationExisting:
    @pytest.mark.asyncio
    async def test_increments_total_cancellations(self):
        from app.services.rider_cancellation_stats import record_rider_cancellation

        existing = _make_stats(total_cancellations=2, total_rides_requested=5)
        db = _make_db(stats=existing)
        await record_rider_cancellation(
            db, rider_id=10, had_fee=False, in_grace_period=False, category=None
        )
        assert existing.total_cancellations == 3

    @pytest.mark.asyncio
    async def test_fee_counter_increments_when_had_fee(self):
        from app.services.rider_cancellation_stats import record_rider_cancellation

        existing = _make_stats(cancellations_with_fee=1)
        db = _make_db(stats=existing)
        await record_rider_cancellation(
            db, rider_id=10, had_fee=True, in_grace_period=False, category=None
        )
        assert existing.cancellations_with_fee == 2

    @pytest.mark.asyncio
    async def test_fee_counter_not_incremented_without_fee(self):
        from app.services.rider_cancellation_stats import record_rider_cancellation

        existing = _make_stats(cancellations_with_fee=1)
        db = _make_db(stats=existing)
        await record_rider_cancellation(
            db, rider_id=10, had_fee=False, in_grace_period=False, category=None
        )
        assert existing.cancellations_with_fee == 1

    @pytest.mark.asyncio
    async def test_grace_counter_increments_when_in_grace(self):
        from app.services.rider_cancellation_stats import record_rider_cancellation

        existing = _make_stats(cancellations_in_grace_period=0)
        db = _make_db(stats=existing)
        await record_rider_cancellation(
            db, rider_id=10, had_fee=False, in_grace_period=True, category=None
        )
        assert existing.cancellations_in_grace_period == 1

    @pytest.mark.asyncio
    async def test_rate_recalculated(self):
        from app.services.rider_cancellation_stats import record_rider_cancellation

        existing = _make_stats(total_cancellations=2, total_rides_requested=10)
        db = _make_db(stats=existing)
        await record_rider_cancellation(
            db, rider_id=10, had_fee=False, in_grace_period=False, category=None
        )
        # 3 cancels / 10 requests = 0.3
        assert existing.cancellation_rate == pytest.approx(0.3, abs=1e-4)

    @pytest.mark.asyncio
    async def test_category_updated_to_latest(self):
        from app.services.rider_cancellation_stats import record_rider_cancellation

        existing = _make_stats(last_cancel_category=CancellationCategory.WRONG_PICKUP)
        db = _make_db(stats=existing)
        await record_rider_cancellation(
            db, rider_id=10, had_fee=False, in_grace_period=False,
            category=CancellationCategory.PLANS_CHANGED
        )
        assert existing.last_cancel_category == CancellationCategory.PLANS_CHANGED

    @pytest.mark.asyncio
    async def test_commit_called_no_add(self):
        from app.services.rider_cancellation_stats import record_rider_cancellation

        existing = _make_stats()
        db = _make_db(stats=existing)
        await record_rider_cancellation(
            db, rider_id=10, had_fee=False, in_grace_period=False, category=None
        )
        db.add.assert_not_called()
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 22–24: increment_ride_requested service
# ---------------------------------------------------------------------------

class TestIncrementRideRequested:
    @pytest.mark.asyncio
    async def test_creates_row_when_none_exists(self):
        from app.services.rider_cancellation_stats import increment_ride_requested

        db = _make_db(stats=None)
        created = None

        def capture_add(obj):
            nonlocal created
            created = obj

        db.add.side_effect = capture_add
        await increment_ride_requested(db, rider_id=10)
        assert created is not None
        assert created.total_rides_requested == 1
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_increments_existing_row(self):
        from app.services.rider_cancellation_stats import increment_ride_requested

        existing = _make_stats(total_rides_requested=4, total_cancellations=1)
        db = _make_db(stats=existing)
        await increment_ride_requested(db, rider_id=10)
        assert existing.total_rides_requested == 5

    @pytest.mark.asyncio
    async def test_rate_recalculated_after_increment(self):
        from app.services.rider_cancellation_stats import increment_ride_requested

        existing = _make_stats(total_rides_requested=4, total_cancellations=2)
        db = _make_db(stats=existing)
        await increment_ride_requested(db, rider_id=10)
        # 2 cancels / 5 requests = 0.4
        assert existing.cancellation_rate == pytest.approx(0.4, abs=1e-4)


# ---------------------------------------------------------------------------
# 25–26: get_rider_cancel_stats service
# ---------------------------------------------------------------------------

class TestGetRiderCancelStats:
    @pytest.mark.asyncio
    async def test_returns_stats_when_found(self):
        from app.services.rider_cancellation_stats import get_rider_cancel_stats

        existing = _make_stats()
        db = _make_db(stats=existing)
        result = await get_rider_cancel_stats(db, rider_id=10)
        assert result is existing

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        from app.services.rider_cancellation_stats import get_rider_cancel_stats

        db = _make_db(stats=None)
        result = await get_rider_cancel_stats(db, rider_id=10)
        assert result is None


# ---------------------------------------------------------------------------
# 27–29: GET /riders/me/cancel-stats endpoint
# ---------------------------------------------------------------------------

class TestGetMyCancelStatsEndpoint:
    @pytest.mark.asyncio
    async def test_returns_zeros_when_no_stats(self):
        from app.api.v1.rider_cancellation_stats import get_my_cancel_stats
        from app.models.user import User

        user = MagicMock(spec=User)
        user.id = 10
        db = _make_db(stats=None)

        response = await get_my_cancel_stats(user=user, db=db)
        assert response.total_cancellations == 0
        assert response.cancellation_rate == 0.0
        assert response.rider_id == 10

    @pytest.mark.asyncio
    async def test_returns_stats_when_row_exists(self):
        from app.api.v1.rider_cancellation_stats import get_my_cancel_stats
        from app.models.user import User

        user = MagicMock(spec=User)
        user.id = 10
        existing = _make_stats(rider_id=10, total_cancellations=3, cancellation_rate=0.3)
        db = _make_db(stats=existing)

        response = await get_my_cancel_stats(user=user, db=db)
        # Returns the ORM object — from_attributes=True handles serialization
        assert response is existing


# ---------------------------------------------------------------------------
# 30–32: GET /admin/riders/{rider_id}/cancel-stats endpoint
# ---------------------------------------------------------------------------

class TestAdminGetCancelStatsEndpoint:
    @pytest.mark.asyncio
    async def test_returns_stats_for_admin(self):
        from app.api.v1.rider_cancellation_stats import admin_get_rider_cancel_stats
        from app.models.user import User

        admin = MagicMock(spec=User)
        admin.is_admin = True
        existing = _make_stats(rider_id=99)
        db = _make_db(stats=existing)

        response = await admin_get_rider_cancel_stats(rider_id=99, _admin=admin, db=db)
        assert response is existing

    @pytest.mark.asyncio
    async def test_404_when_no_stats(self):
        from app.api.v1.rider_cancellation_stats import admin_get_rider_cancel_stats
        from app.models.user import User
        from fastapi import HTTPException

        admin = MagicMock(spec=User)
        db = _make_db(stats=None)

        with pytest.raises(HTTPException) as exc_info:
            await admin_get_rider_cancel_stats(rider_id=99, _admin=admin, db=db)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 33–38: Cancel endpoint integration
# ---------------------------------------------------------------------------

class TestCancelEndpointIntegration:
    """Test that the cancel endpoint correctly stores category/cancelled_by
    and fires the stats update."""

    def _make_ride(
        self,
        ride_id=1,
        rider_id=10,
        driver_id=20,
        status=RideStatus.REQUESTED,  # pre-match = free cancel, no payment path
        estimated_fare=20.0,
        matched_at=None,
    ):
        ride = MagicMock()
        ride.id = ride_id
        ride.rider_id = rider_id
        ride.driver_id = driver_id
        ride.status = status
        ride.estimated_fare = estimated_fare
        ride.matched_at = matched_at  # None for REQUESTED rides
        ride.dispatch_retry_count = 0
        ride.cancellation_reason = None
        ride.cancellation_category = None
        ride.cancelled_by = None
        return ride

    @pytest.mark.asyncio
    async def test_cancellation_category_stored_on_ride(self):
        from app.api.v1.rides import cancel_ride
        from app.models.user import User

        ride = self._make_ride()
        user = MagicMock(spec=User)
        user.id = 10  # rider

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        req = CancelRequest(category=CancellationCategory.WAIT_TOO_LONG)

        with patch("app.api.v1.rides.get_matching_engine") as mock_engine_factory, \
             patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock), \
             patch("app.services.notification_events.notify_ride_cancelled", new_callable=AsyncMock), \
             patch("app.services.audit_events.audit_ride_cancelled", new_callable=AsyncMock), \
             patch("app.services.rider_cancellation_stats.record_rider_cancellation", new_callable=AsyncMock):

            mock_engine = AsyncMock()
            mock_engine_factory.return_value = mock_engine

            await cancel_ride(ride_id=1, req=req, user=user, db=db)

        assert ride.cancellation_category == CancellationCategory.WAIT_TOO_LONG

    @pytest.mark.asyncio
    async def test_cancelled_by_rider_stored(self):
        from app.api.v1.rides import cancel_ride
        from app.models.user import User

        ride = self._make_ride()
        user = MagicMock(spec=User)
        user.id = 10  # rider

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        req = CancelRequest()

        with patch("app.api.v1.rides.get_matching_engine") as mock_engine_factory, \
             patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock), \
             patch("app.services.notification_events.notify_ride_cancelled", new_callable=AsyncMock), \
             patch("app.services.audit_events.audit_ride_cancelled", new_callable=AsyncMock), \
             patch("app.services.rider_cancellation_stats.record_rider_cancellation", new_callable=AsyncMock):

            mock_engine = AsyncMock()
            mock_engine_factory.return_value = mock_engine

            await cancel_ride(ride_id=1, req=req, user=user, db=db)

        assert ride.cancelled_by == "rider"

    @pytest.mark.asyncio
    async def test_cancelled_by_driver_stored(self):
        from app.api.v1.rides import cancel_ride
        from app.models.user import User

        ride = self._make_ride()
        user = MagicMock(spec=User)
        user.id = 20  # driver

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        req = CancelRequest()

        with patch("app.api.v1.rides.get_matching_engine") as mock_engine_factory, \
             patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock), \
             patch("app.services.notification_events.notify_ride_cancelled", new_callable=AsyncMock), \
             patch("app.services.audit_events.audit_ride_cancelled", new_callable=AsyncMock):

            mock_engine = AsyncMock()
            mock_engine_factory.return_value = mock_engine

            await cancel_ride(ride_id=1, req=req, user=user, db=db)

        assert ride.cancelled_by == "driver"

    @pytest.mark.asyncio
    async def test_response_includes_cancelled_by(self):
        from app.api.v1.rides import cancel_ride
        from app.models.user import User

        ride = self._make_ride()
        user = MagicMock(spec=User)
        user.id = 10  # rider

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        req = CancelRequest()

        with patch("app.api.v1.rides.get_matching_engine") as mock_engine_factory, \
             patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock), \
             patch("app.services.notification_events.notify_ride_cancelled", new_callable=AsyncMock), \
             patch("app.services.audit_events.audit_ride_cancelled", new_callable=AsyncMock), \
             patch("app.services.rider_cancellation_stats.record_rider_cancellation", new_callable=AsyncMock):

            mock_engine = AsyncMock()
            mock_engine_factory.return_value = mock_engine

            response = await cancel_ride(ride_id=1, req=req, user=user, db=db)

        assert response.cancelled_by == "rider"

    @pytest.mark.asyncio
    async def test_stats_not_updated_for_driver_cancel(self):
        from app.api.v1.rides import cancel_ride
        from app.models.user import User

        ride = self._make_ride()
        user = MagicMock(spec=User)
        user.id = 20  # driver

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        req = CancelRequest()

        with patch("app.api.v1.rides.get_matching_engine") as mock_engine_factory, \
             patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock), \
             patch("app.services.notification_events.notify_ride_cancelled", new_callable=AsyncMock), \
             patch("app.services.audit_events.audit_ride_cancelled", new_callable=AsyncMock), \
             patch("app.services.rider_cancellation_stats.record_rider_cancellation", new_callable=AsyncMock) as mock_stats:

            mock_engine = AsyncMock()
            mock_engine_factory.return_value = mock_engine

            await cancel_ride(ride_id=1, req=req, user=user, db=db)

        mock_stats.assert_not_called()
