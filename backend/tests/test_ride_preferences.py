"""Comprehensive unit tests for the ride preferences feature.

Covers:
- Model: RidePreference fields, TemperaturePreference enum
- Schema: RidePreferenceUpdate (partial), RidePreferenceResponse
- Service: get_preferences (create on miss), update_preferences (partial),
           get_preferences_for_ride (None when absent)
- Endpoints: GET /me/ride-preferences, PUT /me/ride-preferences,
             GET /rides/{ride_id}/rider-preferences

All tests are pure unit tests — no database required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ride_preference import RidePreference, TemperaturePreference
from app.schemas.ride_preference import RidePreferenceResponse, RidePreferenceUpdate
from app.services.ride_preferences import (
    get_preferences,
    get_preferences_for_ride,
    update_preferences,
)


# ===========================================================================
# Helpers
# ===========================================================================


def _make_prefs(
    user_id: int = 1,
    quiet_ride: bool = False,
    music_off: bool = False,
    temperature_preference: TemperaturePreference = TemperaturePreference.NO_PREFERENCE,
    pet_friendly: bool = False,
    extra_luggage: bool = False,
    accessibility_vehicle_needed: bool = False,
    notes: str | None = None,
) -> MagicMock:
    p = MagicMock(spec=RidePreference)
    p.id = 1
    p.user_id = user_id
    p.quiet_ride = quiet_ride
    p.music_off = music_off
    p.temperature_preference = temperature_preference
    p.pet_friendly = pet_friendly
    p.extra_luggage = extra_luggage
    p.accessibility_vehicle_needed = accessibility_vehicle_needed
    p.notes = notes
    p.updated_at = datetime.now(timezone.utc)
    return p


def _make_db(row=None) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute.return_value = result
    return db


# ===========================================================================
# Model tests
# ===========================================================================


class TestRidePreferenceModel:
    def test_temperature_preference_enum_values(self):
        assert TemperaturePreference.NO_PREFERENCE == "no_preference"
        assert TemperaturePreference.WARM == "warm"
        assert TemperaturePreference.COOL == "cool"

    def test_model_has_all_fields(self):
        p = RidePreference()
        for field in [
            "user_id", "quiet_ride", "music_off", "temperature_preference",
            "pet_friendly", "extra_luggage", "accessibility_vehicle_needed", "notes",
        ]:
            assert hasattr(p, field), f"Missing field: {field}"

    def test_tablename(self):
        assert RidePreference.__tablename__ == "ride_preferences"


# ===========================================================================
# Schema tests
# ===========================================================================


class TestRidePreferenceUpdateSchema:
    def test_all_fields_optional(self):
        """Empty update is valid — all fields optional."""
        update = RidePreferenceUpdate()
        assert update.quiet_ride is None
        assert update.music_off is None
        assert update.temperature_preference is None
        assert update.pet_friendly is None
        assert update.extra_luggage is None
        assert update.accessibility_vehicle_needed is None
        assert update.notes is None

    def test_partial_update_quiet_only(self):
        update = RidePreferenceUpdate(quiet_ride=True)
        assert update.quiet_ride is True
        assert update.music_off is None

    def test_notes_max_length_200(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RidePreferenceUpdate(notes="x" * 201)

    def test_notes_exactly_200_ok(self):
        update = RidePreferenceUpdate(notes="x" * 200)
        assert len(update.notes) == 200

    def test_temperature_preference_validation(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RidePreferenceUpdate(temperature_preference="hot")

    def test_valid_temperature_preferences(self):
        for val in ["no_preference", "warm", "cool"]:
            update = RidePreferenceUpdate(temperature_preference=val)
            assert update.temperature_preference == TemperaturePreference(val)


class TestRidePreferenceResponseSchema:
    def test_response_from_attributes(self):
        prefs = _make_prefs(user_id=5, quiet_ride=True)
        resp = RidePreferenceResponse.model_validate(prefs)
        assert resp.user_id == 5
        assert resp.quiet_ride is True
        assert resp.music_off is False
        assert resp.temperature_preference == TemperaturePreference.NO_PREFERENCE

    def test_response_accessibility_flag(self):
        prefs = _make_prefs(user_id=3, accessibility_vehicle_needed=True)
        resp = RidePreferenceResponse.model_validate(prefs)
        assert resp.accessibility_vehicle_needed is True

    def test_response_notes(self):
        prefs = _make_prefs(notes="Please don't talk")
        resp = RidePreferenceResponse.model_validate(prefs)
        assert resp.notes == "Please don't talk"

    def test_response_notes_none(self):
        prefs = _make_prefs(notes=None)
        resp = RidePreferenceResponse.model_validate(prefs)
        assert resp.notes is None


# ===========================================================================
# Service: get_preferences
# ===========================================================================


class TestGetPreferences:
    @pytest.mark.asyncio
    async def test_returns_existing_row(self):
        """Returns existing row without creating a new one."""
        prefs = _make_prefs(user_id=1)
        db = _make_db(row=prefs)

        result = await get_preferences(db, user_id=1)

        assert result is prefs
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_default_row_when_absent(self):
        """Creates and returns a default RidePreference when none exists."""
        db = _make_db(row=None)

        result = await get_preferences(db, user_id=42)

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert isinstance(added, RidePreference)
        assert added.user_id == 42
        assert added.quiet_ride is False
        assert added.accessibility_vehicle_needed is False
        assert added.temperature_preference == TemperaturePreference.NO_PREFERENCE
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_created_default_has_no_notes(self):
        """Default preferences have notes=None."""
        db = _make_db(row=None)

        await get_preferences(db, user_id=7)

        added = db.add.call_args[0][0]
        assert added.notes is None


# ===========================================================================
# Service: update_preferences
# ===========================================================================


class TestUpdatePreferences:
    @pytest.mark.asyncio
    async def test_updates_provided_fields(self):
        """Only provided (non-None) fields are updated."""
        prefs = _make_prefs(user_id=1, quiet_ride=False, music_off=False)
        db = _make_db(row=prefs)

        updates = RidePreferenceUpdate(quiet_ride=True)
        result = await update_preferences(db, user_id=1, updates=updates)

        assert prefs.quiet_ride is True
        assert prefs.music_off is False  # unchanged
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_flush_when_nothing_changed(self):
        """No flush if the update values are identical to existing values."""
        prefs = _make_prefs(user_id=1, quiet_ride=True)
        db = _make_db(row=prefs)

        updates = RidePreferenceUpdate(quiet_ride=True)
        result = await update_preferences(db, user_id=1, updates=updates)

        db.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_update_no_flush(self):
        """All-None update doesn't flush."""
        prefs = _make_prefs(user_id=1)
        db = _make_db(row=prefs)

        updates = RidePreferenceUpdate()
        await update_preferences(db, user_id=1, updates=updates)

        db.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_updates_multiple_fields(self):
        """Multiple fields can be updated in one call."""
        prefs = _make_prefs(user_id=1)
        db = _make_db(row=prefs)

        updates = RidePreferenceUpdate(
            quiet_ride=True,
            music_off=True,
            temperature_preference=TemperaturePreference.COOL,
            notes="Sleepy",
        )
        await update_preferences(db, user_id=1, updates=updates)

        assert prefs.quiet_ride is True
        assert prefs.music_off is True
        assert prefs.temperature_preference == TemperaturePreference.COOL
        assert prefs.notes == "Sleepy"

    @pytest.mark.asyncio
    async def test_update_creates_row_if_absent(self):
        """update_preferences creates default row if none exists, then applies update."""
        db = _make_db(row=None)

        updates = RidePreferenceUpdate(pet_friendly=True)

        with patch(
            "app.services.ride_preferences.get_preferences",
            new_callable=AsyncMock,
        ) as mock_get:
            prefs = _make_prefs(user_id=1, pet_friendly=False)
            mock_get.return_value = prefs

            result = await update_preferences(db, user_id=1, updates=updates)

        mock_get.assert_called_once_with(db, 1)
        assert prefs.pet_friendly is True

    @pytest.mark.asyncio
    async def test_accessibility_flag_update(self):
        """accessibility_vehicle_needed can be set to True."""
        prefs = _make_prefs(user_id=1, accessibility_vehicle_needed=False)
        db = _make_db(row=prefs)

        updates = RidePreferenceUpdate(accessibility_vehicle_needed=True)
        await update_preferences(db, user_id=1, updates=updates)

        assert prefs.accessibility_vehicle_needed is True


