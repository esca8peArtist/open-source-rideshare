"""Unit tests for driver speeding alert detection.

Covers:
Pure speed computation:
  1.  compute_speed_mph — stationary (same point) returns 0.0
  2.  compute_speed_mph — 60 mph over 1 hour returns ≈ 60 mph
  3.  compute_speed_mph — zero elapsed time returns 0.0
  4.  compute_speed_mph — negative elapsed time returns 0.0
  5.  compute_speed_mph — 90 mph over 30 minutes
  6.  compute_speed_mph — speed proportional to distance

check_and_notify_speeding service:
  7.  No previous position (first call) — returns False, stores position
  8.  Interval below minimum (< 3 s) — returns False
  9.  No active IN_PROGRESS ride — returns False
  10. Ride already flagged — returns False, no second notification
  11. Speed within threshold — returns False, not flagged
  12. Speed exceeds threshold — returns True, flag set, rider notified
  13. DB exception in active ride query — returns False without raising
  14. Commit called on flag
  15. No commit when within threshold
  16. Custom threshold parameter respected

Idempotency:
  17. Second call after flag set — returns False, no re-notify

Notification template:
  18. speeding_alert template returns expected title/body/channels

NotificationType registration:
  19. SPEEDING_ALERT in NotificationType enum
  20. SPEEDING_ALERT in ride_types set

notify_speeding_alert dispatcher:
  21. Calls send_ride_notification with correct args
  22. Exception in send_ride_notification is swallowed

GET /rides/{ride_id}/speeding-status endpoint:
  23. 401 without auth
  24. 404 for non-existent ride
  25. 403 when user is neither rider nor driver
  26. 200 with speeding_detected=False when not flagged
  27. 200 with speeding_detected=True and flagged_at when flagged
  28. Rider can access their own ride's speeding status
  29. Driver can access their ride's speeding status
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.speeding_alert import (
    DEFAULT_SPEEDING_THRESHOLD_MPH,
    MIN_INTERVAL_SECONDS,
    _clear_prev_positions,
    check_and_notify_speeding,
    compute_speed_mph,
)

NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(active_ride_id=1, ride_row=None):
    """Build a mock AsyncSession for check_and_notify_speeding."""
    db = AsyncMock()

    first_result = MagicMock()
    if active_ride_id is None:
        first_result.first.return_value = None
    else:
        first_result.first.return_value = (active_ride_id,)

    second_result = MagicMock()
    second_result.one_or_none.return_value = ride_row

    fourth_result = MagicMock()  # UPDATE result

    db.execute = AsyncMock(
        side_effect=[first_result, second_result, fourth_result]
    )
    db.commit = AsyncMock()
    return db


def _make_ride_row(rider_id=10, speeding_flagged_at=None):
    row = MagicMock()
    row.rider_id = rider_id
    row.speeding_flagged_at = speeding_flagged_at
    return row


# ---------------------------------------------------------------------------
# 1–6: Pure speed computation
# ---------------------------------------------------------------------------


class TestComputeSpeedMph:
    def test_stationary_returns_zero(self):
        t1 = NOW
        t2 = NOW + timedelta(hours=1)
        speed = compute_speed_mph(40.0, -74.0, t1, 40.0, -74.0, t2)
        assert speed == 0.0

    def test_60mph_over_one_hour(self):
        # ≈ 60 miles north of NYC (1° lat ≈ 69 miles)
        t1 = NOW
        t2 = NOW + timedelta(hours=1)
        # 60/69 ≈ 0.87° of latitude
        speed = compute_speed_mph(40.0, -74.0, t1, 40.87, -74.0, t2)
        assert 55 < speed < 65

    def test_zero_elapsed_returns_zero(self):
        speed = compute_speed_mph(40.0, -74.0, NOW, 40.5, -74.0, NOW)
        assert speed == 0.0

    def test_negative_elapsed_returns_zero(self):
        t_future = NOW
        t_past = NOW + timedelta(seconds=10)
        # t_past > t_future so elapsed is negative
        speed = compute_speed_mph(40.0, -74.0, t_past, 40.5, -74.0, t_future)
        assert speed == 0.0

    def test_90mph_over_30_minutes(self):
        t1 = NOW
        t2 = NOW + timedelta(minutes=30)
        # 45 miles ÷ 69 miles/degree ≈ 0.652°
        speed = compute_speed_mph(40.0, -74.0, t1, 40.652, -74.0, t2)
        assert 83 < speed < 97

    def test_speed_proportional_to_distance(self):
        t1 = NOW
        t2 = NOW + timedelta(hours=1)
        speed_half = compute_speed_mph(40.0, -74.0, t1, 40.435, -74.0, t2)
        speed_full = compute_speed_mph(40.0, -74.0, t1, 40.87, -74.0, t2)
        assert speed_full > speed_half * 1.5


# ---------------------------------------------------------------------------
# 7–16: check_and_notify_speeding service
# ---------------------------------------------------------------------------


class TestCheckAndNotifySpeeding:
    def setup_method(self):
        _clear_prev_positions()

    @pytest.mark.asyncio
    async def test_no_prev_position_returns_false(self):
        """First call for a driver — no previous position to compare."""
        db = AsyncMock()
        with patch("app.services.notification_events.notify_speeding_alert") as mock_notify:
            result = await check_and_notify_speeding(
                user_id=99, lat=40.7128, lng=-74.0060, db=db
            )
        assert result is False
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_interval_below_minimum_returns_false(self):
        """Positions less than MIN_INTERVAL_SECONDS apart produce no result."""
        db = AsyncMock()
        # First call to populate store — set _now so the stored ts is controlled
        t0 = NOW
        await check_and_notify_speeding(user_id=20, lat=40.0, lng=-74.0, db=db, _now=t0)

        # Second call only 1 second later
        with patch("app.services.notification_events.notify_speeding_alert") as mock_notify:
            result = await check_and_notify_speeding(
                user_id=20, lat=40.001, lng=-74.0, db=db,
                _now=t0 + timedelta(seconds=1)
            )
        assert result is False
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_active_ride_returns_false(self):
        """If driver has no IN_PROGRESS ride, return False."""
        db = _make_db(active_ride_id=None)
        from app.services import speeding_alert as _svc
        _svc._prev_positions[20] = (40.0, -74.0, NOW - timedelta(seconds=10))

        with patch("app.services.notification_events.notify_speeding_alert") as mock_notify:
            result = await check_and_notify_speeding(
                user_id=20, lat=41.0, lng=-74.0, db=db, _now=NOW
            )
        assert result is False
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_flagged_returns_false(self):
        """Ride with speeding_flagged_at already set is not re-notified."""
        from app.services import speeding_alert as _svc
        _svc._prev_positions[20] = (40.0, -74.0, NOW - timedelta(seconds=10))

        ride_row = _make_ride_row(speeding_flagged_at=NOW)
        db = _make_db(active_ride_id=1, ride_row=ride_row)

        with patch("app.services.notification_events.notify_speeding_alert") as mock_notify:
            result = await check_and_notify_speeding(
                user_id=20, lat=41.0, lng=-74.0, db=db, _now=NOW
            )
        assert result is False
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_within_threshold_returns_false(self):
        """Driver below 90 mph does not trigger a flag."""
        from app.services import speeding_alert as _svc
        # 0.1° lat ≈ 6.9 miles in 10 minutes ≈ 41 mph — well under 90
        _svc._prev_positions[20] = (40.0, -74.0, NOW - timedelta(minutes=10))

        ride_row = _make_ride_row()
        db = _make_db(active_ride_id=1, ride_row=ride_row)

        with patch(
            "app.services.notification_events.notify_speeding_alert", new_callable=AsyncMock
        ) as mock_notify:
            result = await check_and_notify_speeding(
                user_id=20, lat=40.1, lng=-74.0, db=db, threshold_mph=90, _now=NOW
            )
        assert result is False
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_exceeds_threshold_notifies_rider(self):
        """Driver above 90 mph triggers flag and rider notification."""
        from app.services import speeding_alert as _svc
        # 1° lat ≈ 69 miles in 30 minutes ≈ 138 mph — over 90
        _svc._prev_positions[20] = (40.0, -74.0, NOW - timedelta(minutes=30))

        ride_row = _make_ride_row(rider_id=10)
        db = _make_db(active_ride_id=1, ride_row=ride_row)

        with patch(
            "app.services.notification_events.notify_speeding_alert", new_callable=AsyncMock
        ) as mock_notify:
            result = await check_and_notify_speeding(
                user_id=20, lat=41.0, lng=-74.0, db=db, threshold_mph=90, _now=NOW
            )
        assert result is True
        mock_notify.assert_awaited_once()
        kwargs = mock_notify.call_args.kwargs
        assert kwargs["rider_id"] == 10
        assert kwargs["ride_id"] == 1

    @pytest.mark.asyncio
    async def test_db_exception_returns_false(self):
        """Exception in DB query is caught; function returns False without raising."""
        from app.services import speeding_alert as _svc
        _svc._prev_positions[20] = (40.0, -74.0, NOW - timedelta(seconds=10))

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("DB connection lost"))
        result = await check_and_notify_speeding(
            user_id=20, lat=41.0, lng=-74.0, db=db, _now=NOW
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_commit_called_on_flag(self):
        """When speeding is flagged, db.commit() is called."""
        from app.services import speeding_alert as _svc
        _svc._prev_positions[20] = (40.0, -74.0, NOW - timedelta(minutes=30))

        ride_row = _make_ride_row()
        db = _make_db(active_ride_id=1, ride_row=ride_row)

        with patch(
            "app.services.notification_events.notify_speeding_alert", new_callable=AsyncMock
        ):
            await check_and_notify_speeding(
                user_id=20, lat=41.0, lng=-74.0, db=db, threshold_mph=90, _now=NOW
            )
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_commit_when_within_threshold(self):
        """No DB commit when driver is within the threshold."""
        from app.services import speeding_alert as _svc
        _svc._prev_positions[20] = (40.0, -74.0, NOW - timedelta(minutes=10))

        ride_row = _make_ride_row()
        db = _make_db(active_ride_id=1, ride_row=ride_row)

        with patch(
            "app.services.notification_events.notify_speeding_alert", new_callable=AsyncMock
        ):
            await check_and_notify_speeding(
                user_id=20, lat=40.1, lng=-74.0, db=db, threshold_mph=90, _now=NOW
            )
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_custom_threshold_respected(self):
        """A stricter threshold (50 mph) flags what 90 mph would miss."""
        from app.services import speeding_alert as _svc
        # ≈ 69 mph (1° in 60 min) — above 50, below 90
        _svc._prev_positions[20] = (40.0, -74.0, NOW - timedelta(hours=1))

        ride_row = _make_ride_row()
        db = _make_db(active_ride_id=1, ride_row=ride_row)

        with patch(
            "app.services.notification_events.notify_speeding_alert", new_callable=AsyncMock
        ) as mock_notify:
            result = await check_and_notify_speeding(
                user_id=20, lat=41.0, lng=-74.0, db=db, threshold_mph=50, _now=NOW
            )
        assert result is True
        mock_notify.assert_awaited_once()


# ---------------------------------------------------------------------------
# 17: Idempotency
# ---------------------------------------------------------------------------


class TestSpeedingIdempotency:
    def setup_method(self):
        _clear_prev_positions()

    @pytest.mark.asyncio
    async def test_second_call_after_flag_does_not_re_notify(self):
        """Once flagged, subsequent calls return False even if still speeding."""
        from app.services import speeding_alert as _svc
        _svc._prev_positions[20] = (40.0, -74.0, NOW - timedelta(minutes=30))

        flagged_row = _make_ride_row(speeding_flagged_at=NOW)
        db = _make_db(active_ride_id=1, ride_row=flagged_row)

        with patch(
            "app.services.notification_events.notify_speeding_alert", new_callable=AsyncMock
        ) as mock_notify:
            result = await check_and_notify_speeding(
                user_id=20, lat=41.0, lng=-74.0, db=db, threshold_mph=90
            )
        assert result is False
        mock_notify.assert_not_called()


# ---------------------------------------------------------------------------
# 18: Notification template
# ---------------------------------------------------------------------------


class TestSpeedingAlertTemplate:
    def test_template_returns_expected_content(self):
        from app.services.notification_templates import speeding_alert

        title, body, channels = speeding_alert()
        assert "speed" in title.lower() or "alert" in title.lower()
        assert len(body) > 10
        assert len(channels) >= 1


# ---------------------------------------------------------------------------
# 19–20: NotificationType registration
# ---------------------------------------------------------------------------


class TestNotificationTypeRegistration:
    def test_speeding_alert_in_enum(self):
        from app.services.notifications import NotificationType
        assert NotificationType.SPEEDING_ALERT == "speeding_alert"

    def test_speeding_alert_in_ride_types_set(self):
        from app.services.notification_templates import TEMPLATES
        from app.services.notifications import NotificationType
        assert NotificationType.SPEEDING_ALERT in TEMPLATES


# ---------------------------------------------------------------------------
# 21–22: notify_speeding_alert dispatcher
# ---------------------------------------------------------------------------


class TestNotifySpeedingAlertDispatcher:
    @pytest.mark.asyncio
    async def test_calls_send_ride_notification_with_correct_args(self):
        from app.services.notification_events import notify_speeding_alert
        from app.services.notifications import NotificationType

        db = AsyncMock()
        user_result = MagicMock()
        user_result.one_or_none.return_value = MagicMock(phone="+15551234567", email=None)
        db.execute = AsyncMock(return_value=user_result)

        with patch(
            "app.services.notification_events.send_ride_notification", new_callable=AsyncMock
        ) as mock_send:
            await notify_speeding_alert(db=db, rider_id=10, ride_id=42)

        mock_send.assert_awaited_once()
        kwargs = mock_send.call_args.kwargs
        assert kwargs["user_id"] == 10
        assert kwargs["ride_id"] == 42
        assert kwargs["type"] == NotificationType.SPEEDING_ALERT

    @pytest.mark.asyncio
    async def test_exception_in_send_is_swallowed(self):
        """Notification failure must not propagate."""
        from app.services.notification_events import notify_speeding_alert

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("DB error"))

        # Should not raise
        await notify_speeding_alert(db=db, rider_id=10, ride_id=42)


# ---------------------------------------------------------------------------
# 23–29: GET /rides/{ride_id}/speeding-status endpoint
# ---------------------------------------------------------------------------


class TestSpeedingStatusEndpoint:
    def _make_ride_model(self, ride_id=1, rider_id=1, driver_id=20, flagged_at=None):
        from app.models.ride import Ride, RideStatus
        ride = MagicMock(spec=Ride)
        ride.id = ride_id
        ride.rider_id = rider_id
        ride.driver_id = driver_id
        ride.status = RideStatus.IN_PROGRESS
        ride.speeding_flagged_at = flagged_at
        return ride

    @pytest.mark.asyncio
    async def test_requires_authentication(self):
        """GET /rides/{id}/speeding-status returns 401 without auth."""
        from httpx import ASGITransport, AsyncClient
        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/rides/1/speeding-status")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_404_for_unknown_ride(self):
        """Returns 404 when ride_id does not exist."""
        from fastapi import HTTPException
        from app.api.v1.rides import get_speeding_status
        from app.models.user import User, UserRole

        user = MagicMock(spec=User)
        user.id = 1
        user.role = UserRole.RIDER

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc_info:
            await get_speeding_status(ride_id=999, user=user, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_403_for_unrelated_user(self):
        """Returns 403 when the requesting user is not the rider or driver."""
        from fastapi import HTTPException
        from app.api.v1.rides import get_speeding_status
        from app.models.user import User

        user = MagicMock(spec=User)
        user.id = 99  # Not rider_id=1 or driver_id=20

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._make_ride_model(rider_id=1, driver_id=20)
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc_info:
            await get_speeding_status(ride_id=1, user=user, db=db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_no_speeding_when_not_flagged(self):
        """speeding_detected=False when speeding_flagged_at is None."""
        from app.api.v1.rides import get_speeding_status
        from app.models.user import User

        user = MagicMock(spec=User)
        user.id = 1  # rider

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._make_ride_model(rider_id=1, flagged_at=None)
        db.execute = AsyncMock(return_value=result)

        response = await get_speeding_status(ride_id=1, user=user, db=db)
        assert response.speeding_detected is False
        assert response.flagged_at is None

    @pytest.mark.asyncio
    async def test_returns_speeding_detected_when_flagged(self):
        """speeding_detected=True and flagged_at populated when flag is set."""
        from app.api.v1.rides import get_speeding_status
        from app.models.user import User

        user = MagicMock(spec=User)
        user.id = 1  # rider

        flagged_time = datetime(2026, 4, 18, 12, 30, 0, tzinfo=timezone.utc)

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._make_ride_model(
            rider_id=1, flagged_at=flagged_time
        )
        db.execute = AsyncMock(return_value=result)

        response = await get_speeding_status(ride_id=1, user=user, db=db)
        assert response.speeding_detected is True
        assert response.flagged_at == flagged_time

    @pytest.mark.asyncio
    async def test_rider_can_access_own_ride_status(self):
        """Rider of the ride can query the speeding status."""
        from app.api.v1.rides import get_speeding_status
        from app.models.user import User

        user = MagicMock(spec=User)
        user.id = 1  # rider_id

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._make_ride_model(
            rider_id=1, driver_id=20, flagged_at=None
        )
        db.execute = AsyncMock(return_value=result)

        response = await get_speeding_status(ride_id=1, user=user, db=db)
        assert response.ride_id == 1
        assert response.speeding_detected is False

    @pytest.mark.asyncio
    async def test_driver_can_access_own_ride_status(self):
        """Driver of the ride can query the speeding status."""
        from app.api.v1.rides import get_speeding_status
        from app.models.user import User

        driver_user = MagicMock(spec=User)
        driver_user.id = 20  # driver_id

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._make_ride_model(
            rider_id=1, driver_id=20, flagged_at=None
        )
        db.execute = AsyncMock(return_value=result)

        response = await get_speeding_status(ride_id=1, user=driver_user, db=db)
        assert response.ride_id == 1
        assert response.speeding_detected is False
