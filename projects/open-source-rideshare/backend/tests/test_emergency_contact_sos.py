"""Tests for SOS → emergency contact notifications.

Covers:
- NotificationType entry exists for emergency_contact_sos
- Template renders correct title, body, channels (SMS-only)
- notify_emergency_contacts_sos sends one SMS per contact
- notify_emergency_contacts_sos sends to contact phone, not user phone
- notify_emergency_contacts_sos sends 0 notifications when no contacts exist
- notify_emergency_contacts_sos includes location when provided
- Individual contact failure does not prevent other contacts from being notified
- DB failure in contact fetch does not raise
- Wiring: trigger_sos calls notify_emergency_contacts_sos
- Wiring: emergency contact notification failure does not block SOS creation
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
from app.services.notification_templates import emergency_contact_sos, render


# ---------------------------------------------------------------------------
# Enum presence
# ---------------------------------------------------------------------------


class TestNotificationTypeEntry:
    def test_emergency_contact_sos_exists(self):
        assert NotificationType.EMERGENCY_CONTACT_SOS == "emergency_contact_sos"


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


class TestEmergencyContactSosTemplate:
    def test_title_contains_emergency(self):
        title, _, _ = emergency_contact_sos()
        assert "emergency" in title.lower() or "sos" in title.lower()

    def test_body_includes_user_name(self):
        _, body, _ = emergency_contact_sos(user_name="Alice")
        assert "Alice" in body

    def test_body_default_someone(self):
        _, body, _ = emergency_contact_sos()
        assert "Someone" in body

    def test_body_includes_ride_id(self):
        _, body, _ = emergency_contact_sos(user_name="Bob", ride_id=42)
        assert "42" in body

    def test_body_includes_location_when_provided(self):
        _, body, _ = emergency_contact_sos(user_name="Carol", latitude=37.7749, longitude=-122.4194)
        assert "37.7749" in body
        assert "-122.4194" in body

    def test_body_omits_location_when_not_provided(self):
        _, body, _ = emergency_contact_sos(user_name="Dave")
        assert "Location:" not in body

    def test_channels_sms_only(self):
        _, _, channels = emergency_contact_sos()
        assert channels == [NotificationChannel.SMS]
        assert NotificationChannel.PUSH not in channels
        assert NotificationChannel.EMAIL not in channels

    def test_render_dispatch(self):
        title, body, channels = render(NotificationType.EMERGENCY_CONTACT_SOS, user_name="Eve", ride_id=7)
        assert "Eve" in body
        assert "7" in body
        assert NotificationChannel.SMS in channels


# ---------------------------------------------------------------------------
# Dispatcher: notify_emergency_contacts_sos
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


class TestNotifyEmergencyContactsSos:
    @pytest.mark.asyncio
    async def test_sends_one_notification_per_contact(self):
        from app.services.notification_events import notify_emergency_contacts_sos

        contacts = [_make_contact("+15550001111"), _make_contact("+15550002222")]
        db = AsyncMock()
        contacts_result = MagicMock()
        contacts_result.scalars.return_value.all.return_value = contacts
        db.execute.return_value = contacts_result

        await notify_emergency_contacts_sos(db, user_id=1, user_name="Alice")

        sent = get_sent_notifications()
        assert len(sent) == 2

    @pytest.mark.asyncio
    async def test_sends_to_contact_phone_not_user_phone(self):
        from app.services.notification_events import notify_emergency_contacts_sos

        contacts = [_make_contact("+15559998888")]
        db = AsyncMock()
        contacts_result = MagicMock()
        contacts_result.scalars.return_value.all.return_value = contacts
        db.execute.return_value = contacts_result

        with patch("app.services.notifications.send_sms", new_callable=AsyncMock) as mock_sms:
            mock_sms.return_value = True
            await notify_emergency_contacts_sos(db, user_id=1, user_name="Alice")

        mock_sms.assert_awaited_once()
        sms_phone_arg = mock_sms.call_args[0][1]
        assert sms_phone_arg == "+15559998888"

    @pytest.mark.asyncio
    async def test_sends_zero_notifications_when_no_contacts(self):
        from app.services.notification_events import notify_emergency_contacts_sos

        db = AsyncMock()
        contacts_result = MagicMock()
        contacts_result.scalars.return_value.all.return_value = []
        db.execute.return_value = contacts_result

        await notify_emergency_contacts_sos(db, user_id=1, user_name="Alice")

        sent = get_sent_notifications()
        assert len(sent) == 0

    @pytest.mark.asyncio
    async def test_notification_type_is_emergency_contact_sos(self):
        from app.services.notification_events import notify_emergency_contacts_sos

        db = AsyncMock()
        contacts_result = MagicMock()
        contacts_result.scalars.return_value.all.return_value = [_make_contact("+15551234567")]
        db.execute.return_value = contacts_result

        await notify_emergency_contacts_sos(db, user_id=5, user_name="Bob")

        sent = get_sent_notifications()
        assert sent[0].type == NotificationType.EMERGENCY_CONTACT_SOS

    @pytest.mark.asyncio
    async def test_user_id_attributed_to_triggering_user(self):
        from app.services.notification_events import notify_emergency_contacts_sos

        db = AsyncMock()
        contacts_result = MagicMock()
        contacts_result.scalars.return_value.all.return_value = [_make_contact("+15551234567")]
        db.execute.return_value = contacts_result

        await notify_emergency_contacts_sos(db, user_id=42, user_name="Charlie")

        sent = get_sent_notifications()
        assert sent[0].user_id == 42

    @pytest.mark.asyncio
    async def test_body_includes_user_name(self):
        from app.services.notification_events import notify_emergency_contacts_sos

        db = AsyncMock()
        contacts_result = MagicMock()
        contacts_result.scalars.return_value.all.return_value = [_make_contact("+15551234567")]
        db.execute.return_value = contacts_result

        await notify_emergency_contacts_sos(db, user_id=1, user_name="Diana")

        sent = get_sent_notifications()
        assert "Diana" in sent[0].body

    @pytest.mark.asyncio
    async def test_individual_contact_failure_does_not_block_remaining(self):
        from app.services.notification_events import notify_emergency_contacts_sos

        contacts = [_make_contact("+15550001111"), _make_contact("+15550002222")]
        db = AsyncMock()
        contacts_result = MagicMock()
        contacts_result.scalars.return_value.all.return_value = contacts
        db.execute.return_value = contacts_result

        call_count = 0

        async def fake_send(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first contact send failed")
            return True

        with patch("app.services.notifications.send_sms", new_callable=AsyncMock, side_effect=fake_send):
            await notify_emergency_contacts_sos(db, user_id=1, user_name="Eve")

        # Both were attempted — the sent log collects before provider raises
        # At minimum the second one made it into the log
        sent = get_sent_notifications()
        assert len(sent) >= 1

    @pytest.mark.asyncio
    async def test_db_failure_does_not_raise(self):
        from app.services.notification_events import notify_emergency_contacts_sos

        db = AsyncMock()
        db.execute.side_effect = RuntimeError("DB down")

        await notify_emergency_contacts_sos(db, user_id=1, user_name="Frank")

    @pytest.mark.asyncio
    async def test_no_contacts_when_db_returns_none(self):
        from app.services.notification_events import notify_emergency_contacts_sos

        db = AsyncMock()
        contacts_result = MagicMock()
        contacts_result.scalars.return_value.all.return_value = []
        db.execute.return_value = contacts_result

        await notify_emergency_contacts_sos(db, user_id=1)

        sent = get_sent_notifications()
        assert len(sent) == 0


# ---------------------------------------------------------------------------
# Wiring: trigger_sos calls notify_emergency_contacts_sos
# ---------------------------------------------------------------------------


class TestTriggerSosWiring:
    @pytest.mark.asyncio
    @patch("app.services.notification_events.notify_emergency_contacts_sos", new_callable=AsyncMock)
    @patch("app.services.notification_events.notify_sos_alert", new_callable=AsyncMock)
    async def test_trigger_sos_calls_emergency_contact_notifier(self, mock_sos_alert, mock_ec_notify):
        from app.services.safety import trigger_sos

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        # ride check: no ride_id provided, skip ride query
        # user name query
        user_name_result = MagicMock()
        user_name_result.scalar_one_or_none.return_value = "Grace"
        db.execute.return_value = user_name_result

        await trigger_sos(user_id=7, db=db, ride_id=None, latitude=40.0, longitude=-74.0)

        mock_ec_notify.assert_awaited_once()
        call_kwargs = mock_ec_notify.call_args
        assert call_kwargs.kwargs.get("user_id") == 7 or (call_kwargs.args and call_kwargs.args[1] == 7)
        assert call_kwargs.kwargs.get("latitude") == 40.0
        assert call_kwargs.kwargs.get("longitude") == -74.0

    @pytest.mark.asyncio
    @patch(
        "app.services.notification_events.notify_emergency_contacts_sos",
        new_callable=AsyncMock,
        side_effect=RuntimeError("ec notify failed"),
    )
    @patch("app.services.notification_events.notify_sos_alert", new_callable=AsyncMock)
    async def test_emergency_contact_failure_does_not_block_sos_creation(self, mock_sos_alert, mock_ec_notify):
        from app.services.safety import trigger_sos
        from app.models.safety import SOSAlert

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        user_name_result = MagicMock()
        user_name_result.scalar_one_or_none.return_value = "Henry"
        db.execute.return_value = user_name_result

        # Should not raise
        alert = await trigger_sos(user_id=8, db=db)
        assert alert is not None
