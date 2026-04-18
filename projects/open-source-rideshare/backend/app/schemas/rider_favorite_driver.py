from datetime import datetime

from pydantic import BaseModel


class FavoriteDriverEntry(BaseModel):
    """A single favourited driver as seen by the rider."""

    driver_profile_id: int
    vehicle_type: str
    vehicle_make: str
    vehicle_model: str
    vehicle_year: int
    vehicle_color: str
    rating_avg: float
    total_trips: int
    is_approved: bool
    member_since: datetime
    favorited_at: datetime


class FavoriteDriverListResponse(BaseModel):
    drivers: list[FavoriteDriverEntry]
    total: int
