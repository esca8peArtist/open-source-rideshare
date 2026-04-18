from datetime import datetime

from pydantic import BaseModel


class DriverUpcomingRide(BaseModel):
    id: int
    rider_id: int
    pickup_address: str
    dropoff_address: str
    scheduled_for: datetime
    estimated_fare: float
    accessibility_required: bool
    recurring_ride_id: int | None

    model_config = {"from_attributes": True}


class DriverUpcomingRidesResponse(BaseModel):
    rides: list[DriverUpcomingRide]
    total: int
