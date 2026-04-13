from datetime import datetime

from pydantic import BaseModel

from app.models.vehicle import VehicleServiceCategory


class LocationPoint(BaseModel):
    lat: float
    lng: float


class FareEstimateRequest(BaseModel):
    pickup: LocationPoint | None = None
    dropoff: LocationPoint | None = None
    pickup_saved_location_id: int | None = None
    dropoff_saved_location_id: int | None = None
    promo_code: str | None = None
    waypoints: list["WaypointInput"] | None = None


class FareBreakdownResponse(BaseModel):
    base: float
    distance: float
    time: float
    multiplier: float = 1.0
    multiplier_label: str | None = None
    demand_multiplier: float = 1.0
    demand_label: str | None = None
    subtotal: float
    platform_fee: float = 0.0
    total: float


class FareEstimateResponse(BaseModel):
    estimated_fare: float
    distance_km: float
    duration_min: float
    currency: str = "USD"
    breakdown: FareBreakdownResponse | None = None
    demand_info: "DemandInfoSummary | None" = None
    promo_discount: float = 0.0
    final_fare: float | None = None  # estimated_fare - promo_discount
    promo_code: str | None = None


class DemandInfoSummary(BaseModel):
    """Rider-facing demand pricing transparency."""

    multiplier: float
    is_elevated: bool
    explanation: str


class WaypointInput(BaseModel):
    """Inline waypoint for ride request."""

    address: str
    lat: float
    lng: float
    wait_time_minutes: int = 3
    notes: str | None = None


class RideRequest(BaseModel):
    pickup: LocationPoint | None = None
    dropoff: LocationPoint | None = None
    pickup_address: str | None = None
    dropoff_address: str | None = None
    pickup_saved_location_id: int | None = None
    dropoff_saved_location_id: int | None = None
    promo_code: str | None = None
    accessibility_required: bool = False
    vehicle_type_preference: VehicleServiceCategory | None = None
    waypoints: list[WaypointInput] | None = None


class ScheduleRideRequest(BaseModel):
    pickup: LocationPoint
    dropoff: LocationPoint
    pickup_address: str
    dropoff_address: str
    scheduled_for: datetime
    accessibility_required: bool = False


class RideResponse(BaseModel):
    id: int
    status: str
    pickup_address: str
    dropoff_address: str
    estimated_fare: float
    actual_fare: float | None = None
    driver_name: str | None = None
    driver_rating: float | None = None
    vehicle_info: str | None = None
    vehicle_type_preference: VehicleServiceCategory | None = None
    scheduled_for: datetime | None = None
    requested_at: datetime
    matched_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class RideRatingRequest(BaseModel):
    rating: int
    tip_amount: float = 0.0


class TipRequest(BaseModel):
    amount: float


class CancelRequest(BaseModel):
    reason: str | None = None


class CancelResponse(BaseModel):
    status: str
    cancellation_fee: float = 0.0
    fee_reason: str = ""
    payment_required: bool = False
    payment_intent_client_secret: str | None = None
    payment_intent_id: str | None = None


class GeocodeRequest(BaseModel):
    address: str


class GeocodeResponse(BaseModel):
    lat: float
    lng: float
    display_name: str


class ReverseGeocodeRequest(BaseModel):
    lat: float
    lng: float


class ReverseGeocodeResponse(BaseModel):
    display_name: str
    short_address: str


# ---- Ride Receipt ----


class ReceiptFareBreakdown(BaseModel):
    base: float
    distance: float
    time: float
    multiplier: float = 1.0
    multiplier_label: str | None = None
    subtotal: float
    platform_fee: float = 0.0
    total: float


class ReceiptPaymentInfo(BaseModel):
    payment_method: str = "card"  # card, cash, etc.
    payment_status: str
    amount_charged: float
    platform_fee: float
    driver_payout: float
    tip: float = 0.0
    promo_discount: float = 0.0
    total_charged: float  # amount_charged + tip - promo_discount


class ReceiptDriverInfo(BaseModel):
    name: str
    rating: float
    vehicle: str  # e.g. "Silver Toyota Camry"
    license_plate: str


class RideReceiptResponse(BaseModel):
    ride_id: int
    status: str
    receipt_number: str  # e.g. "OR-00000123"

    # Route
    pickup_address: str
    dropoff_address: str
    distance_km: float
    duration_min: float

    # Fare
    fare_breakdown: ReceiptFareBreakdown
    promo_code: str | None = None
    promo_discount: float = 0.0
    tip: float = 0.0
    total_charged: float  # final amount after promo + tip

    # Payment
    payment: ReceiptPaymentInfo | None = None

    # Driver
    driver: ReceiptDriverInfo | None = None

    # Timestamps
    requested_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Rating given by rider
    rider_rating_given: int | None = None

    # Cooperative info
    cooperative_name: str = "OpenRide"
    currency: str = "USD"


class RiderStatsResponse(BaseModel):
    """Lifetime statistics summary for a rider."""

    total_rides: int
    completed_rides: int
    cancelled_rides: int
    completion_rate_pct: float
    total_spent_dollars: float
    avg_fare_dollars: float
    total_distance_km: float
    avg_rating_given: float | None
    tips_given_count: int
    total_tips_given_dollars: float
    member_since: datetime | None
