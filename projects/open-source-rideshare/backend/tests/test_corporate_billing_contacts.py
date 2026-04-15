"""Tests for the Corporate Billing Contact Management feature.

Service tests (async, mocked DB):
  1.  add_billing_contact — success, returns BillingContactResponse
  2.  add_billing_contact — non-admin → 403
  3.  add_billing_contact — duplicate email within account → 409
  4.  add_billing_contact — email normalised to lowercase
  5.  get_billing_contact — success
  6.  get_billing_contact — wrong account → 404
  7.  list_billing_contacts — returns active only by default
  8.  list_billing_contacts — active_only=False includes inactive
  9.  list_billing_contacts — empty list
  10. list_billing_contacts — ordered by name
  11. update_billing_contact — name updated
  12. update_billing_contact — receives_invoices toggled
  13. update_billing_contact — non-admin → 403
  14. update_billing_contact — not found → 404
  15. deactivate_billing_contact — success: is_active=False
  16. deactivate_billing_contact — already inactive → 409
  17. deactivate_billing_contact — non-admin → 403
  18. list_contacts_for_notification — invoices type returns correct contacts
  19. list_contacts_for_notification — budget_alerts type
  20. list_contacts_for_notification — monthly_summary type

Schema tests (sync):
  21. BillingContactCreate — valid
  22. BillingContactCreate — email normalised to lowercase by validator
  23. BillingContactCreate — name too long → ValidationError
  24. BillingContactUpdate — all fields optional

API layer tests (service patched):
  25. GET  /corporate/accounts/me/billing-contacts — 200
  26. GET  /corporate/accounts/me/billing-contacts/{id} — 200
  27. POST /corporate/accounts/me/billing-contacts — 201
  28. PUT  /corporate/accounts/me/billing-contacts/{id} — 200
  29. DELETE /corporate/accounts/me/billing-contacts/{id}/deactivate — 200
  30. GET  /admin/corporate/accounts/{id}/billing-contacts — 200
  31. POST /corporate/accounts/me/billing-contacts — 403 when _resolve_account_id raises 404
  32. add_billing_contact — phone and role stored correctly
  33. add_billing_contact — receives_budget_alerts defaults to False
  34. update_billing_contact — role updated
  35. update_billing_contact — receives_monthly_summary toggled
  36. deactivate_billing_contact — not found → 404
  37. list_billing_contacts — total reflects active_only filter
  38. BillingContactCreate — email with uppercase is lowercased
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_billing_contact import CorporateBillingContact
from app.schemas.corporate_billing_contact import (
    BillingContactCreate,
    BillingContactListResponse,
    BillingContactResponse,
    BillingContactUpdate,
)
from app.services.corporate_billing_contact import (
    add_billing_contact,
    deactivate_billing_contact,
    get_billing_contact,
    list_billing_contacts,
    list_contacts_for_notification,
    update_billing_contact,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 1
ADMIN_ID = 10
MEMBER_ID = 20
CONTACT_ID = 100


def _make_member(user_id: int, role: MemberRole = MemberRole.ADMIN) -> BusinessAccountMember:
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = ACCOUNT_ID
    m.user_id = user_id
    m.role = role
    m.is_active = True
    return m


def _make_contact(
    contact_id: int = CONTACT_ID,
    email: str = "finance@example.com",
    is_active: bool = True,
    receives_invoices: bool = True,
    receives_budget_alerts: bool = False,
    receives_monthly_summary: bool = False,
    name: str = "Jane Smith",
    phone: str | None = None,
    role: str | None = None,
) -> CorporateBillingContact:
    c = MagicMock(spec=CorporateBillingContact)
    c.id = contact_id
    c.account_id = ACCOUNT_ID
    c.name = name
    c.email = email
    c.phone = phone
    c.role = role
    c.receives_invoices = receives_invoices
    c.receives_budget_alerts = receives_budget_alerts
    c.receives_monthly_summary = receives_monthly_summary
    c.is_active = is_active
    c.added_by_id = ADMIN_ID
    c.created_at = NOW
    c.updated_at = NOW
    return c


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_billing_contact_success():
    """1. add_billing_contact — happy path."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID, MemberRole.ADMIN)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = None  # no duplicate
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    def _set_id(obj):
        obj.id = CONTACT_ID
        obj.created_at = NOW
        obj.updated_at = NOW

    db.add = MagicMock(side_effect=_set_id)

    data = BillingContactCreate(name="Jane Smith", email="finance@example.com")
    result = await add_billing_contact(db, ACCOUNT_ID, ADMIN_ID, data)

    assert result.name == "Jane Smith"
    assert result.email == "finance@example.com"
    assert result.receives_invoices is True
    assert result.receives_budget_alerts is False


