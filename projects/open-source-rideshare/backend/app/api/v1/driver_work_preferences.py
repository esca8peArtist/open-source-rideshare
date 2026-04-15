"""Driver Work Preferences endpoints.

Drivers can specify what kinds of rides they are willing to accept — pool vs
solo, pet passengers, extra luggage, trip distance ranges, and whether they
prefer language-matched dispatch.  Giving drivers meaningful control over
their workload is a core cooperative value: Uber/Lyft's algorithmic dispatch
ignores driver preferences entirely.

Authenticated driver endpoints:
  GET    /drivers/me/work-preferences   — view own preferences (auto-creates defaults)
  PUT    /drivers/me/work-preferences   — partial update
  DELETE /drivers/me/work-preferences   — reset to platform defaults

Admin endpoints:
  GET  /admin/drivers/{driver_id}/work-preferences — view any driver's preferences
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.driver_work_preference import (
    DriverWorkPreferenceResponse,
    DriverWorkPreferenceUpdate,
)
from app.services.driver_work_preference import (
    get_preferences,
    reset_preferences,
    update_preferences,
)

router = APIRouter(tags=["driver-work-preferences"])


# ---------------------------------------------------------------------------
# Driver: manage own work preferences
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/work-preferences",
    response_model=DriverWorkPreferenceResponse,
    summary="View my work preferences",
)
async def get_my_work_preferences(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DriverWorkPreferenceResponse:
    """Return the authenticated driver's work preferences.

    A default row is automatically created on first access — drivers are
    always opted-in to all ride types by default so new drivers aren't
    inadvertently excluded from dispatch.
    """
    prefs = await get_preferences(db, user.id)
    return DriverWorkPreferenceResponse.model_validate(prefs)


@router.put(
    "/drivers/me/work-preferences",
    response_model=DriverWorkPreferenceResponse,
    summary="Update my work preferences",
)
async def update_my_work_preferences(
    body: DriverWorkPreferenceUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DriverWorkPreferenceResponse:
    """Partially update the authenticated driver's work preferences.

    Only supplied (non-null) fields are written; omitted fields retain their
    current value.  Distance range is validated: min <= max when both are set.
    """
    prefs = await update_preferences(db, user.id, body)
    return DriverWorkPreferenceResponse.model_validate(prefs)


@router.delete(
    "/drivers/me/work-preferences",
    response_model=DriverWorkPreferenceResponse,
    summary="Reset my work preferences to defaults",
)
async def reset_my_work_preferences(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DriverWorkPreferenceResponse:
    """Reset the authenticated driver's work preferences to platform defaults.

    Returns the new (default) preference state.  Useful when a driver wants
    to clear all customisations and start fresh.
    """
    prefs = await reset_preferences(db, user.id)
    return DriverWorkPreferenceResponse.model_validate(prefs)


# ---------------------------------------------------------------------------
# Admin: view any driver's preferences
# ---------------------------------------------------------------------------


@router.get(
    "/admin/drivers/{driver_id}/work-preferences",
    response_model=DriverWorkPreferenceResponse,
    summary="Admin: view a driver's work preferences",
    dependencies=[Depends(require_admin)],
)
async def admin_get_driver_work_preferences(
    driver_id: int,
    db: AsyncSession = Depends(get_db),
) -> DriverWorkPreferenceResponse:
    """Admin view of any driver's work preferences.

    Useful when investigating dispatch issues or auditing driver availability
    configuration.
    """
    prefs = await get_preferences(db, driver_id)
    return DriverWorkPreferenceResponse.model_validate(prefs)
