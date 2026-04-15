"""Pydantic schemas for the Corporate Ride Policy API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, model_validator


class CorporateRidePolicySet(BaseModel):
    """Request body for creating or replacing a corporate ride policy.

    All fields are optional.  Omitting a field means "no restriction" for
    that dimension.  To clear a restriction that was previously set, supply
    ``null`` explicitly.

    Rules enforced:
    - ``max_per_ride_usd`` and ``max_per_member_monthly_usd`` must be > 0 when provided.
    - ``approved_purposes`` is capped at 20 entries; each entry max 100 chars.
    - ``approved_purposes`` is only meaningful when ``require_purpose=True``.
    """

    allowed_vehicle_categories: list[str] | None = Field(
        None,
        description="Permitted vehicle categories. NULL means all categories allowed.",
        max_length=20,
    )
    max_per_ride_usd: Decimal | None = Field(
        None,
        gt=Decimal("0"),
        description="Maximum cost per single ride. NULL means no per-ride cap.",
    )
    max_per_member_monthly_usd: Decimal | None = Field(
        None,
        gt=Decimal("0"),
        description="Per-employee monthly spending cap. NULL means no individual cap.",
    )
    require_purpose: bool = Field(
        False,
        description="Whether employees must provide a trip purpose when booking.",
    )
    approved_purposes: list[Annotated[str, Field(max_length=100)]] | None = Field(
        None,
        description=(
            "Allowed purpose strings when require_purpose=True. "
            "NULL means any purpose accepted. Max 20 entries."
        ),
    )
    business_hours_only: bool = Field(
        False,
        description="Restrict rides to Mon–Fri 07:00–21:00 UTC.",
    )

    @model_validator(mode="after")
    def validate_approved_purposes_length(self) -> "CorporateRidePolicySet":
        if self.approved_purposes is not None and len(self.approved_purposes) > 20:
            raise ValueError("approved_purposes may contain at most 20 entries.")
        return self


class CorporateRidePolicyResponse(BaseModel):
    """Corporate ride policy as returned by the API."""

    id: int
    account_id: int
    allowed_vehicle_categories: list[str] | None
    max_per_ride_usd: Decimal | None
    max_per_member_monthly_usd: Decimal | None
    require_purpose: bool
    approved_purposes: list[str] | None
    business_hours_only: bool
    updated_at: datetime

    model_config = {"from_attributes": True}


class RideCheckRequest(BaseModel):
    """Payload for validating a proposed ride against the account policy."""

    vehicle_category: str = Field(
        ...,
        description="Vehicle category the rider intends to request.",
    )
    estimated_cost_usd: Decimal = Field(
        ...,
        gt=Decimal("0"),
        description="Estimated ride cost in USD.",
    )
    purpose: str | None = Field(
        None,
        max_length=100,
        description="Trip purpose supplied by the employee, if any.",
    )
    departure_utc_hour: int | None = Field(
        None,
        ge=0,
        le=23,
        description="Hour of departure in UTC (0–23). Required when policy has business_hours_only=True.",
    )
    departure_utc_weekday: int | None = Field(
        None,
        ge=0,
        le=6,
        description="Weekday of departure in UTC (0=Monday … 6=Sunday). Required when policy has business_hours_only=True.",
    )


class RideCheckResponse(BaseModel):
    """Result of a ride policy check."""

    allowed: bool
    reason: str | None = Field(
        None,
        description="Human-readable explanation when allowed=False.",
    )
