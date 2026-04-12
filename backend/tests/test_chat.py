"""Tests for in-app chat messaging between driver and rider."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.chat import ChatMessage
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.schemas.chat import (
    ChatHistoryResponse,
    ChatMessageResponse,
    ChatMessageSend,
    UnreadCountResponse,
)
from app.services.chat import (
    CHAT_ALLOWED_STATUSES,
    get_recipient_id,
    get_ride_messages,
    get_unread_count,
    mark_messages_read,
    save_message,
    validate_chat_participant,
)


# ===========================================================================
# ChatMessage Model Tests
# ===========================================================================


class TestChatMessageModel:
    def test_table_name(self):
        assert ChatMessage.__tablename__ == "chat_messages"

    def test_has_ride_id_column(self):
        cols = {c.name for c in ChatMessage.__table__.columns}
        assert "ride_id" in cols

    def test_has_sender_id_column(self):
        cols = {c.name for c in ChatMessage.__table__.columns}
        assert "sender_id" in cols

    def test_has_recipient_id_column(self):
        cols = {c.name for c in ChatMessage.__table__.columns}
        assert "recipient_id" in cols

    def test_has_message_column(self):
        cols = {c.name for c in ChatMessage.__table__.columns}
        assert "message" in cols

    def test_has_is_read_column(self):
        cols = {c.name for c in ChatMessage.__table__.columns}
        assert "is_read" in cols

    def test_has_created_at_column(self):
        cols = {c.name for c in ChatMessage.__table__.columns}
        assert "created_at" in cols

    def test_ride_id_is_indexed(self):
        col = ChatMessage.__table__.columns["ride_id"]
        assert col.index is True

    def test_sender_id_is_indexed(self):
        col = ChatMessage.__table__.columns["sender_id"]
        assert col.index is True

    def test_recipient_id_is_indexed(self):
        col = ChatMessage.__table__.columns["recipient_id"]
        assert col.index is True

    def test_created_at_is_indexed(self):
        col = ChatMessage.__table__.columns["created_at"]
        assert col.index is True

    def test_ride_id_has_fk(self):
        col = ChatMessage.__table__.columns["ride_id"]
        fk_targets = [fk.target_fullname for fk in col.foreign_keys]
        assert "rides.id" in fk_targets

    def test_sender_id_has_fk(self):
        col = ChatMessage.__table__.columns["sender_id"]
        fk_targets = [fk.target_fullname for fk in col.foreign_keys]
        assert "users.id" in fk_targets

    def test_recipient_id_has_fk(self):
        col = ChatMessage.__table__.columns["recipient_id"]
        fk_targets = [fk.target_fullname for fk in col.foreign_keys]
        assert "users.id" in fk_targets


# ===========================================================================
# Schema Validation Tests
# ===========================================================================


class TestChatMessageSendSchema:
    def test_valid_message(self):
        msg = ChatMessageSend(ride_id=1, message="Hello driver!")
        assert msg.ride_id == 1
        assert msg.message == "Hello driver!"

    def test_message_stripped(self):
        msg = ChatMessageSend(ride_id=1, message="  Hello  ")
        assert msg.message == "Hello"

    def test_empty_message_rejected(self):
        with pytest.raises(ValueError):
            ChatMessageSend(ride_id=1, message="")

    def test_whitespace_only_message_rejected(self):
        with pytest.raises(ValueError):
            ChatMessageSend(ride_id=1, message="   ")

    def test_message_too_long_rejected(self):
        with pytest.raises(ValueError):
            ChatMessageSend(ride_id=1, message="x" * 2001)

    def test_message_at_max_length(self):
        msg = ChatMessageSend(ride_id=1, message="x" * 2000)
        assert len(msg.message) == 2000

    def test_ride_id_required(self):
        with pytest.raises(ValueError):
            ChatMessageSend(message="Hello")


class TestChatMessageResponseSchema:
    def test_from_attributes(self):
        assert ChatMessageResponse.model_config.get("from_attributes") is True

    def test_all_fields_present(self):
        fields = set(ChatMessageResponse.model_fields.keys())
        assert fields == {"id", "ride_id", "sender_id", "recipient_id", "message", "is_read", "created_at"}


class TestChatHistoryResponseSchema:
    def test_fields(self):
        fields = set(ChatHistoryResponse.model_fields.keys())
        assert fields == {"ride_id", "messages", "total"}

    def test_empty_history(self):
        resp = ChatHistoryResponse(ride_id=1, messages=[], total=0)
        assert resp.total == 0
        assert resp.messages == []


class TestUnreadCountResponseSchema:
    def test_fields(self):
        fields = set(UnreadCountResponse.model_fields.keys())
        assert fields == {"ride_id", "unread_count"}

    def test_zero_unread(self):
        resp = UnreadCountResponse(ride_id=1, unread_count=0)
        assert resp.unread_count == 0


# ===========================================================================
# Chat Service — CHAT_ALLOWED_STATUSES
# ===========================================================================


class TestChatAllowedStatuses:
    def test_matched_allowed(self):
        assert RideStatus.MATCHED in CHAT_ALLOWED_STATUSES

    def test_driver_en_route_allowed(self):
        assert RideStatus.DRIVER_EN_ROUTE in CHAT_ALLOWED_STATUSES

    def test_arrived_allowed(self):
        assert RideStatus.ARRIVED in CHAT_ALLOWED_STATUSES

    def test_in_progress_allowed(self):
        assert RideStatus.IN_PROGRESS in CHAT_ALLOWED_STATUSES

    def test_requested_not_allowed(self):
        assert RideStatus.REQUESTED not in CHAT_ALLOWED_STATUSES

    def test_completed_not_allowed(self):
        assert RideStatus.COMPLETED not in CHAT_ALLOWED_STATUSES

    def test_cancelled_not_allowed(self):
        assert RideStatus.CANCELLED not in CHAT_ALLOWED_STATUSES

    def test_scheduled_not_allowed(self):
        assert RideStatus.SCHEDULED not in CHAT_ALLOWED_STATUSES

    def test_exactly_four_statuses(self):
        assert len(CHAT_ALLOWED_STATUSES) == 4


# ===========================================================================
# Chat Service — get_recipient_id
# ===========================================================================


class TestGetRecipientId:
    def _make_ride(self, rider_id=10, driver_id=20):
        ride = MagicMock(spec=Ride)
        ride.rider_id = rider_id
        ride.driver_id = driver_id
        return ride

    def test_sender_is_rider_returns_driver(self):
        ride = self._make_ride(rider_id=10, driver_id=20)
        assert get_recipient_id(ride, 10) == 20

    def test_sender_is_driver_returns_rider(self):
        ride = self._make_ride(rider_id=10, driver_id=20)
        assert get_recipient_id(ride, 20) == 10

    def test_different_ids(self):
        ride = self._make_ride(rider_id=5, driver_id=99)
        assert get_recipient_id(ride, 5) == 99
        assert get_recipient_id(ride, 99) == 5


# ===========================================================================
# Chat Service — validate_chat_participant
# ===========================================================================


class TestValidateChatParticipant:
    @pytest.mark.asyncio
    async def test_ride_not_found(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute.return_value = result_mock

        ride, error = await validate_chat_participant(db, 999, 1)
        assert ride is None
        assert error == "Ride not found"

    @pytest.mark.asyncio
    async def test_ride_wrong_status(self):
        ride = MagicMock(spec=Ride)
        ride.status = RideStatus.COMPLETED
        ride.rider_id = 1
        ride.driver_id = 2

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = ride
        db.execute.return_value = result_mock

        result_ride, error = await validate_chat_participant(db, 1, 1)
        assert result_ride is None
        assert "completed" in error

    @pytest.mark.asyncio
    async def test_user_not_participant(self):
        ride = MagicMock(spec=Ride)
        ride.status = RideStatus.IN_PROGRESS
        ride.rider_id = 1
        ride.driver_id = 2

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = ride
        db.execute.return_value = result_mock

        result_ride, error = await validate_chat_participant(db, 1, 999)
        assert result_ride is None
        assert "not a participant" in error

    @pytest.mark.asyncio
    async def test_valid_rider_participant(self):
        ride = MagicMock(spec=Ride)
        ride.status = RideStatus.MATCHED
        ride.rider_id = 10
        ride.driver_id = 20

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = ride
        db.execute.return_value = result_mock

        result_ride, error = await validate_chat_participant(db, 1, 10)
        assert result_ride is ride
        assert error is None

    @pytest.mark.asyncio
    async def test_valid_driver_participant(self):
        ride = MagicMock(spec=Ride)
        ride.status = RideStatus.DRIVER_EN_ROUTE
        ride.rider_id = 10
        ride.driver_id = 20

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = ride
        db.execute.return_value = result_mock

        result_ride, error = await validate_chat_participant(db, 1, 20)
        assert result_ride is ride
        assert error is None

    @pytest.mark.asyncio
    async def test_all_allowed_statuses_pass(self):
        for s in CHAT_ALLOWED_STATUSES:
            ride = MagicMock(spec=Ride)
            ride.status = s
            ride.rider_id = 1
            ride.driver_id = 2

            db = AsyncMock()
            result_mock = MagicMock()
            result_mock.scalar_one_or_none.return_value = ride
            db.execute.return_value = result_mock

            result_ride, error = await validate_chat_participant(db, 1, 1)
            assert error is None, f"Status {s} should be allowed"


# ===========================================================================
# Chat Service — save_message
# ===========================================================================


class TestSaveMessage:
    @pytest.mark.asyncio
    async def test_save_message_calls_db(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        # Patch ChatMessage constructor to avoid triggering ORM mapper configuration
        with patch("app.services.chat.ChatMessage") as MockChatMessage:
            mock_instance = MagicMock()
            MockChatMessage.return_value = mock_instance

            await save_message(db, ride_id=1, sender_id=10, recipient_id=20, message="Hi!")

        MockChatMessage.assert_called_once_with(
            ride_id=1, sender_id=10, recipient_id=20, message="Hi!",
        )
        db.add.assert_called_once_with(mock_instance)
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(mock_instance)


# ===========================================================================
# WebSocket Chat Handler Tests
# ===========================================================================


class TestWebSocketChatHandler:
    @pytest.mark.asyncio
    async def test_handle_chat_missing_ride_id(self):
        from app.api.websocket import _handle_chat_message

        ws = AsyncMock()
        await _handle_chat_message(1, {"message": "hi"}, ws)
        ws.send_json.assert_called_once()
        sent = ws.send_json.call_args[0][0]
        assert sent["type"] == "chat_error"
        assert "required" in sent["error"]

    @pytest.mark.asyncio
    async def test_handle_chat_missing_message(self):
        from app.api.websocket import _handle_chat_message

        ws = AsyncMock()
        await _handle_chat_message(1, {"ride_id": 1}, ws)
        ws.send_json.assert_called_once()
        sent = ws.send_json.call_args[0][0]
        assert sent["type"] == "chat_error"

    @pytest.mark.asyncio
    async def test_handle_chat_empty_message(self):
        from app.api.websocket import _handle_chat_message

        ws = AsyncMock()
        await _handle_chat_message(1, {"ride_id": 1, "message": "   "}, ws)
        ws.send_json.assert_called_once()
        sent = ws.send_json.call_args[0][0]
        assert sent["type"] == "chat_error"

    @pytest.mark.asyncio
    async def test_handle_chat_message_too_long(self):
        from app.api.websocket import _handle_chat_message

        ws = AsyncMock()
        await _handle_chat_message(1, {"ride_id": 1, "message": "x" * 2001}, ws)
        ws.send_json.assert_called_once()
        sent = ws.send_json.call_args[0][0]
        assert sent["type"] == "chat_error"
        assert "2000" in sent["error"]

    @pytest.mark.asyncio
    async def test_handle_chat_validation_failure(self):
        from app.api.websocket import _handle_chat_message

        ws = AsyncMock()

        mock_db = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.database.async_session", return_value=mock_session_ctx), \
             patch("app.services.chat.validate_chat_participant", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = (None, "Ride not found")

            await _handle_chat_message(1, {"ride_id": 99, "message": "hi"}, ws)

        ws.send_json.assert_called_once()
        sent = ws.send_json.call_args[0][0]
        assert sent["type"] == "chat_error"
        assert sent["error"] == "Ride not found"

    @pytest.mark.asyncio
    async def test_handle_chat_success(self):
        from app.api.websocket import _handle_chat_message, manager

        ws = AsyncMock()
        mock_ride = MagicMock(spec=Ride)
        mock_ride.rider_id = 1
        mock_ride.driver_id = 2

        mock_msg = MagicMock(spec=ChatMessage)
        mock_msg.id = 42
        mock_msg.created_at = datetime(2026, 4, 12, tzinfo=timezone.utc)

        mock_db = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.database.async_session", return_value=mock_session_ctx), \
             patch("app.services.chat.validate_chat_participant", new_callable=AsyncMock) as mock_validate, \
             patch("app.services.chat.save_message", new_callable=AsyncMock) as mock_save, \
             patch("app.services.chat.get_recipient_id") as mock_get_recip, \
             patch.object(manager, "send_to_rider", new_callable=AsyncMock) as mock_send_rider, \
             patch.object(manager, "send_to_driver", new_callable=AsyncMock) as mock_send_driver:

            mock_validate.return_value = (mock_ride, None)
            mock_save.return_value = mock_msg
            mock_get_recip.return_value = 2
            mock_send_rider.return_value = True

            await _handle_chat_message(1, {"ride_id": 5, "message": "Almost there?"}, ws)

        # Should get chat_ack
        ack_call = ws.send_json.call_args_list[0][0][0]
        assert ack_call["type"] == "chat_ack"
        assert ack_call["message_id"] == 42

        # Should relay to recipient
        mock_send_rider.assert_called_once()
        relay_payload = mock_send_rider.call_args[0][1]
        assert relay_payload["type"] == "chat_message"
        assert relay_payload["sender_id"] == 1

    @pytest.mark.asyncio
    async def test_handle_chat_relays_to_driver_if_rider_offline(self):
        from app.api.websocket import _handle_chat_message, manager

        ws = AsyncMock()
        mock_ride = MagicMock(spec=Ride)
        mock_ride.rider_id = 1
        mock_ride.driver_id = 2

        mock_msg = MagicMock(spec=ChatMessage)
        mock_msg.id = 43
        mock_msg.created_at = datetime(2026, 4, 12, tzinfo=timezone.utc)

        mock_db = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.database.async_session", return_value=mock_session_ctx), \
             patch("app.services.chat.validate_chat_participant", new_callable=AsyncMock) as mock_validate, \
             patch("app.services.chat.save_message", new_callable=AsyncMock) as mock_save, \
             patch("app.services.chat.get_recipient_id") as mock_get_recip, \
             patch.object(manager, "send_to_rider", new_callable=AsyncMock) as mock_send_rider, \
             patch.object(manager, "send_to_driver", new_callable=AsyncMock) as mock_send_driver:

            mock_validate.return_value = (mock_ride, None)
            mock_save.return_value = mock_msg
            mock_get_recip.return_value = 2
            mock_send_rider.return_value = False  # rider not connected
            mock_send_driver.return_value = True

            await _handle_chat_message(1, {"ride_id": 5, "message": "Hello"}, ws)

        # Falls through to driver pool
        mock_send_driver.assert_called_once()


# ===========================================================================
# relay_chat_message Tests
# ===========================================================================


class TestRelayChatMessage:
    @pytest.mark.asyncio
    async def test_relay_to_rider(self):
        from app.api.websocket import manager, relay_chat_message

        with patch.object(manager, "send_to_rider", new_callable=AsyncMock) as mock_rider:
            mock_rider.return_value = True
            result = await relay_chat_message(
                recipient_id=10, message_id=1, ride_id=5,
                sender_id=20, message_text="hi", created_at="2026-04-12T00:00:00+00:00",
            )
        assert result is True
        mock_rider.assert_called_once()

    @pytest.mark.asyncio
    async def test_relay_falls_through_to_driver(self):
        from app.api.websocket import manager, relay_chat_message

        with patch.object(manager, "send_to_rider", new_callable=AsyncMock) as mock_rider, \
             patch.object(manager, "send_to_driver", new_callable=AsyncMock) as mock_driver:
            mock_rider.return_value = False
            mock_driver.return_value = True
            result = await relay_chat_message(
                recipient_id=10, message_id=1, ride_id=5,
                sender_id=20, message_text="hi", created_at="2026-04-12T00:00:00+00:00",
            )
        assert result is True
        mock_driver.assert_called_once()

    @pytest.mark.asyncio
    async def test_relay_returns_false_if_offline(self):
        from app.api.websocket import manager, relay_chat_message

        with patch.object(manager, "send_to_rider", new_callable=AsyncMock) as mock_rider, \
             patch.object(manager, "send_to_driver", new_callable=AsyncMock) as mock_driver:
            mock_rider.return_value = False
            mock_driver.return_value = False
            result = await relay_chat_message(
                recipient_id=10, message_id=1, ride_id=5,
                sender_id=20, message_text="hi", created_at="2026-04-12T00:00:00+00:00",
            )
        assert result is False


# ===========================================================================
# REST API Endpoint Tests (via TestClient)
# ===========================================================================


class TestChatRESTEndpoints:
    """Test the REST chat endpoints using mocked dependencies."""

    def _make_user(self, user_id=1, role="rider"):
        user = MagicMock(spec=User)
        user.id = user_id
        user.role = UserRole(role)
        user.is_active = True
        return user

    @pytest.mark.asyncio
    async def test_send_message_ride_id_mismatch(self):
        from app.api.v1.chat import send_chat_message
        from fastapi import HTTPException

        user = self._make_user()
        body = ChatMessageSend(ride_id=99, message="Hello")
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await send_chat_message(ride_id=1, body=body, user=user, db=db)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_send_message_not_participant(self):
        from app.api.v1.chat import send_chat_message
        from fastapi import HTTPException

        user = self._make_user(user_id=999)
        body = ChatMessageSend(ride_id=1, message="Hello")
        db = AsyncMock()

        with patch("app.api.v1.chat.validate_chat_participant", new_callable=AsyncMock) as mock_v:
            mock_v.return_value = (None, "You are not a participant in this ride")
            with pytest.raises(HTTPException) as exc_info:
                await send_chat_message(ride_id=1, body=body, user=user, db=db)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_send_message_success(self):
        from app.api.v1.chat import send_chat_message

        user = self._make_user(user_id=1)
        body = ChatMessageSend(ride_id=1, message="On my way")
        db = AsyncMock()

        mock_ride = MagicMock(spec=Ride)
        mock_ride.rider_id = 1
        mock_ride.driver_id = 2

        mock_msg = MagicMock(spec=ChatMessage)
        mock_msg.id = 10
        mock_msg.ride_id = 1
        mock_msg.sender_id = 1
        mock_msg.recipient_id = 2
        mock_msg.message = "On my way"
        mock_msg.is_read = False
        mock_msg.created_at = datetime(2026, 4, 12, tzinfo=timezone.utc)

        with patch("app.api.v1.chat.validate_chat_participant", new_callable=AsyncMock) as mock_v, \
             patch("app.api.v1.chat.get_recipient_id") as mock_recip, \
             patch("app.api.v1.chat.save_message", new_callable=AsyncMock) as mock_save, \
             patch("app.api.websocket.relay_chat_message", new_callable=AsyncMock):
            mock_v.return_value = (mock_ride, None)
            mock_recip.return_value = 2
            mock_save.return_value = mock_msg

            result = await send_chat_message(ride_id=1, body=body, user=user, db=db)

        assert result.id == 10
        assert result.message == "On my way"

    @pytest.mark.asyncio
    async def test_get_chat_history(self):
        from app.api.v1.chat import get_chat_history

        user = self._make_user(user_id=1)
        db = AsyncMock()

        mock_msg = MagicMock(spec=ChatMessage)
        mock_msg.id = 1
        mock_msg.ride_id = 5
        mock_msg.sender_id = 1
        mock_msg.recipient_id = 2
        mock_msg.message = "hello"
        mock_msg.is_read = True
        mock_msg.created_at = datetime(2026, 4, 12, tzinfo=timezone.utc)

        with patch("app.api.v1.chat.get_ride_messages", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = ([mock_msg], 1)
            result = await get_chat_history(ride_id=5, limit=100, before_id=None, user=user, db=db)

        assert result.ride_id == 5
        assert result.total == 1
        assert len(result.messages) == 1

    @pytest.mark.asyncio
    async def test_mark_read(self):
        from app.api.v1.chat import mark_read

        user = self._make_user(user_id=1)
        db = AsyncMock()

        with patch("app.api.v1.chat.mark_messages_read", new_callable=AsyncMock) as mock_mark:
            mock_mark.return_value = 3
            result = await mark_read(ride_id=5, user=user, db=db)

        assert result["ride_id"] == 5
        assert result["marked_read"] == 3

    @pytest.mark.asyncio
    async def test_get_unread(self):
        from app.api.v1.chat import get_unread

        user = self._make_user(user_id=1)
        db = AsyncMock()

        with patch("app.api.v1.chat.get_unread_count", new_callable=AsyncMock) as mock_count:
            mock_count.return_value = 7
            result = await get_unread(ride_id=5, user=user, db=db)

        assert result.ride_id == 5
        assert result.unread_count == 7


# ===========================================================================
# Integration: Model registration
# ===========================================================================


class TestModelRegistration:
    def test_chat_message_imported_in_init(self):
        from app.models import ChatMessage as ImportedModel
        assert ImportedModel is ChatMessage

    def test_chat_message_has_ride_fk(self):
        col = ChatMessage.__table__.columns["ride_id"]
        fk_targets = [fk.target_fullname for fk in col.foreign_keys]
        assert "rides.id" in fk_targets


# ===========================================================================
# Router registration
# ===========================================================================


class TestRouterRegistration:
    def test_chat_router_in_app(self):
        from app.main import app
        routes = [r.path for r in app.routes]
        assert any("/chat/" in r for r in routes)

    def test_chat_history_route_exists(self):
        from app.main import app
        routes = [r.path for r in app.routes]
        assert "/api/v1/chat/rides/{ride_id}/messages" in routes

    def test_mark_read_route_exists(self):
        from app.main import app
        routes = [r.path for r in app.routes]
        assert "/api/v1/chat/rides/{ride_id}/messages/read" in routes

    def test_unread_route_exists(self):
        from app.main import app
        routes = [r.path for r in app.routes]
        assert "/api/v1/chat/rides/{ride_id}/unread" in routes
