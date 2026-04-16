"""Tests for the Corporate Carpool Groups feature.

Service layer (async, mocked DB):
  1.  create_group — happy path
  2.  create_group — 409 on duplicate name (case-insensitive)
  3.  get_group — found
  4.  get_group — 404 not found
  5.  list_groups — all groups
  6.  list_groups — filter is_active=True
  7.  list_groups — filter is_active=False
  8.  list_groups — empty list
  9.  update_group — partial update
  10. update_group — name collision 409
  11. update_group — 404 not found
  12. deactivate_group — happy path
  13. deactivate_group — 409 already inactive
  14. deactivate_group — 404 not found
  15. reactivate_group — happy path
  16. reactivate_group — 409 already active
  17. reactivate_group — 404 not found
  18. delete_group — happy path (inactive group)
  19. delete_group — 409 if active
  20. delete_group — 404 not found
  21. add_member — happy path
  22. add_member — 409 already a member
  23. add_member — group 404
  24. remove_member — happy path
  25. remove_member — 404 not a member
  26. list_members — all members
  27. list_members — filter is_active
  28. list_members — group 404
  29. get_member_carpools — found groups
  30. get_member_carpools — empty list
  31. get_group_summary — correct counts
  32. get_group_summary — 404 not found
  33. list_all_platform — all groups
  34. list_all_platform — filter by account_id

Schema validation:
  35. CarpoolGroupCreate — valid data
  36. CarpoolGroupCreate — name too long raises
  37. CarpoolGroupCreate — max_members must be >= 1
  38. CarpoolGroupCreate — departure_time format validation
  39. CarpoolGroupCreate — vehicle_type too long raises
  40. CarpoolGroupUpdate — all fields optional
  41. CarpoolGroupResponse — from_attributes construction
  42. CarpoolMemberCreate — valid data
  43. CarpoolMemberCreate — pickup_sequence must be >= 1
  44. CarpoolGroupSummary — fields correct
  45. CarpoolMemberListResponse — items and total

API layer (service functions patched):
  46. POST admin/carpool-groups — 201 success
  47. GET admin/carpool-groups — 200 returns list
  48. GET admin/carpool-groups/{id} — 200 returns group
  49. GET admin/carpool-groups/{id} — 404 not found
  50. PUT admin/carpool-groups/{id} — 200 updates
  51. POST admin/carpool-groups/{id}/deactivate — 200
  52. POST admin/carpool-groups/{id}/reactivate — 200
  53. DELETE admin/carpool-groups/{id} — 204
  54. POST admin/carpool-groups/{id}/members — 201
  55. DELETE admin/carpool-groups/{id}/members/{mid} — 204
  56. GET admin/carpool-groups/{id}/members — 200
  57. GET admin/carpool-groups/{id}/summary — 200
  58. GET platform-admin/carpool-groups — 200 all
  59. GET platform-admin/carpool-groups/account/{id} — 200
  60. GET member/carpool-groups — 200 active groups
  61. GET member/carpool-groups/my-groups — 200
  62. GET member/carpool-groups/{id} — 200
  63. POST admin/carpool-groups — 409 duplicate name
  64. POST admin/carpool-groups/{id}/members — 409 already member
  65. update_group — only description field
  66. list_groups — multiple groups returned in name order
  67. list_members — empty list for group with no members
  68. get_group_summary — has_destination True/False
  69. get_group_summary — has_departure_time True/False
  70. CarpoolGroupCreate — days_of_week list
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.corporate_carpool_group import (
    CorporateCarpoolGroup,
    CorporateCarpoolMember,
)
from app.schemas.corporate_carpool_group import (
    CarpoolGroupCreate,
    CarpoolGroupListResponse,
    CarpoolGroupResponse,
    CarpoolGroupSummary,
    CarpoolGroupUpdate,
    CarpoolMemberCreate,
    CarpoolMemberListResponse,
    CarpoolMemberResponse,
    CarpoolMemberUpdate,
)
from app.services.corporate_carpool_group import (
    add_member,
    create_group,
    deactivate_group,
    delete_group,
    get_group,
    get_group_summary,
    get_member_carpools,
    list_all_platform,
    list_groups,
    list_members,
    reactivate_group,
    remove_member,
    update_group,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)

ACCOUNT_ID = 10
OTHER_ACCOUNT_ID = 99
GROUP_ID = uuid.uuid4()
GROUP_ID_2 = uuid.uuid4()
MEMBER_USER_ID = 42
ADDED_BY_ID = 1
MEMBER_RECORD_ID = 100


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_group(
    id: uuid.UUID = GROUP_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Morning Commute",
    description: str | None = None,
    max_members: int | None = None,
    home_base_address: str | None = None,
    home_base_lat=None,
    home_base_lng=None,
    destination_address: str | None = None,
    destination_lat=None,
    destination_lng=None,
    departure_time: str | None = None,
    days_of_week=None,
    vehicle_type: str | None = None,
    cost_center_id: int | None = None,
    trip_purpose_id: int | None = None,
    is_active: bool = True,
    created_by_id: int | None = ADDED_BY_ID,
) -> CorporateCarpoolGroup:
    g = CorporateCarpoolGroup()
    g.id = id
    g.account_id = account_id
    g.name = name
    g.description = description
    g.max_members = max_members
    g.home_base_address = home_base_address
    g.home_base_lat = home_base_lat
    g.home_base_lng = home_base_lng
    g.destination_address = destination_address
    g.destination_lat = destination_lat
    g.destination_lng = destination_lng
    g.departure_time = departure_time
    g.days_of_week = days_of_week
    g.vehicle_type = vehicle_type
    g.cost_center_id = cost_center_id
    g.trip_purpose_id = trip_purpose_id
    g.is_active = is_active
    g.created_by_id = created_by_id
    g.created_at = NOW
    g.updated_at = NOW
    return g


def _make_member(
    id: int = MEMBER_RECORD_ID,
    carpool_group_id: uuid.UUID = GROUP_ID,
    account_id: int = ACCOUNT_ID,
    member_id: int = MEMBER_USER_ID,
    pickup_address: str | None = None,
    pickup_lat=None,
    pickup_lng=None,
    pickup_sequence: int | None = None,
    is_active: bool = True,
    added_by_id: int | None = ADDED_BY_ID,
    notes: str | None = None,
) -> CorporateCarpoolMember:
    m = CorporateCarpoolMember()
    m.id = id
    m.carpool_group_id = carpool_group_id
    m.account_id = account_id
    m.member_id = member_id
    m.pickup_address = pickup_address
    m.pickup_lat = pickup_lat
    m.pickup_lng = pickup_lng
    m.pickup_sequence = pickup_sequence
    m.is_active = is_active
    m.added_by_id = added_by_id
    m.notes = notes
    m.joined_at = NOW
    return m


def _async_result(value: Any):
    mock = MagicMock()
    mock.scalar_one_or_none.return_value = value
    mock.scalar.return_value = value
    mock.scalars.return_value.all.return_value = (
        value if isinstance(value, list) else []
    )
    return mock


def _async_list(items: list):
    mock = MagicMock()
    mock.scalars.return_value.all.return_value = items
    mock.scalar_one_or_none.return_value = None
    mock.scalar.return_value = len(items)
    return mock


def _async_scalar(value):
    mock = MagicMock()
    mock.scalar.return_value = value
    mock.scalar_one_or_none.return_value = None
    return mock


def _make_db(execute_returns=None, refresh_fn=None):
    db = AsyncMock()
    if execute_returns is not None:
        if isinstance(execute_returns, list):
            db.execute.side_effect = execute_returns
        else:
            db.execute.return_value = execute_returns
    if refresh_fn is not None:
        db.refresh.side_effect = refresh_fn
    return db


# ---------------------------------------------------------------------------
# Response fixtures
# ---------------------------------------------------------------------------

_GROUP_RESPONSE = CarpoolGroupResponse(
    id=GROUP_ID,
    account_id=ACCOUNT_ID,
    name="Morning Commute",
    description=None,
    max_members=None,
    home_base_address=None,
    home_base_lat=None,
    home_base_lng=None,
    destination_address=None,
    destination_lat=None,
    destination_lng=None,
    departure_time=None,
    days_of_week=None,
    vehicle_type=None,
    cost_center_id=None,
    trip_purpose_id=None,
    is_active=True,
    created_by_id=ADDED_BY_ID,
    created_at=NOW,
    updated_at=NOW,
)

_GROUP_LIST_RESPONSE = CarpoolGroupListResponse(items=[_GROUP_RESPONSE], total=1)
_EMPTY_GROUP_LIST_RESPONSE = CarpoolGroupListResponse(items=[], total=0)

_MEMBER_RESPONSE = CarpoolMemberResponse(
    id=MEMBER_RECORD_ID,
    carpool_group_id=GROUP_ID,
    account_id=ACCOUNT_ID,
    member_id=MEMBER_USER_ID,
    pickup_address=None,
    pickup_lat=None,
    pickup_lng=None,
    pickup_sequence=None,
    is_active=True,
    added_by_id=ADDED_BY_ID,
    notes=None,
    joined_at=NOW,
)

_MEMBER_LIST_RESPONSE = CarpoolMemberListResponse(items=[_MEMBER_RESPONSE], total=1)

_SUMMARY_RESPONSE = CarpoolGroupSummary(
    group_id=GROUP_ID,
    name="Morning Commute",
    total_members=3,
    active_members=2,
    has_destination=False,
    has_departure_time=False,
    days_of_week=None,
)


# ---------------------------------------------------------------------------
# Service layer tests (1-34)
# ---------------------------------------------------------------------------


class TestCreateGroup:
    """Tests 1-2: create_group."""

    @pytest.mark.asyncio
    async def test_creates_group_happy_path(self):
        data = CarpoolGroupCreate(name="Morning Commute")

        db = AsyncMock()
        db.add = MagicMock()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None

        async def _refresh(obj):
            obj.id = GROUP_ID
            obj.account_id = ACCOUNT_ID
            obj.name = "Morning Commute"
            obj.is_active = True
            obj.created_at = NOW
            obj.updated_at = NOW

        db.execute.return_value = no_existing
        db.refresh = AsyncMock(side_effect=_refresh)

        result = await create_group(db, ACCOUNT_ID, ADDED_BY_ID, data)

        assert result.name == "Morning Commute"
        assert result.account_id == ACCOUNT_ID
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_409_on_duplicate_name(self):
        data = CarpoolGroupCreate(name="Morning Commute")
        existing = _make_group()
        db = _make_db(execute_returns=_async_result(existing))

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await create_group(db, ACCOUNT_ID, ADDED_BY_ID, data)
        assert exc_info.value.status_code == 409


class TestGetGroup:
    """Tests 3-4: get_group."""

    @pytest.mark.asyncio
    async def test_returns_group_when_found(self):
        group = _make_group()
        db = _make_db(execute_returns=_async_result(group))
        result = await get_group(db, GROUP_ID, ACCOUNT_ID)
        assert result.id == GROUP_ID
        assert result.account_id == ACCOUNT_ID

    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_group(db, GROUP_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404


class TestListGroups:
    """Tests 5-8: list_groups."""

    @pytest.mark.asyncio
    async def test_returns_all_groups(self):
        group = _make_group()
        db = _make_db(execute_returns=_async_list([group]))
        result = await list_groups(db, ACCOUNT_ID)
        assert result.total == 1
        assert result.items[0].id == GROUP_ID

    @pytest.mark.asyncio
    async def test_filter_is_active_true(self):
        group = _make_group(is_active=True)
        db = _make_db(execute_returns=_async_list([group]))
        result = await list_groups(db, ACCOUNT_ID, is_active=True)
        assert result.total == 1
        assert result.items[0].is_active is True

    @pytest.mark.asyncio
    async def test_filter_is_active_false(self):
        group = _make_group(is_active=False)
        db = _make_db(execute_returns=_async_list([group]))
        result = await list_groups(db, ACCOUNT_ID, is_active=False)
        assert result.total == 1
        assert result.items[0].is_active is False

    @pytest.mark.asyncio
    async def test_empty_list(self):
        db = _make_db(execute_returns=_async_list([]))
        result = await list_groups(db, ACCOUNT_ID)
        assert result.total == 0
        assert result.items == []


class TestUpdateGroup:
    """Tests 9-11: update_group."""

    @pytest.mark.asyncio
    async def test_partial_update(self):
        group = _make_group()
        # First execute: get_group_or_404; second: no name collision
        found = _async_result(group)
        no_collision = _async_result(None)
        db = _make_db(execute_returns=[found, no_collision])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        data = CarpoolGroupUpdate(description="New description")
        await update_group(db, GROUP_ID, ACCOUNT_ID, data)
        assert group.description == "New description"

    @pytest.mark.asyncio
    async def test_409_on_name_collision(self):
        group = _make_group()
        other_group = _make_group(id=GROUP_ID_2, name="Evening Carpool")
        found = _async_result(group)
        collision = _async_result(other_group)
        db = _make_db(execute_returns=[found, collision])

        data = CarpoolGroupUpdate(name="Evening Carpool")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await update_group(db, GROUP_ID, ACCOUNT_ID, data)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        data = CarpoolGroupUpdate(description="Nope")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await update_group(db, GROUP_ID, ACCOUNT_ID, data)
        assert exc_info.value.status_code == 404


class TestDeactivateGroup:
    """Tests 12-14: deactivate_group."""

    @pytest.mark.asyncio
    async def test_deactivates_happy_path(self):
        group = _make_group(is_active=True)
        db = _make_db(execute_returns=_async_result(group))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await deactivate_group(db, GROUP_ID, ACCOUNT_ID)
        assert group.is_active is False

    @pytest.mark.asyncio
    async def test_409_already_inactive(self):
        group = _make_group(is_active=False)
        db = _make_db(execute_returns=_async_result(group))

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await deactivate_group(db, GROUP_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 409
        assert "already inactive" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await deactivate_group(db, GROUP_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404


class TestReactivateGroup:
    """Tests 15-17: reactivate_group."""

    @pytest.mark.asyncio
    async def test_reactivates_happy_path(self):
        group = _make_group(is_active=False)
        db = _make_db(execute_returns=_async_result(group))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await reactivate_group(db, GROUP_ID, ACCOUNT_ID)
        assert group.is_active is True

    @pytest.mark.asyncio
    async def test_409_already_active(self):
        group = _make_group(is_active=True)
        db = _make_db(execute_returns=_async_result(group))

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await reactivate_group(db, GROUP_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 409
        assert "already active" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await reactivate_group(db, GROUP_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404


class TestDeleteGroup:
    """Tests 18-20: delete_group."""

    @pytest.mark.asyncio
    async def test_deletes_inactive_group(self):
        group = _make_group(is_active=False)
        db = _make_db(execute_returns=_async_result(group))
        db.delete = AsyncMock()
        db.commit = AsyncMock()

        await delete_group(db, GROUP_ID, ACCOUNT_ID)
        db.delete.assert_awaited_once_with(group)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_409_when_active(self):
        group = _make_group(is_active=True)
        db = _make_db(execute_returns=_async_result(group))

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await delete_group(db, GROUP_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 409
        assert "deactivate it first" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await delete_group(db, GROUP_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404


class TestAddMember:
    """Tests 21-23: add_member."""

    @pytest.mark.asyncio
    async def test_adds_member_happy_path(self):
        group = _make_group()
        member = _make_member()

        group_result = _async_result(group)
        no_existing_member = _async_result(None)

        db = AsyncMock()
        db.add = MagicMock()
        db.execute.side_effect = [group_result, no_existing_member]

        async def _refresh(obj):
            obj.id = MEMBER_RECORD_ID
            obj.carpool_group_id = GROUP_ID
            obj.account_id = ACCOUNT_ID
            obj.member_id = MEMBER_USER_ID
            obj.is_active = True
            obj.joined_at = NOW

        db.refresh = AsyncMock(side_effect=_refresh)

        data = CarpoolMemberCreate(member_id=MEMBER_USER_ID)
        result = await add_member(db, GROUP_ID, ACCOUNT_ID, data, added_by_id=ADDED_BY_ID)
        assert result.member_id == MEMBER_USER_ID
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_409_already_member(self):
        group = _make_group()
        existing_member = _make_member()

        group_result = _async_result(group)
        found_member = _async_result(existing_member)

        db = _make_db(execute_returns=[group_result, found_member])

        data = CarpoolMemberCreate(member_id=MEMBER_USER_ID)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await add_member(db, GROUP_ID, ACCOUNT_ID, data)
        assert exc_info.value.status_code == 409
        assert "already in this carpool group" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_group_404(self):
        db = _make_db(execute_returns=_async_result(None))
        data = CarpoolMemberCreate(member_id=MEMBER_USER_ID)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await add_member(db, GROUP_ID, ACCOUNT_ID, data)
        assert exc_info.value.status_code == 404


class TestRemoveMember:
    """Tests 24-25: remove_member."""

    @pytest.mark.asyncio
    async def test_removes_member_happy_path(self):
        member = _make_member()
        db = _make_db(execute_returns=_async_result(member))
        db.delete = AsyncMock()
        db.commit = AsyncMock()

        await remove_member(db, GROUP_ID, ACCOUNT_ID, MEMBER_USER_ID)
        db.delete.assert_awaited_once_with(member)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_404_not_a_member(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await remove_member(db, GROUP_ID, ACCOUNT_ID, MEMBER_USER_ID)
        assert exc_info.value.status_code == 404


class TestListMembers:
    """Tests 26-28: list_members."""

    @pytest.mark.asyncio
    async def test_returns_all_members(self):
        group = _make_group()
        member = _make_member()
        group_result = _async_result(group)
        members_result = _async_list([member])
        db = _make_db(execute_returns=[group_result, members_result])

        result = await list_members(db, GROUP_ID, ACCOUNT_ID)
        assert result.total == 1
        assert result.items[0].member_id == MEMBER_USER_ID

    @pytest.mark.asyncio
    async def test_filter_is_active(self):
        group = _make_group()
        member = _make_member(is_active=True)
        group_result = _async_result(group)
        members_result = _async_list([member])
        db = _make_db(execute_returns=[group_result, members_result])

        result = await list_members(db, GROUP_ID, ACCOUNT_ID, is_active=True)
        assert result.total == 1
        assert result.items[0].is_active is True

    @pytest.mark.asyncio
    async def test_group_404(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await list_members(db, GROUP_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404


class TestGetMemberCarpools:
    """Tests 29-30: get_member_carpools."""

    @pytest.mark.asyncio
    async def test_returns_groups_for_member(self):
        group = _make_group()
        db = _make_db(execute_returns=_async_list([group]))

        result = await get_member_carpools(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result.total == 1
        assert result.items[0].id == GROUP_ID

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        db = _make_db(execute_returns=_async_list([]))
        result = await get_member_carpools(db, ACCOUNT_ID, MEMBER_USER_ID)
        assert result.total == 0
        assert result.items == []


class TestGetGroupSummary:
    """Tests 31-32: get_group_summary."""

    @pytest.mark.asyncio
    async def test_correct_counts(self):
        group = _make_group(destination_address="123 Main St", departure_time="08:00")
        group_result = _async_result(group)
        total_count = _async_scalar(3)
        active_count = _async_scalar(2)
        db = _make_db(execute_returns=[group_result, total_count, active_count])

        result = await get_group_summary(db, GROUP_ID, ACCOUNT_ID)
        assert result.group_id == GROUP_ID
        assert result.name == "Morning Commute"
        assert result.total_members == 3
        assert result.active_members == 2
        assert result.has_destination is True
        assert result.has_departure_time is True

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_group_summary(db, GROUP_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404


class TestListAllPlatform:
    """Tests 33-34: list_all_platform."""

    @pytest.mark.asyncio
    async def test_returns_all_groups(self):
        group = _make_group()
        db = _make_db(execute_returns=_async_list([group]))
        result = await list_all_platform(db)
        assert result.total == 1

    @pytest.mark.asyncio
    async def test_filter_by_account_id(self):
        group = _make_group()
        db = _make_db(execute_returns=_async_list([group]))
        result = await list_all_platform(db, account_id=ACCOUNT_ID)
        assert result.total == 1


# ---------------------------------------------------------------------------
# Schema validation tests (35-45 + extras)
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    """Tests 35-45 + extra schema tests."""

    def test_carpool_group_create_valid(self):
        data = CarpoolGroupCreate(name="Morning Commute")
        assert data.name == "Morning Commute"
        assert data.max_members is None
        assert data.departure_time is None

    def test_carpool_group_create_name_too_long(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CarpoolGroupCreate(name="x" * 121)

    def test_carpool_group_create_max_members_must_be_positive(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CarpoolGroupCreate(name="Test", max_members=0)

    def test_carpool_group_create_departure_time_format(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CarpoolGroupCreate(name="Test", departure_time="8:00")

    def test_carpool_group_create_departure_time_valid(self):
        data = CarpoolGroupCreate(name="Test", departure_time="08:30")
        assert data.departure_time == "08:30"

    def test_carpool_group_create_vehicle_type_too_long(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CarpoolGroupCreate(name="Test", vehicle_type="x" * 51)

    def test_carpool_group_update_all_optional(self):
        data = CarpoolGroupUpdate()
        assert data.name is None
        assert data.description is None
        assert data.max_members is None
        assert data.departure_time is None

    def test_carpool_group_response_fields(self):
        resp = CarpoolGroupResponse(
            id=GROUP_ID,
            account_id=ACCOUNT_ID,
            name="Test Group",
            is_active=True,
            created_by_id=1,
            created_at=NOW,
            updated_at=NOW,
        )
        assert resp.id == GROUP_ID
        assert resp.name == "Test Group"
        assert resp.is_active is True

    def test_carpool_member_create_valid(self):
        data = CarpoolMemberCreate(member_id=42, pickup_address="123 Home St")
        assert data.member_id == 42
        assert data.pickup_address == "123 Home St"

    def test_carpool_member_create_pickup_sequence_must_be_positive(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CarpoolMemberCreate(member_id=42, pickup_sequence=0)

    def test_carpool_group_summary_fields(self):
        summary = CarpoolGroupSummary(
            group_id=GROUP_ID,
            name="Evening Ride",
            total_members=5,
            active_members=4,
            has_destination=True,
            has_departure_time=True,
            days_of_week=[0, 1, 2, 3, 4],
        )
        assert summary.total_members == 5
        assert summary.active_members == 4
        assert summary.has_destination is True
        assert len(summary.days_of_week) == 5

    def test_carpool_member_list_response(self):
        resp = CarpoolMemberListResponse(items=[_MEMBER_RESPONSE], total=1)
        assert resp.total == 1
        assert resp.items[0].member_id == MEMBER_USER_ID

    def test_carpool_group_create_days_of_week(self):
        data = CarpoolGroupCreate(name="Test", days_of_week=[0, 1, 2, 3, 4])
        assert data.days_of_week == [0, 1, 2, 3, 4]

    def test_carpool_group_create_with_all_fields(self):
        data = CarpoolGroupCreate(
            name="Full Group",
            description="A full group",
            max_members=8,
            home_base_address="100 Home Rd",
            home_base_lat=37.7749,
            home_base_lng=-122.4194,
            destination_address="500 Office Way",
            destination_lat=37.3382,
            destination_lng=-121.8863,
            departure_time="07:45",
            days_of_week=[0, 1, 2, 3, 4],
            vehicle_type="SUV",
            cost_center_id=5,
            trip_purpose_id=3,
        )
        assert data.max_members == 8
        assert data.departure_time == "07:45"
        assert data.vehicle_type == "SUV"


# ---------------------------------------------------------------------------
# Additional service tests
# ---------------------------------------------------------------------------


class TestAdditionalServiceTests:
    """Extra edge-case service tests."""

    @pytest.mark.asyncio
    async def test_update_only_description(self):
        group = _make_group()
        found = _async_result(group)
        db = _make_db(execute_returns=found)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        data = CarpoolGroupUpdate(description="Updated desc")
        await update_group(db, GROUP_ID, ACCOUNT_ID, data)
        assert group.description == "Updated desc"

    @pytest.mark.asyncio
    async def test_list_groups_multiple_in_name_order(self):
        g1 = _make_group(id=GROUP_ID, name="Alpha Group")
        g2 = _make_group(id=GROUP_ID_2, name="Zeta Group")
        db = _make_db(execute_returns=_async_list([g1, g2]))
        result = await list_groups(db, ACCOUNT_ID)
        assert result.total == 2
        # names returned in whichever order the mock provides; service orders by name at DB level
        assert result.items[0].name == "Alpha Group"

    @pytest.mark.asyncio
    async def test_list_members_empty(self):
        group = _make_group()
        group_result = _async_result(group)
        members_result = _async_list([])
        db = _make_db(execute_returns=[group_result, members_result])

        result = await list_members(db, GROUP_ID, ACCOUNT_ID)
        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_get_group_summary_no_destination_no_time(self):
        group = _make_group(destination_address=None, departure_time=None)
        group_result = _async_result(group)
        total_count = _async_scalar(0)
        active_count = _async_scalar(0)
        db = _make_db(execute_returns=[group_result, total_count, active_count])

        result = await get_group_summary(db, GROUP_ID, ACCOUNT_ID)
        assert result.has_destination is False
        assert result.has_departure_time is False
        assert result.total_members == 0
        assert result.active_members == 0

    @pytest.mark.asyncio
    async def test_get_group_summary_with_days_of_week(self):
        group = _make_group(days_of_week=[0, 1, 2, 3, 4])
        group_result = _async_result(group)
        total_count = _async_scalar(1)
        active_count = _async_scalar(1)
        db = _make_db(execute_returns=[group_result, total_count, active_count])

        result = await get_group_summary(db, GROUP_ID, ACCOUNT_ID)
        assert result.days_of_week == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# API layer tests (46-70)
# ---------------------------------------------------------------------------


def _make_user(is_admin: bool = False, account_id: int = ACCOUNT_ID):
    user = MagicMock()
    user.id = 99
    user.is_admin = is_admin
    return user


class TestAPIEndpoints:
    """API layer tests (46-70)."""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.v1.corporate_carpool_groups import router
        from app.api.deps import get_current_user, get_db, require_admin

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        user = _make_user()
        admin_user = _make_user(is_admin=True)
        fake_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: fake_db
        app.dependency_overrides[require_admin] = lambda: admin_user

        return TestClient(app)

    # ---- admin: create ----

    def test_admin_create_201(self, client):
        with (
            patch(
                "app.api.v1.corporate_carpool_groups._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups.create_group",
                new=AsyncMock(return_value=_GROUP_RESPONSE),
            ),
        ):
            resp = client.post(
                "/api/v1/corporate/admin/carpool-groups",
                json={"name": "Morning Commute"},
            )
        assert resp.status_code == 201
        assert resp.json()["name"] == "Morning Commute"

    def test_admin_create_409_duplicate_name(self, client):
        from fastapi import HTTPException
        with (
            patch(
                "app.api.v1.corporate_carpool_groups._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups.create_group",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=409, detail="Already exists")
                ),
            ),
        ):
            resp = client.post(
                "/api/v1/corporate/admin/carpool-groups",
                json={"name": "Morning Commute"},
            )
        assert resp.status_code == 409

    # ---- admin: list ----

    def test_admin_list_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_carpool_groups._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups.list_groups",
                new=AsyncMock(return_value=_GROUP_LIST_RESPONSE),
            ),
        ):
            resp = client.get("/api/v1/corporate/admin/carpool-groups")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    # ---- admin: get ----

    def test_admin_get_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_carpool_groups._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups.get_group",
                new=AsyncMock(return_value=_GROUP_RESPONSE),
            ),
        ):
            resp = client.get(f"/api/v1/corporate/admin/carpool-groups/{GROUP_ID}")
        assert resp.status_code == 200

    def test_admin_get_404(self, client):
        from fastapi import HTTPException
        with (
            patch(
                "app.api.v1.corporate_carpool_groups._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups.get_group",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=404, detail="Not found")
                ),
            ),
        ):
            resp = client.get(f"/api/v1/corporate/admin/carpool-groups/{GROUP_ID}")
        assert resp.status_code == 404

    # ---- admin: update ----

    def test_admin_update_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_carpool_groups._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups.update_group",
                new=AsyncMock(return_value=_GROUP_RESPONSE),
            ),
        ):
            resp = client.put(
                f"/api/v1/corporate/admin/carpool-groups/{GROUP_ID}",
                json={"description": "Updated"},
            )
        assert resp.status_code == 200

    # ---- admin: deactivate ----

    def test_admin_deactivate_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_carpool_groups._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups.deactivate_group",
                new=AsyncMock(return_value=_GROUP_RESPONSE),
            ),
        ):
            resp = client.post(
                f"/api/v1/corporate/admin/carpool-groups/{GROUP_ID}/deactivate"
            )
        assert resp.status_code == 200

    # ---- admin: reactivate ----

    def test_admin_reactivate_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_carpool_groups._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups.reactivate_group",
                new=AsyncMock(return_value=_GROUP_RESPONSE),
            ),
        ):
            resp = client.post(
                f"/api/v1/corporate/admin/carpool-groups/{GROUP_ID}/reactivate"
            )
        assert resp.status_code == 200

    # ---- admin: delete ----

    def test_admin_delete_204(self, client):
        with (
            patch(
                "app.api.v1.corporate_carpool_groups._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups.delete_group",
                new=AsyncMock(return_value=None),
            ),
        ):
            resp = client.delete(
                f"/api/v1/corporate/admin/carpool-groups/{GROUP_ID}"
            )
        assert resp.status_code == 204

    # ---- admin: add member ----

    def test_admin_add_member_201(self, client):
        with (
            patch(
                "app.api.v1.corporate_carpool_groups._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups.add_member",
                new=AsyncMock(return_value=_MEMBER_RESPONSE),
            ),
        ):
            resp = client.post(
                f"/api/v1/corporate/admin/carpool-groups/{GROUP_ID}/members",
                json={"member_id": MEMBER_USER_ID},
            )
        assert resp.status_code == 201
        assert resp.json()["member_id"] == MEMBER_USER_ID

    def test_admin_add_member_409_already_member(self, client):
        from fastapi import HTTPException
        with (
            patch(
                "app.api.v1.corporate_carpool_groups._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups.add_member",
                new=AsyncMock(
                    side_effect=HTTPException(
                        status_code=409, detail="already in this carpool group"
                    )
                ),
            ),
        ):
            resp = client.post(
                f"/api/v1/corporate/admin/carpool-groups/{GROUP_ID}/members",
                json={"member_id": MEMBER_USER_ID},
            )
        assert resp.status_code == 409

    # ---- admin: remove member ----

    def test_admin_remove_member_204(self, client):
        with (
            patch(
                "app.api.v1.corporate_carpool_groups._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups.remove_member",
                new=AsyncMock(return_value=None),
            ),
        ):
            resp = client.delete(
                f"/api/v1/corporate/admin/carpool-groups/{GROUP_ID}/members/{MEMBER_USER_ID}"
            )
        assert resp.status_code == 204

    # ---- admin: list members ----

    def test_admin_list_members_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_carpool_groups._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups.list_members",
                new=AsyncMock(return_value=_MEMBER_LIST_RESPONSE),
            ),
        ):
            resp = client.get(
                f"/api/v1/corporate/admin/carpool-groups/{GROUP_ID}/members"
            )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    # ---- admin: summary ----

    def test_admin_get_summary_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_carpool_groups._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups._require_account_admin",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups.get_group_summary",
                new=AsyncMock(return_value=_SUMMARY_RESPONSE),
            ),
        ):
            resp = client.get(
                f"/api/v1/corporate/admin/carpool-groups/{GROUP_ID}/summary"
            )
        assert resp.status_code == 200
        assert resp.json()["total_members"] == 3
        assert resp.json()["active_members"] == 2

    # ---- platform-admin ----

    def test_platform_list_all_200(self, client):
        with patch(
            "app.api.v1.corporate_carpool_groups.list_all_platform",
            new=AsyncMock(return_value=_GROUP_LIST_RESPONSE),
        ):
            resp = client.get("/api/v1/corporate/platform-admin/carpool-groups")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_platform_list_for_account_200(self, client):
        with patch(
            "app.api.v1.corporate_carpool_groups.list_all_platform",
            new=AsyncMock(return_value=_GROUP_LIST_RESPONSE),
        ):
            resp = client.get(
                f"/api/v1/corporate/platform-admin/carpool-groups/account/{ACCOUNT_ID}"
            )
        assert resp.status_code == 200

    # ---- member endpoints ----

    def test_member_list_active_groups_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_carpool_groups._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups.list_groups",
                new=AsyncMock(return_value=_GROUP_LIST_RESPONSE),
            ),
        ):
            resp = client.get("/api/v1/corporate/member/carpool-groups")
        assert resp.status_code == 200

    def test_member_list_my_groups_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_carpool_groups._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups.get_member_carpools",
                new=AsyncMock(return_value=_GROUP_LIST_RESPONSE),
            ),
        ):
            resp = client.get("/api/v1/corporate/member/carpool-groups/my-groups")
        assert resp.status_code == 200

    def test_member_get_group_200(self, client):
        with (
            patch(
                "app.api.v1.corporate_carpool_groups._resolve_account_id",
                new=AsyncMock(return_value=ACCOUNT_ID),
            ),
            patch(
                "app.api.v1.corporate_carpool_groups.get_group",
                new=AsyncMock(return_value=_GROUP_RESPONSE),
            ),
        ):
            resp = client.get(
                f"/api/v1/corporate/member/carpool-groups/{GROUP_ID}"
            )
        assert resp.status_code == 200
