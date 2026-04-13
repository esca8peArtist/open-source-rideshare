"""Unit tests for user profile and driver profile endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.driver import DriverProfile
from app.models.user import User, UserRole
from app.schemas.auth import UserProfileResponse, UserProfileUpdate
from app.schemas.driver import (
    DriverProfileCreate,
    DriverProfileResponse,
    DriverProfileUpdate,
)


def _make_user(
    user_id=1,
    phone="+15551234567",
    name="Test User",
    email="test@example.com",
    role=UserRole.RIDER,
    is_active=True,
    phone_verified=False,
):
    user = MagicMock(spec=User)
    user.id = user_id
    user.phone = phone
    user.name = name
    user.email = email
    user.role = role
    user.is_active = is_active
    user.phone_verified = phone_verified
    return user


def _make_driver_profile(
    profile_id=1,
    user_id=2,
    vehicle_type="sedan",
    vehicle_make="Toyota",
    vehicle_model="Camry",
    vehicle_year=2022,
    vehicle_color="Silver",
    license_plate="TEST-123",
    is_online=False,
    is_approved=True,
    rating_avg=4.8,
    total_trips=50,
):
    profile = MagicMock(spec=DriverProfile)
    profile.id = profile_id
    profile.user_id = user_id
    profile.vehicle_type = vehicle_type
    profile.vehicle_make = vehicle_make
    profile.vehicle_model = vehicle_model
    profile.vehicle_year = vehicle_year
    profile.vehicle_color = vehicle_color
    profile.license_plate = license_plate
    profile.is_online = is_online
    profile.is_approved = is_approved
    profile.rating_avg = rating_avg
    profile.total_trips = total_trips
    return profile


class TestUserProfileResponseSchema:
    def test_from_user_model(self):
        user = _make_user()
        resp = UserProfileResponse(
            id=user.id,
            phone=user.phone,
            email=user.email,
            name=user.name,
            role=user.role.value,
            is_active=user.is_active,
            phone_verified=user.phone_verified,
        )
        assert resp.id == 1
        assert resp.phone == "+15551234567"
        assert resp.name == "Test User"
        assert resp.email == "test@example.com"
        assert resp.role == "rider"
        assert resp.is_active is True
        assert resp.phone_verified is False

    def test_null_email(self):
        resp = UserProfileResponse(
            id=1,
            phone="+15551234567",
            email=None,
            name="No Email",
            role="rider",
            is_active=True,
            phone_verified=False,
        )
        assert resp.email is None

    def test_driver_role(self):
        resp = UserProfileResponse(
            id=2,
            phone="+15559999999",
            email="driver@test.com",
            name="Driver User",
            role="driver",
            is_active=True,
            phone_verified=True,
        )
        assert resp.role == "driver"
        assert resp.phone_verified is True


class TestUserProfileUpdateSchema:
    def test_partial_update_name_only(self):
        update = UserProfileUpdate(name="New Name")
        assert update.name == "New Name"
        assert update.email is None

    def test_partial_update_email_only(self):
        update = UserProfileUpdate(email="new@example.com")
        assert update.name is None
        assert update.email == "new@example.com"

    def test_full_update(self):
        update = UserProfileUpdate(name="New Name", email="new@example.com")
        assert update.name == "New Name"
        assert update.email == "new@example.com"

    def test_empty_update(self):
        update = UserProfileUpdate()
        assert update.name is None
        assert update.email is None


class TestDriverProfileUpdateSchema:
    def test_partial_update_vehicle_type(self):
        update = DriverProfileUpdate(vehicle_type="suv")
        assert update.vehicle_type == "suv"
        assert update.vehicle_make is None

    def test_partial_update_license_plate(self):
        update = DriverProfileUpdate(license_plate="NEW-456")
        assert update.license_plate == "NEW-456"
        assert update.vehicle_year is None

    def test_full_update(self):
        update = DriverProfileUpdate(
            vehicle_type="suv",
            vehicle_make="Honda",
            vehicle_model="CR-V",
            vehicle_year=2024,
            vehicle_color="Blue",
            license_plate="NEW-789",
        )
        assert update.vehicle_type == "suv"
        assert update.vehicle_make == "Honda"
        assert update.vehicle_model == "CR-V"
        assert update.vehicle_year == 2024
        assert update.vehicle_color == "Blue"
        assert update.license_plate == "NEW-789"

    def test_exclude_unset(self):
        update = DriverProfileUpdate(vehicle_color="Red")
        dumped = update.model_dump(exclude_unset=True)
        assert dumped == {"vehicle_color": "Red"}


class TestDriverProfileResponseSchema:
    def test_from_driver_profile(self):
        profile = _make_driver_profile()
        resp = DriverProfileResponse(
            id=profile.id,
            user_id=profile.user_id,
            vehicle_type=profile.vehicle_type,
            vehicle_make=profile.vehicle_make,
            vehicle_model=profile.vehicle_model,
            vehicle_year=profile.vehicle_year,
            vehicle_color=profile.vehicle_color,
            license_plate=profile.license_plate,
            is_online=profile.is_online,
            is_approved=profile.is_approved,
            rating_avg=profile.rating_avg,
            total_trips=profile.total_trips,
        )
        assert resp.id == 1
        assert resp.user_id == 2
        assert resp.vehicle_type == "sedan"
        assert resp.vehicle_make == "Toyota"
        assert resp.vehicle_model == "Camry"
        assert resp.vehicle_year == 2022
        assert resp.vehicle_color == "Silver"
        assert resp.license_plate == "TEST-123"
        assert resp.is_online is False
        assert resp.is_approved is True
        assert resp.rating_avg == 4.8
        assert resp.total_trips == 50


class TestGetMeEndpointLogic:
    """Tests for GET /auth/me endpoint logic."""

    def test_returns_current_user_fields(self):
        user = _make_user(
            user_id=42,
            name="Anya",
            phone="+15550001111",
            email="anya@example.com",
            role=UserRole.RIDER,
        )
        assert user.id == 42
        assert user.name == "Anya"
        assert user.phone == "+15550001111"
        assert user.email == "anya@example.com"

    def test_driver_user_can_get_profile(self):
        user = _make_user(role=UserRole.DRIVER, name="Driver Person")
        assert user.role == UserRole.DRIVER
        assert user.name == "Driver Person"


class TestUpdateMeEndpointLogic:
    """Tests for PUT /auth/me endpoint logic — field update behavior."""

    def test_name_update_applied(self):
        user = _make_user(name="Old Name")
        req = UserProfileUpdate(name="New Name")
        if req.name is not None:
            user.name = req.name
        assert user.name == "New Name"

    def test_email_update_applied(self):
        user = _make_user(email="old@example.com")
        req = UserProfileUpdate(email="new@example.com")
        if req.email is not None:
            user.email = req.email
        assert user.email == "new@example.com"

    def test_null_fields_not_applied(self):
        user = _make_user(name="Keep This", email="keep@example.com")
        req = UserProfileUpdate()
        if req.name is not None:
            user.name = req.name
        if req.email is not None:
            user.email = req.email
        assert user.name == "Keep This"
        assert user.email == "keep@example.com"

    def test_partial_update_preserves_other_field(self):
        user = _make_user(name="Original", email="original@example.com")
        req = UserProfileUpdate(name="Updated")
        if req.name is not None:
            user.name = req.name
        if req.email is not None:
            user.email = req.email
        assert user.name == "Updated"
        assert user.email == "original@example.com"


class TestDriverProfileUpdateLogic:
    """Tests for PUT /driver/profile endpoint logic — field update behavior."""

    def test_partial_update_applies_only_set_fields(self):
        profile = _make_driver_profile(vehicle_color="Silver", license_plate="OLD-111")
        req = DriverProfileUpdate(vehicle_color="Red")
        update_data = req.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(profile, field, value)
        assert profile.vehicle_color == "Red"
        assert profile.license_plate == "OLD-111"

    def test_full_update_applies_all_fields(self):
        profile = _make_driver_profile()
        req = DriverProfileUpdate(
            vehicle_type="suv",
            vehicle_make="Honda",
            vehicle_model="CR-V",
            vehicle_year=2024,
            vehicle_color="Blue",
            license_plate="NEW-789",
        )
        update_data = req.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(profile, field, value)
        assert profile.vehicle_type == "suv"
        assert profile.vehicle_make == "Honda"
        assert profile.vehicle_model == "CR-V"
        assert profile.vehicle_year == 2024
        assert profile.vehicle_color == "Blue"
        assert profile.license_plate == "NEW-789"

    def test_empty_update_changes_nothing(self):
        profile = _make_driver_profile(vehicle_color="Silver")
        req = DriverProfileUpdate()
        update_data = req.model_dump(exclude_unset=True)
        assert update_data == {}
        for field, value in update_data.items():
            setattr(profile, field, value)
        assert profile.vehicle_color == "Silver"


# ---------------------------------------------------------------------------
# Async endpoint function tests — call route handlers with mocked deps
# ---------------------------------------------------------------------------


def _mock_db(scalar_return=None):
    """Create a mock AsyncSession whose execute().scalar_one_or_none() returns *scalar_return*."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = scalar_return
    db.execute.return_value = result_mock
    return db


