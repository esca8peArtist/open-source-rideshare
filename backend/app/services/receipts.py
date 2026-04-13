"""Ride receipt generation service.

Produces detailed fare breakdowns, payment info, and driver details
for completed rides. Used by the receipt endpoint and (future) email receipts.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.driver import DriverProfile
from app.models.payment import Payment, PaymentType
from app.models.promo import PromoCode
from app.models.ride import Ride, RideStatus
from app.services.pricing import calculate_fare_breakdown


async def generate_receipt(ride_id: int, user_id: int, db: AsyncSession) -> dict | None:
    """Build a receipt dict for a completed ride.

    Returns None if the ride doesn't exist, isn't completed, or the user
    isn't the rider or driver on it.
    """
    result = await db.execute(
        select(Ride)
        .options(joinedload(Ride.rider), joinedload(Ride.driver))
        .where(Ride.id == ride_id)
    )
    ride = result.unique().scalar_one_or_none()
    if not ride:
        return None
    if ride.status != RideStatus.COMPLETED:
        return None
    if ride.rider_id != user_id and ride.driver_id != user_id:
        return None

    # Fare breakdown (reconstruct from ride data)
    distance_km = ride.distance_km or 0.0
    duration_min = ride.duration_min or 0.0
    breakdown = calculate_fare_breakdown(distance_km, duration_min, at_time=ride.requested_at)

    # Payment info
    payment_info = None
    pay_result = await db.execute(
        select(Payment).where(
            Payment.ride_id == ride.id,
            Payment.payment_type == PaymentType.RIDE_FARE,
        )
    )
    payment = pay_result.scalar_one_or_none()
    if payment:
        payment_info = {
            "payment_method": "card",
            "payment_status": payment.status.value,
            "amount_charged": payment.amount,
            "platform_fee": payment.platform_fee,
            "driver_payout": payment.driver_payout,
            "tip": payment.tip_amount,
            "promo_discount": ride.promo_discount,
            "total_charged": round(payment.amount + payment.tip_amount - ride.promo_discount, 2),
        }

    # Driver info
    driver_info = None
    if ride.driver:
        profile_result = await db.execute(
            select(DriverProfile).where(DriverProfile.user_id == ride.driver_id)
        )
        profile = profile_result.scalar_one_or_none()
        if profile:
            driver_info = {
                "name": ride.driver.name,
                "rating": profile.rating_avg,
                "vehicle": f"{profile.vehicle_color} {profile.vehicle_make} {profile.vehicle_model}",
                "license_plate": profile.license_plate,
            }

    # Promo code string
    promo_code_str = None
    if ride.promo_code_id:
        promo_result = await db.execute(
            select(PromoCode.code).where(PromoCode.id == ride.promo_code_id)
        )
        promo_code_str = promo_result.scalar_one_or_none()

    actual_fare = ride.actual_fare or breakdown.total
    total_charged = round(actual_fare + ride.tip_amount - ride.promo_discount, 2)

    return {
        "ride_id": ride.id,
        "status": ride.status.value,
        "receipt_number": f"OR-{ride.id:08d}",
        "pickup_address": ride.pickup_address,
        "dropoff_address": ride.dropoff_address,
        "distance_km": round(distance_km, 2),
        "duration_min": round(duration_min, 1),
        "fare_breakdown": {
            "base": breakdown.base,
            "distance": breakdown.distance,
            "time": breakdown.time,
            "multiplier": breakdown.multiplier,
            "multiplier_label": breakdown.multiplier_label,
            "subtotal": breakdown.subtotal,
            "platform_fee": breakdown.platform_fee,
            "total": breakdown.total,
        },
        "promo_code": promo_code_str,
        "promo_discount": ride.promo_discount,
        "tip": ride.tip_amount,
        "total_charged": total_charged,
        "payment": payment_info,
        "driver": driver_info,
        "requested_at": ride.requested_at,
        "started_at": ride.started_at,
        "completed_at": ride.completed_at,
        "rider_rating_given": ride.driver_rating,
        "cooperative_name": "OpenRide",
        "currency": "USD",
    }
