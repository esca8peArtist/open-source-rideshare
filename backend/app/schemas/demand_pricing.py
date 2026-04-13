from pydantic import BaseModel


class DemandInfoResponse(BaseModel):
    """Transparent demand pricing info shown to riders before confirming a ride."""

    geohash: str
    demand_count: int
    supply_count: int
    multiplier: float
    multiplier_cap: float
    is_elevated: bool
    explanation: str


class DemandPricingConfigResponse(BaseModel):
    """Current demand pricing configuration (admin view)."""

    enabled: bool
    max_multiplier: float
    threshold: float
    scale_factor: float


class DemandPricingConfigUpdate(BaseModel):
    """Admin update to demand pricing configuration."""

    enabled: bool | None = None
    max_multiplier: float | None = None
    threshold: float | None = None
    scale_factor: float | None = None
