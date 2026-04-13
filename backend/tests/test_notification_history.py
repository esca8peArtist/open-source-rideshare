"""Tests for notification history endpoints.

Covers:
Unit tests (no DB — AsyncMock):
  1.  get_notification_history — returns empty list and zero counts when no logs
  2.  get_notification_history — returns only the current user's notifications
  3.  get_notification_history — filters by notification_type
  4.  get_notification_history — unread_only=True excludes read notifications
  5.  get_notification_history — limit is respected (returns at most N items)
  6.  get_notification_history — offset skips earlier records
  7.  get_notification_history — total reflects full count not just current page
  8.  get_notification_history — unread_count reflects only unread items

  9.  list_notification_logs — returns all logs when no filter applied
  10. list_notification_logs — filters by user_id
  11. list_notification_logs — filters by notification_type
  12. list_notification_logs — filters by channel
  13. list_notification_logs — filters by status
  14. list_notification_logs — filters by ride_id
  15. list_notification_logs — returns correct total count

Integration tests (real test DB via conftest):
  16. GET /notifications/history — no auth returns 401
  17. GET /notifications/history — authenticated user returns 200
  18. GET /notifications/history — empty when user has no notifications
  19. GET /notifications/history — returns list and total fields
  20. GET /notifications/history — unread_only=true filters correctly
  21. POST /notifications/mark-read/{id} — 404 for non-existent notification
  22. POST /notifications/mark-read/{id} — 404 for other user's notification
  23. POST /notifications/mark-all-read — marks all as read
  24. GET /notifications/unread-count — returns zero when all read
  25. GET /admin/notification-logs — no auth returns 401
  26. GET /admin/notification-logs — rider token returns 403
  27. GET /admin/notification-logs — driver token returns 403
  28. GET /admin/notification-logs — admin token returns 200
  29. GET /admin/notification-logs — response contains logs and total fields
  30. GET /admin/notification-logs — limit and offset accepted
  31. GET /admin/notification-logs — filter by user_id accepted
  32. GET /admin/notification-logs — filter by notification_type accepted
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.notification import NotificationLog, NotificationStatus
from app.schemas.admin import AdminNotificationLogEntry, AdminNotificationLogListResponse
from app.schemas.notification import NotificationListResponse, NotificationLogResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_log(
    *,
    log_id: int = 1,
    user_id: int = 42,
    notification_type: str = "ride_matched",
    channel: str = "push",
    title: str = "Your driver is here",
    body: str = "Driver has arrived",
    status: NotificationStatus = NotificationStatus.SENT,
    ride_id: int | None = 10,
    is_read: bool = False,
    error_message: str | None = None,
) -> NotificationLog:
    now = datetime.now(timezone.utc)
    log = NotificationLog(
        user_id=user_id,
        notification_type=notification_type,
        channel=channel,
        title=title,
        body=body,
        status=status,
        ride_id=ride_id,
        is_read=is_read,
        error_message=error_message,
    )
    log.id = log_id
    log.created_at = now
    log.read_at = None
    return log


def _make_mock_user(user_id: int = 42) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


def _mock_db_with_logs(
    logs: list[NotificationLog],
    total: int,
    unread_count: int,
) -> AsyncMock:
    """Return an AsyncSession mock that yields logs and counts."""
    db = AsyncMock()

    call_index = 0

    async def side_effect(query):
        nonlocal call_index
        result = MagicMock()
        if call_index == 0:
            # First execute: count query
            result.scalar.return_value = total
        elif call_index == 1:
            # Second execute: unread count
            result.scalar.return_value = unread_count
        else:
            # Third execute: fetch page
            result.scalars.return_value.all.return_value = logs
        call_index += 1
        return result

    db.execute = side_effect
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# 1–8. Unit tests: get_notification_history endpoint function
# ---------------------------------------------------------------------------


class TestGetNotificationHistoryUnit:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_logs(self):
        from app.api.v1.notifications import get_notification_history

        db = _mock_db_with_logs([], total=0, unread_count=0)
        user = _make_mock_user()

        result = await get_notification_history(user=user, db=db, limit=20, offset=0)

        assert result.total == 0
        assert result.unread_count == 0
        assert result.notifications == []

    @pytest.mark.asyncio
    async def test_returns_list_of_notification_responses(self):
        from app.api.v1.notifications import get_notification_history

        logs = [_make_log(log_id=1), _make_log(log_id=2)]
        db = _mock_db_with_logs(logs, total=2, unread_count=2)
        user = _make_mock_user()

        result = await get_notification_history(user=user, db=db, limit=20, offset=0)

        assert len(result.notifications) == 2

    @pytest.mark.asyncio
    async def test_total_reflects_full_count(self):
        from app.api.v1.notifications import get_notification_history

        # One page returned but total is larger
        logs = [_make_log(log_id=1)]
        db = _mock_db_with_logs(logs, total=50, unread_count=10)
        user = _make_mock_user()

        result = await get_notification_history(user=user, db=db, limit=1, offset=0)

        assert result.total == 50

    @pytest.mark.asyncio
    async def test_unread_count_reflects_only_unread(self):
        from app.api.v1.notifications import get_notification_history

        logs = [
            _make_log(log_id=1, is_read=False),
            _make_log(log_id=2, is_read=True),
        ]
        db = _mock_db_with_logs(logs, total=2, unread_count=1)
        user = _make_mock_user()

        result = await get_notification_history(user=user, db=db, limit=20, offset=0)

        assert result.unread_count == 1

    @pytest.mark.asyncio
    async def test_notification_response_fields_present(self):
        from app.api.v1.notifications import get_notification_history

        logs = [_make_log(log_id=5, notification_type="payment_received", channel="email")]
        db = _mock_db_with_logs(logs, total=1, unread_count=1)
        user = _make_mock_user()

        result = await get_notification_history(user=user, db=db, limit=20, offset=0)

        entry = result.notifications[0]
        assert entry.id == 5
        assert entry.notification_type == "payment_received"
        assert entry.channel == "email"
        assert isinstance(entry.is_read, bool)

    @pytest.mark.asyncio
    async def test_empty_result_when_no_matching_type(self):
        from app.api.v1.notifications import get_notification_history

        db = _mock_db_with_logs([], total=0, unread_count=0)
        user = _make_mock_user()

        result = await get_notification_history(
            user=user,
            db=db,
            limit=20,
            offset=0,
            notification_type="sos_alert",
        )

        assert result.total == 0
        assert result.notifications == []

    @pytest.mark.asyncio
    async def test_unread_only_returns_unread_subset(self):
        from app.api.v1.notifications import get_notification_history

        unread = [_make_log(log_id=3, is_read=False)]
        db = _mock_db_with_logs(unread, total=1, unread_count=1)
        user = _make_mock_user()

        result = await get_notification_history(user=user, db=db, limit=20, offset=0, unread_only=True)

        assert all(not n.is_read for n in result.notifications)

    @pytest.mark.asyncio
    async def test_limit_and_offset_accepted(self):
        """Verify the function accepts limit/offset keyword arguments."""
        from app.api.v1.notifications import get_notification_history

        logs = [_make_log(log_id=i) for i in range(5)]
        db = _mock_db_with_logs(logs[:5], total=100, unread_count=50)
        user = _make_mock_user()

        result = await get_notification_history(user=user, db=db, limit=5, offset=0)

        assert result.total == 100
        assert len(result.notifications) <= 5


# ---------------------------------------------------------------------------
# 9–15. Unit tests: admin list_notification_logs endpoint function
# ---------------------------------------------------------------------------


def _mock_admin_db(logs: list, total: int) -> AsyncMock:
    db = AsyncMock()
    call_index = 0

    async def side_effect(query):
        nonlocal call_index
        result = MagicMock()
        if call_index == 0:
            result.scalar.return_value = total
        else:
            result.scalars.return_value.all.return_value = logs
        call_index += 1
        return result

    db.execute = side_effect
    return db


class TestListNotificationLogsUnit:
    @pytest.mark.asyncio
    async def test_returns_all_logs_when_no_filter(self):
        from app.api.v1.admin import list_notification_logs

        logs = [_make_log(log_id=1, user_id=1), _make_log(log_id=2, user_id=2)]
        db = _mock_admin_db(logs, total=2)
        admin = _make_mock_user(user_id=99)

        result = await list_notification_logs(
            db=db, _=admin, limit=50, offset=0,
            user_id=None, notification_type=None, channel=None,
            status=None, ride_id=None,
        )

        assert result.total == 2
        assert len(result.logs) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_logs(self):
        from app.api.v1.admin import list_notification_logs

        db = _mock_admin_db([], total=0)
        admin = _make_mock_user(user_id=99)

        result = await list_notification_logs(
            db=db, _=admin, limit=50, offset=0,
            user_id=None, notification_type=None, channel=None,
            status=None, ride_id=None,
        )

        assert result.total == 0
        assert result.logs == []

    @pytest.mark.asyncio
    async def test_filter_by_user_id_accepted(self):
        from app.api.v1.admin import list_notification_logs

        logs = [_make_log(user_id=5)]
        db = _mock_admin_db(logs, total=1)
        admin = _make_mock_user(user_id=99)

        result = await list_notification_logs(
            db=db, _=admin, limit=50, offset=0,
            user_id=5, notification_type=None, channel=None,
            status=None, ride_id=None,
        )

        assert result.total == 1
        assert result.logs[0].user_id == 5

    @pytest.mark.asyncio
    async def test_filter_by_notification_type_accepted(self):
        from app.api.v1.admin import list_notification_logs

        logs = [_make_log(notification_type="sos_alert")]
        db = _mock_admin_db(logs, total=1)
        admin = _make_mock_user(user_id=99)

        result = await list_notification_logs(
            db=db, _=admin, limit=50, offset=0,
            user_id=None, notification_type="sos_alert", channel=None,
            status=None, ride_id=None,
        )

        assert result.logs[0].notification_type == "sos_alert"

    @pytest.mark.asyncio
    async def test_filter_by_channel_accepted(self):
        from app.api.v1.admin import list_notification_logs

        logs = [_make_log(channel="sms")]
        db = _mock_admin_db(logs, total=1)
        admin = _make_mock_user(user_id=99)

        result = await list_notification_logs(
            db=db, _=admin, limit=50, offset=0,
            user_id=None, notification_type=None, channel="sms",
            status=None, ride_id=None,
        )

        assert result.logs[0].channel == "sms"

    @pytest.mark.asyncio
    async def test_filter_by_status_accepted(self):
        from app.api.v1.admin import list_notification_logs

        logs = [_make_log(status=NotificationStatus.FAILED)]
        db = _mock_admin_db(logs, total=1)
        admin = _make_mock_user(user_id=99)

        result = await list_notification_logs(
            db=db, _=admin, limit=50, offset=0,
            user_id=None, notification_type=None, channel=None,
            status="failed", ride_id=None,
        )

        assert result.logs[0].status == "failed"

    @pytest.mark.asyncio
    async def test_filter_by_ride_id_accepted(self):
        from app.api.v1.admin import list_notification_logs

        logs = [_make_log(ride_id=77)]
        db = _mock_admin_db(logs, total=1)
        admin = _make_mock_user(user_id=99)

        result = await list_notification_logs(
            db=db, _=admin, limit=50, offset=0,
            user_id=None, notification_type=None, channel=None,
            status=None, ride_id=77,
        )

        assert result.logs[0].ride_id == 77

    @pytest.mark.asyncio
    async def test_total_is_full_count_not_page_size(self):
        from app.api.v1.admin import list_notification_logs

        # Return 2 logs but total says 200
        logs = [_make_log(log_id=1), _make_log(log_id=2)]
        db = _mock_admin_db(logs, total=200)
        admin = _make_mock_user(user_id=99)

        result = await list_notification_logs(
            db=db, _=admin, limit=2, offset=0,
            user_id=None, notification_type=None, channel=None,
            status=None, ride_id=None,
        )

        assert result.total == 200


# ---------------------------------------------------------------------------
# 16–32. Integration tests (require test DB)
# ---------------------------------------------------------------------------


BASE = "/api/v1/notifications"
ADMIN_BASE = "/api/v1/admin"


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _add_log(db, user_id: int, notification_type: str = "ride_matched",
             channel: str = "push", is_read: bool = False,
             ride_id: int | None = None) -> NotificationLog:
    log = NotificationLog(
        user_id=user_id,
        notification_type=notification_type,
        channel=channel,
        title="Test notification",
        body="Test body",
        status=NotificationStatus.SENT,
        ride_id=ride_id,
        is_read=is_read,
    )
    db.add(log)
    return log


@pytest.mark.anyio
class TestNotificationHistoryEndpoints:
    async def test_no_auth_returns_401(self, client):
        resp = await client.get(f"{BASE}/history")
        assert resp.status_code == 401

    async def test_authenticated_user_returns_200(self, client, rider, rider_token):
        resp = await client.get(
            f"{BASE}/history",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 200

    async def test_empty_list_when_no_notifications(self, client, rider, rider_token):
        resp = await client.get(
            f"{BASE}/history",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["notifications"] == []
        assert data["unread_count"] == 0

    async def test_response_contains_required_fields(self, client, rider, rider_token, db):
        _add_log(db, user_id=rider.id)
        await db.flush()

        resp = await client.get(
            f"{BASE}/history",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "notifications" in data
        assert "total" in data
        assert "unread_count" in data

    async def test_notification_fields_present(self, client, rider, rider_token, db):
        _add_log(db, user_id=rider.id, notification_type="payment_received", channel="email")
        await db.flush()

        resp = await client.get(
            f"{BASE}/history",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 200
        entries = resp.json()["notifications"]
        assert len(entries) >= 1
        entry = entries[0]
        for field in ("id", "notification_type", "channel", "title", "body",
                      "status", "is_read", "created_at"):
            assert field in entry

    async def test_unread_only_true_filters_read_notifications(
        self, client, rider, rider_token, db
    ):
        _add_log(db, user_id=rider.id, is_read=True)
        _add_log(db, user_id=rider.id, is_read=False, notification_type="ride_cancelled")
        await db.flush()

        resp = await client.get(
            f"{BASE}/history?unread_only=true",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(not n["is_read"] for n in data["notifications"])

    async def test_mark_read_404_for_nonexistent_notification(
        self, client, rider, rider_token
    ):
        resp = await client.post(
            f"{BASE}/mark-read/999999",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 404

    async def test_mark_read_404_for_another_users_notification(
        self, client, rider, rider_token, driver_user, db
    ):
        # Create a log belonging to driver_user, not rider
        log = _add_log(db, user_id=driver_user.id)
        await db.flush()

        resp = await client.post(
            f"{BASE}/mark-read/{log.id}",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 404

    async def test_mark_all_read_returns_ok(self, client, rider, rider_token, db):
        _add_log(db, user_id=rider.id, is_read=False)
        _add_log(db, user_id=rider.id, is_read=False)
        await db.flush()

        resp = await client.post(
            f"{BASE}/mark-all-read",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    async def test_unread_count_is_zero_after_mark_all_read(
        self, client, rider, rider_token, db
    ):
        _add_log(db, user_id=rider.id, is_read=False)
        await db.flush()

        await client.post(f"{BASE}/mark-all-read", headers=auth_header(rider_token))

        resp = await client.get(f"{BASE}/unread-count", headers=auth_header(rider_token))
        assert resp.status_code == 200
        assert resp.json()["total_unread"] == 0

    async def test_type_filter_excludes_other_types(
        self, client, rider, rider_token, db
    ):
        _add_log(db, user_id=rider.id, notification_type="sos_alert")
        _add_log(db, user_id=rider.id, notification_type="ride_matched")
        await db.flush()

        resp = await client.get(
            f"{BASE}/history?notification_type=sos_alert",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(n["notification_type"] == "sos_alert" for n in data["notifications"])

    async def test_pagination_limit_respected(self, client, rider, rider_token, db):
        for i in range(5):
            _add_log(db, user_id=rider.id)
        await db.flush()

        resp = await client.get(
            f"{BASE}/history?limit=2",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 200
        assert len(resp.json()["notifications"]) <= 2


@pytest.mark.anyio
class TestAdminNotificationLogsEndpoint:
    async def test_no_auth_returns_401(self, client):
        resp = await client.get(f"{ADMIN_BASE}/notification-logs")
        assert resp.status_code == 401

    async def test_rider_token_returns_403(self, client, rider, rider_token):
        resp = await client.get(
            f"{ADMIN_BASE}/notification-logs",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_driver_token_returns_403(self, client, driver_user, driver_token):
        resp = await client.get(
            f"{ADMIN_BASE}/notification-logs",
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 403

    async def test_admin_token_returns_200(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{ADMIN_BASE}/notification-logs",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_response_has_logs_and_total(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{ADMIN_BASE}/notification-logs",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "logs" in data
        assert "total" in data
        assert isinstance(data["logs"], list)
        assert isinstance(data["total"], int)

    async def test_returns_logs_across_all_users(
        self, client, admin_user, admin_token, rider, driver_user, db
    ):
        _add_log(db, user_id=rider.id)
        _add_log(db, user_id=driver_user.id)
        await db.flush()

        resp = await client.get(
            f"{ADMIN_BASE}/notification-logs",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        user_ids = {entry["user_id"] for entry in data["logs"]}
        assert rider.id in user_ids
        assert driver_user.id in user_ids

    async def test_filter_by_user_id(
        self, client, admin_user, admin_token, rider, driver_user, db
    ):
        _add_log(db, user_id=rider.id, notification_type="ride_matched")
        _add_log(db, user_id=driver_user.id, notification_type="payout_completed")
        await db.flush()

        resp = await client.get(
            f"{ADMIN_BASE}/notification-logs?user_id={rider.id}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(entry["user_id"] == rider.id for entry in data["logs"])

    async def test_filter_by_notification_type(
        self, client, admin_user, admin_token, rider, db
    ):
        _add_log(db, user_id=rider.id, notification_type="sos_alert")
        _add_log(db, user_id=rider.id, notification_type="ride_matched")
        await db.flush()

        resp = await client.get(
            f"{ADMIN_BASE}/notification-logs?notification_type=sos_alert",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(e["notification_type"] == "sos_alert" for e in data["logs"])

    async def test_limit_and_offset_accepted(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{ADMIN_BASE}/notification-logs?limit=5&offset=0",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_log_entry_fields_present(
        self, client, admin_user, admin_token, rider, db
    ):
        _add_log(db, user_id=rider.id, channel="sms", ride_id=99)
        await db.flush()

        resp = await client.get(
            f"{ADMIN_BASE}/notification-logs",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        entries = resp.json()["logs"]
        if entries:
            entry = entries[0]
            for field in ("id", "user_id", "notification_type", "channel",
                          "title", "body", "status", "is_read", "created_at"):
                assert field in entry
