from pydantic import BaseModel


class DriverLocationResponse(BaseModel):
    lat: float
    lng: float


class DriverETAResponse(BaseModel):
    """ETA for the driver to reach the pickup point."""

    eta_minutes: float
    distance_km: float
    driver_location: DriverLocationResponse
    source: str  # "osrm" or "haversine"


class TripETAResponse(BaseModel):
    """Full trip ETA: driver→pickup + pickup→dropoff."""

    pickup_eta_minutes: float
    pickup_distance_km: float
    trip_duration_minutes: float
    trip_distance_km: float
    total_minutes: float
    driver_location: DriverLocationResponse
    source: str
