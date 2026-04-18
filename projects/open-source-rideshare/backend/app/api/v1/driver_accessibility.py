"""Driver accessibility capability flag endpoints.

Driver-facing:
  GET  /drivers/me/accessibility  — read current accessibility flags
  PUT  /drivers/me/accessibility  — update accessibility flags (partial update)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import require_driver
from app.db.database import get_db
from app.models.user import User
from app.schemas.driver_accessibility import (
    DriverAccessibilityResponse,
    DriverAccessibilityUpdate,
)
from app.services.driver_accessibility import get_accessibility, update_accessibility
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/drivers/me", tags=["driver-accessibility"])


@router.get(
    "/accessibility",
    response_model=DriverAccessibilityResponse,
    summary="Get my accessibility capability flags",
)
async def get_my_accessibility(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return the current driver's accessibility capability flags.

    Returns 404 if the driver has not yet created a profile.
    """
    profile = await get_accessibility(db, user.id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found.",
        )
    return DriverAccessibilityResponse.model_validate(profile)


@router.put(
    "/accessibility",
    response_model=DriverAccessibilityResponse,
    summary="Update my accessibility capability flags",
)
async def update_my_accessibility(
    updates: DriverAccessibilityUpdate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Update accessibility capability flags.  Only provided fields are changed.

    All fields are optional — send only what you want to change.

    Returns 404 if the driver has not yet created a profile.
    """
    try:
        profile = await update_accessibility(db, user.id, updates)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found.",
        )
    return DriverAccessibilityResponse.model_validate(profile)
