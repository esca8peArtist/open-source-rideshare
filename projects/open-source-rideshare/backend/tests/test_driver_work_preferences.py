"""Tests for the Driver Work Preferences feature.

Service layer (async, mocked DB):
  1.  get_preferences — creates default row when none exists
  2.  get_preferences — returns existing row without creating a new one
  3.  update_preferences — writes only the supplied non-None fields
  4.  update_preferences — preserves existing values for omitted fields
  5.  update_preferences — creates row via get_preferences if none exists
  6.  reset_preferences — restores all fields to platform defaults
  7.  reset_preferences — works even when no prior row existed (creates then resets)

Schema validation:
  8.  DriverWorkPreferenceUpdate — empty update (all None) is valid
  9.  DriverWorkPreferenceUpdate — valid full update accepted
  10. DriverWorkPreferenceUpdate — min > max raises ValueError
  11. DriverWorkPreferenceUpdate — min == max is valid (no constraint violation)
  12. DriverWorkPreferenceUpdate — notes max_length=200 enforced
  13. DriverWorkPreferenceUpdate — min_trip_distance_km < 0 rejected
  14. DriverWorkPreferenceUpdate — max_trip_distance_km > 500 rejected
  15. DriverWorkPreferenceUpdate — boolean fields accept True/False
  16. DriverWorkPreferenceResponse — from_attributes works correctly
  17. DriverWorkPreferenceResponse — notes field can be None
  18. DriverWorkPreferenceResponse — distance fields can be None

API layer (service functions patched):
  19. GET /drivers/me/work-preferences — returns preference response
  20. PUT /drivers/me/work-preferences — calls update_preferences and returns result
  21. DELETE /drivers/me/work-preferences — calls reset_preferences and returns defaults
  22. GET /admin/drivers/{driver_id}/work-preferences — admin reads any driver's prefs
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.models.driver_work_preference import DriverWorkPreference
from app.schemas.driver_work_preference import (
    DriverWorkPreferenceResponse,
    DriverWorkPreferenceUpdate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_prefs(
    driver_id: int = 1,
    accept_pool_rides: bool = True,
    accept_pet_riders: bool = True,
    accept_extra_luggage: bool = True,
    min_trip_distance_km: float | None = None,
    max_trip_distance_km: float | None = None,
    prefer_long_distance: bool = False,
    prefer_language_matched: bool = False,
    notes: str | None = None,
    pref_id: int = 10,
) -> DriverWorkPreference:
    prefs = MagicMock(spec=DriverWorkPreference)
    prefs.id = pref_id
    prefs.driver_id = driver_id
    prefs.accept_pool_rides = accept_pool_rides
    prefs.accept_pet_riders = accept_pet_riders
    prefs.accept_extra_luggage = accept_extra_luggage
    prefs.min_trip_distance_km = min_trip_distance_km
    prefs.max_trip_distance_km = max_trip_distance_km
    prefs.prefer_long_distance = prefer_long_distance
    prefs.prefer_language_matched = prefer_language_matched
    prefs.notes = notes
    prefs.updated_at = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
    return prefs


def _scalar_result(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _mock_user(user_id: int = 1):
    user = MagicMock()
    user.id = user_id
    user.is_admin = False
    return user


# ---------------------------------------------------------------------------
# Service layer tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_preferences_creates_default_row_when_none_exists():
    """1. get_preferences creates default row when none exists."""
    from app.services.driver_work_preference import get_preferences

    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(None))

    prefs = await get_preferences(db, driver_id=1)

    db.add.assert_called_once()
    db.flush.assert_called_once()
    # The added object should be a DriverWorkPreference with default values
    added = db.add.call_args[0][0]
    assert added.driver_id == 1
    assert added.accept_pool_rides is True
    assert added.accept_pet_riders is True
    assert added.accept_extra_luggage is True
    assert added.min_trip_distance_km is None
    assert added.max_trip_distance_km is None
    assert added.prefer_long_distance is False
    assert added.prefer_language_matched is False
    assert added.notes is None


@pytest.mark.asyncio
async def test_get_preferences_returns_existing_row():
    """2. get_preferences returns existing row without creating a new one."""
    from app.services.driver_work_preference import get_preferences

    existing = _make_prefs(driver_id=3, accept_pool_rides=False)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(existing))

    result = await get_preferences(db, driver_id=3)

    db.add.assert_not_called()
    assert result.accept_pool_rides is False
    assert result.driver_id == 3


@pytest.mark.asyncio
async def test_update_preferences_writes_only_supplied_fields():
    """3. update_preferences writes only the supplied non-None fields."""
    from app.services.driver_work_preference import update_preferences

    existing = _make_prefs(driver_id=1, accept_pool_rides=True, accept_pet_riders=True)
    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(existing))

    updates = DriverWorkPreferenceUpdate(accept_pool_rides=False)
    result = await update_preferences(db, driver_id=1, updates=updates)

    # accept_pool_rides should be updated
    assert result.accept_pool_rides is False
    # accept_pet_riders was not in the update — unchanged
    assert result.accept_pet_riders is True


@pytest.mark.asyncio
async def test_update_preferences_preserves_omitted_fields():
    """4. update_preferences preserves existing values for omitted fields."""
    from app.services.driver_work_preference import update_preferences

    existing = _make_prefs(
        driver_id=2,
        min_trip_distance_km=5.0,
        max_trip_distance_km=50.0,
        notes="prefer city centre",
    )
    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(existing))

    # Only update accept_extra_luggage — all other fields should stay
    updates = DriverWorkPreferenceUpdate(accept_extra_luggage=False)
    result = await update_preferences(db, driver_id=2, updates=updates)

    assert result.min_trip_distance_km == 5.0
    assert result.max_trip_distance_km == 50.0
    assert result.notes == "prefer city centre"
    assert result.accept_extra_luggage is False


@pytest.mark.asyncio
async def test_update_preferences_creates_row_if_none_exists():
    """5. update_preferences creates row via get_preferences if none exists."""
    from app.services.driver_work_preference import update_preferences

    db = AsyncMock()
    db.flush = AsyncMock()
    # First execute (in get_preferences) returns None → will create; subsequent call
    # returns the newly created mock
    db.execute = AsyncMock(return_value=_scalar_result(None))

    updates = DriverWorkPreferenceUpdate(prefer_long_distance=True)
    await update_preferences(db, driver_id=5, updates=updates)

    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_reset_preferences_restores_all_defaults():
    """6. reset_preferences restores all fields to platform defaults."""
    from app.services.driver_work_preference import reset_preferences

    customised = _make_prefs(
        driver_id=1,
        accept_pool_rides=False,
        accept_pet_riders=False,
        accept_extra_luggage=False,
        min_trip_distance_km=10.0,
        max_trip_distance_km=30.0,
        prefer_long_distance=True,
        prefer_language_matched=True,
        notes="special notes",
    )
    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(customised))

    result = await reset_preferences(db, driver_id=1)

    assert result.accept_pool_rides is True
    assert result.accept_pet_riders is True
    assert result.accept_extra_luggage is True
    assert result.min_trip_distance_km is None
    assert result.max_trip_distance_km is None
    assert result.prefer_long_distance is False
    assert result.prefer_language_matched is False
    assert result.notes is None


@pytest.mark.asyncio
async def test_reset_preferences_creates_and_resets_when_no_prior_row():
    """7. reset_preferences works even when no prior row existed."""
    from app.services.driver_work_preference import reset_preferences

    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(None))

    await reset_preferences(db, driver_id=99)

    # Row is created by get_preferences, then reset applies defaults
    db.add.assert_called_once()


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_schema_empty_update_is_valid():
    """8. DriverWorkPreferenceUpdate — empty update (all None) is valid."""
    update = DriverWorkPreferenceUpdate()
    assert update.accept_pool_rides is None
    assert update.min_trip_distance_km is None


def test_schema_full_valid_update_accepted():
    """9. DriverWorkPreferenceUpdate — valid full update accepted."""
    update = DriverWorkPreferenceUpdate(
        accept_pool_rides=False,
        accept_pet_riders=True,
        accept_extra_luggage=False,
        min_trip_distance_km=2.0,
        max_trip_distance_km=40.0,
        prefer_long_distance=True,
        prefer_language_matched=True,
        notes="prefer highway routes",
    )
    assert update.accept_pool_rides is False
    assert update.min_trip_distance_km == 2.0
    assert update.max_trip_distance_km == 40.0
    assert update.notes == "prefer highway routes"


def test_schema_min_greater_than_max_raises_error():
    """10. DriverWorkPreferenceUpdate — min > max raises ValueError."""
    with pytest.raises(ValidationError) as exc_info:
        DriverWorkPreferenceUpdate(
            min_trip_distance_km=50.0,
            max_trip_distance_km=10.0,
        )
    assert "min_trip_distance_km" in str(exc_info.value)


def test_schema_min_equals_max_is_valid():
    """11. DriverWorkPreferenceUpdate — min == max is valid (no constraint violation)."""
    update = DriverWorkPreferenceUpdate(
        min_trip_distance_km=20.0,
        max_trip_distance_km=20.0,
    )
    assert update.min_trip_distance_km == update.max_trip_distance_km == 20.0


def test_schema_notes_too_long_rejected():
    """12. DriverWorkPreferenceUpdate — notes max_length=200 enforced."""
    with pytest.raises(ValidationError):
        DriverWorkPreferenceUpdate(notes="x" * 201)


def test_schema_min_negative_rejected():
    """13. DriverWorkPreferenceUpdate — min_trip_distance_km < 0 rejected."""
    with pytest.raises(ValidationError):
        DriverWorkPreferenceUpdate(min_trip_distance_km=-1.0)


def test_schema_max_over_limit_rejected():
    """14. DriverWorkPreferenceUpdate — max_trip_distance_km > 500 rejected."""
    with pytest.raises(ValidationError):
        DriverWorkPreferenceUpdate(max_trip_distance_km=501.0)


def test_schema_boolean_fields_accept_values():
    """15. DriverWorkPreferenceUpdate — boolean fields accept True/False."""
    update = DriverWorkPreferenceUpdate(
        accept_pool_rides=True,
        prefer_long_distance=False,
        prefer_language_matched=True,
    )
    assert update.accept_pool_rides is True
    assert update.prefer_long_distance is False
    assert update.prefer_language_matched is True


def test_response_from_attributes_works():
    """16. DriverWorkPreferenceResponse — from_attributes works correctly."""
    prefs = _make_prefs(
        driver_id=7,
        accept_pool_rides=False,
        accept_pet_riders=True,
        accept_extra_luggage=False,
        min_trip_distance_km=3.0,
        max_trip_distance_km=25.0,
        prefer_long_distance=True,
        prefer_language_matched=False,
        notes="city only",
    )
    resp = DriverWorkPreferenceResponse.model_validate(prefs)
    assert resp.driver_id == 7
    assert resp.accept_pool_rides is False
    assert resp.accept_pet_riders is True
    assert resp.min_trip_distance_km == 3.0
    assert resp.max_trip_distance_km == 25.0
    assert resp.notes == "city only"


def test_response_notes_can_be_none():
    """17. DriverWorkPreferenceResponse — notes field can be None."""
    prefs = _make_prefs(notes=None)
    resp = DriverWorkPreferenceResponse.model_validate(prefs)
    assert resp.notes is None


def test_response_distance_fields_can_be_none():
    """18. DriverWorkPreferenceResponse — distance fields can be None."""
    prefs = _make_prefs(min_trip_distance_km=None, max_trip_distance_km=None)
    resp = DriverWorkPreferenceResponse.model_validate(prefs)
    assert resp.min_trip_distance_km is None
    assert resp.max_trip_distance_km is None


# ---------------------------------------------------------------------------
# API layer tests — call handler functions directly (service patched)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_get_my_work_preferences():
    """19. GET /drivers/me/work-preferences — returns preference response."""
    from app.api.v1.driver_work_preferences import get_my_work_preferences

    prefs = _make_prefs(driver_id=4, accept_pool_rides=True)
    user = _mock_user(user_id=4)

    with patch(
        "app.api.v1.driver_work_preferences.get_preferences",
        new=AsyncMock(return_value=prefs),
    ):
        db = AsyncMock()
        result = await get_my_work_preferences(user=user, db=db)

    assert result.driver_id == 4
    assert result.accept_pool_rides is True


@pytest.mark.asyncio
async def test_api_update_my_work_preferences():
    """20. PUT /drivers/me/work-preferences — calls update_preferences and returns result."""
    from app.api.v1.driver_work_preferences import update_my_work_preferences

    updated = _make_prefs(
        driver_id=4,
        accept_pool_rides=False,
        prefer_long_distance=True,
        min_trip_distance_km=5.0,
        max_trip_distance_km=80.0,
    )
    user = _mock_user(user_id=4)
    body = DriverWorkPreferenceUpdate(
        accept_pool_rides=False,
        prefer_long_distance=True,
        min_trip_distance_km=5.0,
        max_trip_distance_km=80.0,
    )

    with patch(
        "app.api.v1.driver_work_preferences.update_preferences",
        new=AsyncMock(return_value=updated),
    ):
        db = AsyncMock()
        result = await update_my_work_preferences(body=body, user=user, db=db)

    assert result.accept_pool_rides is False
    assert result.prefer_long_distance is True
    assert result.min_trip_distance_km == 5.0


@pytest.mark.asyncio
async def test_api_reset_my_work_preferences():
    """21. DELETE /drivers/me/work-preferences — calls reset_preferences and returns defaults."""
    from app.api.v1.driver_work_preferences import reset_my_work_preferences

    defaults = _make_prefs(
        driver_id=4,
        accept_pool_rides=True,
        accept_pet_riders=True,
        accept_extra_luggage=True,
        prefer_long_distance=False,
        prefer_language_matched=False,
    )
    user = _mock_user(user_id=4)

    with patch(
        "app.api.v1.driver_work_preferences.reset_preferences",
        new=AsyncMock(return_value=defaults),
    ):
        db = AsyncMock()
        result = await reset_my_work_preferences(user=user, db=db)

    assert result.accept_pool_rides is True
    assert result.prefer_long_distance is False
    assert result.notes is None


@pytest.mark.asyncio
async def test_api_admin_get_driver_work_preferences():
    """22. GET /admin/drivers/{driver_id}/work-preferences — admin reads any driver's prefs."""
    from app.api.v1.driver_work_preferences import admin_get_driver_work_preferences

    prefs = _make_prefs(driver_id=9, accept_pet_riders=False)

    with patch(
        "app.api.v1.driver_work_preferences.get_preferences",
        new=AsyncMock(return_value=prefs),
    ):
        db = AsyncMock()
        result = await admin_get_driver_work_preferences(driver_id=9, db=db)

    assert result.driver_id == 9
    assert result.accept_pet_riders is False
