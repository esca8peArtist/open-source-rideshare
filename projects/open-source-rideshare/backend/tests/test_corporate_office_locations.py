"""Tests for the Corporate Office Location & Membership feature.

Service layer (async, mocked DB):
  1.  create_office — creates active office with defaults
  2.  create_office — sets created_by_id from caller
  3.  create_office — 409 on duplicate name within account
  4.  create_office — sets is_headquarters and clears old HQ
  5.  get_office — returns office when found
  6.  get_office — 404 when not found
  7.  get_office — 404 when office belongs to different account
  8.  list_offices — returns all offices sorted by name
  9.  list_offices — filter is_active=True returns only active
  10. list_offices — filter is_active=False returns only inactive
  11. list_offices — filter is_headquarters=True returns only HQ
  12. update_office — partial update writes only supplied fields
  13. update_office — 404 when not found
  14. update_office — 409 on name collision with different office
  15. update_office — clears old HQ when is_headquarters=True set
  16. deactivate_office — sets is_active=False
  17. deactivate_office — 404 when not found
  18. deactivate_office — 409 when already inactive
  19. reactivate_office — sets is_active=True
  20. reactivate_office — 404 when not found
  21. reactivate_office — 409 when already active
  22. delete_office — hard-deletes inactive office
  23. delete_office — 404 when not found
  24. delete_office — 409 when active
  25. assign_member — creates membership record
  26. assign_member — 404 when office not found
  27. assign_member — 409 when member already assigned
  28. assign_member — clears existing primary when is_primary=True
  29. remove_member — deletes membership
  30. remove_member — 404 when membership not found
  31. list_office_members — returns memberships for office
  32. list_office_members — filter is_active passed through
  33. list_office_members — 404 when office not found
  34. get_member_offices — returns all offices for a member
  35. get_member_offices — filter is_primary=True returns primary only
  36. get_office_summary — returns office with member counts
  37. get_office_summary — 404 when office not found
  38. list_all_platform — returns all offices without filter
  39. list_all_platform — filters by account_id

Schema validation:
  40. OfficeLocationCreate — valid data accepted
  41. OfficeLocationCreate — blank name rejected
  42. OfficeLocationCreate — blank address_line1 rejected
  43. OfficeLocationCreate — blank city rejected
  44. OfficeLocationCreate — blank state rejected
  45. OfficeLocationCreate — blank postal_code rejected
  46. OfficeLocationCreate — country defaults to "US"
  47. OfficeLocationUpdate — all fields optional
  48. OfficeLocationUpdate — blank name rejected when supplied
  49. OfficeLocationResponse — from_attributes construction
  50. OfficeMembershipResponse — from_attributes construction
  51. OfficeSummaryResponse — has office + total + active fields

API layer (service functions patched):
  52. GET list offices — 200 member gets list
  53. GET list offices — 404 when not in account
  54. GET my-office — 200 member gets primary office
  55. GET my-office — 404 when no primary office assigned
  56. GET {office_id} — 200 member gets specific office
  57. GET {office_id} — 404 when not found
  58. POST create — 201 admin creates office
  59. POST create — 403 non-admin cannot create
  60. POST create — 409 on duplicate name
  61. PUT update — 200 admin updates office
  62. PUT update — 403 non-admin cannot update
  63. POST deactivate — 200 admin deactivates
  64. POST deactivate — 409 when already inactive
  65. POST reactivate — 200 admin reactivates
  66. DELETE office — 204 admin deletes inactive office
  67. DELETE office — 409 when active
  68. POST assign member — 201 admin assigns member
  69. POST assign member — 409 when duplicate
  70. DELETE member — 204 admin removes member
  71. GET members — 200 admin lists members
  72. GET summary — 200 admin gets office summary
  73. GET platform all — 200 platform-admin list all
  74. GET platform for-account — 200 platform-admin list for account
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.corporate_office_location import (
    CorporateOfficeLocation,
    CorporateOfficeMembership,
)
from app.schemas.corporate_office_location import (
    AssignMemberRequest,
    OfficeLocationCreate,
    OfficeLocationListResponse,
    OfficeLocationResponse,
    OfficeLocationUpdate,
    OfficeMembershipListResponse,
    OfficeMembershipResponse,
    OfficeSummaryResponse,
)
from app.services.corporate_office_location import (
    assign_member,
    create_office,
    deactivate_office,
    delete_office,
    get_member_offices,
    get_office,
    get_office_summary,
    list_all_platform,
    list_office_members,
    list_offices,
    reactivate_office,
    remove_member,
    update_office,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 16, 0, 0, 0, tzinfo=timezone.utc)

ACCOUNT_ID = 10
MEMBER_ID = 20
ADMIN_ID = 21
OFFICE_ID = uuid.uuid4()
MEMBERSHIP_ID = uuid.uuid4()
OTHER_OFFICE_ID = uuid.uuid4()


def _make_office(
    id: uuid.UUID = OFFICE_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Main Office",
    description: str | None = "Our headquarters",
    address_line1: str = "123 Main St",
    address_line2: str | None = None,
    city: str = "Springfield",
    state: str = "IL",
    postal_code: str = "62701",
    country: str = "US",
    latitude=None,
    longitude=None,
    default_cost_center_id: int | None = None,
    is_headquarters: bool = False,
    is_active: bool = True,
    created_by_id: int | None = ADMIN_ID,
) -> CorporateOfficeLocation:
    office = CorporateOfficeLocation()
    office.id = id
    office.account_id = account_id
    office.name = name
    office.description = description
    office.address_line1 = address_line1
    office.address_line2 = address_line2
    office.city = city
    office.state = state
    office.postal_code = postal_code
    office.country = country
    office.latitude = latitude
    office.longitude = longitude
    office.default_cost_center_id = default_cost_center_id
    office.is_headquarters = is_headquarters
    office.is_active = is_active
    office.created_by_id = created_by_id
    office.created_at = NOW
    office.updated_at = NOW
    return office


def _make_hq_office(**kwargs) -> CorporateOfficeLocation:
    return _make_office(is_headquarters=True, **kwargs)


def _make_inactive_office(**kwargs) -> CorporateOfficeLocation:
    return _make_office(is_active=False, **kwargs)


def _make_membership(
    id: uuid.UUID = MEMBERSHIP_ID,
    office_id: uuid.UUID = OFFICE_ID,
    member_id: int = MEMBER_ID,
    account_id: int = ACCOUNT_ID,
    is_primary: bool = False,
    assigned_by_id: int | None = ADMIN_ID,
    notes: str | None = None,
    is_active: bool = True,
) -> CorporateOfficeMembership:
    m = CorporateOfficeMembership()
    m.id = id
    m.office_id = office_id
    m.member_id = member_id
    m.account_id = account_id
    m.is_primary = is_primary
    m.assigned_by_id = assigned_by_id
    m.notes = notes
    m.is_active = is_active
    m.created_at = NOW
    return m


def _make_office_response(office: CorporateOfficeLocation) -> OfficeLocationResponse:
    return OfficeLocationResponse(
        id=office.id,
        account_id=office.account_id,
        name=office.name,
        description=office.description,
        address_line1=office.address_line1,
        address_line2=office.address_line2,
        city=office.city,
        state=office.state,
        postal_code=office.postal_code,
        country=office.country,
        latitude=None,
        longitude=None,
        default_cost_center_id=office.default_cost_center_id,
        is_headquarters=office.is_headquarters,
        is_active=office.is_active,
        created_by_id=office.created_by_id,
        created_at=office.created_at,
        updated_at=office.updated_at,
    )


def _make_membership_response(m: CorporateOfficeMembership) -> OfficeMembershipResponse:
    return OfficeMembershipResponse(
        id=m.id,
        office_id=m.office_id,
        member_id=m.member_id,
        account_id=m.account_id,
        is_primary=m.is_primary,
        assigned_by_id=m.assigned_by_id,
        notes=m.notes,
        is_active=m.is_active,
        created_at=m.created_at,
    )


def _db_returning(row):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute.return_value = result
    return db


def _db_returning_all(rows):
    db = AsyncMock()
    result = MagicMock()
    scalar_result = MagicMock()
    scalar_result.all.return_value = rows
    result.scalars.return_value = scalar_result
    db.execute.return_value = result
    return db


def _db_multi(*responses):
    """Return a db mock that cycles through multiple execute() return values."""
    db = AsyncMock()
    results = []
    for r in responses:
        mock_result = MagicMock()
        if isinstance(r, list):
            scalar_res = MagicMock()
            scalar_res.all.return_value = r
            mock_result.scalars.return_value = scalar_res
        else:
            mock_result.scalar_one_or_none.return_value = r
        results.append(mock_result)
    db.execute.side_effect = results
    return db


# ---------------------------------------------------------------------------
# Service layer tests — create_office
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_office_creates_active_office():
    """create_office creates a new office with is_active=True."""
    db = AsyncMock()
    db.add = MagicMock()

    async def _refresh(obj):
        obj.id = OFFICE_ID
        obj.created_at = NOW
        obj.updated_at = NOW

    db.refresh = AsyncMock(side_effect=_refresh)

    # First execute: check for duplicate name (returns None)
    # Second execute: check for existing HQ (not called unless is_headquarters=True)
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    db.execute.return_value = result_mock

    data = OfficeLocationCreate(
        name="Main Office",
        address_line1="123 Main St",
        city="Springfield",
        state="IL",
        postal_code="62701",
    )
    result = await create_office(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)

    db.add.assert_called_once()
    db.commit.assert_called_once()
    assert result.is_active is True


@pytest.mark.asyncio
async def test_create_office_sets_created_by_id():
    """create_office stores the created_by_id on the new record."""
    db = AsyncMock()
    captured = {}

    def _capture(obj):
        captured["office"] = obj

    db.add = MagicMock(side_effect=_capture)

    async def _refresh(obj):
        obj.id = OFFICE_ID
        obj.created_at = NOW
        obj.updated_at = NOW

    db.refresh = AsyncMock(side_effect=_refresh)

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    db.execute.return_value = result_mock

    data = OfficeLocationCreate(
        name="Branch",
        address_line1="456 Elm St",
        city="Shelbyville",
        state="IL",
        postal_code="62565",
    )
    await create_office(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)
    assert captured["office"].created_by_id == ADMIN_ID


@pytest.mark.asyncio
async def test_create_office_409_on_duplicate_name():
    """create_office raises 409 when an office with the same name exists."""
    from fastapi import HTTPException

    existing = _make_office()
    db = _db_returning(existing)

    data = OfficeLocationCreate(
        name="Main Office",
        address_line1="123 Main St",
        city="Springfield",
        state="IL",
        postal_code="62701",
    )
    with pytest.raises(HTTPException) as exc:
        await create_office(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_office_clears_old_hq_when_is_hq():
    """create_office clears the old HQ flag when is_headquarters=True."""
    old_hq = _make_hq_office(id=OTHER_OFFICE_ID)
    new_office_id = uuid.uuid4()

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # Duplicate name check — no match
            result.scalar_one_or_none.return_value = None
        else:
            # Clear HQ check — returns old HQ
            result.scalar_one_or_none.return_value = old_hq
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect
    db.add = MagicMock()

    async def _refresh(obj):
        obj.id = new_office_id
        obj.created_at = NOW
        obj.updated_at = NOW

    db.refresh = AsyncMock(side_effect=_refresh)

    data = OfficeLocationCreate(
        name="New HQ",
        address_line1="1 HQ Blvd",
        city="Springfield",
        state="IL",
        postal_code="62701",
        is_headquarters=True,
    )
    await create_office(db, ACCOUNT_ID, data)
    assert old_hq.is_headquarters is False


# ---------------------------------------------------------------------------
# Service layer tests — get_office
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_office_returns_office_when_found():
    """get_office returns the office response when found."""
    office = _make_office()
    db = _db_returning(office)
    result = await get_office(db, OFFICE_ID, ACCOUNT_ID)
    assert result.id == OFFICE_ID
    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_get_office_raises_404_when_not_found():
    """get_office raises HTTP 404 when office is not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await get_office(db, OFFICE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_office_404_for_different_account():
    """get_office raises 404 when office belongs to a different account."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await get_office(db, OFFICE_ID, account_id=999)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests — list_offices
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_offices_returns_all():
    """list_offices returns all offices for the account."""
    offices = [_make_office(id=uuid.uuid4(), name="A"), _make_office(id=uuid.uuid4(), name="B")]
    db = _db_returning_all(offices)
    result = await list_offices(db, ACCOUNT_ID)
    assert result.total == 2
    assert len(result.items) == 2


@pytest.mark.asyncio
async def test_list_offices_filter_active():
    """list_offices with is_active=True returns only active offices."""
    active = _make_office()
    db = _db_returning_all([active])
    result = await list_offices(db, ACCOUNT_ID, is_active=True)
    assert result.total == 1
    assert result.items[0].is_active is True


@pytest.mark.asyncio
async def test_list_offices_filter_inactive():
    """list_offices with is_active=False returns only inactive offices."""
    inactive = _make_inactive_office()
    db = _db_returning_all([inactive])
    result = await list_offices(db, ACCOUNT_ID, is_active=False)
    assert result.total == 1
    assert result.items[0].is_active is False


@pytest.mark.asyncio
async def test_list_offices_filter_hq():
    """list_offices with is_headquarters=True returns only HQ offices."""
    hq = _make_hq_office()
    db = _db_returning_all([hq])
    result = await list_offices(db, ACCOUNT_ID, is_headquarters=True)
    assert result.total == 1
    assert result.items[0].is_headquarters is True


# ---------------------------------------------------------------------------
# Service layer tests — update_office
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_office_partial_update():
    """update_office writes only supplied fields."""
    office = _make_office(name="Old Name")

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = office
        else:
            # Name collision check
            result.scalar_one_or_none.return_value = None
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    data = OfficeLocationUpdate(name="New Name")
    await update_office(db, OFFICE_ID, ACCOUNT_ID, data)
    assert office.name == "New Name"
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_office_404_when_not_found():
    """update_office raises 404 when office not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    data = OfficeLocationUpdate(name="New Name")
    with pytest.raises(HTTPException) as exc:
        await update_office(db, OFFICE_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_office_409_on_name_collision():
    """update_office raises 409 when new name collides with another office."""
    from fastapi import HTTPException

    office = _make_office(name="Office A")
    other = _make_office(id=OTHER_OFFICE_ID, name="Office B")

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = office
        else:
            result.scalar_one_or_none.return_value = other
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    data = OfficeLocationUpdate(name="Office B")
    with pytest.raises(HTTPException) as exc:
        await update_office(db, OFFICE_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_office_clears_old_hq():
    """update_office clears the old HQ when is_headquarters=True is set."""
    office = _make_office(is_headquarters=False)
    old_hq = _make_hq_office(id=OTHER_OFFICE_ID)

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = office
        else:
            # Clear HQ — returns old HQ
            result.scalar_one_or_none.return_value = old_hq
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    data = OfficeLocationUpdate(is_headquarters=True)
    await update_office(db, OFFICE_ID, ACCOUNT_ID, data)
    assert old_hq.is_headquarters is False


# ---------------------------------------------------------------------------
# Service layer tests — deactivate_office
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_office_sets_inactive():
    """deactivate_office sets is_active=False."""
    office = _make_office(is_active=True)
    db = _db_returning(office)
    await deactivate_office(db, OFFICE_ID, ACCOUNT_ID)
    assert office.is_active is False
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_deactivate_office_404_when_not_found():
    """deactivate_office raises 404 when office not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await deactivate_office(db, OFFICE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_office_409_when_already_inactive():
    """deactivate_office raises 409 when office is already inactive."""
    from fastapi import HTTPException

    office = _make_inactive_office()
    db = _db_returning(office)
    with pytest.raises(HTTPException) as exc:
        await deactivate_office(db, OFFICE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — reactivate_office
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reactivate_office_sets_active():
    """reactivate_office sets is_active=True."""
    office = _make_inactive_office()
    db = _db_returning(office)
    await reactivate_office(db, OFFICE_ID, ACCOUNT_ID)
    assert office.is_active is True
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_reactivate_office_404_when_not_found():
    """reactivate_office raises 404 when office not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await reactivate_office(db, OFFICE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_reactivate_office_409_when_already_active():
    """reactivate_office raises 409 when office is already active."""
    from fastapi import HTTPException

    office = _make_office(is_active=True)
    db = _db_returning(office)
    with pytest.raises(HTTPException) as exc:
        await reactivate_office(db, OFFICE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — delete_office
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_office_deletes_inactive():
    """delete_office hard-deletes an inactive office."""
    office = _make_inactive_office()
    db = _db_returning(office)
    await delete_office(db, OFFICE_ID, ACCOUNT_ID)
    db.delete.assert_called_once_with(office)
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_office_404_when_not_found():
    """delete_office raises 404 when office not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await delete_office(db, OFFICE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_office_409_when_active():
    """delete_office raises 409 when office is active."""
    from fastapi import HTTPException

    office = _make_office(is_active=True)
    db = _db_returning(office)
    with pytest.raises(HTTPException) as exc:
        await delete_office(db, OFFICE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — assign_member
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_member_creates_membership():
    """assign_member creates a new membership record."""
    office = _make_office()
    membership = _make_membership()

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # get_office check
            result.scalar_one_or_none.return_value = office
        else:
            # duplicate membership check — none
            result.scalar_one_or_none.return_value = None
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect
    db.add = MagicMock()

    async def _refresh(obj):
        obj.id = MEMBERSHIP_ID
        obj.created_at = NOW

    db.refresh = AsyncMock(side_effect=_refresh)

    await assign_member(db, OFFICE_ID, ACCOUNT_ID, MEMBER_ID, False, ADMIN_ID)
    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_assign_member_404_when_office_not_found():
    """assign_member raises 404 when the office is not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await assign_member(db, OFFICE_ID, ACCOUNT_ID, MEMBER_ID, False)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_assign_member_409_when_already_assigned():
    """assign_member raises 409 when member is already assigned to this office."""
    from fastapi import HTTPException

    office = _make_office()
    existing_membership = _make_membership()

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = office
        else:
            result.scalar_one_or_none.return_value = existing_membership
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    with pytest.raises(HTTPException) as exc:
        await assign_member(db, OFFICE_ID, ACCOUNT_ID, MEMBER_ID, False)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_assign_member_clears_existing_primary():
    """assign_member clears the member's existing primary when is_primary=True."""
    office = _make_office()
    old_primary = _make_membership(id=uuid.uuid4(), is_primary=True)

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # get_office
            result.scalar_one_or_none.return_value = office
        elif call_count == 2:
            # duplicate membership check
            result.scalar_one_or_none.return_value = None
        else:
            # clear existing primary
            result.scalar_one_or_none.return_value = old_primary
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect
    db.add = MagicMock()

    async def _refresh(obj):
        obj.id = MEMBERSHIP_ID
        obj.created_at = NOW

    db.refresh = AsyncMock(side_effect=_refresh)

    await assign_member(db, OFFICE_ID, ACCOUNT_ID, MEMBER_ID, is_primary=True)
    assert old_primary.is_primary is False


# ---------------------------------------------------------------------------
# Service layer tests — remove_member
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_member_deletes_membership():
    """remove_member deletes the membership record."""
    office = _make_office()
    membership = _make_membership()

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = office
        else:
            result.scalar_one_or_none.return_value = membership
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    await remove_member(db, OFFICE_ID, ACCOUNT_ID, MEMBER_ID)
    db.delete.assert_called_once_with(membership)
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_remove_member_404_when_not_assigned():
    """remove_member raises 404 when member is not assigned to the office."""
    from fastapi import HTTPException

    office = _make_office()

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = office
        else:
            result.scalar_one_or_none.return_value = None
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    with pytest.raises(HTTPException) as exc:
        await remove_member(db, OFFICE_ID, ACCOUNT_ID, MEMBER_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests — list_office_members
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_office_members_returns_memberships():
    """list_office_members returns memberships for the office."""
    office = _make_office()
    memberships = [_make_membership(), _make_membership(id=uuid.uuid4(), member_id=22)]

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = office
        else:
            scalar_res = MagicMock()
            scalar_res.all.return_value = memberships
            result.scalars.return_value = scalar_res
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    result = await list_office_members(db, OFFICE_ID, ACCOUNT_ID)
    assert result.total == 2


@pytest.mark.asyncio
async def test_list_office_members_filter_is_active():
    """list_office_members passes is_active filter through."""
    office = _make_office()
    active_membership = _make_membership(is_active=True)

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = office
        else:
            scalar_res = MagicMock()
            scalar_res.all.return_value = [active_membership]
            result.scalars.return_value = scalar_res
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    result = await list_office_members(db, OFFICE_ID, ACCOUNT_ID, is_active=True)
    assert result.total == 1
    assert result.items[0].is_active is True


@pytest.mark.asyncio
async def test_list_office_members_404_when_office_not_found():
    """list_office_members raises 404 when office not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await list_office_members(db, OFFICE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests — get_member_offices
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_member_offices_returns_all():
    """get_member_offices returns all memberships for a member."""
    memberships = [
        _make_membership(is_primary=True),
        _make_membership(id=uuid.uuid4(), office_id=OTHER_OFFICE_ID, is_primary=False),
    ]
    db = _db_returning_all(memberships)
    result = await get_member_offices(db, MEMBER_ID, ACCOUNT_ID)
    assert result.total == 2


@pytest.mark.asyncio
async def test_get_member_offices_filter_primary():
    """get_member_offices with is_primary=True returns primary memberships only."""
    primary = _make_membership(is_primary=True)
    db = _db_returning_all([primary])
    result = await get_member_offices(db, MEMBER_ID, ACCOUNT_ID, is_primary=True)
    assert result.total == 1
    assert result.items[0].is_primary is True


# ---------------------------------------------------------------------------
# Service layer tests — get_office_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_office_summary_returns_counts():
    """get_office_summary returns office with total and active member counts."""
    office = _make_office()

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = office
        elif call_count == 2:
            result.scalar.return_value = 5  # total_members
        else:
            result.scalar.return_value = 3  # active_members
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    summary = await get_office_summary(db, OFFICE_ID, ACCOUNT_ID)
    assert summary.total_members == 5
    assert summary.active_members == 3
    assert summary.office.id == OFFICE_ID


@pytest.mark.asyncio
async def test_get_office_summary_404_when_not_found():
    """get_office_summary raises 404 when office not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await get_office_summary(db, OFFICE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests — list_all_platform
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_platform_returns_all():
    """list_all_platform returns all offices without account filter."""
    offices = [
        _make_office(id=uuid.uuid4(), account_id=10),
        _make_office(id=uuid.uuid4(), account_id=20),
    ]
    db = _db_returning_all(offices)
    result = await list_all_platform(db)
    assert result.total == 2


@pytest.mark.asyncio
async def test_list_all_platform_filters_by_account():
    """list_all_platform with account_id filter returns only that account's offices."""
    offices = [_make_office(account_id=10)]
    db = _db_returning_all(offices)
    result = await list_all_platform(db, account_id=10)
    assert result.total == 1
    assert result.items[0].account_id == 10


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_office_create_valid():
    """OfficeLocationCreate accepts valid data."""
    data = OfficeLocationCreate(
        name="HQ",
        address_line1="1 Corp Way",
        city="Chicago",
        state="IL",
        postal_code="60601",
        country="US",
    )
    assert data.name == "HQ"
    assert data.country == "US"
    assert data.is_headquarters is False


def test_office_create_blank_name_rejected():
    """OfficeLocationCreate rejects a blank name."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OfficeLocationCreate(
            name="   ",
            address_line1="1 Corp Way",
            city="Chicago",
            state="IL",
            postal_code="60601",
        )


def test_office_create_blank_address_rejected():
    """OfficeLocationCreate rejects a blank address_line1."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OfficeLocationCreate(
            name="HQ",
            address_line1="  ",
            city="Chicago",
            state="IL",
            postal_code="60601",
        )


def test_office_create_blank_city_rejected():
    """OfficeLocationCreate rejects a blank city."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OfficeLocationCreate(
            name="HQ",
            address_line1="1 Corp Way",
            city="  ",
            state="IL",
            postal_code="60601",
        )


def test_office_create_blank_state_rejected():
    """OfficeLocationCreate rejects a blank state."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OfficeLocationCreate(
            name="HQ",
            address_line1="1 Corp Way",
            city="Chicago",
            state="  ",
            postal_code="60601",
        )


def test_office_create_blank_postal_code_rejected():
    """OfficeLocationCreate rejects a blank postal_code."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OfficeLocationCreate(
            name="HQ",
            address_line1="1 Corp Way",
            city="Chicago",
            state="IL",
            postal_code="  ",
        )


def test_office_create_country_defaults_to_us():
    """OfficeLocationCreate defaults country to 'US'."""
    data = OfficeLocationCreate(
        name="Office",
        address_line1="1 Main St",
        city="Chicago",
        state="IL",
        postal_code="60601",
    )
    assert data.country == "US"


def test_office_update_all_fields_optional():
    """OfficeLocationUpdate accepts empty update (all fields optional)."""
    data = OfficeLocationUpdate()
    assert data.model_dump(exclude_unset=True) == {}


def test_office_update_blank_name_rejected():
    """OfficeLocationUpdate rejects a blank name when supplied."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OfficeLocationUpdate(name="  ")


def test_office_response_from_attributes():
    """OfficeLocationResponse can be constructed from ORM attributes."""
    office = _make_office()
    response = OfficeLocationResponse.model_validate(office)
    assert response.id == OFFICE_ID
    assert response.account_id == ACCOUNT_ID
    assert response.name == "Main Office"


def test_membership_response_from_attributes():
    """OfficeMembershipResponse can be constructed from ORM attributes."""
    m = _make_membership()
    response = OfficeMembershipResponse.model_validate(m)
    assert response.id == MEMBERSHIP_ID
    assert response.office_id == OFFICE_ID
    assert response.member_id == MEMBER_ID


def test_office_summary_response_fields():
    """OfficeSummaryResponse has office, total_members, and active_members."""
    office_resp = _make_office_response(_make_office())
    summary = OfficeSummaryResponse(
        office=office_resp,
        total_members=10,
        active_members=8,
    )
    assert summary.total_members == 10
    assert summary.active_members == 8
    assert summary.office.name == "Main Office"


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

_ROUTER = "app.api.v1.corporate_office_locations"


# --- GET list offices ---


@pytest.mark.asyncio
async def test_api_list_offices_200():
    """GET /corporate/offices returns the list of offices."""
    list_resp = OfficeLocationListResponse(items=[], total=0)

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.list_offices", return_value=list_resp),
    ):
        from app.api.v1.corporate_office_locations import list_my_account_offices

        result = await list_my_account_offices(
            is_active=None, user=MagicMock(id=MEMBER_ID), db=AsyncMock()
        )
    assert result.total == 0


@pytest.mark.asyncio
async def test_api_list_offices_404_no_account():
    """GET /corporate/offices raises 404 when user has no account."""
    from fastapi import HTTPException

    with patch(
        f"{_ROUTER}._resolve_account_id",
        side_effect=HTTPException(status_code=404, detail="no account"),
    ):
        from app.api.v1.corporate_office_locations import list_my_account_offices

        with pytest.raises(HTTPException) as exc:
            await list_my_account_offices(
                is_active=None, user=MagicMock(id=MEMBER_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 404


# --- GET my-office ---


@pytest.mark.asyncio
async def test_api_get_my_office_200():
    """GET /corporate/offices/my-office returns the primary office membership."""
    membership_resp = _make_membership_response(_make_membership(is_primary=True))
    memberships_list = OfficeMembershipListResponse(items=[membership_resp], total=1)

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.get_member_offices", return_value=memberships_list),
    ):
        from app.api.v1.corporate_office_locations import get_my_primary_office

        result = await get_my_primary_office(
            user=MagicMock(id=MEMBER_ID), db=AsyncMock()
        )
    assert result.is_primary is True


@pytest.mark.asyncio
async def test_api_get_my_office_404_when_no_primary():
    """GET /corporate/offices/my-office raises 404 when no primary office."""
    from fastapi import HTTPException

    memberships_list = OfficeMembershipListResponse(items=[], total=0)

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.get_member_offices", return_value=memberships_list),
    ):
        from app.api.v1.corporate_office_locations import get_my_primary_office

        with pytest.raises(HTTPException) as exc:
            await get_my_primary_office(
                user=MagicMock(id=MEMBER_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 404


# --- GET {office_id} ---


@pytest.mark.asyncio
async def test_api_get_office_200():
    """GET /corporate/offices/{office_id} returns the office."""
    office_resp = _make_office_response(_make_office())

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.get_office", return_value=office_resp),
    ):
        from app.api.v1.corporate_office_locations import get_office_endpoint

        result = await get_office_endpoint(
            office_id=OFFICE_ID, user=MagicMock(id=MEMBER_ID), db=AsyncMock()
        )
    assert result.id == OFFICE_ID


@pytest.mark.asyncio
async def test_api_get_office_404():
    """GET /corporate/offices/{office_id} raises 404 when not found."""
    from fastapi import HTTPException

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}.get_office",
            side_effect=HTTPException(status_code=404, detail="not found"),
        ),
    ):
        from app.api.v1.corporate_office_locations import get_office_endpoint

        with pytest.raises(HTTPException) as exc:
            await get_office_endpoint(
                office_id=OFFICE_ID, user=MagicMock(id=MEMBER_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 404


# --- POST create ---


@pytest.mark.asyncio
async def test_api_create_office_201():
    """POST /corporate/offices returns created office."""
    office_resp = _make_office_response(_make_office())
    data = OfficeLocationCreate(
        name="Main Office",
        address_line1="123 Main St",
        city="Springfield",
        state="IL",
        postal_code="62701",
    )
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.create_office", return_value=office_resp),
    ):
        from app.api.v1.corporate_office_locations import create_office_endpoint

        result = await create_office_endpoint(
            data=data, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
    assert result.is_active is True


@pytest.mark.asyncio
async def test_api_create_office_403_non_admin():
    """POST /corporate/offices raises 403 for non-admin."""
    from fastapi import HTTPException

    data = OfficeLocationCreate(
        name="Main Office",
        address_line1="123 Main St",
        city="Springfield",
        state="IL",
        postal_code="62701",
    )
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}._require_account_admin",
            side_effect=HTTPException(status_code=403, detail="Forbidden"),
        ),
    ):
        from app.api.v1.corporate_office_locations import create_office_endpoint

        with pytest.raises(HTTPException) as exc:
            await create_office_endpoint(
                data=data, user=MagicMock(id=MEMBER_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_create_office_409_duplicate_name():
    """POST /corporate/offices raises 409 on duplicate name."""
    from fastapi import HTTPException

    data = OfficeLocationCreate(
        name="Main Office",
        address_line1="123 Main St",
        city="Springfield",
        state="IL",
        postal_code="62701",
    )
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(
            f"{_ROUTER}.create_office",
            side_effect=HTTPException(status_code=409, detail="Duplicate name"),
        ),
    ):
        from app.api.v1.corporate_office_locations import create_office_endpoint

        with pytest.raises(HTTPException) as exc:
            await create_office_endpoint(
                data=data, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 409


# --- PUT update ---


@pytest.mark.asyncio
async def test_api_update_office_200():
    """PUT /corporate/offices/{office_id} returns updated office."""
    office_resp = _make_office_response(_make_office(name="Updated"))
    data = OfficeLocationUpdate(name="Updated")

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.update_office", return_value=office_resp),
    ):
        from app.api.v1.corporate_office_locations import update_office_endpoint

        result = await update_office_endpoint(
            office_id=OFFICE_ID,
            data=data,
            user=MagicMock(id=ADMIN_ID),
            db=AsyncMock(),
        )
    assert result.name == "Updated"


@pytest.mark.asyncio
async def test_api_update_office_403_non_admin():
    """PUT /corporate/offices/{office_id} raises 403 for non-admin."""
    from fastapi import HTTPException

    data = OfficeLocationUpdate(name="Updated")
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}._require_account_admin",
            side_effect=HTTPException(status_code=403, detail="Forbidden"),
        ),
    ):
        from app.api.v1.corporate_office_locations import update_office_endpoint

        with pytest.raises(HTTPException) as exc:
            await update_office_endpoint(
                office_id=OFFICE_ID,
                data=data,
                user=MagicMock(id=MEMBER_ID),
                db=AsyncMock(),
            )
    assert exc.value.status_code == 403


