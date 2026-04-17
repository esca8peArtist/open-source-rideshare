"""Unit tests for the driver accountability escalation system.

Covers:

DriverEscalation model:
  1. Model has the expected fields
  2. RESET_WINDOW_DAYS is 28

NotificationType:
  3. DRIVER_PERFORMANCE_WARNING exists and has correct value
  4. DRIVER_PERFORMANCE_FINAL_WARNING exists and has correct value
  5. DRIVER_AUTO_SUSPENDED exists and has correct value

notification_templates:
  6. driver_performance_warning returns push+SMS
  7. driver_performance_warning body mentions the alert label
  8. driver_performance_final_warning title contains "final"
  9. driver_performance_final_warning body warns of suspension
  10. driver_auto_suspended title contains "suspended"
  11. driver_auto_suspended body mentions support/appeal
  12. Unknown alert_type falls back to generic label

ESCALATION_TRIGGER_TYPES:
  13. high_no_show is a trigger type
  14. low_score is a trigger type
  15. high_cancellation is a trigger type
  16. low_rating is NOT a trigger type

check_and_escalate — not a trigger type:
  17. Returns None for non-trigger alert_type

check_and_escalate — 1st offence:
  18. Sets warning_count = 1
  19. Sets escalation_level = "warning"
  20. Returns action = "warning"
  21. Commits and calls notification

check_and_escalate — 2nd offence:
  22. Sets warning_count = 2
  23. Sets escalation_level = "final_warning"
  24. Returns action = "final_warning"

check_and_escalate — 3rd offence (auto-suspend):
  25. Sets warning_count = 3
  26. Sets escalation_level = "suspended"
  27. Sets auto_suspended_at to now
  28. Returns action = "auto_suspended"

check_and_escalate — streak reset after RESET_WINDOW_DAYS:
  29. warning_count resets to 1 (not 2) when last_warning_at > 28 days ago
  30. Escalation level is "warning" (not "final_warning") after reset

check_and_escalate — within reset window:
  31. warning_count increments normally within RESET_WINDOW_DAYS

get_escalation_status:
  32. Returns None when no record exists
  33. Returns record when it exists

reset_escalation:
  34. Clears warning_count to 0
  35. Clears escalation_level to "none"
  36. Sets reset_by and last_reset_at
  37. Stores admin note

check_and_create_alerts — escalation is triggered for high_no_show:
  38. check_and_escalate is called when high_no_show alert is created
  39. check_and_escalate is NOT called when low_rating alert is created

API schema:
  40. DriverEscalationStatusResponse serialises a clean driver correctly
  41. AdminResetEscalationResponse contains expected fields

notification_events dispatchers:
  42. notify_driver_performance_warning swallows exceptions
  43. notify_driver_performance_final_warning swallows exceptions
  44. notify_driver_auto_suspended swallows exceptions
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_escalation import RESET_WINDOW_DAYS, DriverEscalation
from app.services.driver_escalation import (
    ESCALATION_TRIGGER_TYPES,
    check_and_escalate,
    get_escalation_status,
    reset_escalation,
)
from app.services.notifications import NotificationType
from app.services.notification_templates import (
    driver_auto_suspended as _tpl_suspended,
    driver_performance_final_warning as _tpl_final,
    driver_performance_warning as _tpl_warning,
)
from app.services.notifications import NotificationChannel

NOW = datetime(2026, 4, 18, 10, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_escalation(
    *,
    driver_id: int = 99,
    warning_count: int = 0,
    escalation_level: str = "none",
    last_warning_at: datetime | None = None,
    auto_suspended_at: datetime | None = None,
) -> MagicMock:
    rec = MagicMock(spec=DriverEscalation)
    rec.driver_id = driver_id
    rec.warning_count = warning_count
    rec.escalation_level = escalation_level
    rec.last_warning_at = last_warning_at
    rec.auto_suspended_at = auto_suspended_at
    rec.last_trigger_type = None
    rec.admin_reset_note = None
    rec.reset_by = None
    rec.last_reset_at = None
    return rec


def _mock_db_no_record() -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    return db


def _mock_db_with_record(record: MagicMock) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = record
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# 1–2: Model attributes
# ---------------------------------------------------------------------------


def test_driver_escalation_model_has_warning_count():  # 1
    assert hasattr(DriverEscalation, "warning_count")


def test_reset_window_days():  # 2
    assert RESET_WINDOW_DAYS == 28


# ---------------------------------------------------------------------------
# 3–5: NotificationType values
# ---------------------------------------------------------------------------


def test_notification_type_performance_warning_exists():  # 3
    assert NotificationType.DRIVER_PERFORMANCE_WARNING.value == "driver_performance_warning"


def test_notification_type_performance_final_warning_exists():  # 4
    assert NotificationType.DRIVER_PERFORMANCE_FINAL_WARNING.value == "driver_performance_final_warning"


def test_notification_type_auto_suspended_exists():  # 5
    assert NotificationType.DRIVER_AUTO_SUSPENDED.value == "driver_auto_suspended"


# ---------------------------------------------------------------------------
# 6–12: Notification templates
# ---------------------------------------------------------------------------


def test_warning_template_channels():  # 6
    _, _, channels = _tpl_warning()
    assert NotificationChannel.PUSH in channels
    assert NotificationChannel.SMS in channels


def test_warning_template_body_mentions_label():  # 7
    _, body, _ = _tpl_warning(alert_type="high_no_show")
    assert "no-show" in body.lower()


def test_final_warning_template_title():  # 8
    title, _, _ = _tpl_final()
    assert "final" in title.lower()


def test_final_warning_template_body_warns_suspension():  # 9
    _, body, _ = _tpl_final(alert_type="high_cancellation")
    assert "suspension" in body.lower()


def test_auto_suspended_template_title():  # 10
    title, _, _ = _tpl_suspended()
    assert "suspend" in title.lower()


def test_auto_suspended_template_body_mentions_support():  # 11
    _, body, _ = _tpl_suspended()
    assert "support" in body.lower() or "appeal" in body.lower()


def test_warning_template_unknown_alert_type_fallback():  # 12
    _, body, _ = _tpl_warning(alert_type="some_unknown_type")
    assert "performance issue" in body


# ---------------------------------------------------------------------------
# 13–16: ESCALATION_TRIGGER_TYPES
# ---------------------------------------------------------------------------


def test_trigger_type_high_no_show():  # 13
    assert "high_no_show" in ESCALATION_TRIGGER_TYPES


def test_trigger_type_low_score():  # 14
    assert "low_score" in ESCALATION_TRIGGER_TYPES


def test_trigger_type_high_cancellation():  # 15
    assert "high_cancellation" in ESCALATION_TRIGGER_TYPES


def test_trigger_type_low_rating_not_included():  # 16
    assert "low_rating" not in ESCALATION_TRIGGER_TYPES


# ---------------------------------------------------------------------------
# 17: Non-trigger type returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_and_escalate_non_trigger_returns_none():  # 17
    db = _mock_db_no_record()
    result = await check_and_escalate(1, "low_rating", db, now=NOW)
    assert result is None


# ---------------------------------------------------------------------------
# 18–21: 1st offence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_offence_warning_count():  # 18
    rec = _make_escalation()
    db = _mock_db_with_record(rec)
    with patch(
        "app.services.driver_escalation._notify_driver", new_callable=AsyncMock
    ):
        result = await check_and_escalate(99, "high_no_show", db, now=NOW)
    assert rec.warning_count == 1


@pytest.mark.asyncio
async def test_first_offence_escalation_level():  # 19
    rec = _make_escalation()
    db = _mock_db_with_record(rec)
    with patch(
        "app.services.driver_escalation._notify_driver", new_callable=AsyncMock
    ):
        await check_and_escalate(99, "high_no_show", db, now=NOW)
    assert rec.escalation_level == "warning"


@pytest.mark.asyncio
async def test_first_offence_action():  # 20
    rec = _make_escalation()
    db = _mock_db_with_record(rec)
    with patch(
        "app.services.driver_escalation._notify_driver", new_callable=AsyncMock
    ):
        result = await check_and_escalate(99, "high_no_show", db, now=NOW)
    assert result["action"] == "warning"


@pytest.mark.asyncio
async def test_first_offence_notifies_driver():  # 21
    rec = _make_escalation()
    db = _mock_db_with_record(rec)
    with patch(
        "app.services.driver_escalation._notify_driver", new_callable=AsyncMock
    ) as mock_notify:
        await check_and_escalate(99, "high_no_show", db, now=NOW)
    mock_notify.assert_awaited_once()


# ---------------------------------------------------------------------------
# 22–24: 2nd offence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_offence_warning_count():  # 22
    rec = _make_escalation(warning_count=1, last_warning_at=NOW - timedelta(days=3))
    db = _mock_db_with_record(rec)
    with patch(
        "app.services.driver_escalation._notify_driver", new_callable=AsyncMock
    ):
        await check_and_escalate(99, "high_no_show", db, now=NOW)
    assert rec.warning_count == 2


@pytest.mark.asyncio
async def test_second_offence_escalation_level():  # 23
    rec = _make_escalation(warning_count=1, last_warning_at=NOW - timedelta(days=3))
    db = _mock_db_with_record(rec)
    with patch(
        "app.services.driver_escalation._notify_driver", new_callable=AsyncMock
    ):
        await check_and_escalate(99, "high_no_show", db, now=NOW)
    assert rec.escalation_level == "final_warning"


@pytest.mark.asyncio
async def test_second_offence_action():  # 24
    rec = _make_escalation(warning_count=1, last_warning_at=NOW - timedelta(days=3))
    db = _mock_db_with_record(rec)
    with patch(
        "app.services.driver_escalation._notify_driver", new_callable=AsyncMock
    ):
        result = await check_and_escalate(99, "high_no_show", db, now=NOW)
    assert result["action"] == "final_warning"


# ---------------------------------------------------------------------------
# 25–28: 3rd offence (auto-suspend)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_third_offence_warning_count():  # 25
    rec = _make_escalation(warning_count=2, last_warning_at=NOW - timedelta(days=5))
    db = _mock_db_with_record(rec)
    with patch(
        "app.services.driver_escalation._auto_suspend", new_callable=AsyncMock
    ), patch(
        "app.services.driver_escalation._notify_driver", new_callable=AsyncMock
    ):
        await check_and_escalate(99, "low_score", db, now=NOW)
    assert rec.warning_count == 3


@pytest.mark.asyncio
async def test_third_offence_escalation_level():  # 26
    rec = _make_escalation(warning_count=2, last_warning_at=NOW - timedelta(days=5))
    db = _mock_db_with_record(rec)
    with patch(
        "app.services.driver_escalation._auto_suspend", new_callable=AsyncMock
    ), patch(
        "app.services.driver_escalation._notify_driver", new_callable=AsyncMock
    ):
        await check_and_escalate(99, "low_score", db, now=NOW)
    assert rec.escalation_level == "suspended"


@pytest.mark.asyncio
async def test_third_offence_auto_suspended_at():  # 27
    rec = _make_escalation(warning_count=2, last_warning_at=NOW - timedelta(days=5))
    db = _mock_db_with_record(rec)
    with patch(
        "app.services.driver_escalation._auto_suspend", new_callable=AsyncMock
    ), patch(
        "app.services.driver_escalation._notify_driver", new_callable=AsyncMock
    ):
        await check_and_escalate(99, "low_score", db, now=NOW)
    assert rec.auto_suspended_at == NOW


@pytest.mark.asyncio
async def test_third_offence_action():  # 28
    rec = _make_escalation(warning_count=2, last_warning_at=NOW - timedelta(days=5))
    db = _mock_db_with_record(rec)
    with patch(
        "app.services.driver_escalation._auto_suspend", new_callable=AsyncMock
    ), patch(
        "app.services.driver_escalation._notify_driver", new_callable=AsyncMock
    ):
        result = await check_and_escalate(99, "low_score", db, now=NOW)
    assert result["action"] == "auto_suspended"


# ---------------------------------------------------------------------------
# 29–30: Streak reset after RESET_WINDOW_DAYS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streak_reset_warning_count_resets_to_one():  # 29
    # last_warning_at is 29 days ago — exceeds RESET_WINDOW_DAYS (28)
    old_warning = NOW - timedelta(days=29)
    rec = _make_escalation(warning_count=2, last_warning_at=old_warning)
    db = _mock_db_with_record(rec)
    with patch(
        "app.services.driver_escalation._notify_driver", new_callable=AsyncMock
    ):
        await check_and_escalate(99, "high_no_show", db, now=NOW)
    assert rec.warning_count == 1


@pytest.mark.asyncio
async def test_streak_reset_escalation_level_is_warning():  # 30
    old_warning = NOW - timedelta(days=29)
    rec = _make_escalation(warning_count=2, last_warning_at=old_warning)
    db = _mock_db_with_record(rec)
    with patch(
        "app.services.driver_escalation._notify_driver", new_callable=AsyncMock
    ):
        await check_and_escalate(99, "high_no_show", db, now=NOW)
    assert rec.escalation_level == "warning"


# ---------------------------------------------------------------------------
# 31: Within reset window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_within_reset_window_count_increments():  # 31
    recent_warning = NOW - timedelta(days=27)  # within 28-day window
    rec = _make_escalation(warning_count=1, last_warning_at=recent_warning)
    db = _mock_db_with_record(rec)
    with patch(
        "app.services.driver_escalation._notify_driver", new_callable=AsyncMock
    ):
        await check_and_escalate(99, "high_no_show", db, now=NOW)
    assert rec.warning_count == 2


# ---------------------------------------------------------------------------
# 32–33: get_escalation_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_escalation_status_none_when_no_record():  # 32
    db = _mock_db_no_record()
    result = await get_escalation_status(db, driver_id=42)
    assert result is None


@pytest.mark.asyncio
async def test_get_escalation_status_returns_record():  # 33
    rec = _make_escalation(driver_id=42, warning_count=1, escalation_level="warning")
    db = _mock_db_with_record(rec)
    result = await get_escalation_status(db, driver_id=42)
    assert result is rec


# ---------------------------------------------------------------------------
# 34–37: reset_escalation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_escalation_clears_warning_count():  # 34
    rec = _make_escalation(warning_count=2, escalation_level="final_warning")
    db = _mock_db_with_record(rec)
    await reset_escalation(db, driver_id=99, admin_id=1, now=NOW)
    assert rec.warning_count == 0


@pytest.mark.asyncio
async def test_reset_escalation_clears_level():  # 35
    rec = _make_escalation(warning_count=2, escalation_level="final_warning")
    db = _mock_db_with_record(rec)
    await reset_escalation(db, driver_id=99, admin_id=1, now=NOW)
    assert rec.escalation_level == "none"


@pytest.mark.asyncio
async def test_reset_escalation_sets_reset_by_and_timestamp():  # 36
    rec = _make_escalation()
    db = _mock_db_with_record(rec)
    await reset_escalation(db, driver_id=99, admin_id=77, now=NOW)
    assert rec.reset_by == 77
    assert rec.last_reset_at == NOW


@pytest.mark.asyncio
async def test_reset_escalation_stores_note():  # 37
    rec = _make_escalation()
    db = _mock_db_with_record(rec)
    await reset_escalation(db, driver_id=99, admin_id=1, note="Coaching completed", now=NOW)
    assert rec.admin_reset_note == "Coaching completed"


# ---------------------------------------------------------------------------
# 38–39: Integration with check_and_create_alerts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_and_create_alerts_triggers_escalation_for_high_no_show():  # 38
    """high_no_show alert created → check_and_escalate is called."""
    from app.models.driver_performance import DriverPerformanceSnapshot
    from app.services.driver_performance import check_and_create_alerts

    snapshot = MagicMock(spec=DriverPerformanceSnapshot)
    snapshot.id = 1
    snapshot.driver_id = 99
    snapshot.acceptance_rate = 0.90
    snapshot.cancellation_rate = 0.05
    snapshot.no_show_rate = 0.15  # above 10 % threshold → high_no_show alert
    snapshot.total_rider_ratings = 0
    snapshot.average_rider_rating = 0.0
    snapshot.performance_score = 75.0

    # Mock DB: no existing alerts
    db = AsyncMock()
    existing_result = MagicMock()
    existing_result.all.return_value = []
    db.execute.return_value = existing_result

    with patch(
        "app.services.driver_escalation.check_and_escalate", new_callable=AsyncMock
    ) as mock_escalate:
        await check_and_create_alerts(db, snapshot)

    # Should have been called at least once with "high_no_show"
    calls = [c.args[1] for c in mock_escalate.await_args_list]
    assert "high_no_show" in calls


@pytest.mark.asyncio
async def test_check_and_create_alerts_does_not_trigger_for_low_rating():  # 39
    """low_rating alert → check_and_escalate NOT called."""
    from app.models.driver_performance import DriverPerformanceSnapshot
    from app.services.driver_performance import check_and_create_alerts

    snapshot = MagicMock(spec=DriverPerformanceSnapshot)
    snapshot.id = 1
    snapshot.driver_id = 99
    snapshot.acceptance_rate = 0.90
    snapshot.cancellation_rate = 0.05
    snapshot.no_show_rate = 0.0  # no high_no_show
    snapshot.total_rider_ratings = 5
    snapshot.average_rider_rating = 2.5  # below 3.5 → low_rating alert
    snapshot.performance_score = 72.0  # above 60 → no low_score

    db = AsyncMock()
    existing_result = MagicMock()
    existing_result.all.return_value = []
    db.execute.return_value = existing_result

    with patch(
        "app.services.driver_escalation.check_and_escalate", new_callable=AsyncMock
    ) as mock_escalate:
        await check_and_create_alerts(db, snapshot)

    # escalation should NOT have been called for low_rating
    calls = [c.args[1] for c in mock_escalate.await_args_list]
    assert "low_rating" not in calls


# ---------------------------------------------------------------------------
# 40–41: Schema serialisation
# ---------------------------------------------------------------------------


def test_escalation_status_schema_clean_driver():  # 40
    from app.schemas.driver_escalation import DriverEscalationStatusResponse

    schema = DriverEscalationStatusResponse(
        driver_id=5,
        escalation_level="none",
        warning_count=0,
        last_trigger_type=None,
        last_warning_at=None,
        auto_suspended_at=None,
        last_reset_at=None,
    )
    assert schema.driver_id == 5
    assert schema.escalation_level == "none"
    assert schema.warning_count == 0


def test_reset_escalation_response_schema():  # 41
    from app.schemas.driver_escalation import AdminResetEscalationResponse

    resp = AdminResetEscalationResponse(
        driver_id=10,
        escalation_level="none",
        warning_count=0,
        last_reset_at=NOW,
        admin_reset_note="Coaching done",
        message="Escalation reset successfully. Driver warnings cleared.",
    )
    assert resp.driver_id == 10
    assert "cleared" in resp.message


# ---------------------------------------------------------------------------
# 42–44: Notification dispatcher exception swallowing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_driver_performance_warning_swallows_exception():  # 42
    from app.services.notification_events import notify_driver_performance_warning

    db = AsyncMock()
    with patch(
        "app.services.notification_events._send_driver_escalation_notification",
        side_effect=RuntimeError("boom"),
    ):
        # Should not raise
        await notify_driver_performance_warning(db, driver_id=1, alert_type="high_no_show", warning_count=1)


@pytest.mark.asyncio
async def test_notify_driver_performance_final_warning_swallows_exception():  # 43
    from app.services.notification_events import notify_driver_performance_final_warning

    db = AsyncMock()
    with patch(
        "app.services.notification_events._send_driver_escalation_notification",
        side_effect=RuntimeError("boom"),
    ):
        await notify_driver_performance_final_warning(db, driver_id=1, alert_type="low_score", warning_count=2)


@pytest.mark.asyncio
async def test_notify_driver_auto_suspended_swallows_exception():  # 44
    from app.services.notification_events import notify_driver_auto_suspended

    db = AsyncMock()
    with patch(
        "app.services.notification_events._send_driver_escalation_notification",
        side_effect=RuntimeError("boom"),
    ):
        await notify_driver_auto_suspended(db, driver_id=1, alert_type="high_no_show", warning_count=3)
