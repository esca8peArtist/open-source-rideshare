"""Unit tests for scheduled ride push/SMS reminders."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ride import Ride, RideStatus
from app.services.dispatch_scheduler import send_scheduled_ride_reminders

NOW = datetime(2026, 4, 12, 14, 0, 0, tzinfo=timezone.utc)


def _make_ride(
    ride_id,
    rider_id,
    scheduled_for,
    status=RideStatus.SCHEDULED,
    reminder_1hr_sent_at=None,
    reminder_15min_sent_at=None,
    pickup_address="123 Main St",
):
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.status = status
    ride.scheduled_for = scheduled_for
    ride.pickup_address = pickup_address
    ride.reminder_1hr_sent_at = reminder_1hr_sent_at
    ride.reminder_15min_sent_at = reminder_15min_sent_at
    return ride


def _make_user(user_id, phone="+15550001234"):
    user = MagicMock()
    user.id = user_id
    user.phone = phone
    return user


def _build_db(rides, rider):
    """Build a mock async DB session.

    execute() returns rides result on the first call, and rider result on
    subsequent calls (one per reminder sent).
    """
    rides_scalars = MagicMock()
    rides_scalars.all.return_value = rides
    rides_result = MagicMock()
    rides_result.scalars.return_value = rides_scalars

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = rider

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[rides_result] + [user_result] * 20)
    db.commit = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=ctx)
    return factory, db


def _build_db_multi_user(rides, riders_by_user_id):
    """Build a mock DB that returns different riders per ride."""
    rides_scalars = MagicMock()
    rides_scalars.all.return_value = rides
    rides_result = MagicMock()
    rides_result.scalars.return_value = rides_scalars

    user_results = []
    for ride in rides:
        ur = MagicMock()
        ur.scalar_one_or_none.return_value = riders_by_user_id.get(ride.rider_id)
        user_results.append(ur)

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[rides_result] + user_results)
    db.commit = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=ctx)
    return factory, db


class TestSendScheduledRideReminders:
    """Tests for send_scheduled_ride_reminders()."""

    @pytest.mark.asyncio
    async def test_sends_1hr_reminder_for_ride_60_min_away(self):
        """Ride 60 minutes out with no prior reminder triggers 1hr notification."""
        ride = _make_ride(1, 10, NOW + timedelta(minutes=60))
        rider = _make_user(10)
        factory, db = _build_db([ride], rider)

        with (
            patch("app.db.database.async_session", factory),
            patch(
                "app.services.notifications.send_ride_notification",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_notify,
        ):
            count = await send_scheduled_ride_reminders(now=NOW)

        assert count == 1
        mock_notify.assert_called_once()
        call_kwargs = mock_notify.call_args.kwargs
        assert call_kwargs["ride_id"] == 1
        assert call_kwargs["user_id"] == 10
        assert ride.reminder_1hr_sent_at == NOW

    @pytest.mark.asyncio
    async def test_sends_15min_reminder_for_ride_15_min_away(self):
        """Ride 15 minutes out triggers 15-minute reminder."""
        ride = _make_ride(2, 11, NOW + timedelta(minutes=15))
        rider = _make_user(11)
        factory, db = _build_db([ride], rider)

        with (
            patch("app.db.database.async_session", factory),
            patch(
                "app.services.notifications.send_ride_notification",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_notify,
        ):
            count = await send_scheduled_ride_reminders(now=NOW)

        assert count == 1
        mock_notify.assert_called_once()
        assert ride.reminder_15min_sent_at == NOW

    @pytest.mark.asyncio
    async def test_skips_1hr_reminder_already_sent(self):
        """Ride with reminder_1hr_sent_at already set is not re-notified."""
        ride = _make_ride(
            3, 12, NOW + timedelta(minutes=60),
            reminder_1hr_sent_at=NOW - timedelta(minutes=2),
        )
        factory, db = _build_db([ride], _make_user(12))

        with (
            patch("app.db.database.async_session", factory),
            patch(
                "app.services.notifications.send_ride_notification",
                new_callable=AsyncMock,
            ) as mock_notify,
        ):
            count = await send_scheduled_ride_reminders(now=NOW)

        assert count == 0
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_15min_reminder_already_sent(self):
        """Ride with reminder_15min_sent_at already set is not re-notified."""
        ride = _make_ride(
            4, 13, NOW + timedelta(minutes=10),
            reminder_15min_sent_at=NOW - timedelta(minutes=5),
        )
        factory, db = _build_db([ride], _make_user(13))

        with (
            patch("app.db.database.async_session", factory),
            patch(
                "app.services.notifications.send_ride_notification",
                new_callable=AsyncMock,
            ) as mock_notify,
        ):
            count = await send_scheduled_ride_reminders(now=NOW)

        assert count == 0
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_reminder_for_ride_2_hours_away(self):
        """Ride 2 hours out is outside both reminder windows."""
        ride = _make_ride(5, 14, NOW + timedelta(hours=2))
        factory, db = _build_db([ride], _make_user(14))

        with (
            patch("app.db.database.async_session", factory),
            patch(
                "app.services.notifications.send_ride_notification",
                new_callable=AsyncMock,
            ) as mock_notify,
        ):
            count = await send_scheduled_ride_reminders(now=NOW)

        assert count == 0
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_ride_list_returns_zero(self):
        """No scheduled rides means zero reminders sent."""
        factory, db = _build_db([], None)

        with (
            patch("app.db.database.async_session", factory),
            patch(
                "app.services.notifications.send_ride_notification",
                new_callable=AsyncMock,
            ) as mock_notify,
        ):
            count = await send_scheduled_ride_reminders(now=NOW)

        assert count == 0
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_both_reminders_for_different_rides(self):
        """Two rides in different windows each get one reminder."""
        ride_1hr = _make_ride(6, 20, NOW + timedelta(minutes=55))
        ride_15min = _make_ride(7, 21, NOW + timedelta(minutes=12))
        rider20 = _make_user(20)
        rider21 = _make_user(21)
        factory, db = _build_db_multi_user(
            [ride_1hr, ride_15min],
            {20: rider20, 21: rider21},
        )

        with (
            patch("app.db.database.async_session", factory),
            patch(
                "app.services.notifications.send_ride_notification",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_notify,
        ):
            count = await send_scheduled_ride_reminders(now=NOW)

        assert count == 2
        assert mock_notify.call_count == 2
        assert ride_1hr.reminder_1hr_sent_at == NOW
        assert ride_15min.reminder_15min_sent_at == NOW

    @pytest.mark.asyncio
    async def test_notification_failure_does_not_update_sent_at(self):
        """If notification raises, reminder_1hr_sent_at stays None so next cycle retries."""
        ride = _make_ride(8, 30, NOW + timedelta(minutes=50))
        factory, db = _build_db([ride], _make_user(30))

        with (
            patch("app.db.database.async_session", factory),
            patch(
                "app.services.notifications.send_ride_notification",
                new_callable=AsyncMock,
                side_effect=Exception("Twilio down"),
            ),
        ):
            count = await send_scheduled_ride_reminders(now=NOW)

        assert count == 0
        assert ride.reminder_1hr_sent_at is None

    @pytest.mark.asyncio
    async def test_ride_at_upper_boundary_of_1hr_window(self):
        """Ride exactly 65 minutes away is within the 1hr window."""
        ride = _make_ride(9, 40, NOW + timedelta(minutes=65))
        factory, db = _build_db([ride], _make_user(40))

        with (
            patch("app.db.database.async_session", factory),
            patch(
                "app.services.notifications.send_ride_notification",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            count = await send_scheduled_ride_reminders(now=NOW)

        assert count == 1
        assert ride.reminder_1hr_sent_at == NOW
        assert ride.reminder_15min_sent_at is None

    @pytest.mark.asyncio
    async def test_naive_scheduled_for_treated_as_utc(self):
        """Naive datetime in scheduled_for is normalised to UTC and processed."""
        naive_time = datetime(2026, 4, 12, 14, 55, 0)  # 55 min from NOW, no tzinfo
        ride = _make_ride(10, 50, naive_time)
        factory, db = _build_db([ride], _make_user(50))

        with (
            patch("app.db.database.async_session", factory),
            patch(
                "app.services.notifications.send_ride_notification",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_notify,
        ):
            count = await send_scheduled_ride_reminders(now=NOW)

        assert count == 1
        mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_ride_with_1hr_reminder_gets_15min_when_close(self):
        """Ride that already got 1hr reminder gets 15min reminder when in that window."""
        ride = _make_ride(
            11, 60, NOW + timedelta(minutes=14),
            reminder_1hr_sent_at=NOW - timedelta(minutes=46),
        )
        factory, db = _build_db([ride], _make_user(60))

        with (
            patch("app.db.database.async_session", factory),
            patch(
                "app.services.notifications.send_ride_notification",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_notify,
        ):
            count = await send_scheduled_ride_reminders(now=NOW)

        assert count == 1
        assert ride.reminder_15min_sent_at == NOW
        mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_pickup_time_and_address_in_notification_kwargs(self):
        """Notification includes pickup_time and pickup_address in kwargs."""
        ride = _make_ride(12, 70, NOW + timedelta(minutes=60), pickup_address="42 Elm St")
        factory, db = _build_db([ride], _make_user(70))

        with (
            patch("app.db.database.async_session", factory),
            patch(
                "app.services.notifications.send_ride_notification",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_notify,
        ):
            await send_scheduled_ride_reminders(now=NOW)

        call_kwargs = mock_notify.call_args.kwargs
        assert call_kwargs["pickup_address"] == "42 Elm St"
        assert "pickup_time" in call_kwargs

    @pytest.mark.asyncio
    async def test_rider_phone_passed_to_notification(self):
        """Rider's phone number is extracted and passed for SMS delivery."""
        ride = _make_ride(13, 80, NOW + timedelta(minutes=45))
        rider = _make_user(80, phone="+15559876543")
        factory, db = _build_db([ride], rider)

        with (
            patch("app.db.database.async_session", factory),
            patch(
                "app.services.notifications.send_ride_notification",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_notify,
        ):
            await send_scheduled_ride_reminders(now=NOW)

        call_kwargs = mock_notify.call_args.kwargs
        assert call_kwargs["phone"] == "+15559876543"

    @pytest.mark.asyncio
    async def test_missing_rider_sends_notification_without_phone(self):
        """If rider not found in DB, notification is sent with phone=None."""
        ride = _make_ride(14, 90, NOW + timedelta(minutes=45))
        factory, db = _build_db([ride], None)  # rider not found

        with (
            patch("app.db.database.async_session", factory),
            patch(
                "app.services.notifications.send_ride_notification",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_notify,
        ):
            count = await send_scheduled_ride_reminders(now=NOW)

        assert count == 1
        call_kwargs = mock_notify.call_args.kwargs
        assert call_kwargs["phone"] is None
