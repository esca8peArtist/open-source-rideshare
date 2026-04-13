from datetime import date, datetime

from pydantic import BaseModel


class DriverLocationUpdate(BaseModel):
    lat: float
    lng: float


class EarningsSummary(BaseModel):
    total_fares: float
    total_tips: float
    total_cancellation_fees: float = 0.0
    total_earnings: float
    trip_count: int
    average_fare: float
    average_tip: float
    period_start: date
    period_end: date


class EarningsTrip(BaseModel):
    ride_id: int
    pickup_address: str
    dropoff_address: str
    fare: float
    tip: float
    total: float
    distance_km: float | None
    duration_min: float | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class EarningsResponse(BaseModel):
    summary: EarningsSummary
    trips: list[EarningsTrip]


class DailyEarningsPoint(BaseModel):
    date: str
    fares: float
    tips: float
    cancellation_fees: float
    total: float
    trips: int


class DriverProfileCreate(BaseModel):
    vehicle_type: str
    vehicle_make: str
    vehicle_model: str
    vehicle_year: int
    vehicle_color: str
    license_plate: str
    license_number: str
    insurance_policy: str | None = None


class DriverProfileUpdate(BaseModel):
    vehicle_type: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_year: int | None = None
    vehicle_color: str | None = None
    license_plate: str | None = None


class DriverProfileResponse(BaseModel):
    id: int
    user_id: int
    vehicle_type: str
    vehicle_make: str
    vehicle_model: str
    vehicle_year: int
    vehicle_color: str
    license_plate: str
    is_online: bool
    is_approved: bool
    rating_avg: float
    total_trips: int
    active_vehicle_id: int | None = None

    model_config = {"from_attributes": True}


class RatingDistributionResponse(BaseModel):
    one_star: int = 0
    two_star: int = 0
    three_star: int = 0
    four_star: int = 0
    five_star: int = 0


class RatingsSummaryResponse(BaseModel):
    average: float
    total_ratings: int
    distribution: RatingDistributionResponse
    recent_average: float | None = None
    recent_count: int = 0
