from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.ride import LocationPoint


# --- Requests ---


class PoolRideRequest(BaseModel):
    """Request a pool (shared) ride."""
    pickup: LocationPoint
    dropoff: LocationPoint
    pickup_address: str
    dropoff_address: str


class PoolEstimateRequest(BaseModel):
    """Estimate fare for a pool ride."""
    pickup: LocationPoint
    dropoff: LocationPoint
    promo_code: str | None = None


# --- Responses ---


class PoolLegResponse(BaseModel):
    id: int
    ride_id: int
    rider_name: str | None = None
    pickup_address: str
    dropoff_address: str
    pickup_order: int
    dropoff_order: int
    fare_discount_percent: float
    status: str
    picked_up_at: datetime | None = None
    dropped_off_at: datetime | None = None

    model_config = {"from_attributes": True}


class PoolResponse(BaseModel):
    id: int
    status: str
    max_riders: int
    current_riders: int
    driver_name: str | None = None
    total_distance_km: float | None = None
    total_duration_min: float | None = None
    legs: list[PoolLegResponse] = []
    created_at: datetime
    matched_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class PoolEstimateResponse(BaseModel):
    solo_fare: float
    pool_fare: float
    discount_percent: float
    savings: float
    distance_km: float
    duration_min: float
    currency: str = "USD"


class PoolRideResponse(BaseModel):
    """Response after requesting a pool ride."""
    ride_id: int
    pool_id: int
    status: str
    estimated_fare: float
    pool_fare: float
    discount_percent: float
    pickup_address: str
    dropoff_address: str
    riders_in_pool: int
    max_riders: int


class PoolLegStatusUpdate(BaseModel):
    """Driver reports picking up or dropping off a pool rider."""
    leg_id: int


class PoolSearchResult(BaseModel):
    """A candidate pool that a new rider could join."""
    pool_id: int
    current_riders: int
    detour_km: float
    detour_percent: float
    discount_percent: float
    estimated_pool_fare: float
