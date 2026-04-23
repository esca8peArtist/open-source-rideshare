"""Tests for driver activation and suspension notifications.

Covers:
- NotificationType entries exist for all 4 relevant types
- background_check_approved template: channels, title, body with/without name
- background_check_action_required template: channels, title, body with/without name
- driver_activated template: channels, title, body with/without name
- driver_suspended template: channels, title, body with reason, without reason
- render() dispatch returns 3-tuples for all 4 types
- notify_driver_activated sends exactly one notification
- notify_driver_activated sends to the correct user
- notify_driver_activated notification type is DRIVER_ACTIVATED
- notify_driver_activated does nothing when user not found
- notify_driver_activated failure does not raise
- notify_driver_suspended sends exactly one notification
- notify_driver_suspended notification type is DRIVER_SUSPENDED
- notify_driver_suspended does nothing when user not found
- notify_driver_suspended failure does not raise
- activate_driver calls notify_driver_activated (wiring)
- suspend_driver calls notify_driver_suspended (wiring)
- notification failure in activate_driver does not raise
- notification failure in suspend_driver does not raise
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
    background_check_approved,
    background_check_action_required,
    driver_activated,
    driver_suspended,
    render,
)


# ---------------------------------------------------------------------------
# Enum presence
# ---------------------------------------------------------------------------


class TestNotificationTypeEntries:
    def test_driver_activated_exists(self):
        assert NotificationType.DRIVER_ACTIVATED == "driver_activated"

    def test_driver_suspended_exists(self):
        assert NotificationType.DRIVER_SUSPENDED == "driver_suspended"

    def test_background_check_approved_exists(self):
        assert NotificationType.BACKGROUND_CHECK_APPROVED == "background_check_approved"

    def test_background_check_action_required_exists(self):
        assert NotificationType.BACKGROUND_CHECK_ACTION_REQUIRED == "background_check_action_required"


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class TestBackgroundCheckApprovedTemplate:
    def test_channels_push_and_sms(self):
        _, _, channels = background_check_approved()
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS in channels

    def test_title_contains_approved(self):
        title, _, _ = background_check_approved()
        assert "approved" in title.lower()

    def test_body_contains_background_check(self):
        _, body, _ = background_check_approved()
        assert "background check" in body.lower()

    def test_body_contains_driver_name(self):
        _, body, _ = background_check_approved(driver_name="Alice")
        assert "Alice" in body

    def test_body_fallback_without_driver_name(self):
        _, body, _ = background_check_approved()
        # Should not crash and should still be a sensible message
        assert "background check" in body.lower()


class TestBackgroundCheckActionRequiredTemplate:
    def test_channels_push_and_sms(self):
        _, _, channels = background_check_action_required()
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS in channels

    def test_title_contains_attention_or_requires(self):
        title, _, _ = background_check_action_required()
        assert "attention" in title.lower() or "requires" in title.lower()

    def test_body_contains_driver_name(self):
        _, body, _ = background_check_action_required(driver_name="Bob")
        assert "Bob" in body

    def test_body_fallback_without_driver_name(self):
        _, body, _ = background_check_action_required()
        assert "background check" in body.lower()


class TestDriverActivatedTemplate:
    def test_channels_push_and_sms(self):
        _, _, channels = driver_activated()
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS in channels

    def test_title_contains_approved(self):
        title, _, _ = driver_activated()
        assert "approved" in title.lower()

    def test_body_contains_driver_name(self):
        _, body, _ = driver_activated(driver_name="Carol")
        assert "Carol" in body

    def test_body_fallback_without_driver_name(self):
        title, body, _ = driver_activated()
        # Should not crash
        assert "approved" in title.lower() or "congratulations" in body.lower()


class TestDriverSuspendedTemplate:
    def test_channels_push_and_sms(self):
        _, _, channels = driver_suspended()
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS in channels

    def test_title_contains_suspended(self):
        title, _, _ = driver_suspended()
        assert "suspended" in title.lower()

    def test_body_contains_reason_when_provided(self):
        _, body, _ = driver_suspended(driver_name="Dave", reason="policy violation")
        assert "policy violation" in body

    def test_body_no_crash_without_reason(self):
        _, body, _ = driver_suspended()
        assert "support" in body.lower()

    def test_body_contains_support_reference(self):
        _, body, _ = driver_suspended(driver_name="Eve", reason="")
        assert "support" in body.lower()

    def test_body_contains_driver_name(self):
        _, body, _ = driver_suspended(driver_name="Frank")
        assert "Frank" in body


# ---------------------------------------------------------------------------
# render() dispatch
# ---------------------------------------------------------------------------


class TestRenderDispatch:
    def test_background_check_approved_returns_tuple(self):
        result = render(NotificationType.BACKGROUND_CHECK_APPROVED)
        assert len(result) == 3
        title, body, channels = result
        assert isinstance(title, str)
        assert isinstance(body, str)
        assert isinstance(channels, list)

    def test_background_check_action_required_returns_tuple(self):
        result = render(NotificationType.BACKGROUND_CHECK_ACTION_REQUIRED)
        assert len(result) == 3

    def test_driver_activated_returns_tuple(self):
        result = render(NotificationType.DRIVER_ACTIVATED)
        assert len(result) == 3

    def test_driver_suspended_returns_tuple(self):
        result = render(NotificationType.DRIVER_SUSPENDED)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Dispatcher helpers
# ---------------------------------------------------------------------------


def _make_db():
    return AsyncMock()


def _make_user(user_id: int = 10, name: str = "Test Driver", phone: str = "+15550001111", email: str = "driver@example.com"):
    user = MagicMock()
    user.id = user_id
    user.name = name
    user.phone = phone
    user.email = email
    return user


def _mock_db_with_user(user):
    """Return an AsyncMock db whose execute() yields the given user."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# notify_driver_activated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNotifyDriverActivated:
    async def test_sends_one_notification(self):
        clear_sent_notifications()
        user = _make_user(user_id=10)
        db = _mock_db_with_user(user)

        from app.services.notification_events import notify_driver_activated
        await notify_driver_activated(db, driver_user_id=10)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DRIVER_ACTIVATED]
        assert len(sent) == 1

    async def test_sends_to_correct_user(self):
        clear_sent_notifications()
        user = _make_user(user_id=42)
        db = _mock_db_with_user(user)

        from app.services.notification_events import notify_driver_activated
        await notify_driver_activated(db, driver_user_id=42)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DRIVER_ACTIVATED]
        assert sent[0].user_id == 42

    async def test_notification_type_is_driver_activated(self):
        clear_sent_notifications()
        user = _make_user(user_id=10)
        db = _mock_db_with_user(user)

        from app.services.notification_events import notify_driver_activated
        await notify_driver_activated(db, driver_user_id=10)

        sent = get_sent_notifications()
        assert sent[-1].type == NotificationType.DRIVER_ACTIVATED

    async def test_does_nothing_when_user_not_found(self):
        clear_sent_notifications()
        db = _mock_db_with_user(None)

        from app.services.notification_events import notify_driver_activated
        await notify_driver_activated(db, driver_user_id=999)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DRIVER_ACTIVATED]
        assert len(sent) == 0

    async def test_failure_does_not_raise(self):
        db = AsyncMock()
        db.execute.side_effect = RuntimeError("db exploded")

        from app.services.notification_events import notify_driver_activated
        await notify_driver_activated(db, driver_user_id=10)  # must not raise


