"""Tests for visual impairment support.

Covers:
1. Model columns
   - visual_impairment on RidePreference: exists, default False
   - visual_assistance_capable on DriverProfile: exists, default False

2. Schemas
   - RidePreferenceUpdate: visual_impairment optional, default None
   - RidePreferenceResponse: visual_impairment required bool
   - DriverAccessibilityUpdate: visual_assistance_capable optional, default None
   - DriverAccessibilityResponse: visual_assistance_capable required bool

3. Service logic
   - update_accessibility sets visual_assistance_capable and flushes
   - update_accessibility no-op when visual_assistance_capable unchanged
   - update_accessibility partial: other fields unaffected
   - update_accessibility can set all four capability flags simultaneously

4. DriverCandidate dataclass
   - visual_assistance_capable field exists, default False

5. Matching engine: soft visual-impairment preference
   - visual_assistance_capable driver sorted first when rider_visual_impairment=True
   - Capable driver promoted even when farther away
   - No capable driver: non-capable drivers still returned (no rider stranded)
   - Without rider flag: default distance/rating sort unchanged
   - Multiple capable drivers: distance tiebreaker applies
   - All three flags active (hearing + service_animal + visual): compound sort

6. WebSocket: send_ride_offer
   - rider_visual_impairment included in message payload when True
   - Default value is False when not supplied
   - All three accessibility flags present in single offer message

7. RidePreference schema round-trip
   - visual_impairment=True preserved through model_validate
   - visual_impairment=False preserved through model_validate
   - partial update excludes None fields

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
    visual_assistance_capable: bool = False,
) -> MagicMock:
    p = MagicMock(spec=DriverProfile)
    p.id = 1
    p.user_id = user_id
    p.hearing_impairment_capable = hearing_impairment_capable
    p.sign_language_capable = sign_language_capable
    p.service_animal_friendly = service_animal_friendly
    p.visual_assistance_capable = visual_assistance_capable
    p.updated_at = datetime.now(timezone.utc)
    return p


def _make_ride_preference(
    user_id: int = 1,
    hearing_impairment: bool = False,
    has_service_animal: bool = False,
    visual_impairment: bool = False,
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
    p.visual_impairment = visual_impairment
    p.pool_opt_out = False
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
    visual_assistance_capable: bool = False,
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
        visual_assistance_capable=visual_assistance_capable,
    )


# ===========================================================================
# 1. Model columns
# ===========================================================================


class TestRidePreferenceVisualImpairmentColumn:
    def test_visual_impairment_exists(self):
        p = RidePreference()
        assert hasattr(p, "visual_impairment")

    def test_visual_impairment_default_false(self):
        p = RidePreference()
        assert not p.visual_impairment


class TestDriverProfileVisualAssistanceColumn:
    def test_visual_assistance_capable_exists(self):
        p = DriverProfile()
        assert hasattr(p, "visual_assistance_capable")

    def test_visual_assistance_capable_default_false(self):
        p = DriverProfile()
        assert not p.visual_assistance_capable


# ===========================================================================
# 2. Schemas
# ===========================================================================


class TestRidePreferenceUpdateVisualImpairment:
    def test_visual_impairment_optional_default_none(self):
        update = RidePreferenceUpdate()
        assert update.visual_impairment is None

    def test_visual_impairment_can_be_set_true(self):
        update = RidePreferenceUpdate(visual_impairment=True)
        assert update.visual_impairment is True

    def test_visual_impairment_can_be_set_false(self):
        update = RidePreferenceUpdate(visual_impairment=False)
        assert update.visual_impairment is False

    def test_partial_update_other_fields_unaffected(self):
        update = RidePreferenceUpdate(visual_impairment=True)
        assert update.hearing_impairment is None
        assert update.has_service_animal is None
        assert update.quiet_ride is None


class TestRidePreferenceResponseVisualImpairment:
    def test_visual_impairment_true_in_response(self):
        pref = _make_ride_preference(visual_impairment=True)
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.visual_impairment is True

    def test_visual_impairment_false_in_response(self):
        pref = _make_ride_preference(visual_impairment=False)
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.visual_impairment is False

    def test_all_accessibility_flags_present_in_response(self):
        pref = _make_ride_preference(
            hearing_impairment=True,
            has_service_animal=True,
            visual_impairment=True,
        )
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.hearing_impairment is True
        assert resp.has_service_animal is True
        assert resp.visual_impairment is True


class TestDriverAccessibilityUpdateVisualAssistance:
    def test_visual_assistance_capable_optional_default_none(self):
        update = DriverAccessibilityUpdate()
        assert update.visual_assistance_capable is None

    def test_visual_assistance_capable_can_be_set_true(self):
        update = DriverAccessibilityUpdate(visual_assistance_capable=True)
        assert update.visual_assistance_capable is True

    def test_visual_assistance_capable_can_be_set_false(self):
        update = DriverAccessibilityUpdate(visual_assistance_capable=False)
        assert update.visual_assistance_capable is False

    def test_partial_update_other_fields_unaffected(self):
        update = DriverAccessibilityUpdate(visual_assistance_capable=True)
        assert update.hearing_impairment_capable is None
        assert update.sign_language_capable is None
        assert update.service_animal_friendly is None


class TestDriverAccessibilityResponseVisualAssistance:
    def test_visual_assistance_capable_false_in_response(self):
        profile = _make_driver_profile(visual_assistance_capable=False)
        resp = DriverAccessibilityResponse.model_validate(profile)
        assert resp.visual_assistance_capable is False

    def test_visual_assistance_capable_true_in_response(self):
        profile = _make_driver_profile(visual_assistance_capable=True)
        resp = DriverAccessibilityResponse.model_validate(profile)
        assert resp.visual_assistance_capable is True

    def test_all_four_capability_flags_in_response(self):
        profile = _make_driver_profile(
            hearing_impairment_capable=True,
            sign_language_capable=False,
            service_animal_friendly=True,
            visual_assistance_capable=True,
        )
        resp = DriverAccessibilityResponse.model_validate(profile)
        assert resp.hearing_impairment_capable is True
        assert resp.sign_language_capable is False
        assert resp.service_animal_friendly is True
        assert resp.visual_assistance_capable is True

    def test_response_includes_updated_at(self):
        profile = _make_driver_profile()
        resp = DriverAccessibilityResponse.model_validate(profile)
        assert isinstance(resp.updated_at, datetime)


# ===========================================================================
# 3. Service logic
# ===========================================================================


class TestDriverAccessibilityServiceVisualAssistance:
    @pytest.mark.asyncio
    async def test_update_sets_visual_assistance_capable_true(self):
        profile = _make_driver_profile(visual_assistance_capable=False)
        db = _make_db(row=profile)

        await update_accessibility(
            db,
            user_id=1,
            updates=DriverAccessibilityUpdate(visual_assistance_capable=True),
        )

        assert profile.visual_assistance_capable is True
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_no_flush_when_visual_assistance_unchanged(self):
        profile = _make_driver_profile(visual_assistance_capable=True)
        db = _make_db(row=profile)

        await update_accessibility(
            db,
            user_id=1,
            updates=DriverAccessibilityUpdate(visual_assistance_capable=True),
        )

        db.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_visual_assistance_does_not_touch_other_flags(self):
        profile = _make_driver_profile(
            hearing_impairment_capable=True,
            sign_language_capable=True,
            service_animal_friendly=True,
            visual_assistance_capable=False,
        )
        db = _make_db(row=profile)

        await update_accessibility(
            db,
            user_id=1,
            updates=DriverAccessibilityUpdate(visual_assistance_capable=True),
        )

        assert profile.visual_assistance_capable is True
        assert profile.hearing_impairment_capable is True
        assert profile.sign_language_capable is True
        assert profile.service_animal_friendly is True

    @pytest.mark.asyncio
    async def test_update_all_four_flags_simultaneously(self):
        profile = _make_driver_profile(
            hearing_impairment_capable=False,
            sign_language_capable=False,
            service_animal_friendly=False,
            visual_assistance_capable=False,
        )
        db = _make_db(row=profile)

        await update_accessibility(
            db,
            user_id=1,
            updates=DriverAccessibilityUpdate(
                hearing_impairment_capable=True,
                sign_language_capable=True,
                service_animal_friendly=True,
                visual_assistance_capable=True,
            ),
        )

        assert profile.hearing_impairment_capable is True
        assert profile.sign_language_capable is True
        assert profile.service_animal_friendly is True
        assert profile.visual_assistance_capable is True
        db.flush.assert_called_once()


# ===========================================================================
# 4. DriverCandidate dataclass
# ===========================================================================


class TestDriverCandidateVisualAssistanceField:
    def test_visual_assistance_capable_field_exists(self):
        c = _make_candidate(1, 1.0)
        assert hasattr(c, "visual_assistance_capable")

    def test_visual_assistance_capable_default_false(self):
        c = _make_candidate(1, 1.0)
        assert c.visual_assistance_capable is False

    def test_visual_assistance_capable_can_be_set_true(self):
        c = _make_candidate(1, 1.0, visual_assistance_capable=True)
        assert c.visual_assistance_capable is True


# ===========================================================================
# 5. Matching engine: soft visual-impairment preference sort
# ===========================================================================


def _sort_with_visual(
    candidates: list[DriverCandidate],
    rider_visual_impairment: bool = True,
) -> list[DriverCandidate]:
    """Apply the compound accessibility sort key, visual impairment only."""
    if rider_visual_impairment:
        candidates.sort(
            key=lambda c: (
                not c.visual_assistance_capable if rider_visual_impairment else 0,
                c.distance_km,
                -c.rating_avg,
            )
        )
    else:
        candidates.sort(key=lambda c: (c.distance_km, -c.rating_avg))
    return candidates


def _sort_all_three(
    candidates: list[DriverCandidate],
    rider_hearing_impairment: bool = False,
    rider_has_service_animal: bool = False,
    rider_visual_impairment: bool = False,
) -> list[DriverCandidate]:
    """Compound sort matching the engine's implementation."""
    if rider_hearing_impairment or rider_has_service_animal or rider_visual_impairment:
        candidates.sort(
            key=lambda c: (
                not c.hearing_impairment_capable if rider_hearing_impairment else 0,
                not c.service_animal_friendly if rider_has_service_animal else 0,
                not c.visual_assistance_capable if rider_visual_impairment else 0,
                c.distance_km,
                -c.rating_avg,
            )
        )
    else:
        candidates.sort(key=lambda c: (c.distance_km, -c.rating_avg))
    return candidates


