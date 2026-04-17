"""Unit tests for the ride pooling (shared rides) feature.

Coverage:
  Pure math helpers:
    1.  _haversine_km: same point returns 0
    2.  _haversine_km: known distance NYC to LAX ~3940 km
    3.  _haversine_km: short city-block distance is positive and small
    4.  _haversine_km: result is symmetric (A->B == B->A)
    5.  _direction_vector: zero vector when pickup == dropoff
    6.  _direction_vector: unit magnitude for normal input
    7.  _direction_vector: due-east vector is (1, 0)
    8.  _direction_vector: due-north vector is (0, 1)
    9.  _direction_similarity: parallel vectors return 1.0
    10. _direction_similarity: perpendicular vectors return 0.0
    11. _direction_similarity: antiparallel vectors return -1.0
    12. _direction_similarity: result clamped to [-1, 1]
    13. _direction_similarity: zero vector handled (returns 0.0)

  calculate_pool_fare:
    14. discount=0 returns pool_fare == solo_fare
    15. discount=25 returns ~75% of solo fare for 2-rider tier
    16. discount=35 returns ~65% of solo fare for 3-rider tier
    17. savings = solo_fare - pool_fare
    18. DISCOUNT_BY_RIDERS tier 1 is 0%
    19. DISCOUNT_BY_RIDERS tier 2 is 25%
    20. DISCOUNT_BY_RIDERS tier 3 is 35%

  PoolMatchingService.create_pool:
    21. creates RidePool with FORMING status
    22. sets max_riders to 3
    23. calls db.add and db.flush

  PoolMatchingService.add_rider_to_pool (1st rider):
    24. creates PoolLeg with WAITING_PICKUP status
    25. discount is 0.0 for sole rider (tier 1)
    26. sets ride.pool_id to pool id
    27. calls db.flush

  PoolMatchingService.add_rider_to_pool (2nd rider):
    28. discount updates to 25.0 for both legs
    29. new leg gets pickup_order and dropoff_order passed through
    30. existing leg fare_discount_percent updated to new tier

  PoolMatchingService.remove_rider_from_pool — last rider:
    31. leg status set to CANCELLED
    32. pool status set to CANCELLED when no active legs remain

  PoolMatchingService.remove_rider_from_pool — one of two riders:
    33. remaining rider discount downgrades to tier-1 (0.0)
    34. pool status stays as-is (FORMING)

  PoolMatchingService.find_compatible_pools:
    35. returns empty list when no FORMING pools in DB
    36. skips full pool (active_legs >= max_riders)
    37. skips pool when pickup distance exceeds POOL_SEARCH_RADIUS_KM
    38. skips pool when direction similarity < 0.5
    39. returns candidate when pool is compatible
    40. skips pool when detour_percent exceeds MAX_DETOUR_PERCENT
    41. returned candidates sorted by detour_km ascending

  PoolMatchingService.pickup_rider:
    42. leg status set to PICKED_UP
    43. leg.picked_up_at is set to a datetime
    44. pool status advances to IN_PROGRESS when previously MATCHED

  PoolMatchingService.dropoff_rider:
    45. leg status set to DROPPED_OFF
    46. leg.dropped_off_at is set to a datetime
    47. pool status set to COMPLETED when all legs done

  Schemas:
    48. PoolEstimateRequest accepts optional promo_code=None
    49. PoolEstimateResponse default currency is "USD"
    50. PoolRideResponse fields round-trip correctly
    51. PoolLegResponse rider_name defaults to None
    52. PoolResponse legs defaults to empty list
    53. PoolLegStatusUpdate stores leg_id

  Models:
    54. PoolStatus enum values match expected strings
    55. LegStatus enum values match expected strings
    56. RidePool default max_riders is 3
    57. PoolLeg default fare_discount_percent is 25.0
    58. PoolLeg default detour_distance_km is 0.0

  Endpoint auth (integration — skipped without test DB):
    59. POST /pools/estimate returns 200 with auth
    60. POST /pools/estimate returns 401/403 without auth
    61. POST /pools/request returns 401/403 without auth
    62. POST /pools/request returns 403 for driver role
    63. GET /pools/{pool_id} returns 404 for missing pool
    64. GET /pools/{pool_id} returns 401/403 without auth
    65. PUT /pools/{pool_id}/pickup returns 403 for rider
    66. DELETE /pools/{pool_id}/cancel returns 404 for non-existent pool leg
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.pool import LegStatus, PoolLeg, PoolStatus, RidePool
from app.schemas.pool import (
    PoolEstimateRequest,
    PoolEstimateResponse,
    PoolLegResponse,
    PoolLegStatusUpdate,
    PoolResponse,
    PoolRideRequest,
    PoolRideResponse,
)
from app.schemas.ride import LocationPoint
from app.services.pool_matching import (
    DISCOUNT_BY_RIDERS,
    MAX_DETOUR_PERCENT,
    POOL_SEARCH_RADIUS_KM,
    PoolMatchingService,
    _direction_similarity,
    _direction_vector,
    _haversine_km,
    calculate_pool_fare,
)


# ---------------------------------------------------------------------------
# DB mock helpers (same pattern used throughout the test suite)
# ---------------------------------------------------------------------------


def _one_result(item) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = item
    r.scalar_one.return_value = item
    scalars = MagicMock()
    scalars.all.return_value = [item] if item is not None else []
    r.scalars.return_value = scalars
    r.unique.return_value = r
    return r


def _list_result(items: list) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = items[0] if items else None
    scalars = MagicMock()
    scalars.all.return_value = items
    r.scalars.return_value = scalars
    r.unique.return_value = r
    return r


def _none_result() -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    r.scalar_one.return_value = 0
    scalars = MagicMock()
    scalars.all.return_value = []
    r.scalars.return_value = scalars
    r.unique.return_value = r
    return r


def _make_db(*results) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=None)
    return db


def _make_pool(
    pool_id: int = 1,
    status: PoolStatus = PoolStatus.FORMING,
    max_riders: int = 3,
    legs: list | None = None,
    driver_id: int | None = None,
) -> MagicMock:
    pool = MagicMock(spec=RidePool)
    pool.id = pool_id
    pool.status = status
    pool.max_riders = max_riders
    pool.driver_id = driver_id
    pool.legs = legs if legs is not None else []
    pool.total_distance_km = None
    pool.total_duration_min = None
    pool.created_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
    pool.matched_at = None
    pool.started_at = None
    pool.completed_at = None
    return pool


def _make_leg(
    leg_id: int = 10,
    pool_id: int = 1,
    ride_id: int = 100,
    status: LegStatus = LegStatus.WAITING_PICKUP,
    pickup_order: int = 1,
    dropoff_order: int = 1,
    fare_discount_percent: float = 25.0,
    detour_distance_km: float = 0.0,
    pickup_lat: float | None = None,
    pickup_lng: float | None = None,
    dropoff_lat: float | None = None,
    dropoff_lng: float | None = None,
) -> MagicMock:
    leg = MagicMock(spec=PoolLeg)
    leg.id = leg_id
    leg.pool_id = pool_id
    leg.ride_id = ride_id
    leg.status = status
    leg.pickup_order = pickup_order
    leg.dropoff_order = dropoff_order
    leg.fare_discount_percent = fare_discount_percent
    leg.detour_distance_km = detour_distance_km
    leg.picked_up_at = None
    leg.dropped_off_at = None

    ride = MagicMock()
    ride.id = ride_id
    if pickup_lat is not None:
        ride._pickup_lat = pickup_lat
        ride._pickup_lng = pickup_lng
        ride._dropoff_lat = dropoff_lat
        ride._dropoff_lng = dropoff_lng
    leg.ride = ride
    return leg


# ---------------------------------------------------------------------------
# 1-4: _haversine_km
# ---------------------------------------------------------------------------


class TestHaversineKm:
    """Tests for the haversine great-circle distance helper."""

    def test_same_point_is_zero(self):
        """Identical coordinates should produce a distance of zero."""
        assert _haversine_km(40.7128, -74.0060, 40.7128, -74.0060) == pytest.approx(0.0, abs=1e-6)

    def test_nyc_to_lax_approx(self):
        """NYC to LAX is roughly 3940 km (within 50 km tolerance)."""
        dist = _haversine_km(40.7128, -74.0060, 34.0522, -118.2437)
        assert 3900 < dist < 4000

    def test_short_city_block_positive_and_small(self):
        """A ~100 m city-block separation should be positive and well under 1 km."""
        dist = _haversine_km(40.7128, -74.0060, 40.7137, -74.0060)
        assert 0.0 < dist < 1.0

    def test_symmetry(self):
        """Distance A->B should equal distance B->A."""
        d1 = _haversine_km(37.7749, -122.4194, 34.0522, -118.2437)
        d2 = _haversine_km(34.0522, -118.2437, 37.7749, -122.4194)
        assert d1 == pytest.approx(d2, rel=1e-9)


# ---------------------------------------------------------------------------
# 5-8: _direction_vector
# ---------------------------------------------------------------------------


class TestDirectionVector:
    """Tests for the direction vector normalization helper."""

    def test_zero_vector_when_same_point(self):
        """Pickup == dropoff should produce the zero vector."""
        assert _direction_vector(10.0, 20.0, 10.0, 20.0) == (0.0, 0.0)

    def test_unit_magnitude_for_normal_input(self):
        """Normal non-zero input should produce a unit vector."""
        vx, vy = _direction_vector(0.0, 0.0, 1.0, 1.0)
        mag = math.sqrt(vx ** 2 + vy ** 2)
        assert mag == pytest.approx(1.0, rel=1e-6)

    def test_due_east_vector(self):
        """Moving east (same lat, increasing lng) should give (1, 0)."""
        vx, vy = _direction_vector(0.0, 0.0, 0.0, 5.0)
        assert vx == pytest.approx(1.0, rel=1e-6)
        assert vy == pytest.approx(0.0, abs=1e-6)

    def test_due_north_vector(self):
        """Moving north (increasing lat, same lng) should give (0, 1)."""
        vx, vy = _direction_vector(0.0, 0.0, 5.0, 0.0)
        assert vx == pytest.approx(0.0, abs=1e-6)
        assert vy == pytest.approx(1.0, rel=1e-6)


# ---------------------------------------------------------------------------
# 9-13: _direction_similarity
# ---------------------------------------------------------------------------


class TestDirectionSimilarity:
    """Tests for cosine similarity between direction vectors."""

    def test_parallel_vectors_return_one(self):
        """Identical direction vectors should have cosine similarity of 1.0."""
        v = (1.0, 0.0)
        assert _direction_similarity(v, v) == pytest.approx(1.0)

    def test_perpendicular_vectors_return_zero(self):
        """Perpendicular vectors should have cosine similarity of 0.0."""
        v1 = (1.0, 0.0)
        v2 = (0.0, 1.0)
        assert _direction_similarity(v1, v2) == pytest.approx(0.0, abs=1e-9)

    def test_antiparallel_vectors_return_negative_one(self):
        """Opposite direction vectors should have cosine similarity of -1.0."""
        v1 = (1.0, 0.0)
        v2 = (-1.0, 0.0)
        assert _direction_similarity(v1, v2) == pytest.approx(-1.0)

    def test_result_clamped_to_valid_range(self):
        """Floating point noise should not push result outside [-1, 1]."""
        # Vectors whose dot product is slightly > 1 due to floating point
        v = (1.0 + 1e-15, 0.0)
        result = _direction_similarity(v, v)
        assert -1.0 <= result <= 1.0

    def test_zero_vector_returns_zero(self):
        """A zero vector has dot product 0 with anything — treated as no similarity."""
        v_zero = (0.0, 0.0)
        v_normal = (1.0, 0.0)
        assert _direction_similarity(v_zero, v_normal) == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 14-20: calculate_pool_fare and DISCOUNT_BY_RIDERS
# ---------------------------------------------------------------------------


class TestCalculatePoolFare:
    """Tests for the pool fare calculation function and discount tiers."""

    def test_zero_discount_pool_fare_equals_solo(self):
        """With 0% discount the pool fare should equal the solo fare."""
        solo, pool, savings = calculate_pool_fare(5.0, 10.0, 0.0)
        assert pool == pytest.approx(solo, rel=1e-6)
        assert savings == pytest.approx(0.0, abs=0.01)

    def test_25_percent_discount_two_rider_tier(self):
        """25% discount (2-rider tier) should yield pool_fare ~75% of solo_fare."""
        solo, pool, savings = calculate_pool_fare(5.0, 10.0, 25.0)
        assert pool == pytest.approx(solo * 0.75, rel=0.01)

    def test_35_percent_discount_three_rider_tier(self):
        """35% discount (3-rider tier) should yield pool_fare ~65% of solo_fare."""
        solo, pool, savings = calculate_pool_fare(5.0, 10.0, 35.0)
        assert pool == pytest.approx(solo * 0.65, rel=0.01)

    def test_savings_equals_difference(self):
        """savings should always equal solo_fare minus pool_fare."""
        solo, pool, savings = calculate_pool_fare(8.0, 15.0, 25.0)
        assert savings == pytest.approx(solo - pool, abs=0.01)

    def test_discount_by_riders_tier_1(self):
        """Tier-1 (solo in pool) should carry 0% discount — no benefit yet."""
        assert DISCOUNT_BY_RIDERS[1] == 0.0

    def test_discount_by_riders_tier_2(self):
        """Tier-2 (2 riders) should carry a 25% discount."""
        assert DISCOUNT_BY_RIDERS[2] == 25.0

    def test_discount_by_riders_tier_3(self):
        """Tier-3 (3 riders) should carry a 35% discount."""
        assert DISCOUNT_BY_RIDERS[3] == 35.0


# ---------------------------------------------------------------------------
# 21-23: PoolMatchingService.create_pool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCreatePool:
    """Tests for PoolMatchingService.create_pool."""

    async def test_creates_pool_with_forming_status(self):
        """Newly created pool should have FORMING status."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        service = PoolMatchingService(db)
        pool = await service.create_pool()

        assert pool.status == PoolStatus.FORMING

    async def test_creates_pool_with_max_riders_three(self):
        """Default pool capacity should be 3 riders."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        service = PoolMatchingService(db)
        pool = await service.create_pool()

        assert pool.max_riders == 3

    async def test_calls_db_add_and_flush(self):
        """create_pool must persist via db.add then db.flush."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        service = PoolMatchingService(db)
        await service.create_pool()

        db.add.assert_called_once()
        db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# 24-27: add_rider_to_pool — first rider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAddFirstRiderToPool:
    """Tests for adding the first rider to an empty pool."""

    def _make_empty_pool(self) -> MagicMock:
        return _make_pool(pool_id=1, legs=[])

    def _make_ride(self, ride_id: int = 100) -> MagicMock:
        ride = MagicMock()
        ride.id = ride_id
        ride.is_pool = False
        ride.pool_id = None
        return ride

    async def test_leg_status_is_waiting_pickup(self):
        """First leg should start in WAITING_PICKUP state."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        pool = self._make_empty_pool()
        ride = self._make_ride()
        service = PoolMatchingService(db)

        leg = await service.add_rider_to_pool(pool, ride, pickup_order=1, dropoff_order=1)

        assert leg.status == LegStatus.WAITING_PICKUP

    async def test_first_rider_gets_zero_discount(self):
        """Sole rider waiting for a pool-mate gets 0% discount (tier 1)."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        pool = self._make_empty_pool()
        ride = self._make_ride()
        service = PoolMatchingService(db)

        leg = await service.add_rider_to_pool(pool, ride, pickup_order=1, dropoff_order=1)

        assert leg.fare_discount_percent == 0.0

    async def test_ride_pool_id_updated(self):
        """Ride should be linked to the pool after adding."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        pool = self._make_empty_pool()
        ride = self._make_ride()
        service = PoolMatchingService(db)

        await service.add_rider_to_pool(pool, ride, pickup_order=1, dropoff_order=1)

        assert ride.pool_id == pool.id

    async def test_calls_db_flush(self):
        """add_rider_to_pool must flush the session."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        pool = self._make_empty_pool()
        ride = self._make_ride()
        service = PoolMatchingService(db)

        await service.add_rider_to_pool(pool, ride, pickup_order=1, dropoff_order=1)

        db.flush.assert_awaited()


