"""Tests for the Corporate Custom Ride Fields feature.

Service tests (async, mocked DB):
  1.  create_custom_field — success, text field
  2.  create_custom_field — non-admin → 403
  3.  create_custom_field — duplicate field_key → 409
  4.  create_custom_field — auto-slugifies label when field_key omitted
  5.  create_custom_field — dropdown with options
  6.  get_custom_field — success
  7.  get_custom_field — wrong account → 404
  8.  list_custom_fields — active_only=True returns only active
  9.  list_custom_fields — active_only=False includes inactive
  10. list_custom_fields — empty list returns total=0
  11. update_custom_field — label updated
  12. update_custom_field — display_order updated
  13. update_custom_field — non-admin → 403
  14. update_custom_field — not found → 404
  15. update_custom_field — dropdown_options on non-dropdown → 422
  16. deactivate_custom_field — success: is_active=False
  17. deactivate_custom_field — already inactive → 409
  18. deactivate_custom_field — non-admin → 403
  19. set_ride_field_value — success (create)
  20. set_ride_field_value — success (update existing)
  21. set_ride_field_value — non-member → 403
  22. set_ride_field_value — inactive field → 404
  23. set_ride_field_value — number field validates numeric value
  24. set_ride_field_value — number field rejects non-numeric → 422
  25. set_ride_field_value — checkbox field validates true/false
  26. set_ride_field_value — checkbox rejects invalid value → 422
  27. set_ride_field_value — dropdown validates option
  28. set_ride_field_value — dropdown rejects unknown option → 422
  29. set_ride_field_value — text field respects max_length
  30. set_ride_field_value — text field rejects over-length value → 422
  31. get_ride_field_values — returns all values for ride
  32. get_ride_field_values — no fields → empty values list

Schema tests (sync):
  33. CustomFieldCreate — valid text field
  34. CustomFieldCreate — dropdown requires dropdown_options
  35. CustomFieldCreate — dropdown_options on non-dropdown type → ValidationError
  36. CustomFieldCreate — field_key auto-slugified from label
  37. CustomFieldCreate — field_key with invalid chars → ValidationError
  38. CustomFieldUpdate — all fields optional
  39. RideFieldValueSet — valid value

API layer tests (service patched):
  40. GET  /corporate/accounts/me/custom-fields — 200
  41. GET  /corporate/accounts/me/custom-fields/{id} — 200
  42. POST /corporate/accounts/me/custom-fields — 201
  43. PUT  /corporate/accounts/me/custom-fields/{id} — 200
  44. DELETE /corporate/accounts/me/custom-fields/{id}/deactivate — 200
  45. PUT  /corporate/accounts/me/rides/{ride_id}/custom-fields/{field_id} — 200
  46. GET  /corporate/accounts/me/rides/{ride_id}/custom-fields — 200
  47. GET  /admin/corporate/accounts/{id}/custom-fields — 200
  48. GET  /admin/corporate/accounts/{id}/rides/{ride_id}/custom-fields — 200
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_custom_field import (
    CorporateCustomField,
    CorporateRideCustomFieldValue,
    CustomFieldType,
)
from app.schemas.corporate_custom_field import (
    CustomFieldCreate,
    CustomFieldListResponse,
    CustomFieldResponse,
    CustomFieldUpdate,
    RideFieldValueResponse,
    RideFieldValueSet,
    RideFieldValuesResponse,
)
from app.services.corporate_custom_field import (
    create_custom_field,
    deactivate_custom_field,
    get_custom_field,
    get_ride_field_values,
    list_custom_fields,
    set_ride_field_value,
    update_custom_field,
)

# ---------------------------------------------------------------------------
# Constants / fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 1
ADMIN_ID = 10
MEMBER_ID = 20
FIELD_ID = 100
RIDE_ID = 999


def _make_member(user_id: int, role: MemberRole = MemberRole.ADMIN) -> BusinessAccountMember:
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = ACCOUNT_ID
    m.user_id = user_id
    m.role = role
    m.is_active = True
    return m


def _make_field(
    field_id: int = FIELD_ID,
    label: str = "Project Code",
    field_key: str = "project_code",
    field_type: CustomFieldType = CustomFieldType.TEXT,
    dropdown_options: list[str] | None = None,
    is_required: bool = False,
    max_length: int | None = None,
    display_order: int = 0,
    is_active: bool = True,
) -> CorporateCustomField:
    f = MagicMock(spec=CorporateCustomField)
    f.id = field_id
    f.account_id = ACCOUNT_ID
    f.label = label
    f.field_key = field_key
    f.field_type = field_type
    f.dropdown_options = dropdown_options
    f.is_required = is_required
    f.max_length = max_length
    f.display_order = display_order
    f.is_active = is_active
    f.created_by_id = ADMIN_ID
    f.created_at = NOW
    f.updated_at = NOW
    return f


def _make_value(
    value_id: int = 1,
    field_id: int = FIELD_ID,
    ride_id: int = RIDE_ID,
    value: str = "PROJ-42",
    set_by_id: int = MEMBER_ID,
) -> CorporateRideCustomFieldValue:
    v = MagicMock(spec=CorporateRideCustomFieldValue)
    v.id = value_id
    v.field_id = field_id
    v.ride_id = ride_id
    v.value = value
    v.set_by_id = set_by_id
    v.set_at = NOW
    return v


# ---------------------------------------------------------------------------
# Service tests — field schema management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_custom_field_success():
    """1. create_custom_field — success, text field."""
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
            r.scalar_one_or_none.return_value = None  # no duplicate
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    def _set_id(obj):
        obj.id = FIELD_ID
        obj.created_at = NOW
        obj.updated_at = NOW

    db.add = MagicMock(side_effect=_set_id)

    data = CustomFieldCreate(label="Project Code", field_type=CustomFieldType.TEXT)
    result = await create_custom_field(db, ACCOUNT_ID, ADMIN_ID, data)

    assert result.label == "Project Code"
    assert result.field_key == "project_code"
    assert result.field_type == CustomFieldType.TEXT


@pytest.mark.asyncio
async def test_create_custom_field_non_admin():
    """2. create_custom_field — non-admin → 403."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await create_custom_field(
            db, ACCOUNT_ID, MEMBER_ID,
            CustomFieldCreate(label="X", field_type=CustomFieldType.TEXT),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_custom_field_duplicate_key():
    """3. create_custom_field — duplicate field_key → 409."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    existing = _make_field()
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
        await create_custom_field(
            db, ACCOUNT_ID, ADMIN_ID,
            CustomFieldCreate(label="Project Code", field_key="project_code", field_type=CustomFieldType.TEXT),
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_custom_field_auto_slugify():
    """4. create_custom_field — auto-slugifies label when field_key omitted."""
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
    db.flush = AsyncMock()

    captured = {}

    def _capture(obj):
        captured["field_key"] = obj.field_key
        obj.id = FIELD_ID
        obj.created_at = NOW
        obj.updated_at = NOW

    db.add = MagicMock(side_effect=_capture)

    data = CustomFieldCreate(label="Client Matter Number", field_type=CustomFieldType.TEXT)
    await create_custom_field(db, ACCOUNT_ID, ADMIN_ID, data)

    assert captured["field_key"] == "client_matter_number"


@pytest.mark.asyncio
async def test_create_custom_field_dropdown():
    """5. create_custom_field — dropdown with options."""
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
    db.flush = AsyncMock()

    def _set_id(obj):
        obj.id = FIELD_ID
        obj.created_at = NOW
        obj.updated_at = NOW

    db.add = MagicMock(side_effect=_set_id)

    data = CustomFieldCreate(
        label="Department",
        field_type=CustomFieldType.DROPDOWN,
        dropdown_options=["Engineering", "Sales", "Finance"],
    )
    result = await create_custom_field(db, ACCOUNT_ID, ADMIN_ID, data)
    assert result.field_type == CustomFieldType.DROPDOWN


@pytest.mark.asyncio
async def test_get_custom_field_success():
    """6. get_custom_field — success."""
    db = AsyncMock()
    field = _make_field()
    r = MagicMock()
    r.scalar_one_or_none.return_value = field
    db.execute = AsyncMock(return_value=r)

    result = await get_custom_field(db, ACCOUNT_ID, FIELD_ID)
    assert result.id == FIELD_ID
    assert result.label == "Project Code"


@pytest.mark.asyncio
async def test_get_custom_field_not_found():
    """7. get_custom_field — wrong account → 404."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await get_custom_field(db, ACCOUNT_ID, FIELD_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_custom_fields_active_only():
    """8. list_custom_fields — active_only=True returns only active."""
    db = AsyncMock()
    field = _make_field()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one.return_value = 1
        else:
            r.scalars.return_value.all.return_value = [field]
        return r

    db.execute = fake_execute

    result = await list_custom_fields(db, ACCOUNT_ID, active_only=True)
    assert result.total == 1
    assert len(result.fields) == 1
    assert result.fields[0].is_active is True


