"""Tests for streak completion and streak-lost notifications.

Covers:
- NotificationType entries exist for streak events
- notification_templates.py renders correct title/body/channels
- notify_streak_completed dispatches with correct notification type
- notify_streak_lost dispatches with correct notification type
- incentives.record_trip_completion fires notify_streak_completed on streak finish
- incentives.record_trip_completion fires notify_streak_lost on cancellation
- Notification failure never raises out of incentive service
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.services.notifications import (
    NotificationChannel,
    NotificationType,
    clear_sent_notifications,
    get_sent_notifications,
)
from app.services.notification_templates import render, streak_completed, streak_lost
from app.models.incentive import DriverIncentiveProgress, IncentiveProgram, ProgressStatus, ProgramType
from app.models.ride import Ride, RideStatus

NOW = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Enum presence
# ---------------------------------------------------------------------------


class TestNotificationTypeEntries:
    def test_streak_completed_exists(self):
        assert NotificationType.STREAK_COMPLETED == "streak_completed"

    def test_streak_lost_exists(self):
        assert NotificationType.STREAK_LOST == "streak_lost"


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class TestStreakCompletedTemplate:
    def test_default_title(self):
        title, _, _ = streak_completed()
        assert "Streak bonus earned" in title

    def test_body_includes_program_name(self):
        _, body, _ = streak_completed(program_name="Weekend Sprint")
        assert "Weekend Sprint" in body

    def test_body_includes_bonus_amount(self):
        _, body, _ = streak_completed(program_name="Sprint", bonus_amount=25.0)
        assert "25.0" in body or "25" in body

    def test_channels_include_push_and_email(self):
        _, _, channels = streak_completed()
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.EMAIL in channels

    def test_render_dispatch(self):
        title, body, channels = render(NotificationType.STREAK_COMPLETED, program_name="Sprint", bonus_amount=10.0)
        assert "Sprint" in body
        assert NotificationChannel.PUSH in channels


class TestStreakLostTemplate:
    def test_default_title(self):
        title, _, _ = streak_lost()
        assert "Streak reset" in title or "reset" in title.lower()

    def test_body_includes_program_name(self):
        _, body, _ = streak_lost(program_name="Daily Grind")
        assert "Daily Grind" in body

    def test_body_mentions_cancellation(self):
        _, body, _ = streak_lost()
        assert "cancell" in body.lower()

    def test_channels_include_push(self):
        _, _, channels = streak_lost()
        assert NotificationChannel.PUSH in channels

    def test_render_dispatch(self):
        title, body, channels = render(NotificationType.STREAK_LOST, program_name="Daily Grind")
        assert "Daily Grind" in body


# ---------------------------------------------------------------------------
# Event dispatcher helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_notifications():
    clear_sent_notifications()
    yield
    clear_sent_notifications()


class TestNotifyStreakCompleted:
    @pytest.mark.asyncio
    async def test_dispatches_streak_completed_type(self):
        from app.services.notification_events import notify_streak_completed

        db = AsyncMock()
        user_row = MagicMock()
        user_row.phone = "+15551234567"
        user_row.email = "driver@example.com"
        contact_result = MagicMock()
        contact_result.one_or_none.return_value = user_row
        db.execute.return_value = contact_result

        await notify_streak_completed(db, driver_id=42, program_name="Weekend Sprint", bonus_amount=15.0, program_id=7)

        sent = get_sent_notifications()
        assert len(sent) == 1
        assert sent[0].type == NotificationType.STREAK_COMPLETED
        assert sent[0].user_id == 42

    @pytest.mark.asyncio
    async def test_notification_data_contains_program_info(self):
        from app.services.notification_events import notify_streak_completed

        db = AsyncMock()
        contact_result = MagicMock()
        contact_result.one_or_none.return_value = None
        db.execute.return_value = contact_result

        await notify_streak_completed(db, driver_id=1, program_name="Sprint", bonus_amount=20.0, program_id=3)

        sent = get_sent_notifications()
        assert sent[0].data["program_name"] == "Sprint"
        assert sent[0].data["bonus_amount"] == 20.0
        assert sent[0].data["program_id"] == 3

    @pytest.mark.asyncio
    async def test_does_not_raise_on_db_failure(self):
        from app.services.notification_events import notify_streak_completed

        db = AsyncMock()
        db.execute.side_effect = RuntimeError("DB down")

        # Must not raise
        await notify_streak_completed(db, driver_id=1, program_name="Sprint", bonus_amount=10.0)


class TestNotifyStreakLost:
    @pytest.mark.asyncio
    async def test_dispatches_streak_lost_type(self):
        from app.services.notification_events import notify_streak_lost

        db = AsyncMock()
        contact_result = MagicMock()
        contact_result.one_or_none.return_value = None
        db.execute.return_value = contact_result

        await notify_streak_lost(db, driver_id=99, program_name="Daily Grind", program_id=5)

        sent = get_sent_notifications()
        assert len(sent) == 1
        assert sent[0].type == NotificationType.STREAK_LOST
        assert sent[0].user_id == 99

    @pytest.mark.asyncio
    async def test_notification_data_contains_program_info(self):
        from app.services.notification_events import notify_streak_lost

        db = AsyncMock()
        contact_result = MagicMock()
        contact_result.one_or_none.return_value = None
        db.execute.return_value = contact_result

        await notify_streak_lost(db, driver_id=2, program_name="Daily Grind", program_id=8)

        sent = get_sent_notifications()
        assert sent[0].data["program_name"] == "Daily Grind"
        assert sent[0].data["program_id"] == 8

    @pytest.mark.asyncio
    async def test_does_not_raise_on_db_failure(self):
        from app.services.notification_events import notify_streak_lost

        db = AsyncMock()
        db.execute.side_effect = RuntimeError("DB down")

        await notify_streak_lost(db, driver_id=1, program_name="Sprint")


# ---------------------------------------------------------------------------
# Wiring: incentives.record_trip_completion fires notifications
# ---------------------------------------------------------------------------


def _make_program(
    program_id: int = 1,
    name: str = "Test Streak",
    bonus_amount: float = 20.0,
    trip_target: int = 2,
) -> MagicMock:
    p = MagicMock(spec=IncentiveProgram)
    p.id = program_id
    p.name = name
    p.program_type = ProgramType.STREAK.value
    p.bonus_amount = bonus_amount
    p.trip_target = trip_target
    p.start_date = date.today()
    p.end_date = None
    p.is_active = True
    p.start_time = None
    p.end_time = None
    p.days_of_week = None
    return p


def _make_progress(
    driver_id: int = 10,
    program_id: int = 1,
    trips_completed: int = 1,
    status: str = ProgressStatus.ACTIVE.value,
) -> MagicMock:
    prog = MagicMock(spec=DriverIncentiveProgress)
    prog.driver_id = driver_id
    prog.program_id = program_id
    prog.trips_completed = trips_completed
    prog.status = status
    prog.period_start = date.today()
    prog.bonus_earned = 0.0
    prog.completed_at = None
    return prog


class TestStreakNotificationWiring:
    @pytest.mark.asyncio
    @patch("app.services.notification_events.notify_streak_completed", new_callable=AsyncMock)
    async def test_streak_completed_notification_fires(self, mock_notify):
        """notify_streak_completed is called when streak hits trip_target."""
        from app.services.incentives import record_trip_completion

        program = _make_program(program_id=1, name="Weekend Sprint", bonus_amount=25.0, trip_target=2)
        # progress already has 1 trip, this completion brings it to 2 (== target)
        progress = _make_progress(driver_id=10, program_id=1, trips_completed=1)

        db = AsyncMock()
        programs_result = MagicMock()
        programs_result.scalars.return_value.all.return_value = [program]

        progress_result = MagicMock()
        progress_result.scalar_one_or_none.return_value = progress

        # No cancellations found
        cancel_result = MagicMock()
        cancel_result.scalar_one_or_none.return_value = None

        db.execute.side_effect = [programs_result, progress_result, cancel_result]
        db.flush = AsyncMock()

        await record_trip_completion(db, driver_id=10, ride_id=5, completed_at=NOW)

        mock_notify.assert_awaited_once()
        call_kwargs = mock_notify.call_args
        assert call_kwargs.kwargs.get("driver_id") == 10 or call_kwargs.args[1] == 10

    @pytest.mark.asyncio
    @patch("app.services.notification_events.notify_streak_lost", new_callable=AsyncMock)
    async def test_streak_lost_notification_fires_on_cancellation(self, mock_notify):
        """notify_streak_lost is called when driver has a cancellation in period."""
        from app.services.incentives import record_trip_completion

        program = _make_program(program_id=2, name="Daily Grind", trip_target=5)
        progress = _make_progress(driver_id=10, program_id=2, trips_completed=2)

        db = AsyncMock()
        programs_result = MagicMock()
        programs_result.scalars.return_value.all.return_value = [program]

        progress_result = MagicMock()
        progress_result.scalar_one_or_none.return_value = progress

        # Cancellation found — streak expires
        cancellation_ride = MagicMock(spec=Ride)
        cancel_result = MagicMock()
        cancel_result.scalar_one_or_none.return_value = cancellation_ride

        db.execute.side_effect = [programs_result, progress_result, cancel_result]
        db.flush = AsyncMock()

        await record_trip_completion(db, driver_id=10, ride_id=6, completed_at=NOW)

        mock_notify.assert_awaited_once()
        call_kwargs = mock_notify.call_args
        assert call_kwargs.kwargs.get("driver_id") == 10 or call_kwargs.args[1] == 10

    @pytest.mark.asyncio
    @patch("app.services.notification_events.notify_streak_completed", new_callable=AsyncMock, side_effect=RuntimeError("notify failed"))
    async def test_notification_failure_does_not_block_streak_completion(self, mock_notify):
        """Streak status is COMPLETED even if notification raises."""
        from app.services.incentives import record_trip_completion

        program = _make_program(program_id=3, name="Sprint", bonus_amount=10.0, trip_target=2)
        progress = _make_progress(driver_id=11, program_id=3, trips_completed=1)

        db = AsyncMock()
        programs_result = MagicMock()
        programs_result.scalars.return_value.all.return_value = [program]

        progress_result = MagicMock()
        progress_result.scalar_one_or_none.return_value = progress

        cancel_result = MagicMock()
        cancel_result.scalar_one_or_none.return_value = None

        db.execute.side_effect = [programs_result, progress_result, cancel_result]
        db.flush = AsyncMock()

        # Should not raise despite notification failure
        updated = await record_trip_completion(db, driver_id=11, ride_id=7, completed_at=NOW)
        assert len(updated) == 1
        assert updated[0].status == ProgressStatus.COMPLETED.value

    @pytest.mark.asyncio
    @patch("app.services.notification_events.notify_streak_lost", new_callable=AsyncMock, side_effect=RuntimeError("notify failed"))
    async def test_notification_failure_does_not_block_streak_expiry(self, mock_notify):
        """Streak is marked EXPIRED even if notification raises."""
        from app.services.incentives import record_trip_completion

        program = _make_program(program_id=4, name="Sprint", trip_target=5)
        progress = _make_progress(driver_id=12, program_id=4, trips_completed=3)

        db = AsyncMock()
        programs_result = MagicMock()
        programs_result.scalars.return_value.all.return_value = [program]

        progress_result = MagicMock()
        progress_result.scalar_one_or_none.return_value = progress

        cancellation_ride = MagicMock(spec=Ride)
        cancel_result = MagicMock()
        cancel_result.scalar_one_or_none.return_value = cancellation_ride

        db.execute.side_effect = [programs_result, progress_result, cancel_result]
        db.flush = AsyncMock()

        updated = await record_trip_completion(db, driver_id=12, ride_id=8, completed_at=NOW)
        assert len(updated) == 1
        assert updated[0].status == ProgressStatus.EXPIRED.value
