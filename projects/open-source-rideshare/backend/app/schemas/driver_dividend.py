"""Schemas for cooperative member dividend / profit-sharing endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class DividendCalculationRequest(BaseModel):
    """Preview a dividend distribution without persisting it."""

    year: int = Field(ge=2020, le=2100)
    quarter: int = Field(ge=1, le=4)
    surplus_usd: float = Field(
        gt=0,
        description="Total platform surplus to distribute among driver-members (USD)",
    )


class DividendDeclarationRequest(BaseModel):
    """Declare and persist a dividend distribution."""

    year: int = Field(ge=2020, le=2100)
    quarter: int = Field(ge=1, le=4)
    surplus_usd: float = Field(gt=0, description="Total platform surplus to distribute (USD)")
    notes: str | None = None


class ApproveDividendRequest(BaseModel):
    notes: str | None = None


class CancelDividendRequest(BaseModel):
    reason: str | None = None


# ---------------------------------------------------------------------------
# Driver share summary (used in admin detail view)
# ---------------------------------------------------------------------------

class DriverShareItem(BaseModel):
    """One driver's allocation in a distribution."""

    driver_share_id: int
    driver_id: int
    driver_profile_id: int
    driver_name: str | None
    qualifying_rides: int
    share_pct: float
    amount_usd: float
    status: str
    paid_at: datetime | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Calculation preview (no DB write)
# ---------------------------------------------------------------------------

class DividendCalculationPreview(BaseModel):
    """Dry-run result — shows how a distribution would be split."""

    year: int
    quarter: int
    total_platform_surplus_usd: float
    total_qualifying_rides: int
    per_ride_payout_usd: float
    participating_drivers: int
    driver_shares: list[DriverShareItem]


# ---------------------------------------------------------------------------
# Dividend response (persisted)
# ---------------------------------------------------------------------------

class DividendResponse(BaseModel):
    id: int
    year: int
    quarter: int
    total_platform_surplus_usd: float
    total_qualifying_rides: int
    per_ride_payout_usd: float
    status: str
    approved_by_user_id: int | None
    notes: str | None
    cancellation_reason: str | None
    declared_at: datetime
    approved_at: datetime | None
    distributed_at: datetime | None

    model_config = {"from_attributes": True}


class DividendDetailResponse(DividendResponse):
    """Full detail view including per-driver breakdown (admin only)."""

    shares: list[DriverShareItem] = []


class DividendListResponse(BaseModel):
    dividends: list[DividendResponse]
    total: int


# ---------------------------------------------------------------------------
# Driver-facing history (own shares only — no cross-driver visibility)
# ---------------------------------------------------------------------------

class DriverDividendHistoryItem(BaseModel):
    dividend_id: int
    year: int
    quarter: int
    qualifying_rides: int
    share_pct: float
    amount_usd: float
    dividend_status: str
    share_status: str
    paid_at: datetime | None


class DriverDividendHistoryResponse(BaseModel):
    history: list[DriverDividendHistoryItem]
    total: int


# ---------------------------------------------------------------------------
# Public list (amounts only, no per-driver breakdown)
# ---------------------------------------------------------------------------

class PublicDividendItem(BaseModel):
    id: int
    year: int
    quarter: int
    total_platform_surplus_usd: float
    total_qualifying_rides: int
    per_ride_payout_usd: float
    status: str
    distributed_at: datetime | None


class PublicDividendListResponse(BaseModel):
    dividends: list[PublicDividendItem]
    total: int
