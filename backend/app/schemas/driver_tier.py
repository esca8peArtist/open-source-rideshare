"""Pydantic schemas for the driver career tier system."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.driver_tier import CareerTierLevel


# ---------------------------------------------------------------------------
# Tier benefit definitions (embedded in responses, not persisted)
# ---------------------------------------------------------------------------


class TierBenefits(BaseModel):
    """Benefits granted to a driver at a particular tier level."""

    dispatch_priority: int = Field(
        description="Dispatch priority multiplier (1=standard, 4=highest)"
    )
    earnings_bonus_pct: float = Field(
        description="Additional earnings percentage bonus (0.0 = none)"
    )
    badge: str | None = Field(
        description="Visual badge label shown on the driver profile, or null"
    )
    perks: list[str] = Field(description="Human-readable list of perks")


# ---------------------------------------------------------------------------
# Next-tier progress
# ---------------------------------------------------------------------------


class NextTierProgress(BaseModel):
    """Progress toward the next tier, or None if already at PLATINUM."""

    next_tier: CareerTierLevel
    rides_needed: int = Field(description="Additional lifetime rides required (0 if met)")
    rides_required: int = Field(description="Total lifetime rides required for next tier")
    rating_needed: float = Field(
        description="Additional rating improvement required (0.0 if met)"
    )
    rating_required: float = Field(description="Minimum avg rating required for next tier")
    acceptance_needed: float = Field(
        description="Additional acceptance rate improvement required (0.0 if met)"
    )
    acceptance_required: float = Field(
        description="Minimum acceptance rate required for next tier (0.0–1.0)"
    )


# ---------------------------------------------------------------------------
# Driver-facing response
# ---------------------------------------------------------------------------


class DriverCareerTierResponse(BaseModel):
    """Full career tier response returned to the driver."""

    driver_id: int
    current_tier: CareerTierLevel
    previous_tier: CareerTierLevel | None
    tier_since: datetime
    evaluated_at: datetime

    # Metrics captured at last evaluation
    snapshot_rides: int
    snapshot_rating: float
    snapshot_acceptance_rate: float

    # Enriched data computed at response time
    benefits: TierBenefits
    next_tier_progress: NextTierProgress | None = Field(
        description="Progress to next tier, or null if PLATINUM"
    )

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Admin responses
# ---------------------------------------------------------------------------


class TierCount(BaseModel):
    tier: CareerTierLevel
    count: int


class AdminTierDistributionResponse(BaseModel):
    """Aggregate tier counts across all drivers."""

    total_drivers: int
    distribution: list[TierCount]
