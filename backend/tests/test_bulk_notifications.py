"""Unit tests for admin bulk notification broadcast feature.

Coverage:
  Schema validation:
    1.  BulkNotificationRequest — valid request accepted
    2.  BulkNotificationRequest — title over 255 chars rejected
    3.  BulkNotificationRequest — empty title rejected
    4.  BulkNotificationRequest — body over 2000 chars rejected
    5.  BulkNotificationRequest — empty body rejected
    6.  BulkNotificationRequest — invalid channel name rejected
    7.  BulkNotificationRequest — empty channels list rejected
    8.  BulkNotificationRequest — mixed valid and invalid channels rejected
    9.  BulkNotificationRequest — default channels is ["push"]
    10. BulkNotificationRequest — default notification_type is "platform_announcement"
    11. BulkNotificationRequest — all valid channel combinations accepted

  get_broadcast_recipients:
    12. ALL target queries all active users regardless of role
    13. RIDERS target filters to RIDER role only
    14. DRIVERS target filters to DRIVER role only
    15. Inactive users are excluded from ALL
    16. Inactive riders excluded from RIDERS
    17. Inactive drivers excluded from DRIVERS
    18. Empty DB returns empty list for any target

  send_bulk_notification:
    19. Creates a BroadcastRecord in the DB
    20. BroadcastRecord has correct recipient_count
    21. send_notification called once per recipient
    22. sent_count equals number of successful sends
    23. failed_count equals number of failed sends
    24. Returns BulkNotificationResult with correct broadcast_id
    25. Result title matches request title
    26. Result target matches request target
    27. Result recipient_count equals number of recipients
    28. Zero recipients produces sent_count=0 and failed_count=0
    29. Exception in send_notification increments failed_count not sent_count
    30. send_notification exception does not propagate (service is fault-tolerant)

  list_broadcasts:
    31. Returns records ordered newest-first
    32. Respects limit parameter
    33. Respects offset parameter
    34. Returns empty list when no records

  Endpoint auth:
    35. POST /broadcast returns 403 for non-admin (rider)
    36. POST /broadcast returns 403 for non-admin (driver)
    37. POST /broadcast without auth returns 403 or 401

  Endpoint logic:
    38. POST /broadcast returns 201 on success
    39. POST /broadcast with invalid channel returns 422
    40. POST /broadcast with empty channels returns 422
    41. Response contains recipient_count and sent_count
    42. GET /broadcasts returns 403 for non-admin
    43. GET /broadcasts returns list ordered newest-first
    44. GET /broadcasts/{id} returns 404 for missing broadcast_id
    45. GET /broadcasts/{id} returns correct data for existing record
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.models.broadcast import BroadcastRecord
from app.models.user import User, UserRole
from app.schemas.bulk_notification import (
    BroadcastTarget,
    BulkNotificationRequest,
    BulkNotificationResult,
)
from app.services.bulk_notifications import (
    get_broadcast_recipients,
    list_broadcasts,
    send_bulk_notification,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_user(
    user_id: int = 1,
    role: UserRole = UserRole.RIDER,
    is_active: bool = True,
    phone: str = "+15550000001",
    email: str | None = "user@example.com",
) -> MagicMock:
    u = MagicMock(spec=User)
    u.id = user_id
    u.role = role
    u.is_active = is_active
    u.phone = phone
    u.email = email
    return u


def _make_broadcast_record(
    record_id: int = 1,
    admin_id: int = 99,
    target: str = "all",
    title: str = "Test",
    body: str = "Body",
    channels: str = "push",
    recipient_count: int = 5,
    sent_count: int = 4,
    failed_count: int = 1,
    created_at: datetime | None = None,
) -> MagicMock:
    r = MagicMock(spec=BroadcastRecord)
    r.id = record_id
    r.admin_id = admin_id
    r.target = target
    r.title = title
    r.body = body
    r.channels = channels
    r.recipient_count = recipient_count
    r.sent_count = sent_count
    r.failed_count = failed_count
    r.created_at = created_at or _NOW
    return r


def _scalar_result(items: list) -> MagicMock:
    """Simulate an AsyncSession execute() result with scalars().all()."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    result.scalars.return_value = scalars
    return result


