"""Tests for the pool opt-out ride preference.

Covers:
- Model: pool_opt_out field exists with default False
- Schema: RidePreferenceUpdate and RidePreferenceResponse include pool_opt_out
- Service: default row has pool_opt_out=False; update sets it correctly
- Endpoint: POST /pools/request returns 400 when rider has pool_opt_out=True
            POST /pools/request proceeds when pool_opt_out=False (default)
            POST /pools/request proceeds when rider has no preferences (None)

All tests are pure unit tests — no database required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.ride_preference import RidePreference, TemperaturePreference
from app.schemas.ride_preference import RidePreferenceResponse, RidePreferenceUpdate
from app.services.ride_preferences import get_preferences, update_preferences


# ===========================================================================
# Helpers
# ===========================================================================


def _make_prefs(
    user_id: int = 1,
    pool_opt_out: bool = False,
    accessibility_vehicle_needed: bool = False,
    quiet_ride: bool = False,
) -> MagicMock:
    p = MagicMock(spec=RidePreference)
    p.id = 1
    p.user_id = user_id
    p.quiet_ride = quiet_ride
    p.music_off = False
    p.temperature_preference = TemperaturePreference.NO_PREFERENCE
    p.pet_friendly = False
    p.extra_luggage = False
    p.accessibility_vehicle_needed = accessibility_vehicle_needed
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
# Model
# ===========================================================================


class TestPoolOptOutModel:
    def test_field_exists(self):
        p = RidePreference()
        assert hasattr(p, "pool_opt_out")

    def test_default_is_falsy(self):
        p = RidePreference()
        assert not p.pool_opt_out


# ===========================================================================
# Schema: Update
# ===========================================================================


class TestPoolOptOutUpdateSchema:
    def test_pool_opt_out_optional_defaults_none(self):
        update = RidePreferenceUpdate()
        assert update.pool_opt_out is None

    def test_pool_opt_out_can_be_set_true(self):
        update = RidePreferenceUpdate(pool_opt_out=True)
        assert update.pool_opt_out is True

    def test_pool_opt_out_can_be_set_false(self):
        update = RidePreferenceUpdate(pool_opt_out=False)
        assert update.pool_opt_out is False

    def test_pool_opt_out_independent_of_other_fields(self):
        update = RidePreferenceUpdate(quiet_ride=True, pool_opt_out=True)
        assert update.quiet_ride is True
        assert update.pool_opt_out is True
        assert update.music_off is None


# ===========================================================================
# Schema: Response
# ===========================================================================


class TestPoolOptOutResponseSchema:
    def test_response_includes_pool_opt_out_false(self):
        prefs = _make_prefs(user_id=1, pool_opt_out=False)
        resp = RidePreferenceResponse.model_validate(prefs)
        assert resp.pool_opt_out is False

    def test_response_includes_pool_opt_out_true(self):
        prefs = _make_prefs(user_id=2, pool_opt_out=True)
        resp = RidePreferenceResponse.model_validate(prefs)
        assert resp.pool_opt_out is True

    def test_response_has_pool_opt_out_field(self):
        prefs = _make_prefs()
        resp = RidePreferenceResponse.model_validate(prefs)
        assert hasattr(resp, "pool_opt_out")


# ===========================================================================
# Service: default row includes pool_opt_out=False
# ===========================================================================


class TestPoolOptOutService:
    @pytest.mark.asyncio
    async def test_default_row_has_pool_opt_out_false(self):
        """Newly created default preference has pool_opt_out=False."""
        db = _make_db(row=None)

        await get_preferences(db, user_id=42)

        added = db.add.call_args[0][0]
        assert isinstance(added, RidePreference)
        assert added.pool_opt_out is False

    @pytest.mark.asyncio
    async def test_update_sets_pool_opt_out_true(self):
        """update_preferences can enable pool_opt_out."""
        prefs = _make_prefs(user_id=1, pool_opt_out=False)
        db = _make_db(row=prefs)

        updates = RidePreferenceUpdate(pool_opt_out=True)
        await update_preferences(db, user_id=1, updates=updates)

        assert prefs.pool_opt_out is True
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_sets_pool_opt_out_false(self):
        """update_preferences can disable pool_opt_out."""
        prefs = _make_prefs(user_id=1, pool_opt_out=True)
        db = _make_db(row=prefs)

        updates = RidePreferenceUpdate(pool_opt_out=False)
        await update_preferences(db, user_id=1, updates=updates)

        assert prefs.pool_opt_out is False
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_no_flush_when_same_value(self):
        """No flush if pool_opt_out value is already the same."""
        prefs = _make_prefs(user_id=1, pool_opt_out=True)
        db = _make_db(row=prefs)

        updates = RidePreferenceUpdate(pool_opt_out=True)
        await update_preferences(db, user_id=1, updates=updates)

        db.flush.assert_not_called()


# ===========================================================================
# Endpoint: POST /pools/request enforces pool_opt_out
# ===========================================================================


class TestPoolOptOutEndpoint:
    @pytest.mark.asyncio
    async def test_pool_request_blocked_when_opted_out(self):
        """POST /pools/request returns 400 when rider has pool_opt_out=True."""
        from app.api.v1.pools import request_pool_ride
        from app.schemas.pool import PoolRideRequest

        user = MagicMock()
        user.id = 1
        user.name = "Alice"

        req = MagicMock(spec=PoolRideRequest)
        req.pickup = MagicMock(lat=40.7, lng=-74.0)
        req.dropoff = MagicMock(lat=40.8, lng=-74.0)
        req.pickup_address = "123 Main St"
        req.dropoff_address = "456 Elm St"

        db = AsyncMock()
        prefs = _make_prefs(user_id=1, pool_opt_out=True)

        with patch(
            "app.api.v1.pools.get_preferences_for_ride",
            new_callable=AsyncMock,
            return_value=prefs,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await request_pool_ride(req=req, user=user, db=db)

        assert exc_info.value.status_code == 400
        assert "opted out" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_pool_request_proceeds_when_not_opted_out(self):
        """POST /pools/request proceeds when pool_opt_out=False."""
        from app.api.v1.pools import request_pool_ride
        from app.schemas.pool import PoolRideRequest, PoolRideResponse

        user = MagicMock()
        user.id = 1
        user.name = "Bob"

        req = MagicMock(spec=PoolRideRequest)
        req.pickup = MagicMock(lat=40.7, lng=-74.0)
        req.dropoff = MagicMock(lat=40.8, lng=-74.0)
        req.pickup_address = "123 Main St"
        req.dropoff_address = "456 Elm St"

        db = AsyncMock()
        prefs = _make_prefs(user_id=1, pool_opt_out=False)

        mock_response = MagicMock(spec=PoolRideResponse)

        with patch(
            "app.api.v1.pools.get_preferences_for_ride",
            new_callable=AsyncMock,
            return_value=prefs,
        ), patch(
            "app.api.v1.pools.get_route",
            new_callable=AsyncMock,
            return_value={"distance_km": 5.0, "duration_min": 12.0},
        ), patch(
            "app.api.v1.pools.calculate_fare",
            return_value=8.50,
        ), patch(
            "app.api.v1.pools.PoolMatchingService",
        ) as MockService, patch(
            "app.api.v1.pools.calculate_pool_fare",
            return_value=(8.50, 6.80, 1.70),
        ):
            mock_svc = AsyncMock()
            MockService.return_value = mock_svc
            mock_svc.find_compatible_pools.return_value = []

            mock_pool = MagicMock()
            mock_pool.id = 10
            mock_pool.status.value = "forming"
            mock_pool.max_riders = 3
            mock_svc.create_pool.return_value = mock_pool

            mock_leg = MagicMock()
            mock_leg.fare_discount_percent = 20
            mock_svc.add_rider_to_pool.return_value = mock_leg

            mock_ride = MagicMock()
            mock_ride.id = 99
            db.add = MagicMock()
            db.flush = AsyncMock()
            db.commit = AsyncMock()

            with patch("app.api.v1.pools.Ride") as MockRide:
                MockRide.return_value = mock_ride
                result = await request_pool_ride(req=req, user=user, db=db)

        assert result.pool_id == 10

    @pytest.mark.asyncio
    async def test_pool_request_proceeds_when_no_prefs(self):
        """POST /pools/request proceeds when rider has no preference row (None)."""
        from app.api.v1.pools import request_pool_ride
        from app.schemas.pool import PoolRideRequest

        user = MagicMock()
        user.id = 1
        user.name = "Carol"

        req = MagicMock(spec=PoolRideRequest)
        req.pickup = MagicMock(lat=40.7, lng=-74.0)
        req.dropoff = MagicMock(lat=40.8, lng=-74.0)
        req.pickup_address = "123 Main St"
        req.dropoff_address = "456 Elm St"

        db = AsyncMock()

        with patch(
            "app.api.v1.pools.get_preferences_for_ride",
            new_callable=AsyncMock,
            return_value=None,  # rider has no prefs row
        ), patch(
            "app.api.v1.pools.get_route",
            new_callable=AsyncMock,
            return_value={"distance_km": 5.0, "duration_min": 12.0},
        ), patch(
            "app.api.v1.pools.calculate_fare",
            return_value=8.50,
        ), patch(
            "app.api.v1.pools.PoolMatchingService",
        ) as MockService, patch(
            "app.api.v1.pools.calculate_pool_fare",
            return_value=(8.50, 6.80, 1.70),
        ):
            mock_svc = AsyncMock()
            MockService.return_value = mock_svc
            mock_svc.find_compatible_pools.return_value = []

            mock_pool = MagicMock()
            mock_pool.id = 11
            mock_pool.status.value = "forming"
            mock_pool.max_riders = 3
            mock_svc.create_pool.return_value = mock_pool

            mock_leg = MagicMock()
            mock_leg.fare_discount_percent = 20
            mock_svc.add_rider_to_pool.return_value = mock_leg

            mock_ride = MagicMock()
            mock_ride.id = 100
            db.add = MagicMock()
            db.flush = AsyncMock()
            db.commit = AsyncMock()

            with patch("app.api.v1.pools.Ride") as MockRide:
                MockRide.return_value = mock_ride
                result = await request_pool_ride(req=req, user=user, db=db)

        # No 400 raised; result is returned
        assert result.pool_id == 11
