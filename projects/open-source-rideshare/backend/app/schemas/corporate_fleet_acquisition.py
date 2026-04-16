"""Pydantic v2 schemas for Corporate Fleet Vehicle Acquisition and Disposal.

Fleet managers record how vehicles entered the fleet (purchased, leased,
financed, donated) and how they leave it (sold, scrapped, lease returned, etc.).

Public surface
--------------
AcquisitionCreate           — payload for recording a vehicle acquisition.
AcquisitionUpdate           — partial-update payload.
AcquisitionResponse         — full acquisition record returned by the API.
DisposalCreate              — payload for disposing of a vehicle.
DisposalResponse            — full disposal record returned by the API.
FleetOwnershipSummary       — aggregate ownership stats for an account.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.corporate_fleet_acquisition import AcquisitionType, DisposalReason


# ---------------------------------------------------------------------------
# Acquisition write schemas
# ---------------------------------------------------------------------------


class AcquisitionCreate(BaseModel):
    """Payload for recording how a fleet vehicle was acquired.

    Attributes:
        acquisition_type: How the vehicle was acquired (required).
        acquisition_date: Date the vehicle was acquired (required).
        vendor_name: Seller, lessor, or donor name, nullable.
        acquisition_cost_usd: Purchase price in USD, nullable (ge=0).
        lease_start_date: First day of the lease term, nullable.
        lease_end_date: Last day of the lease term, nullable.
        monthly_lease_payment_usd: Monthly lease payment in USD, nullable (ge=0).
        lease_mileage_allowance_annual: Annual mileage cap under the lease, nullable (ge=0).
        financed_amount_usd: Principal amount financed in USD, nullable (ge=0).
        loan_term_months: Loan term in months, nullable (ge=1).
        monthly_loan_payment_usd: Monthly loan payment in USD, nullable (ge=0).
        notes: Optional free-text notes.
    """

    acquisition_type: AcquisitionType
    acquisition_date: date
    vendor_name: Optional[str] = Field(None, max_length=200)
    acquisition_cost_usd: Optional[float] = Field(None, ge=0)
    lease_start_date: Optional[date] = None
    lease_end_date: Optional[date] = None
    monthly_lease_payment_usd: Optional[float] = Field(None, ge=0)
    lease_mileage_allowance_annual: Optional[int] = Field(None, ge=0)
    financed_amount_usd: Optional[float] = Field(None, ge=0)
    loan_term_months: Optional[int] = Field(None, ge=1)
    monthly_loan_payment_usd: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None


class AcquisitionUpdate(BaseModel):
    """Partial-update payload for a fleet vehicle acquisition record.

    All fields are optional.  fleet_vehicle_id and account_id cannot be
    changed after creation.
    """

    acquisition_type: Optional[AcquisitionType] = None
    acquisition_date: Optional[date] = None
    vendor_name: Optional[str] = Field(None, max_length=200)
    acquisition_cost_usd: Optional[float] = Field(None, ge=0)
    lease_start_date: Optional[date] = None
    lease_end_date: Optional[date] = None
    monthly_lease_payment_usd: Optional[float] = Field(None, ge=0)
    lease_mileage_allowance_annual: Optional[int] = Field(None, ge=0)
    financed_amount_usd: Optional[float] = Field(None, ge=0)
    loan_term_months: Optional[int] = Field(None, ge=1)
    monthly_loan_payment_usd: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Acquisition read schema
# ---------------------------------------------------------------------------


class AcquisitionResponse(BaseModel):
    """Full fleet vehicle acquisition record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fleet_vehicle_id: uuid.UUID
    account_id: int
    acquisition_type: str
    vendor_name: Optional[str]
    acquisition_date: date
    acquisition_cost_usd: Optional[float]
    lease_start_date: Optional[date]
    lease_end_date: Optional[date]
    monthly_lease_payment_usd: Optional[float]
    lease_mileage_allowance_annual: Optional[int]
    financed_amount_usd: Optional[float]
    loan_term_months: Optional[int]
    monthly_loan_payment_usd: Optional[float]
    notes: Optional[str]
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Disposal write schema
# ---------------------------------------------------------------------------


class DisposalCreate(BaseModel):
    """Payload for retiring a fleet vehicle from the fleet.

    Attributes:
        disposal_reason: Why the vehicle is being retired (required).
        disposal_date: Date the vehicle was disposed of (required).
        sale_price_usd: Sale or trade-in value in USD, nullable (ge=0).
        buyer_name: Name of the buyer or receiving party, nullable.
        notes: Optional free-text notes.
    """

    disposal_reason: DisposalReason
    disposal_date: date
    sale_price_usd: Optional[float] = Field(None, ge=0)
    buyer_name: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Disposal read schema
# ---------------------------------------------------------------------------


class DisposalResponse(BaseModel):
    """Full fleet vehicle disposal record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fleet_vehicle_id: uuid.UUID
    account_id: int
    disposal_reason: str
    disposal_date: date
    sale_price_usd: Optional[float]
    buyer_name: Optional[str]
    notes: Optional[str]
    disposed_by_id: Optional[int]
    created_at: datetime


# ---------------------------------------------------------------------------
# Fleet ownership summary schema
# ---------------------------------------------------------------------------


class FleetOwnershipSummary(BaseModel):
    """Aggregate ownership and financial statistics for a corporate fleet account.

    Attributes:
        total_vehicles: Total vehicles ever recorded (active and retired).
        active_vehicles: Vehicles with is_active=True.
        retired_vehicles: Vehicles that have a disposal record.
        by_acquisition_type: Active-vehicle count keyed by AcquisitionType value.
        total_monthly_lease_payments_usd: Sum of monthly lease payments for active leased vehicles.
        total_monthly_loan_payments_usd: Sum of monthly loan payments for active financed vehicles.
        leases_expiring_within_90_days: Active leased vehicles whose lease_end_date is within 90 days.
    """

    total_vehicles: int
    active_vehicles: int
    retired_vehicles: int
    by_acquisition_type: Dict[str, int]
    total_monthly_lease_payments_usd: float
    total_monthly_loan_payments_usd: float
    leases_expiring_within_90_days: int
