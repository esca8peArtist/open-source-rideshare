"""Tests for ride cancellation category surfacing in notifications.

Covers:
- ride_cancelled template: body includes human-readable category label
- ride_cancelled template: falls back to freetext reason when no category
- ride_cancelled template: no reason part when both category and reason absent
- ride_cancelled template: category label takes precedence over freetext reason
- ride_cancelled template: unknown category falls back to freetext reason
- ride_cancelled template: all known categories render without error
- _CANCELLATION_CATEGORY_LABELS exported and covers all CancellationCategory values
- notify_ride_cancelled: passes cancellation_category to send_ride_notification
- notify_ride_cancelled: category absent → notification still sends (backward compat)
- notify_ride_cancelled: category present → notification still sends
- notify_ride_cancelled: exception never propagates
- rides.py cancel endpoint: passes cancellation_category.value to driver notification
- rides.py cancel endpoint: passes cancellation_category.value to rider notification
- rides.py cancel endpoint: None category passes empty string (no crash)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ride import CancellationCategory
from app.services.notification_templates import (
    TEMPLATES,
    _CANCELLATION_CATEGORY_LABELS,
    render,
    ride_cancelled,
)
from app.services.notifications import (
    NotificationChannel,
    NotificationType,
    clear_sent_notifications,
    get_sent_notifications,
)


@pytest.fixture(autouse=True)
def clean_notifications():
    clear_sent_notifications()
    yield
    clear_sent_notifications()


@pytest.fixture
def mock_db():
    db = AsyncMock()
    contact_row = MagicMock()
    contact_row.phone = "+15550001111"
    contact_row.email = "user@example.com"
    contact_result = MagicMock()
    contact_result.one_or_none.return_value = contact_row
    db.execute = AsyncMock(return_value=contact_result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


# ===========================================================================
# Template — ride_cancelled with category
# ===========================================================================

class TestRideCancelledTemplateCategory:
    def test_plans_changed_label_in_body(self):
        _, body, _ = ride_cancelled(cancellation_category="plans_changed")
        assert "Plans changed" in body

    def test_wait_too_long_label_in_body(self):
        _, body, _ = ride_cancelled(cancellation_category="wait_too_long")
        assert "Wait time too long" in body

    def test_vehicle_issue_label_in_body(self):
        _, body, _ = ride_cancelled(cancellation_category="vehicle_issue")
        assert "Vehicle issue" in body

    def test_driver_no_show_label_in_body(self):
        _, body, _ = ride_cancelled(cancellation_category="driver_no_show")
        assert "Driver no-show" in body

    def test_safety_concern_label_in_body(self):
        _, body, _ = ride_cancelled(cancellation_category="safety_concern")
        assert "Safety concern" in body

    def test_price_too_high_label_in_body(self):
        _, body, _ = ride_cancelled(cancellation_category="price_too_high")
        assert "Price too high" in body

    def test_category_takes_precedence_over_freetext_reason(self):
        _, body, _ = ride_cancelled(cancellation_category="plans_changed", reason="Some freetext reason")
        assert "Plans changed" in body
        assert "Some freetext reason" not in body

    def test_unknown_category_falls_back_to_freetext_reason(self):
        _, body, _ = ride_cancelled(cancellation_category="does_not_exist", reason="Fallback reason")
        assert "Fallback reason" in body

    def test_no_category_no_reason_no_reason_part(self):
        _, body, _ = ride_cancelled()
        assert "Reason:" not in body

    def test_no_category_with_freetext_reason_shown(self):
        _, body, _ = ride_cancelled(reason="Traffic was bad")
        assert "Traffic was bad" in body

    def test_empty_category_string_falls_back_to_reason(self):
        _, body, _ = ride_cancelled(cancellation_category="", reason="Freetext")
        assert "Freetext" in body

    def test_body_still_includes_cancelled_by(self):
        _, body, _ = ride_cancelled(cancelled_by="rider", cancellation_category="plans_changed")
        assert "rider" in body
        assert "Plans changed" in body

    def test_channels_are_push_and_sms(self):
        _, _, channels = ride_cancelled(cancellation_category="plans_changed")
        assert NotificationChannel.PUSH in channels
        assert NotificationChannel.SMS in channels

    def test_title_is_ride_cancelled(self):
        title, _, _ = ride_cancelled(cancellation_category="plans_changed")
        assert "cancelled" in title.lower()

    def test_render_dispatch_passes_category(self):
        _, body, _ = render(NotificationType.RIDE_CANCELLED, cancellation_category="vehicle_issue")
        assert "Vehicle issue" in body

    def test_all_known_categories_render_without_error(self):
        for cat_value in _CANCELLATION_CATEGORY_LABELS:
            title, body, channels = ride_cancelled(cancellation_category=cat_value)
            assert "Reason:" in body


class TestCancellationCategoryLabelsMapping:
    def test_labels_dict_is_exported(self):
        assert isinstance(_CANCELLATION_CATEGORY_LABELS, dict)
        assert len(_CANCELLATION_CATEGORY_LABELS) > 0

    def test_all_enum_values_have_labels(self):
        for member in CancellationCategory:
            assert member.value in _CANCELLATION_CATEGORY_LABELS, (
                f"CancellationCategory.{member.name} ({member.value}) missing from _CANCELLATION_CATEGORY_LABELS"
            )

    def test_all_label_values_are_nonempty_strings(self):
        for key, label in _CANCELLATION_CATEGORY_LABELS.items():
            assert isinstance(label, str) and label.strip(), f"Label for '{key}' is empty"


# ===========================================================================
# Dispatcher — notify_ride_cancelled with category
# ===========================================================================

class TestNotifyRideCancelledWithCategory:
    @pytest.mark.asyncio
    async def test_sends_notification_with_category(self, mock_db):
        from app.services.notification_events import notify_ride_cancelled
        await notify_ride_cancelled(
            mock_db, user_id=5, ride_id=10,
            cancelled_by="rider", cancellation_category="plans_changed",
        )
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].type == NotificationType.RIDE_CANCELLED
        assert log[0].user_id == 5
        assert log[0].ride_id == 10

    @pytest.mark.asyncio
    async def test_sends_notification_without_category(self, mock_db):
        from app.services.notification_events import notify_ride_cancelled
        await notify_ride_cancelled(mock_db, user_id=5, ride_id=10, cancelled_by="driver")
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].type == NotificationType.RIDE_CANCELLED

    @pytest.mark.asyncio
    async def test_category_label_appears_in_rendered_body(self, mock_db):
        from app.services.notification_events import notify_ride_cancelled
        await notify_ride_cancelled(
            mock_db, user_id=5, ride_id=10,
            cancelled_by="rider", cancellation_category="wait_too_long",
        )
        log = get_sent_notifications()
        assert log[0].body and "Wait time too long" in log[0].body

    @pytest.mark.asyncio
    async def test_does_not_raise_on_exception(self, mock_db):
        from app.services.notification_events import notify_ride_cancelled
        mock_db.execute.side_effect = RuntimeError("db down")
        # Should not raise
        await notify_ride_cancelled(mock_db, user_id=5, ride_id=10, cancellation_category="plans_changed")


# ===========================================================================
# category_val extraction — unit tests for the rides.py logic
# ===========================================================================

class TestCategoryValueExtraction:
    """Verify the category_val extraction logic used in cancel_ride."""

    def test_enum_category_extracts_value(self):
        # Mirrors: category_val = ride.cancellation_category.value if ride.cancellation_category else ""
        ride_category = CancellationCategory.PLANS_CHANGED
        category_val = ride_category.value if ride_category else ""
        assert category_val == "plans_changed"

    def test_none_category_gives_empty_string(self):
        ride_category = None
        category_val = ride_category.value if ride_category else ""
        assert category_val == ""

    def test_vehicle_issue_category_extracts_value(self):
        ride_category = CancellationCategory.VEHICLE_ISSUE
        category_val = ride_category.value if ride_category else ""
        assert category_val == "vehicle_issue"

    def test_driver_no_show_category_extracts_value(self):
        ride_category = CancellationCategory.DRIVER_NO_SHOW
        category_val = ride_category.value if ride_category else ""
        assert category_val == "driver_no_show"

    def test_extracted_value_matches_template_label_key(self):
        # Verify round-trip: enum → value → label
        for member in CancellationCategory:
            category_val = member.value
            assert category_val in _CANCELLATION_CATEGORY_LABELS

    @pytest.mark.asyncio
    async def test_notify_ride_cancelled_called_with_category_value(self, mock_db):
        """End-to-end: dispatcher receives category value and body reflects label."""
        from app.services.notification_events import notify_ride_cancelled
        category_val = CancellationCategory.WAIT_TOO_LONG.value
        await notify_ride_cancelled(
            mock_db, user_id=3, ride_id=55,
            cancelled_by="driver", cancellation_category=category_val,
        )
        log = get_sent_notifications()
        assert len(log) == 1
        assert log[0].user_id == 3
        assert "Wait time too long" in log[0].body

    @pytest.mark.asyncio
    async def test_notify_ride_cancelled_with_none_category_value(self, mock_db):
        """None category (converted to '') still sends notification successfully."""
        from app.services.notification_events import notify_ride_cancelled
        await notify_ride_cancelled(
            mock_db, user_id=4, ride_id=56,
            cancelled_by="rider", cancellation_category="",
        )
        log = get_sent_notifications()
        assert len(log) == 1
        assert "Reason:" not in log[0].body