@pytest.mark.asyncio
async def test_list_custom_fields_include_inactive():
    """9. list_custom_fields — active_only=False includes inactive."""
    db = AsyncMock()
    inactive = _make_field(is_active=False)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one.return_value = 1
        else:
            r.scalars.return_value.all.return_value = [inactive]
        return r

    db.execute = fake_execute

    result = await list_custom_fields(db, ACCOUNT_ID, active_only=False)
    assert result.total == 1
    assert result.fields[0].is_active is False


@pytest.mark.asyncio
async def test_list_custom_fields_empty():
    """10. list_custom_fields — empty list returns total=0."""
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

    result = await list_custom_fields(db, ACCOUNT_ID)
    assert result.total == 0
    assert result.fields == []


@pytest.mark.asyncio
async def test_update_custom_field_label():
    """11. update_custom_field — label updated."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    field = _make_field()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = field
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    data = CustomFieldUpdate(label="Updated Label")
    result = await update_custom_field(db, ACCOUNT_ID, FIELD_ID, ADMIN_ID, data)
    assert field.label == "Updated Label"


@pytest.mark.asyncio
async def test_update_custom_field_display_order():
    """12. update_custom_field — display_order updated."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    field = _make_field()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = field
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    data = CustomFieldUpdate(display_order=5)
    await update_custom_field(db, ACCOUNT_ID, FIELD_ID, ADMIN_ID, data)
    assert field.display_order == 5


