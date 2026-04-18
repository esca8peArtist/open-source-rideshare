"""Driver upcoming scheduled rides endpoint.

GET /driver/me/upcoming-scheduled — returns SCHEDULED rides assigned to the
authenticated driver, ordered by scheduled_for ascending.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver
from app.db.database import get_db
from app.models.ride import Ride, RideStatus
from app.models.user import User
from app.schemas.driver_upcoming_rides import DriverUpcomingRide, DriverUpcomingRidesResponse

router = APIRouter(prefix="/driver", tags=["driver"])

_MAX_LIMIT = 50


@router.get(
    "/me/upcoming-scheduled",
    response_model=DriverUpcomingRidesResponse,
    summary="Get upcoming scheduled rides for the authenticated driver",
    description=(
        "Returns all SCHEDULED rides assigned to this driver with a future "
        "scheduled_for time, ordered soonest first. Use `limit` to cap results "
        "(max 50, default 20)."
    ),
)
async def get_upcoming_scheduled(
    limit: int = Query(default=20, ge=1, le=_MAX_LIMIT),
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverUpcomingRidesResponse:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Ride)
        .where(
            Ride.driver_id == driver.id,
            Ride.status == RideStatus.SCHEDULED,
            Ride.scheduled_for > now,
        )
        .order_by(Ride.scheduled_for.asc())
        .limit(limit)
    )
    rides = list(result.scalars().all())
    return DriverUpcomingRidesResponse(
        rides=[DriverUpcomingRide.model_validate(r) for r in rides],
        total=len(rides),
    )
