"""Pydantic schemas for corporate account contacts."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.corporate_account_contact import ContactRole


class ContactCreateRequest(BaseModel):
    """Request body for registering a new operational contact."""

    name: str = Field(..., max_length=200)
    email: str = Field(..., max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    title: Optional[str] = Field(None, max_length=150)
    contact_role: ContactRole = Field(ContactRole.other)
    notes: Optional[str] = Field(None, max_length=1000)
    is_primary: bool = Field(False)


class ContactUpdateRequest(BaseModel):
    """Request body for partially updating an operational contact.

    All fields are optional — only supplied fields are updated.
    """

    name: Optional[str] = Field(None, max_length=200)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    title: Optional[str] = Field(None, max_length=150)
    contact_role: Optional[ContactRole] = None
    notes: Optional[str] = Field(None, max_length=1000)
    is_primary: Optional[bool] = None


class ContactResponse(BaseModel):
    """A single operational contact (safe to return to clients)."""

    id: int
    account_id: int
    name: str
    email: str
    phone: Optional[str]
    title: Optional[str]
    contact_role: ContactRole
    notes: Optional[str]
    is_primary: bool
    is_active: bool
    added_by_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContactListResponse(BaseModel):
    """Paginated list of operational contacts."""

    account_id: int
    total: int
    items: list[ContactResponse]


class ContactDeactivateResponse(BaseModel):
    """Response returned after deactivating a contact."""

    id: int
    account_id: int
    is_active: bool
    message: str