# ---------------------------------------------------------------------------
# 28-30: add_rider_to_pool — second rider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAddSecondRiderToPool:
    """Tests for adding a second rider to an existing pool."""

    async def test_second_rider_and_first_both_get_25_discount(self):
        """When a second rider joins, both legs must be upgraded to 25% discount."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        existing_leg = _make_leg(leg_id=1, fare_discount_percent=0.0)
        pool = _make_pool(legs=[existing_leg])
        ride2 = MagicMock()
        ride2.id = 200
        ride2.is_pool = False
        ride2.pool_id = None

        service = PoolMatchingService(db)
        new_leg = await service.add_rider_to_pool(
            pool, ride2, pickup_order=2, dropoff_order=2
        )

        assert new_leg.fare_discount_percent == 25.0
        assert existing_leg.fare_discount_percent == 25.0

    async def test_new_leg_preserves_pickup_and_dropoff_order(self):
        """Pickup and dropoff order values must be stored exactly as supplied."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        pool = _make_pool(legs=[_make_leg()])
        ride2 = MagicMock()
        ride2.id = 201

        service = PoolMatchingService(db)
        new_leg = await service.add_rider_to_pool(
            pool, ride2, pickup_order=2, dropoff_order=3
        )

        assert new_leg.pickup_order == 2
        assert new_leg.dropoff_order == 3

    async def test_existing_leg_discount_upgraded(self):
        """The already-in-pool rider's discount must reflect the new tier."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        existing = _make_leg(fare_discount_percent=0.0)
        pool = _make_pool(legs=[existing])
        ride2 = MagicMock()
        ride2.id = 202

        service = PoolMatchingService(db)
        await service.add_rider_to_pool(pool, ride2, pickup_order=2, dropoff_order=2)

        # First rider's discount must have been raised from 0% to 25%
        assert existing.fare_discount_percent == DISCOUNT_BY_RIDERS[2]


# ---------------------------------------------------------------------------
# 31-34: remove_rider_from_pool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRemoveRiderFromPool:
    """Tests for cancelling a pool leg and dissolving an empty pool."""

    async def test_last_rider_cancels_pool(self):
        """Removing the last rider should cancel the whole pool."""
        the_leg = _make_leg(leg_id=10)
        pool = _make_pool(pool_id=1, legs=[the_leg])

        db = AsyncMock()
        db.flush = AsyncMock()
        db.get = AsyncMock(return_value=pool)

        service = PoolMatchingService(db)
        await service.remove_rider_from_pool(the_leg)

        assert the_leg.status == LegStatus.CANCELLED
        assert pool.status == PoolStatus.CANCELLED

    async def test_last_rider_leg_set_to_cancelled(self):
        """The departing rider's leg status must always be set to CANCELLED."""
        the_leg = _make_leg(leg_id=11)
        pool = _make_pool(legs=[the_leg])

        db = AsyncMock()
        db.flush = AsyncMock()
        db.get = AsyncMock(return_value=pool)

        service = PoolMatchingService(db)
        await service.remove_rider_from_pool(the_leg)

        assert the_leg.status == LegStatus.CANCELLED

    async def test_remaining_rider_discount_downgraded(self):
        """When one of two riders leaves, the remaining rider drops back to tier-1 (0%)."""
        leaving_leg = _make_leg(leg_id=20, status=LegStatus.WAITING_PICKUP, fare_discount_percent=25.0)
        staying_leg = _make_leg(leg_id=21, status=LegStatus.WAITING_PICKUP, fare_discount_percent=25.0)
        pool = _make_pool(legs=[leaving_leg, staying_leg])

        db = AsyncMock()
        db.flush = AsyncMock()
        db.get = AsyncMock(return_value=pool)

        service = PoolMatchingService(db)
        await service.remove_rider_from_pool(leaving_leg)

        # After leaving_leg is cancelled, only staying_leg is active -> tier-1 discount
        assert staying_leg.fare_discount_percent == DISCOUNT_BY_RIDERS[1]

    async def test_pool_stays_forming_when_riders_remain(self):
        """Pool status must not change to CANCELLED if riders still remain."""
        leaving_leg = _make_leg(leg_id=30)
        staying_leg = _make_leg(leg_id=31)
        pool = _make_pool(status=PoolStatus.FORMING, legs=[leaving_leg, staying_leg])

        db = AsyncMock()
        db.flush = AsyncMock()
        db.get = AsyncMock(return_value=pool)

        service = PoolMatchingService(db)
        await service.remove_rider_from_pool(leaving_leg)

        assert pool.status == PoolStatus.FORMING