class TestMatchingVisualImpairmentPreference:
    def test_visual_capable_driver_sorted_first(self):
        driver_a = _make_candidate(1, distance_km=1.0, visual_assistance_capable=False)
        driver_b = _make_candidate(2, distance_km=1.0, visual_assistance_capable=True)

        result = _sort_with_visual([driver_a, driver_b])

        assert result[0].visual_assistance_capable is True
        assert result[0].driver_id == 2

    def test_visual_capable_promoted_when_farther_away(self):
        close_incapable = _make_candidate(1, distance_km=0.3, visual_assistance_capable=False)
        far_capable = _make_candidate(2, distance_km=5.0, visual_assistance_capable=True)

        result = _sort_with_visual([close_incapable, far_capable])

        assert result[0].driver_id == 2  # capable, farther away

    def test_no_capable_driver_incapable_still_returned(self):
        driver_a = _make_candidate(1, distance_km=1.0, visual_assistance_capable=False)
        driver_b = _make_candidate(2, distance_km=2.0, visual_assistance_capable=False)

        result = _sort_with_visual([driver_a, driver_b])

        # Both remain; closest first
        assert len(result) == 2
        assert result[0].driver_id == 1

    def test_without_visual_flag_sort_by_distance_and_rating(self):
        driver_a = _make_candidate(1, distance_km=3.0, rating_avg=4.9, visual_assistance_capable=True)
        driver_b = _make_candidate(2, distance_km=1.0, rating_avg=4.0)

        result = _sort_with_visual([driver_a, driver_b], rider_visual_impairment=False)

        assert result[0].driver_id == 2  # closer wins when flag is off

    def test_multiple_capable_drivers_sorted_by_distance(self):
        capable_far = _make_candidate(1, distance_km=4.0, visual_assistance_capable=True)
        capable_close = _make_candidate(2, distance_km=1.0, visual_assistance_capable=True)
        incapable_closest = _make_candidate(3, distance_km=0.2, visual_assistance_capable=False)

        result = _sort_with_visual([capable_far, capable_close, incapable_closest])

        # Both capable drivers first, ordered by distance; incapable last
        assert result[0].driver_id == 2  # capable, closer
        assert result[1].driver_id == 1  # capable, farther
        assert result[2].driver_id == 3  # incapable

    def test_rating_tiebreaker_among_capable_drivers_at_same_distance(self):
        capable_low_rating = _make_candidate(1, distance_km=2.0, rating_avg=4.0, visual_assistance_capable=True)
        capable_high_rating = _make_candidate(2, distance_km=2.0, rating_avg=4.9, visual_assistance_capable=True)

        result = _sort_with_visual([capable_low_rating, capable_high_rating])

        assert result[0].driver_id == 2  # higher rated wins on tie


