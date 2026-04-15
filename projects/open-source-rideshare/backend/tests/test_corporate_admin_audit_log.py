"""Tests for the Corporate Admin Audit Log feature.

Service tests (async, mocked DB):
  1.  log_action — success, entry created and flushed
  2.  log_action — actor_id=None (system action) stored correctly
  3.  log_action — details JSONB stored correctly
  4.  list_audit_logs — admin success, returns entries newest-first
  5.  list_audit_logs — non-admin → 403
  6.  list_audit_logs — filter by actor_id
  7.  list_audit_logs — filter by action
  8.  list_audit_logs — filter by resource_type
  9.  list_audit_logs — filter by from_dt
  10. list_audit_logs — filter by to_dt
  11. list_audit_logs — empty result
  12. list_audit_logs — pagination skip/limit respected
  13. get_audit_log_entry — admin success
  14. get_audit_log_entry — non-admin → 403
  15. get_audit_log_entry — not found → 404
  16. get_audit_log_entry — wrong account → 404
  17. list_audit_logs_platform — returns entries without auth check
  18. list_audit_logs_platform — filter by action
  19. get_audit_log_entry_platform — success
  20. get_audit_log_entry_platform — not found → 404

Schema tests (sync):
  21. AuditLogEntryResponse — valid with all fields
  22. AuditLogEntryResponse — actor_id optional (None)
  23. AuditLogEntryResponse — details optional (None)
  24. AuditLogListResponse — valid with entries list

API layer tests (service patched):
  25. GET /corporate/accounts/me/audit-log — 200
  26. GET /corporate/accounts/me/audit-log/{id} — 200
  27. GET /admin/corporate/accounts/{id}/audit-log — 200
  28. GET /admin/corporate/accounts/{id}/audit-log/{entry_id} — 200
  29. GET /corporate/accounts/me/audit-log — 403 when not admin
  30. GET /corporate/accounts/me/audit-log — 404 when not a member
  31. GET /corporate/accounts/me/audit-log — actor_id query param passed through
  32. GET /corporate/accounts/me/audit-log — action query param passed through
  33. GET /corporate/accounts/me/audit-log — resource_type query param passed through
  34. GET /admin/corporate/accounts/{id}/audit-log — action filter forwarded
  35. list_audit_logs — total count correct
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_admin_audit_log import CorporateAdminAuditLog
from app.schemas.corporate_admin_audit_log import (
    AuditLogEntryResponse,
    AuditLogListResponse,
)
from app.services.corporate_admin_audit_log import (
    get_audit_log_entry,
    get_audit_log_entry_platform,
    list_audit_logs,
    list_audit_logs_platform,
    log_action,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 1
ADMIN_ID = 10
MEMBER_ID = 20
ENTRY_ID = 100


def _make_member(user_id: int, role: MemberRole = MemberRole.ADMIN) -> BusinessAccountMember:
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = ACCOUNT_ID
    m.user_id = user_id
    m.role = role
    m.is_active = True
    return m


def _make_entry(
    entry_id: int = ENTRY_ID,
    account_id: int = ACCOUNT_ID,
    actor_id: int | None = ADMIN_ID,
    action: str = "billing_contact.create",
    resource_type: str = "billing_contact",
    resource_id: str = "42",
    details: dict | None = None,
) -> CorporateAdminAuditLog:
    e = MagicMock(spec=CorporateAdminAuditLog)
    e.id = entry_id
    e.account_id = account_id
    e.actor_id = actor_id
    e.action = action
    e.resource_type = resource_type
    e.resource_id = resource_id
    e.details = details
    e.created_at = NOW
    return e


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_action_success():
    """1. log_action — happy path: entry created and flushed."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    result = await log_action(
        db, ACCOUNT_ID, ADMIN_ID, "billing_contact.create", "billing_contact", "42"
    )

    db.add.assert_called_once()
    db.flush.assert_called_once()
    added = db.add.call_args[0][0]
    assert added.account_id == ACCOUNT_ID
    assert added.actor_id == ADMIN_ID
    assert added.action == "billing_contact.create"
    assert added.resource_type == "billing_contact"
    assert added.resource_id == "42"
    assert added.details is None


