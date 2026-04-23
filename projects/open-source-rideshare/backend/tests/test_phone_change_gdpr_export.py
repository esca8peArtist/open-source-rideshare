"""Unit tests for phone number change and GDPR data export endpoints.

Covers:
  POST /auth/me/change-phone
    - 200 on correct password, new phone not already taken
    - 400 when password is wrong
    - 400 when new_phone equals current phone
    - 409 when new_phone already registered
    - phone field updated, phone_verified reset to False
    - schema: new_phone min_length=5 enforced
    - drivers and admins can change phone

  GET /auth/me/data-export
    - returns dict with expected top-level keys
    - calls export_user_data with correct user_id
    - profile section contains user fields
    - graceful empty response when user not found in service

  account_data_export service (export_user_data)
    - returns empty dict when user not found
    - profile keys present
    - rides_as_rider and rides_as_driver lists present
    - saved_locations list present
    - ride_preferences None when not set
    - notifications list present
    - datetime values serialised as ISO strings (or None)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.user import User, UserRole
from app.schemas.auth import ChangePhoneRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    user_id: int = 1,
    phone: str = "+15551234567",
    role: UserRole = UserRole.RIDER,
    is_active: bool = True,
    password_hash: str = "$2b$12$fakehash",
    phone_verified: bool = True,
) -> MagicMock:
    u = MagicMock(spec=User)
    u.id = user_id
    u.phone = phone
    u.role = role
    u.is_active = is_active
    u.password_hash = password_hash
    u.phone_verified = phone_verified
    return u


def _mock_db(scalar_return=None) -> AsyncMock:
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = scalar_return
    db.execute.return_value = result_mock
    return db


# ---------------------------------------------------------------------------
# ChangePhoneRequest schema
# ---------------------------------------------------------------------------


class TestChangePhoneSchema:
    def test_valid_request(self):
        req = ChangePhoneRequest(password="mypass", new_phone="+15559999999")
        assert req.new_phone == "+15559999999"

    def test_new_phone_too_short(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            ChangePhoneRequest(password="mypass", new_phone="123")

    def test_new_phone_exactly_5_chars(self):
        req = ChangePhoneRequest(password="mypass", new_phone="12345")
        assert len(req.new_phone) == 5

    def test_new_phone_too_long(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            ChangePhoneRequest(password="mypass", new_phone="+1" + "9" * 20)

    def test_password_required(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            ChangePhoneRequest(new_phone="+15559999999")


# ---------------------------------------------------------------------------
# change_phone endpoint
# ---------------------------------------------------------------------------


class TestChangePhoneEndpoint:
    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_success(self, mock_verify):
        from app.api.v1.auth import change_phone

        user = _make_user(phone="+15551111111")
        db = _mock_db(scalar_return=None)  # new phone not taken
        req = ChangePhoneRequest(password="correct", new_phone="+15552222222")

        result = await change_phone(req, user=user, db=db)

        assert result == {"status": "phone updated"}
        assert user.phone == "+15552222222"
        assert user.phone_verified is False
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=False)
    async def test_wrong_password(self, mock_verify):
        from fastapi import HTTPException

        from app.api.v1.auth import change_phone

        user = _make_user()
        db = _mock_db()
        req = ChangePhoneRequest(password="wrong", new_phone="+15552222222")

        with pytest.raises(HTTPException) as exc_info:
            await change_phone(req, user=user, db=db)

        assert exc_info.value.status_code == 400
        assert "password" in exc_info.value.detail.lower()
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_same_phone_rejected(self, mock_verify):
        from fastapi import HTTPException

        from app.api.v1.auth import change_phone

        user = _make_user(phone="+15551111111")
        db = _mock_db()
        req = ChangePhoneRequest(password="correct", new_phone="+15551111111")

        with pytest.raises(HTTPException) as exc_info:
            await change_phone(req, user=user, db=db)

        assert exc_info.value.status_code == 400
        assert "same" in exc_info.value.detail.lower()
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_phone_already_taken(self, mock_verify):
        from fastapi import HTTPException

        from app.api.v1.auth import change_phone

        user = _make_user(phone="+15551111111")
        other_user = MagicMock()
        db = _mock_db(scalar_return=other_user)  # new phone already registered
        req = ChangePhoneRequest(password="correct", new_phone="+15553333333")

        with pytest.raises(HTTPException) as exc_info:
            await change_phone(req, user=user, db=db)

        assert exc_info.value.status_code == 409
        assert "already in use" in exc_info.value.detail.lower()
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_phone_verified_reset_to_false(self, mock_verify):
        from app.api.v1.auth import change_phone

        user = _make_user(phone_verified=True)
        db = _mock_db(scalar_return=None)
        req = ChangePhoneRequest(password="correct", new_phone="+15554444444")

        await change_phone(req, user=user, db=db)

        assert user.phone_verified is False

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_driver_can_change_phone(self, mock_verify):
        from app.api.v1.auth import change_phone

        user = _make_user(role=UserRole.DRIVER, phone="+15551111111")
        db = _mock_db(scalar_return=None)
        req = ChangePhoneRequest(password="correct", new_phone="+15555555555")

        result = await change_phone(req, user=user, db=db)

        assert result == {"status": "phone updated"}

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_admin_can_change_phone(self, mock_verify):
        from app.api.v1.auth import change_phone

        user = _make_user(role=UserRole.ADMIN, phone="+15551111111")
        db = _mock_db(scalar_return=None)
        req = ChangePhoneRequest(password="correct", new_phone="+15556666666")

        result = await change_phone(req, user=user, db=db)

        assert result == {"status": "phone updated"}

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_phone_field_updated_on_user(self, mock_verify):
        from app.api.v1.auth import change_phone

        user = _make_user(phone="+15550000000")
        db = _mock_db(scalar_return=None)
        req = ChangePhoneRequest(password="correct", new_phone="+15557777777")

        await change_phone(req, user=user, db=db)

        assert user.phone == "+15557777777"


# ---------------------------------------------------------------------------
# data_export endpoint
# ---------------------------------------------------------------------------


class TestDataExportEndpoint:
    @pytest.mark.asyncio
    @patch("app.services.account_data_export.export_user_data", new_callable=AsyncMock)
    async def test_calls_service_with_user_id(self, mock_export):
        from app.api.v1.auth import data_export

        mock_export.return_value = {"profile": {}, "rides_as_rider": []}
        user = _make_user(user_id=42)
        db = AsyncMock()

        result = await data_export(user=user, db=db)

        mock_export.assert_awaited_once_with(42, db)
        assert "profile" in result

    @pytest.mark.asyncio
    @patch("app.services.account_data_export.export_user_data", new_callable=AsyncMock)
    async def test_returns_service_result(self, mock_export):
        from app.api.v1.auth import data_export

        payload = {
            "profile": {"id": 1, "name": "Alice"},
            "rides_as_rider": [{"id": 10}],
            "rides_as_driver": [],
            "saved_locations": [],
            "ride_preferences": None,
            "notifications": [],
        }
        mock_export.return_value = payload
        user = _make_user()
        db = AsyncMock()

        result = await data_export(user=user, db=db)

        assert result == payload

    @pytest.mark.asyncio
    @patch("app.services.account_data_export.export_user_data", new_callable=AsyncMock)
    async def test_top_level_keys_present(self, mock_export):
        from app.api.v1.auth import data_export

        mock_export.return_value = {
            "profile": {},
            "rides_as_rider": [],
            "rides_as_driver": [],
            "saved_locations": [],
            "ride_preferences": None,
            "notifications": [],
        }
        user = _make_user()
        result = await data_export(user=user, db=AsyncMock())

        assert set(result.keys()) == {
            "profile",
            "rides_as_rider",
            "rides_as_driver",
            "saved_locations",
            "ride_preferences",
            "notifications",
        }


# ---------------------------------------------------------------------------
# export_user_data service
# ---------------------------------------------------------------------------


def _make_async_result(rows=None, scalar=None):
    """Build a mock execute() result that handles both .scalars().all() and .scalar_one_or_none()."""
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = rows if rows is not None else []
    mock_result.scalars.return_value = mock_scalars
    mock_result.scalar_one_or_none.return_value = scalar
    return mock_result


class TestExportUserDataService:
    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_user_not_found(self):
        from app.services.account_data_export import export_user_data

        db = AsyncMock()
        # First execute call (user lookup) returns None
        db.execute.return_value = _make_async_result(scalar=None)

        result = await export_user_data(99, db)

        assert result == {}

    @pytest.mark.asyncio
    async def test_profile_keys_present(self):
        from datetime import datetime, timezone

        from app.services.account_data_export import export_user_data

        user = MagicMock(spec=User)
        user.id = 1
        user.name = "Alice"
        user.phone = "+15551234567"
        user.email = "alice@example.com"
        user.role = UserRole.RIDER
        user.is_active = True
        user.phone_verified = True
        user.referral_code = "REFABC"
        user.referred_by = None
        user.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        user.updated_at = datetime(2025, 6, 1, tzinfo=timezone.utc)

        db = AsyncMock()
        calls = [
            _make_async_result(scalar=user),   # user lookup
            _make_async_result(rows=[]),        # rides as rider
            _make_async_result(rows=[]),        # rides as driver
            _make_async_result(rows=[]),        # saved locations
            _make_async_result(scalar=None),    # ride preferences
            _make_async_result(rows=[]),        # notifications
        ]
        db.execute.side_effect = calls

        result = await export_user_data(1, db)

        assert "profile" in result
        assert result["profile"]["name"] == "Alice"
        assert result["profile"]["phone"] == "+15551234567"
        assert result["profile"]["email"] == "alice@example.com"

    @pytest.mark.asyncio
    async def test_ride_lists_present(self):
        from datetime import datetime, timezone

        from app.services.account_data_export import export_user_data

        user = MagicMock(spec=User)
        user.id = 1
        user.name = "Alice"
        user.phone = "+15551234567"
        user.email = None
        user.role = UserRole.RIDER
        user.is_active = True
        user.phone_verified = False
        user.referral_code = None
        user.referred_by = None
        user.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        user.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

        ride = MagicMock()
        ride.id = 10
        ride.status = MagicMock(value="completed")
        ride.pickup_address = "123 Main St"
        ride.dropoff_address = "456 Oak Ave"
        ride.estimated_fare = 12.5
        ride.actual_fare = 12.5
        ride.distance_km = 5.0
        ride.duration_min = 15.0
        ride.tip_amount = 2.0
        ride.promo_discount = 0.0
        ride.is_pool = False
        ride.requested_at = datetime(2025, 3, 1, tzinfo=timezone.utc)
        ride.completed_at = datetime(2025, 3, 1, tzinfo=timezone.utc)
        ride.cancelled_at = None
        ride.rider_rating = 5
        ride.driver_rating = 4

        db = AsyncMock()
        db.execute.side_effect = [
            _make_async_result(scalar=user),
            _make_async_result(rows=[ride]),   # rides as rider
            _make_async_result(rows=[]),       # rides as driver
            _make_async_result(rows=[]),       # saved locations
            _make_async_result(scalar=None),   # preferences
            _make_async_result(rows=[]),       # notifications
        ]

        result = await export_user_data(1, db)

        assert len(result["rides_as_rider"]) == 1
        assert result["rides_as_rider"][0]["id"] == 10
        assert result["rides_as_rider"][0]["pickup_address"] == "123 Main St"
        assert result["rides_as_driver"] == []

    @pytest.mark.asyncio
    async def test_ride_preferences_none_when_not_set(self):
        from datetime import datetime, timezone

        from app.services.account_data_export import export_user_data

        user = MagicMock(spec=User)
        user.id = 1
        user.name = "Bob"
        user.phone = "+15559999999"
        user.email = None
        user.role = UserRole.DRIVER
        user.is_active = True
        user.phone_verified = True
        user.referral_code = None
        user.referred_by = None
        user.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        user.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

        db = AsyncMock()
        db.execute.side_effect = [
            _make_async_result(scalar=user),
            _make_async_result(rows=[]),
            _make_async_result(rows=[]),
            _make_async_result(rows=[]),
            _make_async_result(scalar=None),  # no ride preferences
            _make_async_result(rows=[]),
        ]

        result = await export_user_data(1, db)

        assert result["ride_preferences"] is None

    @pytest.mark.asyncio
    async def test_ride_preferences_included_when_set(self):
        from datetime import datetime, timezone

        from app.models.ride_preference import CommunicationPreference, RidePreference, TemperaturePreference
        from app.services.account_data_export import export_user_data

        user = MagicMock(spec=User)
        user.id = 1
        user.name = "Carol"
        user.phone = "+15558888888"
        user.email = None
        user.role = UserRole.RIDER
        user.is_active = True
        user.phone_verified = True
        user.referral_code = None
        user.referred_by = None
        user.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        user.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

        pref = MagicMock(spec=RidePreference)
        pref.quiet_ride = True
        pref.music_off = False
        pref.temperature_preference = TemperaturePreference.COOL
        pref.pet_friendly = False
        pref.extra_luggage = False
        pref.accessibility_vehicle_needed = False
        pref.hearing_impairment = False
        pref.has_service_animal = False
        pref.visual_impairment = False
        pref.pool_opt_out = True
        pref.communication_preference = CommunicationPreference.TEXT
        pref.notes = "quiet please"

        db = AsyncMock()
        db.execute.side_effect = [
            _make_async_result(scalar=user),
            _make_async_result(rows=[]),
            _make_async_result(rows=[]),
            _make_async_result(rows=[]),
            _make_async_result(scalar=pref),
            _make_async_result(rows=[]),
        ]

        result = await export_user_data(1, db)

        assert result["ride_preferences"] is not None
        assert result["ride_preferences"]["quiet_ride"] is True
        assert result["ride_preferences"]["pool_opt_out"] is True
        assert result["ride_preferences"]["notes"] == "quiet please"

    @pytest.mark.asyncio
    async def test_notifications_included(self):
        from datetime import datetime, timezone

        from app.models.notification import NotificationLog, NotificationStatus
        from app.services.account_data_export import export_user_data

        user = MagicMock(spec=User)
        user.id = 1
        user.name = "Dave"
        user.phone = "+15557777777"
        user.email = None
        user.role = UserRole.RIDER
        user.is_active = True
        user.phone_verified = True
        user.referral_code = None
        user.referred_by = None
        user.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        user.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

        notif = MagicMock(spec=NotificationLog)
        notif.id = 5
        notif.notification_type = "ride_matched"
        notif.channel = "push"
        notif.title = "Ride matched"
        notif.body = "Your driver is on the way"
        notif.status = NotificationStatus.SENT
        notif.is_read = True
        notif.created_at = datetime(2025, 4, 1, tzinfo=timezone.utc)
        notif.read_at = datetime(2025, 4, 1, tzinfo=timezone.utc)

        db = AsyncMock()
        db.execute.side_effect = [
            _make_async_result(scalar=user),
            _make_async_result(rows=[]),
            _make_async_result(rows=[]),
            _make_async_result(rows=[]),
            _make_async_result(scalar=None),
            _make_async_result(rows=[notif]),
        ]

        result = await export_user_data(1, db)

        assert len(result["notifications"]) == 1
        assert result["notifications"][0]["type"] == "ride_matched"
        assert result["notifications"][0]["is_read"] is True

    @pytest.mark.asyncio
    async def test_datetime_serialised_as_iso_string(self):
        from datetime import datetime, timezone

        from app.services.account_data_export import export_user_data

        user = MagicMock(spec=User)
        user.id = 1
        user.name = "Eve"
        user.phone = "+15556666666"
        user.email = None
        user.role = UserRole.RIDER
        user.is_active = True
        user.phone_verified = False
        user.referral_code = None
        user.referred_by = None
        ts = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        user.created_at = ts
        user.updated_at = ts

        db = AsyncMock()
        db.execute.side_effect = [
            _make_async_result(scalar=user),
            _make_async_result(rows=[]),
            _make_async_result(rows=[]),
            _make_async_result(rows=[]),
            _make_async_result(scalar=None),
            _make_async_result(rows=[]),
        ]

        result = await export_user_data(1, db)

        created = result["profile"]["created_at"]
        assert isinstance(created, str)
        assert "2025-06-15" in created

    @pytest.mark.asyncio
    async def test_saved_locations_included(self):
        from datetime import datetime, timezone

        from app.models.saved_location import LocationLabel, SavedLocation
        from app.services.account_data_export import export_user_data

        user = MagicMock(spec=User)
        user.id = 1
        user.name = "Frank"
        user.phone = "+15555555555"
        user.email = None
        user.role = UserRole.RIDER
        user.is_active = True
        user.phone_verified = True
        user.referral_code = None
        user.referred_by = None
        user.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        user.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

        loc = MagicMock(spec=SavedLocation)
        loc.id = 3
        loc.label = LocationLabel.HOME
        loc.name = "Home"
        loc.address = "789 Elm St"
        loc.lat = 37.7749
        loc.lng = -122.4194
        loc.created_at = datetime(2025, 2, 1, tzinfo=timezone.utc)

        db = AsyncMock()
        db.execute.side_effect = [
            _make_async_result(scalar=user),
            _make_async_result(rows=[]),
            _make_async_result(rows=[]),
            _make_async_result(rows=[loc]),
            _make_async_result(scalar=None),
            _make_async_result(rows=[]),
        ]

        result = await export_user_data(1, db)

        assert len(result["saved_locations"]) == 1
        assert result["saved_locations"][0]["address"] == "789 Elm St"
        assert result["saved_locations"][0]["label"] == "home"