# ===========================================================================
# Service: get_preferences_for_ride
# ===========================================================================


class TestGetPreferencesForRide:
    @pytest.mark.asyncio
    async def test_returns_existing_prefs(self):
        """Returns the rider's prefs when they exist."""
        prefs = _make_prefs(user_id=10)
        db = _make_db(row=prefs)

        result = await get_preferences_for_ride(db, rider_user_id=10)

        assert result is prefs

    @pytest.mark.asyncio
    async def test_returns_none_when_absent(self):
        """Returns None when the rider has not set preferences."""
        db = _make_db(row=None)

        result = await get_preferences_for_ride(db, rider_user_id=99)

        assert result is None
        # Must NOT create a new row (read-only)
        db.add.assert_not_called()


# ===========================================================================
# Endpoint tests
# ===========================================================================


class TestRidePreferenceEndpoints:
    @pytest.mark.asyncio
    async def test_get_my_preferences_returns_response(self):
        from app.api.v1.ride_preferences import get_my_ride_preferences

        user = MagicMock()
        user.id = 1
        db = AsyncMock()
        prefs = _make_prefs(user_id=1)

        with patch(
            "app.api.v1.ride_preferences.get_preferences",
            new_callable=AsyncMock,
            return_value=prefs,
        ) as mock_get:
            result = await get_my_ride_preferences(user=user, db=db)

        mock_get.assert_called_once_with(db, 1)
        assert isinstance(result, RidePreferenceResponse)
        assert result.user_id == 1

    @pytest.mark.asyncio
    async def test_update_my_preferences_applies_changes(self):
        from app.api.v1.ride_preferences import update_my_ride_preferences

        user = MagicMock()
        user.id = 2
        db = AsyncMock()
        updates = RidePreferenceUpdate(quiet_ride=True)
        prefs = _make_prefs(user_id=2, quiet_ride=True)

        with patch(
            "app.api.v1.ride_preferences.update_preferences",
            new_callable=AsyncMock,
            return_value=prefs,
        ) as mock_update:
            result = await update_my_ride_preferences(updates=updates, user=user, db=db)

        mock_update.assert_called_once_with(db, 2, updates)
        assert result.quiet_ride is True

    @pytest.mark.asyncio
    async def test_driver_get_rider_preferences_not_assigned(self):
        """Returns 403 if driver is not assigned to the ride."""
        from fastapi import HTTPException

        from app.api.v1.ride_preferences import get_rider_preferences_for_ride

        user = MagicMock()
        user.id = 99  # driver user_id

        ride = MagicMock()
        ride.id = 1
        ride.driver_id = 5  # different driver
        ride.rider_id = 10

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = ride
        db.execute.return_value = result

        with pytest.raises(HTTPException) as exc_info:
            await get_rider_preferences_for_ride(ride_id=1, user=user, db=db)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_driver_get_rider_preferences_ride_not_found(self):
        """Returns 404 if ride doesn't exist."""
        from fastapi import HTTPException

        from app.api.v1.ride_preferences import get_rider_preferences_for_ride

        user = MagicMock()
        user.id = 5

        db = _make_db(row=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_rider_preferences_for_ride(ride_id=999, user=user, db=db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_driver_get_rider_preferences_success(self):
        """Driver can read rider preferences for their assigned ride."""
        from app.api.v1.ride_preferences import get_rider_preferences_for_ride

        user = MagicMock()
        user.id = 5  # driver user_id

        ride = MagicMock()
        ride.id = 1
        ride.driver_id = 5  # same driver
        ride.rider_id = 10

        prefs = _make_prefs(user_id=10, quiet_ride=True)

        db = AsyncMock()
        ride_result = MagicMock()
        ride_result.scalar_one_or_none.return_value = ride
        prefs_result = MagicMock()
        prefs_result.scalar_one_or_none.return_value = prefs
        db.execute.side_effect = [ride_result, prefs_result]

        result = await get_rider_preferences_for_ride(ride_id=1, user=user, db=db)

        assert result is not None
        assert isinstance(result, RidePreferenceResponse)
        assert result.quiet_ride is True

    @pytest.mark.asyncio
    async def test_driver_get_rider_preferences_none_when_not_set(self):
        """Returns None when rider hasn't set preferences."""
        from app.api.v1.ride_preferences import get_rider_preferences_for_ride

        user = MagicMock()
        user.id = 5

        ride = MagicMock()
        ride.id = 1
        ride.driver_id = 5
        ride.rider_id = 10

        db = AsyncMock()
        ride_result = MagicMock()
        ride_result.scalar_one_or_none.return_value = ride
        prefs_result = MagicMock()
        prefs_result.scalar_one_or_none.return_value = None
        db.execute.side_effect = [ride_result, prefs_result]

        result = await get_rider_preferences_for_ride(ride_id=1, user=user, db=db)

        assert result is None
