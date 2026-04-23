from pydantic import BaseModel


class FareTier(BaseModel):
    riders: int
    label: str
    fare: float
    discount_percent: float
    savings: float
    is_solo: bool


class PoolFareLadderResponse(BaseModel):
    pickup_lat: float
    pickup_lng: float
    dropoff_lat: float
    dropoff_lng: float
    distance_km: float
    estimated_duration_min: float
    tiers: list[FareTier]
    recommended_tier: int
    recommendation: str
    max_pool_wait_minutes: int
