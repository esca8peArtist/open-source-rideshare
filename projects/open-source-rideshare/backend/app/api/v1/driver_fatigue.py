"""Driver fatigue monitoring endpoints.

GET  /drivers/me/fatigue-status              — driver sees own fatigue status
GET  /admin/driver-fatigue-alerts            — admin sees all WARNING/LIMIT_REACHED drivers
POST /admin/driver-fatigue/{driver_id}/reset — admin manually resets a driver's fatigue state

Fatigued drivers are a safety risk.  This feature enforces rolling 24-hour
active-hour limits:
  < 8h  → NORMAL
  8–10h → WARNING (warned but can still accept rides)
  ≥ 10h → LIMIT_REACHED (blocked from accepting new rides)
After 6 consecutive hours of rest (no active rides) the status resets to NORMAL.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user, require_admin, require_driver
from app.models.user import User
from app.schemas.driver_fatigue import FatigueAlert, FatigueStatus
from app.services.driver_fatigue import (
    compute_fatigue_status,
    get_all_warnings,
    reset_driver_fatigue,
)

router = APIRouter(tags=["driver-fatigue"])


@router.get(
    "/drivers/me/fatigue-status",
    response_model=FatigueStatus,
    summary="Get own fatigue status",
    description=(
        "Returns the authenticated driver's current fatigue status based on "
        "active driving hours in the rolling 24-hour window.  "
        "Status is NORMAL (<8h), WARNING (8–10h), or LIMIT_REACHED (≥10h).  "
        "Drivers at LIMIT_REACHED are blocked from accepting new rides until "
        "they have rested for 6 consecutive hours."
    ),
)
async def get_my_fatigue_status(
    driver: User = Depends(require_driver),
) -> FatigueStatus:
    return compute_fatigue_status(driver_id=driver.id)


@router.get(
    "/admin/driver-fatigue-alerts",
    response_model=list[FatigueAlert],
    summary="List all drivers at WARNING or LIMIT_REACHED",
    description=(
        "Admin endpoint.  Returns a list of all drivers currently at WARNING "
        "or LIMIT_REACHED fatigue status, including their active hours and "
        "the timestamp of their last completed ride."
    ),
)
async def get_fatigue_alerts(
    admin: User = Depends(require_admin),
) -> list[FatigueAlert]:
    return get_all_warnings()


@router.post(
    "/admin/driver-fatigue/{driver_id}/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Manually reset a driver's fatigue state",
    description=(
        "Admin endpoint.  Clears all fatigue log entries for the specified "
        "driver.  Use this when a verified rest period cannot be auto-detected "
        "(e.g. data loss, driver's first ride of the day).  After reset the "
        "driver's status returns to NORMAL with 0 active hours."
    ),
)
async def reset_fatigue(
    driver_id: int,
    admin: User = Depends(require_admin),
) -> None:
    reset_driver_fatigue(driver_id=driver_id)
