"""Driver income stability report API endpoint.

GET /drivers/me/income-stability-report

Rationale:
    Gig platforms like Uber and Lyft are structurally indifferent to driver
    income instability — their business model thrives on flexible labor supply
    regardless of driver financial outcomes.  A driver-owned cooperative has
    an obligation to quantify and address income volatility, because
    unpredictable earnings harm members' financial wellbeing.  This endpoint
    surfaces a 12-week retrospective of a driver's earnings variance to help
    them understand their income stability and plan accordingly.  It also
    acknowledges when the platform's earnings guarantee (if active) helped
    smooth income.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver
from app.db.database import get_db
from app.models.user import User
from app.schemas.driver_income_stability import DriverIncomeStabilityReport
from app.services.driver_income_stability import get_driver_income_stability_report

logger = logging.getLogger(__name__)

router = APIRouter(tags=["driver-income"])


@router.get(
    "/drivers/me/income-stability-report",
    response_model=DriverIncomeStabilityReport,
    summary="Driver income stability report (12 weeks)",
    description=(
        "Returns a 12-week retrospective income stability report for the "
        "authenticated driver.  Includes:\n\n"
        "- **Weeks analyzed**: active weeks vs. inactive weeks in the window\n"
        "- **Variance metrics**: mean, standard deviation, and coefficient of "
        "variation across active weeks\n"
        "- **Stability tier**: 'high' (CV < 0.2), 'moderate' (0.2–0.4), "
        "'low' (CV > 0.4), or 'insufficient_data'\n"
        "- **Trend direction**: comparing the most recent 4 weeks against the "
        "oldest 4 weeks in the window\n"
        "- **Best and worst non-zero weeks**: range of earnings across active weeks\n"
        "- **Guarantee activations**: weeks where the cooperative's earnings "
        "guarantee topped up the driver's pay\n"
        "- **Weekly breakdown**: per-week earnings, ride count, and guarantee "
        "status for all 12 weeks, newest-first\n"
        "- **Stability note**: a plain-language summary of the driver's situation\n\n"
        "This is a deliberate cooperative differentiator — income volatility "
        "visibility is a core obligation of a platform owned by its drivers."
    ),
)
async def get_income_stability_report(
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverIncomeStabilityReport:
    """Return the 12-week income stability report for the authenticated driver."""
    return await get_driver_income_stability_report(db=db, driver_id=driver.id)