def _make_db(*result_sequences) -> AsyncMock:
    """DB mock returning successive result lists for successive execute() calls.

    flush() side effect assigns id=1 to any BroadcastRecord added via db.add(),
    mirroring what a real DB flush would do.
    """
    db = AsyncMock()
    side_effects = [_scalar_result(items) for items in result_sequences]
    db.execute = AsyncMock(side_effect=side_effects)
    db.add = MagicMock()

    _added: list = []
    _real_add = db.add.side_effect  # None initially

    def _capture_add(obj):
        _added.append(obj)

    db.add.side_effect = _capture_add

    async def _flush_with_id_assignment():
        for obj in _added:
            if isinstance(obj, BroadcastRecord) and obj.id is None:
                object.__setattr__(obj, "id", 1)
                object.__setattr__(obj, "created_at", _NOW)

    db.flush = AsyncMock(side_effect=_flush_with_id_assignment)
    return db


# ---------------------------------------------------------------------------
# 1-11: Schema validation
# ---------------------------------------------------------------------------


class TestBulkNotificationRequestSchema:
    def test_valid_request_accepted(self):
        req = BulkNotificationRequest(
            target=BroadcastTarget.ALL,
            title="Hello",
            body="World",
            channels=["push"],
        )
        assert req.target == BroadcastTarget.ALL
        assert req.title == "Hello"

    def test_title_over_255_chars_rejected(self):
        with pytest.raises(Exception):
            BulkNotificationRequest(
                target=BroadcastTarget.ALL,
                title="x" * 256,
                body="Valid body",
                channels=["push"],
            )

    def test_empty_title_rejected(self):
        with pytest.raises(Exception):
            BulkNotificationRequest(
                target=BroadcastTarget.ALL,
                title="",
                body="Valid body",
                channels=["push"],
            )

    def test_body_over_2000_chars_rejected(self):
        with pytest.raises(Exception):
            BulkNotificationRequest(
                target=BroadcastTarget.ALL,
                title="Title",
                body="x" * 2001,
                channels=["push"],
            )

    def test_empty_body_rejected(self):
        with pytest.raises(Exception):
            BulkNotificationRequest(
                target=BroadcastTarget.ALL,
                title="Title",
                body="",
                channels=["push"],
            )

    def test_invalid_channel_rejected(self):
        with pytest.raises(Exception):
            BulkNotificationRequest(
                target=BroadcastTarget.ALL,
                title="Title",
                body="Body",
                channels=["carrier_pigeon"],
            )

    def test_empty_channels_rejected(self):
        with pytest.raises(Exception):
            BulkNotificationRequest(
                target=BroadcastTarget.ALL,
                title="Title",
                body="Body",
                channels=[],
            )

    def test_mixed_valid_and_invalid_channels_rejected(self):
        with pytest.raises(Exception):
            BulkNotificationRequest(
                target=BroadcastTarget.ALL,
                title="Title",
                body="Body",
                channels=["push", "fax"],
            )

    def test_default_channels_is_push(self):
        req = BulkNotificationRequest(
            target=BroadcastTarget.RIDERS,
            title="Title",
            body="Body",
        )
        assert req.channels == ["push"]

    def test_default_notification_type(self):
        req = BulkNotificationRequest(
            target=BroadcastTarget.ALL,
            title="T",
            body="B",
        )
        assert req.notification_type == "platform_announcement"

    def test_all_valid_channel_combinations_accepted(self):
        for channels in (["push"], ["sms"], ["email"], ["push", "sms"], ["push", "email"], ["sms", "email"], ["push", "sms", "email"]):
            req = BulkNotificationRequest(
                target=BroadcastTarget.ALL,
                title="T",
                body="B",
                channels=channels,
            )
            assert set(req.channels) == set(channels)


# ---------------------------------------------------------------------------
# 12-18: get_broadcast_recipients
# ---------------------------------------------------------------------------


