"""Tests for accessibility features.

Covers:
1. Hearing impairment field
   - Model: hearing_impairment field exists with default False
   - Schema: RidePreferenceUpdate and RidePreferenceResponse include hearing_impairment
   - Service: default row has hearing_impairment=False; update sets it; no flush on same value
   - WebSocket: send_ride_offer includes rider_hearing_impairment in message

2. WAV preference auto-apply
   - POST /rides/request sets accessibility_required=True when preference is True
   - POST /rides/request respects explicit accessibility_required=True even with False pref
   - POST /rides/request keeps accessibility_required=False when pref is False
   - POST /rides/request keeps accessibility_required=False when no prefs row

All tests are pure unit tests — no database required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ride_preference import RidePreference, TemperaturePreference
from app.schemas.ride_preference import RidePreferenceResponse, RidePreferenceUpdate
from app.services.ride_preferences import get_preferences, update_preferences


# ===========================================================================
# Helpers
# ===========================================================================


def _make_prefs(
    user_id: int = 1,
    accessibility_vehicle_needed: bool = False,
    hearing_impairment: bool = False,
    pool_opt_out: bool = False,
) -> MagicMock:
    p = MagicMock(spec=RidePreference)
    p.id = 1
    p.user_id = user_id
    p.quiet_ride = False
    p.music_off = False
    p.temperature_preference = TemperaturePreference.NO_PREFERENCE
    p.pet_friendly = False
    p.extra_luggage = False
    p.accessibility_vehicle_needed = accessibility_vehicle_needed
    p.hearing_impairment = hearing_impairment
    p.pool_opt_out = pool_opt_out
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
# Hearing impairment — Model
# ===========================================================================


class TestHearingImpairmentModel:
    def test_field_exists(self):
        p = RidePreference()
        assert hasattr(p, "hearing_impairment")

    def test_default_is_falsy(self):
        p = RidePreference()
        assert not p.hearing_impairment


# ===========================================================================
# Hearing impairment — Schema: Update
# ===========================================================================


class TestHearingImpairmentUpdateSchema:
    def test_optional_defaults_none(self):
        update = RidePreferenceUpdate()
        assert update.hearing_impairment is None

    def test_can_be_set_true(self):
        update = RidePreferenceUpdate(hearing_impairment=True)
        assert update.hearing_impairment is True

    def test_can_be_set_false(self):
        update = RidePreferenceUpdate(hearing_impairment=False)
        assert update.hearing_impairment is False

    def test_independent_of_other_fields(self):
        update = RidePreferenceUpdate(quiet_ride=True, hearing_impairment=True)
        assert update.quiet_ride is True
        assert update.hearing_impairment is True
        assert update.music_off is None


# ===========================================================================
# Hearing impairment — Schema: Response
# ===========================================================================


class TestHearingImpairmentResponseSchema:
    def test_response_includes_false(self):
        prefs = _make_prefs(hearing_impairment=False)
        resp = RidePreferenceResponse.model_validate(prefs)
        assert resp.hearing_impairment is False

    def test_response_includes_true(self):
        prefs = _make_prefs(hearing_impairment=True)
        resp = RidePreferenceResponse.model_validate(prefs)
        assert resp.hearing_impairment is True

    def test_response_has_field(self):
        prefs = _make_prefs()
        resp = RidePreferenceResponse.model_validate(prefs)
        assert hasattr(resp, "hearing_impairment")


# ===========================================================================
# Hearing impairment — Service
# ===========================================================================


class TestHearingImpairmentService:
    @pytest.mark.asyncio
    async def test_default_row_has_hearing_impairment_false(self):
        db = _make_db(row=None)

        await get_preferences(db, user_id=42)

        added = db.add.call_args[0][0]
        assert isinstance(added, RidePreference)
        assert added.hearing_impairment is False

    @pytest.mark.asyncio
    async def test_update_sets_true(self):
        prefs = _make_prefs(user_id=1, hearing_impairment=False)
        db = _make_db(row=prefs)

        updates = RidePreferenceUpdate(hearing_impairment=True)
        await update_preferences(db, user_id=1, updates=updates)

        assert prefs.hearing_impairment is True
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_sets_false(self):
        prefs = _make_prefs(user_id=1, hearing_impairment=True)
        db = _make_db(row=prefs)

        updates = RidePreferenceUpdate(hearing_impairment=False)
        await update_preferences(db, user_id=1, updates=updates)

        assert prefs.hearing_impairment is False
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_flush_when_same_value(self):
        prefs = _make_prefs(user_id=1, hearing_impairment=True)
        db = _make_db(row=prefs)

        updates = RidePreferenceUpdate(hearing_impairment=True)
        await update_preferences(db, user_id=1, updates=updates)

        db.flush.assert_not_called()


# ===========================================================================
# Hearing impairment — WebSocket ride offer
# ===========================================================================


class TestHearingImpairmentRideOffer:
    @pytest.mark.asyncio
    async def test_send_ride_offer_includes_hearing_impairment_flag(self):
        """send_ride_offer passes rider_hearing_impairment in WebSocket message."""
        from app.api.websocket import send_ride_offer, manager

        sent_message = {}

        async def capture_send(user_id, msg):
            sent_message.update(msg)
            return True

        original = manager.send_to_driver
        manager.send_to_driver = capture_send
        try:
            await send_ride_offer(
                driver_user_id=7,
                ride_id=42,
                pickup_address="100 Main St",
                dropoff_address="200 Oak Ave",
                estimated_fare=12.50,
                distance_km=3.2,
                rider_hearing_impairment=True,
            )
        finally:
            manager.send_to_driver = original

        assert sent_message.get("rider_hearing_impairment") is True

    @pytest.mark.asyncio
    async def test_send_ride_offer_false_by_default(self):
        """send_ride_offer defaults rider_hearing_impairment to False."""
        from app.api.websocket import send_ride_offer, manager

        sent_message = {}

        async def capture_send(user_id, msg):
            sent_message.update(msg)
            return True

        original = manager.send_to_driver
        manager.send_to_driver = capture_send
        try:
            await send_ride_offer(
                driver_user_id=7,
                ride_id=42,
                pickup_address="100 Main St",
                dropoff_address="200 Oak Ave",
                estimated_fare=12.50,
                distance_km=3.2,
            )
        finally:
            manager.send_to_driver = original

        assert sent_message.get("rider_hearing_impairment") is False


# ===========================================================================
# WAV preference auto-apply
# ===========================================================================


class TestWAVPreferenceAutoApply:
    """accessibility_vehicle_needed pref forces accessibility_required on the ride."""

    @pytest.mark.asyncio
    async def test_pref_true_overrides_false_request(self):
        """If rider pref has accessibility_vehicle_needed=True, ride is WAV even if
        req.accessibility_required is False."""
        from app.api.v1.rides import request_ride
        from app.schemas.ride import RideRequest

        user = MagicMock()
        user.id = 1

        req = MagicMock(spec=RideRequest)
        req.accessibility_required = False
        req.vehicle_type_preference = None
        req.promo_code = None
        req.pickup = MagicMock(lat=40.7, lng=-74.0)
        req.dropoff = MagicMock(lat=40.8, lng=-74.0)
        req.pickup_address = "100 Main St"
        req.dropoff_address = "200 Oak Ave"
        req.pickup_saved_location_id = None
        req.dropoff_saved_location_id = None
        req.waypoints = []

        db = AsyncMock()
        background_tasks = MagicMock()
        background_tasks.add_task = MagicMock()

        prefs = _make_prefs(accessibility_vehicle_needed=True)
        ride_obj = MagicMock()
        ride_obj.id = 1
        ride_obj.status = MagicMock(value="requested")
        ride_obj.pickup_address = "100 Main St"
        ride_obj.dropoff_address = "200 Oak Ave"
        ride_obj.estimated_fare = 10.0
        ride_obj.requested_at = datetime.now(timezone.utc)

        with patch("app.api.v1.rides._resolve_saved_location",
                   new_callable=AsyncMock,
                   side_effect=[
                       (req.pickup, "100 Main St"),
                       (req.dropoff, "200 Oak Ave"),
                   ]), \
             patch("app.api.v1.rides.validate_ride_locations",
                   new_callable=AsyncMock,
                   return_value={"valid": True}), \
             patch("app.api.v1.rides.get_route",
                   new_callable=AsyncMock,
                   return_value={"distance_km": 5.0, "duration_min": 12.0}), \
             patch("app.api.v1.rides.get_redis", new_callable=AsyncMock), \
             patch("app.api.v1.rides.record_demand", new_callable=AsyncMock), \
             patch("app.api.v1.rides.get_demand_info",
                   new_callable=AsyncMock,
                   return_value=MagicMock(multiplier=1.0, explanation="")), \
             patch("app.api.v1.rides.calculate_fare_breakdown",
                   return_value=MagicMock(total=10.0, base=5.0, distance=3.0,
                                          time=2.0, multiplier=1.0,
                                          multiplier_label="", demand_multiplier=1.0,
                                          demand_label="", subtotal=10.0,
                                          platform_fee=1.0)), \
             patch("app.services.promos.get_referral_credit_balance",
                   new_callable=AsyncMock,
                   return_value=0.0), \
             patch("app.api.v1.rides.get_preferences_for_ride",
                   new_callable=AsyncMock,
                   return_value=prefs), \
             patch("app.api.v1.rides.Ride", return_value=ride_obj) as MockRide, \
             patch("app.services.audit_events.audit_ride_requested",
                   new_callable=AsyncMock):

            db.add = MagicMock()
            db.commit = AsyncMock()
            db.refresh = AsyncMock()

            await request_ride(
                req=req,
                background_tasks=background_tasks,
                user=user,
                db=db,
            )

        # Ride must be created with accessibility_required=True
        call_kwargs = MockRide.call_args[1]
        assert call_kwargs["accessibility_required"] is True

    @pytest.mark.asyncio
    async def test_pref_false_and_request_false_stays_false(self):
        """When pref is False and request is False, accessibility_required stays False."""
        from app.api.v1.rides import request_ride
        from app.schemas.ride import RideRequest

        user = MagicMock()
        user.id = 1

        req = MagicMock(spec=RideRequest)
        req.accessibility_required = False
        req.vehicle_type_preference = None
        req.promo_code = None
        req.pickup = MagicMock(lat=40.7, lng=-74.0)
        req.dropoff = MagicMock(lat=40.8, lng=-74.0)
        req.pickup_address = "100 Main St"
        req.dropoff_address = "200 Oak Ave"
        req.pickup_saved_location_id = None
        req.dropoff_saved_location_id = None
        req.waypoints = []

        db = AsyncMock()
        background_tasks = MagicMock()
        background_tasks.add_task = MagicMock()

        prefs = _make_prefs(accessibility_vehicle_needed=False)
        ride_obj = MagicMock()
        ride_obj.id = 1
        ride_obj.status = MagicMock(value="requested")
        ride_obj.pickup_address = "100 Main St"
        ride_obj.dropoff_address = "200 Oak Ave"
        ride_obj.estimated_fare = 10.0
        ride_obj.requested_at = datetime.now(timezone.utc)

        with patch("app.api.v1.rides._resolve_saved_location",
                   new_callable=AsyncMock,
                   side_effect=[
                       (req.pickup, "100 Main St"),
                       (req.dropoff, "200 Oak Ave"),
                   ]), \
             patch("app.api.v1.rides.validate_ride_locations",
                   new_callable=AsyncMock,
                   return_value={"valid": True}), \
             patch("app.api.v1.rides.get_route",
                   new_callable=AsyncMock,
                   return_value={"distance_km": 5.0, "duration_min": 12.0}), \
             patch("app.api.v1.rides.get_redis", new_callable=AsyncMock), \
             patch("app.api.v1.rides.record_demand", new_callable=AsyncMock), \
             patch("app.api.v1.rides.get_demand_info",
                   new_callable=AsyncMock,
                   return_value=MagicMock(multiplier=1.0, explanation="")), \
             patch("app.api.v1.rides.calculate_fare_breakdown",
                   return_value=MagicMock(total=10.0, base=5.0, distance=3.0,
                                          time=2.0, multiplier=1.0,
                                          multiplier_label="", demand_multiplier=1.0,
                                          demand_label="", subtotal=10.0,
                                          platform_fee=1.0)), \
             patch("app.services.promos.get_referral_credit_balance",
                   new_callable=AsyncMock,
                   return_value=0.0), \
             patch("app.api.v1.rides.get_preferences_for_ride",
                   new_callable=AsyncMock,
                   return_value=prefs), \
             patch("app.api.v1.rides.Ride", return_value=ride_obj) as MockRide, \
             patch("app.services.audit_events.audit_ride_requested",
                   new_callable=AsyncMock):

            db.add = MagicMock()
            db.commit = AsyncMock()
            db.refresh = AsyncMock()

            await request_ride(
                req=req,
                background_tasks=background_tasks,
                user=user,
                db=db,
            )

        call_kwargs = MockRide.call_args[1]
        assert call_kwargs["accessibility_required"] is False

    @pytest.mark.asyncio
    async def test_explicit_true_request_passes_through(self):
        """accessibility_required=True in request is respected even if pref is False."""
        from app.api.v1.rides import request_ride
        from app.schemas.ride import RideRequest

        user = MagicMock()
        user.id = 1

        req = MagicMock(spec=RideRequest)
        req.accessibility_required = True
        req.vehicle_type_preference = None
        req.promo_code = None
        req.pickup = MagicMock(lat=40.7, lng=-74.0)
        req.dropoff = MagicMock(lat=40.8, lng=-74.0)
        req.pickup_address = "100 Main St"
        req.dropoff_address = "200 Oak Ave"
        req.pickup_saved_location_id = None
        req.dropoff_saved_location_id = None
        req.waypoints = []

        db = AsyncMock()
        background_tasks = MagicMock()
        background_tasks.add_task = MagicMock()

        prefs = _make_prefs(accessibility_vehicle_needed=False)
        ride_obj = MagicMock()
        ride_obj.id = 1
        ride_obj.status = MagicMock(value="requested")
        ride_obj.pickup_address = "100 Main St"
        ride_obj.dropoff_address = "200 Oak Ave"
        ride_obj.estimated_fare = 10.0
        ride_obj.requested_at = datetime.now(timezone.utc)

        with patch("app.api.v1.rides._resolve_saved_location",
                   new_callable=AsyncMock,
                   side_effect=[
                       (req.pickup, "100 Main St"),
                       (req.dropoff, "200 Oak Ave"),
                   ]), \
             patch("app.api.v1.rides.validate_ride_locations",
                   new_callable=AsyncMock,
                   return_value={"valid": True}), \
             patch("app.api.v1.rides.get_route",
                   new_callable=AsyncMock,
                   return_value={"distance_km": 5.0, "duration_min": 12.0}), \
             patch("app.api.v1.rides.get_redis", new_callable=AsyncMock), \
             patch("app.api.v1.rides.record_demand", new_callable=AsyncMock), \
             patch("app.api.v1.rides.get_demand_info",
                   new_callable=AsyncMock,
                   return_value=MagicMock(multiplier=1.0, explanation="")), \
             patch("app.api.v1.rides.calculate_fare_breakdown",
                   return_value=MagicMock(total=10.0, base=5.0, distance=3.0,
                                          time=2.0, multiplier=1.0,
                                          multiplier_label="", demand_multiplier=1.0,
                                          demand_label="", subtotal=10.0,
                                          platform_fee=1.0)), \
             patch("app.services.promos.get_referral_credit_balance",
                   new_callable=AsyncMock,
                   return_value=0.0), \
             patch("app.api.v1.rides.get_preferences_for_ride",
                   new_callable=AsyncMock,
                   return_value=prefs), \
             patch("app.api.v1.rides.Ride", return_value=ride_obj) as MockRide, \
             patch("app.services.audit_events.audit_ride_requested",
                   new_callable=AsyncMock):

            db.add = MagicMock()
            db.commit = AsyncMock()
            db.refresh = AsyncMock()

            await request_ride(
                req=req,
                background_tasks=background_tasks,
                user=user,
                db=db,
            )

        call_kwargs = MockRide.call_args[1]
        assert call_kwargs["accessibility_required"] is True

    @pytest.mark.asyncio
    async def test_no_prefs_row_uses_request_flag(self):
        """When rider has no preferences row, accessibility_required from request is used."""
        from app.api.v1.rides import request_ride
        from app.schemas.ride import RideRequest

        user = MagicMock()
        user.id = 1

        req = MagicMock(spec=RideRequest)
        req.accessibility_required = False
        req.vehicle_type_preference = None
        req.promo_code = None
        req.pickup = MagicMock(lat=40.7, lng=-74.0)
        req.dropoff = MagicMock(lat=40.8, lng=-74.0)
        req.pickup_address = "100 Main St"
        req.dropoff_address = "200 Oak Ave"
        req.pickup_saved_location_id = None
        req.dropoff_saved_location_id = None
        req.waypoints = []

        db = AsyncMock()
        background_tasks = MagicMock()
        background_tasks.add_task = MagicMock()

        ride_obj = MagicMock()
        ride_obj.id = 1
        ride_obj.status = MagicMock(value="requested")
        ride_obj.pickup_address = "100 Main St"
        ride_obj.dropoff_address = "200 Oak Ave"
        ride_obj.estimated_fare = 10.0
        ride_obj.requested_at = datetime.now(timezone.utc)

        with patch("app.api.v1.rides._resolve_saved_location",
                   new_callable=AsyncMock,
                   side_effect=[
                       (req.pickup, "100 Main St"),
                       (req.dropoff, "200 Oak Ave"),
                   ]), \
             patch("app.api.v1.rides.validate_ride_locations",
                   new_callable=AsyncMock,
                   return_value={"valid": True}), \
             patch("app.api.v1.rides.get_route",
                   new_callable=AsyncMock,
                   return_value={"distance_km": 5.0, "duration_min": 12.0}), \
             patch("app.api.v1.rides.get_redis", new_callable=AsyncMock), \
             patch("app.api.v1.rides.record_demand", new_callable=AsyncMock), \
             patch("app.api.v1.rides.get_demand_info",
                   new_callable=AsyncMock,
                   return_value=MagicMock(multiplier=1.0, explanation="")), \
             patch("app.api.v1.rides.calculate_fare_breakdown",
                   return_value=MagicMock(total=10.0, base=5.0, distance=3.0,
                                          time=2.0, multiplier=1.0,
                                          multiplier_label="", demand_multiplier=1.0,
                                          demand_label="", subtotal=10.0,
                                          platform_fee=1.0)), \
             patch("app.services.promos.get_referral_credit_balance",
                   new_callable=AsyncMock,
                   return_value=0.0), \
             patch("app.api.v1.rides.get_preferences_for_ride",
                   new_callable=AsyncMock,
                   return_value=None), \
             patch("app.api.v1.rides.Ride", return_value=ride_obj) as MockRide, \
             patch("app.services.audit_events.audit_ride_requested",
                   new_callable=AsyncMock):

            db.add = MagicMock()
            db.commit = AsyncMock()
            db.refresh = AsyncMock()

            await request_ride(
                req=req,
                background_tasks=background_tasks,
                user=user,
                db=db,
            )

        call_kwargs = MockRide.call_args[1]
        assert call_kwargs["accessibility_required"] is False
