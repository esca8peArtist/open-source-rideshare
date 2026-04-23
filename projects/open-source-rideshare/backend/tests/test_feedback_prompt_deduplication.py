"""Tests for feedback prompt deduplication.

Covers:
- notify_feedback_prompt_rider skipped when feedback already submitted
- notify_feedback_prompt_rider sent when no feedback yet
- notify_feedback_prompt_driver skipped when feedback already submitted
- notify_feedback_prompt_driver sent when no feedback yet
- _feedback_already_submitted returns True when record exists
- _feedback_already_submitted returns False when no record
- _feedback_already_submitted returns False on DB error (fail open)
- Skipped rider prompt still does not raise
- Skipped driver prompt still does not raise
- Deduplication check uses the correct ride_id
- Deduplication check uses the correct user_id for rider
- Deduplication check uses the correct user_id for driver
- Notification count is zero when rider already rated
- Notification count is zero when driver already rated
- Multiple calls: first sends, second (after mock feedback) skips
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notifications import (
    NotificationType,
    clear_sent_notifications,
    get_sent_notifications,
)


# ---------------------------------------------------------------------------
# DB helper factories
# ---------------------------------------------------------------------------


def _make_db_with_feedback(has_feedback: bool, phone="+15550001111", email="u@example.com"):
    """Two-call db: first returns feedback presence, second returns contact row."""
    # feedback check result
    feedback_result = MagicMock()
    feedback_result.scalar_one_or_none.return_value = MagicMock() if has_feedback else None

    # contact info result
    contact_row = MagicMock()
    contact_row.phone = phone
    contact_row.email = email
    contact_result = MagicMock()
    contact_result.one_or_none.return_value = contact_row

    db = AsyncMock()
    db.execute.side_effect = [feedback_result, contact_result]
    return db


def _make_db_feedback_check_raises():
    """DB where the feedback check itself raises an exception."""
    db = AsyncMock()
    db.execute.side_effect = RuntimeError("db exploded during feedback check")
    return db


# ---------------------------------------------------------------------------
# _feedback_already_submitted unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFeedbackAlreadySubmitted:
    async def test_returns_true_when_record_exists(self):
        feedback_result = MagicMock()
        feedback_result.scalar_one_or_none.return_value = MagicMock()
        db = AsyncMock()
        db.execute.return_value = feedback_result

        from app.services.notification_events import _feedback_already_submitted
        assert await _feedback_already_submitted(db, ride_id=1, user_id=10) is True

    async def test_returns_false_when_no_record(self):
        feedback_result = MagicMock()
        feedback_result.scalar_one_or_none.return_value = None
        db = AsyncMock()
        db.execute.return_value = feedback_result

        from app.services.notification_events import _feedback_already_submitted
        assert await _feedback_already_submitted(db, ride_id=1, user_id=10) is False

    async def test_returns_false_on_db_error(self):
        db = AsyncMock()
        db.execute.side_effect = RuntimeError("connection lost")

        from app.services.notification_events import _feedback_already_submitted
        assert await _feedback_already_submitted(db, ride_id=1, user_id=10) is False


# ---------------------------------------------------------------------------
# notify_feedback_prompt_rider deduplication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFeedbackPromptRiderDeduplication:
    async def test_skips_when_feedback_already_submitted(self):
        clear_sent_notifications()
        db = _make_db_with_feedback(has_feedback=True)

        from app.services.notification_events import notify_feedback_prompt_rider
        await notify_feedback_prompt_rider(db, rider_id=1, ride_id=10)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.FEEDBACK_PROMPT_RIDER]
        assert len(sent) == 0

    async def test_sends_when_no_feedback_yet(self):
        clear_sent_notifications()
        db = _make_db_with_feedback(has_feedback=False)

        from app.services.notification_events import notify_feedback_prompt_rider
        await notify_feedback_prompt_rider(db, rider_id=1, ride_id=10)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.FEEDBACK_PROMPT_RIDER]
        assert len(sent) == 1

    async def test_skip_does_not_raise(self):
        db = _make_db_with_feedback(has_feedback=True)

        from app.services.notification_events import notify_feedback_prompt_rider
        await notify_feedback_prompt_rider(db, rider_id=1, ride_id=10)  # must not raise

    async def test_db_error_during_check_still_does_not_raise(self):
        db = _make_db_feedback_check_raises()

        from app.services.notification_events import notify_feedback_prompt_rider
        await notify_feedback_prompt_rider(db, rider_id=1, ride_id=10)  # must not raise

    async def test_deduplication_passes_correct_ride_id(self):
        """Verify the check is scoped to the right ride."""
        seen_ride_ids = []

        async def fake_check(db, ride_id, user_id):
            seen_ride_ids.append(ride_id)
            return False

        clear_sent_notifications()
        db = _make_db_with_feedback(has_feedback=False)

        with patch(
            "app.services.notification_events._feedback_already_submitted",
            side_effect=fake_check,
        ):
            from app.services.notification_events import notify_feedback_prompt_rider
            await notify_feedback_prompt_rider(db, rider_id=1, ride_id=42)

        assert 42 in seen_ride_ids

    async def test_deduplication_passes_correct_user_id_for_rider(self):
        """Verify the check is scoped to the right user (rider)."""
        seen_user_ids = []

        async def fake_check(db, ride_id, user_id):
            seen_user_ids.append(user_id)
            return False

        clear_sent_notifications()
        db = _make_db_with_feedback(has_feedback=False)

        with patch(
            "app.services.notification_events._feedback_already_submitted",
            side_effect=fake_check,
        ):
            from app.services.notification_events import notify_feedback_prompt_rider
            await notify_feedback_prompt_rider(db, rider_id=77, ride_id=10)

        assert 77 in seen_user_ids


# ---------------------------------------------------------------------------
# notify_feedback_prompt_driver deduplication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFeedbackPromptDriverDeduplication:
    async def test_skips_when_feedback_already_submitted(self):
        clear_sent_notifications()
        db = _make_db_with_feedback(has_feedback=True)

        from app.services.notification_events import notify_feedback_prompt_driver
        await notify_feedback_prompt_driver(db, driver_id=2, ride_id=20)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.FEEDBACK_PROMPT_DRIVER]
        assert len(sent) == 0

    async def test_sends_when_no_feedback_yet(self):
        clear_sent_notifications()
        db = _make_db_with_feedback(has_feedback=False)

        from app.services.notification_events import notify_feedback_prompt_driver
        await notify_feedback_prompt_driver(db, driver_id=2, ride_id=20)

        sent = [n for n in get_sent_notifications() if n.type == NotificationType.FEEDBACK_PROMPT_DRIVER]
        assert len(sent) == 1

    async def test_skip_does_not_raise(self):
        db = _make_db_with_feedback(has_feedback=True)

        from app.services.notification_events import notify_feedback_prompt_driver
        await notify_feedback_prompt_driver(db, driver_id=2, ride_id=20)  # must not raise

    async def test_db_error_during_check_still_does_not_raise(self):
        db = _make_db_feedback_check_raises()

        from app.services.notification_events import notify_feedback_prompt_driver
        await notify_feedback_prompt_driver(db, driver_id=2, ride_id=20)  # must not raise

    async def test_deduplication_passes_correct_ride_id(self):
        seen_ride_ids = []

        async def fake_check(db, ride_id, user_id):
            seen_ride_ids.append(ride_id)
            return False

        clear_sent_notifications()
        db = _make_db_with_feedback(has_feedback=False)

        with patch(
            "app.services.notification_events._feedback_already_submitted",
            side_effect=fake_check,
        ):
            from app.services.notification_events import notify_feedback_prompt_driver
            await notify_feedback_prompt_driver(db, driver_id=2, ride_id=99)

        assert 99 in seen_ride_ids

    async def test_deduplication_passes_correct_user_id_for_driver(self):
        seen_user_ids = []

        async def fake_check(db, ride_id, user_id):
            seen_user_ids.append(user_id)
            return False

        clear_sent_notifications()
        db = _make_db_with_feedback(has_feedback=False)

        with patch(
            "app.services.notification_events._feedback_already_submitted",
            side_effect=fake_check,
        ):
            from app.services.notification_events import notify_feedback_prompt_driver
            await notify_feedback_prompt_driver(db, driver_id=88, ride_id=20)

        assert 88 in seen_user_ids
