"""Service layer for Corporate Account Notes.

Platform admins annotate corporate accounts with CRM-style freeform notes.
Notes carry a type label, a pin flag (pinned notes sort first), and an
internal flag that controls member visibility.

Service functions are async and require a SQLAlchemy ``AsyncSession``.

Public surface
--------------
create_note(db, account_id, author_id, payload)        -> NoteResponse
get_note(db, account_id, note_id)                      -> NoteResponse
list_notes(db, account_id, *, note_type, pinned_only,
           include_internal, skip, limit)               -> list[NoteResponse]
update_note(db, account_id, note_id, payload)          -> NoteResponse
delete_note(db, account_id, note_id)                   -> None
toggle_pin(db, account_id, note_id)                    -> NoteResponse
list_notes_member(db, account_id, *, skip, limit)      -> list[NoteResponse]
"""

from __future__ import annotations

from typing import Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_account_note import CorporateAccountNote, NoteType
from app.schemas.corporate_account_note import (
    NoteCreate,
    NoteListResponse,
    NoteResponse,
    NoteUpdate,
)


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _get_or_404(
    db: AsyncSession, account_id: int, note_id: int
) -> CorporateAccountNote:
    """Fetch a note by primary key, 404-ing when it belongs to another account."""
    result = await db.execute(
        select(CorporateAccountNote).where(
            CorporateAccountNote.id == note_id,
            CorporateAccountNote.account_id == account_id,
        )
    )
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note {note_id} not found for this account.",
        )
    return note


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def create_note(
    db: AsyncSession,
    account_id: int,
    author_id: Optional[int],
    payload: NoteCreate,
) -> NoteResponse:
    """Create a new note on a corporate account.

    Args:
        db:         Database session.
        account_id: Target corporate account.
        author_id:  User ID of the platform admin creating the note.
        payload:    Validated NoteCreate schema.

    Returns:
        NoteResponse with the persisted note.
    """
    note = CorporateAccountNote(
        account_id=account_id,
        author_id=author_id,
        note_type=payload.note_type,
        content=payload.content,
        is_pinned=payload.is_pinned,
        is_internal=payload.is_internal,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return NoteResponse.model_validate(note)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def get_note(
    db: AsyncSession,
    account_id: int,
    note_id: int,
) -> NoteResponse:
    """Fetch a single note by ID.

    Raises HTTP 404 when the note does not exist or belongs to another account.
    """
    note = await _get_or_404(db, account_id, note_id)
    return NoteResponse.model_validate(note)


async def list_notes(
    db: AsyncSession,
    account_id: int,
    *,
    note_type: Optional[NoteType] = None,
    pinned_only: bool = False,
    include_internal: bool = True,
    skip: int = 0,
    limit: int = 50,
) -> list[NoteResponse]:
    """List notes for a corporate account.

    Results are sorted: pinned notes first (newest-first within each group),
    then unpinned notes (newest-first).

    Args:
        db:               Database session.
        account_id:       Corporate account to query.
        note_type:        Optional filter by note type.
        pinned_only:      When True, return only pinned notes.
        include_internal: When False, exclude is_internal=True notes
                          (used for member-facing endpoints).
        skip:             Pagination offset.
        limit:            Maximum records to return (max 200).

    Returns:
        List of NoteResponse records.
    """
    q = select(CorporateAccountNote).where(
        CorporateAccountNote.account_id == account_id
    )

    if note_type is not None:
        q = q.where(CorporateAccountNote.note_type == note_type)

    if pinned_only:
        q = q.where(CorporateAccountNote.is_pinned.is_(True))

    if not include_internal:
        q = q.where(CorporateAccountNote.is_internal.is_(False))

    # Pinned notes first, then newest-first within each group
    q = q.order_by(
        desc(CorporateAccountNote.is_pinned),
        desc(CorporateAccountNote.created_at),
    ).offset(skip).limit(min(limit, 200))

    result = await db.execute(q)
    notes = result.scalars().all()
    return [NoteResponse.model_validate(n) for n in notes]


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


async def update_note(
    db: AsyncSession,
    account_id: int,
    note_id: int,
    payload: NoteUpdate,
) -> NoteResponse:
    """Update a note's content, type, pin, or internal flag.

    Only fields present in the payload are written.  Raises HTTP 404 when the
    note does not exist or belongs to another account.
    """
    note = await _get_or_404(db, account_id, note_id)

    if payload.note_type is not None:
        note.note_type = payload.note_type
    if payload.content is not None:
        note.content = payload.content
    if payload.is_pinned is not None:
        note.is_pinned = payload.is_pinned
    if payload.is_internal is not None:
        note.is_internal = payload.is_internal

    await db.commit()
    await db.refresh(note)
    return NoteResponse.model_validate(note)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


async def delete_note(
    db: AsyncSession,
    account_id: int,
    note_id: int,
) -> None:
    """Hard-delete a note.

    Raises HTTP 404 when the note does not exist or belongs to another account.
    """
    note = await _get_or_404(db, account_id, note_id)
    await db.delete(note)
    await db.commit()


# ---------------------------------------------------------------------------
# Pin toggle
# ---------------------------------------------------------------------------


async def toggle_pin(
    db: AsyncSession,
    account_id: int,
    note_id: int,
) -> NoteResponse:
    """Toggle the is_pinned flag on a note.

    If the note is currently pinned it becomes unpinned, and vice versa.
    Raises HTTP 404 when the note does not exist or belongs to another account.
    """
    note = await _get_or_404(db, account_id, note_id)
    note.is_pinned = not note.is_pinned
    await db.commit()
    await db.refresh(note)
    return NoteResponse.model_validate(note)


# ---------------------------------------------------------------------------
# Member-visible listing (non-internal notes only)
# ---------------------------------------------------------------------------


async def list_notes_member(
    db: AsyncSession,
    account_id: int,
    *,
    skip: int = 0,
    limit: int = 50,
) -> list[NoteResponse]:
    """List non-internal notes for account members.

    Excludes notes with is_internal=True.  Pinned notes appear first.
    """
    return await list_notes(
        db,
        account_id,
        include_internal=False,
        skip=skip,
        limit=limit,
    )