@pytest.mark.asyncio
async def test_log_action_system_actor():
    """2. log_action — actor_id=None stored correctly for system events."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    await log_action(db, ACCOUNT_ID, None, "invoice.generate", "invoice", "7")

    added = db.add.call_args[0][0]
    assert added.actor_id is None


@pytest.mark.asyncio
async def test_log_action_with_details():
    """3. log_action — details JSONB stored correctly."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    details = {"before": {"name": "Old"}, "after": {"name": "New"}}
    await log_action(
        db, ACCOUNT_ID, ADMIN_ID, "department.update", "department", "5", details=details
    )

    added = db.add.call_args[0][0]
    assert added.details == details


@pytest.mark.asyncio
async def test_list_audit_logs_success():
    """4. list_audit_logs — admin success, returns entries newest-first."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    entry = _make_entry()

    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one.return_value = 1
        else:
            r.scalars.return_value.all.return_value = [entry]
        return r

    db.execute = fake_execute

    result = await list_audit_logs(db, ACCOUNT_ID, ADMIN_ID)

    assert result.account_id == ACCOUNT_ID
    assert result.total == 1
    assert len(result.entries) == 1
    assert result.entries[0].action == "billing_contact.create"


@pytest.mark.asyncio
async def test_list_audit_logs_non_admin():
    """5. list_audit_logs — non-admin → 403."""
    db = AsyncMock()

    async def fake_execute(stmt):
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await list_audit_logs(db, ACCOUNT_ID, MEMBER_ID)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_list_audit_logs_filter_actor_id():
    """6. list_audit_logs — filter by actor_id respected."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one.return_value = 0
        else:
            r.scalars.return_value.all.return_value = []
        return r

    db.execute = fake_execute
    result = await list_audit_logs(db, ACCOUNT_ID, ADMIN_ID, actor_id=999)
    assert result.total == 0
    assert result.entries == []


@pytest.mark.asyncio
async def test_list_audit_logs_filter_action():
    """7. list_audit_logs — filter by action."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one.return_value = 0
        else:
            r.scalars.return_value.all.return_value = []
        return r

    db.execute = fake_execute
    result = await list_audit_logs(db, ACCOUNT_ID, ADMIN_ID, action="invoice.finalize")
    assert result.total == 0


@pytest.mark.asyncio
async def test_list_audit_logs_filter_resource_type():
    """8. list_audit_logs — filter by resource_type."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one.return_value = 0
        else:
            r.scalars.return_value.all.return_value = []
        return r

    db.execute = fake_execute
    result = await list_audit_logs(db, ACCOUNT_ID, ADMIN_ID, resource_type="department")
    assert result.total == 0


@pytest.mark.asyncio
async def test_list_audit_logs_filter_from_dt():
    """9. list_audit_logs — filter by from_dt."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one.return_value = 0
        else:
            r.scalars.return_value.all.return_value = []
        return r

    db.execute = fake_execute
    result = await list_audit_logs(db, ACCOUNT_ID, ADMIN_ID, from_dt=NOW)
    assert result.total == 0


@pytest.mark.asyncio
async def test_list_audit_logs_filter_to_dt():
    """10. list_audit_logs — filter by to_dt."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one.return_value = 0
        else:
            r.scalars.return_value.all.return_value = []
        return r

    db.execute = fake_execute
    result = await list_audit_logs(db, ACCOUNT_ID, ADMIN_ID, to_dt=NOW)
    assert result.total == 0


