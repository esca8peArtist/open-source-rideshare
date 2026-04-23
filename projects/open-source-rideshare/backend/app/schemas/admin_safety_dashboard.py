"""Schemas for admin safety dashboard feature."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SOSAlertRow(BaseModel):
    id: int
    user_id: int
    ride_id: int | None
    latitude: float | None
    longitude: float | None
    message: str | None
    created_at: datetime


class RouteDeviationRow(BaseModel):
    ride_id: int
    rider_id: int
    driver_id: int | None
    flagged_at: datetime


class SpeedingFlagRow(BaseModel):
    ride_id: int
    rider_id: int
    driver_id: int | None
    flagged_at: datetime


class ExpiredCheckInRow(BaseModel):
    id: int
    rider_id: int
    expires_at: datetime
    expired_notified_at: datetime | None


class AdminSafetyDashboard(BaseModel):
    active_sos_alerts: list[SOSAlertRow] = Field(default_factory=list)
    route_deviation_flags: list[RouteDeviationRow] = Field(default_factory=list)
    speeding_flags: list[SpeedingFlagRow] = Field(default_factory=list)
    expired_check_ins: list[ExpiredCheckInRow] = Field(default_factory=list)

    total_active_sos: int = Field(description="Count of active SOS alerts")
    total_route_deviations: int = Field(description="Count of in-progress rides with route deviation flags")
    total_speeding_flags: int = Field(description="Count of in-progress rides with speeding flags")
    total_expired_check_ins: int = Field(description="Count of expired check-in timers in the last 24 hours")
