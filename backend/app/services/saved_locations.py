"""Saved locations service.

Manages CRUD for user-saved locations (home, work, favorites).
Enforces per-user limits and uniqueness of home/work labels.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.saved_location import LocationLabel, SavedLocation

MAX_SAVED_LOCATIONS = 20


class SavedLocationError(Exception):
    pass


async def create_saved_location(
    db: AsyncSession,
    user_id: int,
    label: str,
    name: str,
    address: str,
    lat: float,
    lng: float,
    place_id: str | None = None,
    icon: str | None = None,
) -> SavedLocation:
    """Create a new saved location for a user."""
    # Check per-user limit
    count_result = await db.execute(
        select(func.count()).select_from(SavedLocation).where(
            SavedLocation.user_id == user_id
        )
    )
    count = count_result.scalar()
    if count >= MAX_SAVED_LOCATIONS:
        raise SavedLocationError(
            f"Maximum {MAX_SAVED_LOCATIONS} saved locations allowed"
        )

    label_enum = LocationLabel(label)

    # Home and work are unique per user — replace if exists
    if label_enum in (LocationLabel.HOME, LocationLabel.WORK):
        existing = await _get_by_label(db, user_id, label_enum)
        if existing:
            raise SavedLocationError(
                f"A '{label}' location already exists. Update or delete it first."
            )

    location = SavedLocation(
        user_id=user_id,
        label=label_enum,
        name=name,
        address=address,
        lat=lat,
        lng=lng,
        place_id=place_id,
        icon=icon,
    )
    db.add(location)
    await db.flush()
    return location


async def get_saved_locations(
    db: AsyncSession, user_id: int
) -> list[SavedLocation]:
    """Get all saved locations for a user, ordered: home first, work second, then by name."""
    result = await db.execute(
        select(SavedLocation)
        .where(SavedLocation.user_id == user_id)
        .order_by(
            # home=0, work=1, custom=2
            SavedLocation.label,
            SavedLocation.name,
        )
    )
    return list(result.scalars().all())


async def get_saved_location(
    db: AsyncSession, user_id: int, location_id: int
) -> SavedLocation | None:
    """Get a single saved location by ID, scoped to user."""
    result = await db.execute(
        select(SavedLocation).where(
            SavedLocation.id == location_id,
            SavedLocation.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def update_saved_location(
    db: AsyncSession,
    user_id: int,
    location_id: int,
    updates: dict,
) -> SavedLocation:
    """Update fields on a saved location."""
    location = await get_saved_location(db, user_id, location_id)
    if not location:
        raise SavedLocationError("Saved location not found")

    # If changing label to home/work, check uniqueness
    if "label" in updates:
        new_label = LocationLabel(updates["label"])
        if new_label in (LocationLabel.HOME, LocationLabel.WORK) and new_label != location.label:
            existing = await _get_by_label(db, user_id, new_label)
            if existing:
                raise SavedLocationError(
                    f"A '{new_label.value}' location already exists"
                )
        updates["label"] = new_label

    for field, value in updates.items():
        setattr(location, field, value)
    await db.flush()
    return location


async def delete_saved_location(
    db: AsyncSession, user_id: int, location_id: int
) -> bool:
    """Delete a saved location. Returns True if deleted, False if not found."""
    location = await get_saved_location(db, user_id, location_id)
    if not location:
        return False
    await db.delete(location)
    await db.flush()
    return True


async def _get_by_label(
    db: AsyncSession, user_id: int, label: LocationLabel
) -> SavedLocation | None:
    """Get a user's saved location by label (used for home/work uniqueness)."""
    result = await db.execute(
        select(SavedLocation).where(
            SavedLocation.user_id == user_id,
            SavedLocation.label == label,
        )
    )
    return result.scalar_one_or_none()