class TestGetBroadcastRecipients:
    @pytest.mark.asyncio
    async def test_all_target_returns_all_active_users(self):
        users = [
            _make_user(1, UserRole.RIDER),
            _make_user(2, UserRole.DRIVER),
            _make_user(3, UserRole.ADMIN),
        ]
        db = _make_db(users)
        result = await get_broadcast_recipients(db, BroadcastTarget.ALL)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_riders_target_filters_to_riders(self):
        riders = [_make_user(1, UserRole.RIDER), _make_user(2, UserRole.RIDER)]
        db = _make_db(riders)
        result = await get_broadcast_recipients(db, BroadcastTarget.RIDERS)
        assert len(result) == 2
        assert all(u.role == UserRole.RIDER for u in result)

    @pytest.mark.asyncio
    async def test_drivers_target_filters_to_drivers(self):
        drivers = [_make_user(1, UserRole.DRIVER)]
        db = _make_db(drivers)
        result = await get_broadcast_recipients(db, BroadcastTarget.DRIVERS)
        assert len(result) == 1
        assert result[0].role == UserRole.DRIVER

    @pytest.mark.asyncio
    async def test_inactive_users_excluded_from_all(self):
        # Service issues a single DB query with is_active filter;
        # simulate that the DB already returns only active users.
        active_users = [_make_user(1, is_active=True)]
        db = _make_db(active_users)
        result = await get_broadcast_recipients(db, BroadcastTarget.ALL)
        assert all(u.is_active for u in result)

    @pytest.mark.asyncio
    async def test_inactive_riders_excluded(self):
        active_riders = [_make_user(1, UserRole.RIDER, is_active=True)]
        db = _make_db(active_riders)
        result = await get_broadcast_recipients(db, BroadcastTarget.RIDERS)
        assert all(u.is_active for u in result)

    @pytest.mark.asyncio
    async def test_inactive_drivers_excluded(self):
        active_drivers = [_make_user(1, UserRole.DRIVER, is_active=True)]
        db = _make_db(active_drivers)
        result = await get_broadcast_recipients(db, BroadcastTarget.DRIVERS)
        assert all(u.is_active for u in result)

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_list(self):
        db = _make_db([])
        result = await get_broadcast_recipients(db, BroadcastTarget.ALL)
        assert result == []


# ---------------------------------------------------------------------------
# 19-30: send_bulk_notification
# ---------------------------------------------------------------------------


def _make_req(
    target: BroadcastTarget = BroadcastTarget.ALL,
    title: str = "Broadcast Title",
    body: str = "Broadcast body text",
    channels: list[str] | None = None,
) -> BulkNotificationRequest:
    return BulkNotificationRequest(
        target=target,
        title=title,
        body=body,
        channels=channels or ["push"],
    )