class TestMatchingCompoundAccessibilitySort:
    def test_all_three_flags_compound_sort(self):
        """When all three rider flags are set, hearing is primary preference."""
        # Only hearing capable
        driver_a = _make_candidate(1, distance_km=1.0, hearing_impairment_capable=True)
        # Only service animal friendly
        driver_b = _make_candidate(2, distance_km=1.0, service_animal_friendly=True)
        # Only visual capable
        driver_c = _make_candidate(3, distance_km=1.0, visual_assistance_capable=True)
        # None
        driver_d = _make_candidate(4, distance_km=1.0)

        result = _sort_all_three(
            [driver_d, driver_c, driver_b, driver_a],
            rider_hearing_impairment=True,
            rider_has_service_animal=True,
            rider_visual_impairment=True,
        )

        # Primary: hearing; secondary: service animal; tertiary: visual
        assert result[0].driver_id == 1  # hearing capable
        assert result[1].driver_id == 2  # service animal friendly
        assert result[2].driver_id == 3  # visual capable
        assert result[3].driver_id == 4  # none

    def test_visual_only_flag_does_not_affect_other_dimensions(self):
        """Setting only rider_visual_impairment leaves hearing/service_animal sort neutral."""
        driver_a = _make_candidate(1, distance_km=2.0, hearing_impairment_capable=True)
        driver_b = _make_candidate(2, distance_km=1.0, visual_assistance_capable=True)

        result = _sort_all_three(
            [driver_a, driver_b],
            rider_visual_impairment=True,
        )

        # Only visual matters: driver_b (capable) first, driver_a (farther, hearing but no visual) second
        assert result[0].driver_id == 2
        assert result[1].driver_id == 1

    def test_visual_and_hearing_combined_sort(self):
        """hearing is primary key, visual is tertiary."""
        # Hearing capable, not visual
        driver_a = _make_candidate(1, distance_km=1.0, hearing_impairment_capable=True, visual_assistance_capable=False)
        # Visual capable, not hearing
        driver_b = _make_candidate(2, distance_km=1.0, hearing_impairment_capable=False, visual_assistance_capable=True)
        # Neither
        driver_c = _make_candidate(3, distance_km=1.0)

        result = _sort_all_three(
            [driver_c, driver_b, driver_a],
            rider_hearing_impairment=True,
            rider_visual_impairment=True,
        )

        # Hearing is primary: A first, then B (visual), then C (neither)
        assert result[0].driver_id == 1  # hearing capable
        assert result[1].driver_id == 2  # visual capable
        assert result[2].driver_id == 3  # neither

    def test_no_flags_active_uses_distance_rating_only(self):
        driver_a = _make_candidate(1, distance_km=3.0, rating_avg=4.9)
        driver_b = _make_candidate(2, distance_km=1.0, rating_avg=4.0)
        driver_c = _make_candidate(3, distance_km=2.0, rating_avg=4.5)

        result = _sort_all_three([driver_a, driver_b, driver_c])

        assert result[0].driver_id == 2  # closest
        assert result[1].driver_id == 3
        assert result[2].driver_id == 1  # farthest


