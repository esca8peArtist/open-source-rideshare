"""Pydantic schemas for recurring rides."""

from datetime import datetime, time

from pydantic import BaseModel, field_validator

from app.schemas.ride import LocationPoint


class RecurringRideCreate(BaseModel):
    pickup: LocationPoint
    dropoff: LocationPoint
    pickup_address: str
    dropoff_address: str
    pickup_saved_location_id: int | None = None
    dropoff_saved_location_id: int | None = None
    days_of_week: list[int]  # 0=Monday .. 6=Sunday
    pickup_time: time  # HH:MM in rider's local timezone
    timezone: str = "UTC"
    accessibility_required: bool = False
    label: str | None = None

    @field_validator("days_of_week")
    @classmethod
    def validate_days(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("At least one day of week is required")
        if len(v) > 7:
            raise ValueError("Cannot have more than 7 days")
        for day in v:
            if day < 0 or day > 6:
                raise ValueError(f"Invalid day of week: {day} (must be 0-6)")
        # Deduplicate and sort
        return sorted(set(v))

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        # Basic validation — accept common IANA timezone formats
        if not v or len(v) > 50:
            raise ValueError("Invalid timezone")
        return v


class RecurringRideUpdate(BaseModel):
    pickup: LocationPoint | None = None
    dropoff: LocationPoint | None = None
    pickup_address: str | None = None
    dropoff_address: str | None = None
    pickup_saved_location_id: int | None = None
    dropoff_saved_location_id: int | None = None
    days_of_week: list[int] | None = None
    pickup_time: time | None = None
    timezone: str | None = None
    accessibility_required: bool | None = None
    label: str | None = None

    @field_validator("days_of_week")
    @classmethod
    def validate_days(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return v
        if not v:
            raise ValueError("At least one day of week is required")
        if len(v) > 7:
            raise ValueError("Cannot have more than 7 days")
        for day in v:
            if day < 0 or day > 6:
                raise ValueError(f"Invalid day of week: {day} (must be 0-6)")
        return sorted(set(v))


class RecurringRideResponse(BaseModel):
    id: int
    rider_id: int
    pickup_address: str
    dropoff_address: str
    days_of_week: list[int]
    pickup_time: time
    timezone: str
    accessibility_required: bool
    status: str
    label: str | None = None
    last_generated_date: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RecurringRideListResponse(BaseModel):
    recurring_rides: list[RecurringRideResponse]
    total: int


class GeneratedRideSummary(BaseModel):
    ride_id: int
    status: str
    scheduled_for: datetime


class RecurringRideDetailResponse(RecurringRideResponse):
    upcoming_rides: list[GeneratedRideSummary] = []