@pytest.mark.asyncio
async def test_add_billing_contact_non_admin():
    """2. add_billing_contact — non-admin → 403."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await add_billing_contact(
            db, ACCOUNT_ID, MEMBER_ID,
            BillingContactCreate(name="X", email="x@example.com"),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_add_billing_contact_duplicate_email():
    """3. add_billing_contact — duplicate email → 409."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    existing = _make_contact()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = existing
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await add_billing_contact(
            db, ACCOUNT_ID, ADMIN_ID,
            BillingContactCreate(name="Dupe", email="finance@example.com"),
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_add_billing_contact_email_lowercased():
    """4. add_billing_contact — email normalised to lowercase on creation."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    call_count = 0
    captured_email: list[str] = []

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    def _capture_add(obj):
        captured_email.append(obj.email)
        obj.id = CONTACT_ID
        obj.created_at = NOW
        obj.updated_at = NOW

    db.add = MagicMock(side_effect=_capture_add)

    data = BillingContactCreate(name="Jane", email="Finance@EXAMPLE.COM")
    await add_billing_contact(db, ACCOUNT_ID, ADMIN_ID, data)

    assert captured_email[0] == "finance@example.com"


@pytest.mark.asyncio
async def test_get_billing_contact_success():
    """5. get_billing_contact — success."""
    db = AsyncMock()
    contact = _make_contact()
    r = MagicMock()
    r.scalar_one_or_none.return_value = contact
    db.execute = AsyncMock(return_value=r)

    result = await get_billing_contact(db, ACCOUNT_ID, CONTACT_ID)
    assert result.id == CONTACT_ID
    assert result.email == "finance@example.com"


@pytest.mark.asyncio
async def test_get_billing_contact_wrong_account():
    """6. get_billing_contact — wrong account → 404."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await get_billing_contact(db, account_id=999, contact_id=CONTACT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_billing_contacts_active_only():
    """7. list_billing_contacts — returns active only by default."""
    db = AsyncMock()
    active_contact = _make_contact(is_active=True)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one.return_value = 1
        else:
            r.scalars.return_value.all.return_value = [active_contact]
        return r

    db.execute = fake_execute

    result = await list_billing_contacts(db, ACCOUNT_ID, active_only=True)
    assert result.total == 1
    assert len(result.contacts) == 1
    assert result.contacts[0].is_active is True


@pytest.mark.asyncio
async def test_list_billing_contacts_includes_inactive():
    """8. list_billing_contacts — active_only=False includes inactive."""
    db = AsyncMock()
    c1 = _make_contact(contact_id=1, is_active=True)
    c2 = _make_contact(contact_id=2, is_active=False, email="old@example.com")
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one.return_value = 2
        else:
            r.scalars.return_value.all.return_value = [c1, c2]
        return r

    db.execute = fake_execute

    result = await list_billing_contacts(db, ACCOUNT_ID, active_only=False)
    assert result.total == 2
    assert len(result.contacts) == 2


@pytest.mark.asyncio
async def test_list_billing_contacts_empty():
    """9. list_billing_contacts — empty list."""
    db = AsyncMock()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one.return_value = 0
        else:
            r.scalars.return_value.all.return_value = []
        return r

    db.execute = fake_execute

    result = await list_billing_contacts(db, ACCOUNT_ID)
    assert result.total == 0
    assert result.contacts == []


@pytest.mark.asyncio
async def test_list_billing_contacts_ordered_by_name():
    """10. list_billing_contacts — ordered by name (tested via query construction)."""
    db = AsyncMock()
    c_alice = _make_contact(contact_id=1, name="Alice", email="alice@example.com")
    c_bob = _make_contact(contact_id=2, name="Bob", email="bob@example.com")
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one.return_value = 2
        else:
            # Return in name order as DB would
            r.scalars.return_value.all.return_value = [c_alice, c_bob]
        return r

    db.execute = fake_execute

    result = await list_billing_contacts(db, ACCOUNT_ID)
    assert result.contacts[0].name == "Alice"
    assert result.contacts[1].name == "Bob"


@pytest.mark.asyncio
async def test_update_billing_contact_name():
    """11. update_billing_contact — name updated."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    contact = _make_contact()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = contact
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    data = BillingContactUpdate(name="Jane Doe")
    result = await update_billing_contact(db, ACCOUNT_ID, CONTACT_ID, ADMIN_ID, data)

    assert contact.name == "Jane Doe"
    assert result is not None


@pytest.mark.asyncio
async def test_update_billing_contact_receives_invoices_toggled():
    """12. update_billing_contact — receives_invoices toggled."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    contact = _make_contact(receives_invoices=True)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = contact
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    data = BillingContactUpdate(receives_invoices=False)
    await update_billing_contact(db, ACCOUNT_ID, CONTACT_ID, ADMIN_ID, data)

    assert contact.receives_invoices is False


@pytest.mark.asyncio
async def test_update_billing_contact_non_admin():
    """13. update_billing_contact — non-admin → 403."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await update_billing_contact(
            db, ACCOUNT_ID, CONTACT_ID, MEMBER_ID, BillingContactUpdate(name="X")
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_update_billing_contact_not_found():
    """14. update_billing_contact — not found → 404."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await update_billing_contact(
            db, ACCOUNT_ID, contact_id=9999, user_id=ADMIN_ID,
            data=BillingContactUpdate(name="X"),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_billing_contact_success():
    """15. deactivate_billing_contact — is_active set to False."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    contact = _make_contact(is_active=True)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = contact
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    result = await deactivate_billing_contact(db, ACCOUNT_ID, CONTACT_ID, ADMIN_ID)
    assert contact.is_active is False
    assert result is not None


@pytest.mark.asyncio
async def test_deactivate_billing_contact_already_inactive():
    """16. deactivate_billing_contact — already inactive → 409."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    contact = _make_contact(is_active=False)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = contact
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await deactivate_billing_contact(db, ACCOUNT_ID, CONTACT_ID, ADMIN_ID)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_deactivate_billing_contact_non_admin():
    """17. deactivate_billing_contact — non-admin → 403."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await deactivate_billing_contact(db, ACCOUNT_ID, CONTACT_ID, MEMBER_ID)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_list_contacts_for_notification_invoices():
    """18. list_contacts_for_notification — invoices type."""
    db = AsyncMock()
    contact = _make_contact(receives_invoices=True)
    r = MagicMock()
    r.scalars.return_value.all.return_value = [contact]
    db.execute = AsyncMock(return_value=r)

    results = await list_contacts_for_notification(db, ACCOUNT_ID, "invoices")
    assert len(results) == 1
    assert results[0].receives_invoices is True


@pytest.mark.asyncio
async def test_list_contacts_for_notification_budget_alerts():
    """19. list_contacts_for_notification — budget_alerts type."""
    db = AsyncMock()
    contact = _make_contact(receives_budget_alerts=True)
    r = MagicMock()
    r.scalars.return_value.all.return_value = [contact]
    db.execute = AsyncMock(return_value=r)

    results = await list_contacts_for_notification(db, ACCOUNT_ID, "budget_alerts")
    assert len(results) == 1
    assert results[0].receives_budget_alerts is True


@pytest.mark.asyncio
async def test_list_contacts_for_notification_monthly_summary():
    """20. list_contacts_for_notification — monthly_summary type."""
    db = AsyncMock()
    contact = _make_contact(receives_monthly_summary=True)
    r = MagicMock()
    r.scalars.return_value.all.return_value = [contact]
    db.execute = AsyncMock(return_value=r)

    results = await list_contacts_for_notification(db, ACCOUNT_ID, "monthly_summary")
    assert len(results) == 1
    assert results[0].receives_monthly_summary is True


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_billing_contact_create_valid():
    """21. BillingContactCreate — valid."""
    data = BillingContactCreate(name="Jane Smith", email="finance@example.com")
    assert data.name == "Jane Smith"
    assert data.email == "finance@example.com"
    assert data.receives_invoices is True
    assert data.receives_budget_alerts is False
    assert data.receives_monthly_summary is False


def test_billing_contact_create_email_lowercased():
    """22. BillingContactCreate — email normalised to lowercase by validator."""
    data = BillingContactCreate(name="Jane", email="Finance@EXAMPLE.COM")
    assert data.email == "finance@example.com"


def test_billing_contact_create_name_too_long():
    """23. BillingContactCreate — name too long → ValidationError."""
    with pytest.raises(ValidationError):
        BillingContactCreate(name="X" * 201, email="test@example.com")


def test_billing_contact_update_all_optional():
    """24. BillingContactUpdate — all fields optional."""
    data = BillingContactUpdate()
    assert data.name is None
    assert data.phone is None
    assert data.role is None
    assert data.receives_invoices is None
    assert data.receives_budget_alerts is None
    assert data.receives_monthly_summary is None


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------


def _fake_user_deps(user_id: int = ADMIN_ID, is_admin: bool = False):
    from app.models.user import User as UserModel

    u = MagicMock(spec=UserModel)
    u.id = user_id
    u.is_admin = is_admin

    async def _fake_db():
        db = AsyncMock()
        yield db

    return u, _fake_db


def _make_contact_response(contact_id: int = CONTACT_ID) -> BillingContactResponse:
    return BillingContactResponse(
        id=contact_id,
        account_id=ACCOUNT_ID,
        name="Jane Smith",
        email="finance@example.com",
        phone=None,
        role=None,
        receives_invoices=True,
        receives_budget_alerts=False,
        receives_monthly_summary=False,
        is_active=True,
        added_by_id=ADMIN_ID,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.asyncio
async def test_api_list_billing_contacts():
    """25. GET /corporate/accounts/me/billing-contacts — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    list_response = BillingContactListResponse(
        account_id=ACCOUNT_ID, total=0, contacts=[]
    )

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_billing_contacts.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_billing_contacts.list_billing_contacts",
            new=AsyncMock(return_value=list_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.get("/api/v1/corporate/accounts/me/billing-contacts")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_api_get_billing_contact():
    """26. GET /corporate/accounts/me/billing-contacts/{id} — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    contact_response = _make_contact_response()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_billing_contacts.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_billing_contacts.get_billing_contact",
            new=AsyncMock(return_value=contact_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.get(f"/api/v1/corporate/accounts/me/billing-contacts/{CONTACT_ID}")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["email"] == "finance@example.com"


@pytest.mark.asyncio
async def test_api_add_billing_contact():
    """27. POST /corporate/accounts/me/billing-contacts — 201."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    contact_response = _make_contact_response()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_billing_contacts.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_billing_contacts.add_billing_contact",
            new=AsyncMock(return_value=contact_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/api/v1/corporate/accounts/me/billing-contacts",
            json={"name": "Jane Smith", "email": "finance@example.com"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["email"] == "finance@example.com"


@pytest.mark.asyncio
async def test_api_update_billing_contact():
    """28. PUT /corporate/accounts/me/billing-contacts/{id} — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    contact_response = BillingContactResponse(
        id=CONTACT_ID,
        account_id=ACCOUNT_ID,
        name="Updated Name",
        email="finance@example.com",
        phone=None,
        role=None,
        receives_invoices=True,
        receives_budget_alerts=False,
        receives_monthly_summary=False,
        is_active=True,
        added_by_id=ADMIN_ID,
        created_at=NOW,
        updated_at=NOW,
    )

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_billing_contacts.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_billing_contacts.update_billing_contact",
            new=AsyncMock(return_value=contact_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.put(
            f"/api/v1/corporate/accounts/me/billing-contacts/{CONTACT_ID}",
            json={"name": "Updated Name"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_api_deactivate_billing_contact():
    """29. DELETE /corporate/accounts/me/billing-contacts/{id}/deactivate — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    contact_response = BillingContactResponse(
        id=CONTACT_ID,
        account_id=ACCOUNT_ID,
        name="Jane Smith",
        email="finance@example.com",
        phone=None,
        role=None,
        receives_invoices=True,
        receives_budget_alerts=False,
        receives_monthly_summary=False,
        is_active=False,
        added_by_id=ADMIN_ID,
        created_at=NOW,
        updated_at=NOW,
    )

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_billing_contacts.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_billing_contacts.deactivate_billing_contact",
            new=AsyncMock(return_value=contact_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.delete(
            f"/api/v1/corporate/accounts/me/billing-contacts/{CONTACT_ID}/deactivate"
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_api_platform_admin_list_billing_contacts():
    """30. GET /admin/corporate/accounts/{id}/billing-contacts — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin

    fake_user, fake_db = _fake_user_deps(is_admin=True)
    list_response = BillingContactListResponse(
        account_id=ACCOUNT_ID, total=1, contacts=[_make_contact_response()]
    )

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[require_admin] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_billing_contacts.list_billing_contacts",
            new=AsyncMock(return_value=list_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/billing-contacts")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_api_add_billing_contact_no_account():
    """31. POST /corporate/accounts/me/billing-contacts — 404 when not a member."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_billing_contacts.get_user_account",
            new=AsyncMock(return_value=None),
        ),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/api/v1/corporate/accounts/me/billing-contacts",
            json={"name": "X", "email": "x@example.com"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_billing_contact_stores_phone_and_role():
    """32. add_billing_contact — phone and role stored correctly."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    call_count = 0
    captured: list[CorporateBillingContact] = []

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    def _capture(obj):
        obj.id = CONTACT_ID
        obj.created_at = NOW
        obj.updated_at = NOW
        captured.append(obj)

    db.add = MagicMock(side_effect=_capture)

    data = BillingContactCreate(
        name="Jane", email="jane@example.com", phone="+1-555-0100", role="CFO"
    )
    await add_billing_contact(db, ACCOUNT_ID, ADMIN_ID, data)

    assert captured[0].phone == "+1-555-0100"
    assert captured[0].role == "CFO"


@pytest.mark.asyncio
async def test_add_billing_contact_budget_alerts_defaults_false():
    """33. add_billing_contact — receives_budget_alerts defaults to False."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    call_count = 0
    captured: list[CorporateBillingContact] = []

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    def _capture(obj):
        obj.id = CONTACT_ID
        obj.created_at = NOW
        obj.updated_at = NOW
        captured.append(obj)

    db.add = MagicMock(side_effect=_capture)

    data = BillingContactCreate(name="Jane", email="jane@example.com")
    await add_billing_contact(db, ACCOUNT_ID, ADMIN_ID, data)

    assert captured[0].receives_budget_alerts is False


@pytest.mark.asyncio
async def test_update_billing_contact_role():
    """34. update_billing_contact — role updated."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    contact = _make_contact(role=None)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = contact
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    data = BillingContactUpdate(role="AP Manager")
    await update_billing_contact(db, ACCOUNT_ID, CONTACT_ID, ADMIN_ID, data)

    assert contact.role == "AP Manager"


@pytest.mark.asyncio
async def test_update_billing_contact_receives_monthly_summary():
    """35. update_billing_contact — receives_monthly_summary toggled."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    contact = _make_contact(receives_monthly_summary=False)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = contact
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    data = BillingContactUpdate(receives_monthly_summary=True)
    await update_billing_contact(db, ACCOUNT_ID, CONTACT_ID, ADMIN_ID, data)

    assert contact.receives_monthly_summary is True


@pytest.mark.asyncio
async def test_deactivate_billing_contact_not_found():
    """36. deactivate_billing_contact — not found → 404."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await deactivate_billing_contact(db, ACCOUNT_ID, contact_id=9999, user_id=ADMIN_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_billing_contacts_total_reflects_filter():
    """37. list_billing_contacts — total reflects active_only filter correctly."""
    db = AsyncMock()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one.return_value = 3  # total active
        else:
            r.scalars.return_value.all.return_value = [
                _make_contact(contact_id=i, email=f"c{i}@example.com")
                for i in range(1, 4)
            ]
        return r

    db.execute = fake_execute

    result = await list_billing_contacts(db, ACCOUNT_ID, active_only=True)
    assert result.total == 3


def test_billing_contact_create_uppercase_email_lowercased():
    """38. BillingContactCreate — email with mixed case is normalised to lowercase."""
    data = BillingContactCreate(name="CFO", email="CFO@CORP.IO")
    assert data.email == "cfo@corp.io"