# ---------------------------------------------------------------------------
# notify_driver_suspended
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNotifyDriverSuspended:
    async def test_sends_one_notification(self):
        clear_sent_notifications()
        user = _make_user(user_id=10)
        db = _mock_db_with_user(user)

        from app.services.notification_events import notify_driver_suspended
        await notify_driver_suspended(db, driver_user_id=10, reason="policy violation")

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DRIVER_SUSPENDED]
        assert len(sent) == 1

    async def test_notification_type_is_driver_suspended(self):
        clear_sent_notifications()
        user = _make_user(user_id=10)
        db = _mock_db_with_user(user)

        from app.services.notification_events import notify_driver_suspended
        await notify_driver_suspended(db, driver_user_id=10, reason="inactive account")

        sent = get_sent_notifications()
        assert sent[-1].type == NotificationType.DRIVER_SUSPENDED

    async def test_does_nothing_when_user_not_found(self):
        clear_sent_notifications()
        db = _mock_db_with_user(None)

        from app.services.notification_events import notify_driver_suspended
        await notify_driver_suspended(db, driver_user_id=999, reason="test")

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.DRIVER_SUSPENDED]
        assert len(sent) == 0

    async def test_failure_does_not_raise(self):
        db = AsyncMock()
        db.execute.side_effect = RuntimeError("db exploded")

        from app.services.notification_events import notify_driver_suspended
        await notify_driver_suspended(db, driver_user_id=10, reason="test")  # must not raise


