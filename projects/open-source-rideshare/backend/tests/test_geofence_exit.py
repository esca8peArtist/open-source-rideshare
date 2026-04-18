"""Unit tests for driver geofence exit detection.

Covers:
check_and_notify_geofence_exit service:
  1.  No active IN_PROGRESS ride — returns False without notification
  2.  Ride already flagged — returns False, no second notification
  3.  Ride row not found — returns False gracefully
  4.  No active service areas configured — returns False (no boundary)
  5.  Driver inside a service area — returns False
  6.  Driver outside all service areas — returns True, rider notified, driver notified
  7.  DB error in find_active_ride — returns False without raising
  8.  commit called when geofence exit flagged
  9.  No commit when driver is inside service area
  10. No commit when no active ride

Idempotency:
  11. Second call after flag set — returns False, no re-notify

Notification templates:
  12. geofence_exit template returns correct title/body/channels for rider (PUSH+SMS)
  13. driver_geofence_exit template returns correct title/body/channels (PUSH only)

NotificationType registration:
  14. GEOFENCE_EXIT in NotificationType enum
  15. DRIVER_GEOFENCE_EXIT in NotificationType enum
  16. Both types registered in TEMPLATES

notify_geofence_exit dispatcher:
  17. Calls send_ride_notification with correct args (rider)
  18. Exception in send_ride_notification is swallowed

notify_driver_geofence_exit dispatcher:
  19. Calls send_ride_notification with correct args (driver)
  20. Exception is swallowed

Helper functions:
  21. _find_active_ride_id returns None when no IN_PROGRESS ride
  22. _get_ride_alert_info returns None when ride not found
  23. _any_active_service_areas returns False when no rows
  24. _any_active_service_areas returns True when rows exist
  25. _driver_within_any_service_area returns False when no match
  26. _driver_within_any_service_area returns True when match
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.geofence_exit import (
    _any_active_service_areas,
    _driver_within_any_service_area,
    _find_active_ride_id,
    _get_ride_alert_info,
    check_and_notify_geofence_exit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)


def _make_ride_row(rider_id=10, geofence_exit_alerted_at=None):
    row = MagicMock()
    row.rider_id = rider_id
    row.geofence_exit_alerted_at = geofence_exit_alerted_at
    return row


def _make_db(
    active_ride_id=1,
    ride_row=None,
    any_service_areas=True,
    driver_inside=False,
):
    """Build a mock AsyncSession for check_and_notify_geofence_exit.

    Execute call order:
      1. _find_active_ride_id  → .first()
      2. _get_ride_alert_info  → .one_or_none()
      3. _any_active_service_areas → .scalar_one_or_none()
      4. _driver_within_any_service_area → .scalar_one_or_none()
      5. UPDATE (idempotency guard) — no return used
    """
    db = AsyncMock()

    # 1. find active ride
    r1 = MagicMock()
    if active_ride_id is None:
        r1.first.return_value = None
    else:
        r1.first.return_value = (active_ride_id,)

    # 2. fetch ride alert info
    r2 = MagicMock()
    r2.one_or_none.return_value = ride_row

    # 3. any active service areas
    r3 = MagicMock()
    r3.scalar_one_or_none.return_value = 1 if any_service_areas else None

    # 4. driver within service area
    r4 = MagicMock()
    r4.scalar_one_or_none.return_value = 1 if driver_inside else None

    # 5. UPDATE
    r5 = MagicMock()

    db.execute = AsyncMock(side_effect=[r1, r2, r3, r4, r5])
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# 1–10: check_and_notify_geofence_exit service tests
# ---------------------------------------------------------------------------


class TestCheckAndNotifyGeofenceExit:
    @pytest.mark.asyncio
    async def test_no_active_ride_returns_false(self):
        """If driver has no IN_PROGRESS ride, return False without notifying."""
        db = _make_db(active_ride_id=None)
        with patch("app.services.notification_events.notify_geofence_exit") as mock_rider, \
             patch("app.services.notification_events.notify_driver_geofence_exit") as mock_driver:
            result = await check_and_notify_geofence_exit(user_id=20, lat=40.7, lng=-74.0, db=db)
        assert result is False
        mock_rider.assert_not_called()
        mock_driver.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_flagged_returns_false(self):
        """Ride with geofence_exit_alerted_at already set is not re-notified."""
        ride_row = _make_ride_row(geofence_exit_alerted_at=NOW)
        db = _make_db(active_ride_id=1, ride_row=ride_row)
        with patch("app.services.notification_events.notify_geofence_exit", new_callable=AsyncMock) as mock_rider:
            result = await check_and_notify_geofence_exit(user_id=20, lat=40.7, lng=-74.0, db=db)
        assert result is False
        mock_rider.assert_not_called()

    @pytest.mark.asyncio
    async def test_ride_row_not_found_returns_false(self):
        """If ride row query returns None, return False gracefully."""
        db = _make_db(active_ride_id=1, ride_row=None)
        with patch("app.services.notification_events.notify_geofence_exit", new_callable=AsyncMock) as mock_notify:
            result = await check_and_notify_geofence_exit(user_id=20, lat=40.7, lng=-74.0, db=db)
        assert result is False
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_service_areas_returns_false(self):
        """If no active service areas exist, return False (boundary not configured)."""
        ride_row = _make_ride_row()
        db = _make_db(active_ride_id=1, ride_row=ride_row, any_service_areas=False)
        with patch("app.services.notification_events.notify_geofence_exit", new_callable=AsyncMock) as mock_notify:
            result = await check_and_notify_geofence_exit(user_id=20, lat=40.7, lng=-74.0, db=db)
        assert result is False
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_driver_inside_returns_false(self):
        """If driver is within a service area, return False."""
        ride_row = _make_ride_row()
        db = _make_db(active_ride_id=1, ride_row=ride_row, any_service_areas=True, driver_inside=True)
        with patch("app.services.notification_events.notify_geofence_exit", new_callable=AsyncMock) as mock_notify:
            result = await check_and_notify_geofence_exit(user_id=20, lat=40.7, lng=-74.0, db=db)
        assert result is False
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_driver_outside_notifies_rider_and_driver(self):
        """Driver outside all service areas → returns True, notifies rider and driver."""
        ride_row = _make_ride_row(rider_id=10)
        db = _make_db(active_ride_id=1, ride_row=ride_row, any_service_areas=True, driver_inside=False)
        with patch("app.services.notification_events.notify_geofence_exit", new_callable=AsyncMock) as mock_rider, \
             patch("app.services.notification_events.notify_driver_geofence_exit", new_callable=AsyncMock) as mock_driver:
            result = await check_and_notify_geofence_exit(user_id=20, lat=40.7, lng=-74.0, db=db)
        assert result is True
        mock_rider.assert_awaited_once()
        mock_driver.assert_awaited_once()
        # Verify rider notification args
        rider_kwargs = mock_rider.call_args.kwargs
        assert rider_kwargs["rider_id"] == 10
        assert rider_kwargs["ride_id"] == 1
        # Verify driver notification args
        driver_kwargs = mock_driver.call_args.kwargs
        assert driver_kwargs["driver_user_id"] == 20
        assert driver_kwargs["ride_id"] == 1

    @pytest.mark.asyncio
    async def test_db_exception_returns_false(self):
        """Exception during DB query is caught; function returns False without raising."""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("DB connection lost"))
        result = await check_and_notify_geofence_exit(user_id=20, lat=40.7, lng=-74.0, db=db)
        assert result is False

    @pytest.mark.asyncio
    async def test_commit_called_on_flag(self):
        """When geofence exit is flagged, db.commit() is called."""
        ride_row = _make_ride_row()
        db = _make_db(active_ride_id=1, ride_row=ride_row, any_service_areas=True, driver_inside=False)
        with patch("app.services.notification_events.notify_geofence_exit", new_callable=AsyncMock), \
             patch("app.services.notification_events.notify_driver_geofence_exit", new_callable=AsyncMock):
            await check_and_notify_geofence_exit(user_id=20, lat=40.7, lng=-74.0, db=db)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_commit_when_driver_inside(self):
        """No DB commit when driver is within a service area."""
        ride_row = _make_ride_row()
        db = _make_db(active_ride_id=1, ride_row=ride_row, any_service_areas=True, driver_inside=True)
        with patch("app.services.notification_events.notify_geofence_exit", new_callable=AsyncMock):
            await check_and_notify_geofence_exit(user_id=20, lat=40.7, lng=-74.0, db=db)
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_commit_when_no_active_ride(self):
        """No DB commit when no active IN_PROGRESS ride exists."""
        db = _make_db(active_ride_id=None)
        with patch("app.services.notification_events.notify_geofence_exit", new_callable=AsyncMock):
            await check_and_notify_geofence_exit(user_id=20, lat=40.7, lng=-74.0, db=db)
        db.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# 11: Idempotency
# ---------------------------------------------------------------------------


class TestGeofenceExitIdempotency:
    @pytest.mark.asyncio
    async def test_second_call_does_not_re_notify(self):
        """Once flagged, subsequent calls return False even if driver is still outside."""
        flagged_row = _make_ride_row(geofence_exit_alerted_at=NOW)
        db = _make_db(active_ride_id=1, ride_row=flagged_row)
        with patch("app.services.notification_events.notify_geofence_exit", new_callable=AsyncMock) as mock_notify:
            result = await check_and_notify_geofence_exit(user_id=20, lat=40.7, lng=-74.0, db=db)
        assert result is False
        mock_notify.assert_not_called()


# ---------------------------------------------------------------------------
# 12–13: Notification templates
# ---------------------------------------------------------------------------


class TestGeofenceExitTemplates:
    def test_rider_template_channels_are_push_sms(self):
        from app.services.notification_templates import geofence_exit
        from app.services.notifications import NotificationChannel

        title, body, channels = geofence_exit()
        assert title
        assert body
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS in channels

    def test_driver_template_channel_is_push_only(self):
        from app.services.notification_templates import driver_geofence_exit
        from app.services.notifications import NotificationChannel

        title, body, channels = driver_geofence_exit()
        assert title
        assert body
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS not in channels


# ---------------------------------------------------------------------------
# 14–16: NotificationType registration
# ---------------------------------------------------------------------------


class TestNotificationTypeRegistration:
    def test_geofence_exit_in_enum(self):
        from app.services.notifications import NotificationType

        assert NotificationType.GEOFENCE_EXIT == "geofence_exit"

    def test_driver_geofence_exit_in_enum(self):
        from app.services.notifications import NotificationType

        assert NotificationType.DRIVER_GEOFENCE_EXIT == "driver_geofence_exit"

    def test_both_types_in_templates(self):
        from app.services.notification_templates import TEMPLATES
        from app.services.notifications import NotificationType

        assert NotificationType.GEOFENCE_EXIT in TEMPLATES
        assert NotificationType.DRIVER_GEOFENCE_EXIT in TEMPLATES


# ---------------------------------------------------------------------------
# 17–20: Notification dispatcher tests
# ---------------------------------------------------------------------------


class TestNotifyGeofenceExitDispatcher:
    @pytest.mark.asyncio
    async def test_rider_dispatcher_calls_send_with_correct_args(self):
        from app.services.notification_events import notify_geofence_exit
        from app.services.notifications import NotificationType

        db = AsyncMock()
        user_result = MagicMock()
        user_result.one_or_none.return_value = MagicMock(phone="+15551234567", email=None)
        db.execute = AsyncMock(return_value=user_result)

        with patch(
            "app.services.notification_events.send_ride_notification", new_callable=AsyncMock
        ) as mock_send:
            await notify_geofence_exit(db=db, rider_id=10, ride_id=42)

        mock_send.assert_awaited_once()
        kwargs = mock_send.call_args.kwargs
        assert kwargs["user_id"] == 10
        assert kwargs["ride_id"] == 42
        assert kwargs["type"] == NotificationType.GEOFENCE_EXIT

    @pytest.mark.asyncio
    async def test_rider_dispatcher_swallows_exception(self):
        from app.services.notification_events import notify_geofence_exit

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("DB error"))
        # Must not raise
        await notify_geofence_exit(db=db, rider_id=10, ride_id=42)

    @pytest.mark.asyncio
    async def test_driver_dispatcher_calls_send_with_correct_args(self):
        from app.services.notification_events import notify_driver_geofence_exit
        from app.services.notifications import NotificationType

        db = AsyncMock()
        user_result = MagicMock()
        user_result.one_or_none.return_value = MagicMock(phone="+15559876543", email=None)
        db.execute = AsyncMock(return_value=user_result)

        with patch(
            "app.services.notification_events.send_ride_notification", new_callable=AsyncMock
        ) as mock_send:
            await notify_driver_geofence_exit(db=db, driver_user_id=20, ride_id=42)

        mock_send.assert_awaited_once()
        kwargs = mock_send.call_args.kwargs
        assert kwargs["user_id"] == 20
        assert kwargs["ride_id"] == 42
        assert kwargs["type"] == NotificationType.DRIVER_GEOFENCE_EXIT

    @pytest.mark.asyncio
    async def test_driver_dispatcher_swallows_exception(self):
        from app.services.notification_events import notify_driver_geofence_exit

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("DB error"))
        # Must not raise
        await notify_driver_geofence_exit(db=db, driver_user_id=20, ride_id=42)


# ---------------------------------------------------------------------------
# 21–26: Helper function unit tests
# ---------------------------------------------------------------------------


class TestGeofenceExitHelpers:
    @pytest.mark.asyncio
    async def test_find_active_ride_returns_none_when_no_ride(self):
        db = AsyncMock()
        result = MagicMock()
        result.first.return_value = None
        db.execute = AsyncMock(return_value=result)
        ride_id = await _find_active_ride_id(db, driver_user_id=20)
        assert ride_id is None

    @pytest.mark.asyncio
    async def test_find_active_ride_returns_id(self):
        db = AsyncMock()
        result = MagicMock()
        result.first.return_value = (7,)
        db.execute = AsyncMock(return_value=result)
        ride_id = await _find_active_ride_id(db, driver_user_id=20)
        assert ride_id == 7

    @pytest.mark.asyncio
    async def test_get_ride_alert_info_returns_none_when_not_found(self):
        db = AsyncMock()
        result = MagicMock()
        result.one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)
        row = await _get_ride_alert_info(db, ride_id=999)
        assert row is None

    @pytest.mark.asyncio
    async def test_any_active_service_areas_false_when_empty(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)
        assert await _any_active_service_areas(db) is False

    @pytest.mark.asyncio
    async def test_any_active_service_areas_true_when_exists(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = 1
        db.execute = AsyncMock(return_value=result)
        assert await _any_active_service_areas(db) is True

    @pytest.mark.asyncio
    async def test_driver_within_service_area_false_when_no_match(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)
        assert await _driver_within_any_service_area(db, lat=40.0, lng=-74.0) is False

    @pytest.mark.asyncio
    async def test_driver_within_service_area_true_when_match(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = 3  # service area id
        db.execute = AsyncMock(return_value=result)
        assert await _driver_within_any_service_area(db, lat=40.0, lng=-74.0) is True
