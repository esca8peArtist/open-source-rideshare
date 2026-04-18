"""Driver per-ride earnings breakdown endpoint.

GET /rides/{ride_id}/driver-earnings
  Returns a full earnings breakdown for a completed ride from the driver's
  perspective: base/distance/time components, platform fee, net fare, and tip.
  Only accessible by the driver assigned to the ride.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver
from app.db.database import get_db
from app.models.ride import Ride, RideStatus
from app.models.user import User
from app.schemas.driver_ride_earnings import DriverRideEarnings
from app.services.driver_ride_earnings import compute_driver_ride_earnings

router = APIRouter(prefix="/rides", tags=["rides"])


@router.get("/{ride_id}/driver-earnings", response_model=DriverRideEarnings)
async def get_driver_ride_earnings(
    ride_id: int,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverRideEarnings:
    """Return earnings breakdown for a completed ride (driver-scoped)."""
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()

    if ride is None:
        raise HTTPException(status_code=404, detail="Ride not found")

    if ride.driver_id != driver.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if ride.status != RideStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail="Earnings breakdown only available for completed rides",
        )

    if ride.actual_fare is None:
        raise HTTPException(status_code=409, detail="Fare not yet recorded for this ride")

    return compute_driver_ride_earnings(
        ride_id=ride.id,
        pickup_address=ride.pickup_address,
        dropoff_address=ride.dropoff_address,
        actual_fare=float(ride.actual_fare),
        tip_amount=float(ride.tip_amount),
        distance_km=ride.distance_km,
        duration_min=ride.duration_min,
        completed_at=ride.completed_at,
    )
