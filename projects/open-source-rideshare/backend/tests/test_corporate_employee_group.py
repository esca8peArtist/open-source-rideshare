"""Tests for the Corporate Employee Groups feature.

Service tests (async, mocked DB):
  1.  create_group — success creates new group
  2.  create_group — duplicate name → 409
  3.  get_group — success returns group
  4.  get_group — not found → 404
  5.  list_groups — active_only=True returns active groups only
  6.  list_groups — active_only=False returns all groups
  7.  list_groups — empty list when no groups
  8.  update_group — success updates name
  9.  update_group — name conflict → 409
  10. update_group — group not found → 404
  11. deactivate_group — sets is_active=False
  12. deactivate_group — not found → 404
  13. delete_group — calls db.delete and flush
  14. delete_group — not found → 404
  15. add_member_to_group — success creates membership
  16. add_member_to_group — duplicate membership → 409
  17. add_member_to_group — unknown member → 404
  18. remove_member_from_group — success deletes membership
  19. remove_member_from_group — not found → 404
  20. list_group_members — returns memberships
  21. get_member_groups — returns groups for a member
  22. get_group_stats — returns correct stats

Schema tests (sync):
  23. GroupCreate — valid schema
  24. GroupCreate — name too long → ValidationError
  25. GroupUpdate — all fields optional
  26. GroupResponse — from_attributes works
  27. MembershipResponse — from_attributes works
  28. AddMemberToGroupRequest — valid schema
  29. GroupStatsResponse — fields present

API layer tests (services patched):
  30. GET  /corporate/accounts/me/groups — 200 list
  31. POST /corporate/accounts/me/groups — 201 create
  32. GET  /corporate/accounts/me/groups/{id} — 200 get
  33. GET  /corporate/accounts/me/groups/{id} — 404
  34. PUT  /corporate/accounts/me/groups/{id} — 200 update
  35. POST /corporate/accounts/me/groups/{id}/deactivate — 200 deactivate
  36. DELETE /corporate/accounts/me/groups/{id} — 204 hard delete
  37. GET  /corporate/accounts/me/groups/{id}/members — 200 list members
  38. POST /corporate/accounts/me/groups/{id}/members — 201 add member
  39. DELETE /corporate/accounts/me/groups/{id}/members/{mid} — 204 remove member
  40. GET  /corporate/accounts/me/members/{mid}/groups — 200 member groups
  41. GET  /platform-admin/corporate/groups — 200 platform admin list
  42. GET  /platform-admin/corporate/groups/{id}/stats — 200 group stats
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate_employee_group import (
    CorporateEmployeeGroup,
    CorporateGroupMembership,
)
from app.schemas.corporate_employee_group import (
    AddMemberToGroupRequest,
    GroupCreate,
    GroupResponse,
    GroupStatsResponse,
    GroupUpdate,
    MembershipResponse,
)
from app.services.corporate_employee_group import (
    add_member_to_group,
    create_group,
    deactivate_group,
    delete_group,
    get_group,
    get_group_stats,
    get_member_groups,
    list_group_members,
    list_groups,
    remove_member_from_group,
    update_group,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
_ACCOUNT_ID = 1
_GROUP_ID = 10
_MEMBER_ID = 5
_USER_ID = 20
_MEMBERSHIP_ID = 99


def _make_group(
    id: int = _GROUP_ID,
    account_id: int = _ACCOUNT_ID,
    name: str = "VIP Executives",
    description: str | None = "Top-level VIP group",
    color: str | None = "#FF5733",
    is_active: bool = True,
    created_by_id: int | None = _USER_ID,
) -> CorporateEmployeeGroup:
    group = CorporateEmployeeGroup(
        id=id,
        account_id=account_id,
        name=name,
        description=description,
        color=color,
        is_active=is_active,
        created_by_id=created_by_id,
        created_at=_NOW,
        updated_at=_NOW,
    )
    return group


def _make_membership(
    id: int = _MEMBERSHIP_ID,
    group_id: int = _GROUP_ID,
    member_id: int = _MEMBER_ID,
    added_by_id: int | None = _USER_ID,
) -> CorporateGroupMembership:
    membership = CorporateGroupMembership(
        id=id,
        group_id=group_id,
        member_id=member_id,
        added_by_id=added_by_id,
        created_at=_NOW,
    )
    return membership


def _mock_db_with_one(obj) -> AsyncMock:
    """DB mock that returns *obj* from scalar_one_or_none."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    result.scalar_one.return_value = 0
    db.execute.return_value = result
    return db


