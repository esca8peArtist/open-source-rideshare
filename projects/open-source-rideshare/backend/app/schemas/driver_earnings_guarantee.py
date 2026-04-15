"""Pydantic schemas for driver minimum earnings guarantee."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.driver_earnings_guarantee import GuaranteeStatus


# ---------------------------------------------------------------------------
# Policy schemas
# ---------------------------------------------------------------------------

class PolicyCreateRequest(BaseModel):
    """Admin: create or update the earnings guarantee policy."""

    minimum_per_ride_usd: float = Field(
        ..., gt=0, description="Minimum guaranteed earnings per completed ride (USD)"
    )
    minimum_rides_to_qualify: int = Field(
        ..., ge=1, description="Minimum rides per week driver must complete to qualify"
    )
    effective_from: date = Field(..., description="Date from which this policy applies")
    effective_until: Optional[date] = Field(
        None, description="Date after which policy expires (omit for open-ended)"
    )
    notes: Optional[str] = None


class PolicyResponse(BaseModel):
    """Admin: full policy detail."""

    id: int
    minimum_per_ride_usd: float
    minimum_rides_to_qualify: int
    effective_from: date
    effective_until: Optional[date]
    is_active: bool
    notes: Optional[str]
    created_by_user_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Weekly calculation / preview schemas
# ---------------------------------------------------------------------------

class DriverGuaranteePreviewItem(BaseModel):
    """One driver's projected record for a preview week (not persisted)."""

    driver_id: int
    driver_name: str
    rides_completed: int
    gross_earnings_usd: float
    guaranteed_earnings_usd: float
    shortfall_usd: float
    projected_status: GuaranteeStatus


class WeekPreviewResponse(BaseModel):
    """Dry-run summary for a single week (admin: calculate endpoint)."""

    week_start: date
    week_end: date
    policy_id: int
    minimum_per_ride_usd: float
    minimum_rides_to_qualify: int
    total_drivers_with_rides: int
    total_eligible: int        # met minimum rides threshold
    total_with_shortfall: int  # pending payout
    total_shortfall_usd: float
    drivers: list[DriverGuaranteePreviewItem]


# ---------------------------------------------------------------------------
# Weekly guarantee record schemas
# ---------------------------------------------------------------------------

class WeeklyGuaranteeRecordResponse(BaseModel):
    """A single driver's weekly guarantee record."""

    id: int
    driver_id: int
    driver_profile_id: int
    week_start: date
    week_end: date
    policy_id: int
    rides_completed: int
    gross_earnings_usd: float
    guaranteed_earnings_usd: float
    shortfall_usd: float
    status: GuaranteeStatus
    paid_at: Optional[datetime]
    processed_at: datetime

    model_config = {"from_attributes": True}


class WeeklyGuaranteeRecordDetailResponse(WeeklyGuaranteeRecordResponse):
    """Extended record including driver name (admin detail view)."""

    driver_name: str


class WeekRecordsListResponse(BaseModel):
    """Paginated list of weekly guarantee records for admin."""

    week_start: date
    week_end: date
    total: int
    pending_count: int
    total_pending_shortfall_usd: float
    records: list[WeeklyGuaranteeRecordDetailResponse]


class GuaranteeSummaryResponse(BaseModel):
    """Aggregate guarantee statistics (admin dashboard)."""

    policy_minimum_per_ride_usd: float
    policy_minimum_rides_to_qualify: int
    total_weeks_processed: int
    total_drivers_paid: int
    total_shortfall_paid_usd: float
    total_pending_shortfall_usd: float
    total_ineligible_records: int
    total_waived_records: int


# ---------------------------------------------------------------------------
# Driver-facing schemas
# ---------------------------------------------------------------------------

class DriverCurrentWeekEstimate(BaseModel):
    """Driver's in-progress estimate for the current week (not persisted)."""

    week_start: date
    week_end: date
    rides_completed_so_far: int
    gross_earnings_so_far_usd: float
    guaranteed_if_finished_usd: float   # based on current ride count
    shortfall_so_far_usd: float          # max(0, guaranteed - gross)
    minimum_rides_to_qualify: int
    minimum_per_ride_usd: float
    is_on_track: bool                   # True if already qualified OR no shortfall so far


class DriverGuaranteeHistoryResponse(BaseModel):
    """Driver's historical weekly guarantee records."""

    driver_id: int
    total_records: int
    total_received_usd: float           # sum of shortfall_usd where status=paid
    records: list[WeeklyGuaranteeRecordResponse]


# ---------------------------------------------------------------------------
# Action schemas
# ---------------------------------------------------------------------------

class ProcessWeekRequest(BaseModel):
    """Admin: process and persist guarantee records for a completed week."""

    week_start: date = Field(..., description="ISO Monday date of the week to process")


class PayRecordRequest(BaseModel):
    """Admin: mark a single guarantee record as paid."""

    notes: Optional[str] = None


class PayAllWeekRequest(BaseModel):
    """Admin: bulk-pay all pending records for a given week."""

    week_start: date = Field(..., description="ISO Monday date of the week")


class PayAllWeekResponse(BaseModel):
    """Result of bulk-pay operation."""

    week_start: date
    records_paid: int
    total_paid_usd: float
