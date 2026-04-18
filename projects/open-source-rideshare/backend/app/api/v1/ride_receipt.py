"""Ride receipt endpoint.

GET /rides/{ride_id}/receipt
  Returns a structured receipt for a completed ride.
  Accessible by the rider or the driver of that ride.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.driver import DriverProfile
from app.models.payment import Payment
from app.models.ride import Ride, RideStatus
from app.models.user import User
from app.schemas.ride_receipt import RideReceiptResponse

router = APIRouter(prefix="/rides", tags=["rides"])


@router.get("/{ride_id}/receipt", response_model=RideReceiptResponse)
async def get_ride_receipt(
    ride_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RideReceiptResponse:
    """Return the receipt for a completed ride.

    The requesting user must be the rider or the driver of the ride.
    Returns 404 if the ride does not exist or is not completed.
    Returns 403 if the user is not a participant.
    """
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()

    if not ride or ride.status != RideStatus.COMPLETED:
        raise HTTPException(status_code=404, detail="Completed ride not found")

    if current_user.id != ride.rider_id and current_user.id != ride.driver_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Load payment record (optional — may not exist in all environments)
    pay_result = await db.execute(
        select(Payment).where(Payment.ride_id == ride_id)
    )
    payment = pay_result.scalar_one_or_none()

    # Load driver profile for vehicle details
    driver_name: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_color: str | None = None
    vehicle_year: int | None = None
    license_plate: str | None = None

    if ride.driver_id:
        driver_result = await db.execute(
            select(User).where(User.id == ride.driver_id)
        )
        driver_user = driver_result.scalar_one_or_none()
        if driver_user:
            driver_name = driver_user.name.split()[0] if driver_user.name else None

        profile_result = await db.execute(
            select(DriverProfile).where(DriverProfile.user_id == ride.driver_id)
        )
        profile = profile_result.scalar_one_or_none()
        if profile:
            vehicle_make = profile.vehicle_make
            vehicle_model = profile.vehicle_model
            vehicle_color = profile.vehicle_color
            vehicle_year = profile.vehicle_year
            license_plate = profile.license_plate

    actual_fare = ride.actual_fare or ride.estimated_fare
    promo_discount = ride.promo_discount or 0.0
    referral_credit_discount = ride.referral_credit_discount or 0.0
    tip_amount = ride.tip_amount or 0.0
    subtotal = max(actual_fare - promo_discount - referral_credit_discount, 0.0)
    total_charged = subtotal + tip_amount

    return RideReceiptResponse(
        ride_id=ride.id,
        requested_at=ride.requested_at,
        completed_at=ride.completed_at,
        pickup_address=ride.pickup_address,
        dropoff_address=ride.dropoff_address,
        distance_km=ride.distance_km,
        duration_min=ride.duration_min,
        estimated_fare=ride.estimated_fare,
        actual_fare=actual_fare,
        promo_discount=promo_discount,
        referral_credit_discount=referral_credit_discount,
        tip_amount=tip_amount,
        subtotal=subtotal,
        total_charged=total_charged,
        platform_fee=payment.platform_fee if payment else None,
        driver_payout=payment.driver_payout if payment else None,
        payment_status=payment.status.value if payment else None,
        driver_name=driver_name,
        vehicle_make=vehicle_make,
        vehicle_model=vehicle_model,
        vehicle_color=vehicle_color,
        vehicle_year=vehicle_year,
        license_plate=license_plate,
    )
