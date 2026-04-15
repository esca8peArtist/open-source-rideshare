"""Pydantic v2 schemas for Corporate Member Ride Quotas.

Corporate account admins set per-member ride count limits scoped to a time
period.  These schemas cover quota creation, updates, and the enriched
responses that include current usage statistics.

Public surface
--------------
QuotaPeriod           — enum of allowed time windows (daily/weekly/monthly).
QuotaCreate           — request body for setting a new quota.
QuotaUpdate           — request body for updating max_rides or is_active.
QuotaResponse         — full quota record returned by the API.
QuotaWithUsageResponse — quota record enriched with current usage data.
QuotaListResponse     — paginated list of quota records.
QuotaCheckResponse    — quota status + current usage for a (member, period).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class QuotaPeriod(str, Enum):
    """Supported time windows for ride quotas."""

    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class QuotaCreate(BaseModel):
    """Request body for setting a ride quota on a corporate member.

    Attributes:
        member_id:  User ID of the employee to be quota-d.
        period:     Time window: daily, weekly, or monthly.
        max_rides:  Maximum rides allowed per period (1–500).
    """

    member_id: int
    period: QuotaPeriod
    max_rides: int = Field(..., ge=1, le=500)


class QuotaUpdate(BaseModel):
    """Request body for updating an existing ride quota.

    Only supplied fields are applied; omitted fields are left unchanged.

    Attributes:
        max_rides: New maximum rides per period (1–500), if changing.
        is_active: Whether the quota should be actively enforced.
    """

    max_rides: Optional[int] = Field(None, ge=1, le=500)
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class QuotaResponse(BaseModel):
    """Full quota record returned by the API.

    Attributes:
        id:            Primary key.
        account_id:    Corporate account the quota belongs to.
        member_id:     Employee being quota-d.
        period:        Time window string ("daily", "weekly", "monthly").
        max_rides:     Maximum rides allowed per period.
        is_active:     Whether this quota is currently enforced.
        created_by_id: Admin who created the quota (null if creator deleted).
        created_at:    When the quota was created.
        updated_at:    When the quota was last modified.
    """

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    member_id: int
    period: str
    max_rides: int
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class QuotaWithUsageResponse(BaseModel):
    """Quota record enriched with current-period usage statistics.

    Attributes:
        id:                   Primary key.
        account_id:           Corporate account the quota belongs to.
        member_id:            Employee being quota-d.
        period:               Time window string.
        max_rides:            Maximum rides allowed per period.
        is_active:            Whether this quota is currently enforced.
        created_by_id:        Admin who created the quota.
        created_at:           Creation timestamp.
        updated_at:           Last-modified timestamp.
        current_period_rides: Number of qualifying rides taken this period.
        remaining_rides:      max_rides - current_period_rides (floor 0).
        quota_exceeded:       True when current_period_rides >= max_rides.
    """

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    member_id: int
    period: str
    max_rides: int
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    current_period_rides: int
    remaining_rides: int
    quota_exceeded: bool


class QuotaListResponse(BaseModel):
    """Paginated list of quota records.

    Attributes:
        quotas: Quota records.
        total:  Number of records returned.
    """

    quotas: List[QuotaResponse]
    total: int


class QuotaCheckResponse(BaseModel):
    """Quota status and current usage for a (member, period) combination.

    Attributes:
        member_id:            Employee whose quota is being checked.
        period:               Time window queried.
        max_rides:            Maximum rides allowed per period (0 if no quota).
        current_period_rides: Qualifying rides taken so far this period.
        remaining_rides:      Rides left before the limit is reached.
        quota_exceeded:       True when the limit has been reached or passed.
        quota_active:         False when no quota is set or quota is inactive
                              (meaning rides are unrestricted for this combo).
    """

    member_id: int
    period: str
    max_rides: int
    current_period_rides: int
    remaining_rides: int
    quota_exceeded: bool
    quota_active: bool
