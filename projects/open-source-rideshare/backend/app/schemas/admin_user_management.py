"""Schemas for admin user management endpoints.

Covers:
- GET  /admin/users            — paginated user list
- GET  /admin/users/{user_id}  — detailed user profile
- POST /admin/users/{user_id}/suspend   — suspend account
- POST /admin/users/{user_id}/activate  — reactivate account
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class UserSummary(BaseModel):
    """Compact user row returned in the paginated list."""

    id: int
    name: str
    email: str | None
    phone: str
    role: str
    status: str
    is_active: bool
    created_at: datetime
    ride_count: int


class UserListResponse(BaseModel):
    """Paginated user list response."""

    users: list[UserSummary] = Field(default_factory=list)
    total_count: int
    page: int
    page_size: int


class UserRideStats(BaseModel):
    """Ride statistics embedded in the detailed user profile."""

    total_rides: int
    completed_rides: int
    cancelled_rides: int
    avg_rating: float | None = Field(
        None,
        description="Average rating received by this user (as rider or driver). None if no ratings.",
    )


class UserDetailResponse(BaseModel):
    """Full user profile for admin inspection."""

    id: int
    name: str
    email: str | None
    phone: str
    role: str
    status: str
    is_active: bool
    phone_verified: bool
    suspension_reason: str | None
    referral_code: str | None
    referred_by: int | None
    created_at: datetime
    updated_at: datetime
    ride_stats: UserRideStats


class SuspendUserRequest(BaseModel):
    """Body for POST /admin/users/{user_id}/suspend."""

    reason: str = Field(..., min_length=1, max_length=500, description="Reason for suspension")
    notify_user: bool = Field(True, description="Send notification to the user if True")


class ActivateUserRequest(BaseModel):
    """Body for POST /admin/users/{user_id}/activate."""

    reason: str = Field("", max_length=500, description="Optional reason for reactivation")
    notify_user: bool = Field(True, description="Send notification to the user if True")


class UserStatusChangeResponse(BaseModel):
    """Response for suspend/activate actions."""

    user_id: int
    previous_status: str
    new_status: str
    notified: bool
