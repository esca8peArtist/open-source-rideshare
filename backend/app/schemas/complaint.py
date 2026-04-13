"""Pydantic schemas for the complaint and dispute management feature."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.complaint import ComplaintCategory, ComplaintStatus


class ComplaintCreate(BaseModel):
    """Request body for filing a new complaint.

    against_user_id: the user being complained about.
    ride_id: optional but strongly recommended — links the complaint to a specific trip.
    description: minimum 20 characters to ensure meaningful detail.
    """

    against_user_id: int = Field(..., description="User ID of the person being complained about")
    ride_id: Optional[int] = Field(None, description="ID of the associated ride, if applicable")
    category: ComplaintCategory = Field(..., description="Category that best describes the complaint")
    description: str = Field(
        ...,
        min_length=20,
        max_length=2000,
        description="Detailed description of the complaint (min 20 characters)",
    )


class ComplaintResponse(BaseModel):
    """Response body for a complaint visible to the filing user.

    admin_notes are only included when the complaint has been resolved or dismissed,
    to prevent leaking investigation details while the complaint is active.
    """

    id: int
    filed_by_user_id: int
    against_user_id: int
    ride_id: Optional[int]
    category: ComplaintCategory
    description: str
    status: ComplaintStatus
    admin_notes: Optional[str]  # only populated when status is resolved or dismissed
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AdminComplaintResponse(ComplaintResponse):
    """Extended complaint response for admin users.

    Includes user names for context and the admin who resolved the complaint.
    """

    filed_by_name: str
    against_name: str
    resolved_by_admin_id: Optional[int]

    model_config = {"from_attributes": True}


class ComplaintUpdateAdmin(BaseModel):
    """Request body for admin updating a complaint's status.

    Cannot update a complaint that is already resolved or dismissed.
    admin_notes are required when resolving or dismissing.
    """

    status: ComplaintStatus = Field(
        ...,
        description="New status: reviewing | resolved | dismissed",
    )
    admin_notes: Optional[str] = Field(
        None,
        max_length=5000,
        description="Admin notes about the investigation or resolution",
    )
