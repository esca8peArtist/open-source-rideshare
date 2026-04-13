"""Unit tests for the background dispatch scheduler and retry logic."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ride import Ride, RideStatus
from app.services.dispatch_scheduler import (
    _retry_delay,
    _scheduler_loop,
    dispatch_due_rides,
    retry_unmatched_rides,
    start_scheduler,
    stop_scheduler,
)

NOW = datetime(2026, 4, 12, 14, 0, 0, tzinfo=timezone.utc)


def _make_ride(ride_id, rider_id, scheduled_for, status=RideStatus.SCHEDULED,
               driver_id=None, dispatch_retry_count=0, last_retry_at=None,
               requested_at=None):
    """Create a mock Ride object."""
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.status = status
    ride.scheduled_for = scheduled_for
    ride.pickup_address = "123 Main St"
    ride.dropoff_address = "456 Oak Ave"
    ride.estimated_fare = 15.0
    ride.pickup_location = MagicMock()
    ride.requested_at = requested_at
    ride.matched_at = None
    ride.driver_id = driver_id
    ride.dispatch_retry_count = dispatch_retry_count
    ride.last_retry_at = last_retry_at
    ride.cancelled_at = None
    ride.cancellation_reason = None
    return ride


def _mock_db_with_rides(rides):
    """Build a mock async_session context that returns the given rides."""
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = rides
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session_factory = MagicMock(return_value=mock_session_ctx)
    return mock_session_factory, mock_db


def _patches(mock_session_factory, mock_engine=None):
    """Return a combined context manager patching all lazy imports."""
    if mock_engine is None:
        mock_engine = AsyncMock()
        mock_engine.find_candidates = AsyncMock(return_value=[])
        mock_engine.match_ride = AsyncMock(return_value=None)

    return (
        patch("app.db.database.async_session", mock_session_factory),
        patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock),
        patch("app.api.websocket.send_ride_offer", new_callable=AsyncMock),
        patch("app.services.matching.get_matching_engine", return_value=mock_engine),
    )


class TestDispatchDueRides:
    """Tests for the dispatch_due_rides function."""

    @pytest.mark.asyncio
    async def test_dispatches_ride_within_window(self):
        """A ride scheduled 10 minutes from now (within 15-min window) is dispatched."""
        ride = _make_ride(1, 100, NOW + timedelta(minutes=10))
        mock_sf, mock_db = _mock_db_with_rides([ride])
        p1, p2, p3, p4 = _patches(mock_sf)

        with p1, p2 as mock_notify, p3, p4:
            count = await dispatch_due_rides(now=NOW)

        assert count == 1
        assert ride.status == RideStatus.REQUESTED
        assert ride.requested_at == NOW
        mock_notify.assert_any_call(100, 1, "dispatched")

    @pytest.mark.asyncio
    async def test_skips_ride_not_in_window(self):
        """A ride scheduled 2 hours from now (outside 15-min window) is skipped."""
        ride = _make_ride(1, 100, NOW + timedelta(hours=2))
        mock_sf, _ = _mock_db_with_rides([ride])
        p1, p2, p3, p4 = _patches(mock_sf)

        with p1, p2 as mock_notify, p3, p4:
            count = await dispatch_due_rides(now=NOW)

        assert count == 0
        assert ride.status == RideStatus.SCHEDULED
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_scheduled_rides(self):
        """Returns 0 when there are no scheduled rides."""
        mock_sf, _ = _mock_db_with_rides([])
        p1, p2, p3, p4 = _patches(mock_sf)

        with p1, p2, p3, p4:
            count = await dispatch_due_rides(now=NOW)

        assert count == 0

    @pytest.mark.asyncio
    async def test_multiple_rides_some_due(self):
        """Only rides within the dispatch window are dispatched."""
        ride_due = _make_ride(1, 100, NOW + timedelta(minutes=5))
        ride_not_due = _make_ride(2, 200, NOW + timedelta(hours=3))
        ride_also_due = _make_ride(3, 300, NOW - timedelta(minutes=2))

        mock_sf, _ = _mock_db_with_rides([ride_due, ride_not_due, ride_also_due])
        p1, p2, p3, p4 = _patches(mock_sf)

        with p1, p2, p3, p4:
            count = await dispatch_due_rides(now=NOW)

        assert count == 2
        assert ride_due.status == RideStatus.REQUESTED
        assert ride_also_due.status == RideStatus.REQUESTED
        assert ride_not_due.status == RideStatus.SCHEDULED

    @pytest.mark.asyncio
    async def test_matching_succeeds(self):
        """When a driver is found, ride transitions to MATCHED."""
        ride = _make_ride(1, 100, NOW + timedelta(minutes=5))
        mock_sf, _ = _mock_db_with_rides([ride])

        mock_candidate = MagicMock()
        mock_candidate.user_id = 500
        mock_candidate.distance_km = 1.5

        mock_engine = AsyncMock()
        mock_engine.find_candidates = AsyncMock(return_value=[mock_candidate])
        mock_engine.match_ride = AsyncMock(return_value=mock_candidate)
        mock_engine.set_driver_busy = AsyncMock()

        p1, p2, p3, p4 = _patches(mock_sf, mock_engine)

        with p1, p2 as mock_notify, p3 as mock_offer, p4:
            count = await dispatch_due_rides(now=NOW)

        assert count == 1
        assert ride.status == RideStatus.MATCHED
        assert ride.driver_id == 500
        mock_offer.assert_called_once_with(
            500, 1, "123 Main St", "456 Oak Ave", 15.0, 1.5,
        )
        mock_engine.set_driver_busy.assert_called_once_with(500)
        mock_notify.assert_any_call(100, 1, "matched", driver_distance_km=1.5)

    @pytest.mark.asyncio
    async def test_no_drivers_available(self):
        """When no drivers found, ride stays REQUESTED and rider is notified."""
        ride = _make_ride(1, 100, NOW + timedelta(minutes=5))
        mock_sf, _ = _mock_db_with_rides([ride])
        p1, p2, p3, p4 = _patches(mock_sf)

        with p1, p2 as mock_notify, p3, p4:
            count = await dispatch_due_rides(now=NOW)

        assert count == 1
        assert ride.status == RideStatus.REQUESTED
        mock_notify.assert_any_call(100, 1, "no_drivers")

    @pytest.mark.asyncio
    async def test_matching_exception_doesnt_crash(self):
        """If matching throws, the ride stays REQUESTED and the scheduler continues."""
        ride = _make_ride(1, 100, NOW + timedelta(minutes=5))
        mock_sf, _ = _mock_db_with_rides([ride])

        mock_engine = AsyncMock()
        mock_engine.find_candidates = AsyncMock(side_effect=RuntimeError("Redis down"))

        p1, p2, p3, p4 = _patches(mock_sf, mock_engine)

        with p1, p2, p3, p4:
            count = await dispatch_due_rides(now=NOW)

        assert count == 1
        assert ride.status == RideStatus.REQUESTED

    @pytest.mark.asyncio
    async def test_ride_past_scheduled_time_dispatched(self):
        """A ride whose scheduled_for is already past should still be dispatched."""
        ride = _make_ride(1, 100, NOW - timedelta(minutes=30))
        mock_sf, _ = _mock_db_with_rides([ride])
        p1, p2, p3, p4 = _patches(mock_sf)

        with p1, p2, p3, p4:
            count = await dispatch_due_rides(now=NOW)

        assert count == 1
        assert ride.status == RideStatus.REQUESTED

    @pytest.mark.asyncio
    async def test_ride_at_exact_dispatch_boundary(self):
        """A ride exactly at the 15-minute dispatch boundary is dispatched."""
        ride = _make_ride(1, 100, NOW + timedelta(minutes=15))
        mock_sf, _ = _mock_db_with_rides([ride])
        p1, p2, p3, p4 = _patches(mock_sf)

        with p1, p2, p3, p4:
            count = await dispatch_due_rides(now=NOW)

        assert count == 1
        assert ride.status == RideStatus.REQUESTED

    @pytest.mark.asyncio
    async def test_ride_just_outside_dispatch_window(self):
        """A ride at 16 minutes (just outside 15-min window) is NOT dispatched."""
        ride = _make_ride(1, 100, NOW + timedelta(minutes=16))
        mock_sf, _ = _mock_db_with_rides([ride])
        p1, p2, p3, p4 = _patches(mock_sf)

        with p1, p2, p3, p4:
            count = await dispatch_due_rides(now=NOW)

        assert count == 0
        assert ride.status == RideStatus.SCHEDULED

    @pytest.mark.asyncio
    async def test_matching_finds_candidates_but_no_match(self):
        """When candidates exist but match_ride returns None, rider gets no_drivers."""
        ride = _make_ride(1, 100, NOW + timedelta(minutes=5))
        mock_sf, _ = _mock_db_with_rides([ride])

        mock_candidate = MagicMock()
        mock_engine = AsyncMock()
        mock_engine.find_candidates = AsyncMock(return_value=[mock_candidate])
        mock_engine.match_ride = AsyncMock(return_value=None)

        p1, p2, p3, p4 = _patches(mock_sf, mock_engine)

        with p1, p2 as mock_notify, p3, p4:
            count = await dispatch_due_rides(now=NOW)

        assert count == 1
        assert ride.status == RideStatus.REQUESTED
        mock_notify.assert_any_call(100, 1, "no_drivers")


class TestRetryUnmatchedRides:
    """Tests for the retry_unmatched_rides function."""

    @pytest.mark.asyncio
    async def test_retries_unmatched_ride_after_backoff(self):
        """A REQUESTED ride with no driver is retried after the backoff interval."""
        ride = _make_ride(
            1, 100, NOW - timedelta(minutes=10),
            status=RideStatus.REQUESTED,
            requested_at=NOW - timedelta(minutes=5),
            dispatch_retry_count=0,
            last_retry_at=None,
        )
        mock_sf, _ = _mock_db_with_rides([ride])
        p1, p2, p3, p4 = _patches(mock_sf)

        with p1, p2 as mock_notify, p3, p4, \
             patch("app.services.dispatch_scheduler.settings") as mock_settings:
            mock_settings.dispatch_max_retries = 5
            mock_settings.dispatch_retry_interval_seconds = 60
            mock_settings.dispatch_retry_backoff = 1.5
            count = await retry_unmatched_rides(now=NOW)

        assert count == 1
        assert ride.dispatch_retry_count == 1
        assert ride.last_retry_at == NOW
        mock_notify.assert_any_call(100, 1, "retry_no_drivers", retry=1, max_retries=5)

    @pytest.mark.asyncio
    async def test_skips_ride_within_backoff_window(self):
        """A ride retried recently (within backoff window) is skipped."""
        ride = _make_ride(
            1, 100, NOW - timedelta(minutes=10),
            status=RideStatus.REQUESTED,
            requested_at=NOW - timedelta(minutes=5),
            dispatch_retry_count=1,
            last_retry_at=NOW - timedelta(seconds=30),  # 30s ago, backoff is 90s
        )
        mock_sf, _ = _mock_db_with_rides([ride])
        p1, p2, p3, p4 = _patches(mock_sf)

        with p1, p2, p3, p4, \
             patch("app.services.dispatch_scheduler.settings") as mock_settings:
            mock_settings.dispatch_max_retries = 5
            mock_settings.dispatch_retry_interval_seconds = 60
            mock_settings.dispatch_retry_backoff = 1.5
            count = await retry_unmatched_rides(now=NOW)

        assert count == 0
        assert ride.dispatch_retry_count == 1  # unchanged

    @pytest.mark.asyncio
    async def test_cancels_after_max_retries(self):
        """A ride at max retries is cancelled and rider notified."""
        ride = _make_ride(
            1, 100, NOW - timedelta(minutes=30),
            status=RideStatus.REQUESTED,
            requested_at=NOW - timedelta(minutes=25),
            dispatch_retry_count=5,
            last_retry_at=NOW - timedelta(minutes=10),
        )
        mock_sf, _ = _mock_db_with_rides([ride])
        p1, p2, p3, p4 = _patches(mock_sf)

        with p1, p2 as mock_notify, p3, p4, \
             patch("app.services.dispatch_scheduler.settings") as mock_settings:
            mock_settings.dispatch_max_retries = 5
            mock_settings.dispatch_retry_interval_seconds = 60
            mock_settings.dispatch_retry_backoff = 1.5
            count = await retry_unmatched_rides(now=NOW)

        assert count == 0  # cancellation is not a "retry"
        assert ride.status == RideStatus.CANCELLED
        assert ride.cancelled_at == NOW
        assert "maximum retry" in ride.cancellation_reason
        mock_notify.assert_any_call(100, 1, "matching_failed")

    @pytest.mark.asyncio
    async def test_retry_matches_driver_successfully(self):
        """On retry, if a driver is found, ride transitions to MATCHED."""
        ride = _make_ride(
            1, 100, NOW - timedelta(minutes=10),
            status=RideStatus.REQUESTED,
            requested_at=NOW - timedelta(minutes=5),
            dispatch_retry_count=1,
            last_retry_at=NOW - timedelta(minutes=3),  # 3 min ago, backoff at retry 1 = 90s
        )
        mock_sf, _ = _mock_db_with_rides([ride])

        mock_candidate = MagicMock()
        mock_candidate.user_id = 500
        mock_candidate.distance_km = 2.0

        mock_engine = AsyncMock()
        mock_engine.find_candidates = AsyncMock(return_value=[mock_candidate])
        mock_engine.match_ride = AsyncMock(return_value=mock_candidate)
        mock_engine.set_driver_busy = AsyncMock()

        p1, p2, p3, p4 = _patches(mock_sf, mock_engine)

        with p1, p2 as mock_notify, p3 as mock_offer, p4, \
             patch("app.services.dispatch_scheduler.settings") as mock_settings:
            mock_settings.dispatch_max_retries = 5
            mock_settings.dispatch_retry_interval_seconds = 60
            mock_settings.dispatch_retry_backoff = 1.5
            count = await retry_unmatched_rides(now=NOW)

        assert count == 1
        assert ride.status == RideStatus.MATCHED
        assert ride.driver_id == 500
        assert ride.dispatch_retry_count == 2
        mock_offer.assert_called_once_with(
            500, 1, "123 Main St", "456 Oak Ave", 15.0, 2.0,
        )
        mock_engine.set_driver_busy.assert_called_once_with(500)
        mock_notify.assert_any_call(100, 1, "matched", driver_distance_km=2.0)

    @pytest.mark.asyncio
    async def test_no_unmatched_rides(self):
        """Returns 0 when no REQUESTED rides have driver_id=None."""
        mock_sf, _ = _mock_db_with_rides([])
        p1, p2, p3, p4 = _patches(mock_sf)

        with p1, p2, p3, p4, \
             patch("app.services.dispatch_scheduler.settings") as mock_settings:
            mock_settings.dispatch_max_retries = 5
            mock_settings.dispatch_retry_interval_seconds = 60
            mock_settings.dispatch_retry_backoff = 1.5
            count = await retry_unmatched_rides(now=NOW)

        assert count == 0

    @pytest.mark.asyncio
    async def test_retry_exception_doesnt_crash(self):
        """If matching throws during retry, the ride is not cancelled — just retried later."""
        ride = _make_ride(
            1, 100, NOW - timedelta(minutes=10),
            status=RideStatus.REQUESTED,
            requested_at=NOW - timedelta(minutes=5),
            dispatch_retry_count=0,
            last_retry_at=None,
        )
        mock_sf, _ = _mock_db_with_rides([ride])

        mock_engine = AsyncMock()
        mock_engine.find_candidates = AsyncMock(side_effect=RuntimeError("Redis down"))

        p1, p2, p3, p4 = _patches(mock_sf, mock_engine)

        with p1, p2, p3, p4, \
             patch("app.services.dispatch_scheduler.settings") as mock_settings:
            mock_settings.dispatch_max_retries = 5
            mock_settings.dispatch_retry_interval_seconds = 60
            mock_settings.dispatch_retry_backoff = 1.5
            count = await retry_unmatched_rides(now=NOW)

        assert count == 1
        assert ride.dispatch_retry_count == 1  # incremented
        assert ride.status == RideStatus.REQUESTED  # not cancelled

    @pytest.mark.asyncio
    async def test_multiple_rides_mixed_states(self):
        """Multiple rides: one due for retry, one within backoff, one at max retries."""
        ride_due = _make_ride(
            1, 100, NOW - timedelta(minutes=10),
            status=RideStatus.REQUESTED,
            requested_at=NOW - timedelta(minutes=5),
            dispatch_retry_count=1,
            last_retry_at=NOW - timedelta(minutes=3),
        )
        ride_backoff = _make_ride(
            2, 200, NOW - timedelta(minutes=5),
            status=RideStatus.REQUESTED,
            requested_at=NOW - timedelta(minutes=3),
            dispatch_retry_count=2,
            last_retry_at=NOW - timedelta(seconds=30),  # too soon for retry 2 (backoff=135s)
        )
        ride_exhausted = _make_ride(
            3, 300, NOW - timedelta(minutes=30),
            status=RideStatus.REQUESTED,
            requested_at=NOW - timedelta(minutes=25),
            dispatch_retry_count=5,
            last_retry_at=NOW - timedelta(minutes=10),
        )

        mock_sf, _ = _mock_db_with_rides([ride_due, ride_backoff, ride_exhausted])
        p1, p2, p3, p4 = _patches(mock_sf)

        with p1, p2 as mock_notify, p3, p4, \
             patch("app.services.dispatch_scheduler.settings") as mock_settings:
            mock_settings.dispatch_max_retries = 5
            mock_settings.dispatch_retry_interval_seconds = 60
            mock_settings.dispatch_retry_backoff = 1.5
            count = await retry_unmatched_rides(now=NOW)

        assert count == 1  # only ride_due was retried
        assert ride_due.dispatch_retry_count == 2
        assert ride_backoff.dispatch_retry_count == 2  # unchanged
        assert ride_exhausted.status == RideStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_retry_uses_requested_at_for_first_attempt(self):
        """First retry uses requested_at (not last_retry_at) for backoff check."""
        ride = _make_ride(
            1, 100, NOW - timedelta(minutes=10),
            status=RideStatus.REQUESTED,
            requested_at=NOW - timedelta(seconds=30),  # 30s ago, base backoff is 60s
            dispatch_retry_count=0,
            last_retry_at=None,
        )
        mock_sf, _ = _mock_db_with_rides([ride])
        p1, p2, p3, p4 = _patches(mock_sf)

        with p1, p2, p3, p4, \
             patch("app.services.dispatch_scheduler.settings") as mock_settings:
            mock_settings.dispatch_max_retries = 5
            mock_settings.dispatch_retry_interval_seconds = 60
            mock_settings.dispatch_retry_backoff = 1.5
            count = await retry_unmatched_rides(now=NOW)

        assert count == 0  # too soon — only 30s since requested, need 60s
        assert ride.dispatch_retry_count == 0

    @pytest.mark.asyncio
    async def test_retry_skips_match_if_ride_cancelled_during_matching(self):
        """If a ride is cancelled by the rider while a retry match is in progress,
        the scheduler should not overwrite the CANCELLED status with MATCHED."""
        ride = _make_ride(
            1, 100, NOW - timedelta(minutes=10),
            status=RideStatus.REQUESTED,
            requested_at=NOW - timedelta(minutes=5),
            dispatch_retry_count=1,
            last_retry_at=NOW - timedelta(minutes=3),
        )
        mock_sf, _ = _mock_db_with_rides([ride])

        mock_candidate = MagicMock()
        mock_candidate.user_id = 500
        mock_candidate.distance_km = 2.0

        # Simulate the rider cancelling between find_candidates and match_ride:
        # match_ride succeeds, but by the time we check ride.status it's CANCELLED
        async def cancel_during_match(*args, **kwargs):
            ride.status = RideStatus.CANCELLED
            return mock_candidate

        mock_engine = AsyncMock()
        mock_engine.find_candidates = AsyncMock(return_value=[mock_candidate])
        mock_engine.match_ride = AsyncMock(side_effect=cancel_during_match)
        mock_engine.set_driver_busy = AsyncMock()

        p1, p2, p3, p4 = _patches(mock_sf, mock_engine)

        with p1, p2, p3 as mock_offer, p4, \
             patch("app.services.dispatch_scheduler.settings") as mock_settings:
            mock_settings.dispatch_max_retries = 5
            mock_settings.dispatch_retry_interval_seconds = 60
            mock_settings.dispatch_retry_backoff = 1.5
            count = await retry_unmatched_rides(now=NOW)

        assert count == 1  # retry was attempted
        assert ride.status == RideStatus.CANCELLED  # NOT overwritten to MATCHED
        assert ride.driver_id is None  # driver not assigned
        mock_offer.assert_not_called()  # no offer sent
        mock_engine.set_driver_busy.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_candidates_but_no_match(self):
        """Candidates found but match_ride returns None — rider gets retry_no_drivers."""
        ride = _make_ride(
            1, 100, NOW - timedelta(minutes=10),
            status=RideStatus.REQUESTED,
            requested_at=NOW - timedelta(minutes=5),
            dispatch_retry_count=0,
            last_retry_at=None,
        )
        mock_sf, _ = _mock_db_with_rides([ride])

        mock_candidate = MagicMock()
        mock_engine = AsyncMock()
        mock_engine.find_candidates = AsyncMock(return_value=[mock_candidate])
        mock_engine.match_ride = AsyncMock(return_value=None)

        p1, p2, p3, p4 = _patches(mock_sf, mock_engine)

        with p1, p2 as mock_notify, p3, p4, \
             patch("app.services.dispatch_scheduler.settings") as mock_settings:
            mock_settings.dispatch_max_retries = 5
            mock_settings.dispatch_retry_interval_seconds = 60
            mock_settings.dispatch_retry_backoff = 1.5
            count = await retry_unmatched_rides(now=NOW)

        assert count == 1
        assert ride.status == RideStatus.REQUESTED
        mock_notify.assert_any_call(100, 1, "retry_no_drivers", retry=1, max_retries=5)


class TestRetryDelay:
    """Tests for the _retry_delay backoff calculation."""

    def test_first_retry(self):
        """First retry (count=0) uses the base interval."""
        with patch("app.services.dispatch_scheduler.settings") as mock_settings:
            mock_settings.dispatch_retry_interval_seconds = 60
            mock_settings.dispatch_retry_backoff = 1.5
            assert _retry_delay(0) == 60.0

    def test_second_retry(self):
        """Second retry (count=1) applies backoff once."""
        with patch("app.services.dispatch_scheduler.settings") as mock_settings:
            mock_settings.dispatch_retry_interval_seconds = 60
            mock_settings.dispatch_retry_backoff = 1.5
            assert _retry_delay(1) == 90.0

    def test_third_retry(self):
        """Third retry (count=2) applies backoff twice."""
        with patch("app.services.dispatch_scheduler.settings") as mock_settings:
            mock_settings.dispatch_retry_interval_seconds = 60
            mock_settings.dispatch_retry_backoff = 1.5
            assert _retry_delay(2) == 135.0

    def test_fifth_retry(self):
        """Fifth retry (count=4) — 60 * 1.5^4 = 303.75."""
        with patch("app.services.dispatch_scheduler.settings") as mock_settings:
            mock_settings.dispatch_retry_interval_seconds = 60
            mock_settings.dispatch_retry_backoff = 1.5
            assert _retry_delay(4) == pytest.approx(303.75)


class TestSchedulerLifecycle:
    """Tests for start_scheduler and stop_scheduler."""

    @pytest.mark.asyncio
    async def test_start_creates_task(self):
        """start_scheduler creates an asyncio task."""
        import app.services.dispatch_scheduler as mod

        mod._scheduler_task = None

        with patch.object(mod, "_scheduler_loop", new_callable=AsyncMock) as mock_loop:
            mock_loop.return_value = None
            task = start_scheduler()
            assert task is not None
            assert not task.done()

            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            mod._scheduler_task = None

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        """stop_scheduler cancels a running task."""
        import app.services.dispatch_scheduler as mod

        mod._scheduler_task = None

        with patch.object(mod, "_scheduler_loop", new_callable=AsyncMock) as mock_loop:
            mock_loop.side_effect = asyncio.CancelledError
            start_scheduler()

            await stop_scheduler()
            assert mod._scheduler_task is None

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self):
        """stop_scheduler is a no-op when scheduler isn't running."""
        import app.services.dispatch_scheduler as mod

        mod._scheduler_task = None
        await stop_scheduler()  # should not raise

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        """Calling start_scheduler twice returns the same task."""
        import app.services.dispatch_scheduler as mod

        mod._scheduler_task = None

        with patch.object(mod, "_scheduler_loop", new_callable=AsyncMock):
            task1 = start_scheduler()
            task2 = start_scheduler()
            assert task1 is task2

            task1.cancel()
            try:
                await task1
            except asyncio.CancelledError:
                pass
            mod._scheduler_task = None


