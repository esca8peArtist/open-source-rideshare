"""Tests for the Corporate Account Contacts feature.

Service tests (async, mocked DB):
  1.  create_contact — success
  2.  create_contact — email normalised to lowercase
  3.  create_contact — duplicate email on same account → 409
  4.  create_contact — is_primary=True clears existing primary
  5.  get_contact — success
  6.  get_contact — wrong account_id → 404
  7.  get_contact — not found → 404
  8.  list_contacts — returns active contacts by default
  9.  list_contacts — active_only=False returns all
  10. list_contacts — filters by role
  11. list_contacts — empty list
  12. update_contact — partial update (name only)
  13. update_contact — promoting to primary clears old primary
  14. update_contact — duplicate email → 409
  15. update_contact — not found → 404
  16. deactivate_contact — sets is_active=False
  17. deactivate_contact — not found → 404
  18. delete_contact — removes row
  19. delete_contact — not found → 404
  20. get_primary_contact — returns is_primary contact
  21. get_primary_contact — returns None when none set

Schema tests (sync):
  22. ContactCreateRequest — valid
  23. ContactCreateRequest — defaults (role=other, is_primary=False)
  24. ContactUpdateRequest — all None is valid (partial update)
  25. ContactResponse — from_attributes

API layer tests (services patched):
  26. GET  /corporate/accounts/me/contacts — 200
  27. GET  /corporate/accounts/me/contacts/{id} — 200
  28. POST /corporate/accounts/me/contacts — 201
  29. PUT  /corporate/accounts/me/contacts/{id} — 200
  30. POST /corporate/accounts/me/contacts/{id}/deactivate — 200
  31. DELETE /corporate/accounts/me/contacts/{id} — 204
  32. GET /admin/corporate/accounts/{id}/contacts — 200
  33. GET /admin/corporate/accounts/{id}/contacts/primary — 200 (returns contact)
  34. GET /admin/corporate/accounts/{id}/contacts/primary — 200 (returns null)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate_account_contact import ContactRole, CorporateAccountContact
from app.schemas.corporate_account_contact import (
    ContactCreateRequest,
    ContactDeactivateResponse,
    ContactListResponse,
    ContactResponse,
    ContactUpdateRequest,
)
from app.services.corporate_account_contact import (
    create_contact,
    deactivate_contact,
    delete_contact,
    get_contact,
    get_primary_contact,
    list_contacts,
    update_contact,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
_ACCOUNT_ID = 1
_CONTACT_ID = 42


def _make_contact(
    id: int = _CONTACT_ID,
    account_id: int = _ACCOUNT_ID,
    name: str = "Alice Smith",
    email: str = "alice@example.com",
    phone: str | None = "+1-555-0100",
    title: str | None = "Travel Manager",
    contact_role: ContactRole = ContactRole.travel_coordinator,
    notes: str | None = None,
    is_primary: bool = False,
    is_active: bool = True,
    added_by_id: int = 10,
) -> CorporateAccountContact:
    contact = CorporateAccountContact(
        id=id,
        account_id=account_id,
        name=name,
        email=email,
        phone=phone,
        title=title,
        contact_role=contact_role,
        notes=notes,
        is_primary=is_primary,
        is_active=is_active,
        added_by_id=added_by_id,
        created_at=_NOW,
        updated_at=_NOW,
    )
    return contact


def _mock_db_with_contact(
    contact: CorporateAccountContact | None,
) -> AsyncMock:
    """Build a mock DB that returns *contact* from scalar_one_or_none."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = contact
    db.execute.return_value = result
    return db


def _mock_db_with_contacts(contacts: list[CorporateAccountContact]) -> AsyncMock:
    """Build a mock DB that returns *contacts* from scalars().all()."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = contacts
    # Also handle scalar_one_or_none for duplicate checks (no duplicates)
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# Service: create_contact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_contact_success():
    """create_contact returns a new CorporateAccountContact."""
    # DB returns None for both the duplicate check and the primary check
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    contact = await create_contact(
        db,
        account_id=_ACCOUNT_ID,
        name="Bob Jones",
        email="bob@example.com",
        phone=None,
        title=None,
        contact_role=ContactRole.hr,
        notes=None,
        is_primary=False,
        added_by_id=10,
    )

    assert contact.account_id == _ACCOUNT_ID
    assert contact.email == "bob@example.com"
    assert contact.contact_role == ContactRole.hr
    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_create_contact_normalises_email():
    """create_contact lowercases the email before storage."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    contact = await create_contact(
        db,
        account_id=_ACCOUNT_ID,
        name="Carol White",
        email="Carol.White@Example.COM",
        phone=None,
        title=None,
        contact_role=ContactRole.other,
        notes=None,
        is_primary=False,
        added_by_id=10,
    )

    assert contact.email == "carol.white@example.com"


