"""Pydantic v2 schemas for Corporate Account Notes.

Platform admins annotate corporate accounts with typed, freeform notes.
Notes may be pinned (surfaced first) and flagged as internal (hidden from
account members).

Public surface
--------------
NoteCreate        — request body for creating a note.
NoteUpdate        — request body for editing a note (all fields optional).
NoteResponse      — full note record returned by the API.
NoteListResponse  — paginated list of notes.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.corporate_account_note import NoteType


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class NoteCreate(BaseModel):
    """Request body for creating a new corporate account note.

    Attributes:
        note_type:   Category label (default: general).
        content:     Note body text (minimum 10 characters).
        is_pinned:   Whether to pin the note at the top of the list.
        is_internal: Whether to hide the note from account members.
    """

    note_type: NoteType = NoteType.general
    content: str = Field(..., min_length=10, description="Note body text (min 10 chars)")
    is_pinned: bool = False
    is_internal: bool = True

    @field_validator("content")
    @classmethod
    def strip_content(cls, v: str) -> str:
        return v.strip()


class NoteUpdate(BaseModel):
    """Request body for updating an existing note.

    All fields are optional; only supplied fields are written.

    Attributes:
        note_type:   Updated category label.
        content:     Updated body text (minimum 10 characters if supplied).
        is_pinned:   Updated pin flag.
        is_internal: Updated internal flag.
    """

    note_type: Optional[NoteType] = None
    content: Optional[str] = Field(None, min_length=10)
    is_pinned: Optional[bool] = None
    is_internal: Optional[bool] = None

    @field_validator("content")
    @classmethod
    def strip_content(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v is not None else v


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class NoteResponse(BaseModel):
    """Full note record returned by the API.

    Attributes:
        id:          Primary key.
        account_id:  Corporate account the note belongs to.
        author_id:   User who created the note (null if author was deleted).
        note_type:   Category label.
        content:     Note body text.
        is_pinned:   Whether the note is pinned.
        is_internal: Whether the note is hidden from account members.
        created_at:  When the note was created.
        updated_at:  When the note was last edited.
    """

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    author_id: Optional[int]
    note_type: NoteType
    content: str
    is_pinned: bool
    is_internal: bool
    created_at: datetime
    updated_at: datetime


class NoteListResponse(BaseModel):
    """Paginated list of corporate account notes.

    Attributes:
        notes: List of note records (pinned first, then newest-first).
        total: Total number of records in the result set.
    """

    notes: List[NoteResponse]
    total: int