def _mock_db_with_list(items: list) -> AsyncMock:
    """DB mock that returns *items* from scalars().all()."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    result.scalar_one_or_none.return_value = None
    result.scalar_one.return_value = len(items)
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# Service: create_group
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_group_success():
    """create_group adds a new group when name is unique within account."""
    db = _mock_db_with_one(None)  # no existing group with that name
    data = GroupCreate(name="Remote Workers", description="Fully remote employees")
    group = await create_group(db, account_id=_ACCOUNT_ID, data=data, created_by_id=_USER_ID)
    assert group.name == "Remote Workers"
    assert group.account_id == _ACCOUNT_ID
    assert group.is_active is True
    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_create_group_duplicate_name_raises_409():
    """create_group raises 409 when a group with the same name already exists."""
    existing = _make_group(name="Remote Workers")
    db = _mock_db_with_one(existing)
    data = GroupCreate(name="Remote Workers")
    with pytest.raises(HTTPException) as exc_info:
        await create_group(db, account_id=_ACCOUNT_ID, data=data, created_by_id=_USER_ID)
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service: get_group
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_group_success():
    """get_group returns the group when found."""
    group = _make_group()
    db = _mock_db_with_one(group)
    result = await get_group(db, group_id=_GROUP_ID, account_id=_ACCOUNT_ID)
    assert result.id == _GROUP_ID


@pytest.mark.asyncio
async def test_get_group_not_found_raises_404():
    """get_group raises 404 when the group does not exist."""
    db = _mock_db_with_one(None)
    with pytest.raises(HTTPException) as exc_info:
        await get_group(db, group_id=9999, account_id=_ACCOUNT_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: list_groups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_groups_active_only():
    """list_groups returns only active groups by default."""
    groups = [_make_group(), _make_group(id=11, name="Engineering All-Hands")]
    db = _mock_db_with_list(groups)
    result = await list_groups(db, account_id=_ACCOUNT_ID, active_only=True)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_groups_all_when_active_only_false():
    """list_groups with active_only=False returns all groups including inactive."""
    groups = [_make_group(), _make_group(id=11, name="Archived", is_active=False)]
    db = _mock_db_with_list(groups)
    result = await list_groups(db, account_id=_ACCOUNT_ID, active_only=False)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_groups_empty():
    """list_groups returns an empty list when no groups exist."""
    db = _mock_db_with_list([])
    result = await list_groups(db, account_id=_ACCOUNT_ID)
    assert result == []


# ---------------------------------------------------------------------------
# Service: update_group
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_group_success():
    """update_group modifies the group name and description."""
    group = _make_group()
    db = AsyncMock()

    # First call: _require_group (_get_group_by_id) → returns the group.
    # Second call: _get_group_by_name (name conflict check) → returns None.
    result1 = MagicMock()
    result1.scalar_one_or_none.return_value = group
    result2 = MagicMock()
    result2.scalar_one_or_none.return_value = None

    db.execute.side_effect = [result1, result2]

    data = GroupUpdate(name="Updated Name", description="New description")
    updated = await update_group(db, group_id=_GROUP_ID, account_id=_ACCOUNT_ID, data=data)
    assert updated.name == "Updated Name"
    assert updated.description == "New description"


@pytest.mark.asyncio
async def test_update_group_name_conflict_raises_409():
    """update_group raises 409 when the new name collides with another group."""
    group = _make_group(name="Original Name")
    conflicting = _make_group(id=99, name="Taken Name")
    db = AsyncMock()

    result1 = MagicMock()
    result1.scalar_one_or_none.return_value = group
    result2 = MagicMock()
    result2.scalar_one_or_none.return_value = conflicting

    db.execute.side_effect = [result1, result2]

    data = GroupUpdate(name="Taken Name")
    with pytest.raises(HTTPException) as exc_info:
        await update_group(db, group_id=_GROUP_ID, account_id=_ACCOUNT_ID, data=data)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_update_group_not_found_raises_404():
    """update_group raises 404 when the group does not exist."""
    db = _mock_db_with_one(None)
    data = GroupUpdate(name="Does not matter")
    with pytest.raises(HTTPException) as exc_info:
        await update_group(db, group_id=9999, account_id=_ACCOUNT_ID, data=data)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: deactivate_group
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_group_sets_inactive():
    """deactivate_group sets is_active=False."""
    group = _make_group(is_active=True)
    db = _mock_db_with_one(group)
    result = await deactivate_group(db, group_id=_GROUP_ID, account_id=_ACCOUNT_ID)
    assert result.is_active is False
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_deactivate_group_not_found_raises_404():
    """deactivate_group raises 404 when the group does not exist."""
    db = _mock_db_with_one(None)
    with pytest.raises(HTTPException) as exc_info:
        await deactivate_group(db, group_id=9999, account_id=_ACCOUNT_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: delete_group
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_group_success():
    """delete_group calls db.delete and flush."""
    group = _make_group()
    db = _mock_db_with_one(group)
    await delete_group(db, group_id=_GROUP_ID, account_id=_ACCOUNT_ID)
    db.delete.assert_called_once_with(group)
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_delete_group_not_found_raises_404():
    """delete_group raises 404 when the group does not exist."""
    db = _mock_db_with_one(None)
    with pytest.raises(HTTPException) as exc_info:
        await delete_group(db, group_id=9999, account_id=_ACCOUNT_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: add_member_to_group
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_member_to_group_success():
    """add_member_to_group creates a new membership."""
    group = _make_group()
    from app.models.corporate import BusinessAccountMember
    mock_member = MagicMock(spec=BusinessAccountMember)
    mock_member.id = _MEMBER_ID

    db = AsyncMock()
    # Calls: 1) _require_group, 2) member lookup, 3) membership duplicate check
    r_group = MagicMock(); r_group.scalar_one_or_none.return_value = group
    r_member = MagicMock(); r_member.scalar_one_or_none.return_value = mock_member
    r_memship = MagicMock(); r_memship.scalar_one_or_none.return_value = None
    db.execute.side_effect = [r_group, r_member, r_memship]

    membership = await add_member_to_group(
        db,
        group_id=_GROUP_ID,
        account_id=_ACCOUNT_ID,
        member_id=_MEMBER_ID,
        added_by_id=_USER_ID,
    )
    assert membership.group_id == _GROUP_ID
    assert membership.member_id == _MEMBER_ID
    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_add_member_to_group_duplicate_raises_409():
    """add_member_to_group raises 409 when the member is already in the group."""
    group = _make_group()
    from app.models.corporate import BusinessAccountMember
    mock_member = MagicMock(spec=BusinessAccountMember)
    existing_membership = _make_membership()

    db = AsyncMock()
    r_group = MagicMock(); r_group.scalar_one_or_none.return_value = group
    r_member = MagicMock(); r_member.scalar_one_or_none.return_value = mock_member
    r_memship = MagicMock(); r_memship.scalar_one_or_none.return_value = existing_membership
    db.execute.side_effect = [r_group, r_member, r_memship]

    with pytest.raises(HTTPException) as exc_info:
        await add_member_to_group(
            db,
            group_id=_GROUP_ID,
            account_id=_ACCOUNT_ID,
            member_id=_MEMBER_ID,
            added_by_id=_USER_ID,
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_add_member_to_group_unknown_member_raises_404():
    """add_member_to_group raises 404 when the member is not in this account."""
    group = _make_group()

    db = AsyncMock()
    r_group = MagicMock(); r_group.scalar_one_or_none.return_value = group
    r_member = MagicMock(); r_member.scalar_one_or_none.return_value = None
    db.execute.side_effect = [r_group, r_member]

    with pytest.raises(HTTPException) as exc_info:
        await add_member_to_group(
            db,
            group_id=_GROUP_ID,
            account_id=_ACCOUNT_ID,
            member_id=9999,
            added_by_id=_USER_ID,
        )
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: remove_member_from_group
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_member_from_group_success():
    """remove_member_from_group deletes the membership."""
    group = _make_group()
    membership = _make_membership()

    db = AsyncMock()
    r_group = MagicMock(); r_group.scalar_one_or_none.return_value = group
    r_memship = MagicMock(); r_memship.scalar_one_or_none.return_value = membership
    db.execute.side_effect = [r_group, r_memship]

    await remove_member_from_group(
        db, group_id=_GROUP_ID, account_id=_ACCOUNT_ID, member_id=_MEMBER_ID
    )
    db.delete.assert_called_once_with(membership)
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_remove_member_from_group_not_found_raises_404():
    """remove_member_from_group raises 404 when membership does not exist."""
    group = _make_group()

    db = AsyncMock()
    r_group = MagicMock(); r_group.scalar_one_or_none.return_value = group
    r_memship = MagicMock(); r_memship.scalar_one_or_none.return_value = None
    db.execute.side_effect = [r_group, r_memship]

    with pytest.raises(HTTPException) as exc_info:
        await remove_member_from_group(
            db, group_id=_GROUP_ID, account_id=_ACCOUNT_ID, member_id=_MEMBER_ID
        )
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: list_group_members
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_group_members_returns_memberships():
    """list_group_members returns the memberships for a group."""
    group = _make_group()
    memberships = [_make_membership(), _make_membership(id=100, member_id=6)]

    db = AsyncMock()
    r_group = MagicMock(); r_group.scalar_one_or_none.return_value = group
    r_list = MagicMock(); r_list.scalars.return_value.all.return_value = memberships
    db.execute.side_effect = [r_group, r_list]

    result = await list_group_members(
        db, group_id=_GROUP_ID, account_id=_ACCOUNT_ID
    )
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Service: get_member_groups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_member_groups_returns_groups():
    """get_member_groups returns all active groups for a member."""
    groups = [_make_group(), _make_group(id=11, name="Engineering All-Hands")]
    db = _mock_db_with_list(groups)
    result = await get_member_groups(db, account_id=_ACCOUNT_ID, member_id=_MEMBER_ID)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Service: get_group_stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_group_stats_returns_correct_values():
    """get_group_stats returns member_count and active_members."""
    group = _make_group()

    db = AsyncMock()
    r_group = MagicMock(); r_group.scalar_one_or_none.return_value = group
    r_total = MagicMock(); r_total.scalar_one.return_value = 10
    r_active = MagicMock(); r_active.scalar_one.return_value = 8
    db.execute.side_effect = [r_group, r_total, r_active]

    stats = await get_group_stats(db, group_id=_GROUP_ID, account_id=_ACCOUNT_ID)
    assert stats.group_id == _GROUP_ID
    assert stats.name == "VIP Executives"
    assert stats.member_count == 10
    assert stats.active_members == 8


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_group_create_valid():
    data = GroupCreate(name="VIP Executives", description="Top-level execs", color="#FF5733")
    assert data.name == "VIP Executives"
    assert data.color == "#FF5733"


def test_group_create_name_too_long_raises():
    with pytest.raises(ValidationError):
        GroupCreate(name="x" * 101)


def test_group_update_all_optional():
    data = GroupUpdate()
    assert data.name is None
    assert data.description is None
    assert data.color is None
    assert data.is_active is None


def test_group_response_from_attributes():
    group = _make_group()
    resp = GroupResponse.model_validate(group)
    assert resp.id == _GROUP_ID
    assert resp.name == "VIP Executives"
    assert resp.is_active is True


def test_membership_response_from_attributes():
    membership = _make_membership()
    resp = MembershipResponse.model_validate(membership)
    assert resp.id == _MEMBERSHIP_ID
    assert resp.group_id == _GROUP_ID
    assert resp.member_id == _MEMBER_ID


def test_add_member_to_group_request_valid():
    req = AddMemberToGroupRequest(member_id=5)
    assert req.member_id == 5


def test_group_stats_response_fields():
    stats = GroupStatsResponse(
        group_id=10,
        name="VIP Executives",
        member_count=10,
        active_members=8,
        created_at=_NOW,
    )
    assert stats.member_count == 10
    assert stats.active_members == 8


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

_BASE = "/api/v1/corporate/accounts/me/groups"
_MEMBERS_BASE = "/api/v1/corporate/accounts/me/members"
_PLATFORM_BASE = "/api/v1/platform-admin/corporate/groups"

_DUMMY_GROUP = _make_group()
_DUMMY_MEMBERSHIP = _make_membership()


def _make_app_client():
    """Build a TestClient with auth + DB deps overridden."""
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = _USER_ID

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
    "app.api.v1.corporate_employee_group._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_employee_group.list_groups",
    new_callable=AsyncMock,
    return_value=[_DUMMY_GROUP],
)
def test_api_list_groups_200(mock_list, mock_resolve):
    client = _make_app_client()
    resp = client.get(_BASE)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1


@patch(
    "app.api.v1.corporate_employee_group._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_employee_group.create_group",
    new_callable=AsyncMock,
    return_value=_DUMMY_GROUP,
)
def test_api_create_group_201(mock_create, mock_resolve):
    client = _make_app_client()
    resp = client.post(_BASE, json={"name": "VIP Executives"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "VIP Executives"


@patch(
    "app.api.v1.corporate_employee_group._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_employee_group.get_group",
    new_callable=AsyncMock,
    return_value=_DUMMY_GROUP,
)
def test_api_get_group_200(mock_get, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/{_GROUP_ID}")
    assert resp.status_code == 200
    assert resp.json()["id"] == _GROUP_ID


@patch(
    "app.api.v1.corporate_employee_group._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_employee_group.get_group",
    new_callable=AsyncMock,
    side_effect=HTTPException(status_code=404, detail="Not found"),
)
def test_api_get_group_404(mock_get, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/9999")
    assert resp.status_code == 404


@patch(
    "app.api.v1.corporate_employee_group._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_employee_group.update_group",
    new_callable=AsyncMock,
    return_value=_DUMMY_GROUP,
)
def test_api_update_group_200(mock_update, mock_resolve):
    client = _make_app_client()
    resp = client.put(f"{_BASE}/{_GROUP_ID}", json={"name": "Updated Name"})
    assert resp.status_code == 200


@patch(
    "app.api.v1.corporate_employee_group._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_employee_group.deactivate_group",
    new_callable=AsyncMock,
    return_value=_make_group(is_active=False),
)
def test_api_deactivate_group_200(mock_deactivate, mock_resolve):
    client = _make_app_client()
    resp = client.post(f"{_BASE}/{_GROUP_ID}/deactivate")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@patch(
    "app.api.v1.corporate_employee_group._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_employee_group.delete_group",
    new_callable=AsyncMock,
    return_value=None,
)
def test_api_delete_group_204(mock_delete, mock_resolve):
    client = _make_app_client()
    resp = client.delete(f"{_BASE}/{_GROUP_ID}")
    assert resp.status_code == 204


@patch(
    "app.api.v1.corporate_employee_group._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_employee_group.list_group_members",
    new_callable=AsyncMock,
    return_value=[_DUMMY_MEMBERSHIP],
)
def test_api_list_group_members_200(mock_list, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/{_GROUP_ID}/members")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1


@patch(
    "app.api.v1.corporate_employee_group._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_employee_group.add_member_to_group",
    new_callable=AsyncMock,
    return_value=_DUMMY_MEMBERSHIP,
)
def test_api_add_group_member_201(mock_add, mock_resolve):
    client = _make_app_client()
    resp = client.post(f"{_BASE}/{_GROUP_ID}/members", json={"member_id": _MEMBER_ID})
    assert resp.status_code == 201
    assert resp.json()["member_id"] == _MEMBER_ID


@patch(
    "app.api.v1.corporate_employee_group._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_employee_group.remove_member_from_group",
    new_callable=AsyncMock,
    return_value=None,
)
def test_api_remove_group_member_204(mock_remove, mock_resolve):
    client = _make_app_client()
    resp = client.delete(f"{_BASE}/{_GROUP_ID}/members/{_MEMBER_ID}")
    assert resp.status_code == 204


@patch(
    "app.api.v1.corporate_employee_group._resolve_account_id",
    new_callable=AsyncMock,
    return_value=_ACCOUNT_ID,
)
@patch(
    "app.api.v1.corporate_employee_group.get_member_groups",
    new_callable=AsyncMock,
    return_value=[_DUMMY_GROUP],
)
def test_api_get_member_groups_200(mock_get, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_MEMBERS_BASE}/{_MEMBER_ID}/groups")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1


@patch(
    "app.api.v1.corporate_employee_group.list_groups",
    new_callable=AsyncMock,
    return_value=[_DUMMY_GROUP],
)
def test_api_platform_admin_list_groups_200(mock_list):
    client = _make_app_client()
    resp = client.get(f"{_PLATFORM_BASE}?account_id={_ACCOUNT_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1


@patch(
    "app.api.v1.corporate_employee_group.get_group_stats",
    new_callable=AsyncMock,
    return_value=GroupStatsResponse(
        group_id=_GROUP_ID,
        name="VIP Executives",
        member_count=10,
        active_members=8,
        created_at=_NOW,
    ),
)
def test_api_platform_admin_group_stats_200(mock_stats):
    client = _make_app_client()
    resp = client.get(f"{_PLATFORM_BASE}/{_GROUP_ID}/stats?account_id={_ACCOUNT_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["member_count"] == 10
    assert data["active_members"] == 8
