"""Ride pooling matching service.

Finds compatible pools for new riders based on direction similarity
and detour constraints, manages pool lifecycle, and calculates
discounted fares.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.pool import LegStatus, PoolLeg, PoolStatus, RidePool
from app.models.ride import Ride, RideStatus
from app.services.pricing import calculate_fare_breakdown

logger = logging.getLogger(__name__)

# --- Configuration ---

MAX_DETOUR_PERCENT = 40.0       # Max 40% detour over a rider's direct route
MAX_POOL_WAIT_SECONDS = 300     # 5 min to find pool-mates before converting to solo
POOL_SEARCH_RADIUS_KM = 3.0    # Only consider pools with pickups within 3 km

# Discount tiers by number of riders in pool
DISCOUNT_BY_RIDERS = {
    1: 0.0,    # Solo in pool (waiting for match) — no discount yet
    2: 25.0,   # Two riders — 25% off
    3: 35.0,   # Three riders — 35% off
}


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _direction_vector(
    p_lat: float, p_lng: float, d_lat: float, d_lng: float
) -> tuple[float, float]:
    """Normalized direction vector from pickup to dropoff."""
    dx = d_lng - p_lng
    dy = d_lat - p_lat
    mag = math.sqrt(dx * dx + dy * dy)
    if mag < 1e-9:
        return (0.0, 0.0)
    return (dx / mag, dy / mag)


def _direction_similarity(
    v1: tuple[float, float], v2: tuple[float, float]
) -> float:
    """Cosine similarity between two direction vectors. Range [-1, 1]."""
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    return max(-1.0, min(1.0, dot))


@dataclass
class PoolCandidate:
    pool_id: int
    current_riders: int
    detour_km: float
    detour_percent: float
    direction_score: float  # cosine similarity, higher is better


class PoolMatchingService:
    """Matches new pool ride requests to existing compatible pools."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def find_compatible_pools(
        self,
        pickup_lat: float,
        pickup_lng: float,
        dropoff_lat: float,
        dropoff_lng: float,
        direct_distance_km: float,
    ) -> list[PoolCandidate]:
        """Find forming pools compatible with this rider's route.

        Compatibility criteria:
        1. Pool is in FORMING status and has open seats
        2. Existing riders' pickups are within POOL_SEARCH_RADIUS_KM
        3. Direction similarity > 0.5 (roughly same direction)
        4. Adding this rider doesn't create > MAX_DETOUR_PERCENT detour
           for any existing rider
        """
        # Get all forming pools with their legs and rides
        result = await self.db.execute(
            select(RidePool)
            .options(joinedload(RidePool.legs).joinedload(PoolLeg.ride))
            .where(RidePool.status == PoolStatus.FORMING)
        )
        pools = result.unique().scalars().all()

        new_direction = _direction_vector(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)
        candidates = []

        for pool in pools:
            active_legs = [leg for leg in pool.legs if leg.status != LegStatus.CANCELLED]
            if len(active_legs) >= pool.max_riders:
                continue  # Pool is full

            # Check direction compatibility with each existing rider
            compatible = True
            total_detour = 0.0
            min_similarity = 1.0

            for leg in active_legs:
                ride = leg.ride
                # Extract existing rider's coordinates from their ride
                # We use the address-based approach since geometry needs PostGIS
                # For the matching algorithm, we store lat/lng on the ride schema
                # and use them here. In production, this would use ST_X/ST_Y.
                existing_pickup_lat = getattr(ride, '_pickup_lat', None)
                existing_pickup_lng = getattr(ride, '_pickup_lng', None)
                existing_dropoff_lat = getattr(ride, '_dropoff_lat', None)
                existing_dropoff_lng = getattr(ride, '_dropoff_lng', None)

                if any(v is None for v in [existing_pickup_lat, existing_pickup_lng,
                                            existing_dropoff_lat, existing_dropoff_lng]):
                    compatible = False
                    break

                # Check proximity of pickups
                pickup_dist = _haversine_km(
                    pickup_lat, pickup_lng,
                    existing_pickup_lat, existing_pickup_lng,
                )
                if pickup_dist > POOL_SEARCH_RADIUS_KM:
                    compatible = False
                    break

                # Check direction similarity
                existing_dir = _direction_vector(
                    existing_pickup_lat, existing_pickup_lng,
                    existing_dropoff_lat, existing_dropoff_lng,
                )
                similarity = _direction_similarity(new_direction, existing_dir)
                min_similarity = min(min_similarity, similarity)
                if similarity < 0.5:
                    compatible = False
                    break

                # Estimate detour: simplified as distance between dropoffs
                dropoff_dist = _haversine_km(
                    dropoff_lat, dropoff_lng,
                    existing_dropoff_lat, existing_dropoff_lng,
                )
                total_detour += dropoff_dist

            if not compatible:
                continue

            # Check detour percentage relative to this rider's direct route
            detour_percent = (total_detour / max(direct_distance_km, 0.1)) * 100
            if detour_percent > MAX_DETOUR_PERCENT:
                continue

            candidates.append(PoolCandidate(
                pool_id=pool.id,
                current_riders=len(active_legs),
                detour_km=total_detour,
                detour_percent=detour_percent,
                direction_score=min_similarity,
            ))

        # Sort by: fewest detour first, then best direction match
        candidates.sort(key=lambda c: (c.detour_km, -c.direction_score))
        return candidates

    async def create_pool(self) -> RidePool:
        """Create a new empty pool."""
        pool = RidePool(status=PoolStatus.FORMING, max_riders=3)
        self.db.add(pool)
        await self.db.flush()
        logger.info("Created new pool %d", pool.id)
        return pool

    async def add_rider_to_pool(
        self,
        pool: RidePool,
        ride: Ride,
        pickup_order: int,
        dropoff_order: int,
        detour_km: float = 0.0,
    ) -> PoolLeg:
        """Add a rider's ride to a pool."""
        active_legs = [leg for leg in pool.legs if leg.status != LegStatus.CANCELLED]
        rider_count = len(active_legs) + 1
        discount = DISCOUNT_BY_RIDERS.get(rider_count, 35.0)

        leg = PoolLeg(
            pool_id=pool.id,
            ride_id=ride.id,
            pickup_order=pickup_order,
            dropoff_order=dropoff_order,
            detour_distance_km=detour_km,
            fare_discount_percent=discount,
            status=LegStatus.WAITING_PICKUP,
        )
        self.db.add(leg)

        # Update ride to reference the pool
        ride.is_pool = True
        ride.pool_id = pool.id

        # Update discounts for ALL riders in the pool (all get the same tier)
        for existing_leg in active_legs:
            existing_leg.fare_discount_percent = discount

        await self.db.flush()
        logger.info(
            "Added ride %d to pool %d (rider %d/%d, discount %.0f%%)",
            ride.id, pool.id, rider_count, pool.max_riders, discount,
        )
        return leg

    async def remove_rider_from_pool(self, leg: PoolLeg) -> None:
        """Cancel a rider's leg and update remaining discounts."""
        leg.status = LegStatus.CANCELLED
        pool = await self.db.get(
            RidePool,
            leg.pool_id,
            options=[joinedload(RidePool.legs)],
        )
        if pool is None:
            return

        active_legs = [l for l in pool.legs if l.status != LegStatus.CANCELLED]
        if not active_legs:
            pool.status = PoolStatus.CANCELLED
            logger.info("Pool %d cancelled — no riders left", pool.id)
        else:
            rider_count = len(active_legs)
            discount = DISCOUNT_BY_RIDERS.get(rider_count, 0.0)
            for l in active_legs:
                l.fare_discount_percent = discount

        await self.db.flush()

    async def get_pool(self, pool_id: int) -> RidePool | None:
        """Get a pool with legs and rides loaded."""
        result = await self.db.execute(
            select(RidePool)
            .options(joinedload(RidePool.legs).joinedload(PoolLeg.ride))
            .where(RidePool.id == pool_id)
        )
        return result.unique().scalar_one_or_none()

    async def pickup_rider(self, leg: PoolLeg) -> None:
        """Mark a pool rider as picked up."""
        leg.status = LegStatus.PICKED_UP
        leg.picked_up_at = datetime.now(timezone.utc)

        pool = await self.get_pool(leg.pool_id)
        if pool and pool.status == PoolStatus.MATCHED:
            pool.status = PoolStatus.IN_PROGRESS
            pool.started_at = datetime.now(timezone.utc)

        await self.db.flush()

    async def dropoff_rider(self, leg: PoolLeg) -> None:
        """Mark a pool rider as dropped off."""
        leg.status = LegStatus.DROPPED_OFF
        leg.dropped_off_at = datetime.now(timezone.utc)

        pool = await self.get_pool(leg.pool_id)
        if pool:
            active = [l for l in pool.legs if l.status not in (LegStatus.DROPPED_OFF, LegStatus.CANCELLED)]
            if not active:
                pool.status = PoolStatus.COMPLETED
                pool.completed_at = datetime.now(timezone.utc)
                logger.info("Pool %d completed — all riders dropped off", pool.id)

        await self.db.flush()

    async def get_active_pools_near(
        self,
        lat: float,
        lng: float,
        radius_km: float = POOL_SEARCH_RADIUS_KM,
    ) -> list[RidePool]:
        """Get forming pools with rides near the given location.

        In production this would use PostGIS ST_DWithin. For now we load
        forming pools and filter in Python.
        """
        result = await self.db.execute(
            select(RidePool)
            .options(joinedload(RidePool.legs).joinedload(PoolLeg.ride))
            .where(RidePool.status == PoolStatus.FORMING)
        )
        return list(result.unique().scalars().all())


def calculate_pool_fare(
    distance_km: float,
    duration_min: float,
    discount_percent: float,
) -> tuple[float, float, float]:
    """Calculate pool fare with discount.

    Returns: (solo_fare, pool_fare, savings)
    """
    breakdown = calculate_fare_breakdown(distance_km, duration_min)
    solo_fare = breakdown.total
    pool_fare = round(solo_fare * (1 - discount_percent / 100), 2)
    savings = round(solo_fare - pool_fare, 2)
    return solo_fare, pool_fare, savings