# ---------------------------------------------------------------------------
# Wiring — activate_driver and suspend_driver
# ---------------------------------------------------------------------------


def _make_onboarding_db(profile, onboarding):
    """Build a mock DB that serves the calls made by activate_driver / suspend_driver."""
    db = AsyncMock()

    # activate_driver calls: get_onboarding_checklist (many sub-calls) + get_or_create_onboarding
    # + profile select + db.flush
    # We use side_effect list to return different results per execute() call.
    # For simplicity, any call returning a checklist item succeeds.

    checklist_item = MagicMock()
    checklist_item.met = True
    checklist_item.required = True
    checklist_item.detail = "ok"

    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = profile
    profile_result.scalars.return_value.all.return_value = []

    onboarding_result = MagicMock()
    onboarding_result.scalar_one_or_none.return_value = onboarding

    # Return profile_result for all execute calls — good enough for wiring tests
    db.execute.return_value = profile_result
    return db


@pytest.mark.asyncio
class TestActivateDriverWiring:
    async def test_calls_notify_driver_activated(self):
        """activate_driver wires into notify_driver_activated."""
        from app.services.driver_onboarding import activate_driver

        profile = MagicMock()
        profile.id = 1
        profile.user_id = 10
        profile.insurance_policy = "POL-001"
        profile.is_approved = False

        onboarding = MagicMock()
        from app.models.driver_onboarding import OnboardingStatus
        onboarding.status = OnboardingStatus.PENDING_REVIEW

        called_with = []

        async def fake_notify(db, driver_user_id):
            called_with.append(driver_user_id)

        # Build a more complete mock DB that satisfies all checklist lookups
        db = AsyncMock()

        bg_result = MagicMock()
        bg_result.scalar_one_or_none.return_value = MagicMock()  # has a bg check

        license_result = MagicMock()
        license_result.scalar_one_or_none.return_value = MagicMock(expiry_date="2030-01-01")

        reg_result = MagicMock()
        reg_result.scalar_one_or_none.return_value = MagicMock(expiry_date="2030-01-01")

        inspection_result = MagicMock()
        inspection_result.scalar_one_or_none.return_value = MagicMock(expiry_date="2030-01-01")

        insurance_result = MagicMock()
        insurance_result.scalar_one_or_none.return_value = MagicMock(policy_end_date="2030-01-01")

        onboarding_result = MagicMock()
        onboarding_result.scalar_one_or_none.return_value = onboarding

        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = profile

        db.execute.side_effect = [
            profile_result,    # get_onboarding_checklist: DriverProfile fetch
            bg_result,         # _latest_approved_background_check
            license_result,    # _latest_approved_license
            reg_result,        # _latest_approved_registration
            inspection_result, # _latest_approved_inspection
            insurance_result,  # _latest_approved_insurance
            onboarding_result, # get_or_create_onboarding (checklist)
            onboarding_result, # get_or_create_onboarding (activate)
            profile_result,    # profile select in activate_driver
        ]

        with patch(
            "app.services.notification_events.notify_driver_activated",
            new=fake_notify,
        ):
            await activate_driver(driver_profile_id=1, admin_user_id=99, db=db)

        assert 10 in called_with

    async def test_notification_failure_does_not_raise(self):
        """A crash in notify_driver_activated must not prevent activate_driver from completing."""
        from app.services.driver_onboarding import activate_driver

        profile = MagicMock()
        profile.id = 1
        profile.user_id = 10
        profile.insurance_policy = "POL-001"
        profile.is_approved = False

        onboarding = MagicMock()
        from app.models.driver_onboarding import OnboardingStatus
        onboarding.status = OnboardingStatus.PENDING_REVIEW

        db = AsyncMock()

        bg_result = MagicMock()
        bg_result.scalar_one_or_none.return_value = MagicMock()

        license_result = MagicMock()
        license_result.scalar_one_or_none.return_value = MagicMock(expiry_date="2030-01-01")

        reg_result = MagicMock()
        reg_result.scalar_one_or_none.return_value = MagicMock(expiry_date="2030-01-01")

        inspection_result = MagicMock()
        inspection_result.scalar_one_or_none.return_value = MagicMock(expiry_date="2030-01-01")

        insurance_result = MagicMock()
        insurance_result.scalar_one_or_none.return_value = MagicMock(policy_end_date="2030-01-01")

        onboarding_result = MagicMock()
        onboarding_result.scalar_one_or_none.return_value = onboarding

        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = profile

        db.execute.side_effect = [
            profile_result,
            bg_result,
            license_result,
            reg_result,
            inspection_result,
            insurance_result,
            onboarding_result,
            onboarding_result,
            profile_result,
        ]

        async def crashing_notify(db2, driver_user_id):
            raise RuntimeError("notification provider down")

        with patch(
            "app.services.notification_events.notify_driver_activated",
            new=crashing_notify,
        ):
            result = await activate_driver(driver_profile_id=1, admin_user_id=99, db=db)

        assert result is onboarding


