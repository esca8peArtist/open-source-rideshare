"""Tests for ride status push notifications — driver + rider coverage.

Covers:
- New NotificationType values: RIDE_IN_PROGRESS, RIDE_ASSIGNED, RIDE_COMPLETED_DRIVER
- New templates: ride_in_progress, ride_assigned, ride_completed_driver
- New dispatchers: notify_ride_started, notify_driver_assigned, notify_ride_completed_driver
- Preference filtering includes new ride types
- Fire-and-forget error resilience for new dispatchers
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.notifications import (
    NotificationChannel,
    NotificationType,
    clear_sent_notifications,
    get_sent_notifications,
)
from app.services.notification_templates import (
    render,
    ride_in_progress,
    ride_assigned,
    ride_completed_driver,
    TEMPLATES,
)


@pytest.fixture(autouse=True)
def clean_notifications():
    clear_sent_notifications()
    yield
    clear_sent_notifications()


@pytest.fixture
def mock_db():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.one_or_none.return_value = MagicMock(phone="+15550001111", email="user@example.com")
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


# ===========================================================================
# NotificationType enum — new values
# ===========================================================================

class TestNewNotificationTypes:
    def test_ride_in_progress_exists(self):
        assert NotificationType.RIDE_IN_PROGRESS == "ride_in_progress"

    def test_ride_assigned_exists(self):
        assert NotificationType.RIDE_ASSIGNED == "ride_assigned"

    def test_ride_completed_driver_exists(self):
        assert NotificationType.RIDE_COMPLETED_DRIVER == "ride_completed_driver"

    def test_all_new_types_constructible_from_string(self):
        assert NotificationType("ride_in_progress") == NotificationType.RIDE_IN_PROGRESS
        assert NotificationType("ride_assigned") == NotificationType.RIDE_ASSIGNED
        assert NotificationType("ride_completed_driver") == NotificationType.RIDE_COMPLETED_DRIVER


# ===========================================================================
# Templates — ride_in_progress
# ===========================================================================

class TestRideInProgressTemplate:
    def test_returns_tuple(self):
        result = ride_in_progress()
        assert len(result) == 3

    def test_title(self):
        title, body, channels = ride_in_progress()
        assert "started" in title.lower()

    def test_body_default(self):
        title, body, channels = ride_in_progress()
        assert "way" in body.lower()

    def test_body_with_dropoff(self):
        title, body, channels = ride_in_progress(dropoff_address="123 Main St")
        assert "123 Main St" in body

    def test_body_without_dropoff(self):
        title, body, channels = ride_in_progress()
        assert "Destination:" not in body

    def test_channels_push_only(self):
        title, body, channels = ride_in_progress()
        assert channels == [NotificationChannel.PUSH]

    def test_registered_in_templates(self):
        assert NotificationType.RIDE_IN_PROGRESS in TEMPLATES

    def test_render_dispatches_to_template(self):
        title, body, channels = render(NotificationType.RIDE_IN_PROGRESS, dropoff_address="456 Oak Ave")
        assert "456 Oak Ave" in body


# ===========================================================================
# Templates — ride_assigned
# ===========================================================================

class TestRideAssignedTemplate:
    def test_returns_tuple(self):
        result = ride_assigned()
        assert len(result) == 3

    def test_title(self):
        title, body, channels = ride_assigned()
        assert "assigned" in title.lower() or "ride" in title.lower()

    def test_body_with_rider_name(self):
        title, body, channels = ride_assigned(rider_name="Alice")
        assert "Alice" in body

    def test_body_default_rider_name(self):
        title, body, channels = ride_assigned()
        assert "rider" in body.lower() or "waiting" in body.lower()

    def test_body_with_pickup_address(self):
        title, body, channels = ride_assigned(pickup_address="789 Elm St")
        assert "789 Elm St" in body

    def test_body_without_pickup_address(self):
        title, body, channels = ride_assigned()
        assert "Pickup:" not in body

    def test_channels_include_push(self):
        title, body, channels = ride_assigned()
        assert NotificationChannel.PUSH in channels

    def test_channels_include_sms(self):
        title, body, channels = ride_assigned()
        assert NotificationChannel.SMS in channels

    def test_registered_in_templates(self):
        assert NotificationType.RIDE_ASSIGNED in TEMPLATES

    def test_render_dispatches_to_template(self):
        title, body, channels = render(NotificationType.RIDE_ASSIGNED, rider_name="Bob", pickup_address="10 Park Ln")
        assert "Bob" in body
        assert "10 Park Ln" in body


# ===========================================================================
# Templates — ride_completed_driver
# ===========================================================================

class TestRideCompletedDriverTemplate:
    def test_returns_tuple(self):
        result = ride_completed_driver()
        assert len(result) == 3

    def test_title(self):
        title, body, channels = ride_completed_driver()
        assert "complete" in title.lower()

    def test_body_with_fare(self):
        title, body, channels = ride_completed_driver(fare=18.50)
        assert "18.5" in body

    def test_body_without_fare(self):
        title, body, channels = ride_completed_driver()
        assert "Earnings:" not in body

    def test_channels_push_only(self):
        title, body, channels = ride_completed_driver()
        assert channels == [NotificationChannel.PUSH]

    def test_registered_in_templates(self):
        assert NotificationType.RIDE_COMPLETED_DRIVER in TEMPLATES

    def test_render_dispatches_to_template(self):
        title, body, channels = render(NotificationType.RIDE_COMPLETED_DRIVER, fare=22.00)
        assert "22" in body


# ===========================================================================
# Dispatchers — notify_ride_started
# ===========================================================================

class TestNotifyRideStarted:
    @pytest.mark.asyncio
    async def test_sends_ride_in_progress_to_rider(self, mock_db):
        from app.services.notification_events import notify_ride_started
        await notify_ride_started(mock_db, rider_id=7, ride_id=99)
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].type == NotificationType.RIDE_IN_PROGRESS
        assert log[0].user_id == 7
        assert log[0].ride_id == 99

    @pytest.mark.asyncio
    async def test_passes_dropoff_address(self, mock_db):
        from app.services.notification_events import notify_ride_started
        await notify_ride_started(mock_db, rider_id=7, ride_id=99, dropoff_address="500 Broadway")
        log = get_sent_notifications()
        assert "500 Broadway" in log[0].body

    @pytest.mark.asyncio
    async def test_fire_and_forget_on_db_error(self):
        from app.services.notification_events import notify_ride_started
        bad_db = AsyncMock()
        bad_db.execute = AsyncMock(side_effect=Exception("DB down"))
        await notify_ride_started(bad_db, rider_id=1, ride_id=5)  # must not raise

    @pytest.mark.asyncio
    async def test_works_with_no_contact_info(self):
        from app.services.notification_events import notify_ride_started
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        db.add = MagicMock()
        db.flush = AsyncMock()
        await notify_ride_started(db, rider_id=1, ride_id=10)
        log = get_sent_notifications()
        assert len(log) == 1


# ===========================================================================
# Dispatchers — notify_driver_assigned
# ===========================================================================

class TestNotifyDriverAssigned:
    @pytest.mark.asyncio
    async def test_sends_ride_assigned_to_driver(self, mock_db):
        from app.services.notification_events import notify_driver_assigned
        await notify_driver_assigned(mock_db, driver_id=3, ride_id=55)
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].type == NotificationType.RIDE_ASSIGNED
        assert log[0].user_id == 3
        assert log[0].ride_id == 55

    @pytest.mark.asyncio
    async def test_passes_rider_name_and_pickup(self, mock_db):
        from app.services.notification_events import notify_driver_assigned
        await notify_driver_assigned(
            mock_db, driver_id=3, ride_id=55,
            rider_name="Carol", pickup_address="200 5th Ave",
        )
        log = get_sent_notifications()
        assert "Carol" in log[0].body
        assert "200 5th Ave" in log[0].body

    @pytest.mark.asyncio
    async def test_fire_and_forget_on_db_error(self):
        from app.services.notification_events import notify_driver_assigned
        bad_db = AsyncMock()
        bad_db.execute = AsyncMock(side_effect=RuntimeError("Network error"))
        await notify_driver_assigned(bad_db, driver_id=1, ride_id=5)  # must not raise

    @pytest.mark.asyncio
    async def test_works_with_no_contact_info(self):
        from app.services.notification_events import notify_driver_assigned
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        db.add = MagicMock()
        db.flush = AsyncMock()
        await notify_driver_assigned(db, driver_id=2, ride_id=20)
        log = get_sent_notifications()
        assert len(log) == 1


# ===========================================================================
# Dispatchers — notify_ride_completed_driver
# ===========================================================================

class TestNotifyRideCompletedDriver:
    @pytest.mark.asyncio
    async def test_sends_ride_completed_driver_to_driver(self, mock_db):
        from app.services.notification_events import notify_ride_completed_driver
        await notify_ride_completed_driver(mock_db, driver_id=4, ride_id=77, fare=31.25)
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].type == NotificationType.RIDE_COMPLETED_DRIVER
        assert log[0].user_id == 4
        assert log[0].ride_id == 77

    @pytest.mark.asyncio
    async def test_fare_appears_in_body(self, mock_db):
        from app.services.notification_events import notify_ride_completed_driver
        await notify_ride_completed_driver(mock_db, driver_id=4, ride_id=77, fare=31.25)
        log = get_sent_notifications()
        assert "31.25" in log[0].body

    @pytest.mark.asyncio
    async def test_fire_and_forget_on_db_error(self):
        from app.services.notification_events import notify_ride_completed_driver
        bad_db = AsyncMock()
        bad_db.execute = AsyncMock(side_effect=Exception("Timeout"))
        await notify_ride_completed_driver(bad_db, driver_id=1, ride_id=5, fare=10.00)  # must not raise

    @pytest.mark.asyncio
    async def test_works_with_no_fare(self, mock_db):
        from app.services.notification_events import notify_ride_completed_driver
        await notify_ride_completed_driver(mock_db, driver_id=4, ride_id=77)
        log = get_sent_notifications()
        assert len(log) == 1
        assert "Earnings:" not in log[0].body


# ===========================================================================
# Preference filtering — new types treated as ride_updates
# ===========================================================================

class TestPreferenceFilteringNewTypes:
    @pytest.mark.asyncio
    async def test_ride_in_progress_filtered_when_ride_updates_off(self):
        from app.services.notifications import filter_channels_by_preferences
        db = AsyncMock()
        mock_result = MagicMock()
        prefs = MagicMock()
        prefs.ride_updates = False
        prefs.push_enabled = True
        prefs.sms_enabled = True
        prefs.email_enabled = True
        prefs.payment_updates = True
        prefs.promo_updates = True
        mock_result.scalar_one_or_none.return_value = prefs
        db.execute = AsyncMock(return_value=mock_result)

        result = await filter_channels_by_preferences(
            [NotificationChannel.PUSH], db, user_id=1,
            notification_type=NotificationType.RIDE_IN_PROGRESS,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_ride_assigned_filtered_when_ride_updates_off(self):
        from app.services.notifications import filter_channels_by_preferences
        db = AsyncMock()
        mock_result = MagicMock()
        prefs = MagicMock()
        prefs.ride_updates = False
        prefs.push_enabled = True
        prefs.sms_enabled = True
        prefs.email_enabled = True
        prefs.payment_updates = True
        prefs.promo_updates = True
        mock_result.scalar_one_or_none.return_value = prefs
        db.execute = AsyncMock(return_value=mock_result)

        result = await filter_channels_by_preferences(
            [NotificationChannel.PUSH, NotificationChannel.SMS], db, user_id=2,
            notification_type=NotificationType.RIDE_ASSIGNED,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_ride_completed_driver_filtered_when_ride_updates_off(self):
        from app.services.notifications import filter_channels_by_preferences
        db = AsyncMock()
        mock_result = MagicMock()
        prefs = MagicMock()
        prefs.ride_updates = False
        prefs.push_enabled = True
        prefs.sms_enabled = True
        prefs.email_enabled = True
        prefs.payment_updates = True
        prefs.promo_updates = True
        mock_result.scalar_one_or_none.return_value = prefs
        db.execute = AsyncMock(return_value=mock_result)

        result = await filter_channels_by_preferences(
            [NotificationChannel.PUSH], db, user_id=3,
            notification_type=NotificationType.RIDE_COMPLETED_DRIVER,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_ride_assigned_passes_when_ride_updates_on(self):
        from app.services.notifications import filter_channels_by_preferences
        db = AsyncMock()
        mock_result = MagicMock()
        prefs = MagicMock()
        prefs.ride_updates = True
        prefs.push_enabled = True
        prefs.sms_enabled = True
        prefs.email_enabled = False
        prefs.payment_updates = True
        prefs.promo_updates = True
        mock_result.scalar_one_or_none.return_value = prefs
        db.execute = AsyncMock(return_value=mock_result)

        result = await filter_channels_by_preferences(
            [NotificationChannel.PUSH, NotificationChannel.SMS], db, user_id=4,
            notification_type=NotificationType.RIDE_ASSIGNED,
        )
        assert NotificationChannel.PUSH in result
        assert NotificationChannel.SMS in result