class TestGetMeEndpoint:
    """Async tests for GET /auth/me handler."""

    @pytest.mark.asyncio
    async def test_returns_user_object(self):
        from app.api.v1.auth import get_me

        user = _make_user(user_id=7, name="Anya")
        result = await get_me(user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_returns_driver_user(self):
        from app.api.v1.auth import get_me

        user = _make_user(role=UserRole.DRIVER, name="Driver Anya")
        result = await get_me(user=user)
        assert result.role == UserRole.DRIVER


class TestUpdateMeEndpoint:
    """Async tests for PUT /auth/me handler."""

    @pytest.mark.asyncio
    async def test_updates_name(self):
        from app.api.v1.auth import update_me

        user = _make_user(name="Old")
        db = _mock_db()
        result = await update_me(req=UserProfileUpdate(name="New"), user=user, db=db)
        assert result.name == "New"
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(user)

    @pytest.mark.asyncio
    async def test_updates_email(self):
        from app.api.v1.auth import update_me

        user = _make_user(email="old@test.com")
        db = _mock_db()
        result = await update_me(req=UserProfileUpdate(email="new@test.com"), user=user, db=db)
        assert result.email == "new@test.com"

    @pytest.mark.asyncio
    async def test_updates_both_fields(self):
        from app.api.v1.auth import update_me

        user = _make_user(name="Old", email="old@test.com")
        db = _mock_db()
        result = await update_me(
            req=UserProfileUpdate(name="New", email="new@test.com"), user=user, db=db
        )
        assert result.name == "New"
        assert result.email == "new@test.com"

    @pytest.mark.asyncio
    async def test_empty_update_preserves_fields(self):
        from app.api.v1.auth import update_me

        user = _make_user(name="Keep", email="keep@test.com")
        db = _mock_db()
        result = await update_me(req=UserProfileUpdate(), user=user, db=db)
        assert result.name == "Keep"
        assert result.email == "keep@test.com"
        db.commit.assert_awaited_once()


class TestGetDriverProfileEndpoint:
    """Async tests for GET /driver/profile handler."""

    @pytest.mark.asyncio
    async def test_returns_existing_profile(self):
        from app.api.v1.drivers import get_profile

        user = _make_user(user_id=2, role=UserRole.DRIVER)
        profile = _make_driver_profile(user_id=2)
        db = _mock_db(scalar_return=profile)

        result = await get_profile(user=user, db=db)
        assert result is profile

    @pytest.mark.asyncio
    async def test_raises_404_when_no_profile(self):
        from app.api.v1.drivers import get_profile

        user = _make_user(user_id=99, role=UserRole.DRIVER)
        db = _mock_db(scalar_return=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_profile(user=user, db=db)
        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()


class TestUpdateDriverProfileEndpoint:
    """Async tests for PUT /driver/profile handler."""

    @pytest.mark.asyncio
    async def test_partial_update(self):
        from app.api.v1.drivers import update_profile

        user = _make_user(user_id=2, role=UserRole.DRIVER)
        profile = _make_driver_profile(user_id=2, vehicle_color="Silver")
        db = _mock_db(scalar_return=profile)

        result = await update_profile(
            req=DriverProfileUpdate(vehicle_color="Red"), user=user, db=db
        )
        assert result.vehicle_color == "Red"
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(profile)

    @pytest.mark.asyncio
    async def test_full_update(self):
        from app.api.v1.drivers import update_profile

        user = _make_user(user_id=2, role=UserRole.DRIVER)
        profile = _make_driver_profile(user_id=2)
        db = _mock_db(scalar_return=profile)

        req = DriverProfileUpdate(
            vehicle_type="suv",
            vehicle_make="Honda",
            vehicle_model="CR-V",
            vehicle_year=2024,
            vehicle_color="Blue",
            license_plate="NEW-789",
        )
        result = await update_profile(req=req, user=user, db=db)
        assert result.vehicle_type == "suv"
        assert result.vehicle_make == "Honda"
        assert result.license_plate == "NEW-789"

    @pytest.mark.asyncio
    async def test_raises_404_when_no_profile(self):
        from app.api.v1.drivers import update_profile

        user = _make_user(user_id=99, role=UserRole.DRIVER)
        db = _mock_db(scalar_return=None)

        with pytest.raises(HTTPException) as exc_info:
            await update_profile(
                req=DriverProfileUpdate(vehicle_color="Red"), user=user, db=db
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_empty_update_commits(self):
        from app.api.v1.drivers import update_profile

        user = _make_user(user_id=2, role=UserRole.DRIVER)
        profile = _make_driver_profile(user_id=2, vehicle_color="Silver")
        db = _mock_db(scalar_return=profile)

        result = await update_profile(req=DriverProfileUpdate(), user=user, db=db)
        assert result.vehicle_color == "Silver"
        db.commit.assert_awaited_once()


class TestCreateDriverProfileEndpoint:
    """Async tests for POST /driver/profile handler."""

    @pytest.mark.asyncio
    async def test_creates_new_profile(self):
        from app.api.v1.drivers import create_profile

        user = _make_user(user_id=5, role=UserRole.DRIVER)
        db = _mock_db(scalar_return=None)  # no existing profile

        req = DriverProfileCreate(
            vehicle_type="sedan",
            vehicle_make="Toyota",
            vehicle_model="Camry",
            vehicle_year=2022,
            vehicle_color="Silver",
            license_plate="ABC-123",
            license_number="DL123456",
        )
        result = await create_profile(req=req, user=user, db=db)
        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_409_if_profile_exists(self):
        from app.api.v1.drivers import create_profile

        user = _make_user(user_id=5, role=UserRole.DRIVER)
        existing = _make_driver_profile(user_id=5)
        db = _mock_db(scalar_return=existing)

        req = DriverProfileCreate(
            vehicle_type="sedan",
            vehicle_make="Toyota",
            vehicle_model="Camry",
            vehicle_year=2022,
            vehicle_color="Silver",
            license_plate="ABC-123",
            license_number="DL123456",
        )
        with pytest.raises(HTTPException) as exc_info:
            await create_profile(req=req, user=user, db=db)
        assert exc_info.value.status_code == 409
        assert "already exists" in exc_info.value.detail.lower()