class TestSchedulerLoop:
    """Tests for the _scheduler_loop periodic behavior."""

    @pytest.mark.asyncio
    async def test_loop_calls_dispatch_and_retry(self):
        """The loop calls both dispatch_due_rides and retry_unmatched_rides."""
        dispatch_count = 0
        retry_count = 0

        async def mock_dispatch(**kwargs):
            nonlocal dispatch_count
            dispatch_count += 1
            return 0

        async def mock_retry(**kwargs):
            nonlocal retry_count
            retry_count += 1
            if retry_count >= 2:
                raise asyncio.CancelledError
            return 0

        with patch("app.services.dispatch_scheduler.dispatch_due_rides", side_effect=mock_dispatch), \
             patch("app.services.dispatch_scheduler.retry_unmatched_rides", side_effect=mock_retry), \
             patch("app.services.dispatch_scheduler.settings") as mock_settings, \
             patch("app.services.dispatch_scheduler.asyncio.sleep", new_callable=AsyncMock):
            mock_settings.dispatch_check_interval_seconds = 1

            with pytest.raises(asyncio.CancelledError):
                await _scheduler_loop()

        assert dispatch_count == 2
        assert retry_count == 2

    @pytest.mark.asyncio
    async def test_loop_survives_dispatch_exception(self):
        """The loop continues after an exception in dispatch_due_rides."""
        call_count = 0

        async def mock_dispatch(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("DB connection failed")
            if call_count >= 3:
                raise asyncio.CancelledError
            return 0

        with patch("app.services.dispatch_scheduler.dispatch_due_rides", side_effect=mock_dispatch), \
             patch("app.services.dispatch_scheduler.retry_unmatched_rides", new_callable=AsyncMock, return_value=0), \
             patch("app.services.dispatch_scheduler.settings") as mock_settings, \
             patch("app.services.dispatch_scheduler.asyncio.sleep", new_callable=AsyncMock):
            mock_settings.dispatch_check_interval_seconds = 1

            with pytest.raises(asyncio.CancelledError):
                await _scheduler_loop()

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_loop_survives_retry_exception(self):
        """The loop continues after an exception in retry_unmatched_rides."""
        retry_count = 0

        async def mock_retry(**kwargs):
            nonlocal retry_count
            retry_count += 1
            if retry_count == 1:
                raise RuntimeError("Redis down")
            if retry_count >= 3:
                raise asyncio.CancelledError
            return 0

        with patch("app.services.dispatch_scheduler.dispatch_due_rides", new_callable=AsyncMock, return_value=0), \
             patch("app.services.dispatch_scheduler.retry_unmatched_rides", side_effect=mock_retry), \
             patch("app.services.dispatch_scheduler.settings") as mock_settings, \
             patch("app.services.dispatch_scheduler.asyncio.sleep", new_callable=AsyncMock):
            mock_settings.dispatch_check_interval_seconds = 1

            with pytest.raises(asyncio.CancelledError):
                await _scheduler_loop()

        assert retry_count == 3
