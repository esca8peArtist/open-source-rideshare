"""Tests for the Corporate Delegate Access feature.

Service tests (async, mocked DB):
  1.  grant_delegate_access — success
  2.  grant_delegate_access — non-admin → 403
  3.  grant_delegate_access — duplicate (same account+principal+delegate) → 409
  4.  revoke_delegate_access — success: is_active=False
  5.  revoke_delegate_access — already inactive → 409
  6.  revoke_delegate_access — non-admin → 403
  7.  revoke_delegate_access — not found → 404
  8.  get_delegate — success
  9.  get_delegate — wrong account → 404
  10. list_my_principals — returns delegations where I am delegate
  11. list_my_principals — active_only=True filters expired/inactive
  12. list_my_delegates — returns delegations where I am principal
  13. list_my_delegates — empty returns total=0
  14. check_delegate_permission — allowed when active delegation exists
  15. check_delegate_permission — denied: no delegation found
  16. check_delegate_permission — denied: can_book_rides=False
  17. check_delegate_permission — denied: cost exceeds max_per_ride_usd
  18. check_delegate_permission — allowed: cost within max_per_ride_usd
  19. check_delegate_permission — expired delegation → denied
  20. update_delegate_access — can_book_rides updated
  21. update_delegate_access — max_per_ride_usd updated
  22. update_delegate_access — non-admin → 403
  23. update_delegate_access — not found → 404

Schema tests (sync):
  24. DelegateCreate — valid
  25. DelegateCreate — principal == delegate → ValidationError
  26. DelegateCreate — valid with max_per_ride_usd and valid_until
  27. DelegateUpdate — all fields optional
  28. DelegatePermissionCheck — valid
  29. DelegatePermissionResult — allowed=True
  30. DelegatePermissionResult — allowed=False with reason

API layer tests (service patched):
  31. GET  /corporate/accounts/me/delegates/my-principals — 200
  32. GET  /corporate/accounts/me/delegates/my-delegates — 200
  33. POST /corporate/accounts/me/delegates/check-permission — 200
  34. POST /corporate/accounts/me/delegates — 201
  35. GET  /corporate/accounts/me/delegates/{id} — 200
  36. PUT  /corporate/accounts/me/delegates/{id} — 200
  37. DELETE /corporate/accounts/me/delegates/{id}/revoke — 200
  38. GET  /admin/corporate/accounts/{id}/delegates — 200
  39. GET  /admin/corporate/accounts/{id}/delegates/{delegation_id} — 200

Extras:
  40. grant_delegate_access — valid_until in the future is stored
  41. list_my_principals — skip/limit pagination
  42. check_delegate_permission — no estimated_cost with max_per_ride_usd → still allowed
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_delegate import CorporateDelegate
from app.schemas.corporate_delegate import (
    DelegateCreate,
    DelegateListResponse,
    DelegatePermissionCheck,
    DelegatePermissionResult,
    DelegateResponse,
    DelegateUpdate,
)
from app.services.corporate_delegate import (
    check_delegate_permission,
    get_delegate,
    grant_delegate_access,
    list_all_delegates,
    list_my_delegates,
    list_my_principals,
    revoke_delegate_access,
    update_delegate_access,
)

# ---------------------------------------------------------------------------
# Constants / fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
FUTURE = datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
PAST = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 1
ADMIN_ID = 10
PRINCIPAL_ID = 20
DELEGATE_ID = 30
DELEGATION_ID = 100


def _make_member(user_id: int, role: MemberRole = MemberRole.ADMIN) -> BusinessAccountMember:
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = ACCOUNT_ID
    m.user_id = user_id
    m.role = role
    m.is_active = True
    return m


def _make_delegation(
    delegation_id: int = DELEGATION_ID,
    account_id: int = ACCOUNT_ID,
    principal_id: int = PRINCIPAL_ID,
    delegate_id: int = DELEGATE_ID,
    can_book_rides: bool = True,
    can_view_history: bool = True,
    max_per_ride_usd=None,
    valid_until=None,
    is_active: bool = True,
    created_by_id: int = ADMIN_ID,
) -> CorporateDelegate:
    d = MagicMock(spec=CorporateDelegate)
    d.id = delegation_id
    d.account_id = account_id
    d.principal_id = principal_id
    d.delegate_id = delegate_id
    d.can_book_rides = can_book_rides
    d.can_view_history = can_view_history
    d.max_per_ride_usd = max_per_ride_usd
    d.valid_until = valid_until
    d.is_active = is_active
    d.created_by_id = created_by_id
    d.created_at = NOW
    d.updated_at = NOW
    return d


# ---------------------------------------------------------------------------
# Service tests — grant_delegate_access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grant_delegate_access_success():
    """1. grant_delegate_access — success."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin   # admin check
        else:
            r.scalar_one_or_none.return_value = None    # no duplicate
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    def _set_id(obj):
        obj.id = DELEGATION_ID
        obj.created_at = NOW
        obj.updated_at = NOW

    db.add = MagicMock(side_effect=_set_id)

    data = DelegateCreate(principal_user_id=PRINCIPAL_ID, delegate_user_id=DELEGATE_ID)
    result = await grant_delegate_access(db, ACCOUNT_ID, ADMIN_ID, data)

    assert result.principal_id == PRINCIPAL_ID
    assert result.delegate_id == DELEGATE_ID
    assert result.can_book_rides is True
    assert result.is_active is True


