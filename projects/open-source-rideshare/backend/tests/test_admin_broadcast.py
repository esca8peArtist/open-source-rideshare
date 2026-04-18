"""Tests for admin notification broadcast endpoint and schemas."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.user import User, UserRole
from app.schemas.admin import BroadcastRequest, BroadcastResult, BroadcastSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id: int, role: UserRole, phone: str, email: str | None = None) -> MagicMock:
    user = MagicMock(spec=User)
    user.id = user_id
    user.role = role
    user.is_active = True
    user.phone = phone
    user.email = email
    return user


def _mock_db_with_users(users: list) -> AsyncMock:
    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = users
    mock_db.execute = AsyncMock(return_value=result_mock)
    mock_db.flush = AsyncMock()
    return mock_db


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestBroadcastSegment:
    def test_all_values(self):
        assert BroadcastSegment.ALL_RIDERS == "all_riders"
        assert BroadcastSegment.ALL_DRIVERS == "all_drivers"
        assert BroadcastSegment.ALL_USERS == "all_users"


class TestBroadcastRequest:
    def test_defaults(self):
        req = BroadcastRequest(segment="all_riders", title="Hello", body="World")
        assert req.channels == ["push"]
        assert req.segment == BroadcastSegment.ALL_RIDERS

    def test_custom_channels(self):
        req = BroadcastRequest(
            segment="all_drivers",
            title="Notice",
            body="Important update",
            channels=["push", "sms"],
        )
        assert req.channels == ["push", "sms"]

    def test_all_channels(self):
        req = BroadcastRequest(
            segment="all_users",
            title="T",
            body="B",
            channels=["push", "sms", "email"],
        )
        assert len(req.channels) == 3

    def test_title_min_length(self):
        with pytest.raises(Exception):
            BroadcastRequest(segment="all_riders", title="", body="Some body text")

    def test_body_min_length(self):
        with pytest.raises(Exception):
            BroadcastRequest(segment="all_riders", title="Title", body="")

    def test_title_max_length(self):
        with pytest.raises(Exception):
            BroadcastRequest(segment="all_riders", title="x" * 201, body="Body")

    def test_body_max_length(self):
        with pytest.raises(Exception):
            BroadcastRequest(segment="all_riders", title="Title", body="x" * 1001)

    def test_invalid_segment(self):
        with pytest.raises(Exception):
            BroadcastRequest(segment="all_ghosts", title="Title", body="Body")


class TestBroadcastResult:
    def test_construction(self):
        now = datetime.now(timezone.utc)
        result = BroadcastResult(
            segment="all_riders",
            title="Hello",
            total_targeted=50,
            total_sent=48,
            total_failed=2,
            channels=["push"],
            sent_at=now,
        )
        assert result.total_targeted == 50
        assert result.total_sent == 48
        assert result.total_failed == 2
        assert result.channels == ["push"]
        assert result.sent_at == now

    def test_zero_counts(self):
        result = BroadcastResult(
            segment="all_drivers",
            title="T",
            total_targeted=0,
            total_sent=0,
            total_failed=0,
            channels=["push", "sms"],
            sent_at=datetime.now(timezone.utc),
        )
        assert result.total_targeted == 0
        assert result.total_sent == 0


# ---------------------------------------------------------------------------
# Endpoint unit tests
# ---------------------------------------------------------------------------

class TestBroadcastNotificationEndpoint:
    @pytest.mark.asyncio
    async def test_all_riders_segment_sends_to_each_rider(self):
        from app.api.v1.admin import broadcast_notification

        riders = [
            _make_user(1, UserRole.RIDER, "+15550001111", "r1@test.com"),
            _make_user(2, UserRole.RIDER, "+15550002222", "r2@test.com"),
        ]
        mock_db = _mock_db_with_users(riders)

        payload = BroadcastRequest(segment="all_riders", title="Test", body="Hello riders")

        with patch("app.services.notifications.send_notification", new=AsyncMock(return_value=True)):
            result = await broadcast_notification(payload=payload, db=mock_db)

        assert result.segment == "all_riders"
        assert result.total_targeted == 2
        assert result.total_sent == 2
        assert result.total_failed == 0
        assert result.channels == ["push"]

    @pytest.mark.asyncio
    async def test_all_drivers_segment(self):
        from app.api.v1.admin import broadcast_notification

        drivers = [_make_user(10, UserRole.DRIVER, "+15550003333")]
        mock_db = _mock_db_with_users(drivers)

        payload = BroadcastRequest(segment="all_drivers", title="Driver notice", body="Please update the app")

        with patch("app.services.notifications.send_notification", new=AsyncMock(return_value=True)):
            result = await broadcast_notification(payload=payload, db=mock_db)

        assert result.segment == "all_drivers"
        assert result.total_targeted == 1
        assert result.total_sent == 1

    @pytest.mark.asyncio
    async def test_all_users_segment(self):
        from app.api.v1.admin import broadcast_notification

        users = [
            _make_user(1, UserRole.RIDER, "+15550001111"),
            _make_user(2, UserRole.DRIVER, "+15550002222"),
        ]
        mock_db = _mock_db_with_users(users)

        payload = BroadcastRequest(segment="all_users", title="Platform update", body="We have a new feature")

        with patch("app.services.notifications.send_notification", new=AsyncMock(return_value=True)):
            result = await broadcast_notification(payload=payload, db=mock_db)

        assert result.segment == "all_users"
        assert result.total_targeted == 2
        assert result.total_sent == 2

    @pytest.mark.asyncio
    async def test_empty_segment_returns_zero_counts(self):
        from app.api.v1.admin import broadcast_notification

        mock_db = _mock_db_with_users([])
        payload = BroadcastRequest(segment="all_riders", title="Empty", body="No one here")

        with patch("app.services.notifications.send_notification", new=AsyncMock(return_value=True)):
            result = await broadcast_notification(payload=payload, db=mock_db)

        assert result.total_targeted == 0
        assert result.total_sent == 0
        assert result.total_failed == 0

    @pytest.mark.asyncio
    async def test_failed_notification_counted(self):
        from app.api.v1.admin import broadcast_notification

        users = [
            _make_user(1, UserRole.RIDER, "+15550001111"),
            _make_user(2, UserRole.RIDER, "+15550002222"),
        ]
        mock_db = _mock_db_with_users(users)
        payload = BroadcastRequest(segment="all_riders", title="Test", body="Body")

        # First call succeeds, second fails
        send_mock = AsyncMock(side_effect=[True, False])
        with patch("app.services.notifications.send_notification", new=send_mock):
            result = await broadcast_notification(payload=payload, db=mock_db)

        assert result.total_sent == 1
        assert result.total_failed == 1
        assert result.total_targeted == 2

    @pytest.mark.asyncio
    async def test_invalid_channels_dropped_falls_back_to_push(self):
        from app.api.v1.admin import broadcast_notification

        users = [_make_user(1, UserRole.RIDER, "+15550001111")]
        mock_db = _mock_db_with_users(users)

        payload = BroadcastRequest(
            segment="all_riders",
            title="Test",
            body="Body",
            channels=["fax", "telepathy"],
        )

        with patch("app.services.notifications.send_notification", new=AsyncMock(return_value=True)):
            result = await broadcast_notification(payload=payload, db=mock_db)

        assert result.channels == ["push"]

    @pytest.mark.asyncio
    async def test_mixed_channels_invalid_ones_dropped(self):
        from app.api.v1.admin import broadcast_notification

        users = [_make_user(1, UserRole.RIDER, "+15550001111")]
        mock_db = _mock_db_with_users(users)

        payload = BroadcastRequest(
            segment="all_riders",
            title="Test",
            body="Body",
            channels=["push", "fax", "sms"],
        )

        with patch("app.services.notifications.send_notification", new=AsyncMock(return_value=True)):
            result = await broadcast_notification(payload=payload, db=mock_db)

        assert "push" in result.channels
        assert "sms" in result.channels
        assert "fax" not in result.channels

    @pytest.mark.asyncio
    async def test_result_has_sent_at_timestamp(self):
        from app.api.v1.admin import broadcast_notification

        mock_db = _mock_db_with_users([])
        payload = BroadcastRequest(segment="all_users", title="T", body="B")

        with patch("app.services.notifications.send_notification", new=AsyncMock(return_value=True)):
            result = await broadcast_notification(payload=payload, db=mock_db)

        assert isinstance(result.sent_at, datetime)
        assert result.sent_at.tzinfo is not None

    @pytest.mark.asyncio
    async def test_send_notification_called_with_correct_user_data(self):
        from app.api.v1.admin import broadcast_notification

        user = _make_user(42, UserRole.RIDER, "+15550009999", "user@example.com")
        mock_db = _mock_db_with_users([user])
        payload = BroadcastRequest(segment="all_riders", title="Promo", body="Get 20% off")

        send_mock = AsyncMock(return_value=True)
        with patch("app.services.notifications.send_notification", new=send_mock):
            await broadcast_notification(payload=payload, db=mock_db)

        assert send_mock.call_count == 1
        call_kwargs = send_mock.call_args
        # First positional arg is the Notification object
        notification_arg = call_kwargs[0][0]
        assert notification_arg.user_id == 42
        assert notification_arg.title == "Promo"
        assert notification_arg.body == "Get 20% off"
        # phone and email passed as kwargs
        assert call_kwargs[1]["phone"] == "+15550009999"
        assert call_kwargs[1]["email"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_result_title_matches_payload(self):
        from app.api.v1.admin import broadcast_notification

        mock_db = _mock_db_with_users([])
        payload = BroadcastRequest(segment="all_drivers", title="Driver Alert", body="Check the app")

        with patch("app.services.notifications.send_notification", new=AsyncMock(return_value=True)):
            result = await broadcast_notification(payload=payload, db=mock_db)

        assert result.title == "Driver Alert"
        assert result.segment == "all_drivers"
