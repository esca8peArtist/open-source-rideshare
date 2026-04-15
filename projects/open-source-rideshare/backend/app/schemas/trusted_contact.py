"""Schemas for trusted contacts and trip sharing."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator


class TrustedContactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    phone: str | None = Field(None, max_length=30)
    email: str | None = Field(None)
    relationship_label: str = Field("", max_length=80)
    share_automatically: bool = False

    @model_validator(mode="after")
    def require_phone_or_email(self) -> "TrustedContactCreate":
        if not self.phone and not self.email:
            raise ValueError("At least one of phone or email must be provided")
        return self


class TrustedContactUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=150)
    phone: str | None = Field(None, max_length=30)
    email: str | None = Field(None)
    relationship_label: str | None = Field(None, max_length=80)
    share_automatically: bool | None = None
    is_active: bool | None = None


class TrustedContactResponse(BaseModel):
    id: int
    user_id: int
    name: str
    phone: str | None
    email: str | None
    relationship_label: str
    share_automatically: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ShareTripRequest(BaseModel):
    """Body for POST /riders/me/rides/{ride_id}/share-trip.

    If contact_ids is omitted or empty, all active auto-share contacts are used.
    If contact_ids is provided, those specific contacts (must belong to the rider) are notified.
    """
    contact_ids: list[int] | None = None


class TripShareContactStatus(BaseModel):
    contact_id: int
    contact_name: str
    shared_at: datetime
    start_notified_at: datetime | None
    complete_notified_at: datetime | None


class TripShareStatusResponse(BaseModel):
    ride_id: int
    total_contacts_notified: int
    contacts: list[TripShareContactStatus]


class AdminTripShareSummary(BaseModel):
    total_shares: int
    total_rides_shared: int
    total_contacts: int
    auto_share_contacts: int