@pytest.mark.asyncio
async def test_update_custom_field_non_admin():
    """13. update_custom_field — non-admin → 403."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await update_custom_field(db, ACCOUNT_ID, FIELD_ID, MEMBER_ID, CustomFieldUpdate())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_update_custom_field_not_found():
    """14. update_custom_field — not found → 404."""
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
        await update_custom_field(db, ACCOUNT_ID, FIELD_ID, ADMIN_ID, CustomFieldUpdate())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_custom_field_dropdown_options_on_non_dropdown():
    """15. update_custom_field — dropdown_options on non-dropdown field → 422."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    field = _make_field(field_type=CustomFieldType.TEXT)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = field
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await update_custom_field(
            db, ACCOUNT_ID, FIELD_ID, ADMIN_ID,
            CustomFieldUpdate(dropdown_options=["A", "B"]),
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_deactivate_custom_field_success():
    """16. deactivate_custom_field — success: is_active=False."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    field = _make_field()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = field
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    await deactivate_custom_field(db, ACCOUNT_ID, FIELD_ID, ADMIN_ID)
    assert field.is_active is False


@pytest.mark.asyncio
async def test_deactivate_custom_field_already_inactive():
    """17. deactivate_custom_field — already inactive → 409."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    field = _make_field(is_active=False)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = field
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await deactivate_custom_field(db, ACCOUNT_ID, FIELD_ID, ADMIN_ID)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_deactivate_custom_field_non_admin():
    """18. deactivate_custom_field — non-admin → 403."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await deactivate_custom_field(db, ACCOUNT_ID, FIELD_ID, MEMBER_ID)
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Service tests — ride field values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_ride_field_value_create():
    """19. set_ride_field_value — success (create new value)."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    field = _make_field()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = member
        elif call_count == 2:
            r.scalar_one_or_none.return_value = field
        else:
            r.scalar_one_or_none.return_value = None  # no existing value
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    def _set_id(obj):
        obj.id = 1
        obj.set_at = NOW

    db.add = MagicMock(side_effect=_set_id)

    data = RideFieldValueSet(value="PROJ-42")
    result = await set_ride_field_value(db, ACCOUNT_ID, RIDE_ID, FIELD_ID, MEMBER_ID, data)
    assert result.value == "PROJ-42"


@pytest.mark.asyncio
async def test_set_ride_field_value_update_existing():
    """20. set_ride_field_value — success (update existing value)."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    field = _make_field()
    existing_val = _make_value(value="OLD-VALUE")
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = member
        elif call_count == 2:
            r.scalar_one_or_none.return_value = field
        else:
            r.scalar_one_or_none.return_value = existing_val
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    data = RideFieldValueSet(value="NEW-VALUE")
    result = await set_ride_field_value(db, ACCOUNT_ID, RIDE_ID, FIELD_ID, MEMBER_ID, data)

    assert existing_val.value == "NEW-VALUE"
    assert result.value == "NEW-VALUE"


@pytest.mark.asyncio
async def test_set_ride_field_value_non_member():
    """21. set_ride_field_value — non-member → 403."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await set_ride_field_value(
            db, ACCOUNT_ID, RIDE_ID, FIELD_ID, 999,
            RideFieldValueSet(value="X"),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_set_ride_field_value_inactive_field():
    """22. set_ride_field_value — inactive field → 404."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    field = _make_field(is_active=False)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = member
        else:
            r.scalar_one_or_none.return_value = field
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await set_ride_field_value(
            db, ACCOUNT_ID, RIDE_ID, FIELD_ID, MEMBER_ID,
            RideFieldValueSet(value="X"),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_set_ride_field_value_number_valid():
    """23. set_ride_field_value — number field validates numeric value."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    field = _make_field(field_type=CustomFieldType.NUMBER)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = member
        elif call_count == 2:
            r.scalar_one_or_none.return_value = field
        else:
            r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    def _set_id(obj):
        obj.id = 1
        obj.set_at = NOW

    db.add = MagicMock(side_effect=_set_id)

    result = await set_ride_field_value(
        db, ACCOUNT_ID, RIDE_ID, FIELD_ID, MEMBER_ID,
        RideFieldValueSet(value="42.5"),
    )
    assert result.value == "42.5"


@pytest.mark.asyncio
async def test_set_ride_field_value_number_invalid():
    """24. set_ride_field_value — number field rejects non-numeric → 422."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    field = _make_field(field_type=CustomFieldType.NUMBER)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = member
        else:
            r.scalar_one_or_none.return_value = field
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await set_ride_field_value(
            db, ACCOUNT_ID, RIDE_ID, FIELD_ID, MEMBER_ID,
            RideFieldValueSet(value="not-a-number"),
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_set_ride_field_value_checkbox_valid():
    """25. set_ride_field_value — checkbox field validates true/false."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    field = _make_field(field_type=CustomFieldType.CHECKBOX)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = member
        elif call_count == 2:
            r.scalar_one_or_none.return_value = field
        else:
            r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    def _set_id(obj):
        obj.id = 1
        obj.set_at = NOW

    db.add = MagicMock(side_effect=_set_id)

    result = await set_ride_field_value(
        db, ACCOUNT_ID, RIDE_ID, FIELD_ID, MEMBER_ID,
        RideFieldValueSet(value="true"),
    )
    assert result.value == "true"


@pytest.mark.asyncio
async def test_set_ride_field_value_checkbox_invalid():
    """26. set_ride_field_value — checkbox rejects invalid value → 422."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    field = _make_field(field_type=CustomFieldType.CHECKBOX)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = member
        else:
            r.scalar_one_or_none.return_value = field
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await set_ride_field_value(
            db, ACCOUNT_ID, RIDE_ID, FIELD_ID, MEMBER_ID,
            RideFieldValueSet(value="maybe"),
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_set_ride_field_value_dropdown_valid():
    """27. set_ride_field_value — dropdown validates option."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    field = _make_field(
        field_type=CustomFieldType.DROPDOWN,
        dropdown_options=["Engineering", "Sales", "Finance"],
    )
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = member
        elif call_count == 2:
            r.scalar_one_or_none.return_value = field
        else:
            r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    def _set_id(obj):
        obj.id = 1
        obj.set_at = NOW

    db.add = MagicMock(side_effect=_set_id)

    result = await set_ride_field_value(
        db, ACCOUNT_ID, RIDE_ID, FIELD_ID, MEMBER_ID,
        RideFieldValueSet(value="Engineering"),
    )
    assert result.value == "Engineering"