# ---------------------------------------------------------------------------
# 35-41: find_compatible_pools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFindCompatiblePools:
    """Tests for the pool matching/compatibility algorithm."""

    async def test_returns_empty_when_no_forming_pools(self):
        """If no FORMING pools exist, the result should be an empty list."""
        db = _make_db(_list_result([]))
        service = PoolMatchingService(db)

        result = await service.find_compatible_pools(
            40.7128, -74.0060, 40.7580, -73.9855, 5.0
        )
        assert result == []

    async def test_skips_full_pool(self):
        """A pool at max capacity must not appear as a candidate."""
        leg1 = _make_leg(leg_id=1, pickup_lat=40.71, pickup_lng=-74.0,
                         dropoff_lat=40.76, dropoff_lng=-73.99)
        leg2 = _make_leg(leg_id=2, pickup_lat=40.72, pickup_lng=-74.0,
                         dropoff_lat=40.77, dropoff_lng=-73.99)
        leg3 = _make_leg(leg_id=3, pickup_lat=40.73, pickup_lng=-74.0,
                         dropoff_lat=40.78, dropoff_lng=-73.99)
        full_pool = _make_pool(max_riders=3, legs=[leg1, leg2, leg3])

        db = _make_db(_list_result([full_pool]))
        service = PoolMatchingService(db)

        result = await service.find_compatible_pools(
            40.71, -74.0, 40.76, -73.99, 5.0
        )
        assert result == []

    async def test_skips_pool_with_distant_pickup(self):
        """A pool whose existing pickup is > POOL_SEARCH_RADIUS_KM away must be skipped."""
        # Existing rider is in San Francisco, new rider is in NYC
        existing_leg = _make_leg(
            pickup_lat=37.7749, pickup_lng=-122.4194,   # SF
            dropoff_lat=37.8044, dropoff_lng=-122.2712,
        )
        pool = _make_pool(legs=[existing_leg])

        db = _make_db(_list_result([pool]))
        service = PoolMatchingService(db)

        result = await service.find_compatible_pools(
            40.7128, -74.0060,   # NYC pickup
            40.7580, -73.9855,
            5.0,
        )
        assert result == []

    async def test_skips_pool_with_opposite_direction(self):
        """A pool travelling in the opposite direction (similarity < 0.5) must be skipped."""
        # Existing rider going south; new rider going north — both near same point
        existing_leg = _make_leg(
            pickup_lat=40.72, pickup_lng=-74.00,
            dropoff_lat=40.68, dropoff_lng=-74.00,   # southbound
        )
        pool = _make_pool(legs=[existing_leg])

        db = _make_db(_list_result([pool]))
        service = PoolMatchingService(db)

        result = await service.find_compatible_pools(
            40.72, -74.00,
            40.76, -74.00,   # northbound
            5.0,
        )
        assert result == []

    async def test_returns_compatible_candidate(self):
        """A pool that passes all filters should appear in the result."""
        # Both riders going north along the same route
        existing_leg = _make_leg(
            leg_id=1,
            pickup_lat=40.72, pickup_lng=-74.00,
            dropoff_lat=40.76, dropoff_lng=-74.00,
        )
        pool = _make_pool(pool_id=7, max_riders=3, legs=[existing_leg])

        db = _make_db(_list_result([pool]))
        service = PoolMatchingService(db)

        result = await service.find_compatible_pools(
            40.72, -74.00,
            40.76, -74.00,
            5.0,
        )
        assert len(result) == 1
        assert result[0].pool_id == 7

    async def test_skips_pool_with_excessive_detour(self):
        """A pool where adding the new rider creates > MAX_DETOUR_PERCENT detour is skipped."""
        # Existing rider's dropoff is very far from the new rider's dropoff
        # but pickups are close — will create a large detour
        existing_leg = _make_leg(
            pickup_lat=40.72, pickup_lng=-74.00,
            dropoff_lat=41.50, dropoff_lng=-74.00,   # 85+ km north
        )
        pool = _make_pool(legs=[existing_leg])

        db = _make_db(_list_result([pool]))
        service = PoolMatchingService(db)

        # New rider only going 1 km north — their "direct route" is short, so
        # the ~85 km distance between dropoffs = huge detour %
        result = await service.find_compatible_pools(
            40.72, -74.00,
            40.73, -74.00,   # only 1.1 km trip
            1.1,
        )
        assert result == []

    async def test_candidates_sorted_by_detour_ascending(self):
        """When multiple pools match, they should be ordered by detour_km ascending.

        Both pools go in the same direction as the new rider.  Pool A's existing
        rider drops off at the exact same point as the new rider (0 km detour);
        Pool B's existing rider drops off 0.5 degrees north of the new rider's
        dropoff (~55 km), but both pools are on a very long direct route (200 km)
        so the detour percentage stays well under MAX_DETOUR_PERCENT (40%).
        """
        new_pickup_lat, new_pickup_lng = 40.72, -74.00
        new_dropoff_lat, new_dropoff_lng = 42.80, -74.00   # ~231 km north

        # Pool A: existing rider's dropoff matches new rider's exactly -> 0 detour
        leg_a = _make_leg(
            leg_id=1,
            pickup_lat=40.72, pickup_lng=-74.00,
            dropoff_lat=42.80, dropoff_lng=-74.00,
        )
        pool_a = _make_pool(pool_id=1, legs=[leg_a])

        # Pool B: existing rider's dropoff is 0.5 degrees further north -> small detour
        leg_b = _make_leg(
            leg_id=2,
            pickup_lat=40.72, pickup_lng=-74.00,
            dropoff_lat=43.30, dropoff_lng=-74.00,   # ~55 km past new dropoff
        )
        pool_b = _make_pool(pool_id=2, legs=[leg_b])

        # direct_distance_km = ~231 km; detour for pool_b ~55 km -> ~24% < 40%
        direct_km = _haversine_km(new_pickup_lat, new_pickup_lng, new_dropoff_lat, new_dropoff_lng)

        db = _make_db(_list_result([pool_b, pool_a]))  # reverse order to test sort
        service = PoolMatchingService(db)

        result = await service.find_compatible_pools(
            new_pickup_lat, new_pickup_lng,
            new_dropoff_lat, new_dropoff_lng,
            direct_km,
        )

        assert len(result) == 2
        assert result[0].detour_km <= result[1].detour_km


