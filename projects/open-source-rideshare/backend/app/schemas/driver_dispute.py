"""Pydantic schemas for the driver dispute resolution endpoints.

POST   /drivers/me/disputes
GET    /drivers/me/disputes
GET    /drivers/me/disputes/{dispute_id}
POST   /drivers/me/disputes/{dispute_id}/appeal
DELETE /drivers/me/disputes/{dispute_id}
GET    /admin/disputes
POST   /admin/disputes/{dispute_id}/resolve

On Uber and Lyft, drivers have no meaningful dispute resolution — fares get
silently adjusted, accounts get deactivated without recourse, false rider
complaints stick with no appeal.  A cooperative platform is legally and
ethically obligated to provide due process to its member-owners.  These
schemas surface that process via the API.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DisputeType(str, Enum):
    FARE_ADJUSTMENT = "FARE_ADJUSTMENT"
    DEACTIVATION_APPEAL = "DEACTIVATION_APPEAL"
    FALSE_COMPLAINT = "FALSE_COMPLAINT"
    PAYMENT_MISSING = "PAYMENT_MISSING"
    OTHER = "OTHER"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    PENDING_APPEAL = "PENDING_APPEAL"
    RESOLVED_IN_DRIVER_FAVOR = "RESOLVED_IN_DRIVER_FAVOR"
    RESOLVED_AGAINST_DRIVER = "RESOLVED_AGAINST_DRIVER"
    DISMISSED = "DISMISSED"
    WITHDRAWN = "WITHDRAWN"


class FileDisputeRequest(BaseModel):
    """Request body for filing a new dispute."""

    dispute_type: DisputeType = Field(
        ...,
        description=(
            "Category of dispute: FARE_ADJUSTMENT, DEACTIVATION_APPEAL, "
            "FALSE_COMPLAINT, PAYMENT_MISSING, or OTHER."
        ),
    )
    description: str = Field(
        ...,
        min_length=20,
        max_length=2000,
        description="Full description of the dispute (20–2000 characters).",
    )
    ride_id: Optional[int] = Field(
        None,
        description="ID of the specific ride this dispute relates to, if applicable.",
    )
    amount_disputed_usd: Optional[Decimal] = Field(
        None,
        ge=0,
        description="Dollar amount being disputed, if monetary.  Must be >= 0.",
    )


class AppealDecisionRequest(BaseModel):
    """Request body for appealing a RESOLVED_AGAINST_DRIVER decision."""

    appeal_reason: str = Field(
        ...,
        min_length=20,
        max_length=1000,
        description="Reason for appealing the resolution (20–1000 characters).",
    )


class ResolveDisputeRequest(BaseModel):
    """Admin request body for resolving a dispute.

    Only RESOLVED_IN_DRIVER_FAVOR, RESOLVED_AGAINST_DRIVER, and DISMISSED are
    valid resolution statuses.  OPEN, UNDER_REVIEW, PENDING_APPEAL, and
    WITHDRAWN cannot be set via this endpoint.
    """

    resolution: DisputeStatus = Field(
        ...,
        description=(
            "Final resolution status.  Must be one of: RESOLVED_IN_DRIVER_FAVOR, "
            "RESOLVED_AGAINST_DRIVER, DISMISSED."
        ),
    )
    admin_notes: Optional[str] = Field(
        None,
        description="Internal admin notes on the resolution decision (not shown to driver).",
    )


class DisputeResponse(BaseModel):
    """Full dispute record returned to drivers and admins."""

    id: int = Field(..., description="Unique dispute identifier.")
    driver_id: int = Field(..., description="ID of the driver who filed the dispute.")
    dispute_type: DisputeType = Field(..., description="Category of the dispute.")
    status: DisputeStatus = Field(..., description="Current dispute status.")
    description: str = Field(..., description="Driver-submitted description.")
    ride_id: Optional[int] = Field(None, description="Related ride ID, if any.")
    amount_disputed_usd: Optional[Decimal] = Field(
        None, description="Dollar amount disputed, if monetary."
    )
    filed_at: datetime = Field(..., description="UTC timestamp when the dispute was filed.")
    updated_at: datetime = Field(..., description="UTC timestamp of the most recent update.")
    resolution_at: Optional[datetime] = Field(
        None,
        description="UTC timestamp when the dispute was resolved or dismissed.",
    )
    admin_notes: Optional[str] = Field(
        None,
        description="Admin resolution notes (visible to admins; not shown to drivers in driver-facing responses).",
    )
    appeal_reason: Optional[str] = Field(
        None,
        description="Driver-submitted appeal reason, if an appeal was filed.",
    )
    appeal_filed_at: Optional[datetime] = Field(
        None,
        description="UTC timestamp when the appeal was filed.",
    )
    is_overdue: bool = Field(
        ...,
        description=(
            "True if the dispute was filed more than 14 days ago and is still OPEN "
            "or UNDER_REVIEW.  Cooperative platforms are obligated to resolve "
            "member disputes in a timely manner."
        ),
    )


class DisputeListResponse(BaseModel):
    """Paginated list of disputes."""

    total: int = Field(..., description="Total number of disputes matching the query.")
    items: list[DisputeResponse] = Field(
        ..., description="Page of dispute records."
    )