# --- POST deactivate ---


@pytest.mark.asyncio
async def test_api_deactivate_office_200():
    """POST deactivate returns deactivated office."""
    office_resp = _make_office_response(_make_inactive_office())

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.deactivate_office", return_value=office_resp),
    ):
        from app.api.v1.corporate_office_locations import deactivate_office_endpoint

        result = await deactivate_office_endpoint(
            office_id=OFFICE_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
    assert result.is_active is False


@pytest.mark.asyncio
async def test_api_deactivate_office_409_already_inactive():
    """POST deactivate raises 409 when already inactive."""
    from fastapi import HTTPException

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(
            f"{_ROUTER}.deactivate_office",
            side_effect=HTTPException(status_code=409, detail="Already inactive"),
        ),
    ):
        from app.api.v1.corporate_office_locations import deactivate_office_endpoint

        with pytest.raises(HTTPException) as exc:
            await deactivate_office_endpoint(
                office_id=OFFICE_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 409


# --- POST reactivate ---


@pytest.mark.asyncio
async def test_api_reactivate_office_200():
    """POST reactivate returns reactivated office."""
    office_resp = _make_office_response(_make_office(is_active=True))

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.reactivate_office", return_value=office_resp),
    ):
        from app.api.v1.corporate_office_locations import reactivate_office_endpoint

        result = await reactivate_office_endpoint(
            office_id=OFFICE_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
    assert result.is_active is True


# --- DELETE office ---


@pytest.mark.asyncio
async def test_api_delete_office_204():
    """DELETE /corporate/offices/{office_id} completes without raising."""
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.delete_office", return_value=None),
    ):
        from app.api.v1.corporate_office_locations import delete_office_endpoint

        await delete_office_endpoint(
            office_id=OFFICE_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )


@pytest.mark.asyncio
async def test_api_delete_office_409_when_active():
    """DELETE office raises 409 when office is active."""
    from fastapi import HTTPException

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(
            f"{_ROUTER}.delete_office",
            side_effect=HTTPException(status_code=409, detail="Active"),
        ),
    ):
        from app.api.v1.corporate_office_locations import delete_office_endpoint

        with pytest.raises(HTTPException) as exc:
            await delete_office_endpoint(
                office_id=OFFICE_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 409


# --- POST assign member ---


@pytest.mark.asyncio
async def test_api_assign_member_201():
    """POST /members returns created membership."""
    membership_resp = _make_membership_response(_make_membership())
    data = AssignMemberRequest(member_id=MEMBER_ID, is_primary=False)

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.assign_member", return_value=membership_resp),
    ):
        from app.api.v1.corporate_office_locations import assign_member_endpoint

        result = await assign_member_endpoint(
            office_id=OFFICE_ID,
            data=data,
            user=MagicMock(id=ADMIN_ID),
            db=AsyncMock(),
        )
    assert result.member_id == MEMBER_ID


@pytest.mark.asyncio
async def test_api_assign_member_409_duplicate():
    """POST /members raises 409 when member already assigned."""
    from fastapi import HTTPException

    data = AssignMemberRequest(member_id=MEMBER_ID)
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(
            f"{_ROUTER}.assign_member",
            side_effect=HTTPException(status_code=409, detail="Already assigned"),
        ),
    ):
        from app.api.v1.corporate_office_locations import assign_member_endpoint

        with pytest.raises(HTTPException) as exc:
            await assign_member_endpoint(
                office_id=OFFICE_ID,
                data=data,
                user=MagicMock(id=ADMIN_ID),
                db=AsyncMock(),
            )
    assert exc.value.status_code == 409