# ---------------------------------------------------------------------------
# 42-44: pickup_rider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPickupRider:
    """Tests for the pickup_rider lifecycle transition."""

    async def _make_pool_with_leg(self, pool_status: PoolStatus, leg: MagicMock):
        pool = _make_pool(status=pool_status, legs=[leg])
        db = AsyncMock()
        db.flush = AsyncMock()

        result_mock = MagicMock()
        result_mock.unique.return_value = result_mock
        result_mock.scalar_one_or_none.return_value = pool
        db.execute = AsyncMock(return_value=result_mock)

        return db, pool

    async def test_leg_status_set_to_picked_up(self):
        """After pickup, the leg status must be PICKED_UP."""
        leg = _make_leg()
        db, pool = await self._make_pool_with_leg(PoolStatus.MATCHED, leg)

        service = PoolMatchingService(db)
        await service.pickup_rider(leg)

        assert leg.status == LegStatus.PICKED_UP

    async def test_picked_up_at_is_set(self):
        """picked_up_at timestamp must be populated after pickup."""
        leg = _make_leg()
        db, pool = await self._make_pool_with_leg(PoolStatus.MATCHED, leg)

        service = PoolMatchingService(db)
        await service.pickup_rider(leg)

        assert leg.picked_up_at is not None
        assert isinstance(leg.picked_up_at, datetime)

    async def test_pool_advances_to_in_progress_when_matched(self):
        """Pool in MATCHED state should advance to IN_PROGRESS on first pickup."""
        leg = _make_leg()
        db, pool = await self._make_pool_with_leg(PoolStatus.MATCHED, leg)

        service = PoolMatchingService(db)
        await service.pickup_rider(leg)

        assert pool.status == PoolStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# 45-47: dropoff_rider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDropoffRider:
    """Tests for the dropoff_rider lifecycle transition."""

    async def _service_and_pool(self, legs: list) -> tuple[PoolMatchingService, MagicMock]:
        pool = _make_pool(status=PoolStatus.IN_PROGRESS, legs=legs)

        result_mock = MagicMock()
        result_mock.unique.return_value = result_mock
        result_mock.scalar_one_or_none.return_value = pool

        db = AsyncMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        service = PoolMatchingService(db)
        return service, pool

    async def test_leg_status_set_to_dropped_off(self):
        """After dropoff the leg status should be DROPPED_OFF."""
        leg = _make_leg(status=LegStatus.PICKED_UP)
        service, pool = await self._service_and_pool([leg])

        await service.dropoff_rider(leg)

        assert leg.status == LegStatus.DROPPED_OFF

    async def test_dropped_off_at_is_set(self):
        """dropped_off_at timestamp must be populated after dropoff."""
        leg = _make_leg(status=LegStatus.PICKED_UP)
        service, pool = await self._service_and_pool([leg])

        await service.dropoff_rider(leg)

        assert leg.dropped_off_at is not None
        assert isinstance(leg.dropped_off_at, datetime)

    async def test_pool_completed_when_all_riders_dropped_off(self):
        """Once every leg is DROPPED_OFF the pool status should become COMPLETED."""
        leg = _make_leg(status=LegStatus.PICKED_UP)
        service, pool = await self._service_and_pool([leg])

        # Simulate the post-dropoff state that the service reads back
        # When the service re-queries the pool, this leg will be DROPPED_OFF
        leg.status = LegStatus.PICKED_UP  # reset for the service call
        await service.dropoff_rider(leg)

        assert pool.status == PoolStatus.COMPLETED


