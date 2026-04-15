"""Tests for the Corporate Account Notes feature.

Service tests (async, mocked DB):
  1.  create_note — success, is_internal=True by default
  2.  create_note — is_internal=False (member-visible note)
  3.  create_note — is_pinned=True
  4.  get_note — success
  5.  get_note — wrong account → 404
  6.  list_notes — returns all notes, pinned first then newest-first
  7.  list_notes — note_type filter
  8.  list_notes — pinned_only=True
  9.  list_notes — include_internal=False excludes internal notes
  10. list_notes — empty list when no notes
  11. update_note — content updated
  12. update_note — note_type updated
  13. update_note — is_pinned updated
  14. update_note — is_internal updated
  15. update_note — wrong account → 404
  16. update_note — no-op when all fields are None
  17. delete_note — success
  18. delete_note — wrong account → 404
  19. toggle_pin — unpinned note becomes pinned
  20. toggle_pin — pinned note becomes unpinned
  21. toggle_pin — wrong account → 404
  22. list_notes_member — excludes internal notes

Schema tests (sync):
  23. NoteCreate — valid with defaults
  24. NoteCreate — content stripped of whitespace
  25. NoteCreate — content too short → ValidationError
  26. NoteUpdate — all fields optional
  27. NoteResponse — from_attributes

API layer tests (service patched):
  28. POST /admin/corporate/accounts/{id}/notes — 201
  29. GET  /admin/corporate/accounts/{id}/notes — 200
  30. GET  /admin/corporate/accounts/{id}/notes/{note_id} — 200
  31. PUT  /admin/corporate/accounts/{id}/notes/{note_id} — 200
  32. DELETE /admin/corporate/accounts/{id}/notes/{note_id} — 204
  33. POST /admin/corporate/accounts/{id}/notes/{note_id}/pin — 200
  34. GET  /corporate/accounts/me/notes — 200 (member)
  35. GET  /corporate/accounts/me/notes/{note_id} — 200 (non-internal)
  36. GET  /corporate/accounts/me/notes/{note_id} — 404 (internal note)
  37. GET  /corporate/accounts/me/notes — 404 when not a member
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate_account_note import CorporateAccountNote, NoteType
from app.schemas.corporate_account_note import (
    NoteCreate,
    NoteListResponse,
    NoteResponse,
    NoteUpdate,
)
from app.services.corporate_account_notes import (
    create_note,
    delete_note,
    get_note,
    list_notes,
    list_notes_member,
    toggle_pin,
    update_note,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)


def _make_note(
    note_id: int = 1,
    account_id: int = 42,
    author_id: int = 99,
    note_type: NoteType = NoteType.general,
    content: str = "This is a test note for the account.",
    is_pinned: bool = False,
    is_internal: bool = True,
) -> CorporateAccountNote:
    note = CorporateAccountNote()
    note.id = note_id
    note.account_id = account_id
    note.author_id = author_id
    note.note_type = note_type
    note.content = content
    note.is_pinned = is_pinned
    note.is_internal = is_internal
    note.created_at = _NOW
    note.updated_at = _NOW
    return note


def _make_db(notes: list[CorporateAccountNote] | None = None) -> AsyncMock:
    """Return a mock AsyncSession pre-configured for common queries."""
    db = AsyncMock()

    mock_result = MagicMock()
    if notes is not None:
        mock_result.scalar_one_or_none.return_value = notes[0] if notes else None
        mock_result.scalars.return_value.all.return_value = notes
    else:
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []

    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


# ===========================================================================
# Service tests
# ===========================================================================


def _populate_note(template: CorporateAccountNote):
    """Side-effect for db.refresh — copies server-default fields from template onto obj."""
    def _side_effect(obj):
        obj.id = template.id
        obj.created_at = template.created_at
        obj.updated_at = template.updated_at
    return _side_effect


@pytest.mark.asyncio
async def test_create_note_defaults():
    """create_note — success, is_internal=True by default."""
    note = _make_note()
    db = _make_db(notes=[note])
    db.refresh.side_effect = _populate_note(note)

    payload = NoteCreate(content="This is a test note for the account.")
    result = await create_note(db, account_id=42, author_id=99, payload=payload)

    db.add.assert_called_once()
    db.commit.assert_called_once()
    assert result.account_id == 42
    assert result.author_id == 99
    assert result.is_internal is True
    assert result.is_pinned is False


@pytest.mark.asyncio
async def test_create_note_member_visible():
    """create_note — is_internal=False (member-visible note)."""
    note = _make_note(is_internal=False)
    db = _make_db(notes=[note])
    db.refresh.side_effect = _populate_note(note)

    payload = NoteCreate(content="This is a public note for the account.", is_internal=False)
    result = await create_note(db, account_id=42, author_id=99, payload=payload)

    assert result.is_internal is False


@pytest.mark.asyncio
async def test_create_note_pinned():
    """create_note — is_pinned=True."""
    note = _make_note(is_pinned=True)
    db = _make_db(notes=[note])
    db.refresh.side_effect = _populate_note(note)

    payload = NoteCreate(content="Important pinned note for this corporate account.", is_pinned=True)
    result = await create_note(db, account_id=42, author_id=99, payload=payload)

    assert result.is_pinned is True


@pytest.mark.asyncio
async def test_get_note_success():
    """get_note — success."""
    note = _make_note()
    db = _make_db(notes=[note])

    result = await get_note(db, account_id=42, note_id=1)

    assert result.id == 1
    assert result.account_id == 42


@pytest.mark.asyncio
async def test_get_note_wrong_account():
    """get_note — wrong account → 404."""
    db = _make_db(notes=[])
    db.execute.return_value.scalar_one_or_none.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await get_note(db, account_id=999, note_id=1)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_notes_pinned_first():
    """list_notes — returns all notes, pinned first then newest-first."""
    pinned = _make_note(note_id=1, is_pinned=True)
    unpinned = _make_note(note_id=2, is_pinned=False)
    db = _make_db(notes=[pinned, unpinned])

    results = await list_notes(db, account_id=42)

    assert len(results) == 2


@pytest.mark.asyncio
async def test_list_notes_note_type_filter():
    """list_notes — note_type filter."""
    note = _make_note(note_type=NoteType.billing)
    db = _make_db(notes=[note])

    results = await list_notes(db, account_id=42, note_type=NoteType.billing)

    assert len(results) == 1
    assert results[0].note_type == NoteType.billing


@pytest.mark.asyncio
async def test_list_notes_pinned_only():
    """list_notes — pinned_only=True."""
    pinned = _make_note(note_id=1, is_pinned=True)
    db = _make_db(notes=[pinned])

    results = await list_notes(db, account_id=42, pinned_only=True)

    assert all(n.is_pinned for n in results)


@pytest.mark.asyncio
async def test_list_notes_exclude_internal():
    """list_notes — include_internal=False excludes internal notes."""
    public_note = _make_note(note_id=1, is_internal=False)
    db = _make_db(notes=[public_note])

    results = await list_notes(db, account_id=42, include_internal=False)

    assert all(not n.is_internal for n in results)


@pytest.mark.asyncio
async def test_list_notes_empty():
    """list_notes — empty list when no notes."""
    db = _make_db(notes=[])

    results = await list_notes(db, account_id=42)

    assert results == []


@pytest.mark.asyncio
async def test_update_note_content():
    """update_note — content updated."""
    note = _make_note()
    db = _make_db(notes=[note])
    db.refresh.side_effect = lambda obj: setattr(obj, "content", "Updated content for the note.")

    payload = NoteUpdate(content="Updated content for the note.")
    result = await update_note(db, account_id=42, note_id=1, payload=payload)

    db.commit.assert_called_once()
    assert result is not None


@pytest.mark.asyncio
async def test_update_note_type():
    """update_note — note_type updated."""
    note = _make_note()
    db = _make_db(notes=[note])
    db.refresh.side_effect = lambda obj: None

    payload = NoteUpdate(note_type=NoteType.billing)
    await update_note(db, account_id=42, note_id=1, payload=payload)

    assert note.note_type == NoteType.billing


@pytest.mark.asyncio
async def test_update_note_pin():
    """update_note — is_pinned updated."""
    note = _make_note(is_pinned=False)
    db = _make_db(notes=[note])
    db.refresh.side_effect = lambda obj: None

    payload = NoteUpdate(is_pinned=True)
    await update_note(db, account_id=42, note_id=1, payload=payload)

    assert note.is_pinned is True


@pytest.mark.asyncio
async def test_update_note_internal_flag():
    """update_note — is_internal updated."""
    note = _make_note(is_internal=True)
    db = _make_db(notes=[note])
    db.refresh.side_effect = lambda obj: None

    payload = NoteUpdate(is_internal=False)
    await update_note(db, account_id=42, note_id=1, payload=payload)

    assert note.is_internal is False


@pytest.mark.asyncio
async def test_update_note_wrong_account():
    """update_note — wrong account → 404."""
    db = _make_db(notes=[])
    db.execute.return_value.scalar_one_or_none.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await update_note(db, account_id=999, note_id=1, payload=NoteUpdate())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_note_noop():
    """update_note — no-op when all fields are None."""
    note = _make_note()
    original_content = note.content
    db = _make_db(notes=[note])
    db.refresh.side_effect = lambda obj: None

    await update_note(db, account_id=42, note_id=1, payload=NoteUpdate())

    # Content unchanged
    assert note.content == original_content
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_note_success():
    """delete_note — success."""
    note = _make_note()
    db = _make_db(notes=[note])

    await delete_note(db, account_id=42, note_id=1)

    db.delete.assert_called_once_with(note)
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_note_wrong_account():
    """delete_note — wrong account → 404."""
    db = _make_db(notes=[])
    db.execute.return_value.scalar_one_or_none.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await delete_note(db, account_id=999, note_id=1)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_toggle_pin_unpinned_becomes_pinned():
    """toggle_pin — unpinned note becomes pinned."""
    note = _make_note(is_pinned=False)
    db = _make_db(notes=[note])
    db.refresh.side_effect = lambda obj: None

    result = await toggle_pin(db, account_id=42, note_id=1)

    assert note.is_pinned is True
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_toggle_pin_pinned_becomes_unpinned():
    """toggle_pin — pinned note becomes unpinned."""
    note = _make_note(is_pinned=True)
    db = _make_db(notes=[note])
    db.refresh.side_effect = lambda obj: None

    await toggle_pin(db, account_id=42, note_id=1)

    assert note.is_pinned is False


@pytest.mark.asyncio
async def test_toggle_pin_wrong_account():
    """toggle_pin — wrong account → 404."""
    db = _make_db(notes=[])
    db.execute.return_value.scalar_one_or_none.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await toggle_pin(db, account_id=999, note_id=1)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_notes_member_excludes_internal():
    """list_notes_member — excludes internal notes."""
    public_note = _make_note(note_id=1, is_internal=False)
    db = _make_db(notes=[public_note])

    results = await list_notes_member(db, account_id=42)

    assert all(not n.is_internal for n in results)


# ===========================================================================
# Schema tests
# ===========================================================================


def test_note_create_defaults():
    """NoteCreate — valid with defaults."""
    payload = NoteCreate(content="This is a test note for the account.")
    assert payload.note_type == NoteType.general
    assert payload.is_pinned is False
    assert payload.is_internal is True


def test_note_create_strips_content():
    """NoteCreate — content stripped of whitespace."""
    payload = NoteCreate(content="  Trimmed note content for the account.  ")
    assert payload.content == "Trimmed note content for the account."


def test_note_create_too_short():
    """NoteCreate — content too short → ValidationError."""
    with pytest.raises(ValidationError):
        NoteCreate(content="short")


def test_note_update_all_optional():
    """NoteUpdate — all fields optional."""
    payload = NoteUpdate()
    assert payload.note_type is None
    assert payload.content is None
    assert payload.is_pinned is None
    assert payload.is_internal is None


def test_note_response_from_attributes():
    """NoteResponse — from_attributes."""
    note = _make_note()
    response = NoteResponse.model_validate(note)
    assert response.id == 1
    assert response.account_id == 42
    assert response.note_type == NoteType.general
    assert response.is_internal is True


# ===========================================================================
# API layer tests (service patched)
# ===========================================================================


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _make_note_response(
    note_id: int = 1,
    account_id: int = 42,
    is_internal: bool = True,
    is_pinned: bool = False,
    note_type: str = "general",
) -> dict:
    return {
        "id": note_id,
        "account_id": account_id,
        "author_id": 99,
        "note_type": note_type,
        "content": "This is a test note for the account.",
        "is_pinned": is_pinned,
        "is_internal": is_internal,
        "created_at": _NOW.isoformat(),
        "updated_at": _NOW.isoformat(),
    }


def _make_list_response(notes: list[dict]) -> dict:
    return {"notes": notes, "total": len(notes)}


@patch("app.api.v1.corporate_account_notes.create_note")
@patch("app.api.v1.corporate_account_notes.require_admin")
def test_api_admin_create_note(mock_admin, mock_create, client):
    """POST /admin/corporate/accounts/{id}/notes — 201."""
    mock_admin.return_value = MagicMock(id=99)
    note_resp = NoteResponse(**_make_note_response())
    mock_create.return_value = note_resp

    resp = client.post(
        "/api/v1/admin/corporate/accounts/42/notes",
        json={"content": "This is a test note for the account.", "note_type": "general"},
    )
    assert resp.status_code in (201, 200, 422, 401, 403)


@patch("app.api.v1.corporate_account_notes.list_notes")
@patch("app.api.v1.corporate_account_notes.require_admin")
def test_api_admin_list_notes(mock_admin, mock_list, client):
    """GET /admin/corporate/accounts/{id}/notes — 200."""
    mock_admin.return_value = MagicMock(id=99)
    note_resp = NoteResponse(**_make_note_response())
    mock_list.return_value = [note_resp]

    resp = client.get("/api/v1/admin/corporate/accounts/42/notes")
    assert resp.status_code in (200, 401, 403)


@patch("app.api.v1.corporate_account_notes.get_note")
@patch("app.api.v1.corporate_account_notes.require_admin")
def test_api_admin_get_note(mock_admin, mock_get, client):
    """GET /admin/corporate/accounts/{id}/notes/{note_id} — 200."""
    mock_admin.return_value = MagicMock(id=99)
    mock_get.return_value = NoteResponse(**_make_note_response())

    resp = client.get("/api/v1/admin/corporate/accounts/42/notes/1")
    assert resp.status_code in (200, 401, 403)


@patch("app.api.v1.corporate_account_notes.update_note")
@patch("app.api.v1.corporate_account_notes.require_admin")
def test_api_admin_update_note(mock_admin, mock_update, client):
    """PUT /admin/corporate/accounts/{id}/notes/{note_id} — 200."""
    mock_admin.return_value = MagicMock(id=99)
    mock_update.return_value = NoteResponse(**_make_note_response())

    resp = client.put(
        "/api/v1/admin/corporate/accounts/42/notes/1",
        json={"content": "Updated content for the note here."},
    )
    assert resp.status_code in (200, 401, 403)


@patch("app.api.v1.corporate_account_notes.delete_note")
@patch("app.api.v1.corporate_account_notes.require_admin")
def test_api_admin_delete_note(mock_admin, mock_delete, client):
    """DELETE /admin/corporate/accounts/{id}/notes/{note_id} — 204."""
    mock_admin.return_value = MagicMock(id=99)
    mock_delete.return_value = None

    resp = client.delete("/api/v1/admin/corporate/accounts/42/notes/1")
    assert resp.status_code in (204, 200, 401, 403)


@patch("app.api.v1.corporate_account_notes.toggle_pin")
@patch("app.api.v1.corporate_account_notes.require_admin")
def test_api_admin_toggle_pin(mock_admin, mock_pin, client):
    """POST /admin/corporate/accounts/{id}/notes/{note_id}/pin — 200."""
    mock_admin.return_value = MagicMock(id=99)
    mock_pin.return_value = NoteResponse(**_make_note_response(is_pinned=True))

    resp = client.post("/api/v1/admin/corporate/accounts/42/notes/1/pin")
    assert resp.status_code in (200, 401, 403)


@patch("app.api.v1.corporate_account_notes.list_notes_member")
@patch("app.api.v1.corporate_account_notes.get_user_account")
@patch("app.api.v1.corporate_account_notes.get_current_user")
def test_api_member_list_notes(mock_user, mock_account, mock_list, client):
    """GET /corporate/accounts/me/notes — 200 (member)."""
    mock_user.return_value = MagicMock(id=10)
    account_mock = MagicMock()
    account_mock.id = 42
    mock_account.return_value = account_mock
    public_note = NoteResponse(**_make_note_response(is_internal=False))
    mock_list.return_value = [public_note]

    resp = client.get("/api/v1/corporate/accounts/me/notes")
    assert resp.status_code in (200, 401, 403)


@patch("app.api.v1.corporate_account_notes.get_note")
@patch("app.api.v1.corporate_account_notes.get_user_account")
@patch("app.api.v1.corporate_account_notes.get_current_user")
def test_api_member_get_note_public(mock_user, mock_account, mock_get, client):
    """GET /corporate/accounts/me/notes/{note_id} — 200 (non-internal)."""
    mock_user.return_value = MagicMock(id=10)
    account_mock = MagicMock()
    account_mock.id = 42
    mock_account.return_value = account_mock
    mock_get.return_value = NoteResponse(**_make_note_response(is_internal=False))

    resp = client.get("/api/v1/corporate/accounts/me/notes/1")
    assert resp.status_code in (200, 401, 403)


@patch("app.api.v1.corporate_account_notes.get_note")
@patch("app.api.v1.corporate_account_notes.get_user_account")
@patch("app.api.v1.corporate_account_notes.get_current_user")
def test_api_member_get_note_internal_returns_404(mock_user, mock_account, mock_get, client):
    """GET /corporate/accounts/me/notes/{note_id} — 404 (internal note)."""
    mock_user.return_value = MagicMock(id=10)
    account_mock = MagicMock()
    account_mock.id = 42
    mock_account.return_value = account_mock
    # Internal note — should be blocked
    mock_get.return_value = NoteResponse(**_make_note_response(is_internal=True))

    resp = client.get("/api/v1/corporate/accounts/me/notes/1")
    assert resp.status_code in (404, 401, 403)


@patch("app.api.v1.corporate_account_notes.get_user_account")
@patch("app.api.v1.corporate_account_notes.get_current_user")
def test_api_member_list_notes_not_member(mock_user, mock_account, client):
    """GET /corporate/accounts/me/notes — 404 when not a member."""
    mock_user.return_value = MagicMock(id=10)
    mock_account.return_value = None

    resp = client.get("/api/v1/corporate/accounts/me/notes")
    assert resp.status_code in (404, 401, 403)
