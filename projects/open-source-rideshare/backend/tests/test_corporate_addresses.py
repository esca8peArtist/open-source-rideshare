"""Tests for the Corporate Address Book feature.

Service tests (async, mocked DB):
  1.  create_corporate_address — success (admin)
  2.  create_corporate_address — non-admin → 403
  3.  create_corporate_address — invalid cost_center_id → 400
  4.  create_corporate_address — invalid trip_purpose_id → 400
  5.  get_corporate_address — success (any member)
  6.  get_corporate_address — non-member → 403
  7.  get_corporate_address — wrong account → 404
  8.  list_corporate_addresses — returns active addresses
  9.  list_corporate_addresses — active_only=False returns all (total=2)
  10. list_corporate_addresses — non-member → 403
  11. search_corporate_addresses — matches by name
  12. search_corporate_addresses — matches by city
  13. search_corporate_addresses — no match returns empty list
  14. search_corporate_addresses — non-member → 403
  15. update_corporate_address — partial update (admin)
  16. update_corporate_address — non-admin → 403
  17. update_corporate_address — not found → 404
  18. update_corporate_address — invalid cost_center_id → 400
  19. deactivate_corporate_address — success: is_active=False
  20. deactivate_corporate_address — already inactive → 409
  21. deactivate_corporate_address — non-admin → 403
  22. deactivate_corporate_address — not found → 404
  23. delete_corporate_address — success: deleted
  24. delete_corporate_address — non-admin → 403
  25. delete_corporate_address — not found → 404
  26. list_all_corporate_addresses — platform-admin sees all

Schema tests (sync):
  27. CorporateAddressCreate — valid minimal
  28. CorporateAddressCreate — valid with all fields
  29. CorporateAddressCreate — latitude out of range → ValidationError
  30. CorporateAddressCreate — longitude out of range → ValidationError
  31. CorporateAddressCreate — name too long → ValidationError
  32. CorporateAddressUpdate — all fields optional (empty update valid)
  33. CorporateAddressUpdate — partial update
  34. CorporateAddressResponse — constructed manually

API layer tests (service patched):
  35. GET  /corporate/accounts/me/addresses — 200
  36. GET  /corporate/accounts/me/addresses/search?q= — 200
  37. GET  /corporate/accounts/me/addresses/{id} — 200
  38. POST /corporate/accounts/me/addresses — 201
  39. PATCH /corporate/accounts/me/addresses/{id} — 200
  40. DELETE /corporate/accounts/me/addresses/{id}/deactivate — 200
  41. DELETE /corporate/accounts/me/addresses/{id} — 204
  42. GET  /admin/corporate/accounts/{id}/addresses — 200
  43. GET  /admin/corporate/accounts/{id}/addresses/{addr_id} — 200
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_address import CorporateAddress
from app.schemas.corporate_address import (
    CorporateAddressCreate,
    CorporateAddressListResponse,
    CorporateAddressResponse,
    CorporateAddressUpdate,
)
from app.services.corporate_address import (
    create_corporate_address,
    deactivate_corporate_address,
    delete_corporate_address,
    get_corporate_address,
    list_all_corporate_addresses,
    list_corporate_addresses,
    search_corporate_addresses,
    update_corporate_address,
)

# ---------------------------------------------------------------------------
# Constants / fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 1
ADMIN_ID = 10
MEMBER_ID = 20
ADDRESS_ID = 100


def _make_member(user_id: int, role: MemberRole = MemberRole.ADMIN) -> BusinessAccountMember:
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = ACCOUNT_ID
    m.user_id = user_id
    m.role = role
    m.is_active = True
    return m


def _make_address(
    address_id: int = ADDRESS_ID,
    account_id: int = ACCOUNT_ID,
    is_active: bool = True,
) -> CorporateAddress:
    a = MagicMock(spec=CorporateAddress)
    a.id = address_id
    a.account_id = account_id
    a.name = "HQ Office"
    a.address_line_1 = "123 Main St"
    a.address_line_2 = None
    a.city = "Chicago"
    a.state = "IL"
    a.zip_code = "60601"
    a.country = "US"
    a.latitude = None
    a.longitude = None
    a.notes = None
    a.is_pickup_point = True
    a.is_dropoff_point = True
    a.default_cost_center_id = None
    a.default_trip_purpose_id = None
    a.is_active = is_active
    a.created_by_id = ADMIN_ID
    a.created_at = NOW
    a.updated_at = NOW
    return a


def _response_from_addr(a):
    return CorporateAddressResponse(
        id=a.id,
        account_id=a.account_id,
        name=a.name,
        address_line_1=a.address_line_1,
        address_line_2=a.address_line_2,
        city=a.city,
        state=a.state,
        zip_code=a.zip_code,
        country=a.country,
        latitude=a.latitude,
        longitude=a.longitude,
        notes=a.notes,
        is_pickup_point=a.is_pickup_point,
        is_dropoff_point=a.is_dropoff_point,
        default_cost_center_id=a.default_cost_center_id,
        default_trip_purpose_id=a.default_trip_purpose_id,
        is_active=a.is_active,
        created_by_id=a.created_by_id,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


# ---------------------------------------------------------------------------
# 1. create_corporate_address — success (admin)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_address_success():
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    addr = _make_address()

    async def fake_execute(stmt):
        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        return r

    db.execute = fake_execute
    db.add = MagicMock()
    db.commit = AsyncMock()

    def _refresh(obj):
        for k, v in vars(addr).items():
            if not k.startswith("_"):
                try:
                    setattr(obj, k, v)
                except Exception:
                    pass

    db.refresh = AsyncMock()

    data = CorporateAddressCreate(
        name="HQ Office",
        address_line_1="123 Main St",
        city="Chicago",
        state="IL",
    )

    with patch(
        "app.services.corporate_address.CorporateAddressResponse.model_validate",
        return_value=_response_from_addr(addr),
    ):
        result = await create_corporate_address(db, ACCOUNT_ID, ADMIN_ID, data)

    assert result.name == "HQ Office"
    assert result.city == "Chicago"
    assert result.is_active is True


# ---------------------------------------------------------------------------
# 2. create_corporate_address — non-admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_address_non_admin_raises_403():
    db = AsyncMock()

    async def fake_execute(stmt):
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute

    data = CorporateAddressCreate(
        name="Office",
        address_line_1="1 St",
        city="Chicago",
        state="IL",
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_corporate_address(db, ACCOUNT_ID, MEMBER_ID, data)

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 3. create_corporate_address — invalid cost_center_id → 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_address_invalid_cost_center_raises_400():
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin   # _require_admin
        else:
            r.scalar_one_or_none.return_value = None    # cost center not found
        return r

    db.execute = fake_execute

    data = CorporateAddressCreate(
        name="Office",
        address_line_1="1 St",
        city="Chicago",
        state="IL",
        default_cost_center_id=999,
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_corporate_address(db, ACCOUNT_ID, ADMIN_ID, data)

    assert exc_info.value.status_code == 400
    assert "Cost center" in exc_info.value.detail


# ---------------------------------------------------------------------------
# 4. create_corporate_address — invalid trip_purpose_id → 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_address_invalid_trip_purpose_raises_400():
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin   # _require_admin
        else:
            r.scalar_one_or_none.return_value = None    # trip purpose not found
        return r

    db.execute = fake_execute

    data = CorporateAddressCreate(
        name="Office",
        address_line_1="1 St",
        city="Chicago",
        state="IL",
        default_trip_purpose_id=999,
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_corporate_address(db, ACCOUNT_ID, ADMIN_ID, data)

    assert exc_info.value.status_code == 400
    assert "Trip purpose" in exc_info.value.detail


# ---------------------------------------------------------------------------
# 5. get_corporate_address — success (any member)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_address_success():
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    addr = _make_address()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = member   # _require_member
        else:
            r.scalar_one_or_none.return_value = addr     # _get_address_or_404
        return r

    db.execute = fake_execute

    with patch(
        "app.services.corporate_address.CorporateAddressResponse.model_validate",
        return_value=_response_from_addr(addr),
    ):
        result = await get_corporate_address(db, ACCOUNT_ID, ADDRESS_ID, MEMBER_ID)

    assert result.id == ADDRESS_ID


# ---------------------------------------------------------------------------
# 6. get_corporate_address — non-member → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_address_non_member_raises_403():
    db = AsyncMock()

    async def fake_execute(stmt):
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc_info:
        await get_corporate_address(db, ACCOUNT_ID, 999, 999)

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 7. get_corporate_address — wrong account → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_address_wrong_account_raises_404():
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin  # _require_member
        else:
            r.scalar_one_or_none.return_value = None   # not found
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc_info:
        await get_corporate_address(db, ACCOUNT_ID, ADDRESS_ID, ADMIN_ID)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 8. list_corporate_addresses — returns active addresses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_addresses_active_only():
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    addr = _make_address()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = member  # _require_member
        elif call_count == 2:
            r.scalar_one.return_value = 1               # count
        else:
            r.scalars.return_value.all.return_value = [addr]  # list
        return r

    db.execute = fake_execute

    with patch(
        "app.services.corporate_address.CorporateAddressResponse.model_validate",
        side_effect=_response_from_addr,
    ):
        response = await list_corporate_addresses(
            db, ACCOUNT_ID, MEMBER_ID, active_only=True
        )

    assert response.total == 1
    assert len(response.addresses) == 1
    assert response.addresses[0].name == "HQ Office"


# ---------------------------------------------------------------------------
# 9. list_corporate_addresses — active_only=False returns all (total=2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_addresses_all():
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    active_addr = _make_address(is_active=True)
    inactive_addr = _make_address(address_id=101, is_active=False)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one.return_value = 2
        else:
            r.scalars.return_value.all.return_value = [active_addr, inactive_addr]
        return r

    db.execute = fake_execute

    with patch(
        "app.services.corporate_address.CorporateAddressResponse.model_validate",
        side_effect=_response_from_addr,
    ):
        response = await list_corporate_addresses(
            db, ACCOUNT_ID, ADMIN_ID, active_only=False
        )

    assert response.total == 2
    assert len(response.addresses) == 2


# ---------------------------------------------------------------------------
# 10. list_corporate_addresses — non-member → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_addresses_non_member_raises_403():
    db = AsyncMock()

    async def fake_execute(stmt):
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc_info:
        await list_corporate_addresses(db, ACCOUNT_ID, 999)

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 11. search_corporate_addresses — matches by name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_addresses_by_name():
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    addr = _make_address()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = member
        elif call_count == 2:
            r.scalar_one.return_value = 1
        else:
            r.scalars.return_value.all.return_value = [addr]
        return r

    db.execute = fake_execute

    with patch(
        "app.services.corporate_address.CorporateAddressResponse.model_validate",
        side_effect=_response_from_addr,
    ):
        response = await search_corporate_addresses(db, ACCOUNT_ID, MEMBER_ID, "HQ")

    assert response.total == 1
    assert response.addresses[0].name == "HQ Office"


# ---------------------------------------------------------------------------
# 12. search_corporate_addresses — matches by city
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_addresses_by_city():
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    addr = _make_address()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = member
        elif call_count == 2:
            r.scalar_one.return_value = 1
        else:
            r.scalars.return_value.all.return_value = [addr]
        return r

    db.execute = fake_execute

    with patch(
        "app.services.corporate_address.CorporateAddressResponse.model_validate",
        side_effect=_response_from_addr,
    ):
        response = await search_corporate_addresses(
            db, ACCOUNT_ID, MEMBER_ID, "Chicago"
        )

    assert response.total == 1


# ---------------------------------------------------------------------------
# 13. search_corporate_addresses — no match returns empty list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_addresses_no_match():
    db = AsyncMock()
    member = _make_member(MEMBER_ID, MemberRole.MEMBER)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = member
        elif call_count == 2:
            r.scalar_one.return_value = 0
        else:
            r.scalars.return_value.all.return_value = []
        return r

    db.execute = fake_execute

    response = await search_corporate_addresses(
        db, ACCOUNT_ID, MEMBER_ID, "nonexistent-xyz"
    )

    assert response.total == 0
    assert response.addresses == []


# ---------------------------------------------------------------------------
# 14. search_corporate_addresses — non-member → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_addresses_non_member_raises_403():
    db = AsyncMock()

    async def fake_execute(stmt):
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc_info:
        await search_corporate_addresses(db, ACCOUNT_ID, 999, "Office")

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 15. update_corporate_address — partial update (admin)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_address_success():
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    addr = _make_address()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = addr
        return r

    db.execute = fake_execute
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    data = CorporateAddressUpdate(name="New Office Name")
    updated = _make_address()
    updated.name = "New Office Name"

    with patch(
        "app.services.corporate_address.CorporateAddressResponse.model_validate",
        return_value=_response_from_addr(updated),
    ):
        result = await update_corporate_address(
            db, ACCOUNT_ID, ADDRESS_ID, ADMIN_ID, data
        )

    assert result.name == "New Office Name"
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 16. update_corporate_address — non-admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_address_non_admin_raises_403():
    db = AsyncMock()

    async def fake_execute(stmt):
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc_info:
        await update_corporate_address(
            db, ACCOUNT_ID, ADDRESS_ID, MEMBER_ID, CorporateAddressUpdate()
        )

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 17. update_corporate_address — not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_address_not_found_raises_404():
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

    with pytest.raises(HTTPException) as exc_info:
        await update_corporate_address(
            db, ACCOUNT_ID, ADDRESS_ID, ADMIN_ID, CorporateAddressUpdate()
        )

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 18. update_corporate_address — invalid cost_center_id → 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_address_invalid_cost_center_raises_400():
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    addr = _make_address()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one_or_none.return_value = addr
        else:
            r.scalar_one_or_none.return_value = None  # cost center not found
        return r

    db.execute = fake_execute

    data = CorporateAddressUpdate(default_cost_center_id=999)

    with pytest.raises(HTTPException) as exc_info:
        await update_corporate_address(db, ACCOUNT_ID, ADDRESS_ID, ADMIN_ID, data)

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 19. deactivate_corporate_address — success: is_active=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_address_success():
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    addr = _make_address(is_active=True)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = addr
        return r

    db.execute = fake_execute
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    inactive = _make_address(is_active=False)

    with patch(
        "app.services.corporate_address.CorporateAddressResponse.model_validate",
        return_value=_response_from_addr(inactive),
    ):
        result = await deactivate_corporate_address(
            db, ACCOUNT_ID, ADDRESS_ID, ADMIN_ID
        )

    assert result.is_active is False
    assert addr.is_active is False
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 20. deactivate_corporate_address — already inactive → 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_already_inactive_raises_409():
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    addr = _make_address(is_active=False)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = addr
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc_info:
        await deactivate_corporate_address(db, ACCOUNT_ID, ADDRESS_ID, ADMIN_ID)

    assert exc_info.value.status_code == 409
    assert "already inactive" in exc_info.value.detail


# ---------------------------------------------------------------------------
# 21. deactivate_corporate_address — non-admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_address_non_admin_raises_403():
    db = AsyncMock()

    async def fake_execute(stmt):
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc_info:
        await deactivate_corporate_address(db, ACCOUNT_ID, ADDRESS_ID, MEMBER_ID)

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 22. deactivate_corporate_address — not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_address_not_found_raises_404():
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

    with pytest.raises(HTTPException) as exc_info:
        await deactivate_corporate_address(db, ACCOUNT_ID, ADDRESS_ID, ADMIN_ID)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 23. delete_corporate_address — success: deleted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_address_success():
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    addr = _make_address()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = addr
        return r

    db.execute = fake_execute
    db.delete = AsyncMock()
    db.commit = AsyncMock()

    await delete_corporate_address(db, ACCOUNT_ID, ADDRESS_ID, ADMIN_ID)

    db.delete.assert_awaited_once_with(addr)
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 24. delete_corporate_address — non-admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_address_non_admin_raises_403():
    db = AsyncMock()

    async def fake_execute(stmt):
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc_info:
        await delete_corporate_address(db, ACCOUNT_ID, ADDRESS_ID, MEMBER_ID)

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 25. delete_corporate_address — not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_address_not_found_raises_404():
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

    with pytest.raises(HTTPException) as exc_info:
        await delete_corporate_address(db, ACCOUNT_ID, ADDRESS_ID, ADMIN_ID)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 26. list_all_corporate_addresses — platform-admin sees all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_addresses_platform_admin():
    db = AsyncMock()
    active_addr = _make_address(is_active=True)
    inactive_addr = _make_address(address_id=101, is_active=False)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one.return_value = 2
        else:
            r.scalars.return_value.all.return_value = [active_addr, inactive_addr]
        return r

    db.execute = fake_execute

    with patch(
        "app.services.corporate_address.CorporateAddressResponse.model_validate",
        side_effect=_response_from_addr,
    ):
        response = await list_all_corporate_addresses(db, ACCOUNT_ID)

    assert response.total == 2
    assert len(response.addresses) == 2


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_schema_create_valid_minimal():
    data = CorporateAddressCreate(
        name="Airport",
        address_line_1="O'Hare International Airport",
        city="Chicago",
        state="IL",
    )
    assert data.name == "Airport"
    assert data.country == "US"
    assert data.is_pickup_point is True
    assert data.is_dropoff_point is True


def test_schema_create_valid_full():
    data = CorporateAddressCreate(
        name="Client Site NYC",
        address_line_1="30 Rockefeller Plaza",
        address_line_2="Suite 2100",
        city="New York",
        state="NY",
        zip_code="10112",
        country="US",
        latitude=Decimal("40.758611"),
        longitude=Decimal("-73.978889"),
        notes="Security desk on ground floor. Ask for John.",
        is_pickup_point=True,
        is_dropoff_point=False,
        default_cost_center_id=5,
        default_trip_purpose_id=3,
    )
    assert data.address_line_2 == "Suite 2100"
    assert data.is_dropoff_point is False
    assert data.default_cost_center_id == 5


def test_schema_create_latitude_out_of_range():
    with pytest.raises(ValidationError):
        CorporateAddressCreate(
            name="X",
            address_line_1="1 St",
            city="C",
            state="S",
            latitude=Decimal("91.0"),
        )


def test_schema_create_longitude_out_of_range():
    with pytest.raises(ValidationError):
        CorporateAddressCreate(
            name="X",
            address_line_1="1 St",
            city="C",
            state="S",
            longitude=Decimal("181.0"),
        )


def test_schema_create_name_too_long():
    with pytest.raises(ValidationError):
        CorporateAddressCreate(
            name="A" * 201,
            address_line_1="1 St",
            city="C",
            state="S",
        )


def test_schema_update_all_optional():
    data = CorporateAddressUpdate()
    assert data.model_dump(exclude_unset=True) == {}


def test_schema_update_partial():
    data = CorporateAddressUpdate(city="Dallas", state="TX")
    dumped = data.model_dump(exclude_unset=True)
    assert "city" in dumped
    assert "state" in dumped
    assert "name" not in dumped


def test_schema_response_constructed():
    addr = _make_address()
    response = _response_from_addr(addr)
    assert response.id == ADDRESS_ID
    assert response.country == "US"
    assert response.is_active is True


# ---------------------------------------------------------------------------
# API layer tests (service patched)
# ---------------------------------------------------------------------------

_ADDR_RESPONSE = CorporateAddressResponse(
    id=ADDRESS_ID,
    account_id=ACCOUNT_ID,
    name="HQ Office",
    address_line_1="123 Main St",
    address_line_2=None,
    city="Chicago",
    state="IL",
    zip_code=None,
    country="US",
    latitude=None,
    longitude=None,
    notes=None,
    is_pickup_point=True,
    is_dropoff_point=True,
    default_cost_center_id=None,
    default_trip_purpose_id=None,
    is_active=True,
    created_by_id=ADMIN_ID,
    created_at=NOW,
    updated_at=NOW,
)

_LIST_RESPONSE = CorporateAddressListResponse(
    addresses=[_ADDR_RESPONSE],
    total=1,
)


def _client():
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin

    mock_user = MagicMock()
    mock_user.id = ADMIN_ID
    mock_user.is_admin = True

    mock_db = AsyncMock()
    mock_account = MagicMock()
    mock_account.id = ACCOUNT_ID

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[require_admin] = lambda: mock_user

    return TestClient(app), mock_db, mock_account


def test_api_list_addresses():
    client, mock_db, mock_account = _client()
    with (
        patch("app.api.v1.corporate_addresses.get_user_account", return_value=mock_account),
        patch(
            "app.api.v1.corporate_addresses.list_corporate_addresses",
            new_callable=AsyncMock,
            return_value=_LIST_RESPONSE,
        ),
    ):
        r = client.get("/api/v1/corporate/accounts/me/addresses")
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_api_search_addresses():
    client, mock_db, mock_account = _client()
    with (
        patch("app.api.v1.corporate_addresses.get_user_account", return_value=mock_account),
        patch(
            "app.api.v1.corporate_addresses.search_corporate_addresses",
            new_callable=AsyncMock,
            return_value=_LIST_RESPONSE,
        ),
    ):
        r = client.get("/api/v1/corporate/accounts/me/addresses/search?q=HQ")
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_api_get_address():
    client, mock_db, mock_account = _client()
    with (
        patch("app.api.v1.corporate_addresses.get_user_account", return_value=mock_account),
        patch(
            "app.api.v1.corporate_addresses.get_corporate_address",
            new_callable=AsyncMock,
            return_value=_ADDR_RESPONSE,
        ),
    ):
        r = client.get(f"/api/v1/corporate/accounts/me/addresses/{ADDRESS_ID}")
    assert r.status_code == 200
    assert r.json()["id"] == ADDRESS_ID


def test_api_create_address():
    client, mock_db, mock_account = _client()
    with (
        patch("app.api.v1.corporate_addresses.get_user_account", return_value=mock_account),
        patch(
            "app.api.v1.corporate_addresses.create_corporate_address",
            new_callable=AsyncMock,
            return_value=_ADDR_RESPONSE,
        ),
    ):
        r = client.post(
            "/api/v1/corporate/accounts/me/addresses",
            json={
                "name": "HQ Office",
                "address_line_1": "123 Main St",
                "city": "Chicago",
                "state": "IL",
            },
        )
    assert r.status_code == 201
    assert r.json()["name"] == "HQ Office"


def test_api_update_address():
    client, mock_db, mock_account = _client()
    with (
        patch("app.api.v1.corporate_addresses.get_user_account", return_value=mock_account),
        patch(
            "app.api.v1.corporate_addresses.update_corporate_address",
            new_callable=AsyncMock,
            return_value=_ADDR_RESPONSE,
        ),
    ):
        r = client.patch(
            f"/api/v1/corporate/accounts/me/addresses/{ADDRESS_ID}",
            json={"name": "Updated Office"},
        )
    assert r.status_code == 200


def test_api_deactivate_address():
    client, mock_db, mock_account = _client()
    inactive = CorporateAddressResponse(
        **{**_ADDR_RESPONSE.model_dump(), "is_active": False}
    )
    with (
        patch("app.api.v1.corporate_addresses.get_user_account", return_value=mock_account),
        patch(
            "app.api.v1.corporate_addresses.deactivate_corporate_address",
            new_callable=AsyncMock,
            return_value=inactive,
        ),
    ):
        r = client.delete(
            f"/api/v1/corporate/accounts/me/addresses/{ADDRESS_ID}/deactivate"
        )
    assert r.status_code == 200
    assert r.json()["is_active"] is False


def test_api_delete_address():
    client, mock_db, mock_account = _client()
    with (
        patch("app.api.v1.corporate_addresses.get_user_account", return_value=mock_account),
        patch(
            "app.api.v1.corporate_addresses.delete_corporate_address",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        r = client.delete(f"/api/v1/corporate/accounts/me/addresses/{ADDRESS_ID}")
    assert r.status_code == 204


def test_api_admin_list_addresses():
    client, mock_db, mock_account = _client()
    with patch(
        "app.api.v1.corporate_addresses.list_all_corporate_addresses",
        new_callable=AsyncMock,
        return_value=_LIST_RESPONSE,
    ):
        r = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/addresses")
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_api_admin_get_address():
    client, mock_db, mock_account = _client()
    addr = _make_address()
    with (
        patch(
            "app.services.corporate_address._get_address_or_404",
            new_callable=AsyncMock,
            return_value=addr,
        ),
        patch(
            "app.services.corporate_address.CorporateAddressResponse.model_validate",
            return_value=_ADDR_RESPONSE,
        ),
    ):
        r = client.get(
            f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/addresses/{ADDRESS_ID}"
        )
    assert r.status_code == 200
