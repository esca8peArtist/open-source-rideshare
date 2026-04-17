"""Driver welfare summary API endpoint.

GET /drivers/me/welfare-summary

A cooperative-only feature that surfaces a holistic welfare snapshot to the
authenticated driver: shift hours vs. safety limits, earnings this week,
insurance status, and cooperative standing.

Rationale:
    Uber and Lyft have no equivalent endpoint because they have no structural
    incentive to surface driver fatigue or burnout risk — their business model
    is indifferent to driver working hours.  A driver-owned cooperative is
    legally and ethically obligated to act in the collective interest of its
    member-owners, which includes not normalising dangerous working hours.

    This endpoint is designed for the driver app home screen or a dedicated
    welfare section, providing a single API call that replaces fetching data
    from five separate endpoints.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver
from app.db.database import get_db
from app.models.user import User
from app.schemas.driver_welfare_summary import DriverWelfareSummary
from app.services.driver_welfare_summary import get_driver_welfare_summary

logger = logging.getLogger(__name__)

router = APIRouter(tags=["driver-welfare"])


@router.get(
    "/drivers/me/welfare-summary",
    response_model=DriverWelfareSummary,
    summary="Driver welfare snapshot",
    description=(
        "Returns a holistic welfare snapshot for the authenticated driver.  "
        "Includes:\n\n"
        "- **Shift hours** (last 7 days): total, today, max consecutive, active "
        "shift duration, fatigue risk level\n"
        "- **Earnings** (last 7 days): gross fares, tips, hourly rate estimate, "
        "earnings goal progress\n"
        "- **Insurance status**: active / expiring soon / pending / expired / "
        "not on file, with days-until-expiry\n"
        "- **Cooperative status**: approval, lifetime trips, rating, background "
        "check status\n"
        "- **Welfare note**: single most important message tailored to the "
        "driver's current state\n"
        "- **Support resources**: always includes driver safety guidelines and "
        "cooperative hardship fund\n\n"
        "This is a deliberate cooperative differentiator — driver welfare "
        "visibility is a core obligation of a platform owned by its drivers."
    ),
)
async def get_welfare_summary(
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverWelfareSummary:
    """Return the welfare snapshot for the authenticated driver."""
    return await get_driver_welfare_summary(db=db, driver_id=driver.id)