@pytest.mark.asyncio
class TestSuspendDriverWiring:
    async def test_calls_notify_driver_suspended(self):
        """suspend_driver wires into notify_driver_suspended."""
        from app.services.driver_onboarding import suspend_driver

        profile = MagicMock()
        profile.id = 1
        profile.user_id = 10
        profile.is_approved = True
        profile.is_online = True

        onboarding = MagicMock()
        from app.models.driver_onboarding import OnboardingStatus
        onboarding.status = OnboardingStatus.APPROVED

        db = AsyncMock()

        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = profile

        onboarding_result = MagicMock()
        onboarding_result.scalar_one_or_none.return_value = onboarding

        db.execute.side_effect = [profile_result, onboarding_result]

        called_with = []

        async def fake_notify(db2, driver_user_id, reason=""):
            called_with.append((driver_user_id, reason))

        with patch(
            "app.services.notification_events.notify_driver_suspended",
            new=fake_notify,
        ):
            await suspend_driver(
                driver_profile_id=1,
                reason="policy violation",
                admin_user_id=99,
                db=db,
            )

        assert (10, "policy violation") in called_with

    async def test_notification_failure_does_not_raise(self):
        """A crash in notify_driver_suspended must not prevent suspend_driver from completing."""
        from app.services.driver_onboarding import suspend_driver

        profile = MagicMock()
        profile.id = 1
        profile.user_id = 10
        profile.is_approved = True
        profile.is_online = True

        onboarding = MagicMock()
        from app.models.driver_onboarding import OnboardingStatus
        onboarding.status = OnboardingStatus.APPROVED

        db = AsyncMock()

        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = profile

        onboarding_result = MagicMock()
        onboarding_result.scalar_one_or_none.return_value = onboarding

        db.execute.side_effect = [profile_result, onboarding_result]

        async def crashing_notify(db2, driver_user_id, reason=""):
            raise RuntimeError("notification provider down")

        with patch(
            "app.services.notification_events.notify_driver_suspended",
            new=crashing_notify,
        ):
            result = await suspend_driver(
                driver_profile_id=1,
                reason="test reason",
                admin_user_id=99,
                db=db,
            )

        assert result is onboarding
