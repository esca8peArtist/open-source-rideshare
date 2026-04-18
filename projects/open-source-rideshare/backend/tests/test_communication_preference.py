"""Tests for rider communication preference.

Covers:
1. Model column
   - communication_preference on RidePreference: exists, default NO_PREFERENCE
   - CommunicationPreference enum: four expected values

2. Schemas
   - RidePreferenceUpdate: communication_preference optional, default None
   - RidePreferenceUpdate: accepts each valid enum value
   - RidePreferenceUpdate: rejects invalid value
   - RidePreferenceResponse: communication_preference required, round-trips all values

3. Service logic
   - update_preferences sets communication_preference and flushes
   - update_preferences no-op when communication_preference unchanged
   - update_preferences partial: other fields unaffected
   - update_preferences can set communication_preference alongside boolean flags

4. Schema round-trip
   - All four enum values survive model_validate
   - partial update with only communication_preference excludes other fields

All tests are pure unit tests — no database required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.ride_preference import CommunicationPreference, RidePreference
from app.schemas.ride_preference import RidePreferenceResponse, RidePreferenceUpdate
from app.services.ride_preferences import update_preferences


# ===========================================================================
# Helpers
# ===========================================================================


def _make_ride_preference(
    user_id: int = 1,
    communication_preference: CommunicationPreference = CommunicationPreference.NO_PREFERENCE,
    hearing_impairment: bool = False,
    has_service_animal: bool = False,
    visual_impairment: bool = False,
) -> MagicMock:
    p = MagicMock(spec=RidePreference)
    p.id = 1
    p.user_id = user_id
    p.quiet_ride = False
    p.music_off = False
    p.temperature_preference = "no_preference"
    p.pet_friendly = False
    p.extra_luggage = False
    p.accessibility_vehicle_needed = False
    p.hearing_impairment = hearing_impairment
    p.has_service_animal = has_service_animal
    p.visual_impairment = visual_impairment
    p.pool_opt_out = False
    p.communication_preference = communication_preference
    p.notes = None
    p.updated_at = datetime.now(timezone.utc)
    return p


def _make_db(row=None) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute.return_value = result
    return db


# ===========================================================================
# 1. Model column
# ===========================================================================


class TestCommunicationPreferenceModel:
    def test_communication_preference_column_exists(self):
        p = RidePreference()
        assert hasattr(p, "communication_preference")

    def test_communication_preference_column_default_no_preference(self):
        col = RidePreference.__table__.c.communication_preference
        assert col.default.arg == CommunicationPreference.NO_PREFERENCE

    def test_enum_has_no_preference(self):
        assert CommunicationPreference.NO_PREFERENCE == "no_preference"

    def test_enum_has_text(self):
        assert CommunicationPreference.TEXT == "text"

    def test_enum_has_app(self):
        assert CommunicationPreference.APP == "app"

    def test_enum_has_verbal(self):
        assert CommunicationPreference.VERBAL == "verbal"

    def test_enum_has_exactly_four_values(self):
        assert len(CommunicationPreference) == 4


# ===========================================================================
# 2. Schemas
# ===========================================================================


class TestRidePreferenceUpdateCommunicationPreference:
    def test_communication_preference_optional_default_none(self):
        update = RidePreferenceUpdate()
        assert update.communication_preference is None

    def test_accepts_no_preference(self):
        update = RidePreferenceUpdate(communication_preference=CommunicationPreference.NO_PREFERENCE)
        assert update.communication_preference == CommunicationPreference.NO_PREFERENCE

    def test_accepts_text(self):
        update = RidePreferenceUpdate(communication_preference=CommunicationPreference.TEXT)
        assert update.communication_preference == CommunicationPreference.TEXT

    def test_accepts_app(self):
        update = RidePreferenceUpdate(communication_preference=CommunicationPreference.APP)
        assert update.communication_preference == CommunicationPreference.APP

    def test_accepts_verbal(self):
        update = RidePreferenceUpdate(communication_preference=CommunicationPreference.VERBAL)
        assert update.communication_preference == CommunicationPreference.VERBAL

    def test_accepts_string_value_text(self):
        update = RidePreferenceUpdate(communication_preference="text")
        assert update.communication_preference == CommunicationPreference.TEXT

    def test_rejects_invalid_value(self):
        with pytest.raises(Exception):
            RidePreferenceUpdate(communication_preference="carrier_pigeon")

    def test_partial_update_other_fields_unaffected(self):
        update = RidePreferenceUpdate(communication_preference=CommunicationPreference.APP)
        assert update.quiet_ride is None
        assert update.music_off is None
        assert update.hearing_impairment is None
        assert update.visual_impairment is None


class TestRidePreferenceResponseCommunicationPreference:
    def test_no_preference_in_response(self):
        pref = _make_ride_preference(communication_preference=CommunicationPreference.NO_PREFERENCE)
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.communication_preference == CommunicationPreference.NO_PREFERENCE

    def test_text_in_response(self):
        pref = _make_ride_preference(communication_preference=CommunicationPreference.TEXT)
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.communication_preference == CommunicationPreference.TEXT

    def test_app_in_response(self):
        pref = _make_ride_preference(communication_preference=CommunicationPreference.APP)
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.communication_preference == CommunicationPreference.APP

    def test_verbal_in_response(self):
        pref = _make_ride_preference(communication_preference=CommunicationPreference.VERBAL)
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.communication_preference == CommunicationPreference.VERBAL

    def test_response_includes_accessibility_flags_and_communication(self):
        pref = _make_ride_preference(
            communication_preference=CommunicationPreference.TEXT,
            hearing_impairment=True,
            has_service_animal=False,
            visual_impairment=True,
        )
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.communication_preference == CommunicationPreference.TEXT
        assert resp.hearing_impairment is True
        assert resp.has_service_animal is False
        assert resp.visual_impairment is True


# ===========================================================================
# 3. Service logic
# ===========================================================================


class TestRidePreferencesServiceCommunicationPreference:
    @pytest.mark.asyncio
    async def test_update_sets_communication_preference_and_flushes(self):
        pref = _make_ride_preference(
            communication_preference=CommunicationPreference.NO_PREFERENCE
        )
        db = _make_db(row=pref)

        await update_preferences(
            db,
            user_id=1,
            updates=RidePreferenceUpdate(
                communication_preference=CommunicationPreference.TEXT
            ),
        )

        assert pref.communication_preference == CommunicationPreference.TEXT
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_no_flush_when_communication_preference_unchanged(self):
        pref = _make_ride_preference(
            communication_preference=CommunicationPreference.APP
        )
        db = _make_db(row=pref)

        await update_preferences(
            db,
            user_id=1,
            updates=RidePreferenceUpdate(
                communication_preference=CommunicationPreference.APP
            ),
        )

        db.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_communication_does_not_touch_other_fields(self):
        pref = _make_ride_preference(
            communication_preference=CommunicationPreference.NO_PREFERENCE,
            hearing_impairment=True,
            visual_impairment=True,
        )
        db = _make_db(row=pref)

        await update_preferences(
            db,
            user_id=1,
            updates=RidePreferenceUpdate(
                communication_preference=CommunicationPreference.VERBAL
            ),
        )

        assert pref.communication_preference == CommunicationPreference.VERBAL
        assert pref.hearing_impairment is True
        assert pref.visual_impairment is True

    @pytest.mark.asyncio
    async def test_update_communication_and_boolean_flags_together(self):
        pref = _make_ride_preference(
            communication_preference=CommunicationPreference.NO_PREFERENCE,
            hearing_impairment=False,
        )
        db = _make_db(row=pref)

        await update_preferences(
            db,
            user_id=1,
            updates=RidePreferenceUpdate(
                communication_preference=CommunicationPreference.APP,
                hearing_impairment=True,
            ),
        )

        assert pref.communication_preference == CommunicationPreference.APP
        assert pref.hearing_impairment is True
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_to_verbal_from_text(self):
        pref = _make_ride_preference(
            communication_preference=CommunicationPreference.TEXT
        )
        db = _make_db(row=pref)

        await update_preferences(
            db,
            user_id=1,
            updates=RidePreferenceUpdate(
                communication_preference=CommunicationPreference.VERBAL
            ),
        )

        assert pref.communication_preference == CommunicationPreference.VERBAL
        db.flush.assert_called_once()


# ===========================================================================
# 4. Schema round-trip
# ===========================================================================


class TestCommunicationPreferenceSchemaRoundTrip:
    def test_no_preference_survives_model_validate(self):
        pref = _make_ride_preference(
            communication_preference=CommunicationPreference.NO_PREFERENCE
        )
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.communication_preference == CommunicationPreference.NO_PREFERENCE

    def test_text_survives_model_validate(self):
        pref = _make_ride_preference(communication_preference=CommunicationPreference.TEXT)
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.communication_preference == CommunicationPreference.TEXT

    def test_app_survives_model_validate(self):
        pref = _make_ride_preference(communication_preference=CommunicationPreference.APP)
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.communication_preference == CommunicationPreference.APP

    def test_verbal_survives_model_validate(self):
        pref = _make_ride_preference(communication_preference=CommunicationPreference.VERBAL)
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.communication_preference == CommunicationPreference.VERBAL

    def test_partial_update_only_communication_preference_excludes_other_fields(self):
        update = RidePreferenceUpdate(
            communication_preference=CommunicationPreference.APP
        )
        dumped = update.model_dump(exclude_none=True)
        assert dumped == {"communication_preference": CommunicationPreference.APP}
        assert "quiet_ride" not in dumped
        assert "hearing_impairment" not in dumped
        assert "visual_impairment" not in dumped

    def test_update_with_communication_and_other_fields(self):
        update = RidePreferenceUpdate(
            communication_preference=CommunicationPreference.VERBAL,
            quiet_ride=True,
        )
        dumped = update.model_dump(exclude_none=True)
        assert dumped["communication_preference"] == CommunicationPreference.VERBAL
        assert dumped["quiet_ride"] is True
        assert len(dumped) == 2
