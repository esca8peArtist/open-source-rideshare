"""Pydantic schemas for the driver availability and scheduling API."""

from __future__ import annotations

import re
from datetime import datetime, time
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

# Maps integer day_of_week → human-readable name used in WeeklyScheduleResponse.
DAY_NAMES = {
    0: "monday",
    1: "tuesday",
    2: "wednesday",
    3: "thursday",
    4: "friday",
    5: "saturday",
    6: "sunday",
}

_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


def _parse_hhmm(value: str) -> time:
    """Parse a HH:MM string into a datetime.time object."""
    if not isinstance(value, str) or not _TIME_RE.match(value):
        raise ValueError("Time must be in HH:MM format")
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


# ---------------------------------------------------------------------------
# Schedule slot schemas
# ---------------------------------------------------------------------------


class ScheduleSlotCreate(BaseModel):
    """Request body for creating or updating a weekly availability slot.

    Fields
    ------
    day_of_week  0=Monday … 6=Sunday (Python datetime.weekday() convention)
    start_time   HH:MM string, e.g. "08:00"
    end_time     HH:MM string, must be strictly after start_time
    """

    day_of_week: int = Field(..., ge=0, le=6, description="0=Monday, 6=Sunday")
    start_time: str = Field(..., description="HH:MM e.g. '08:00'")
    end_time: str = Field(..., description="HH:MM e.g. '17:00', must be after start_time")

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        # Validate that it parses correctly — will raise ValueError on bad input.
        _parse_hhmm(v)
        return v

    @model_validator(mode="after")
    def end_after_start(self) -> "ScheduleSlotCreate":
        start = _parse_hhmm(self.start_time)
        end = _parse_hhmm(self.end_time)
        if end <= start:
            raise ValueError("end_time must be strictly after start_time")
        return self

    def start_as_time(self) -> time:
        return _parse_hhmm(self.start_time)

    def end_as_time(self) -> time:
        return _parse_hhmm(self.end_time)


class ScheduleSlotResponse(BaseModel):
    """A single weekly availability slot as returned by the API."""

    id: int
    driver_id: int
    day_of_week: int
    start_time: Any  # datetime.time — serialised as "HH:MM:SS" by Pydantic
    end_time: Any
    is_active: bool

    model_config = {"from_attributes": True}


class WeeklyScheduleResponse(BaseModel):
    """Full weekly schedule for a driver, keyed by day name.

    Example::

        {
            "monday": [...],
            "tuesday": [],
            ...
        }
    """

    monday: list[ScheduleSlotResponse] = Field(default_factory=list)
    tuesday: list[ScheduleSlotResponse] = Field(default_factory=list)
    wednesday: list[ScheduleSlotResponse] = Field(default_factory=list)
    thursday: list[ScheduleSlotResponse] = Field(default_factory=list)
    friday: list[ScheduleSlotResponse] = Field(default_factory=list)
    saturday: list[ScheduleSlotResponse] = Field(default_factory=list)
    sunday: list[ScheduleSlotResponse] = Field(default_factory=list)

    @classmethod
    def from_slots(cls, slots: list[Any]) -> "WeeklyScheduleResponse":
        """Build a WeeklyScheduleResponse from a flat list of DriverSchedule rows."""
        day_map: dict[str, list[ScheduleSlotResponse]] = {name: [] for name in DAY_NAMES.values()}
        for slot in slots:
            day_name = DAY_NAMES.get(slot.day_of_week)
            if day_name is not None:
                day_map[day_name].append(ScheduleSlotResponse.model_validate(slot))
        return cls(**day_map)


# ---------------------------------------------------------------------------
# Online status schemas
# ---------------------------------------------------------------------------


class OnlineStatusResponse(BaseModel):
    """Current online/offline/break state for a driver."""

    driver_id: int
    is_online: bool
    is_on_break: bool = False
    went_online_at: datetime | None
    break_started_at: datetime | None = None
    last_heartbeat: datetime | None

    model_config = {"from_attributes": True}


class BreakResponse(BaseModel):
    """Response after starting or ending a break."""

    driver_id: int
    is_online: bool
    is_on_break: bool
    break_started_at: datetime | None

    model_config = {"from_attributes": True}


class SetOnlineRequest(BaseModel):
    """Request body for toggling a driver's online/offline state."""

    is_online: bool


# ---------------------------------------------------------------------------
# Combined availability response (schedule + status)
# ---------------------------------------------------------------------------


class DriverAvailabilityResponse(BaseModel):
    """Full availability snapshot: schedule slots + current online status."""

    online_status: OnlineStatusResponse | None
    schedule: WeeklyScheduleResponse


# ---------------------------------------------------------------------------
# Admin list schemas
# ---------------------------------------------------------------------------


class AdminDriverAvailabilityItem(BaseModel):
    """Per-driver row in the admin availability listing."""

    driver_id: int
    is_online: bool
    is_on_break: bool = False
    went_online_at: datetime | None
    last_heartbeat: datetime | None
    is_available_now: bool

    model_config = {"from_attributes": True}


class AdminDriverAvailabilityDetail(BaseModel):
    """Full admin detail for one driver."""

    driver_id: int
    is_available_now: bool
    online_status: OnlineStatusResponse | None
    schedule: WeeklyScheduleResponse