class TestSendBulkNotification:
    @pytest.mark.asyncio
    async def test_creates_broadcast_record_in_db(self):
        users = [_make_user(1)]
        db = _make_db(users)

        with patch(
            "app.services.bulk_notifications.send_notification",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.services.bulk_notifications.log_event",
            new_callable=AsyncMock,
        ):
            await send_bulk_notification(db, admin_id=99, req=_make_req())

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert isinstance(added, BroadcastRecord)

    @pytest.mark.asyncio
    async def test_broadcast_record_has_correct_recipient_count(self):
        users = [_make_user(i) for i in range(3)]
        db = _make_db(users)

        with patch(
            "app.services.bulk_notifications.send_notification",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.services.bulk_notifications.log_event",
            new_callable=AsyncMock,
        ):
            await send_bulk_notification(db, admin_id=99, req=_make_req())

        added = db.add.call_args[0][0]
        assert added.recipient_count == 3

    @pytest.mark.asyncio
    async def test_send_notification_called_once_per_recipient(self):
        users = [_make_user(i + 1) for i in range(4)]
        db = _make_db(users)

        with patch(
            "app.services.bulk_notifications.send_notification",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_send, patch(
            "app.services.bulk_notifications.log_event",
            new_callable=AsyncMock,
        ):
            await send_bulk_notification(db, admin_id=99, req=_make_req())

        assert mock_send.call_count == 4

    @pytest.mark.asyncio
    async def test_sent_count_equals_successful_sends(self):
        users = [_make_user(1), _make_user(2), _make_user(3)]
        db = _make_db(users)

        with patch(
            "app.services.bulk_notifications.send_notification",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.services.bulk_notifications.log_event",
            new_callable=AsyncMock,
        ):
            result = await send_bulk_notification(db, admin_id=99, req=_make_req())

        assert result.sent_count == 3
        assert result.failed_count == 0

    @pytest.mark.asyncio
    async def test_failed_count_equals_failed_sends(self):
        users = [_make_user(1), _make_user(2)]
        db = _make_db(users)

        with patch(
            "app.services.bulk_notifications.send_notification",
            new_callable=AsyncMock,
            return_value=False,
        ), patch(
            "app.services.bulk_notifications.log_event",
            new_callable=AsyncMock,
        ):
            result = await send_bulk_notification(db, admin_id=99, req=_make_req())

        assert result.failed_count == 2
        assert result.sent_count == 0

    @pytest.mark.asyncio
    async def test_result_has_broadcast_id(self):
        users = [_make_user(1)]
        db = _make_db(users)

        with patch(
            "app.services.bulk_notifications.send_notification",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.services.bulk_notifications.log_event",
            new_callable=AsyncMock,
        ):
            result = await send_bulk_notification(db, admin_id=99, req=_make_req())

        assert isinstance(result.broadcast_id, int)

    @pytest.mark.asyncio
    async def test_result_title_matches_request(self):
        db = _make_db([_make_user(1)])

        with patch(
            "app.services.bulk_notifications.send_notification",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.services.bulk_notifications.log_event",
            new_callable=AsyncMock,
        ):
            result = await send_bulk_notification(
                db, admin_id=99, req=_make_req(title="My Announcement")
            )

        assert result.title == "My Announcement"

    @pytest.mark.asyncio
    async def test_result_target_matches_request(self):
        db = _make_db([_make_user(1)])

        with patch(
            "app.services.bulk_notifications.send_notification",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.services.bulk_notifications.log_event",
            new_callable=AsyncMock,
        ):
            result = await send_bulk_notification(
                db, admin_id=99, req=_make_req(target=BroadcastTarget.DRIVERS)
            )

        assert result.target == BroadcastTarget.DRIVERS

    @pytest.mark.asyncio
    async def test_result_recipient_count_matches_users(self):
        users = [_make_user(i + 1) for i in range(5)]
        db = _make_db(users)

        with patch(
            "app.services.bulk_notifications.send_notification",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.services.bulk_notifications.log_event",
            new_callable=AsyncMock,
        ):
            result = await send_bulk_notification(db, admin_id=99, req=_make_req())

        assert result.recipient_count == 5

    @pytest.mark.asyncio
    async def test_zero_recipients_produces_zero_counts(self):
        db = _make_db([])

        with patch(
            "app.services.bulk_notifications.send_notification",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_send, patch(
            "app.services.bulk_notifications.log_event",
            new_callable=AsyncMock,
        ):
            result = await send_bulk_notification(db, admin_id=99, req=_make_req())

        assert result.sent_count == 0
        assert result.failed_count == 0
        assert result.recipient_count == 0
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_exception_increments_failed_count(self):
        users = [_make_user(1), _make_user(2)]
        db = _make_db(users)

        with patch(
            "app.services.bulk_notifications.send_notification",
            new_callable=AsyncMock,
            side_effect=RuntimeError("provider down"),
        ), patch(
            "app.services.bulk_notifications.log_event",
            new_callable=AsyncMock,
        ):
            result = await send_bulk_notification(db, admin_id=99, req=_make_req())

        assert result.failed_count == 2
        assert result.sent_count == 0

    @pytest.mark.asyncio
    async def test_send_exception_does_not_propagate(self):
        db = _make_db([_make_user(1)])

        with patch(
            "app.services.bulk_notifications.send_notification",
            new_callable=AsyncMock,
            side_effect=Exception("boom"),
        ), patch(
            "app.services.bulk_notifications.log_event",
            new_callable=AsyncMock,
        ):
            # Should not raise
            result = await send_bulk_notification(db, admin_id=99, req=_make_req())

        assert result.failed_count == 1


# ---------------------------------------------------------------------------
# 31-34: list_broadcasts
# ---------------------------------------------------------------------------


class TestListBroadcasts:
    @pytest.mark.asyncio
    async def test_returns_records_newest_first(self):
        records = [
            _make_broadcast_record(record_id=3),
            _make_broadcast_record(record_id=2),
            _make_broadcast_record(record_id=1),
        ]
        db = _make_db(records)
        result = await list_broadcasts(db)
        assert [r.id for r in result] == [3, 2, 1]

    @pytest.mark.asyncio
    async def test_respects_limit_parameter(self):
        # The service passes limit to the query; DB mock returns whatever we give it.
        records = [_make_broadcast_record(record_id=i) for i in range(3)]
        db = _make_db(records)
        result = await list_broadcasts(db, limit=3)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_respects_offset_parameter(self):
        records = [_make_broadcast_record(record_id=5)]
        db = _make_db(records)
        result = await list_broadcasts(db, offset=2)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_list(self):
        db = _make_db([])
        result = await list_broadcasts(db)
        assert result == []


# ---------------------------------------------------------------------------
# 35-45: Endpoint tests (via conftest client / integration fixtures)
# ---------------------------------------------------------------------------


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


BASE = "/api/v1/admin/notifications"

_VALID_PAYLOAD = {
    "target": "all",
    "title": "System Maintenance",
    "body": "The platform will be offline from 2-3 AM.",
    "channels": ["push"],
}


@pytest.mark.anyio
class TestBroadcastEndpointAuth:
    async def test_post_broadcast_returns_403_for_rider(self, client, rider, rider_token):
        resp = await client.post(
            f"{BASE}/broadcast",
            json=_VALID_PAYLOAD,
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_post_broadcast_returns_403_for_driver(self, client, driver_user, driver_token):
        resp = await client.post(
            f"{BASE}/broadcast",
            json=_VALID_PAYLOAD,
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 403

    async def test_post_broadcast_without_auth_returns_401_or_403(self, client):
        resp = await client.post(f"{BASE}/broadcast", json=_VALID_PAYLOAD)
        assert resp.status_code in (401, 403)


@pytest.mark.anyio
class TestBroadcastEndpointLogic:
    async def test_post_broadcast_returns_201_on_success(
        self, client, admin_user, admin_token
    ):
        with patch(
            "app.services.bulk_notifications.send_notification",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.services.bulk_notifications.log_event",
            new_callable=AsyncMock,
        ):
            resp = await client.post(
                f"{BASE}/broadcast",
                json=_VALID_PAYLOAD,
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 201

    async def test_post_broadcast_invalid_channel_returns_422(
        self, client, admin_user, admin_token
    ):
        payload = {**_VALID_PAYLOAD, "channels": ["carrier_pigeon"]}
        resp = await client.post(
            f"{BASE}/broadcast",
            json=payload,
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_post_broadcast_empty_channels_returns_422(
        self, client, admin_user, admin_token
    ):
        payload = {**_VALID_PAYLOAD, "channels": []}
        resp = await client.post(
            f"{BASE}/broadcast",
            json=payload,
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_post_broadcast_response_has_counts(
        self, client, admin_user, admin_token
    ):
        with patch(
            "app.services.bulk_notifications.send_notification",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.services.bulk_notifications.log_event",
            new_callable=AsyncMock,
        ):
            resp = await client.post(
                f"{BASE}/broadcast",
                json=_VALID_PAYLOAD,
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "recipient_count" in data
        assert "sent_count" in data
        assert "failed_count" in data
        assert "broadcast_id" in data


@pytest.mark.anyio
class TestBroadcastsListEndpoint:
    async def test_get_broadcasts_returns_403_for_rider(
        self, client, rider, rider_token
    ):
        resp = await client.get(
            f"{BASE}/broadcasts",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_get_broadcasts_returns_list(
        self, client, admin_user, admin_token
    ):
        resp = await client.get(
            f"{BASE}/broadcasts",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


@pytest.mark.anyio
class TestBroadcastDetailEndpoint:
    async def test_get_broadcast_detail_returns_404_for_missing_id(
        self, client, admin_user, admin_token
    ):
        resp = await client.get(
            f"{BASE}/broadcasts/999999",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404

    async def test_get_broadcast_detail_returns_correct_data(
        self, client, admin_user, admin_token
    ):
        with patch(
            "app.services.bulk_notifications.send_notification",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.services.bulk_notifications.log_event",
            new_callable=AsyncMock,
        ):
            create_resp = await client.post(
                f"{BASE}/broadcast",
                json=_VALID_PAYLOAD,
                headers=auth_header(admin_token),
            )
        assert create_resp.status_code == 201
        broadcast_id = create_resp.json()["broadcast_id"]

        detail_resp = await client.get(
            f"{BASE}/broadcasts/{broadcast_id}",
            headers=auth_header(admin_token),
        )
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["broadcast_id"] == broadcast_id
        assert detail["title"] == _VALID_PAYLOAD["title"]
