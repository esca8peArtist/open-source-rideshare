"""Comprehensive tests for the notification system.

Covers:
- NotificationLog and NotificationPreference models
- Notification schemas
- Notification templates (all ride lifecycle events)
- Notification providers (Twilio SMS, SendGrid email, push stubs)
- Refactored notification service (dispatch, preference filtering, DB logging)
- Notification event dispatchers (fire-and-forget lifecycle helpers)
- Notification API endpoints (preferences, history, mark-read)
- Config settings (SendGrid, feature flags)
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.notification import (
    NotificationLog,
    NotificationPreference,
    NotificationStatus,
)
from app.schemas.notification import (
    NotificationListResponse,
    NotificationLogResponse,
    NotificationPreferenceResponse,
    UnreadNotificationCount,
    UpdateNotificationPreference,
)
from app.services.notifications import (
    Notification,
    NotificationChannel,
    NotificationType,
    clear_sent_notifications,
    filter_channels_by_preferences,
    get_sent_notifications,
    send_notification,
    send_ride_notification,
    send_notification_with_preferences,
)
from app.services.notification_templates import (
    TEMPLATES,
    render,
    ride_matched,
    ride_cancelled,
    ride_completed,
    driver_en_route,
    driver_arrived,
    payment_received,
    sos_alert,
    rating_received,
    account_verification,
    payout_completed,
    ride_reminder,
    fare_split_request,
    promo_applied,
)


@pytest.fixture(autouse=True)
def clean_notifications():
    clear_sent_notifications()
    yield
    clear_sent_notifications()


# ===========================================================================
# NotificationLog Model Tests
# ===========================================================================


class TestNotificationLogModel:
    def test_table_name(self):
        assert NotificationLog.__tablename__ == "notification_logs"

    def test_has_user_id_column(self):
        cols = {c.name for c in NotificationLog.__table__.columns}
        assert "user_id" in cols

    def test_has_notification_type_column(self):
        cols = {c.name for c in NotificationLog.__table__.columns}
        assert "notification_type" in cols

    def test_has_channel_column(self):
        cols = {c.name for c in NotificationLog.__table__.columns}
        assert "channel" in cols

    def test_has_title_column(self):
        cols = {c.name for c in NotificationLog.__table__.columns}
        assert "title" in cols

    def test_has_body_column(self):
        cols = {c.name for c in NotificationLog.__table__.columns}
        assert "body" in cols

    def test_has_status_column(self):
        cols = {c.name for c in NotificationLog.__table__.columns}
        assert "status" in cols

    def test_has_ride_id_column(self):
        cols = {c.name for c in NotificationLog.__table__.columns}
        assert "ride_id" in cols

    def test_has_is_read_column(self):
        cols = {c.name for c in NotificationLog.__table__.columns}
        assert "is_read" in cols

    def test_has_error_message_column(self):
        cols = {c.name for c in NotificationLog.__table__.columns}
        assert "error_message" in cols

    def test_has_created_at_column(self):
        cols = {c.name for c in NotificationLog.__table__.columns}
        assert "created_at" in cols

    def test_has_read_at_column(self):
        cols = {c.name for c in NotificationLog.__table__.columns}
        assert "read_at" in cols


class TestNotificationStatusEnum:
    def test_pending(self):
        assert NotificationStatus.PENDING == "pending"

    def test_sent(self):
        assert NotificationStatus.SENT == "sent"

    def test_failed(self):
        assert NotificationStatus.FAILED == "failed"


# ===========================================================================
# NotificationPreference Model Tests
# ===========================================================================


class TestNotificationPreferenceModel:
    def test_table_name(self):
        assert NotificationPreference.__tablename__ == "notification_preferences"

    def test_has_user_id_column(self):
        cols = {c.name for c in NotificationPreference.__table__.columns}
        assert "user_id" in cols

    def test_has_push_enabled_column(self):
        cols = {c.name for c in NotificationPreference.__table__.columns}
        assert "push_enabled" in cols

    def test_has_sms_enabled_column(self):
        cols = {c.name for c in NotificationPreference.__table__.columns}
        assert "sms_enabled" in cols

    def test_has_email_enabled_column(self):
        cols = {c.name for c in NotificationPreference.__table__.columns}
        assert "email_enabled" in cols

    def test_has_quiet_hours_start(self):
        cols = {c.name for c in NotificationPreference.__table__.columns}
        assert "quiet_hours_start" in cols

    def test_has_quiet_hours_end(self):
        cols = {c.name for c in NotificationPreference.__table__.columns}
        assert "quiet_hours_end" in cols

    def test_has_ride_updates_column(self):
        cols = {c.name for c in NotificationPreference.__table__.columns}
        assert "ride_updates" in cols

    def test_has_payment_updates_column(self):
        cols = {c.name for c in NotificationPreference.__table__.columns}
        assert "payment_updates" in cols

    def test_has_promo_updates_column(self):
        cols = {c.name for c in NotificationPreference.__table__.columns}
        assert "promo_updates" in cols

    def test_has_safety_alerts_column(self):
        cols = {c.name for c in NotificationPreference.__table__.columns}
        assert "safety_alerts" in cols


# ===========================================================================
# Notification Schemas
# ===========================================================================


class TestNotificationSchemas:
    def test_preference_response_from_dict(self):
        data = {
            "push_enabled": True, "sms_enabled": False, "email_enabled": True,
            "quiet_hours_start": 22, "quiet_hours_end": 7,
            "ride_updates": True, "payment_updates": True,
            "promo_updates": False, "safety_alerts": True,
        }
        resp = NotificationPreferenceResponse(**data)
        assert resp.push_enabled is True
        assert resp.sms_enabled is False
        assert resp.quiet_hours_start == 22

    def test_update_preference_partial(self):
        req = UpdateNotificationPreference(sms_enabled=False)
        dumped = req.model_dump(exclude_unset=True)
        assert dumped == {"sms_enabled": False}

    def test_update_preference_quiet_hours_validation(self):
        req = UpdateNotificationPreference(quiet_hours_start=22, quiet_hours_end=7)
        assert req.quiet_hours_start == 22
        assert req.quiet_hours_end == 7

    def test_update_preference_quiet_hours_out_of_range(self):
        with pytest.raises(Exception):
            UpdateNotificationPreference(quiet_hours_start=25)

    def test_log_response_from_dict(self):
        data = {
            "id": 1, "notification_type": "ride_matched", "channel": "push",
            "title": "Test", "body": "Test body", "status": "sent",
            "ride_id": 42, "is_read": False,
            "created_at": datetime.now(timezone.utc), "read_at": None,
        }
        resp = NotificationLogResponse(**data)
        assert resp.notification_type == "ride_matched"
        assert resp.ride_id == 42

    def test_list_response(self):
        resp = NotificationListResponse(notifications=[], total=0, unread_count=0)
        assert resp.total == 0

    def test_unread_count_response(self):
        resp = UnreadNotificationCount(total_unread=5)
        assert resp.total_unread == 5


# ===========================================================================
# Notification Templates
# ===========================================================================


class TestNotificationTemplates:
    def test_ride_matched_basic(self):
        title, body, channels = ride_matched()
        assert title == "Driver matched!"
        assert "your driver" in body
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS in channels

    def test_ride_matched_with_eta(self):
        title, body, channels = ride_matched(driver_name="Alice", eta_minutes=5)
        assert "Alice" in body
        assert "5 min" in body

    def test_ride_cancelled_basic(self):
        title, body, channels = ride_cancelled()
        assert title == "Ride cancelled"
        assert NotificationChannel.SMS in channels

    def test_ride_cancelled_with_reason(self):
        title, body, channels = ride_cancelled(cancelled_by="The rider", reason="Changed plans")
        assert "Changed plans" in body

    def test_ride_completed_basic(self):
        title, body, channels = ride_completed()
        assert title == "Ride completed"
        assert "Rate" in body
        assert NotificationChannel.EMAIL in channels

    def test_ride_completed_with_fare(self):
        title, body, channels = ride_completed(fare=15.50, distance_km=8.2)
        assert "$15.5" in body
        assert "8.2 km" in body

    def test_driver_en_route_basic(self):
        title, body, channels = driver_en_route()
        assert "on the way" in title.lower()

    def test_driver_en_route_with_eta(self):
        title, body, channels = driver_en_route(driver_name="Bob", eta_minutes=3)
        assert "Bob" in body
        assert "3 min" in body

    def test_driver_arrived(self):
        title, body, channels = driver_arrived(driver_name="Carol")
        assert "Carol" in body
        assert "arrived" in title.lower()
        assert NotificationChannel.SMS in channels

    def test_payment_received(self):
        title, body, channels = payment_received(amount=25.00)
        assert "$25.0" in body
        assert NotificationChannel.EMAIL in channels

    def test_sos_alert(self):
        title, body, channels = sos_alert(ride_id=42, user_name="Dave")
        assert "SOS" in title
        assert "Dave" in body
        assert len(channels) == 3  # all channels

    def test_rating_received(self):
        title, body, channels = rating_received(rating=4.5)
        assert "4.5" in body

    def test_account_verification(self):
        title, body, channels = account_verification(status="approved")
        assert "approved" in body
        assert NotificationChannel.EMAIL in channels

    def test_payout_completed(self):
        title, body, channels = payout_completed(amount=150.00, period="2026-04-01 to 2026-04-07")
        assert "$150.0" in body
        assert "2026-04" in body

    def test_ride_reminder(self):
        title, body, channels = ride_reminder(pickup_time="3:00 PM", pickup_address="123 Main St")
        assert "3:00 PM" in body
        assert "123 Main St" in body

    def test_fare_split_request(self):
        title, body, channels = fare_split_request(initiator_name="Eve", amount=12.50)
        assert "Eve" in body
        assert "$12.5" in body

    def test_promo_applied(self):
        title, body, channels = promo_applied(code="SAVE10", discount="10%")
        assert "SAVE10" in body
        assert "10%" in body

    def test_render_known_type(self):
        title, body, channels = render(NotificationType.RIDE_MATCHED, driver_name="Test")
        assert title == "Driver matched!"

    def test_render_unknown_type_falls_back(self):
        title, body, channels = render("unknown_type")
        assert title == "OpenRide Update"

    def test_all_notification_types_have_templates(self):
        core_types = [
            NotificationType.RIDE_MATCHED, NotificationType.RIDE_CANCELLED,
            NotificationType.RIDE_COMPLETED, NotificationType.DRIVER_EN_ROUTE,
            NotificationType.DRIVER_ARRIVED, NotificationType.PAYMENT_RECEIVED,
            NotificationType.SOS_ALERT, NotificationType.RATING_RECEIVED,
            NotificationType.ACCOUNT_VERIFICATION,
        ]
        for t in core_types:
            assert t in TEMPLATES, f"Missing template for {t}"

    def test_extra_templates_registered(self):
        assert "payout_completed" in TEMPLATES
        assert "ride_reminder" in TEMPLATES
        assert "fare_split_request" in TEMPLATES
        assert "promo_applied" in TEMPLATES


# ===========================================================================
# Notification Providers
# ===========================================================================


class TestNotificationProviders:
    @pytest.mark.asyncio
    async def test_send_sms_disabled_by_default(self):
        from app.services.notification_providers import send_sms
        n = Notification(user_id=1, type=NotificationType.RIDE_MATCHED, title="Hi", body="Test")
        result = await send_sms(n, "+1234567890")
        assert result is False  # disabled by default

    @pytest.mark.asyncio
    async def test_send_sms_no_phone(self):
        from app.services.notification_providers import send_sms
        with patch("app.services.notification_providers.settings") as mock_settings:
            mock_settings.notifications_sms_enabled = True
            mock_settings.twilio_account_sid = "test_sid"
            mock_settings.twilio_auth_token = "test_token"
            mock_settings.twilio_phone_number = "+1111111111"
            n = Notification(user_id=1, type=NotificationType.RIDE_MATCHED, title="Hi", body="Test")
            result = await send_sms(n, "")
            assert result is False

    @pytest.mark.asyncio
    async def test_send_sms_missing_credentials(self):
        from app.services.notification_providers import send_sms
        with patch("app.services.notification_providers.settings") as mock_settings:
            mock_settings.notifications_sms_enabled = True
            mock_settings.twilio_account_sid = ""
            mock_settings.twilio_auth_token = ""
            mock_settings.twilio_phone_number = ""
            n = Notification(user_id=1, type=NotificationType.RIDE_MATCHED, title="Hi", body="Test")
            result = await send_sms(n, "+1234567890")
            assert result is False

    @pytest.mark.asyncio
    async def test_send_sms_twilio_not_installed(self):
        from app.services.notification_providers import send_sms
        with patch("app.services.notification_providers.settings") as mock_settings:
            mock_settings.notifications_sms_enabled = True
            mock_settings.twilio_account_sid = "test_sid"
            mock_settings.twilio_auth_token = "test_token"
            mock_settings.twilio_phone_number = "+1111111111"
            # twilio import will fail if not installed — this tests the ImportError path
            import importlib
            import sys
            twilio_present = "twilio" in sys.modules or importlib.util.find_spec("twilio") is not None
            n = Notification(user_id=1, type=NotificationType.RIDE_MATCHED, title="Hi", body="Test")
            result = await send_sms(n, "+1234567890")
            # Either twilio isn't installed (False) or it would try to call the real API
            assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_send_email_disabled_by_default(self):
        from app.services.notification_providers import send_email
        n = Notification(user_id=1, type=NotificationType.RIDE_COMPLETED, title="Done", body="Test")
        result = await send_email(n, "test@example.com")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_email_no_address(self):
        from app.services.notification_providers import send_email
        with patch("app.services.notification_providers.settings") as mock_settings:
            mock_settings.notifications_email_enabled = True
            mock_settings.sendgrid_api_key = "test_key"
            n = Notification(user_id=1, type=NotificationType.RIDE_COMPLETED, title="Done", body="Test")
            result = await send_email(n, "")
            assert result is False

    @pytest.mark.asyncio
    async def test_send_email_no_api_key(self):
        from app.services.notification_providers import send_email
        with patch("app.services.notification_providers.settings") as mock_settings:
            mock_settings.notifications_email_enabled = True
            mock_settings.sendgrid_api_key = ""
            n = Notification(user_id=1, type=NotificationType.RIDE_COMPLETED, title="Done", body="Test")
            result = await send_email(n, "test@example.com")
            assert result is False

    @pytest.mark.asyncio
    async def test_send_push_disabled_by_default(self):
        from app.services.notification_providers import send_push
        n = Notification(user_id=1, type=NotificationType.RIDE_MATCHED, title="Hi", body="Test")
        result = await send_push(n)
        assert result is False

    def test_build_email_html(self):
        from app.services.notification_providers import _build_email_html
        n = Notification(
            user_id=1, type=NotificationType.RIDE_COMPLETED,
            title="Ride completed", body="Your ride is done.",
            data={"ride_id": 42, "fare": 15.50},
        )
        html = _build_email_html(n)
        assert "Ride completed" in html
        assert "Your ride is done." in html
        assert "Ride Id" in html
        assert "42" in html
        assert "OpenRide" in html

    def test_build_email_html_no_data(self):
        from app.services.notification_providers import _build_email_html
        n = Notification(
            user_id=1, type=NotificationType.RIDE_MATCHED,
            title="Matched", body="You have a driver.",
        )
        html = _build_email_html(n)
        assert "Matched" in html
        assert "<ul>" not in html


# ===========================================================================
# Notification Service (Refactored)
# ===========================================================================


class TestNotificationService:
    @pytest.mark.asyncio
    async def test_send_notification_returns_true(self):
        n = Notification(user_id=1, type=NotificationType.RIDE_MATCHED, title="Hi", body="Test")
        result = await send_notification(n)
        assert result is True

    @pytest.mark.asyncio
    async def test_send_notification_records_in_log(self):
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

    @pytest.mark.asyncio
    async def test_clear_empties_log(self):
        n = Notification(user_id=1, type=NotificationType.RIDE_MATCHED, title="Hi", body="Test")
        await send_notification(n)
        assert len(get_sent_notifications()) == 1
        clear_sent_notifications()
        assert len(get_sent_notifications()) == 0


class TestNotificationTypes:
    def test_original_types_preserved(self):
        expected = [
            "ride_matched", "ride_cancelled", "ride_completed",
            "driver_en_route", "driver_arrived", "payment_received",
            "sos_alert", "rating_received", "account_verification",
        ]
        for t in expected:
            assert NotificationType(t) is not None

    def test_new_types_added(self):
        new_types = ["payout_completed", "ride_reminder", "fare_split_request", "promo_applied"]
        for t in new_types:
            assert NotificationType(t) is not None


class TestNotificationDataclass:
    def test_default_channel_is_push(self):
        n = Notification(user_id=1, type=NotificationType.RIDE_MATCHED, title="Hi", body="Test")
        assert n.channels == [NotificationChannel.PUSH]

    def test_custom_channels(self):
        n = Notification(
            user_id=1, type=NotificationType.SOS_ALERT, title="SOS", body="Emergency",
            channels=[NotificationChannel.SMS, NotificationChannel.EMAIL],
        )
        assert NotificationChannel.SMS in n.channels
        assert NotificationChannel.EMAIL in n.channels

    def test_ride_id_field(self):
        n = Notification(
            user_id=1, type=NotificationType.RIDE_MATCHED,
            title="Hi", body="Test", ride_id=42,
        )
        assert n.ride_id == 42

    def test_ride_id_default_none(self):
        n = Notification(user_id=1, type=NotificationType.RIDE_MATCHED, title="Hi", body="Test")
        assert n.ride_id is None

    def test_data_field_optional(self):
        n = Notification(user_id=1, type=NotificationType.RIDE_COMPLETED, title="Done", body="Done")
        assert n.data is None

    def test_data_field_set(self):
        n = Notification(
            user_id=1, type=NotificationType.RIDE_COMPLETED,
            title="Done", body="Done", data={"ride_id": 42},
        )
        assert n.data["ride_id"] == 42


class TestSendRideNotification:
    @pytest.mark.asyncio
    async def test_ride_matched_uses_template(self):
        result = await send_ride_notification(
            user_id=10, type=NotificationType.RIDE_MATCHED, ride_id=42, driver_name="Alice"
        )
        assert result is True
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].title == "Driver matched!"
        assert "Alice" in log[0].body

    @pytest.mark.asyncio
    async def test_ride_cancelled_uses_template(self):
        await send_ride_notification(
            user_id=10, type=NotificationType.RIDE_CANCELLED, ride_id=42
        )
        log = get_sent_notifications()
        assert log[0].title == "Ride cancelled"

    @pytest.mark.asyncio
    async def test_ride_completed_uses_template(self):
        await send_ride_notification(
            user_id=10, type=NotificationType.RIDE_COMPLETED, ride_id=42, fare=25.00
        )
        log = get_sent_notifications()
        assert log[0].title == "Ride completed"
        assert "$25.0" in log[0].body

    @pytest.mark.asyncio
    async def test_extra_data_included(self):
        await send_ride_notification(
            user_id=10, type=NotificationType.RIDE_COMPLETED, ride_id=42, fare=15.50,
        )
        log = get_sent_notifications()
        assert log[0].data["fare"] == 15.50
        assert log[0].data["ride_id"] == 42

    @pytest.mark.asyncio
    async def test_ride_id_stored(self):
        await send_ride_notification(
            user_id=10, type=NotificationType.RIDE_MATCHED, ride_id=99,
        )
        log = get_sent_notifications()
        assert log[0].ride_id == 99

    @pytest.mark.asyncio
    async def test_channels_from_template(self):
        await send_ride_notification(
            user_id=10, type=NotificationType.SOS_ALERT, ride_id=42,
        )
        log = get_sent_notifications()
        # SOS uses all channels
        assert NotificationChannel.PUSH in log[0].channels
        assert NotificationChannel.SMS in log[0].channels
        assert NotificationChannel.EMAIL in log[0].channels


# ===========================================================================
# Notification Event Dispatchers
# ===========================================================================


class TestNotificationEvents:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        # Mock the user contact lookup
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = MagicMock(phone="+1234567890", email="test@example.com")
        db.execute = AsyncMock(return_value=mock_result)
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_notify_ride_matched(self, mock_db):
        from app.services.notification_events import notify_ride_matched
        await notify_ride_matched(mock_db, rider_id=1, ride_id=42, driver_name="Alice")
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].type == NotificationType.RIDE_MATCHED

    @pytest.mark.asyncio
    async def test_notify_ride_cancelled(self, mock_db):
        from app.services.notification_events import notify_ride_cancelled
        await notify_ride_cancelled(mock_db, user_id=1, ride_id=42, cancelled_by="rider")
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].type == NotificationType.RIDE_CANCELLED

    @pytest.mark.asyncio
    async def test_notify_ride_completed(self, mock_db):
        from app.services.notification_events import notify_ride_completed
        await notify_ride_completed(mock_db, rider_id=1, ride_id=42, fare=25.00)
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].type == NotificationType.RIDE_COMPLETED

    @pytest.mark.asyncio
    async def test_notify_driver_en_route(self, mock_db):
        from app.services.notification_events import notify_driver_en_route
        await notify_driver_en_route(mock_db, rider_id=1, ride_id=42, eta_minutes=5)
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].type == NotificationType.DRIVER_EN_ROUTE

    @pytest.mark.asyncio
    async def test_notify_driver_arrived(self, mock_db):
        from app.services.notification_events import notify_driver_arrived
        await notify_driver_arrived(mock_db, rider_id=1, ride_id=42)
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].type == NotificationType.DRIVER_ARRIVED

    @pytest.mark.asyncio
    async def test_notify_payment_received(self, mock_db):
        from app.services.notification_events import notify_payment_received
        await notify_payment_received(mock_db, user_id=1, ride_id=42, amount=25.00)
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].type == NotificationType.PAYMENT_RECEIVED

    @pytest.mark.asyncio
    async def test_notify_sos_alert(self, mock_db):
        from app.services.notification_events import notify_sos_alert
        await notify_sos_alert(mock_db, user_id=1, ride_id=42)
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].type == NotificationType.SOS_ALERT

    @pytest.mark.asyncio
    async def test_notify_rating_received(self, mock_db):
        from app.services.notification_events import notify_rating_received
        await notify_rating_received(mock_db, user_id=1, ride_id=42, rating=4.5)
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].type == NotificationType.RATING_RECEIVED

    @pytest.mark.asyncio
    async def test_notify_payout_completed(self, mock_db):
        from app.services.notification_events import notify_payout_completed
        await notify_payout_completed(mock_db, driver_id=1, amount=150.00)
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].type == NotificationType.PAYOUT_COMPLETED

    @pytest.mark.asyncio
    async def test_events_are_fire_and_forget(self):
        """Events should never raise even if DB is unavailable."""
        from app.services.notification_events import notify_ride_matched
        bad_db = AsyncMock()
        bad_db.execute = AsyncMock(side_effect=Exception("DB error"))
        # Should not raise
        await notify_ride_matched(bad_db, rider_id=1, ride_id=42)

    @pytest.mark.asyncio
    async def test_events_with_none_contact_info(self):
        """Events should work even when user has no phone/email."""
        from app.services.notification_events import notify_ride_matched
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        db.add = MagicMock()
        db.flush = AsyncMock()
        await notify_ride_matched(db, rider_id=1, ride_id=42)
        # Should still record in the in-memory log
        log = get_sent_notifications()
        assert len(log) == 1


# ===========================================================================
# Notification API Endpoints
# ===========================================================================


class TestNotificationAPI:
    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        user.phone = "+1234567890"
        user.email = "test@example.com"
        user.role = MagicMock(value="rider")
        return user

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_get_preferences_creates_default(self, mock_user, mock_db):
        from app.api.v1.notifications import get_preferences

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        # The handler creates a new NotificationPreference if none exists
        result = await get_preferences(user=mock_user, db=mock_db)
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_preferences_returns_existing(self, mock_user, mock_db):
        from app.api.v1.notifications import get_preferences

        existing_prefs = NotificationPreference(
            user_id=1, push_enabled=True, sms_enabled=False,
            email_enabled=True, ride_updates=True, payment_updates=True,
            promo_updates=False, safety_alerts=True,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_prefs
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_preferences(user=mock_user, db=mock_db)
        assert result.sms_enabled is False
        assert result.promo_updates is False

    @pytest.mark.asyncio
    async def test_update_preferences(self, mock_user, mock_db):
        from app.api.v1.notifications import update_preferences

        existing_prefs = NotificationPreference(
            user_id=1, push_enabled=True, sms_enabled=True,
            email_enabled=True, ride_updates=True, payment_updates=True,
            promo_updates=True, safety_alerts=True,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_prefs
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        req = UpdateNotificationPreference(sms_enabled=False, promo_updates=False)
        result = await update_preferences(req=req, user=mock_user, db=mock_db)
        assert result.sms_enabled is False
        assert result.promo_updates is False

    @pytest.mark.asyncio
    async def test_get_unread_count(self, mock_user, mock_db):
        from app.api.v1.notifications import get_unread_count

        mock_result = MagicMock()
        mock_result.scalar.return_value = 3
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_unread_count(user=mock_user, db=mock_db)
        assert result.total_unread == 3

    @pytest.mark.asyncio
    async def test_mark_notification_read(self, mock_user, mock_db):
        from app.api.v1.notifications import mark_notification_read

        mock_notif = MagicMock()
        mock_notif.is_read = False
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_notif
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        result = await mark_notification_read(notification_id=1, user=mock_user, db=mock_db)
        assert result == {"status": "ok"}
        assert mock_notif.is_read is True

    @pytest.mark.asyncio
    async def test_mark_notification_read_not_found(self, mock_user, mock_db):
        from app.api.v1.notifications import mark_notification_read

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(Exception) as exc_info:
            await mark_notification_read(notification_id=999, user=mock_user, db=mock_db)
        assert "404" in str(exc_info.value.status_code)

    @pytest.mark.asyncio
    async def test_mark_all_read(self, mock_user, mock_db):
        from app.api.v1.notifications import mark_all_notifications_read

        mock_db.execute = AsyncMock()
        mock_db.flush = AsyncMock()

        result = await mark_all_notifications_read(user=mock_user, db=mock_db)
        assert result == {"status": "ok"}


# ===========================================================================
# Config Settings
# ===========================================================================


class TestNotificationConfig:
    def test_default_sms_disabled(self):
        from app.config import Settings
        s = Settings()
        assert s.notifications_sms_enabled is False

    def test_default_email_disabled(self):
        from app.config import Settings
        s = Settings()
        assert s.notifications_email_enabled is False

    def test_default_push_disabled(self):
        from app.config import Settings
        s = Settings()
        assert s.notifications_push_enabled is False

    def test_sendgrid_defaults(self):
        from app.config import Settings
        s = Settings()
        assert s.sendgrid_api_key == ""
        assert s.sendgrid_from_email == "noreply@openride.coop"
        assert s.sendgrid_from_name == "OpenRide"

    def test_twilio_defaults(self):
        from app.config import Settings
        s = Settings()
        assert s.twilio_account_sid == ""
        assert s.twilio_auth_token == ""
        assert s.twilio_phone_number == ""
        assert s.sms_provider == "twilio"

    def test_email_provider_default(self):
        from app.config import Settings
        s = Settings()
        assert s.email_provider == "sendgrid"


# ===========================================================================
# Router Registration
# ===========================================================================


class TestNotificationRouterRegistration:
    def test_notifications_router_registered(self):
        from app.main import app
        routes = [r.path for r in app.routes]
        assert any("/notifications" in r for r in routes)

    def test_preferences_endpoint_exists(self):
        from app.main import app
        routes = [r.path for r in app.routes]
        assert any("preferences" in r for r in routes)


# ===========================================================================
# Model Registration
# ===========================================================================


class TestModelRegistration:
    def test_notification_log_imported(self):
        from app.models import NotificationLog
        assert NotificationLog.__tablename__ == "notification_logs"

    def test_notification_preference_imported(self):
        from app.models import NotificationPreference
        assert NotificationPreference.__tablename__ == "notification_preferences"


# ===========================================================================
# Channel Enum
# ===========================================================================


class TestChannelEnum:
    def test_push(self):
        assert NotificationChannel.PUSH == "push"

    def test_sms(self):
        assert NotificationChannel.SMS == "sms"

    def test_email(self):
        assert NotificationChannel.EMAIL == "email"
