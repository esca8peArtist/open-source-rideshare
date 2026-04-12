from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.saved_location import (
    SavedLocationCreate,
    SavedLocationResponse,
    SavedLocationUpdate,
)
from app.services.saved_locations import (
    SavedLocationError,
    create_saved_location,
    delete_saved_location,
    get_saved_location,
    get_saved_locations,
    update_saved_location,
)

router = APIRouter(prefix="/me/saved-locations", tags=["saved-locations"])


@router.get("", response_model=list[SavedLocationResponse])
async def list_saved_locations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all saved locations for the current user."""
    locations = await get_saved_locations(db, user.id)
    return [
        SavedLocationResponse(
            id=loc.id,
            user_id=loc.user_id,
            label=loc.label.value,
            name=loc.name,
            address=loc.address,
            lat=loc.lat,
            lng=loc.lng,
            place_id=loc.place_id,
            icon=loc.icon,
            created_at=loc.created_at,
            updated_at=loc.updated_at,
        )
        for loc in locations
    ]


@router.post("", response_model=SavedLocationResponse, status_code=status.HTTP_201_CREATED)
async def add_saved_location(
    req: SavedLocationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save a new location (home, work, or custom favorite)."""
    try:
        location = await create_saved_location(
            db,
            user_id=user.id,
            label=req.label,
            name=req.name,
            address=req.address,
            lat=req.lat,
            lng=req.lng,
            place_id=req.place_id,
            icon=req.icon,
        )
        await db.commit()
        await db.refresh(location)
    except SavedLocationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    return SavedLocationResponse(
        id=location.id,
        user_id=location.user_id,
        label=location.label.value,
        name=location.name,
        address=location.address,
        lat=location.lat,
        lng=location.lng,
        place_id=location.place_id,
        icon=location.icon,
        created_at=location.created_at,
        updated_at=location.updated_at,
    )


@router.get("/{location_id}", response_model=SavedLocationResponse)
async def get_location(
    location_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific saved location."""
    location = await get_saved_location(db, user.id, location_id)
    if not location:
        raise HTTPException(status_code=404, detail="Saved location not found")

    return SavedLocationResponse(
        id=location.id,
        user_id=location.user_id,
        label=location.label.value,
        name=location.name,
        address=location.address,
        lat=location.lat,
        lng=location.lng,
        place_id=location.place_id,
        icon=location.icon,
        created_at=location.created_at,
        updated_at=location.updated_at,
    )


@router.put("/{location_id}", response_model=SavedLocationResponse)
async def update_location(
    location_id: int,
    req: SavedLocationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a saved location."""
    try:
        location = await update_saved_location(
            db,
            user_id=user.id,
            location_id=location_id,
            updates=req.model_dump(exclude_unset=True),
        )
        await db.commit()
        await db.refresh(location)
    except SavedLocationError as e:
        detail = str(e)
        code = 404 if "not found" in detail.lower() else 409
        raise HTTPException(status_code=code, detail=detail)

    return SavedLocationResponse(
        id=location.id,
        user_id=location.user_id,
        label=location.label.value,
        name=location.name,
        address=location.address,
        lat=location.lat,
        lng=location.lng,
        place_id=location.place_id,
        icon=location.icon,
        created_at=location.created_at,
        updated_at=location.updated_at,
    )


@router.delete("/{location_id}", status_code=status.HTTP_200_OK)
async def remove_location(
    location_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a saved location."""
    deleted = await delete_saved_location(db, user.id, location_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved location not found")
    await db.commit()
    return {"status": "deleted"}