@pytest.mark.asyncio
async def test_grant_delegate_access_non_admin():
    """2. grant_delegate_access — non-admin → 403."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None   # not an admin
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await grant_delegate_access(
            db, ACCOUNT_ID, DELEGATE_ID,
            DelegateCreate(principal_user_id=PRINCIPAL_ID, delegate_user_id=40),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_grant_delegate_access_duplicate():
    """3. grant_delegate_access — duplicate combination → 409."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    existing = _make_delegation()
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
        await grant_delegate_access(
            db, ACCOUNT_ID, ADMIN_ID,
            DelegateCreate(principal_user_id=PRINCIPAL_ID, delegate_user_id=DELEGATE_ID),
        )
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service tests — revoke_delegate_access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_delegate_access_success():
    """4. revoke_delegate_access — success: is_active set to False."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    delegation = _make_delegation(is_active=True)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = delegation
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    result = await revoke_delegate_access(db, ACCOUNT_ID, DELEGATION_ID, ADMIN_ID)

    assert delegation.is_active is False
    assert result.id == DELEGATION_ID


@pytest.mark.asyncio
async def test_revoke_delegate_access_already_inactive():
    """5. revoke_delegate_access — already inactive → 409."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    delegation = _make_delegation(is_active=False)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = delegation
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await revoke_delegate_access(db, ACCOUNT_ID, DELEGATION_ID, ADMIN_ID)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_revoke_delegate_access_non_admin():
    """6. revoke_delegate_access — non-admin → 403."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await revoke_delegate_access(db, ACCOUNT_ID, DELEGATION_ID, DELEGATE_ID)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_revoke_delegate_access_not_found():
    """7. revoke_delegate_access — not found → 404."""
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
            r.scalar_one_or_none.return_value = None   # not found
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await revoke_delegate_access(db, ACCOUNT_ID, DELEGATION_ID, ADMIN_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Service tests — get_delegate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_delegate_success():
    """8. get_delegate — success."""
    db = AsyncMock()
    delegation = _make_delegation()
    r = MagicMock()
    r.scalar_one_or_none.return_value = delegation
    db.execute = AsyncMock(return_value=r)

    result = await get_delegate(db, ACCOUNT_ID, DELEGATION_ID)
    assert result.id == DELEGATION_ID
    assert result.principal_id == PRINCIPAL_ID


@pytest.mark.asyncio
async def test_get_delegate_wrong_account():
    """9. get_delegate — wrong account → 404."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await get_delegate(db, 999, DELEGATION_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Service tests — list_my_principals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_my_principals_returns_delegations():
    """10. list_my_principals — returns delegations where I am delegate."""
    db = AsyncMock()
    delegation = _make_delegation()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one.return_value = 1   # total count
        else:
            r.scalars.return_value.all.return_value = [delegation]
        return r

    db.execute = fake_execute

    result = await list_my_principals(db, ACCOUNT_ID, DELEGATE_ID)
    assert result.total == 1
    assert len(result.delegates) == 1
    assert result.delegates[0].delegate_id == DELEGATE_ID


