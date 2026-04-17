"""Pydantic v2 schemas for Corporate Fleet Cost Analytics."""
from datetime import date
from decimal import Decimal
import uuid
from pydantic import BaseModel, Field


class VehicleCostItem(BaseModel):
    vehicle_id: uuid.UUID
    make: str
    model: str
    year: int
    license_plate: str
    fuel_cost_usd: Decimal
    maintenance_cost_usd: Decimal
    toll_cost_usd: Decimal
    total_cost_usd: Decimal


class FleetCostSummaryResponse(BaseModel):
    account_id: int
    period_start: date | None
    period_end: date | None
    total_fuel_cost_usd: Decimal
    total_maintenance_cost_usd: Decimal
    total_toll_cost_usd: Decimal
    total_cost_usd: Decimal
    vehicle_count: int


class VehicleCostBreakdownResponse(BaseModel):
    account_id: int
    period_start: date | None
    period_end: date | None
    vehicles: list[VehicleCostItem]


class MonthlyCostPoint(BaseModel):
    month: str = Field(..., description="YYYY-MM format")
    fuel_cost_usd: Decimal
    maintenance_cost_usd: Decimal
    toll_cost_usd: Decimal
    total_cost_usd: Decimal


class FleetMonthlyCostTrendResponse(BaseModel):
    account_id: int
    months: list[MonthlyCostPoint]
