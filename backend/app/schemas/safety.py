from datetime import datetime

from pydantic import BaseModel


class SOSTriggerRequest(BaseModel):
    ride_id: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    message: str | None = None


class SOSAlertResponse(BaseModel):
    id: int
    ride_id: int | None
    status: str
    latitude: float | None
    longitude: float | None
    message: str | None
    created_at: datetime
    resolved_at: datetime | None = None

    model_config = {"from_attributes": True}


class SOSResolveRequest(BaseModel):
    resolution: str = "false_alarm"


class TripShareRequest(BaseModel):
    ride_id: int


class TripShareResponse(BaseModel):
    token: str
    share_url: str
    expires_at: datetime


class SharedTripView(BaseModel):
    ride_id: int
    status: str
    pickup_address: str
    dropoff_address: str
    driver_name: str | None = None
    vehicle_info: str | None = None
    started_at: datetime | None = None


class EmergencyContactCreate(BaseModel):
    name: str
    phone: str
    relationship_label: str | None = None


class EmergencyContactResponse(BaseModel):
    id: int
    name: str
    phone: str
    relationship_label: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