@pytest.mark.asyncio
async def test_list_my_principals_active_only_filters():
    """11. list_my_principals — active_only=True filters expired/inactive."""
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

    result = await list_my_principals(db, ACCOUNT_ID, DELEGATE_ID, active_only=True)
    assert result.total == 0
    assert result.delegates == []


# ---------------------------------------------------------------------------
# Service tests — list_my_delegates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_my_delegates_returns_delegations():
    """12. list_my_delegates — returns delegations where I am principal."""
    db = AsyncMock()
    delegation = _make_delegation()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one.return_value = 1
        else:
            r.scalars.return_value.all.return_value = [delegation]
        return r

    db.execute = fake_execute

    result = await list_my_delegates(db, ACCOUNT_ID, PRINCIPAL_ID)
    assert result.total == 1
    assert result.delegates[0].principal_id == PRINCIPAL_ID


@pytest.mark.asyncio
async def test_list_my_delegates_empty():
    """13. list_my_delegates — empty returns total=0."""
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

    result = await list_my_delegates(db, ACCOUNT_ID, PRINCIPAL_ID)
    assert result.total == 0
    assert result.delegates == []


# ---------------------------------------------------------------------------
# Service tests — check_delegate_permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_permission_allowed():
    """14. check_delegate_permission — allowed when active delegation exists."""
    db = AsyncMock()
    delegation = _make_delegation(can_book_rides=True)
    r = MagicMock()
    r.scalar_one_or_none.return_value = delegation
    db.execute = AsyncMock(return_value=r)

    result = await check_delegate_permission(db, ACCOUNT_ID, DELEGATE_ID, PRINCIPAL_ID)
    assert result.allowed is True


@pytest.mark.asyncio
async def test_check_permission_no_delegation():
    """15. check_delegate_permission — denied: no delegation found."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    result = await check_delegate_permission(db, ACCOUNT_ID, DELEGATE_ID, PRINCIPAL_ID)
    assert result.allowed is False
    assert "No active delegation" in result.reason


@pytest.mark.asyncio
async def test_check_permission_can_book_rides_false():
    """16. check_delegate_permission — denied: can_book_rides=False."""
    db = AsyncMock()
    delegation = _make_delegation(can_book_rides=False)
    r = MagicMock()
    r.scalar_one_or_none.return_value = delegation
    db.execute = AsyncMock(return_value=r)

    result = await check_delegate_permission(db, ACCOUNT_ID, DELEGATE_ID, PRINCIPAL_ID)
    assert result.allowed is False
    assert "booking" in result.reason.lower() or "book" in result.reason.lower()


@pytest.mark.asyncio
async def test_check_permission_cost_exceeds_cap():
    """17. check_delegate_permission — denied: cost exceeds max_per_ride_usd."""
    db = AsyncMock()
    delegation = _make_delegation(can_book_rides=True, max_per_ride_usd=50.00)
    r = MagicMock()
    r.scalar_one_or_none.return_value = delegation
    db.execute = AsyncMock(return_value=r)

    result = await check_delegate_permission(
        db, ACCOUNT_ID, DELEGATE_ID, PRINCIPAL_ID, estimated_cost=Decimal("75.00")
    )
    assert result.allowed is False
    assert "cap" in result.reason.lower() or "exceed" in result.reason.lower()


@pytest.mark.asyncio
async def test_check_permission_cost_within_cap():
    """18. check_delegate_permission — allowed: cost within max_per_ride_usd."""
    db = AsyncMock()
    delegation = _make_delegation(can_book_rides=True, max_per_ride_usd=50.00)
    r = MagicMock()
    r.scalar_one_or_none.return_value = delegation
    db.execute = AsyncMock(return_value=r)

    result = await check_delegate_permission(
        db, ACCOUNT_ID, DELEGATE_ID, PRINCIPAL_ID, estimated_cost=Decimal("30.00")
    )
    assert result.allowed is True


@pytest.mark.asyncio
async def test_check_permission_expired():
    """19. check_delegate_permission — expired delegation → denied."""
    db = AsyncMock()
    delegation = _make_delegation(can_book_rides=True, valid_until=PAST)
    r = MagicMock()
    r.scalar_one_or_none.return_value = delegation
    db.execute = AsyncMock(return_value=r)

    result = await check_delegate_permission(db, ACCOUNT_ID, DELEGATE_ID, PRINCIPAL_ID)
    assert result.allowed is False
    assert "expired" in result.reason.lower()


# ---------------------------------------------------------------------------
# Service tests — update_delegate_access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_delegate_can_book_rides():
    """20. update_delegate_access — can_book_rides updated."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    delegation = _make_delegation(can_book_rides=True)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = delegation
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    data = DelegateUpdate(can_book_rides=False)
    result = await update_delegate_access(db, ACCOUNT_ID, DELEGATION_ID, ADMIN_ID, data)

    assert delegation.can_book_rides is False


