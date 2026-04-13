"""Comprehensive unit tests for the per-user notification preferences feature.

Covers:
1.  Model: tablename, columns, unique constraint
2.  Schema: valid/invalid notification_type and channel values
3.  Service: get_user_preferences default (empty DB = all enabled)
4.  Service: set_preference creates new record and upserts existing
5.  Service: bulk_set_preferences
6.  Service: is_channel_enabled with and without a record
7.  Service: SOS_ALERT bypass — is_channel_enabled returns stored value;
    bypass is documented in send_notification (not in the preference check)
8.  Service: reset_preference deletes the record
9.  Integration: send_notification skips disabled channel, sends enabled ones
10. Integration: SOS_ALERT always sent regardless of disabled preference
11. Endpoints: GET, PUT single, PUT bulk, DELETE

All tests are pure unit tests — no database required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.notification_preference import NotificationPreference
from app.schemas.notification_preference import (
    BulkSetPreferenceRequest,
    NotificationPreferenceResponse,
    SetPreferenceRequest,
    UserPreferencesResponse,
    _VALID_CHANNELS,
    _VALID_NOTIFICATION_TYPES,
)
from app.services.notification_preferences import (
    _ALL_CHANNELS,
    _ALL_NOTIFICATION_TYPES,
    bulk_set_preferences,
    get_user_preferences,
    is_channel_enabled,
    reset_preference,
    set_preference,
)
from app.services.notifications import (
    Notification,
    NotificationChannel,
    NotificationType,
    clear_sent_notifications,
    get_sent_notifications,
    send_notification,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db() -> AsyncMock:
    """Return a lightweight async mock of AsyncSession."""
    db = AsyncMock()
    db.add = MagicMock()
    return db


def _make_pref(
    *,
    id: int = 1,
    user_id: int = 42,
    notification_type: str = "ride_matched",
    channel: str = "push",
    enabled: bool = True,
) -> NotificationPreference:
    now = datetime.now(timezone.utc)
    pref = NotificationPreference(
        user_id=user_id,
        notification_type=notification_type,
        channel=channel,
        enabled=enabled,
    )
    pref.id = id
    pref.created_at = now
    pref.updated_at = now
    return pref


# ===========================================================================
# 1. Model tests
# ===========================================================================


class TestNotificationPreferenceModel:
    def test_tablename(self):
        assert NotificationPreference.__tablename__ == "notification_preferences_v2"

    def test_required_columns_present(self):
        cols = {c.key for c in NotificationPreference.__table__.columns}
        assert {"id", "user_id", "notification_type", "channel", "enabled",
                "created_at", "updated_at"}.issubset(cols)

    def test_enabled_default_is_true(self):
        col = NotificationPreference.__table__.columns["enabled"]
        # server_default or default should represent True
        assert col.default is not None or col.server_default is not None

    def test_unique_constraint_exists(self):
        constraint_names = {
            c.name for c in NotificationPreference.__table__.constraints
        }
        assert "uq_notif_pref_user_type_channel" in constraint_names

    def test_user_id_has_foreign_key(self):
        col = NotificationPreference.__table__.columns["user_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert "users.id" in str(fks[0].target_fullname)

    def test_notification_type_column_length(self):
        col = NotificationPreference.__table__.columns["notification_type"]
        assert col.type.length == 60

    def test_channel_column_length(self):
        col = NotificationPreference.__table__.columns["channel"]
        assert col.type.length == 20


# ===========================================================================
# 2. Schema tests
# ===========================================================================


class TestSetPreferenceRequestSchema:
    def test_valid_request(self):
        req = SetPreferenceRequest(
            notification_type="ride_matched", channel="push", enabled=True
        )
        assert req.notification_type == "ride_matched"
        assert req.channel == "push"
        assert req.enabled is True

    def test_valid_disabled(self):
        req = SetPreferenceRequest(
            notification_type="promo_applied", channel="sms", enabled=False
        )
        assert req.enabled is False

    def test_invalid_notification_type_raises(self):
        with pytest.raises(Exception):
            SetPreferenceRequest(
                notification_type="completely_made_up", channel="push", enabled=True
            )

    def test_invalid_channel_raises(self):
        with pytest.raises(Exception):
            SetPreferenceRequest(
                notification_type="ride_matched", channel="carrier_pigeon", enabled=True
            )

    def test_all_notification_types_are_valid(self):
        for nt in _VALID_NOTIFICATION_TYPES:
            req = SetPreferenceRequest(
                notification_type=nt, channel="push", enabled=True
            )
            assert req.notification_type == nt

    def test_all_channels_are_valid(self):
        for ch in _VALID_CHANNELS:
            req = SetPreferenceRequest(
                notification_type="ride_matched", channel=ch, enabled=True
            )
            assert req.channel == ch

    def test_sos_alert_is_valid_notification_type(self):
        """sos_alert must be a valid type (the bypass is in send_notification, not schema)."""
        req = SetPreferenceRequest(
            notification_type="sos_alert", channel="push", enabled=False
        )
        assert req.notification_type == "sos_alert"

    def test_enabled_field_required(self):
        with pytest.raises(Exception):
            SetPreferenceRequest(notification_type="ride_matched", channel="push")


class TestBulkSetPreferenceRequestSchema:
    def test_empty_list_is_valid(self):
        req = BulkSetPreferenceRequest(updates=[])
        assert req.updates == []

    def test_multiple_updates(self):
        req = BulkSetPreferenceRequest(
            updates=[
                SetPreferenceRequest(notification_type="ride_matched", channel="push", enabled=False),
                SetPreferenceRequest(notification_type="promo_applied", channel="email", enabled=False),
            ]
        )
        assert len(req.updates) == 2

    def test_invalid_item_raises(self):
        with pytest.raises(Exception):
            BulkSetPreferenceRequest(
                updates=[{"notification_type": "bogus_type", "channel": "push", "enabled": True}]
            )


class TestNotificationPreferenceResponseSchema:
    def test_from_model(self):
        pref = _make_pref(id=5, notification_type="sos_alert", channel="sms", enabled=True)
        resp = NotificationPreferenceResponse.model_validate(pref)
        assert resp.id == 5
        assert resp.notification_type == "sos_alert"
        assert resp.channel == "sms"
        assert resp.enabled is True

    def test_fields_present(self):
        fields = set(NotificationPreferenceResponse.model_fields.keys())
        assert {"id", "notification_type", "channel", "enabled"}.issubset(fields)


class TestUserPreferencesResponseSchema:
    def test_wraps_dict(self):
        prefs = {"ride_matched": {"push": True, "sms": False, "email": True}}
        resp = UserPreferencesResponse(preferences=prefs)
        assert resp.preferences["ride_matched"]["sms"] is False


# ===========================================================================
# 3. Service: get_user_preferences — defaults when no records exist
# ===========================================================================


class TestGetUserPreferences:
    @pytest.mark.asyncio
    async def test_empty_db_returns_all_enabled(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        prefs = await get_user_preferences(db, user_id=1)

        for notif_type in _ALL_NOTIFICATION_TYPES:
            assert notif_type in prefs
            for channel in _ALL_CHANNELS:
                assert prefs[notif_type][channel] is True

    @pytest.mark.asyncio
    async def test_all_types_and_channels_present(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        prefs = await get_user_preferences(db, user_id=1)

        assert set(prefs.keys()) == set(_ALL_NOTIFICATION_TYPES)
        for ch_map in prefs.values():
            assert set(ch_map.keys()) == set(_ALL_CHANNELS)

    @pytest.mark.asyncio
    async def test_stored_disabled_pref_overrides_default(self):
        db = _mock_db()
        stored_pref = _make_pref(notification_type="promo_applied", channel="email", enabled=False)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stored_pref]
        db.execute = AsyncMock(return_value=mock_result)

        prefs = await get_user_preferences(db, user_id=42)

        assert prefs["promo_applied"]["email"] is False
        # other channels still default to True
        assert prefs["promo_applied"]["push"] is True
        assert prefs["promo_applied"]["sms"] is True

    @pytest.mark.asyncio
    async def test_multiple_stored_prefs(self):
        db = _mock_db()
        stored = [
            _make_pref(notification_type="ride_matched", channel="sms", enabled=False),
            _make_pref(notification_type="ride_completed", channel="push", enabled=False),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = stored
        db.execute = AsyncMock(return_value=mock_result)

        prefs = await get_user_preferences(db, user_id=5)

        assert prefs["ride_matched"]["sms"] is False
        assert prefs["ride_completed"]["push"] is False
        assert prefs["ride_matched"]["push"] is True


# ===========================================================================
# 4. Service: set_preference
# ===========================================================================


class TestSetPreference:
    @pytest.mark.asyncio
    async def test_creates_new_record_when_none_exists(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()

        pref = await set_preference(db, user_id=1, notification_type="ride_matched",
                                    channel="push", enabled=False)

        db.add.assert_called_once()
        assert pref.user_id == 1
        assert pref.notification_type == "ride_matched"
        assert pref.channel == "push"
        assert pref.enabled is False

    @pytest.mark.asyncio
    async def test_updates_existing_record(self):
        db = _mock_db()
        existing = _make_pref(enabled=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()

        pref = await set_preference(db, user_id=42, notification_type="ride_matched",
                                    channel="push", enabled=False)

        db.add.assert_not_called()
        assert pref.enabled is False

    @pytest.mark.asyncio
    async def test_flush_is_called(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()

        await set_preference(db, user_id=1, notification_type="payment_received",
                             channel="sms", enabled=False)

        db.flush.assert_called_once()


# ===========================================================================
# 5. Service: bulk_set_preferences
# ===========================================================================


class TestBulkSetPreferences:
    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self):
        db = _mock_db()
        result = await bulk_set_preferences(db, user_id=1, updates=[])
        assert result == []

    @pytest.mark.asyncio
    async def test_multiple_updates_applied(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()

        updates = [
            {"notification_type": "promo_applied", "channel": "email", "enabled": False},
            {"notification_type": "ride_reminder", "channel": "sms", "enabled": False},
        ]
        prefs = await bulk_set_preferences(db, user_id=7, updates=updates)

        assert len(prefs) == 2
        assert prefs[0].notification_type == "promo_applied"
        assert prefs[1].notification_type == "ride_reminder"

    @pytest.mark.asyncio
    async def test_bulk_returns_in_input_order(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()

        updates = [
            {"notification_type": "rating_received", "channel": "push", "enabled": False},
            {"notification_type": "payment_received", "channel": "email", "enabled": True},
            {"notification_type": "payout_completed", "channel": "sms", "enabled": False},
        ]
        prefs = await bulk_set_preferences(db, user_id=3, updates=updates)

        types = [p.notification_type for p in prefs]
        assert types == ["rating_received", "payment_received", "payout_completed"]


# ===========================================================================
# 6. Service: is_channel_enabled
# ===========================================================================


class TestIsChannelEnabled:
    @pytest.mark.asyncio
    async def test_no_record_returns_true(self):
        """Default opt-in: missing row means enabled."""
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        result = await is_channel_enabled(db, user_id=1, notification_type="ride_matched",
                                          channel="push")
        assert result is True

    @pytest.mark.asyncio
    async def test_record_enabled_true_returns_true(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = True
        db.execute = AsyncMock(return_value=mock_result)

        result = await is_channel_enabled(db, user_id=1, notification_type="ride_matched",
                                          channel="push")
        assert result is True

    @pytest.mark.asyncio
    async def test_record_enabled_false_returns_false(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = False
        db.execute = AsyncMock(return_value=mock_result)

        result = await is_channel_enabled(db, user_id=1, notification_type="promo_applied",
                                          channel="email")
        assert result is False


# ===========================================================================
# 7. Service: SOS_ALERT bypass is documented (bypass is in send_notification)
# ===========================================================================


class TestSosAlertBypassDocumentation:
    """The SOS_ALERT bypass lives in send_notification(), not is_channel_enabled().

    These tests confirm that is_channel_enabled() faithfully returns the stored
    value for sos_alert, and that send_notification() skips the preference check
    for SOS_ALERT notifications.
    """

    @pytest.mark.asyncio
    async def test_is_channel_enabled_returns_false_for_sos_when_disabled(self):
        """is_channel_enabled returns whatever is stored; bypass is caller's responsibility."""
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = False
        db.execute = AsyncMock(return_value=mock_result)

        result = await is_channel_enabled(db, user_id=1, notification_type="sos_alert",
                                          channel="push")
        assert result is False

    @pytest.mark.asyncio
    async def test_sos_alert_bypass_in_send_notification(self):
        """send_notification() does NOT call is_channel_enabled for SOS_ALERT."""
        clear_sent_notifications()

        notif = Notification(
            user_id=1,
            type=NotificationType.SOS_ALERT,
            title="Emergency",
            body="SOS triggered",
            channels=[NotificationChannel.PUSH],
        )

        call_count = 0

        async def mock_is_enabled(db, user_id, notification_type, channel):
            nonlocal call_count
            call_count += 1
            return False  # Would block if consulted

        with (
            patch("app.services.notifications.send_push", new_callable=AsyncMock, return_value=True),
            patch("app.services.notifications.send_sms", new_callable=AsyncMock, return_value=True),
            patch("app.services.notifications.send_email", new_callable=AsyncMock, return_value=True),
            patch("app.services.notification_preferences.is_channel_enabled", mock_is_enabled),
        ):
            db = _mock_db()
            # Provide a mock for device token lookup
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            db.execute = AsyncMock(return_value=mock_result)
            db.flush = AsyncMock()

            # Patch _persist_log to avoid DB writes
            with patch("app.services.notifications._persist_log", new_callable=AsyncMock):
                await send_notification(notif, db=db)

        # is_channel_enabled must NOT have been called for SOS_ALERT
        assert call_count == 0, (
            "send_notification() should not consult is_channel_enabled for SOS_ALERT"
        )


