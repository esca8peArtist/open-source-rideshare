"""Tests for post-ride feedback prompt notifications.

Covers:
- NotificationType.FEEDBACK_PROMPT_RIDER exists
- NotificationType.FEEDBACK_PROMPT_DRIVER exists
- feedback_prompt_rider template: PUSH+SMS channels
- feedback_prompt_rider template: title contains "rate"
- feedback_prompt_rider template: body contains driver name
- feedback_prompt_rider template: body falls back gracefully without driver name
- feedback_prompt_driver template: PUSH+SMS channels
- feedback_prompt_driver template: title contains "rate"
- feedback_prompt_driver template: body contains rider name
- feedback_prompt_driver template: body falls back gracefully without rider name
- render() dispatch works for FEEDBACK_PROMPT_RIDER
- render() dispatch works for FEEDBACK_PROMPT_DRIVER
- notify_feedback_prompt_rider sends exactly one notification
- notify_feedback_prompt_rider sends to correct user
- notify_feedback_prompt_rider notification type is FEEDBACK_PROMPT_RIDER
- notify_feedback_prompt_rider ride_id stored in notification data
- notify_feedback_prompt_rider sends PUSH and SMS channels
- notify_feedback_prompt_rider still sends PUSH when user has no phone/email
- notify_feedback_prompt_rider failure does not raise
- notify_feedback_prompt_driver sends exactly one notification
- notify_feedback_prompt_driver sends to correct user
- notify_feedback_prompt_driver notification type is FEEDBACK_PROMPT_DRIVER
- notify_feedback_prompt_driver ride_id stored in notification data
- notify_feedback_prompt_driver sends PUSH and SMS channels
- notify_feedback_prompt_driver still sends PUSH when user has no phone/email
- notify_feedback_prompt_driver failure does not raise
- Wiring: complete_ride calls notify_feedback_prompt_rider
- Wiring: complete_ride calls notify_feedback_prompt_driver
- Wiring: rider feedback prompt failure does not block ride completion
- Wiring: driver feedback prompt failure does not block ride completion
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
from app.services.notification_templates import (
    feedback_prompt_rider,
    feedback_prompt_driver,
    render,
)


# ---------------------------------------------------------------------------
# Enum presence
# ---------------------------------------------------------------------------


class TestNotificationTypeEntries:
    def test_feedback_prompt_rider_exists(self):
        assert NotificationType.FEEDBACK_PROMPT_RIDER == "feedback_prompt_rider"

    def test_feedback_prompt_driver_exists(self):
        assert NotificationType.FEEDBACK_PROMPT_DRIVER == "feedback_prompt_driver"


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class TestFeedbackPromptRiderTemplate:
    def test_channels_push_and_sms(self):
        _, _, channels = feedback_prompt_rider()
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS in channels

    def test_no_email_channel(self):
        _, _, channels = feedback_prompt_rider()
        assert NotificationChannel.EMAIL not in channels

    def test_title_contains_rate(self):
        title, _, _ = feedback_prompt_rider()
        assert "rate" in title.lower()

    def test_body_contains_driver_name(self):
        _, body, _ = feedback_prompt_rider(driver_name="Alice")
        assert "Alice" in body

    def test_body_fallback_without_driver_name(self):
        title, body, _ = feedback_prompt_rider()
        assert title
        assert body

    def test_returns_three_tuple(self):
        result = feedback_prompt_rider(driver_name="Bob")
        assert len(result) == 3


class TestFeedbackPromptDriverTemplate:
    def test_channels_push_and_sms(self):
        _, _, channels = feedback_prompt_driver()
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS in channels

    def test_no_email_channel(self):
        _, _, channels = feedback_prompt_driver()
        assert NotificationChannel.EMAIL not in channels

    def test_title_contains_rate(self):
        title, _, _ = feedback_prompt_driver()
        assert "rate" in title.lower()

    def test_body_contains_rider_name(self):
        _, body, _ = feedback_prompt_driver(rider_name="Carol")
        assert "Carol" in body

    def test_body_fallback_without_rider_name(self):
        title, body, _ = feedback_prompt_driver()
        assert title
        assert body

    def test_returns_three_tuple(self):
        result = feedback_prompt_driver(rider_name="Dave")
        assert len(result) == 3


# ---------------------------------------------------------------------------
# render() dispatch
# ---------------------------------------------------------------------------


class TestRenderDispatch:
    def test_feedback_prompt_rider_returns_tuple(self):
        title, body, channels = render(NotificationType.FEEDBACK_PROMPT_RIDER, driver_name="Eve")
        assert isinstance(title, str)
        assert isinstance(body, str)
        assert isinstance(channels, list)

    def test_feedback_prompt_driver_returns_tuple(self):
        title, body, channels = render(NotificationType.FEEDBACK_PROMPT_DRIVER, rider_name="Frank")
        assert isinstance(title, str)
        assert isinstance(body, str)
        assert isinstance(channels, list)


# ---------------------------------------------------------------------------
# Dispatcher helpers
# ---------------------------------------------------------------------------


def _make_contact_db(phone: str | None = "+15550001111", email: str | None = "user@example.com"):
    """Return an AsyncMock db whose execute() returns (phone, email)."""
    db = AsyncMock()
    row = MagicMock()
    row.phone = phone
    row.email = email
    result = MagicMock()
    result.one_or_none.return_value = row
    db.execute.return_value = result
    return db


def _make_no_contact_db():
    """Return an AsyncMock db whose execute() returns None row (user not found)."""
    db = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = None
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# notify_feedback_prompt_rider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNotifyFeedbackPromptRider:
    async def test_sends_one_notification(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_feedback_prompt_rider
        await notify_feedback_prompt_rider(db, rider_id=1, ride_id=10, driver_name="Grace")

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.FEEDBACK_PROMPT_RIDER]
        assert len(sent) == 1

    async def test_sends_to_correct_user(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_feedback_prompt_rider
        await notify_feedback_prompt_rider(db, rider_id=7, ride_id=10, driver_name="Henry")

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.FEEDBACK_PROMPT_RIDER]
        assert sent[0].user_id == 7

    async def test_notification_type_is_feedback_prompt_rider(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_feedback_prompt_rider
        await notify_feedback_prompt_rider(db, rider_id=1, ride_id=10)

        sent = get_sent_notifications()
        types = [n.type for n in sent]
        assert NotificationType.FEEDBACK_PROMPT_RIDER in types

    async def test_ride_id_stored_in_notification(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_feedback_prompt_rider
        await notify_feedback_prompt_rider(db, rider_id=1, ride_id=99)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.FEEDBACK_PROMPT_RIDER]
        assert sent[0].ride_id == 99

    async def test_sends_push_and_sms_channels(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_feedback_prompt_rider
        await notify_feedback_prompt_rider(db, rider_id=1, ride_id=10, driver_name="Iris")

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.FEEDBACK_PROMPT_RIDER]
        channels = sent[0].channels
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS in channels

    async def test_still_sends_push_when_user_has_no_phone_or_email(self):
        # PUSH channel does not require phone or email — notification fires regardless
        clear_sent_notifications()
        db = _make_no_contact_db()

        from app.services.notification_events import notify_feedback_prompt_rider
        await notify_feedback_prompt_rider(db, rider_id=1, ride_id=10)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.FEEDBACK_PROMPT_RIDER]
        assert len(sent) == 1
        assert NotificationChannel.PUSH in sent[0].channels

    async def test_failure_does_not_raise(self):
        db = AsyncMock()
        db.execute.side_effect = RuntimeError("db exploded")

        from app.services.notification_events import notify_feedback_prompt_rider
        await notify_feedback_prompt_rider(db, rider_id=1, ride_id=10)  # must not raise


# ---------------------------------------------------------------------------
# notify_feedback_prompt_driver
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNotifyFeedbackPromptDriver:
    async def test_sends_one_notification(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_feedback_prompt_driver
        await notify_feedback_prompt_driver(db, driver_id=2, ride_id=20, rider_name="Jack")

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.FEEDBACK_PROMPT_DRIVER]
        assert len(sent) == 1

    async def test_sends_to_correct_user(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_feedback_prompt_driver
        await notify_feedback_prompt_driver(db, driver_id=9, ride_id=20, rider_name="Kate")

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.FEEDBACK_PROMPT_DRIVER]
        assert sent[0].user_id == 9

    async def test_notification_type_is_feedback_prompt_driver(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_feedback_prompt_driver
        await notify_feedback_prompt_driver(db, driver_id=2, ride_id=20)

        sent = get_sent_notifications()
        types = [n.type for n in sent]
        assert NotificationType.FEEDBACK_PROMPT_DRIVER in types

    async def test_ride_id_stored_in_notification(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_feedback_prompt_driver
        await notify_feedback_prompt_driver(db, driver_id=2, ride_id=77)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.FEEDBACK_PROMPT_DRIVER]
        assert sent[0].ride_id == 77

    async def test_sends_push_and_sms_channels(self):
        clear_sent_notifications()
        db = _make_contact_db()

        from app.services.notification_events import notify_feedback_prompt_driver
        await notify_feedback_prompt_driver(db, driver_id=2, ride_id=20, rider_name="Leo")

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.FEEDBACK_PROMPT_DRIVER]
        channels = sent[0].channels
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS in channels

    async def test_still_sends_push_when_user_has_no_phone_or_email(self):
        # PUSH channel does not require phone or email — notification fires regardless
        clear_sent_notifications()
        db = _make_no_contact_db()

        from app.services.notification_events import notify_feedback_prompt_driver
        await notify_feedback_prompt_driver(db, driver_id=2, ride_id=20)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.FEEDBACK_PROMPT_DRIVER]
        assert len(sent) == 1
        assert NotificationChannel.PUSH in sent[0].channels

    async def test_failure_does_not_raise(self):
        db = AsyncMock()
        db.execute.side_effect = RuntimeError("db exploded")

        from app.services.notification_events import notify_feedback_prompt_driver
        await notify_feedback_prompt_driver(db, driver_id=2, ride_id=20)  # must not raise


# ---------------------------------------------------------------------------
# Wiring — complete_ride
# ---------------------------------------------------------------------------


def _make_complete_ride_db(ride, estimated_fare=10.00):
    ride_result = MagicMock()
    ride_result.scalar_one_or_none.return_value = ride

    count_result = MagicMock()
    count_result.scalar.return_value = 1  # not first ride

    rider_obj = MagicMock()
    rider_obj.name = "Rider Name"
    rider_obj.referred_by = None
    rider_result = MagicMock()
    rider_result.scalar_one_or_none.return_value = rider_obj

    profile = MagicMock()
    profile.total_trips = 3
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = profile

    db = AsyncMock()
    db.execute.side_effect = [ride_result, count_result, rider_result, profile_result]
    return db


_WIRING_PATCHES = [
    patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock),
    patch("app.api.v1.rides.get_matching_engine", new_callable=AsyncMock),
    patch("app.services.notification_events.notify_ride_completed", new_callable=AsyncMock),
    patch("app.services.notification_events.notify_ride_completed_driver", new_callable=AsyncMock),
    patch("app.services.audit_events.audit_ride_completed", new_callable=AsyncMock),
    patch("app.services.rider_safety.send_trusted_contact_notifications", new_callable=AsyncMock),
    patch("app.services.driver_fatigue.log_ride_event"),
    patch("app.services.incentives.record_trip_completion", new_callable=AsyncMock),
    patch("app.services.driver_referral.check_and_award_driver_referral_bonus", new_callable=AsyncMock),
    patch("app.services.notification_events.notify_trip_receipt", new_callable=AsyncMock),
    patch("app.services.notification_events.notify_driver_earnings", new_callable=AsyncMock),
]


def _apply_wiring_patches(fn):
    for p in reversed(_WIRING_PATCHES):
        fn = p(fn)
    return fn


@pytest.mark.asyncio
@_apply_wiring_patches
async def test_complete_ride_calls_notify_feedback_prompt_rider(*mocks):
    """complete_ride fires notify_feedback_prompt_rider after finishing."""
    from app.api.v1.rides import complete_ride
    from app.models.ride import Ride, RideStatus
    from app.models.user import User, UserRole

    mocks[1].return_value = AsyncMock()  # get_matching_engine

    driver = MagicMock(spec=User)
    driver.id = 30
    driver.name = "Test Driver"
    driver.role = UserRole.DRIVER

    ride = MagicMock(spec=Ride)
    ride.id = 50
    ride.rider_id = 20
    ride.driver_id = 30
    ride.status = RideStatus.IN_PROGRESS
    ride.estimated_fare = 10.00
    ride.actual_fare = None
    ride.tip_amount = 0.0
    ride.promo_discount = 0.0
    ride.promo_code_id = None

    db = _make_complete_ride_db(ride)
    rider_calls = []

    async def fake_rider_prompt(db2, rider_id, ride_id, driver_name=""):
        rider_calls.append(ride_id)

    with patch("app.services.notification_events.notify_feedback_prompt_rider", new=fake_rider_prompt):
        with patch("app.services.notification_events.notify_feedback_prompt_driver", new_callable=AsyncMock):
            await complete_ride(ride_id=50, driver=driver, db=db)

    assert 50 in rider_calls


@pytest.mark.asyncio
@_apply_wiring_patches
async def test_complete_ride_calls_notify_feedback_prompt_driver(*mocks):
    """complete_ride fires notify_feedback_prompt_driver after finishing."""
    from app.api.v1.rides import complete_ride
    from app.models.ride import Ride, RideStatus
    from app.models.user import User, UserRole

    mocks[1].return_value = AsyncMock()  # get_matching_engine

    driver = MagicMock(spec=User)
    driver.id = 31
    driver.name = "Test Driver 2"
    driver.role = UserRole.DRIVER

    ride = MagicMock(spec=Ride)
    ride.id = 51
    ride.rider_id = 21
    ride.driver_id = 31
    ride.status = RideStatus.IN_PROGRESS
    ride.estimated_fare = 10.00
    ride.actual_fare = None
    ride.tip_amount = 0.0
    ride.promo_discount = 0.0
    ride.promo_code_id = None

    db = _make_complete_ride_db(ride)
    driver_calls = []

    async def fake_driver_prompt(db2, driver_id, ride_id, rider_name=""):
        driver_calls.append(ride_id)

    with patch("app.services.notification_events.notify_feedback_prompt_rider", new_callable=AsyncMock):
        with patch("app.services.notification_events.notify_feedback_prompt_driver", new=fake_driver_prompt):
            await complete_ride(ride_id=51, driver=driver, db=db)

    assert 51 in driver_calls


@pytest.mark.asyncio
@_apply_wiring_patches
async def test_rider_feedback_prompt_failure_does_not_block_completion(*mocks):
    """A crash in notify_feedback_prompt_rider must not prevent ride completion."""
    from app.api.v1.rides import complete_ride
    from app.models.ride import Ride, RideStatus
    from app.models.user import User, UserRole

    mocks[1].return_value = AsyncMock()  # get_matching_engine

    driver = MagicMock(spec=User)
    driver.id = 32
    driver.name = "Crash Driver"
    driver.role = UserRole.DRIVER

    ride = MagicMock(spec=Ride)
    ride.id = 52
    ride.rider_id = 22
    ride.driver_id = 32
    ride.status = RideStatus.IN_PROGRESS
    ride.estimated_fare = 8.00
    ride.actual_fare = None
    ride.tip_amount = 0.0
    ride.promo_discount = 0.0
    ride.promo_code_id = None

    db = _make_complete_ride_db(ride, estimated_fare=8.00)

    async def crashing_rider_prompt(db2, rider_id, ride_id, driver_name=""):
        raise RuntimeError("push provider down")

    with patch("app.services.notification_events.notify_feedback_prompt_rider", new=crashing_rider_prompt):
        with patch("app.services.notification_events.notify_feedback_prompt_driver", new_callable=AsyncMock):
            result = await complete_ride(ride_id=52, driver=driver, db=db)

    assert result["status"] == "completed"


@pytest.mark.asyncio
@_apply_wiring_patches
async def test_driver_feedback_prompt_failure_does_not_block_completion(*mocks):
    """A crash in notify_feedback_prompt_driver must not prevent ride completion."""
    from app.api.v1.rides import complete_ride
    from app.models.ride import Ride, RideStatus
    from app.models.user import User, UserRole

    mocks[1].return_value = AsyncMock()  # get_matching_engine

    driver = MagicMock(spec=User)
    driver.id = 33
    driver.name = "Crash Driver 2"
    driver.role = UserRole.DRIVER

    ride = MagicMock(spec=Ride)
    ride.id = 53
    ride.rider_id = 23
    ride.driver_id = 33
    ride.status = RideStatus.IN_PROGRESS
    ride.estimated_fare = 8.00
    ride.actual_fare = None
    ride.tip_amount = 0.0
    ride.promo_discount = 0.0
    ride.promo_code_id = None

    db = _make_complete_ride_db(ride, estimated_fare=8.00)

    async def crashing_driver_prompt(db2, driver_id, ride_id, rider_name=""):
        raise RuntimeError("sms provider down")

    with patch("app.services.notification_events.notify_feedback_prompt_rider", new_callable=AsyncMock):
        with patch("app.services.notification_events.notify_feedback_prompt_driver", new=crashing_driver_prompt):
            result = await complete_ride(ride_id=53, driver=driver, db=db)

    assert result["status"] == "completed"