@pytest.mark.asyncio
async def test_update_delegate_max_per_ride():
    """21. update_delegate_access — max_per_ride_usd updated."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    delegation = _make_delegation(max_per_ride_usd=None)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = delegation
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    data = DelegateUpdate(max_per_ride_usd=Decimal("100.00"))
    await update_delegate_access(db, ACCOUNT_ID, DELEGATION_ID, ADMIN_ID, data)

    assert delegation.max_per_ride_usd == 100.00


@pytest.mark.asyncio
async def test_update_delegate_non_admin():
    """22. update_delegate_access — non-admin → 403."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await update_delegate_access(
            db, ACCOUNT_ID, DELEGATION_ID, DELEGATE_ID, DelegateUpdate(can_book_rides=False)
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_update_delegate_not_found():
    """23. update_delegate_access — not found → 404."""
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
        await update_delegate_access(
            db, ACCOUNT_ID, DELEGATION_ID, ADMIN_ID, DelegateUpdate(can_book_rides=False)
        )
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_delegate_create_valid():
    """24. DelegateCreate — valid."""
    d = DelegateCreate(principal_user_id=1, delegate_user_id=2)
    assert d.principal_user_id == 1
    assert d.delegate_user_id == 2
    assert d.can_book_rides is True
    assert d.can_view_history is True


def test_delegate_create_same_user_raises():
    """25. DelegateCreate — principal == delegate → ValidationError."""
    with pytest.raises(ValidationError):
        DelegateCreate(principal_user_id=5, delegate_user_id=5)


def test_delegate_create_with_cap_and_expiry():
    """26. DelegateCreate — valid with max_per_ride_usd and valid_until."""
    d = DelegateCreate(
        principal_user_id=1,
        delegate_user_id=2,
        max_per_ride_usd=Decimal("50.00"),
        valid_until=FUTURE,
    )
    assert d.max_per_ride_usd == Decimal("50.00")
    assert d.valid_until == FUTURE


def test_delegate_update_all_optional():
    """27. DelegateUpdate — all fields optional."""
    d = DelegateUpdate()
    assert d.can_book_rides is None
    assert d.can_view_history is None
    assert d.max_per_ride_usd is None
    assert d.valid_until is None
    assert d.is_active is None


def test_delegate_permission_check_valid():
    """28. DelegatePermissionCheck — valid."""
    c = DelegatePermissionCheck(delegate_user_id=30, principal_user_id=20)
    assert c.delegate_user_id == 30
    assert c.principal_user_id == 20
    assert c.estimated_ride_cost_usd is None


def test_delegate_permission_result_allowed():
    """29. DelegatePermissionResult — allowed=True."""
    r = DelegatePermissionResult(allowed=True, reason="Delegation is valid.")
    assert r.allowed is True


