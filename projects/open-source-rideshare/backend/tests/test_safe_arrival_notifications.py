"""Tests for safe arrival → emergency contact notifications.

Covers:
- NotificationType entry exists for safe_arrival_contact
- Template renders correct title, body, channels (SMS-only)
- Template includes rider name and ride ID
- notify_safe_arrival_contacts sends one SMS per contact
- notify_safe_arrival_contacts sends to contact phone, not user phone
- notify_safe_arrival_contacts sends 0 notifications when no contacts exist
- Notification type is SAFE_ARRIVAL_CONTACT
- user_id attributed to the confirming rider
- Individual contact failure does not prevent other contacts from being notified
- DB failure in contact fetch does not raise
- Wiring: confirm_safe_arrival calls notify_safe_arrival_contacts
- Wiring: notification failure does not block safe arrival confirmation
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notifications import (
    NotificationChannel,
    NotificationType,
    clear_sent_notifications,
    get_sent_notifications,
)
from app.services.notification_templates import safe_arrival_contact, render


# ---------------------------------------------------------------------------
# Enum presence
# ---------------------------------------------------------------------------


class TestNotificationTypeEntry:
    def test_safe_arrival_contact_exists(self):
        assert NotificationType.SAFE_ARRIVAL_CONTACT == "safe_arrival_contact"


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


class TestSafeArrivalContactTemplate:
    def test_title_indicates_safe(self):
        title, _, _ = safe_arrival_contact()
        assert "safe" in title.lower() or "arrival" in title.lower()

    def test_body_includes_user_name(self):
        _, body, _ = safe_arrival_contact(user_name="Alice")
        assert "Alice" in body

    def test_body_default_someone(self):
        _, body, _ = safe_arrival_contact()
        assert "Someone" in body

    def test_body_includes_ride_id(self):
        _, body, _ = safe_arrival_contact(user_name="Bob", ride_id=99)
        assert "99" in body

    def test_body_omits_ride_id_when_not_provided(self):
        _, body, _ = safe_arrival_contact(user_name="Carol")
        assert "Ride #" not in body

    def test_channels_sms_only(self):
        _, _, channels = safe_arrival_contact()
        assert channels == [NotificationChannel.SMS]
        assert NotificationChannel.PUSH not in channels
        assert NotificationChannel.EMAIL not in channels

    def test_render_dispatch(self):
        title, body, channels = render(NotificationType.SAFE_ARRIVAL_CONTACT, user_name="Dave", ride_id=5)
        assert "Dave" in body
        assert "5" in body
        assert NotificationChannel.SMS in channels


# ---------------------------------------------------------------------------
# Dispatcher: notify_safe_arrival_contacts
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_sent():
    clear_sent_notifications()
    yield
    clear_sent_notifications()


def _make_contact(phone: str, user_id: int = 1) -> MagicMock:
    c = MagicMock()
    c.phone = phone
    c.user_id = user_id
    return c


class TestNotifySafeArrivalContacts:
    @pytest.mark.asyncio
    async def test_sends_one_notification_per_contact(self):
        from app.services.notification_events import notify_safe_arrival_contacts

        contacts = [_make_contact("+15550001111"), _make_contact("+15550002222")]
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = contacts
        db.execute.return_value = result

        await notify_safe_arrival_contacts(db, user_id=1, user_name="Alice")

        sent = get_sent_notifications()
        assert len(sent) == 2

    @pytest.mark.asyncio
    async def test_sends_to_contact_phone_not_user_phone(self):
        from app.services.notification_events import notify_safe_arrival_contacts

        contacts = [_make_contact("+15559998888")]
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = contacts
        db.execute.return_value = result

        with patch("app.services.notifications.send_sms", new_callable=AsyncMock) as mock_sms:
            mock_sms.return_value = True
            await notify_safe_arrival_contacts(db, user_id=1, user_name="Alice")

        mock_sms.assert_awaited_once()
        assert mock_sms.call_args[0][1] == "+15559998888"

    @pytest.mark.asyncio
    async def test_sends_zero_notifications_when_no_contacts(self):
        from app.services.notification_events import notify_safe_arrival_contacts

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute.return_value = result

        await notify_safe_arrival_contacts(db, user_id=1, user_name="Alice")

        assert len(get_sent_notifications()) == 0

    @pytest.mark.asyncio
    async def test_notification_type_is_safe_arrival_contact(self):
        from app.services.notification_events import notify_safe_arrival_contacts

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [_make_contact("+15551234567")]
        db.execute.return_value = result

        await notify_safe_arrival_contacts(db, user_id=5, user_name="Eve")

        sent = get_sent_notifications()
        assert sent[0].type == NotificationType.SAFE_ARRIVAL_CONTACT

    @pytest.mark.asyncio
    async def test_user_id_attributed_to_rider(self):
        from app.services.notification_events import notify_safe_arrival_contacts

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [_make_contact("+15551234567")]
        db.execute.return_value = result

        await notify_safe_arrival_contacts(db, user_id=42, user_name="Frank")

        sent = get_sent_notifications()
        assert sent[0].user_id == 42

    @pytest.mark.asyncio
    async def test_body_includes_user_name(self):
        from app.services.notification_events import notify_safe_arrival_contacts

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [_make_contact("+15551234567")]
        db.execute.return_value = result

        await notify_safe_arrival_contacts(db, user_id=1, user_name="Greta")

        sent = get_sent_notifications()
        assert "Greta" in sent[0].body

    @pytest.mark.asyncio
    async def test_individual_contact_failure_does_not_block_remaining(self):
        from app.services.notification_events import notify_safe_arrival_contacts

        contacts = [_make_contact("+15550001111"), _make_contact("+15550002222")]
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = contacts
        db.execute.return_value = result

        call_count = 0

        async def fake_send(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first contact send failed")
            return True

        with patch("app.services.notifications.send_sms", new_callable=AsyncMock, side_effect=fake_send):
            await notify_safe_arrival_contacts(db, user_id=1, user_name="Hana")

        sent = get_sent_notifications()
        assert len(sent) >= 1

    @pytest.mark.asyncio
    async def test_db_failure_does_not_raise(self):
        from app.services.notification_events import notify_safe_arrival_contacts

        db = AsyncMock()
        db.execute.side_effect = RuntimeError("DB down")

        await notify_safe_arrival_contacts(db, user_id=1, user_name="Ivan")


# ---------------------------------------------------------------------------
# Wiring: confirm_safe_arrival calls notify_safe_arrival_contacts
# ---------------------------------------------------------------------------


class TestConfirmSafeArrivalWiring:
    @pytest.mark.asyncio
    @patch(
        "app.services.notification_events.notify_safe_arrival_contacts",
        new_callable=AsyncMock,
    )
    async def test_confirm_safe_arrival_calls_notifier(self, mock_notify):
        from app.services.rider_safety import confirm_safe_arrival, _safe_arrivals
        from app.models.ride import RideStatus

        _safe_arrivals.clear()

        ride = MagicMock()
        ride.rider_id = 10
        ride.status = RideStatus.COMPLETED

        ride_result = MagicMock()
        ride_result.scalar_one_or_none.return_value = ride

        user_name_result = MagicMock()
        user_name_result.scalar_one_or_none.return_value = "Jana"

        db = AsyncMock()
        db.execute.side_effect = [ride_result, user_name_result]

        await confirm_safe_arrival(db=db, ride_id=100, user_id=10)

        mock_notify.assert_awaited_once()
        kwargs = mock_notify.call_args.kwargs
        assert kwargs["user_id"] == 10
        assert kwargs["ride_id"] == 100

    @pytest.mark.asyncio
    @patch(
        "app.services.notification_events.notify_safe_arrival_contacts",
        new_callable=AsyncMock,
        side_effect=RuntimeError("notify failed"),
    )
    async def test_notification_failure_does_not_block_confirmation(self, mock_notify):
        from app.services.rider_safety import confirm_safe_arrival, _safe_arrivals
        from app.models.ride import RideStatus

        _safe_arrivals.clear()

        ride = MagicMock()
        ride.rider_id = 11
        ride.status = RideStatus.COMPLETED

        ride_result = MagicMock()
        ride_result.scalar_one_or_none.return_value = ride

        user_name_result = MagicMock()
        user_name_result.scalar_one_or_none.return_value = "Kai"

        db = AsyncMock()
        db.execute.side_effect = [ride_result, user_name_result]

        record = await confirm_safe_arrival(db=db, ride_id=200, user_id=11)
        assert record is not None
        assert record["ride_id"] == 200