# ===========================================================================
# 8. Service: reset_preference
# ===========================================================================


class TestResetPreference:
    @pytest.mark.asyncio
    async def test_returns_true_when_record_deleted(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 1  # The deleted id
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()

        result = await reset_preference(db, user_id=1, notification_type="ride_matched",
                                        channel="push")
        assert result is True
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_false_when_no_record(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()

        result = await reset_preference(db, user_id=1, notification_type="ride_matched",
                                        channel="push")
        assert result is False
        db.flush.assert_not_called()


# ===========================================================================
# 9. Integration: send_notification skips disabled channel
# ===========================================================================


class TestSendNotificationWithPreferences:
    @pytest.mark.asyncio
    async def test_disabled_channel_is_skipped(self):
        """When a channel is disabled, send_notification skips it."""
        clear_sent_notifications()

        notif = Notification(
            user_id=1,
            type=NotificationType.PROMO_APPLIED,
            title="Promo",
            body="You have a promo",
            channels=[NotificationChannel.EMAIL],
        )

        async def mock_is_enabled(db, user_id, notification_type, channel):
            return False  # disabled

        with (
            patch("app.services.notifications.send_email", new_callable=AsyncMock) as mock_email,
            patch(
                "app.services.notification_preferences.is_channel_enabled",
                side_effect=mock_is_enabled,
            ),
        ):
            db = _mock_db()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            db.execute = AsyncMock(return_value=mock_result)

            with patch("app.services.notifications._persist_log", new_callable=AsyncMock):
                await send_notification(notif, db=db, email="user@example.com")

            mock_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_enabled_channel_is_sent(self):
        """When a channel is enabled, send_notification dispatches it."""
        clear_sent_notifications()

        notif = Notification(
            user_id=2,
            type=NotificationType.RIDE_MATCHED,
            title="Match",
            body="Driver found",
            channels=[NotificationChannel.SMS],
        )

        async def mock_is_enabled(db, user_id, notification_type, channel):
            return True

        with (
            patch("app.services.notifications.send_sms", new_callable=AsyncMock, return_value=True) as mock_sms,
            patch(
                "app.services.notification_preferences.is_channel_enabled",
                side_effect=mock_is_enabled,
            ),
        ):
            db = _mock_db()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            db.execute = AsyncMock(return_value=mock_result)

            with patch("app.services.notifications._persist_log", new_callable=AsyncMock):
                await send_notification(notif, db=db, phone="+15550001234")

            mock_sms.assert_called_once()

    @pytest.mark.asyncio
    async def test_mixed_channels_some_disabled(self):
        """Enabled channels are sent; disabled channels are skipped."""
        clear_sent_notifications()

        notif = Notification(
            user_id=3,
            type=NotificationType.PAYMENT_RECEIVED,
            title="Payment",
            body="You received a payment",
            channels=[NotificationChannel.PUSH, NotificationChannel.EMAIL],
        )

        async def mock_is_enabled(db, user_id, notification_type, channel):
            return channel == "push"  # push enabled, email disabled

        with (
            patch("app.services.notifications.send_push", new_callable=AsyncMock, return_value=True) as mock_push,
            patch("app.services.notifications.send_email", new_callable=AsyncMock) as mock_email,
            patch(
                "app.services.notification_preferences.is_channel_enabled",
                side_effect=mock_is_enabled,
            ),
        ):
            db = _mock_db()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            db.execute = AsyncMock(return_value=mock_result)

            with patch("app.services.notifications._persist_log", new_callable=AsyncMock):
                await send_notification(notif, db=db, email="user@example.com")

            mock_push.assert_called_once()
            mock_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_db_skips_preference_check(self):
        """When db=None, no preference check is made and the channel is sent."""
        clear_sent_notifications()

        notif = Notification(
            user_id=5,
            type=NotificationType.RIDE_MATCHED,
            title="Match",
            body="Driver found",
            channels=[NotificationChannel.SMS],
        )

        with patch("app.services.notifications.send_sms", new_callable=AsyncMock, return_value=True) as mock_sms:
            await send_notification(notif, db=None, phone="+15550001234")

        mock_sms.assert_called_once()


# ===========================================================================
# 10. Endpoint tests
# ===========================================================================


def _make_app_with_mock_user(user_id: int = 42):
    """Return a test client with auth dependency overridden."""
    import httpx
    from fastapi import FastAPI
    from app.api.v1.notification_preferences import router
    from app.api.deps import get_current_user
    from app.db.database import get_db

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    mock_user = MagicMock()
    mock_user.id = user_id

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: AsyncMock()

    return app


class TestNotificationPreferencesEndpoints:
    @pytest.mark.asyncio
    async def test_get_preferences_returns_full_map(self):
        import httpx
        from fastapi import FastAPI
        from app.api.v1.notification_preferences import router
        from app.api.deps import get_current_user
        from app.db.database import get_db

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        mock_user = MagicMock()
        mock_user.id = 42
        mock_db = AsyncMock()

        full_map = {nt: {ch: True for ch in _ALL_CHANNELS} for nt in _ALL_NOTIFICATION_TYPES}
        full_map["promo_applied"]["email"] = False

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("app.api.v1.notification_preferences.get_user_preferences",
                   new_callable=AsyncMock, return_value=full_map):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/users/me/notification-preferences")

        assert resp.status_code == 200
        body = resp.json()
        assert "preferences" in body
        assert body["preferences"]["promo_applied"]["email"] is False

    @pytest.mark.asyncio
    async def test_put_single_preference(self):
        import httpx
        from fastapi import FastAPI
        from app.api.v1.notification_preferences import router
        from app.api.deps import get_current_user
        from app.db.database import get_db

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        mock_user = MagicMock()
        mock_user.id = 1
        mock_db = AsyncMock()

        saved = _make_pref(notification_type="ride_matched", channel="push", enabled=False)

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("app.api.v1.notification_preferences.set_preference",
                   new_callable=AsyncMock, return_value=saved):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    "/api/v1/users/me/notification-preferences/ride_matched/push",
                    json={"notification_type": "ride_matched", "channel": "push", "enabled": False},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is False
        assert body["notification_type"] == "ride_matched"
        assert body["channel"] == "push"

    @pytest.mark.asyncio
    async def test_put_single_invalid_type_returns_422(self):
        import httpx
        from fastapi import FastAPI
        from app.api.v1.notification_preferences import router
        from app.api.deps import get_current_user
        from app.db.database import get_db

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        mock_user = MagicMock()
        mock_user.id = 1
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/api/v1/users/me/notification-preferences/totally_fake_type/push",
                json={"notification_type": "totally_fake_type", "channel": "push", "enabled": False},
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_put_single_invalid_channel_returns_422(self):
        import httpx
        from fastapi import FastAPI
        from app.api.v1.notification_preferences import router
        from app.api.deps import get_current_user
        from app.db.database import get_db

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        mock_user = MagicMock()
        mock_user.id = 1
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/api/v1/users/me/notification-preferences/ride_matched/telegraph",
                json={"notification_type": "ride_matched", "channel": "telegraph", "enabled": False},
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_put_bulk_preferences(self):
        import httpx
        from fastapi import FastAPI
        from app.api.v1.notification_preferences import router
        from app.api.deps import get_current_user
        from app.db.database import get_db

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        mock_user = MagicMock()
        mock_user.id = 1
        mock_db = AsyncMock()

        saved = [
            _make_pref(id=1, notification_type="promo_applied", channel="email", enabled=False),
            _make_pref(id=2, notification_type="ride_reminder", channel="sms", enabled=False),
        ]

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("app.api.v1.notification_preferences.bulk_set_preferences",
                   new_callable=AsyncMock, return_value=saved):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    "/api/v1/users/me/notification-preferences/bulk",
                    json={
                        "updates": [
                            {"notification_type": "promo_applied", "channel": "email", "enabled": False},
                            {"notification_type": "ride_reminder", "channel": "sms", "enabled": False},
                        ]
                    },
                )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        assert body[0]["notification_type"] == "promo_applied"

    @pytest.mark.asyncio
    async def test_put_bulk_invalid_item_returns_422(self):
        import httpx
        from fastapi import FastAPI
        from app.api.v1.notification_preferences import router
        from app.api.deps import get_current_user
        from app.db.database import get_db

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        mock_user = MagicMock()
        mock_user.id = 1
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/api/v1/users/me/notification-preferences/bulk",
                json={
                    "updates": [
                        {"notification_type": "totally_invalid_type", "channel": "push", "enabled": False}
                    ]
                },
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_delete_resets_preference(self):
        import httpx
        from fastapi import FastAPI
        from app.api.v1.notification_preferences import router
        from app.api.deps import get_current_user
        from app.db.database import get_db

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        mock_user = MagicMock()
        mock_user.id = 1
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("app.api.v1.notification_preferences.reset_preference",
                   new_callable=AsyncMock, return_value=True):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.delete(
                    "/api/v1/users/me/notification-preferences/ride_matched/push"
                )

        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_nonexistent_still_returns_204(self):
        """DELETE is idempotent — 204 even when no record existed."""
        import httpx
        from fastapi import FastAPI
        from app.api.v1.notification_preferences import router
        from app.api.deps import get_current_user
        from app.db.database import get_db

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        mock_user = MagicMock()
        mock_user.id = 1
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("app.api.v1.notification_preferences.reset_preference",
                   new_callable=AsyncMock, return_value=False):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.delete(
                    "/api/v1/users/me/notification-preferences/ride_matched/push"
                )

        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_invalid_type_returns_422(self):
        import httpx
        from fastapi import FastAPI
        from app.api.v1.notification_preferences import router
        from app.api.deps import get_current_user
        from app.db.database import get_db

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        mock_user = MagicMock()
        mock_user.id = 1
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete(
                "/api/v1/users/me/notification-preferences/fake_type/push"
            )

        assert resp.status_code == 422