def test_delegate_permission_result_denied():
    """30. DelegatePermissionResult — allowed=False with reason."""
    r = DelegatePermissionResult(allowed=False, reason="No active delegation found.")
    assert r.allowed is False
    assert r.reason == "No active delegation found."


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------


def _make_delegate_response(**kwargs) -> DelegateResponse:
    defaults = dict(
        id=DELEGATION_ID,
        account_id=ACCOUNT_ID,
        principal_id=PRINCIPAL_ID,
        delegate_id=DELEGATE_ID,
        can_book_rides=True,
        can_view_history=True,
        max_per_ride_usd=None,
        valid_until=None,
        is_active=True,
        created_by_id=ADMIN_ID,
        created_at=NOW,
        updated_at=NOW,
    )
    defaults.update(kwargs)
    return DelegateResponse(**defaults)


def _make_list_response(delegates=None) -> DelegateListResponse:
    if delegates is None:
        delegates = [_make_delegate_response()]
    return DelegateListResponse(
        account_id=ACCOUNT_ID,
        total=len(delegates),
        delegates=delegates,
    )


def _get_test_client():
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = ADMIN_ID
    mock_user.is_admin = True

    async def override_user():
        return mock_user

    async def override_db():
        yield AsyncMock()

    async def override_admin():
        return mock_user

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = override_admin

    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def clear_overrides():
    from app.main import app
    yield
    app.dependency_overrides.clear()


