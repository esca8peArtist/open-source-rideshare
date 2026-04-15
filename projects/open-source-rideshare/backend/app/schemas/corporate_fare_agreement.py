"""Pydantic schemas for the Corporate Fare Agreements feature."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

from app.models.corporate_fare_agreement import FareAgreementRateType


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class FareAgreementCreate(BaseModel):
    """Payload for creating a new fare agreement."""

    name: str = Field(..., min_length=1, max_length=200)
    rate_type: FareAgreementRateType
    value: Decimal = Field(..., description=(
        "Numeric value interpreted by rate_type: "
        "surge_cap ≥ 1.0; flat_discount_pct 0–100; "
        "per_mile_rate_usd / per_minute_rate_usd > 0"
    ))
    applies_to_vehicle_types: list[str] | None = Field(
        None, description="Vehicle categories this agreement covers; null = all."
    )
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _validate_value(self) -> "FareAgreementCreate":
        rt = self.rate_type
        v = self.value
        if rt == FareAgreementRateType.surge_cap and v < Decimal("1"):
            raise ValueError("surge_cap value must be ≥ 1.0")
        if rt == FareAgreementRateType.flat_discount_pct and not (
            Decimal("0") <= v <= Decimal("100")
        ):
            raise ValueError("flat_discount_pct must be between 0 and 100")
        if rt in (
            FareAgreementRateType.per_mile_rate_usd,
            FareAgreementRateType.per_minute_rate_usd,
        ) and v <= Decimal("0"):
            raise ValueError(f"{rt.value} must be > 0")
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until <= self.valid_from
        ):
            raise ValueError("valid_until must be after valid_from")
        return self


class FareAgreementUpdate(BaseModel):
    """Partial-update payload — all fields optional."""

    name: str | None = Field(None, min_length=1, max_length=200)
    value: Decimal | None = None
    applies_to_vehicle_types: list[str] | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    is_active: bool | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _validate_validity_window(self) -> "FareAgreementUpdate":
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until <= self.valid_from
        ):
            raise ValueError("valid_until must be after valid_from")
        return self


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class FareAgreementResponse(BaseModel):
    """Full representation of a corporate fare agreement."""

    id: uuid.UUID
    corporate_account_id: int
    name: str
    rate_type: str
    value: Decimal
    applies_to_vehicle_types: list[str] | None
    valid_from: datetime | None
    valid_until: datetime | None
    is_active: bool
    notes: str | None
    created_by_id: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FareAgreementListResponse(BaseModel):
    """Paginated list of fare agreements."""

    items: list[FareAgreementResponse]
    total: int


# ---------------------------------------------------------------------------
# Compute response
# ---------------------------------------------------------------------------


class FareComputeRequest(BaseModel):
    """Inputs for fare computation against active agreements."""

    base_fare_usd: Decimal = Field(
        ..., gt=Decimal("0"), description="Pre-negotiated base fare (before surge)."
    )
    surge_multiplier: Decimal = Field(
        Decimal("1.0"), ge=Decimal("1.0"),
        description="Current platform surge multiplier.",
    )
    vehicle_type: str | None = Field(
        None, description="Vehicle category; null matches all agreements."
    )
    ride_dt: datetime | None = Field(
        None, description="Ride datetime for validity check; null = now."
    )


class AgreementSummary(BaseModel):
    """Brief summary of an applied agreement, included in compute response."""

    id: uuid.UUID
    name: str
    rate_type: str
    value: Decimal


class FareComputeResponse(BaseModel):
    """Result of applying active fare agreements to a hypothetical ride fare."""

    base_fare_usd: Decimal
    original_surge_multiplier: Decimal
    adjusted_surge_multiplier: Decimal
    fare_before_discount_usd: Decimal
    discount_pct_applied: Decimal
    final_fare_usd: Decimal
    agreements_applied: list[AgreementSummary]
    reference_agreements: list[AgreementSummary] = Field(
        default_factory=list,
        description=(
            "Per-mile/per-minute rate agreements that are active and applicable "
            "but require distance/duration data to apply — listed for the "
            "billing engine to reference when processing the actual ride."
        ),
    )
