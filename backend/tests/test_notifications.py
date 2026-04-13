"""Unit tests for the notification service stub."""

import pytest

from app.services.notifications import (
    Notification,
    NotificationChannel,
    NotificationType,
    clear_sent_notifications,
    get_sent_notifications,
    send_notification,
    send_ride_notification,
)


@pytest.fixture(autouse=True)
def clean_notifications():
    clear_sent_notifications()
    yield
    clear_sent_notifications()


class TestNotificationModel:
    def test_default_channel_is_push(self):
        n = Notification(user_id=1, type=NotificationType.RIDE_MATCHED, title="Hi", body="Test")
        assert n.channels == [NotificationChannel.PUSH]

    def test_custom_channels(self):
        n = Notification(
            user_id=1,
            type=NotificationType.SOS_ALERT,
            title="SOS",
            body="Emergency",
            channels=[NotificationChannel.SMS, NotificationChannel.PUSH],
        )
        assert NotificationChannel.SMS in n.channels
        assert NotificationChannel.PUSH in n.channels

    def test_data_field_optional(self):
        n = Notification(user_id=1, type=NotificationType.RIDE_COMPLETED, title="Done", body="Done")
        assert n.data is None

    def test_data_field_set(self):
        n = Notification(
            user_id=1, type=NotificationType.RIDE_COMPLETED,
            title="Done", body="Done", data={"ride_id": 42}
        )
        assert n.data["ride_id"] == 42


class TestNotificationChannelEnum:
    def test_push(self):
        assert NotificationChannel.PUSH == "push"

    def test_sms(self):
        assert NotificationChannel.SMS == "sms"

    def test_email(self):
        assert NotificationChannel.EMAIL == "email"


class TestNotificationTypeEnum:
    def test_all_types_exist(self):
        expected = [
            "ride_matched", "ride_cancelled", "ride_completed",
            "driver_en_route", "driver_arrived", "payment_received",
            "sos_alert", "rating_received", "account_verification",
        ]
        for t in expected:
            assert NotificationType(t) is not None


class TestSendNotification:
    @pytest.mark.asyncio
    async def test_send_returns_true(self):
        n = Notification(user_id=1, type=NotificationType.RIDE_MATCHED, title="Hi", body="Test")
        result = await send_notification(n)
        assert result is True

    @pytest.mark.asyncio
    async def test_send_records_in_log(self):
        n = Notification(user_id=1, type=NotificationType.RIDE_MATCHED, title="Hi", body="Test")
        await send_notification(n)
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].user_id == 1

    @pytest.mark.asyncio
    async def test_multiple_sends_accumulate(self):
        for i in range(3):
            n = Notification(user_id=i, type=NotificationType.RIDE_COMPLETED, title="Done", body="Done")
            await send_notification(n)
        assert len(get_sent_notifications()) == 3


class TestSendRideNotification:
    @pytest.mark.asyncio
    async def test_ride_matched_notification(self):
        result = await send_ride_notification(
            user_id=10, type=NotificationType.RIDE_MATCHED, ride_id=42
        )
        assert result is True
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].title == "Driver matched!"
        assert log[0].data["ride_id"] == 42

    @pytest.mark.asyncio
    async def test_ride_cancelled_notification(self):
        await send_ride_notification(user_id=10, type=NotificationType.RIDE_CANCELLED, ride_id=42)
        log = get_sent_notifications()
        assert log[0].title == "Ride cancelled"

    @pytest.mark.asyncio
    async def test_extra_data_included(self):
        await send_ride_notification(
            user_id=10, type=NotificationType.RIDE_COMPLETED, ride_id=42, fare=15.50
        )
        log = get_sent_notifications()
        assert log[0].data["fare"] == 15.50
        assert log[0].data["ride_id"] == 42

    @pytest.mark.asyncio
    async def test_account_verification_uses_template(self):
        await send_ride_notification(
            user_id=10, type=NotificationType.ACCOUNT_VERIFICATION, ride_id=0
        )
        log = get_sent_notifications()
        assert log[0].title == "Account verification"
        assert "verification" in log[0].body.lower()


class TestClearNotifications:
    @pytest.mark.asyncio
    async def test_clear_empties_log(self):
        await send_notification(
            Notification(user_id=1, type=NotificationType.RIDE_MATCHED, title="Hi", body="Test")
        )
        assert len(get_sent_notifications()) == 1
        clear_sent_notifications()
        assert len(get_sent_notifications()) == 0
