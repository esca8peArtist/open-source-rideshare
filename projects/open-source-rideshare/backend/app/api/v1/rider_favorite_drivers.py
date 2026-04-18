"""Rider favourite driver endpoints.

GET    /riders/me/favorite-drivers               — list all favourites
POST   /riders/me/favorite-drivers/{driver_id}   — add to favourites
DELETE /riders/me/favorite-drivers/{driver_id}   — remove from favourites

driver_id in the path is the DriverProfile primary key.
Capped at 20 favourites per rider.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.deps import require_rider
from app.db.database import get_db
from app.models.driver import DriverProfile
from app.models.rider_favorite_driver import RiderFavoriteDriver, _MAX_FAVORITES
from app.models.user import User
from app.schemas.rider_favorite_driver import FavoriteDriverEntry, FavoriteDriverListResponse

router = APIRouter(prefix="/riders", tags=["riders"])


@router.get("/me/favorite-drivers", response_model=FavoriteDriverListResponse)
async def list_favorite_drivers(
    rider: User = Depends(require_rider),
    db: AsyncSession = Depends(get_db),
) -> FavoriteDriverListResponse:
    """List the rider's saved favourite drivers, newest first."""
    result = await db.execute(
        select(RiderFavoriteDriver)
        .options(joinedload(RiderFavoriteDriver.driver_profile))
        .where(RiderFavoriteDriver.rider_id == rider.id)
        .order_by(RiderFavoriteDriver.created_at.desc())
    )
    favourites = result.scalars().all()

    entries = [
        FavoriteDriverEntry(
            driver_profile_id=fav.driver_profile_id,
            vehicle_type=fav.driver_profile.vehicle_type,
            vehicle_make=fav.driver_profile.vehicle_make,
            vehicle_model=fav.driver_profile.vehicle_model,
            vehicle_year=fav.driver_profile.vehicle_year,
            vehicle_color=fav.driver_profile.vehicle_color,
            rating_avg=fav.driver_profile.rating_avg,
            total_trips=fav.driver_profile.total_trips,
            is_approved=fav.driver_profile.is_approved,
            member_since=fav.driver_profile.created_at,
            favorited_at=fav.created_at,
        )
        for fav in favourites
    ]
    return FavoriteDriverListResponse(drivers=entries, total=len(entries))


@router.post(
    "/me/favorite-drivers/{driver_id}",
    status_code=status.HTTP_201_CREATED,
)
async def add_favorite_driver(
    driver_id: int,
    rider: User = Depends(require_rider),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Add a driver to the rider's favourites.

    Returns 404 if the driver profile does not exist.
    Returns 409 if already in favourites.
    Returns 422 if the rider already has 20 favourites.
    """
    # Verify driver profile exists
    profile_result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == driver_id)
    )
    if not profile_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Driver not found")

    # Check already favourited
    existing_result = await db.execute(
        select(RiderFavoriteDriver).where(
            RiderFavoriteDriver.rider_id == rider.id,
            RiderFavoriteDriver.driver_profile_id == driver_id,
        )
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Driver is already in your favourites")

    # Enforce cap
    count_result = await db.execute(
        select(func.count(RiderFavoriteDriver.id)).where(
            RiderFavoriteDriver.rider_id == rider.id
        )
    )
    count = count_result.scalar() or 0
    if count >= _MAX_FAVORITES:
        raise HTTPException(
            status_code=422,
            detail=f"Favourites list is full (maximum {_MAX_FAVORITES}). Remove a driver first.",
        )

    fav = RiderFavoriteDriver(rider_id=rider.id, driver_profile_id=driver_id)
    db.add(fav)
    await db.commit()
    return {"status": "added", "driver_profile_id": driver_id}


@router.delete(
    "/me/favorite-drivers/{driver_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_favorite_driver(
    driver_id: int,
    rider: User = Depends(require_rider),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a driver from the rider's favourites."""
    result = await db.execute(
        select(RiderFavoriteDriver).where(
            RiderFavoriteDriver.rider_id == rider.id,
            RiderFavoriteDriver.driver_profile_id == driver_id,
        )
    )
    fav = result.scalar_one_or_none()
    if not fav:
        raise HTTPException(status_code=404, detail="Driver not found in your favourites")

    await db.delete(fav)
    await db.commit()