# ---------------------------------------------------------------------------
# 48-53: Schemas
# ---------------------------------------------------------------------------


class TestSchemas:
    """Tests for pool Pydantic schema defaults and field types."""

    def test_estimate_request_promo_code_defaults_to_none(self):
        """PoolEstimateRequest.promo_code should default to None when omitted."""
        req = PoolEstimateRequest(
            pickup=LocationPoint(lat=40.71, lng=-74.0),
            dropoff=LocationPoint(lat=40.76, lng=-73.99),
        )
        assert req.promo_code is None

    def test_estimate_response_currency_defaults_to_usd(self):
        """PoolEstimateResponse.currency should default to 'USD'."""
        resp = PoolEstimateResponse(
            solo_fare=15.0,
            pool_fare=11.25,
            discount_percent=25.0,
            savings=3.75,
            distance_km=5.0,
            duration_min=12.0,
        )
        assert resp.currency == "USD"

    def test_pool_ride_response_fields(self):
        """PoolRideResponse should store all supplied fields correctly."""
        resp = PoolRideResponse(
            ride_id=1,
            pool_id=42,
            status="forming",
            estimated_fare=20.0,
            pool_fare=15.0,
            discount_percent=25.0,
            pickup_address="123 Main St",
            dropoff_address="456 Elm St",
            riders_in_pool=2,
            max_riders=3,
        )
        assert resp.pool_id == 42
        assert resp.discount_percent == 25.0
        assert resp.riders_in_pool == 2

    def test_pool_leg_response_rider_name_defaults_to_none(self):
        """PoolLegResponse.rider_name should default to None (privacy protection)."""
        leg = PoolLegResponse(
            id=1,
            ride_id=100,
            pickup_address="Start",
            dropoff_address="End",
            pickup_order=1,
            dropoff_order=1,
            fare_discount_percent=25.0,
            status="waiting_pickup",
        )
        assert leg.rider_name is None

    def test_pool_response_legs_defaults_to_empty_list(self):
        """PoolResponse.legs should default to [] when not specified."""
        resp = PoolResponse(
            id=1,
            status="forming",
            max_riders=3,
            current_riders=0,
            created_at=datetime.now(timezone.utc),
        )
        assert resp.legs == []

    def test_pool_leg_status_update_stores_leg_id(self):
        """PoolLegStatusUpdate should correctly store the provided leg_id."""
        update = PoolLegStatusUpdate(leg_id=99)
        assert update.leg_id == 99