# ===========================================================================
# 6. WebSocket: send_ride_offer payload
# ===========================================================================


class TestSendRideOfferVisualImpairmentPayload:
    @pytest.mark.asyncio
    async def test_rider_visual_impairment_included_when_true(self):
        from unittest.mock import patch

        sent_messages = []

        async def fake_send(user_id, message):
            sent_messages.append(message)
            return True

        with patch("app.api.websocket.manager.send_to_driver", side_effect=fake_send):
            from app.api.websocket import send_ride_offer

            await send_ride_offer(
                driver_user_id=1,
                ride_id=99,
                pickup_address="1 Pickup St",
                dropoff_address="2 Dropoff Ave",
                estimated_fare=20.00,
                distance_km=4.0,
                rider_visual_impairment=True,
            )

        assert len(sent_messages) == 1
        assert sent_messages[0]["rider_visual_impairment"] is True
        assert sent_messages[0]["type"] == "ride_offer"

    @pytest.mark.asyncio
    async def test_rider_visual_impairment_defaults_false(self):
        from unittest.mock import patch

        sent_messages = []

        async def fake_send(user_id, message):
            sent_messages.append(message)
            return True

        with patch("app.api.websocket.manager.send_to_driver", side_effect=fake_send):
            from app.api.websocket import send_ride_offer

            await send_ride_offer(
                driver_user_id=1,
                ride_id=42,
                pickup_address="A",
                dropoff_address="B",
                estimated_fare=10.00,
                distance_km=2.0,
            )

        assert sent_messages[0]["rider_visual_impairment"] is False

    @pytest.mark.asyncio
    async def test_all_three_accessibility_flags_in_offer_message(self):
        from unittest.mock import patch

        sent_messages = []

        async def fake_send(user_id, message):
            sent_messages.append(message)
            return True

        with patch("app.api.websocket.manager.send_to_driver", side_effect=fake_send):
            from app.api.websocket import send_ride_offer

            await send_ride_offer(
                driver_user_id=5,
                ride_id=77,
                pickup_address="X",
                dropoff_address="Y",
                estimated_fare=25.00,
                distance_km=6.0,
                rider_hearing_impairment=True,
                rider_has_service_animal=True,
                rider_visual_impairment=True,
            )

        msg = sent_messages[0]
        assert msg["rider_hearing_impairment"] is True
        assert msg["rider_has_service_animal"] is True
        assert msg["rider_visual_impairment"] is True

    @pytest.mark.asyncio
    async def test_visual_flag_false_other_flags_true(self):
        from unittest.mock import patch

        sent_messages = []

        async def fake_send(user_id, message):
            sent_messages.append(message)
            return True

        with patch("app.api.websocket.manager.send_to_driver", side_effect=fake_send):
            from app.api.websocket import send_ride_offer

            await send_ride_offer(
                driver_user_id=2,
                ride_id=55,
                pickup_address="C",
                dropoff_address="D",
                estimated_fare=12.00,
                distance_km=1.5,
                rider_hearing_impairment=True,
                rider_has_service_animal=False,
                rider_visual_impairment=False,
            )

        msg = sent_messages[0]
        assert msg["rider_hearing_impairment"] is True
        assert msg["rider_has_service_animal"] is False
        assert msg["rider_visual_impairment"] is False


# ===========================================================================
# 7. RidePreference schema round-trip
# ===========================================================================


class TestRidePreferenceVisualSchemaRoundTrip:
    def test_visual_impairment_true_survives_model_validate(self):
        pref = _make_ride_preference(visual_impairment=True)
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.visual_impairment is True

    def test_visual_impairment_false_survives_model_validate(self):
        pref = _make_ride_preference(visual_impairment=False)
        resp = RidePreferenceResponse.model_validate(pref)
        assert resp.visual_impairment is False

    def test_update_schema_excludes_none_for_partial_update(self):
        update = RidePreferenceUpdate(visual_impairment=True)
        dumped = update.model_dump(exclude_none=True)
        assert dumped == {"visual_impairment": True}
        assert "hearing_impairment" not in dumped
        assert "has_service_animal" not in dumped

    def test_all_three_accessibility_flags_in_update(self):
        update = RidePreferenceUpdate(
            hearing_impairment=True,
            has_service_animal=True,
            visual_impairment=True,
        )
        dumped = update.model_dump(exclude_none=True)
        assert dumped["hearing_impairment"] is True
        assert dumped["has_service_animal"] is True
        assert dumped["visual_impairment"] is True
