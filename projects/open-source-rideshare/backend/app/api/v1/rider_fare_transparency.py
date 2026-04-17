"""Rider fare transparency API endpoint.

Shows riders the exact breakdown of a single completed ride fare: driver
payout percentage, platform fee, taxes, and a side-by-side comparison to
estimated Uber/Lyft fees for the same fare — so riders can see where their
money goes vs. traditional rideshare platforms.

Endpoint:
  GET /rides/{ride_id}/fare-breakdown

Authorization:
  - Riders may only access their own rides.
  - Admins may access any ride.

Distinct from:
  - /drivers/me/earnings-comparison — driver-facing multi-ride comparison
  - /rides/{ride_id}/receipt        — receipt/invoice document view
  - /payments/                      — raw payment record CRUD
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.rider_fare_transparency import FareBreakdownResponse
from app.services.rider_fare_transparency import get_fare_breakdown

logger = logging.getLogger(__name__)

router = APIRouter(tags=["fare-transparency"])


@router.get(
    "/rides/{ride_id}/fare-breakdown",
    response_model=FareBreakdownResponse,
    summary="Get fare breakdown for a completed ride",
)
async def get_ride_fare_breakdown(
    ride_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FareBreakdownResponse:
    """Return an itemised fare breakdown for a completed ride.

    Shows the rider exactly where their money went:

    - **Driver payout** — dollar amount and percentage of total fare.
    - **Platform fee** — OpenRide's cut in dollars and percentage.
    - **Tip** — if included, always 100% to the driver.
    - **Taxes** — currently $0.00; surfaced for future transparency if tax
      tracking is introduced.
    - **Competitor comparison** — estimated platform fees for the same fare on
      Uber (25–28%) and Lyft (20–25%), so the rider can see the difference.
    - **Driver advantage** — how much more the driver received on OpenRide vs.
      estimated competitor payouts.

    The `platform_fee_is_estimated` flag in the response indicates whether the
    platform fee was read from the actual Payment record (preferred) or derived
    from the documented standard rate constant (fallback for cash rides or
    legacy records).

    **Authorization**: Riders may only retrieve fare breakdowns for their own
    rides. Admins may access any ride.
    """
    return await get_fare_breakdown(
        db=db,
        ride_id=ride_id,
        current_user=current_user,
    )
