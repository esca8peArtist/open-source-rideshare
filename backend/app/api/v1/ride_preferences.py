"""Ride preference API endpoints.

Rider-facing:
  GET  /me/ride-preferences               — get current preferences (auto-creates defaults)
  PUT  /me/ride-preferences               — update preferences (partial update)

Driver-facing (read-only):
  GET  /rides/{ride_id}/rider-preferences — view matched rider's preferences
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_driver
from app.db.database import get_db
from app.models.ride import Ride, RideStatus
from app.models.user import User
from app.schemas.ride_preference import RidePreferenceResponse, RidePreferenceUpdate
from app.services.ride_preferences import get_preferences, get_preferences_for_ride, update_preferences

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ride-preferences"])


# ---------------------------------------------------------------------------
# Rider endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/me/ride-preferences",
    response_model=RidePreferenceResponse,
    summary="Get my ride preferences",
)
async def get_my_ride_preferences(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current rider's ride preferences.

    Creates a default preference row if none exists yet.
    """
    prefs = await get_preferences(db, user.id)
    return RidePreferenceResponse.model_validate(prefs)


@router.put(
    "/me/ride-preferences",
    response_model=RidePreferenceResponse,
    summary="Update my ride preferences",
)
async def update_my_ride_preferences(
    updates: RidePreferenceUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update ride preferences.  Only provided fields are changed.

    All fields are optional — send only what you want to change.
    """
    prefs = await update_preferences(db, user.id, updates)
    return RidePreferenceResponse.model_validate(prefs)


# ---------------------------------------------------------------------------
# Driver endpoint (read matched rider's preferences)
# ---------------------------------------------------------------------------


@router.get(
    "/rides/{ride_id}/rider-preferences",
    response_model=RidePreferenceResponse | None,
    summary="View the matched rider's preferences (driver only)",
)
async def get_rider_preferences_for_ride(
    ride_id: int,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Driver reads the rider's preferences for an active/assigned ride.

    Returns None if the rider has not set any preferences.
    Returns 403 if the requesting driver is not assigned to this ride.
    Returns 404 if the ride is not found.
    """
    result = await db.execute(
        select(Ride).where(Ride.id == ride_id)
    )
    ride = result.scalar_one_or_none()

    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ride {ride_id} not found.",
        )

    # Verify the driver is assigned to this ride
    if ride.driver_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to this ride.",
        )

    prefs = await get_preferences_for_ride(db, ride.rider_id)
    if prefs is None:
        return None

    return RidePreferenceResponse.model_validate(prefs)