def test_api_list_my_principals():
    """31. GET /corporate/accounts/me/delegates/my-principals — 200."""
    client = _get_test_client()
    resp_data = _make_list_response()

    with patch("app.api.v1.corporate_delegates._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch("app.api.v1.corporate_delegates.list_my_principals", new=AsyncMock(return_value=resp_data)):
        resp = client.get("/api/v1/corporate/accounts/me/delegates/my-principals")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1


def test_api_list_my_delegates():
    """32. GET /corporate/accounts/me/delegates/my-delegates — 200."""
    client = _get_test_client()
    resp_data = _make_list_response()

    with patch("app.api.v1.corporate_delegates._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch("app.api.v1.corporate_delegates.list_my_delegates", new=AsyncMock(return_value=resp_data)):
        resp = client.get("/api/v1/corporate/accounts/me/delegates/my-delegates")

    assert resp.status_code == 200
    data = resp.json()
    assert data["account_id"] == ACCOUNT_ID


def test_api_check_permission():
    """33. POST /corporate/accounts/me/delegates/check-permission — 200."""
    client = _get_test_client()
    perm_result = DelegatePermissionResult(allowed=True, reason="Delegation is valid.")

    with patch("app.api.v1.corporate_delegates._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch("app.api.v1.corporate_delegates.check_delegate_permission", new=AsyncMock(return_value=perm_result)):
        resp = client.post(
            "/api/v1/corporate/accounts/me/delegates/check-permission",
            json={"delegate_user_id": DELEGATE_ID, "principal_user_id": PRINCIPAL_ID},
        )

    assert resp.status_code == 200
    assert resp.json()["allowed"] is True


def test_api_grant_delegate_access():
    """34. POST /corporate/accounts/me/delegates — 201."""
    client = _get_test_client()
    resp_data = _make_delegate_response()

    with patch("app.api.v1.corporate_delegates._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch("app.api.v1.corporate_delegates.grant_delegate_access", new=AsyncMock(return_value=resp_data)):
        resp = client.post(
            "/api/v1/corporate/accounts/me/delegates",
            json={"principal_user_id": PRINCIPAL_ID, "delegate_user_id": DELEGATE_ID},
        )

    assert resp.status_code == 201
    assert resp.json()["id"] == DELEGATION_ID


def test_api_get_delegation():
    """35. GET /corporate/accounts/me/delegates/{id} — 200."""
    client = _get_test_client()
    resp_data = _make_delegate_response()

    with patch("app.api.v1.corporate_delegates._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch("app.api.v1.corporate_delegates.get_delegate", new=AsyncMock(return_value=resp_data)):
        resp = client.get(f"/api/v1/corporate/accounts/me/delegates/{DELEGATION_ID}")

    assert resp.status_code == 200
    assert resp.json()["principal_id"] == PRINCIPAL_ID


def test_api_update_delegation():
    """36. PUT /corporate/accounts/me/delegates/{id} — 200."""
    client = _get_test_client()
    resp_data = _make_delegate_response(can_book_rides=False)

    with patch("app.api.v1.corporate_delegates._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch("app.api.v1.corporate_delegates.update_delegate_access", new=AsyncMock(return_value=resp_data)):
        resp = client.put(
            f"/api/v1/corporate/accounts/me/delegates/{DELEGATION_ID}",
            json={"can_book_rides": False},
        )

    assert resp.status_code == 200
    assert resp.json()["can_book_rides"] is False


def test_api_revoke_delegation():
    """37. DELETE /corporate/accounts/me/delegates/{id}/revoke — 200."""
    client = _get_test_client()
    resp_data = _make_delegate_response(is_active=False)

    with patch("app.api.v1.corporate_delegates._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch("app.api.v1.corporate_delegates.revoke_delegate_access", new=AsyncMock(return_value=resp_data)):
        resp = client.delete(f"/api/v1/corporate/accounts/me/delegates/{DELEGATION_ID}/revoke")

    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_api_platform_admin_list_delegates():
    """38. GET /admin/corporate/accounts/{id}/delegates — 200."""
    client = _get_test_client()
    resp_data = _make_list_response()

    with patch("app.api.v1.corporate_delegates.list_all_delegates", new=AsyncMock(return_value=resp_data)):
        resp = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/delegates")

    assert resp.status_code == 200
    assert resp.json()["account_id"] == ACCOUNT_ID


def test_api_platform_admin_get_delegate():
    """39. GET /admin/corporate/accounts/{id}/delegates/{delegation_id} — 200."""
    client = _get_test_client()
    resp_data = _make_delegate_response()

    with patch("app.api.v1.corporate_delegates.get_delegate", new=AsyncMock(return_value=resp_data)):
        resp = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/delegates/{DELEGATION_ID}")

    assert resp.status_code == 200
    assert resp.json()["id"] == DELEGATION_ID


# ---------------------------------------------------------------------------
# Extra tests (40–42)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grant_delegate_access_with_valid_until():
    """40. grant_delegate_access — valid_until in the future is stored."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    call_count = 0

    captured = {}

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
        captured["valid_until"] = obj.valid_until
        obj.id = DELEGATION_ID
        obj.created_at = NOW
        obj.updated_at = NOW

    db.add = MagicMock(side_effect=_capture)

    data = DelegateCreate(
        principal_user_id=PRINCIPAL_ID,
        delegate_user_id=DELEGATE_ID,
        valid_until=FUTURE,
    )
    result = await grant_delegate_access(db, ACCOUNT_ID, ADMIN_ID, data)

    assert captured["valid_until"] == FUTURE


@pytest.mark.asyncio
async def test_list_my_principals_pagination():
    """41. list_my_principals — skip/limit pagination."""
    db = AsyncMock()
    delegations = [_make_delegation(delegation_id=i) for i in range(3)]
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one.return_value = 3
        else:
            r.scalars.return_value.all.return_value = delegations[1:2]
        return r

    db.execute = fake_execute

    result = await list_my_principals(db, ACCOUNT_ID, DELEGATE_ID, skip=1, limit=1)
    assert result.total == 3
    assert len(result.delegates) == 1


@pytest.mark.asyncio
async def test_check_permission_no_cost_with_cap_still_allowed():
    """42. check_delegate_permission — no estimated_cost with max_per_ride_usd → still allowed."""
    db = AsyncMock()
    delegation = _make_delegation(can_book_rides=True, max_per_ride_usd=50.00)
    r = MagicMock()
    r.scalar_one_or_none.return_value = delegation
    db.execute = AsyncMock(return_value=r)

    # No estimated_cost provided — should still be allowed
    result = await check_delegate_permission(
        db, ACCOUNT_ID, DELEGATE_ID, PRINCIPAL_ID, estimated_cost=None
    )
    assert result.allowed is True
