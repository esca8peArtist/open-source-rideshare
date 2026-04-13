import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import redis.asyncio as redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.driver import DriverProfile
from app.models.driver_availability import DriverOnlineStatus, DriverSchedule
from app.models.ride import Ride, RideStatus
from app.models.vehicle import Vehicle, VehicleServiceCategory

# How old a heartbeat can be before the driver is considered unreachable.
# Must match HEARTBEAT_STALE_MINUTES in services/driver_availability.py.
_HEARTBEAT_STALE_MINUTES = 15

logger = logging.getLogger(__name__)

REDIS_DRIVER_GEO_KEY = "openride:drivers:locations"
REDIS_DRIVER_STATUS_PREFIX = "openride:drivers:status:"
REDIS_RIDE_OFFERS_PREFIX = "openride:rides:offers:"


@dataclass
class DriverCandidate:
    driver_id: int
    user_id: int
    distance_km: float
    rating_avg: float
    total_trips: int
    is_wheelchair_accessible: bool = False
    vehicle_capacity: int = 4
    vehicle_service_category: VehicleServiceCategory = VehicleServiceCategory.STANDARD


class MatchingEngine:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    async def update_driver_location(self, user_id: int, lat: float, lng: float) -> None:
        await self.redis.geoadd(
            REDIS_DRIVER_GEO_KEY, (lng, lat, str(user_id))
        )
        await self.redis.setex(
            f"{REDIS_DRIVER_STATUS_PREFIX}{user_id}",
            settings.driver_location_ttl_seconds,
            "available",
        )

    async def remove_driver(self, user_id: int) -> None:
        await self.redis.zrem(REDIS_DRIVER_GEO_KEY, str(user_id))
        await self.redis.delete(f"{REDIS_DRIVER_STATUS_PREFIX}{user_id}")

    async def set_driver_busy(self, user_id: int) -> None:
        await self.redis.setex(
            f"{REDIS_DRIVER_STATUS_PREFIX}{user_id}",
            settings.driver_location_ttl_seconds,
            "busy",
        )

    async def set_driver_available(self, user_id: int) -> None:
        await self.redis.setex(
            f"{REDIS_DRIVER_STATUS_PREFIX}{user_id}",
            settings.driver_location_ttl_seconds,
            "available",
        )

    async def find_nearby_drivers(
        self,
        lat: float,
        lng: float,
        radius_km: float | None = None,
        limit: int = 10,
    ) -> list[tuple[str, float]]:
        if radius_km is None:
            radius_km = settings.driver_search_radius_km

        results = await self.redis.geosearch(
            REDIS_DRIVER_GEO_KEY,
            longitude=lng,
            latitude=lat,
            radius=radius_km,
            unit="km",
            sort="ASC",
            count=limit,
            withdist=True,
        )
        return results

    async def _filter_available(self, nearby: list[tuple[str, float]]) -> list[tuple[int, float]]:
        available = []
        for member, dist in nearby:
            user_id = int(member)
            status = await self.redis.get(f"{REDIS_DRIVER_STATUS_PREFIX}{user_id}")
            if status == b"available":
                available.append((user_id, dist))
        return available

    async def _get_availability_eligible_driver_ids(
        self,
        db: AsyncSession,
        candidate_driver_ids: list[int],
    ) -> set[int]:
        """Return the subset of driver profile IDs that pass availability checks.

        A driver is eligible when ALL three conditions hold:
          1. DriverOnlineStatus.is_online is True
          2. last_heartbeat is within _HEARTBEAT_STALE_MINUTES
          3. Either they have no active schedule for today, OR the current UTC
             wall-clock time falls within at least one active schedule slot
             (opt-in model — no schedule means always available when online).

        This is a DB-level pre-filter so we avoid N+1 Python-level queries per
        candidate.  The schedule window check still happens in Python after a
        single bulk fetch because time-range logic is simpler there than in a
        cross-DB-compatible WHERE clause.

        TODO: For very high driver counts, consider moving the schedule window
        check into a DB view or a materialized helper table so the full filter
        is executed at the query layer.
        """
        if not candidate_driver_ids:
            return set()

        now = datetime.now(timezone.utc)
        stale_threshold = now - timedelta(minutes=_HEARTBEAT_STALE_MINUTES)
        today_dow = now.weekday()
        now_time = now.time().replace(tzinfo=None)

        # --- Step 1: fetch online-status rows that pass conditions 1 and 2 ---
        status_result = await db.execute(
            select(DriverOnlineStatus).where(
                DriverOnlineStatus.driver_id.in_(candidate_driver_ids),
                DriverOnlineStatus.is_online.is_(True),
                DriverOnlineStatus.last_heartbeat >= stale_threshold,
            )
        )
        online_status_rows = status_result.scalars().all()
        online_driver_ids = {row.driver_id for row in online_status_rows}

        if not online_driver_ids:
            return set()

        # --- Step 2: fetch active schedule slots for today (bulk) ---
        schedule_result = await db.execute(
            select(DriverSchedule).where(
                DriverSchedule.driver_id.in_(online_driver_ids),
                DriverSchedule.day_of_week == today_dow,
                DriverSchedule.is_active.is_(True),
            )
        )
        schedule_rows = schedule_result.scalars().all()

        # Group slots by driver_id for O(1) lookup
        slots_by_driver: dict[int, list[DriverSchedule]] = {}
        for slot in schedule_rows:
            slots_by_driver.setdefault(slot.driver_id, []).append(slot)

        # --- Step 3: apply schedule window check (condition 3) ---
        eligible: set[int] = set()
        for driver_id in online_driver_ids:
            driver_slots = slots_by_driver.get(driver_id)
            if not driver_slots:
                # No schedule set → opt-in model: always available when online
                eligible.add(driver_id)
                continue
            # At least one active slot must contain the current time
            for slot in driver_slots:
                if slot.start_time <= now_time <= slot.end_time:
                    eligible.add(driver_id)
                    break

        return eligible

    async def find_candidates(
        self,
        pickup_lat: float,
        pickup_lng: float,
        db: AsyncSession,
        accessibility_required: bool = False,
        availability_filter: bool = True,
        vehicle_type_preference: VehicleServiceCategory | None = None,
    ) -> list[DriverCandidate]:
        """Find and rank driver candidates for a ride request.

        Parameters
        ----------
        pickup_lat, pickup_lng:
            Coordinates of the pickup location.
        db:
            Async database session.
        accessibility_required:
            When True, only wheelchair-accessible vehicles are returned.
        availability_filter:
            When True (default), restrict results to drivers that are currently
            available according to the DriverOnlineStatus table and any
            configured weekly schedule.  Set to False only for administrative
            or diagnostic purposes.
        vehicle_type_preference:
            When set, only drivers whose active vehicle matches this service
            category are returned.  None means any category is acceptable.
        """
        initial_radius = settings.driver_search_initial_radius_km
        max_radius = settings.driver_search_radius_km
        radius = initial_radius

        available: list[tuple[int, float]] = []
        while radius <= max_radius and not available:
            nearby = await self.find_nearby_drivers(pickup_lat, pickup_lng, radius)
            available = await self._filter_available(nearby)
            if not available:
                radius = min(radius * 2, max_radius) if radius < max_radius else max_radius + 1

        if not available:
            return []

        user_ids = [uid for uid, _ in available]
        dist_map = {uid: d for uid, d in available}

        result = await db.execute(
            select(DriverProfile).where(
                DriverProfile.user_id.in_(user_ids),
                DriverProfile.is_online.is_(True),
                DriverProfile.is_approved.is_(True),
            )
        )
        profiles = result.scalars().all()

        # --- Availability filter: apply DB-level schedule + heartbeat check ---
        if availability_filter and profiles:
            profile_id_set = {p.id for p in profiles}
            eligible_ids = await self._get_availability_eligible_driver_ids(db, list(profile_id_set))
            profiles = [p for p in profiles if p.id in eligible_ids]
            logger.debug(
                "Availability filter: %d/%d driver profiles remain after availability check",
                len(profiles),
                len(profile_id_set),
            )

        # Load active vehicle info for WAV filtering
        profile_ids = [p.id for p in profiles]
        vehicle_map: dict[int, Vehicle] = {}
        if profile_ids:
            v_result = await db.execute(
                select(Vehicle).where(
                    Vehicle.driver_profile_id.in_(profile_ids),
                    Vehicle.is_active.is_(True),
                )
            )
            for v in v_result.scalars().all():
                # Use active_vehicle_id if set, otherwise first active vehicle
                vehicle_map[v.driver_profile_id] = v

        # Resolve to actual active vehicle per profile
        active_vehicles: dict[int, Vehicle] = {}
        for p in profiles:
            if p.active_vehicle_id and p.active_vehicle_id in {
                v.id for v in vehicle_map.values() if v.driver_profile_id == p.id
            }:
                # Active vehicle is explicitly set — find it
                for v in vehicle_map.values():
                    if v.id == p.active_vehicle_id:
                        active_vehicles[p.id] = v
                        break
            elif p.id in vehicle_map:
                active_vehicles[p.id] = vehicle_map[p.id]

        candidates = []
        for p in profiles:
            vehicle = active_vehicles.get(p.id)
            is_wav = vehicle.is_wheelchair_accessible if vehicle else False
            capacity = vehicle.capacity if vehicle else 4
            service_category = (
                vehicle.service_category
                if vehicle
                else VehicleServiceCategory.STANDARD
            )

            # Filter: if accessibility required, skip non-WAV drivers
            if accessibility_required and not is_wav:
                continue

            # Filter: if a vehicle type preference is set, skip non-matching drivers
            if vehicle_type_preference is not None and service_category != vehicle_type_preference:
                continue

            candidates.append(
                DriverCandidate(
                    driver_id=p.id,
                    user_id=p.user_id,
                    distance_km=dist_map.get(p.user_id, 0.0),
                    rating_avg=p.rating_avg,
                    total_trips=p.total_trips,
                    is_wheelchair_accessible=is_wav,
                    vehicle_capacity=capacity,
                    vehicle_service_category=service_category,
                )
            )

        candidates.sort(key=lambda c: (c.distance_km, -c.rating_avg))
        return candidates

    async def offer_ride_to_drivers(
        self,
        ride_id: int,
        candidates: list[DriverCandidate],
        db: AsyncSession,
    ) -> int | None:
        max_offers = min(settings.max_ride_offers, len(candidates))
        offer_key = f"{REDIS_RIDE_OFFERS_PREFIX}{ride_id}"

        for i in range(max_offers):
            candidate = candidates[i]
            offer = {
                "ride_id": ride_id,
                "driver_user_id": candidate.user_id,
                "driver_id": candidate.driver_id,
                "distance_km": candidate.distance_km,
                "status": "pending",
            }
            await self.redis.setex(
                offer_key,
                settings.ride_offer_timeout_seconds,
                json.dumps(offer),
            )

            await asyncio.sleep(settings.ride_offer_timeout_seconds)

            remaining = await self.redis.get(offer_key)
            if remaining:
                offer_data = json.loads(remaining)
                if offer_data.get("status") == "accepted":
                    return candidate.user_id
            # Offer expired or was declined — try next driver

        return None

    async def accept_offer(self, ride_id: int, user_id: int) -> bool:
        offer_key = f"{REDIS_RIDE_OFFERS_PREFIX}{ride_id}"
        raw = await self.redis.get(offer_key)
        if not raw:
            return False

        offer = json.loads(raw)
        if offer.get("driver_user_id") != user_id:
            return False
        if offer.get("status") != "pending":
            return False

        offer["status"] = "accepted"
        ttl = await self.redis.ttl(offer_key)
        if ttl > 0:
            await self.redis.setex(offer_key, ttl, json.dumps(offer))
        else:
            await self.redis.set(offer_key, json.dumps(offer), ex=10)
        return True

    async def match_ride(
        self,
        ride: Ride,
        pickup_lat: float,
        pickup_lng: float,
        db: AsyncSession,
        accessibility_required: bool = False,
        availability_filter: bool = True,
        vehicle_type_preference: VehicleServiceCategory | None = None,
    ) -> DriverCandidate | None:
        candidates = await self.find_candidates(
            pickup_lat,
            pickup_lng,
            db,
            accessibility_required=accessibility_required,
            availability_filter=availability_filter,
            vehicle_type_preference=vehicle_type_preference,
        )
        if not candidates:
            logger.info("No drivers found for ride %d", ride.id)
            return None

        best = candidates[0]
        logger.info(
            "Matched ride %d to driver user_id=%d (%.2f km away)",
            ride.id,
            best.user_id,
            best.distance_km,
        )
        return best


_redis_pool: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_pool


async def get_matching_engine() -> MatchingEngine:
    r = await get_redis()
    return MatchingEngine(r)