@pytest.mark.asyncio
async def test_create_contact_duplicate_email_raises_409():
    """create_contact raises 409 when the email already exists on the account."""
    existing = _make_contact(email="alice@example.com")
    db = _mock_db_with_contact(existing)

    with pytest.raises(HTTPException) as exc_info:
        await create_contact(
            db,
            account_id=_ACCOUNT_ID,
            name="Alice Duplicate",
            email="Alice@Example.com",  # normalises to same email
            phone=None,
            title=None,
            contact_role=ContactRole.other,
            notes=None,
            is_primary=False,
            added_by_id=10,
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_create_contact_is_primary_clears_existing():
    """create_contact with is_primary=True demotes the existing primary."""
    existing_primary = _make_contact(id=1, is_primary=True)

    call_count = 0

    async def side_effect(query):
        nonlocal call_count
        result = MagicMock()
        if call_count == 0:
            # duplicate-email check — no match
            result.scalar_one_or_none.return_value = None
        else:
            # clear-primary check — return existing primary
            result.scalar_one_or_none.return_value = existing_primary
        call_count += 1
        return result

    db = AsyncMock()
    db.execute.side_effect = side_effect

    await create_contact(
        db,
        account_id=_ACCOUNT_ID,
        name="New Primary",
        email="new.primary@example.com",
        phone=None,
        title=None,
        contact_role=ContactRole.primary,
        notes=None,
        is_primary=True,
        added_by_id=10,
    )

    assert existing_primary.is_primary is False


# ---------------------------------------------------------------------------
# Service: get_contact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_contact_success():
    """get_contact returns the contact when it exists."""
    contact = _make_contact()
    db = _mock_db_with_contact(contact)
    result = await get_contact(db, account_id=_ACCOUNT_ID, contact_id=_CONTACT_ID)
    assert result is contact


@pytest.mark.asyncio
async def test_get_contact_wrong_account_raises_404():
    """get_contact raises 404 when the contact belongs to a different account."""
    db = _mock_db_with_contact(None)  # query returns nothing (account_id mismatch)
    with pytest.raises(HTTPException) as exc_info:
        await get_contact(db, account_id=999, contact_id=_CONTACT_ID)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_contact_not_found_raises_404():
    """get_contact raises 404 when the contact id does not exist."""
    db = _mock_db_with_contact(None)
    with pytest.raises(HTTPException) as exc_info:
        await get_contact(db, account_id=_ACCOUNT_ID, contact_id=99999)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: list_contacts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_contacts_returns_active_by_default():
    """list_contacts returns active contacts."""
    contacts = [_make_contact(id=1), _make_contact(id=2)]
    db = _mock_db_with_contacts(contacts)
    result = await list_contacts(db, account_id=_ACCOUNT_ID)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_contacts_active_only_false_returns_all():
    """list_contacts with active_only=False includes inactive contacts."""
    contacts = [_make_contact(is_active=False)]
    db = _mock_db_with_contacts(contacts)
    result = await list_contacts(db, account_id=_ACCOUNT_ID, active_only=False)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_contacts_filters_by_role():
    """list_contacts filters by the given role."""
    hr_contact = _make_contact(contact_role=ContactRole.hr)
    db = _mock_db_with_contacts([hr_contact])
    result = await list_contacts(
        db, account_id=_ACCOUNT_ID, role=ContactRole.hr
    )
    assert all(c.contact_role == ContactRole.hr for c in result)


@pytest.mark.asyncio
async def test_list_contacts_empty():
    """list_contacts returns an empty list when no contacts exist."""
    db = _mock_db_with_contacts([])
    result = await list_contacts(db, account_id=_ACCOUNT_ID)
    assert result == []


# ---------------------------------------------------------------------------
# Service: update_contact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_contact_partial_name_only():
    """update_contact updates only the name field."""
    contact = _make_contact(name="Old Name")
    db = _mock_db_with_contact(contact)

    updated = await update_contact(
        db, account_id=_ACCOUNT_ID, contact_id=_CONTACT_ID, name="New Name"
    )
    assert updated.name == "New Name"
    assert updated.email == contact.email  # unchanged


@pytest.mark.asyncio
async def test_update_contact_promote_to_primary_clears_old():
    """update_contact with is_primary=True demotes the existing primary."""
    target = _make_contact(id=_CONTACT_ID, is_primary=False)
    existing_primary = _make_contact(id=1, is_primary=True)

    call_count = 0

    async def side_effect(query):
        nonlocal call_count
        result = MagicMock()
        if call_count == 0:
            # _get_contact_or_404
            result.scalar_one_or_none.return_value = target
        else:
            # _clear_existing_primary
            result.scalar_one_or_none.return_value = existing_primary
        call_count += 1
        return result

    db = AsyncMock()
    db.execute.side_effect = side_effect

    await update_contact(
        db,
        account_id=_ACCOUNT_ID,
        contact_id=_CONTACT_ID,
        is_primary=True,
    )
    assert existing_primary.is_primary is False


@pytest.mark.asyncio
async def test_update_contact_duplicate_email_raises_409():
    """update_contact raises 409 when the new email conflicts with another contact."""
    target = _make_contact(email="target@example.com")
    conflicting = _make_contact(id=99, email="taken@example.com")

    call_count = 0

    async def side_effect(query):
        nonlocal call_count
        result = MagicMock()
        if call_count == 0:
            # _get_contact_or_404 returns the target
            result.scalar_one_or_none.return_value = target
        else:
            # duplicate email check — conflict found
            result.scalar_one_or_none.return_value = conflicting
        call_count += 1
        return result

    db = AsyncMock()
    db.execute.side_effect = side_effect

    with pytest.raises(HTTPException) as exc_info:
        await update_contact(
            db,
            account_id=_ACCOUNT_ID,
            contact_id=_CONTACT_ID,
            email="taken@example.com",
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_update_contact_not_found_raises_404():
    """update_contact raises 404 when the contact does not exist."""
    db = _mock_db_with_contact(None)
    with pytest.raises(HTTPException) as exc_info:
        await update_contact(
            db,
            account_id=_ACCOUNT_ID,
            contact_id=99999,
            name="Ghost",
        )
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: deactivate_contact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_contact_sets_inactive():
    """deactivate_contact sets is_active=False."""
    contact = _make_contact(is_active=True)
    db = _mock_db_with_contact(contact)
    result = await deactivate_contact(db, account_id=_ACCOUNT_ID, contact_id=_CONTACT_ID)
    assert result.is_active is False


@pytest.mark.asyncio
async def test_deactivate_contact_not_found_raises_404():
    """deactivate_contact raises 404 when the contact does not exist."""
    db = _mock_db_with_contact(None)
    with pytest.raises(HTTPException) as exc_info:
        await deactivate_contact(db, account_id=_ACCOUNT_ID, contact_id=99999)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: delete_contact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_contact_removes_row():
    """delete_contact calls db.delete on the contact."""
    contact = _make_contact()
    db = _mock_db_with_contact(contact)
    await delete_contact(db, account_id=_ACCOUNT_ID, contact_id=_CONTACT_ID)
    db.delete.assert_called_once_with(contact)
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_delete_contact_not_found_raises_404():
    """delete_contact raises 404 when the contact does not exist."""
    db = _mock_db_with_contact(None)
    with pytest.raises(HTTPException) as exc_info:
        await delete_contact(db, account_id=_ACCOUNT_ID, contact_id=99999)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: get_primary_contact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_primary_contact_returns_primary():
    """get_primary_contact returns the is_primary contact."""
    primary = _make_contact(is_primary=True)
    db = _mock_db_with_contact(primary)
    result = await get_primary_contact(db, account_id=_ACCOUNT_ID)
    assert result is primary


@pytest.mark.asyncio
async def test_get_primary_contact_none_when_not_set():
    """get_primary_contact returns None when no primary is set."""
    db = _mock_db_with_contact(None)
    result = await get_primary_contact(db, account_id=_ACCOUNT_ID)
    assert result is None


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_contact_create_request_valid():
    req = ContactCreateRequest(name="Dave Green", email="dave@corp.com")
    assert req.name == "Dave Green"
    assert req.email == "dave@corp.com"
    assert req.contact_role == ContactRole.other
    assert req.is_primary is False


def test_contact_create_request_defaults():
    """Default role is 'other' and is_primary defaults to False."""
    req = ContactCreateRequest(name="Eve Blue", email="eve@corp.com")
    assert req.contact_role == ContactRole.other
    assert req.is_primary is False


def test_contact_update_request_all_none_valid():
    """ContactUpdateRequest accepts all None fields (partial update intent)."""
    req = ContactUpdateRequest()
    assert req.name is None
    assert req.email is None
    assert req.contact_role is None
    assert req.is_primary is None


def test_contact_response_from_attributes():
    """ContactResponse can be built from a model instance."""
    contact = _make_contact()
    resp = ContactResponse.model_validate(contact)
    assert resp.id == contact.id
    assert resp.email == contact.email
    assert resp.contact_role == contact.contact_role


# ---------------------------------------------------------------------------
# API layer (services patched)
# ---------------------------------------------------------------------------

_BASE = "/api/v1/corporate/accounts/me/contacts"
_ADMIN_BASE = "/api/v1/admin/corporate/accounts"

_DUMMY_CONTACT = _make_contact()
_DUMMY_CONTACT_DICT = {
    "id": _DUMMY_CONTACT.id,
    "account_id": _DUMMY_CONTACT.account_id,
    "name": _DUMMY_CONTACT.name,
    "email": _DUMMY_CONTACT.email,
    "phone": _DUMMY_CONTACT.phone,
    "title": _DUMMY_CONTACT.title,
    "contact_role": _DUMMY_CONTACT.contact_role,
    "notes": _DUMMY_CONTACT.notes,
    "is_primary": _DUMMY_CONTACT.is_primary,
    "is_active": _DUMMY_CONTACT.is_active,
    "added_by_id": _DUMMY_CONTACT.added_by_id,
    "created_at": _DUMMY_CONTACT.created_at,
    "updated_at": _DUMMY_CONTACT.updated_at,
}


def _make_app_client():
    """Build a TestClient with auth + DB deps overridden."""
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = 10

    async def override_user():
        return mock_user

    async def override_admin():
        return mock_user

    async def override_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[require_admin] = override_admin
    app.dependency_overrides[get_db] = override_db
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _clear_dep_overrides():
    yield
    from app.main import app
    app.dependency_overrides.clear()


@patch(
    "app.api.v1.corporate_account_contacts._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_account_contacts.list_contacts",
    new_callable=AsyncMock,
    return_value=[_DUMMY_CONTACT],
)
def test_api_list_my_contacts(mock_list, mock_resolve):
    client = _make_app_client()
    resp = client.get(_BASE)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["total"] == 1


@patch(
    "app.api.v1.corporate_account_contacts._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_account_contacts.get_contact",
    new_callable=AsyncMock,
    return_value=_DUMMY_CONTACT,
)
def test_api_get_my_contact(mock_get, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/{_CONTACT_ID}")
    assert resp.status_code == 200
    assert resp.json()["id"] == _CONTACT_ID


@patch(
    "app.api.v1.corporate_account_contacts._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_account_contacts.create_contact",
    new_callable=AsyncMock,
    return_value=_DUMMY_CONTACT,
)
def test_api_create_my_contact(mock_create, mock_resolve):
    client = _make_app_client()
    resp = client.post(
        _BASE,
        json={
            "name": "Alice Smith",
            "email": "alice@example.com",
            "contact_role": "travel_coordinator",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "alice@example.com"


@patch(
    "app.api.v1.corporate_account_contacts._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_account_contacts.update_contact",
    new_callable=AsyncMock,
    return_value=_DUMMY_CONTACT,
)
def test_api_update_my_contact(mock_update, mock_resolve):
    client = _make_app_client()
    resp = client.put(
        f"{_BASE}/{_CONTACT_ID}",
        json={"name": "Alice Updated"},
    )
    assert resp.status_code == 200


@patch(
    "app.api.v1.corporate_account_contacts._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_account_contacts.deactivate_contact",
    new_callable=AsyncMock,
    return_value=_make_contact(is_active=False),
)
def test_api_deactivate_my_contact(mock_deactivate, mock_resolve):
    client = _make_app_client()
    resp = client.post(f"{_BASE}/{_CONTACT_ID}/deactivate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_active"] is False
    assert "message" in data


@patch(
    "app.api.v1.corporate_account_contacts._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_account_contacts.delete_contact",
    new_callable=AsyncMock,
    return_value=None,
)
def test_api_delete_my_contact(mock_delete, mock_resolve):
    client = _make_app_client()
    resp = client.delete(f"{_BASE}/{_CONTACT_ID}")
    assert resp.status_code == 204


@patch(
    "app.api.v1.corporate_account_contacts.list_contacts",
    new_callable=AsyncMock,
    return_value=[_DUMMY_CONTACT],
)
def test_api_platform_admin_list_contacts(mock_list):
    client = _make_app_client()
    resp = client.get(f"{_ADMIN_BASE}/{_ACCOUNT_ID}/contacts")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["total"] == 1


@patch(
    "app.api.v1.corporate_account_contacts.get_primary_contact",
    new_callable=AsyncMock,
    return_value=_make_contact(is_primary=True),
)
def test_api_platform_admin_get_primary_contact(mock_primary):
    client = _make_app_client()
    resp = client.get(f"{_ADMIN_BASE}/{_ACCOUNT_ID}/contacts/primary")
    assert resp.status_code == 200
    assert resp.json()["is_primary"] is True


@patch(
    "app.api.v1.corporate_account_contacts.get_primary_contact",
    new_callable=AsyncMock,
    return_value=None,
)
def test_api_platform_admin_get_primary_contact_none(mock_primary):
    """Returns null JSON body when no primary contact is set."""
    client = _make_app_client()
    resp = client.get(f"{_ADMIN_BASE}/{_ACCOUNT_ID}/contacts/primary")
    assert resp.status_code == 200
    assert resp.json() is None
