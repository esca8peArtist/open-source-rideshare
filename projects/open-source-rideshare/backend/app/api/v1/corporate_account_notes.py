"""Corporate Account Notes endpoints.

Platform-admin endpoints (require_admin):
  POST   /admin/corporate/accounts/{account_id}/notes               — create note
  GET    /admin/corporate/accounts/{account_id}/notes               — list all notes
  GET    /admin/corporate/accounts/{account_id}/notes/{note_id}     — get note
  PUT    /admin/corporate/accounts/{account_id}/notes/{note_id}     — update note
  DELETE /admin/corporate/accounts/{account_id}/notes/{note_id}     — delete note
  POST   /admin/corporate/accounts/{account_id}/notes/{note_id}/pin — toggle pin

Member endpoints (authenticated account member):
  GET /corporate/accounts/me/notes             — list non-internal notes
  GET /corporate/accounts/me/notes/{note_id}  — get a non-internal note
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_account_note import NoteType
from app.models.user import User
from app.schemas.corporate_account_note import (
    NoteCreate,
    NoteListResponse,
    NoteResponse,
    NoteUpdate,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_account_notes import (
    create_note,
    delete_note,
    get_note,
    list_notes,
    list_notes_member,
    toggle_pin,
    update_note,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-account-notes"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_member_account(db: AsyncSession, user_id: int) -> int:
    """Return the corporate account ID for the authenticated member.

    Raises HTTP 404 when the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ===========================================================================
# Platform-admin endpoints
# ===========================================================================


@router.post(
    "/admin/corporate/accounts/{account_id}/notes",
    response_model=NoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a note on a corporate account",
)
async def admin_create_note(
    account_id: int,
    payload: NoteCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a CRM-style note on a corporate account.

    Notes are visible only to platform admins by default (``is_internal=True``).
    Set ``is_internal=False`` to allow account members to see the note.

    Platform admin only.
    """
    return await create_note(db, account_id=account_id, author_id=admin.id, payload=payload)


@router.get(
    "/admin/corporate/accounts/{account_id}/notes",
    response_model=NoteListResponse,
    summary="Admin: list notes for a corporate account",
)
async def admin_list_notes(
    account_id: int,
    note_type: NoteType | None = Query(None, description="Filter by note type"),
    pinned_only: bool = Query(False, description="Return only pinned notes"),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=200, description="Maximum notes to return"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all notes (including internal) for a corporate account.

    Results are sorted pinned-first, then newest-first within each group.

    Platform admin only.
    """
    notes = await list_notes(
        db,
        account_id,
        note_type=note_type,
        pinned_only=pinned_only,
        include_internal=True,
        skip=skip,
        limit=limit,
    )
    return NoteListResponse(notes=notes, total=len(notes))


@router.get(
    "/admin/corporate/accounts/{account_id}/notes/{note_id}",
    response_model=NoteResponse,
    summary="Admin: get a single note",
)
async def admin_get_note(
    account_id: int,
    note_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single note by ID.

    Returns HTTP 404 when the note does not exist or belongs to another account.

    Platform admin only.
    """
    return await get_note(db, account_id=account_id, note_id=note_id)


@router.put(
    "/admin/corporate/accounts/{account_id}/notes/{note_id}",
    response_model=NoteResponse,
    summary="Admin: update a note",
)
async def admin_update_note(
    account_id: int,
    note_id: int,
    payload: NoteUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a note's content, type, pin flag, or internal flag.

    All fields in the request body are optional; only supplied fields are
    written.

    Returns HTTP 404 when the note does not exist or belongs to another account.

    Platform admin only.
    """
    return await update_note(db, account_id=account_id, note_id=note_id, payload=payload)


@router.delete(
    "/admin/corporate/accounts/{account_id}/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: delete a note",
)
async def admin_delete_note(
    account_id: int,
    note_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a note.

    Returns HTTP 404 when the note does not exist or belongs to another account.

    Platform admin only.
    """
    await delete_note(db, account_id=account_id, note_id=note_id)


@router.post(
    "/admin/corporate/accounts/{account_id}/notes/{note_id}/pin",
    response_model=NoteResponse,
    summary="Admin: toggle pin on a note",
)
async def admin_toggle_pin(
    account_id: int,
    note_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Toggle the ``is_pinned`` flag on a note.

    Pinned notes sort before unpinned notes in list responses.  Calling this
    endpoint on a pinned note unpins it; calling it on an unpinned note pins
    it.

    Returns HTTP 404 when the note does not exist or belongs to another account.

    Platform admin only.
    """
    return await toggle_pin(db, account_id=account_id, note_id=note_id)


# ===========================================================================
# Member endpoints
# ===========================================================================


@router.get(
    "/corporate/accounts/me/notes",
    response_model=NoteListResponse,
    summary="List non-internal notes on your corporate account",
)
async def member_list_notes(
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=100, description="Maximum notes to return"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List notes visible to account members (``is_internal=False`` only).

    Results are sorted pinned-first, then newest-first.

    Returns an empty list when no non-internal notes exist.
    """
    account_id = await _resolve_member_account(db, user.id)
    notes = await list_notes_member(db, account_id, skip=skip, limit=limit)
    return NoteListResponse(notes=notes, total=len(notes))


@router.get(
    "/corporate/accounts/me/notes/{note_id}",
    response_model=NoteResponse,
    summary="Get a non-internal note on your corporate account",
)
async def member_get_note(
    note_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single non-internal note visible to account members.

    Returns HTTP 404 when the note does not exist, belongs to another account,
    or is marked internal.
    """
    account_id = await _resolve_member_account(db, user.id)
    note = await get_note(db, account_id=account_id, note_id=note_id)
    if note.is_internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note {note_id} not found.",
        )
    return note