@pytest.mark.asyncio
async def test_set_ride_field_value_dropdown_invalid():
    """28. set_ride_field_value — dropdown rejects unknown option → 422."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    field = _make_field(
        field_type=CustomFieldType.DROPDOWN,
        dropdown_options=["Engineering", "Sales"],
    )
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = member
        else:
            r.scalar_one_or_none.return_value = field
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await set_ride_field_value(
            db, ACCOUNT_ID, RIDE_ID, FIELD_ID, MEMBER_ID,
            RideFieldValueSet(value="Unknown Department"),
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_set_ride_field_value_text_max_length_ok():
    """29. set_ride_field_value — text field respects max_length."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    field = _make_field(field_type=CustomFieldType.TEXT, max_length=10)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = member
        elif call_count == 2:
            r.scalar_one_or_none.return_value = field
        else:
            r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    def _set_id(obj):
        obj.id = 1
        obj.set_at = NOW

    db.add = MagicMock(side_effect=_set_id)

    result = await set_ride_field_value(
        db, ACCOUNT_ID, RIDE_ID, FIELD_ID, MEMBER_ID,
        RideFieldValueSet(value="PROJ-001"),
    )
    assert result.value == "PROJ-001"


@pytest.mark.asyncio
async def test_set_ride_field_value_text_over_max_length():
    """30. set_ride_field_value — text field rejects over-length value → 422."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    field = _make_field(field_type=CustomFieldType.TEXT, max_length=5)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = member
        else:
            r.scalar_one_or_none.return_value = field
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await set_ride_field_value(
            db, ACCOUNT_ID, RIDE_ID, FIELD_ID, MEMBER_ID,
            RideFieldValueSet(value="TOO-LONG-VALUE"),
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_get_ride_field_values_with_data():
    """31. get_ride_field_values — returns all values for a ride."""
    db = AsyncMock()
    field = _make_field()
    val = _make_value()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalars.return_value.all.return_value = [field]
        else:
            r.scalars.return_value.all.return_value = [val]
        return r

    db.execute = fake_execute

    result = await get_ride_field_values(db, ACCOUNT_ID, RIDE_ID)
    assert result.ride_id == RIDE_ID
    assert len(result.values) == 1
    assert result.values[0].value == "PROJ-42"


@pytest.mark.asyncio
async def test_get_ride_field_values_no_fields():
    """32. get_ride_field_values — no fields → empty values list."""
    db = AsyncMock()
    r = MagicMock()
    r.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=r)

    result = await get_ride_field_values(db, ACCOUNT_ID, RIDE_ID)
    assert result.ride_id == RIDE_ID
    assert result.values == []


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_schema_custom_field_create_text():
    """33. CustomFieldCreate — valid text field."""
    f = CustomFieldCreate(label="Project Code", field_type=CustomFieldType.TEXT)
    assert f.label == "Project Code"
    assert f.field_type == CustomFieldType.TEXT
    assert f.is_required is False


def test_schema_custom_field_create_dropdown_missing_options():
    """34. CustomFieldCreate — dropdown requires dropdown_options."""
    with pytest.raises(ValidationError):
        CustomFieldCreate(
            label="Dept",
            field_type=CustomFieldType.DROPDOWN,
            # no dropdown_options
        )


def test_schema_custom_field_create_options_on_text():
    """35. CustomFieldCreate — dropdown_options on non-dropdown type → ValidationError."""
    with pytest.raises(ValidationError):
        CustomFieldCreate(
            label="X",
            field_type=CustomFieldType.TEXT,
            dropdown_options=["A", "B"],
        )


def test_schema_custom_field_key_auto_slug():
    """36. CustomFieldCreate — field_key auto-slugified from label (no explicit key)."""
    f = CustomFieldCreate(label="Client Matter Number", field_type=CustomFieldType.TEXT)
    # key is None here — service will slugify; schema does not set it automatically
    assert f.field_key is None


def test_schema_custom_field_key_invalid_chars():
    """37. CustomFieldCreate — field_key with invalid chars → ValidationError."""
    with pytest.raises(ValidationError):
        CustomFieldCreate(
            label="Bad Key",
            field_key="Bad Key!",
            field_type=CustomFieldType.TEXT,
        )


def test_schema_custom_field_update_all_optional():
    """38. CustomFieldUpdate — all fields optional."""
    u = CustomFieldUpdate()
    assert u.label is None
    assert u.is_required is None
    assert u.display_order is None


def test_schema_ride_field_value_set():
    """39. RideFieldValueSet — valid value."""
    v = RideFieldValueSet(value="PROJ-42")
    assert v.value == "PROJ-42"


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


def _make_field_response() -> CustomFieldResponse:
    return CustomFieldResponse(
        id=FIELD_ID,
        account_id=ACCOUNT_ID,
        label="Project Code",
        field_key="project_code",
        field_type=CustomFieldType.TEXT,
        dropdown_options=None,
        is_required=False,
        max_length=None,
        display_order=0,
        is_active=True,
        created_by_id=ADMIN_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _make_value_response() -> RideFieldValueResponse:
    return RideFieldValueResponse(
        id=1,
        field_id=FIELD_ID,
        ride_id=RIDE_ID,
        field_label="Project Code",
        field_key="project_code",
        field_type=CustomFieldType.TEXT,
        value="PROJ-42",
        set_by_id=MEMBER_ID,
        set_at=NOW,
    )


@pytest.mark.asyncio
async def test_api_list_custom_fields():
    """40. GET /corporate/accounts/me/custom-fields — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    list_response = CustomFieldListResponse(account_id=ACCOUNT_ID, total=1, fields=[_make_field_response()])

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch("app.api.v1.corporate_custom_fields.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch("app.api.v1.corporate_custom_fields.list_custom_fields", new=AsyncMock(return_value=list_response)),
        TestClient(app) as client,
    ):
        resp = client.get("/api/v1/corporate/accounts/me/custom-fields")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_api_get_custom_field():
    """41. GET /corporate/accounts/me/custom-fields/{id} — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    field_response = _make_field_response()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch("app.api.v1.corporate_custom_fields.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch("app.api.v1.corporate_custom_fields.get_custom_field", new=AsyncMock(return_value=field_response)),
        TestClient(app) as client,
    ):
        resp = client.get(f"/api/v1/corporate/accounts/me/custom-fields/{FIELD_ID}")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["id"] == FIELD_ID


@pytest.mark.asyncio
async def test_api_create_custom_field():
    """42. POST /corporate/accounts/me/custom-fields — 201."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    field_response = _make_field_response()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch("app.api.v1.corporate_custom_fields.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch("app.api.v1.corporate_custom_fields.create_custom_field", new=AsyncMock(return_value=field_response)),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/api/v1/corporate/accounts/me/custom-fields",
            json={"label": "Project Code", "field_type": "text"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["label"] == "Project Code"


@pytest.mark.asyncio
async def test_api_update_custom_field():
    """43. PUT /corporate/accounts/me/custom-fields/{id} — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    field_response = _make_field_response()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch("app.api.v1.corporate_custom_fields.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch("app.api.v1.corporate_custom_fields.update_custom_field", new=AsyncMock(return_value=field_response)),
        TestClient(app) as client,
    ):
        resp = client.put(
            f"/api/v1/corporate/accounts/me/custom-fields/{FIELD_ID}",
            json={"label": "New Label"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_deactivate_custom_field():
    """44. DELETE /corporate/accounts/me/custom-fields/{id}/deactivate — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    field_response = _make_field_response()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch("app.api.v1.corporate_custom_fields.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch("app.api.v1.corporate_custom_fields.deactivate_custom_field", new=AsyncMock(return_value=field_response)),
        TestClient(app) as client,
    ):
        resp = client.delete(f"/api/v1/corporate/accounts/me/custom-fields/{FIELD_ID}/deactivate")
    app.dependency_overrides.clear()
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_set_ride_custom_field_value():
    """45. PUT /corporate/accounts/me/rides/{ride_id}/custom-fields/{field_id} — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    value_response = _make_value_response()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch("app.api.v1.corporate_custom_fields.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch("app.api.v1.corporate_custom_fields.set_ride_field_value", new=AsyncMock(return_value=value_response)),
        TestClient(app) as client,
    ):
        resp = client.put(
            f"/api/v1/corporate/accounts/me/rides/{RIDE_ID}/custom-fields/{FIELD_ID}",
            json={"value": "PROJ-42"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["value"] == "PROJ-42"


@pytest.mark.asyncio
async def test_api_get_ride_custom_field_values():
    """46. GET /corporate/accounts/me/rides/{ride_id}/custom-fields — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    values_response = RideFieldValuesResponse(ride_id=RIDE_ID, values=[_make_value_response()])

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch("app.api.v1.corporate_custom_fields.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch("app.api.v1.corporate_custom_fields.get_ride_field_values", new=AsyncMock(return_value=values_response)),
        TestClient(app) as client,
    ):
        resp = client.get(f"/api/v1/corporate/accounts/me/rides/{RIDE_ID}/custom-fields")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["ride_id"] == RIDE_ID


@pytest.mark.asyncio
async def test_api_platform_admin_list_custom_fields():
    """47. GET /admin/corporate/accounts/{id}/custom-fields — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin

    fake_user, fake_db = _fake_user_deps(is_admin=True)
    list_response = CustomFieldListResponse(account_id=ACCOUNT_ID, total=1, fields=[_make_field_response()])

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[require_admin] = lambda: fake_user

    with (
        patch("app.api.v1.corporate_custom_fields.list_custom_fields", new=AsyncMock(return_value=list_response)),
        TestClient(app) as client,
    ):
        resp = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/custom-fields")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_api_platform_admin_get_ride_custom_field_values():
    """48. GET /admin/corporate/accounts/{id}/rides/{ride_id}/custom-fields — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin

    fake_user, fake_db = _fake_user_deps(is_admin=True)
    values_response = RideFieldValuesResponse(ride_id=RIDE_ID, values=[_make_value_response()])

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[require_admin] = lambda: fake_user

    with (
        patch("app.api.v1.corporate_custom_fields.get_ride_field_values", new=AsyncMock(return_value=values_response)),
        TestClient(app) as client,
    ):
        resp = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/rides/{RIDE_ID}/custom-fields")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["ride_id"] == RIDE_ID
