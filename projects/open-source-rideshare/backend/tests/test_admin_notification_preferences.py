"""Tests for admin notification preference management endpoints.

Covers:
- GET /admin/users/{user_id}/notification-preferences — view user prefs, 404 on unknown user
- PUT /admin/users/{user_id}/notification-preferences/{type}/{channel} — single override, 404, 422
- PUT /admin/users/{user_id}/notification-preferences — bulk override, 404, 422
- DELETE /admin/users/{user_id}/notification-preferences/{type}/{channel} — reset, 404, 422
- Schema: AdminUserPreferencesResponse, AdminSetPreferenceRequest, AdminBulkSetPreferenceRequest
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.user import User, UserRole
from app.schemas.admin import (
    AdminBulkSetPreferenceRequest,
    AdminSetPreferenceRequest,
    AdminUserPreferencesResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id: int = 42, role: UserRole = UserRole.RIDER) -> MagicMock:
    user = MagicMock(spec=User)
    user.id = user_id
    user.role = role
    user.is_active = True
    return user


def _mock_db(user: MagicMock | None = None) -> AsyncMock:
    db = AsyncMock()
    db.get = AsyncMock(return_value=user)
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


_FULL_PREFS: dict = {
    nt: {"push": True, "sms": True, "email": True}
    for nt in [
        "ride_matched",
        "ride_cancelled",
        "ride_completed",
        "driver_en_route",
        "driver_arrived",
        "payment_received",
        "sos_alert",
        "rating_received",
        "account_verification",
        "payout_completed",
        "ride_reminder",
        "fare_split_request",
        "promo_applied",
        "promo_expiring",
        "background_check_approved",
        "background_check_action_required",
    ]
}


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestAdminUserPreferencesResponse:
    def test_basic_structure(self):
        resp = AdminUserPreferencesResponse(user_id=5, preferences=_FULL_PREFS)
        assert resp.user_id == 5
        assert resp.preferences["ride_matched"]["push"] is True
        assert "promo_expiring" in resp.preferences

    def test_empty_preferences(self):
        resp = AdminUserPreferencesResponse(user_id=1, preferences={})
        assert resp.preferences == {}

    def test_partial_preferences(self):
        prefs = {"sos_alert": {"push": False, "sms": True, "email": True}}
        resp = AdminUserPreferencesResponse(user_id=3, preferences=prefs)
        assert resp.preferences["sos_alert"]["push"] is False


class TestAdminSetPreferenceRequest:
    def test_enabled_true(self):
        req = AdminSetPreferenceRequest(enabled=True)
        assert req.enabled is True

    def test_enabled_false(self):
        req = AdminSetPreferenceRequest(enabled=False)
        assert req.enabled is False


class TestAdminBulkSetPreferenceRequest:
    def test_valid_updates(self):
        req = AdminBulkSetPreferenceRequest(
            updates=[
                {"notification_type": "ride_matched", "channel": "push", "enabled": False},
                {"notification_type": "sos_alert", "channel": "sms", "enabled": True},
            ]
        )
        assert len(req.updates) == 2

    def test_empty_updates(self):
        req = AdminBulkSetPreferenceRequest(updates=[])
        assert req.updates == []


# ---------------------------------------------------------------------------
# GET /admin/users/{user_id}/notification-preferences
# ---------------------------------------------------------------------------

class TestAdminGetUserNotificationPreferences:
    @pytest.mark.asyncio
    async def test_returns_full_pref_map(self):
        from app.api.v1.admin import admin_get_user_notification_preferences

        user = _make_user(user_id=42)
        db = _mock_db(user=user)

        with patch(
            "app.services.notification_preferences.get_user_preferences",
            new_callable=AsyncMock,
            return_value=_FULL_PREFS,
        ):
            resp = await admin_get_user_notification_preferences(user_id=42, db=db)

        assert resp.user_id == 42
        assert "ride_matched" in resp.preferences
        assert "promo_expiring" in resp.preferences

    @pytest.mark.asyncio
    async def test_404_on_unknown_user(self):
        from fastapi import HTTPException
        from app.api.v1.admin import admin_get_user_notification_preferences

        db = _mock_db(user=None)

        with pytest.raises(HTTPException) as exc_info:
            await admin_get_user_notification_preferences(user_id=999, db=db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_works_for_driver_user(self):
        from app.api.v1.admin import admin_get_user_notification_preferences

        user = _make_user(user_id=7, role=UserRole.DRIVER)
        db = _mock_db(user=user)

        with patch(
            "app.services.notification_preferences.get_user_preferences",
            new_callable=AsyncMock,
            return_value={"sos_alert": {"push": False, "sms": True, "email": True}},
        ):
            resp = await admin_get_user_notification_preferences(user_id=7, db=db)

        assert resp.user_id == 7
        assert resp.preferences["sos_alert"]["push"] is False


# ---------------------------------------------------------------------------
# PUT /admin/users/{user_id}/notification-preferences/{type}/{channel}
# ---------------------------------------------------------------------------

class TestAdminSetUserNotificationPreference:
    @pytest.mark.asyncio
    async def test_sets_preference_and_returns_map(self):
        from app.api.v1.admin import admin_set_user_notification_preference

        user = _make_user(user_id=10)
        db = _mock_db(user=user)
        body = AdminSetPreferenceRequest(enabled=False)

        updated_prefs = {**_FULL_PREFS, "ride_matched": {"push": False, "sms": True, "email": True}}

        with (
            patch(
                "app.services.notification_preferences.set_preference",
                new_callable=AsyncMock,
            ) as mock_set,
            patch(
                "app.services.notification_preferences.get_user_preferences",
                new_callable=AsyncMock,
                return_value=updated_prefs,
            ),
        ):
            resp = await admin_set_user_notification_preference(
                user_id=10,
                notification_type="ride_matched",
                channel="push",
                body=body,
                db=db,
            )
            mock_set.assert_awaited_once_with(db, 10, "ride_matched", "push", False)

        assert resp.user_id == 10
        assert resp.preferences["ride_matched"]["push"] is False
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_404_on_unknown_user(self):
        from fastapi import HTTPException
        from app.api.v1.admin import admin_set_user_notification_preference

        db = _mock_db(user=None)
        body = AdminSetPreferenceRequest(enabled=True)

        with pytest.raises(HTTPException) as exc_info:
            await admin_set_user_notification_preference(
                user_id=999,
                notification_type="ride_matched",
                channel="push",
                body=body,
                db=db,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_422_on_invalid_notification_type(self):
        from fastapi import HTTPException
        from app.api.v1.admin import admin_set_user_notification_preference

        user = _make_user()
        db = _mock_db(user=user)
        body = AdminSetPreferenceRequest(enabled=True)

        with pytest.raises(HTTPException) as exc_info:
            await admin_set_user_notification_preference(
                user_id=42,
                notification_type="not_a_real_type",
                channel="push",
                body=body,
                db=db,
            )

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_422_on_invalid_channel(self):
        from fastapi import HTTPException
        from app.api.v1.admin import admin_set_user_notification_preference

        user = _make_user()
        db = _mock_db(user=user)
        body = AdminSetPreferenceRequest(enabled=True)

        with pytest.raises(HTTPException) as exc_info:
            await admin_set_user_notification_preference(
                user_id=42,
                notification_type="ride_matched",
                channel="telegram",
                body=body,
                db=db,
            )

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_enable_true_stores_correctly(self):
        from app.api.v1.admin import admin_set_user_notification_preference

        user = _make_user(user_id=5)
        db = _mock_db(user=user)
        body = AdminSetPreferenceRequest(enabled=True)

        with (
            patch(
                "app.services.notification_preferences.set_preference",
                new_callable=AsyncMock,
            ) as mock_set,
            patch(
                "app.services.notification_preferences.get_user_preferences",
                new_callable=AsyncMock,
                return_value=_FULL_PREFS,
            ),
        ):
            await admin_set_user_notification_preference(
                user_id=5,
                notification_type="promo_expiring",
                channel="sms",
                body=body,
                db=db,
            )
            mock_set.assert_awaited_once_with(db, 5, "promo_expiring", "sms", True)


# ---------------------------------------------------------------------------
# PUT /admin/users/{user_id}/notification-preferences (bulk)
# ---------------------------------------------------------------------------

class TestAdminBulkSetUserNotificationPreferences:
    @pytest.mark.asyncio
    async def test_bulk_update_calls_service(self):
        from app.api.v1.admin import admin_bulk_set_user_notification_preferences

        user = _make_user(user_id=20)
        db = _mock_db(user=user)
        body = AdminBulkSetPreferenceRequest(
            updates=[
                {"notification_type": "ride_matched", "channel": "push", "enabled": False},
                {"notification_type": "promo_expiring", "channel": "email", "enabled": False},
            ]
        )

        with (
            patch(
                "app.services.notification_preferences.bulk_set_preferences",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_bulk,
            patch(
                "app.services.notification_preferences.get_user_preferences",
                new_callable=AsyncMock,
                return_value=_FULL_PREFS,
            ),
        ):
            resp = await admin_bulk_set_user_notification_preferences(
                user_id=20,
                body=body,
                db=db,
            )
            mock_bulk.assert_awaited_once_with(db, 20, body.updates)

        assert resp.user_id == 20
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_404_on_unknown_user(self):
        from fastapi import HTTPException
        from app.api.v1.admin import admin_bulk_set_user_notification_preferences

        db = _mock_db(user=None)
        body = AdminBulkSetPreferenceRequest(updates=[])

        with pytest.raises(HTTPException) as exc_info:
            await admin_bulk_set_user_notification_preferences(
                user_id=999, body=body, db=db
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_422_on_invalid_type_in_updates(self):
        from fastapi import HTTPException
        from app.api.v1.admin import admin_bulk_set_user_notification_preferences

        user = _make_user()
        db = _mock_db(user=user)
        body = AdminBulkSetPreferenceRequest(
            updates=[{"notification_type": "invalid_type", "channel": "push", "enabled": True}]
        )

        with pytest.raises(HTTPException) as exc_info:
            await admin_bulk_set_user_notification_preferences(
                user_id=42, body=body, db=db
            )

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_422_on_invalid_channel_in_updates(self):
        from fastapi import HTTPException
        from app.api.v1.admin import admin_bulk_set_user_notification_preferences

        user = _make_user()
        db = _mock_db(user=user)
        body = AdminBulkSetPreferenceRequest(
            updates=[{"notification_type": "ride_matched", "channel": "fax", "enabled": True}]
        )

        with pytest.raises(HTTPException) as exc_info:
            await admin_bulk_set_user_notification_preferences(
                user_id=42, body=body, db=db
            )

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_updates_succeeds(self):
        from app.api.v1.admin import admin_bulk_set_user_notification_preferences

        user = _make_user(user_id=3)
        db = _mock_db(user=user)
        body = AdminBulkSetPreferenceRequest(updates=[])

        with (
            patch(
                "app.services.notification_preferences.bulk_set_preferences",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.notification_preferences.get_user_preferences",
                new_callable=AsyncMock,
                return_value=_FULL_PREFS,
            ),
        ):
            resp = await admin_bulk_set_user_notification_preferences(
                user_id=3, body=body, db=db
            )

        assert resp.user_id == 3


# ---------------------------------------------------------------------------
# DELETE /admin/users/{user_id}/notification-preferences/{type}/{channel}
# ---------------------------------------------------------------------------

class TestAdminResetUserNotificationPreference:
    @pytest.mark.asyncio
    async def test_reset_existing_preference(self):
        from app.api.v1.admin import admin_reset_user_notification_preference

        user = _make_user(user_id=15)
        db = _mock_db(user=user)

        with patch(
            "app.services.notification_preferences.reset_preference",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_reset:
            await admin_reset_user_notification_preference(
                user_id=15,
                notification_type="ride_cancelled",
                channel="email",
                db=db,
            )
            mock_reset.assert_awaited_once_with(db, 15, "ride_cancelled", "email")

        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reset_nonexistent_preference_still_returns_204(self):
        from app.api.v1.admin import admin_reset_user_notification_preference

        user = _make_user(user_id=15)
        db = _mock_db(user=user)

        with patch(
            "app.services.notification_preferences.reset_preference",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await admin_reset_user_notification_preference(
                user_id=15,
                notification_type="ride_cancelled",
                channel="email",
                db=db,
            )

        assert result is None  # 204 No Content

    @pytest.mark.asyncio
    async def test_404_on_unknown_user(self):
        from fastapi import HTTPException
        from app.api.v1.admin import admin_reset_user_notification_preference

        db = _mock_db(user=None)

        with pytest.raises(HTTPException) as exc_info:
            await admin_reset_user_notification_preference(
                user_id=999,
                notification_type="ride_matched",
                channel="push",
                db=db,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_422_on_invalid_notification_type(self):
        from fastapi import HTTPException
        from app.api.v1.admin import admin_reset_user_notification_preference

        user = _make_user()
        db = _mock_db(user=user)

        with pytest.raises(HTTPException) as exc_info:
            await admin_reset_user_notification_preference(
                user_id=42,
                notification_type="fake_type",
                channel="push",
                db=db,
            )

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_422_on_invalid_channel(self):
        from fastapi import HTTPException
        from app.api.v1.admin import admin_reset_user_notification_preference

        user = _make_user()
        db = _mock_db(user=user)

        with pytest.raises(HTTPException) as exc_info:
            await admin_reset_user_notification_preference(
                user_id=42,
                notification_type="ride_matched",
                channel="pigeon",
                db=db,
            )

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_all_valid_channels_accepted(self):
        from app.api.v1.admin import admin_reset_user_notification_preference

        for channel in ("push", "sms", "email"):
            user = _make_user()
            db = _mock_db(user=user)

            with patch(
                "app.services.notification_preferences.reset_preference",
                new_callable=AsyncMock,
                return_value=True,
            ):
                await admin_reset_user_notification_preference(
                    user_id=42,
                    notification_type="ride_matched",
                    channel=channel,
                    db=db,
                )