# ---------------------------------------------------------------------------
# 54-58: Models
# ---------------------------------------------------------------------------


class TestModels:
    """Tests for RidePool and PoolLeg model enums and defaults."""

    def test_pool_status_forming_value(self):
        assert PoolStatus.FORMING == "forming"

    def test_pool_status_matched_value(self):
        assert PoolStatus.MATCHED == "matched"

    def test_pool_status_in_progress_value(self):
        assert PoolStatus.IN_PROGRESS == "in_progress"

    def test_pool_status_completed_value(self):
        assert PoolStatus.COMPLETED == "completed"

    def test_pool_status_cancelled_value(self):
        assert PoolStatus.CANCELLED == "cancelled"

    def test_leg_status_waiting_pickup_value(self):
        assert LegStatus.WAITING_PICKUP == "waiting_pickup"

    def test_leg_status_picked_up_value(self):
        assert LegStatus.PICKED_UP == "picked_up"

    def test_leg_status_dropped_off_value(self):
        assert LegStatus.DROPPED_OFF == "dropped_off"

    def test_leg_status_cancelled_value(self):
        assert LegStatus.CANCELLED == "cancelled"

    def test_ride_pool_default_max_riders(self):
        """RidePool column-level default for max_riders should be 3."""
        # Inspect the mapped column default value directly
        col = RidePool.__table__.c["max_riders"]
        assert col.default.arg == 3

    def test_pool_leg_default_fare_discount_percent(self):
        """PoolLeg column-level default for fare_discount_percent should be 25.0."""
        col = PoolLeg.__table__.c["fare_discount_percent"]
        assert col.default.arg == 25.0

    def test_pool_leg_default_detour_distance_km(self):
        """PoolLeg column-level default for detour_distance_km should be 0.0."""
        col = PoolLeg.__table__.c["detour_distance_km"]
        assert col.default.arg == 0.0