# --- DELETE remove member ---


@pytest.mark.asyncio
async def test_api_remove_member_204():
    """DELETE /members/{member_id} completes without raising."""
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.remove_member", return_value=None),
    ):
        from app.api.v1.corporate_office_locations import remove_member_endpoint

        await remove_member_endpoint(
            office_id=OFFICE_ID,
            member_id=MEMBER_ID,
            user=MagicMock(id=ADMIN_ID),
            db=AsyncMock(),
        )


# --- GET list members ---


@pytest.mark.asyncio
async def test_api_list_office_members_200():
    """GET /members returns the membership list."""
    list_resp = OfficeMembershipListResponse(items=[], total=0)

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.list_office_members", return_value=list_resp),
    ):
        from app.api.v1.corporate_office_locations import list_office_members_endpoint

        result = await list_office_members_endpoint(
            office_id=OFFICE_ID,
            is_active=None,
            user=MagicMock(id=ADMIN_ID),
            db=AsyncMock(),
        )
    assert result.total == 0


# --- GET office summary ---


@pytest.mark.asyncio
async def test_api_get_office_summary_200():
    """GET /summary returns office summary."""
    office_resp = _make_office_response(_make_office())
    summary = OfficeSummaryResponse(
        office=office_resp, total_members=5, active_members=3
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.get_office_summary", return_value=summary),
    ):
        from app.api.v1.corporate_office_locations import get_office_summary_endpoint

        result = await get_office_summary_endpoint(
            office_id=OFFICE_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
    assert result.total_members == 5
    assert result.active_members == 3


# --- Platform-admin ---


@pytest.mark.asyncio
async def test_api_platform_list_all_offices_200():
    """Platform-admin list-all returns all offices."""
    list_resp = OfficeLocationListResponse(items=[], total=0)

    with patch(f"{_ROUTER}.list_all_platform", return_value=list_resp):
        from app.api.v1.corporate_office_locations import admin_list_all_offices

        result = await admin_list_all_offices(
            account_id=None, _admin=MagicMock(), db=AsyncMock()
        )
    assert result.total == 0


@pytest.mark.asyncio
async def test_api_platform_list_offices_for_account_200():
    """Platform-admin list-for-account returns offices for a specific account."""
    list_resp = OfficeLocationListResponse(items=[], total=0)

    with patch(f"{_ROUTER}.list_offices", return_value=list_resp):
        from app.api.v1.corporate_office_locations import admin_list_offices_for_account

        result = await admin_list_offices_for_account(
            account_id=ACCOUNT_ID,
            is_active=None,
            _admin=MagicMock(),
            db=AsyncMock(),
        )
    assert result.total == 0
