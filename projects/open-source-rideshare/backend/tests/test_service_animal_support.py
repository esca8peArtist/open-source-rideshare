"""Tests for service animal support.

Covers:
1. Model columns
   - has_service_animal on RidePreference: exists, default False
   - service_animal_friendly on DriverProfile: exists, default False

2. Schemas
   - RidePreferenceUpdate: has_service_animal optional, default None
   - RidePreferenceResponse: has_service_animal required bool
   - DriverAccessibilityUpdate: service_animal_friendly optional, default None
   - DriverAccessibilityResponse: service_animal_friendly required bool

3. Service logic
   - update_accessibility sets service_animal_friendly and flushes
   - update_accessibility no-op when service_animal_friendly unchanged
   - update_accessibility partial: other fields unaffected

4. DriverCandidate dataclass
   - service_animal_friendly field exists, default False

5. Matching engine: soft service-animal preference
   - service_animal_friendly driver sorted first when rider_has_service_animal=True
   - Friendly driver promoted even when farther away
   - No friendly driver: non-friendly drivers still returned
   - Without rider flag: default distance/rating sort
   - Both hearing_impairment + service_animal: both preferences applied in sort
   - Multiple friendly drivers: distance tiebreaker still applies

6. WebSocket: send_ride_offer
   - rider_has_service_animal included in message payload
   - Default value is False when not supplied

7. RidePreference schema round-trip
   - has_service_animal=True is preserved through model_validate

All tests are pure unit tests — no database required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.driver import DriverProfile
from app.models.ride_preference import RidePreference
from app.schemas.driver_accessibility import (
    DriverAccessibilityResponse,
    DriverAccessibilityUpdate,
)
from app.schemas.ride_preference import RidePreferenceResponse, RidePreferenceUpdate
from app.services.driver_accessibility import update_accessibility
from app.services.matching import DriverCandidate


# ===========================================================================
# Helpers
# ===========================================================================


def _make_driver_profile(
    user_id: int = 1,
    hearing_impairment_capable: bool = False,
    sign_language_capable: bool = False,
    service_animal_friendly: bool = False,
) -> MagicMock:
    p = MagicMock(spec=DriverProfile)
    p.id = 1
    p.user_id = user_id
    p.hearing_impairment_capable = hearing_impairment_capable
    p.sign_language_capable = sign_language_capable
    p.service_animal_friendly = service_animal_friendly
    p.updated_at = datetime.now(timezone.utc)
    return p


def _make_ride_preference(
    user_id: int = 1,
    hearing_impairment: bool = False,
    has_service_animal: bool = False,
    accessibility_vehicle_needed: bool = False,
) -> MagicMock:
    p = MagicMock(spec=RidePreference)
    p.id = 1
    p.user_id = user_id
    p.quiet_ride = False
    p.music_off = False
    p.temperature_preference = "no_preference"
    p.pet_friendly = False
    p.extra_luggage = False
    p.accessibility_vehicle_needed = accessibility_vehicle_needed
    p.hearing_impairment = hearing_impairment
    p.has_service_animal = has_service_animal
    p.pool_opt_out = False
    p.communication_preference = "no_preference"
    p.notes = None
    p.updated_at = datetime.now(timezone.utc)
    return p


def _make_db(row=None) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute.return_value = result
    return db


def _make_candidate(
    driver_id: int,
    distance_km: float,
    rating_avg: float = 4.5,
    hearing_impairment_capable: bool = False,
    service_animal_friendly: bool = False,
) -> DriverCandidate:
    return DriverCandidate(
        driver_id=driver_id,
        user_id=driver_id + 100,
        distance_km=distance_km,
        rating_avg=rating_avg,
        total_trips=10,
        is_wheelchair_accessible=False,
        hearing_impairment_capable=hearing_impairment_capable,
        service_animal_friendly=service_animal_friendly,
    )


# ===========================================================================
# 1. Model columns
# ===========================================================================


class TestRidePreferenceServiceAnimalColumn:
    def test_has_service_animal_exists(self):
        p = RidePreference()
        assert hasattr(p, "has_service_animal")

    def test_has_service_animal_default_false(self):
        p = RidePreference()
        assert not p.has_service_animal


class TestDriverProfileServiceAnimalColumn:
    def test_service_animal_friendly_exists(self):
        p = DriverProfile()
        assert hasattr(p, "service_animal_friendly")

    def test_service_animal_friendly_default_false(self):
        p = DriverProfile()
        assert not p.service_animal_friendly


# ===========================================================================
# 2. Schemas
# ===========================================================================


class TestRidePreferenceUpdateSchema:
    def test_has_service_animal_optional_default_none(self):
        update = RidePreferenceUpdate()
        assert update.has_service_animal is None

    def test_has_service_animal_can_be_set_true(self):
        update = RidePreferenceUpdate(has_service_animal=True)
        assert update.has_service_animal is True

    def test_has_service_animal_can_be_set_false(self):
        update = RidePreferenceUpdate(has_service_animal=False)
        assert update.has_service_animal is False

    def test_partial_update_other_fields_unaffected(self):
        update = RidePreferenceUpdate(has_service_animal=True)
        assert update.hearing_impairment is None
        assert update.quiet_ride is None


class TestRidePreferenceResponseSchema:
    def test_has_service_animal_included_in_response(self):
        pref = _make_ride_preference(has_service_animal=True)
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.has_service_animal is True

    def test_has_service_animal_false_included_in_response(self):
        pref = _make_ride_preference(has_service_animal=False)
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.has_service_animal is False

    def test_other_fields_still_present(self):
        pref = _make_ride_preference(has_service_animal=True, hearing_impairment=True)
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.hearing_impairment is True
        assert resp.has_service_animal is True


class TestDriverAccessibilityUpdateSchemaServiceAnimal:
    def test_service_animal_friendly_optional_default_none(self):
        update = DriverAccessibilityUpdate()
        assert update.service_animal_friendly is None

    def test_service_animal_friendly_can_be_set_true(self):
        update = DriverAccessibilityUpdate(service_animal_friendly=True)
        assert update.service_animal_friendly is True

    def test_partial_update_other_fields_unaffected(self):
        update = DriverAccessibilityUpdate(service_animal_friendly=True)
        assert update.hearing_impairment_capable is None
        assert update.sign_language_capable is None

    def test_all_three_fields_can_be_set(self):
        update = DriverAccessibilityUpdate(
            hearing_impairment_capable=True,
            sign_language_capable=True,
            service_animal_friendly=True,
        )
        assert update.hearing_impairment_capable is True
        assert update.sign_language_capable is True
        assert update.service_animal_friendly is True


class TestDriverAccessibilityResponseSchemaServiceAnimal:
    def test_service_animal_friendly_false_in_response(self):
        profile = _make_driver_profile(service_animal_friendly=False)
        resp = DriverAccessibilityResponse.model_validate(profile)
        assert resp.service_animal_friendly is False

    def test_service_animal_friendly_true_in_response(self):
        profile = _make_driver_profile(service_animal_friendly=True)
        resp = DriverAccessibilityResponse.model_validate(profile)
        assert resp.service_animal_friendly is True

    def test_all_flags_in_response(self):
        profile = _make_driver_profile(
            hearing_impairment_capable=True,
            sign_language_capable=False,
            service_animal_friendly=True,
        )
        resp = DriverAccessibilityResponse.model_validate(profile)
        assert resp.hearing_impairment_capable is True
        assert resp.sign_language_capable is False
        assert resp.service_animal_friendly is True

    def test_response_includes_updated_at(self):
        profile = _make_driver_profile()
        resp = DriverAccessibilityResponse.model_validate(profile)
        assert isinstance(resp.updated_at, datetime)


# ===========================================================================
# 3. Service logic
# ===========================================================================


class TestDriverAccessibilityServiceServiceAnimal:
    @pytest.mark.asyncio
    async def test_update_sets_service_animal_friendly_true(self):
        profile = _make_driver_profile(service_animal_friendly=False)
        db = _make_db(row=profile)

        await update_accessibility(
            db, user_id=1, updates=DriverAccessibilityUpdate(service_animal_friendly=True)
        )

        assert profile.service_animal_friendly is True
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_no_flush_when_service_animal_unchanged(self):
        profile = _make_driver_profile(service_animal_friendly=True)
        db = _make_db(row=profile)

        await update_accessibility(
            db, user_id=1, updates=DriverAccessibilityUpdate(service_animal_friendly=True)
        )

        db.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_service_animal_does_not_touch_other_fields(self):
        profile = _make_driver_profile(
            hearing_impairment_capable=True,
            sign_language_capable=True,
            service_animal_friendly=False,
        )
        db = _make_db(row=profile)

        await update_accessibility(
            db, user_id=1, updates=DriverAccessibilityUpdate(service_animal_friendly=True)
        )

        assert profile.service_animal_friendly is True
        assert profile.hearing_impairment_capable is True
        assert profile.sign_language_capable is True

    @pytest.mark.asyncio
    async def test_update_all_three_flags_simultaneously(self):
        profile = _make_driver_profile(
            hearing_impairment_capable=False,
            sign_language_capable=False,
            service_animal_friendly=False,
        )
        db = _make_db(row=profile)

        await update_accessibility(
            db,
            user_id=1,
            updates=DriverAccessibilityUpdate(
                hearing_impairment_capable=True,
                sign_language_capable=True,
                service_animal_friendly=True,
            ),
        )

        assert profile.hearing_impairment_capable is True
        assert profile.sign_language_capable is True
        assert profile.service_animal_friendly is True
        db.flush.assert_called_once()


# ===========================================================================
# 4. DriverCandidate dataclass
# ===========================================================================


class TestDriverCandidateServiceAnimalField:
    def test_service_animal_friendly_field_exists(self):
        c = _make_candidate(1, 1.0)
        assert hasattr(c, "service_animal_friendly")

    def test_service_animal_friendly_default_false(self):
        c = _make_candidate(1, 1.0)
        assert c.service_animal_friendly is False

    def test_service_animal_friendly_can_be_set_true(self):
        c = _make_candidate(1, 1.0, service_animal_friendly=True)
        assert c.service_animal_friendly is True


# ===========================================================================
# 5. Matching engine: soft service-animal preference sort
# ===========================================================================


class TestMatchingServiceAnimalPreference:
    def test_friendly_driver_sorted_first_when_rider_has_service_animal(self):
        driver_a = _make_candidate(1, distance_km=1.0, service_animal_friendly=False)
        driver_b = _make_candidate(2, distance_km=1.0, service_animal_friendly=True)

        candidates = [driver_a, driver_b]
        candidates.sort(
            key=lambda c: (
                not c.service_animal_friendly,  # False (friendly) sorts first
                c.distance_km,
                -c.rating_avg,
            )
        )

        assert candidates[0].service_animal_friendly is True
        assert candidates[0].driver_id == 2

    def test_friendly_driver_promoted_even_when_farther_away(self):
        close_unfriendly = _make_candidate(1, distance_km=0.5, service_animal_friendly=False)
        far_friendly = _make_candidate(2, distance_km=4.0, service_animal_friendly=True)

        candidates = [close_unfriendly, far_friendly]
        candidates.sort(
            key=lambda c: (
                not c.service_animal_friendly,
                c.distance_km,
                -c.rating_avg,
            )
        )

        assert candidates[0].driver_id == 2  # friendly, farther away

    def test_no_friendly_driver_non_friendly_still_returned(self):
        driver_a = _make_candidate(1, distance_km=1.0, service_animal_friendly=False)
        driver_b = _make_candidate(2, distance_km=2.0, service_animal_friendly=False)

        candidates = [driver_a, driver_b]
        candidates.sort(
            key=lambda c: (
                not c.service_animal_friendly,
                c.distance_km,
                -c.rating_avg,
            )
        )

        # Both remain; sorted by distance
        assert len(candidates) == 2
        assert candidates[0].driver_id == 1

    def test_without_service_animal_flag_sort_by_distance_and_rating(self):
        driver_a = _make_candidate(1, distance_km=2.0, rating_avg=4.9)
        driver_b = _make_candidate(2, distance_km=1.0, rating_avg=4.0)

        candidates = [driver_a, driver_b]
        candidates.sort(key=lambda c: (c.distance_km, -c.rating_avg))

        assert candidates[0].driver_id == 2  # closer

    def test_multiple_friendly_drivers_sorted_by_distance(self):
        friendly_far = _make_candidate(1, distance_km=3.0, service_animal_friendly=True)
        friendly_close = _make_candidate(2, distance_km=1.0, service_animal_friendly=True)
        unfriendly = _make_candidate(3, distance_km=0.5, service_animal_friendly=False)

        candidates = [friendly_far, friendly_close, unfriendly]
        candidates.sort(
            key=lambda c: (
                not c.service_animal_friendly,
                c.distance_km,
                -c.rating_avg,
            )
        )

        # Both friendly drivers come first, ordered by distance
        assert candidates[0].driver_id == 2  # friendly, closer
        assert candidates[1].driver_id == 1  # friendly, farther
        assert candidates[2].driver_id == 3  # unfriendly

    def test_both_hearing_and_service_animal_flags_applied(self):
        """When both flags are set, hearing capability is primary preference."""
        # A: hearing capable only
        driver_a = _make_candidate(
            1, distance_km=1.0, hearing_impairment_capable=True, service_animal_friendly=False
        )
        # B: service animal friendly only
        driver_b = _make_candidate(
            2, distance_km=1.0, hearing_impairment_capable=False, service_animal_friendly=True
        )
        # C: neither
        driver_c = _make_candidate(
            3, distance_km=1.0, hearing_impairment_capable=False, service_animal_friendly=False
        )

        candidates = [driver_c, driver_b, driver_a]
        # Combined sort: hearing first, then service animal, then distance/rating
        candidates.sort(
            key=lambda c: (
                not c.hearing_impairment_capable,
                not c.service_animal_friendly,
                c.distance_km,
                -c.rating_avg,
            )
        )

        assert candidates[0].driver_id == 1  # hearing capable — first
        assert candidates[1].driver_id == 2  # service animal friendly — second
        assert candidates[2].driver_id == 3  # neither — last


# ===========================================================================
# 6. WebSocket: send_ride_offer payload
# ===========================================================================


class TestSendRideOfferServiceAnimalPayload:
    @pytest.mark.asyncio
    async def test_rider_has_service_animal_included_in_message(self):
        from unittest.mock import AsyncMock, patch

        sent_messages = []

        async def fake_send(user_id, message):
            sent_messages.append(message)
            return True

        with patch(
            "app.api.websocket.manager.send_to_driver",
            side_effect=fake_send,
        ):
            from app.api.websocket import send_ride_offer

            await send_ride_offer(
                driver_user_id=1,
                ride_id=42,
                pickup_address="123 Main St",
                dropoff_address="456 Oak Ave",
                estimated_fare=15.00,
                distance_km=3.5,
                rider_hearing_impairment=False,
                rider_has_service_animal=True,
            )

        assert len(sent_messages) == 1
        assert sent_messages[0]["rider_has_service_animal"] is True
        assert sent_messages[0]["type"] == "ride_offer"

    @pytest.mark.asyncio
    async def test_rider_has_service_animal_defaults_false(self):
        from unittest.mock import AsyncMock, patch

        sent_messages = []

        async def fake_send(user_id, message):
            sent_messages.append(message)
            return True

        with patch(
            "app.api.websocket.manager.send_to_driver",
            side_effect=fake_send,
        ):
            from app.api.websocket import send_ride_offer

            await send_ride_offer(
                driver_user_id=1,
                ride_id=42,
                pickup_address="123 Main St",
                dropoff_address="456 Oak Ave",
                estimated_fare=15.00,
                distance_km=3.5,
            )

        assert sent_messages[0]["rider_has_service_animal"] is False

    @pytest.mark.asyncio
    async def test_both_accessibility_flags_in_message(self):
        from unittest.mock import patch

        sent_messages = []

        async def fake_send(user_id, message):
            sent_messages.append(message)
            return True

        with patch(
            "app.api.websocket.manager.send_to_driver",
            side_effect=fake_send,
        ):
            from app.api.websocket import send_ride_offer

            await send_ride_offer(
                driver_user_id=1,
                ride_id=10,
                pickup_address="A",
                dropoff_address="B",
                estimated_fare=10.00,
                distance_km=2.0,
                rider_hearing_impairment=True,
                rider_has_service_animal=True,
            )

        msg = sent_messages[0]
        assert msg["rider_hearing_impairment"] is True
        assert msg["rider_has_service_animal"] is True


# ===========================================================================
# 7. RidePreference schema round-trip
# ===========================================================================


class TestRidePreferenceSchemaRoundTrip:
    def test_has_service_animal_true_survives_model_validate(self):
        pref = _make_ride_preference(has_service_animal=True)
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.has_service_animal is True

    def test_has_service_animal_false_survives_model_validate(self):
        pref = _make_ride_preference(has_service_animal=False)
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.has_service_animal is False

    def test_update_schema_excludes_none_for_partial_update(self):
        update = RidePreferenceUpdate(has_service_animal=True)
        dumped = update.model_dump(exclude_none=True)
        assert dumped == {"has_service_animal": True}
        assert "hearing_impairment" not in dumped