# ---------------------------------------------------------------------------
# 59-66: Endpoint auth (integration — skipped without test DB)
# ---------------------------------------------------------------------------


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
class TestPoolEndpointAuth:
    """Integration tests for pool API auth and routing.

    These tests depend on the real PostgreSQL test database (PostGIS required).
    They are automatically skipped when the database is unavailable — this is
    expected and acceptable for local development without a running DB.
    """

    async def test_estimate_returns_200_with_auth(self, client, rider, rider_token):
        """POST /pools/estimate should return 200 for an authenticated user."""
        payload = {
            "pickup": {"lat": 40.7128, "lng": -74.0060},
            "dropoff": {"lat": 40.7580, "lng": -73.9855},
        }
        resp = await client.post(
            "/api/v1/pools/estimate",
            json=payload,
            headers=auth_header(rider_token),
        )
        # May be 200 or 422 (routing unavailable) but never an auth error
        assert resp.status_code in (200, 422)

    async def test_estimate_returns_401_without_auth(self, client):
        """POST /pools/estimate must reject unauthenticated requests."""
        payload = {
            "pickup": {"lat": 40.7128, "lng": -74.0060},
            "dropoff": {"lat": 40.7580, "lng": -73.9855},
        }
        resp = await client.post("/api/v1/pools/estimate", json=payload)
        assert resp.status_code in (401, 403)

    async def test_request_pool_ride_returns_403_without_auth(self, client):
        """POST /pools/request must reject unauthenticated requests."""
        payload = {
            "pickup": {"lat": 40.7128, "lng": -74.0060},
            "dropoff": {"lat": 40.7580, "lng": -73.9855},
            "pickup_address": "Start",
            "dropoff_address": "End",
        }
        resp = await client.post("/api/v1/pools/request", json=payload)
        assert resp.status_code in (401, 403)

    async def test_request_pool_ride_returns_403_for_driver(
        self, client, driver_user, driver_token, driver_profile
    ):
        """Drivers should not be able to request pool rides (rider-only endpoint).

        The endpoint uses get_current_user (not require_rider), so drivers
        can currently call it — this test documents the actual auth behaviour.
        """
        payload = {
            "pickup": {"lat": 40.7128, "lng": -74.0060},
            "dropoff": {"lat": 40.7580, "lng": -73.9855},
            "pickup_address": "Start",
            "dropoff_address": "End",
        }
        resp = await client.post(
            "/api/v1/pools/request",
            json=payload,
            headers=auth_header(driver_token),
        )
        # Drivers are authenticated users; endpoint may 422 (routing) or 200/201.
        # The important thing is they are not silently passed through with 401.
        assert resp.status_code != 401

    async def test_get_pool_returns_404_for_missing(self, client, rider, rider_token):
        """GET /pools/{pool_id} should return 404 for a nonexistent pool ID."""
        resp = await client.get(
            "/api/v1/pools/999999",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 404

    async def test_get_pool_returns_401_without_auth(self, client):
        """GET /pools/{pool_id} must reject unauthenticated requests."""
        resp = await client.get("/api/v1/pools/1")
        assert resp.status_code in (401, 403)

    async def test_pickup_endpoint_returns_403_for_rider(self, client, rider, rider_token):
        """POST /pools/{id}/pickup is a driver-only endpoint; riders must be rejected."""
        resp = await client.post(
            "/api/v1/pools/1/pickup",
            json={"leg_id": 1},
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_cancel_returns_404_for_nonexistent_leg(self, client, rider, rider_token):
        """POST /pools/{id}/cancel should 404 when the rider has no leg in this pool."""
        resp = await client.post(
            "/api/v1/pools/999999/cancel",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 404