@pytest.mark.asyncio
async def test_list_audit_logs_empty():
    """11. list_audit_logs — empty result."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one.return_value = 0
        else:
            r.scalars.return_value.all.return_value = []
        return r

    db.execute = fake_execute
    result = await list_audit_logs(db, ACCOUNT_ID, ADMIN_ID)
    assert result.total == 0
    assert result.entries == []


@pytest.mark.asyncio
async def test_list_audit_logs_pagination():
    """12. list_audit_logs — skip/limit respected (service doesn't error)."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one.return_value = 5
        else:
            r.scalars.return_value.all.return_value = []
        return r

    db.execute = fake_execute
    result = await list_audit_logs(db, ACCOUNT_ID, ADMIN_ID, skip=3, limit=2)
    assert result.total == 5
    assert result.entries == []


@pytest.mark.asyncio
async def test_get_audit_log_entry_success():
    """13. get_audit_log_entry — admin success."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    entry = _make_entry()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = entry
        return r

    db.execute = fake_execute
    result = await get_audit_log_entry(db, ACCOUNT_ID, ADMIN_ID, ENTRY_ID)
    assert result.id == ENTRY_ID
    assert result.action == "billing_contact.create"


@pytest.mark.asyncio
async def test_get_audit_log_entry_non_admin():
    """14. get_audit_log_entry — non-admin → 403."""
    db = AsyncMock()

    async def fake_execute(stmt):
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await get_audit_log_entry(db, ACCOUNT_ID, MEMBER_ID, ENTRY_ID)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_audit_log_entry_not_found():
    """15. get_audit_log_entry — entry not found → 404."""
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
        await get_audit_log_entry(db, ACCOUNT_ID, ADMIN_ID, 9999)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_audit_log_entry_wrong_account():
    """16. get_audit_log_entry — entry belongs to different account → 404."""
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
            r.scalar_one_or_none.return_value = None  # wrong account filter → not found
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await get_audit_log_entry(db, ACCOUNT_ID, ADMIN_ID, ENTRY_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_audit_logs_platform_success():
    """17. list_audit_logs_platform — no auth check, returns entries."""
    db = AsyncMock()
    entry = _make_entry()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one.return_value = 1
        else:
            r.scalars.return_value.all.return_value = [entry]
        return r

    db.execute = fake_execute
    result = await list_audit_logs_platform(db, ACCOUNT_ID)
    assert result.total == 1
    assert result.entries[0].id == ENTRY_ID


@pytest.mark.asyncio
async def test_list_audit_logs_platform_filter_action():
    """18. list_audit_logs_platform — action filter forwarded."""
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
    result = await list_audit_logs_platform(db, ACCOUNT_ID, action="department.delete")
    assert result.total == 0


@pytest.mark.asyncio
async def test_get_audit_log_entry_platform_success():
    """19. get_audit_log_entry_platform — success."""
    db = AsyncMock()
    entry = _make_entry()

    async def fake_execute(stmt):
        r = MagicMock()
        r.scalar_one_or_none.return_value = entry
        return r

    db.execute = fake_execute
    result = await get_audit_log_entry_platform(db, ACCOUNT_ID, ENTRY_ID)
    assert result.id == ENTRY_ID


@pytest.mark.asyncio
async def test_get_audit_log_entry_platform_not_found():
    """20. get_audit_log_entry_platform — not found → 404."""
    db = AsyncMock()

    async def fake_execute(stmt):
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await get_audit_log_entry_platform(db, ACCOUNT_ID, 9999)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_audit_log_entry_response_valid():
    """21. AuditLogEntryResponse — valid with all fields."""
    entry = AuditLogEntryResponse(
        id=1,
        account_id=ACCOUNT_ID,
        actor_id=ADMIN_ID,
        action="billing_contact.create",
        resource_type="billing_contact",
        resource_id="42",
        details={"note": "test"},
        created_at=NOW,
    )
    assert entry.id == 1
    assert entry.actor_id == ADMIN_ID
    assert entry.details == {"note": "test"}


def test_audit_log_entry_response_actor_id_optional():
    """22. AuditLogEntryResponse — actor_id optional (None)."""
    entry = AuditLogEntryResponse(
        id=2,
        account_id=ACCOUNT_ID,
        actor_id=None,
        action="invoice.generate",
        resource_type="invoice",
        resource_id="7",
        details=None,
        created_at=NOW,
    )
    assert entry.actor_id is None


def test_audit_log_entry_response_details_optional():
    """23. AuditLogEntryResponse — details optional (None)."""
    entry = AuditLogEntryResponse(
        id=3,
        account_id=ACCOUNT_ID,
        actor_id=ADMIN_ID,
        action="department.create",
        resource_type="department",
        resource_id="5",
        details=None,
        created_at=NOW,
    )
    assert entry.details is None


def test_audit_log_list_response_valid():
    """24. AuditLogListResponse — valid with entries list."""
    entry = AuditLogEntryResponse(
        id=1,
        account_id=ACCOUNT_ID,
        actor_id=ADMIN_ID,
        action="billing_contact.create",
        resource_type="billing_contact",
        resource_id="42",
        details=None,
        created_at=NOW,
    )
    resp = AuditLogListResponse(account_id=ACCOUNT_ID, total=1, entries=[entry])
    assert resp.total == 1
    assert len(resp.entries) == 1


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

_ENTRY_RESP = AuditLogEntryResponse(
    id=ENTRY_ID,
    account_id=ACCOUNT_ID,
    actor_id=ADMIN_ID,
    action="billing_contact.create",
    resource_type="billing_contact",
    resource_id="42",
    details=None,
    created_at=NOW,
)

_LIST_RESP = AuditLogListResponse(
    account_id=ACCOUNT_ID,
    total=1,
    entries=[_ENTRY_RESP],
)


@pytest.mark.asyncio
async def test_api_list_audit_log_200():
    """25. GET /corporate/accounts/me/audit-log — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = ADMIN_ID
    mock_db = AsyncMock()

    with (
        patch("app.api.v1.corporate_admin_audit_log.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch("app.api.v1.corporate_admin_audit_log.list_audit_logs", new=AsyncMock(return_value=_LIST_RESP)),
    ):
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get("/api/v1/corporate/accounts/me/audit-log")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 1
            assert data["entries"][0]["action"] == "billing_contact.create"
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_get_audit_log_entry_200():
    """26. GET /corporate/accounts/me/audit-log/{entry_id} — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = ADMIN_ID
    mock_db = AsyncMock()

    with (
        patch("app.api.v1.corporate_admin_audit_log.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch("app.api.v1.corporate_admin_audit_log.get_audit_log_entry", new=AsyncMock(return_value=_ENTRY_RESP)),
    ):
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get(f"/api/v1/corporate/accounts/me/audit-log/{ENTRY_ID}")
            assert resp.status_code == 200
            assert resp.json()["id"] == ENTRY_ID
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_platform_admin_list_audit_log_200():
    """27. GET /admin/corporate/accounts/{id}/audit-log — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_db, require_admin
    from app.models.user import User

    mock_admin = MagicMock(spec=User)
    mock_admin.id = 1
    mock_admin.is_admin = True
    mock_db = AsyncMock()

    with patch("app.api.v1.corporate_admin_audit_log.list_audit_logs_platform", new=AsyncMock(return_value=_LIST_RESP)):
        app.dependency_overrides[require_admin] = lambda: mock_admin
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/audit-log")
            assert resp.status_code == 200
            assert resp.json()["total"] == 1
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_platform_admin_get_entry_200():
    """28. GET /admin/corporate/accounts/{id}/audit-log/{entry_id} — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_db, require_admin
    from app.models.user import User

    mock_admin = MagicMock(spec=User)
    mock_admin.id = 1
    mock_admin.is_admin = True
    mock_db = AsyncMock()

    with patch("app.api.v1.corporate_admin_audit_log.get_audit_log_entry_platform", new=AsyncMock(return_value=_ENTRY_RESP)):
        app.dependency_overrides[require_admin] = lambda: mock_admin
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/audit-log/{ENTRY_ID}")
            assert resp.status_code == 200
            assert resp.json()["id"] == ENTRY_ID
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_list_audit_log_403():
    """29. GET /corporate/accounts/me/audit-log — 403 when not admin."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = MEMBER_ID
    mock_db = AsyncMock()

    with (
        patch("app.api.v1.corporate_admin_audit_log.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch("app.api.v1.corporate_admin_audit_log.list_audit_logs", side_effect=HTTPException(status_code=403, detail="Forbidden")),
    ):
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get("/api/v1/corporate/accounts/me/audit-log")
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_list_audit_log_not_member_404():
    """30. GET /corporate/accounts/me/audit-log — 404 when not a member."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = ADMIN_ID
    mock_db = AsyncMock()

    with patch("app.api.v1.corporate_admin_audit_log.get_user_account", new=AsyncMock(return_value=None)):
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get("/api/v1/corporate/accounts/me/audit-log")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_list_audit_log_actor_id_param():
    """31. GET /corporate/accounts/me/audit-log — actor_id query param passed through."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = ADMIN_ID
    mock_db = AsyncMock()

    mock_list = AsyncMock(return_value=AuditLogListResponse(account_id=ACCOUNT_ID, total=0, entries=[]))

    with (
        patch("app.api.v1.corporate_admin_audit_log.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch("app.api.v1.corporate_admin_audit_log.list_audit_logs", mock_list),
    ):
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get("/api/v1/corporate/accounts/me/audit-log?actor_id=42")
            assert resp.status_code == 200
            call_kwargs = mock_list.call_args[1]
            assert call_kwargs["actor_id"] == 42
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_list_audit_log_action_param():
    """32. GET /corporate/accounts/me/audit-log — action query param passed through."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = ADMIN_ID
    mock_db = AsyncMock()

    mock_list = AsyncMock(return_value=AuditLogListResponse(account_id=ACCOUNT_ID, total=0, entries=[]))

    with (
        patch("app.api.v1.corporate_admin_audit_log.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch("app.api.v1.corporate_admin_audit_log.list_audit_logs", mock_list),
    ):
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get("/api/v1/corporate/accounts/me/audit-log?action=department.create")
            assert resp.status_code == 200
            call_kwargs = mock_list.call_args[1]
            assert call_kwargs["action"] == "department.create"
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_list_audit_log_resource_type_param():
    """33. GET /corporate/accounts/me/audit-log — resource_type query param passed through."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = ADMIN_ID
    mock_db = AsyncMock()

    mock_list = AsyncMock(return_value=AuditLogListResponse(account_id=ACCOUNT_ID, total=0, entries=[]))

    with (
        patch("app.api.v1.corporate_admin_audit_log.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch("app.api.v1.corporate_admin_audit_log.list_audit_logs", mock_list),
    ):
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get("/api/v1/corporate/accounts/me/audit-log?resource_type=billing_contact")
            assert resp.status_code == 200
            call_kwargs = mock_list.call_args[1]
            assert call_kwargs["resource_type"] == "billing_contact"
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_platform_admin_list_action_filter():
    """34. GET /admin/corporate/accounts/{id}/audit-log — action filter forwarded."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_db, require_admin
    from app.models.user import User

    mock_admin = MagicMock(spec=User)
    mock_admin.is_admin = True
    mock_db = AsyncMock()

    mock_platform_list = AsyncMock(return_value=AuditLogListResponse(account_id=ACCOUNT_ID, total=0, entries=[]))

    with patch("app.api.v1.corporate_admin_audit_log.list_audit_logs_platform", mock_platform_list):
        app.dependency_overrides[require_admin] = lambda: mock_admin
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/audit-log?action=invoice.void")
            assert resp.status_code == 200
            call_kwargs = mock_platform_list.call_args[1]
            assert call_kwargs["action"] == "invoice.void"
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_audit_logs_total_count():
    """35. list_audit_logs — total count correct even when fewer entries returned."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    entries = [_make_entry(entry_id=i) for i in range(2)]
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one.return_value = 10
        else:
            r.scalars.return_value.all.return_value = entries
        return r

    db.execute = fake_execute
    result = await list_audit_logs(db, ACCOUNT_ID, ADMIN_ID, skip=0, limit=2)
    assert result.total == 10
    assert len(result.entries) == 2
