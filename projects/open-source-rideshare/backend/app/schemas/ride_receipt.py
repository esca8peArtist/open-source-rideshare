from datetime import datetime

from pydantic import BaseModel


class RideReceiptResponse(BaseModel):
    ride_id: int
    requested_at: datetime
    completed_at: datetime
    pickup_address: str
    dropoff_address: str
    distance_km: float | None
    duration_min: float | None
    estimated_fare: float
    actual_fare: float
    promo_discount: float
    referral_credit_discount: float
    tip_amount: float
    subtotal: float
    total_charged: float
    platform_fee: float | None
    driver_payout: float | None
    payment_status: str | None
    driver_name: str | None
    vehicle_make: str | None
    vehicle_model: str | None
    vehicle_color: str | None
    vehicle_year: int | None
    license_plate: str | None
