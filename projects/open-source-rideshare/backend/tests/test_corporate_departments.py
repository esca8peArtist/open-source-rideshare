"""Tests for the Corporate Department Management feature.

Service tests (async, mocked DB):
  1.  create_department — success, returns DepartmentResponse with member_count=0
  2.  create_department — non-admin → 403
  3.  create_department — duplicate code within account → 409
  4.  create_department — code stored uppercase
  5.  create_department — invalid cost_center_id → 404
  6.  create_department — cost_center in different account → 404
  7.  get_department — success
  8.  get_department — wrong account → 404
  9.  list_departments — returns all active by default
  10. list_departments — active_only=False includes inactive
  11. list_departments — empty list
  12. list_departments — member counts populated via bulk query
  13. update_department — success: name updated
  14. update_department — code updated and uppercased
  15. update_department — non-admin → 403
  16. update_department — duplicate code (other dept) → 409
  17. update_department — same code as self → no conflict
  18. deactivate_department — success: is_active=False
  19. deactivate_department — already inactive → 409
  20. deactivate_department — non-admin → 403
  21. add_department_member — success
  22. add_department_member — target not active account member → 404
  23. add_department_member — duplicate → 409
  24. add_department_member — non-admin → 403
  25. add_department_member — inactive department → 409
  26. remove_department_member — success
  27. remove_department_member — membership not found → 404
  28. remove_department_member — non-admin → 403
  29. list_department_members — returns all ordered (heads first)
  30. list_department_members — empty department
  31. get_department_spend — no members → all zeros
  32. get_department_spend — aggregates member spend correctly
  33. get_department_spend — budget_utilization_pct computed when budget set
  34. get_department_spend — budget_utilization_pct None when no budget

Schema tests (sync):
  35. DepartmentCreate — valid
  36. DepartmentCreate — code uppercased by validator
  37. DepartmentCreate — invalid code pattern → ValidationError
  38. DepartmentCreate — negative monthly_budget → ValidationError
  39. DepartmentUpdate — all fields optional
  40. AddMemberRequest — valid with is_head=True

API layer tests (asyncio, service patched):
  41. GET  /corporate/accounts/me/departments — 200
  42. POST /corporate/accounts/me/departments — 201
  43. GET  /corporate/accounts/me/departments/{id} — 200
  44. PUT  /corporate/accounts/me/departments/{id} — 200
  45. DELETE /corporate/accounts/me/departments/{id}/deactivate — 200
  46. GET  /corporate/accounts/me/departments/{id}/members — 200
  47. POST /corporate/accounts/me/departments/{id}/members — 201
  48. DELETE /corporate/accounts/me/departments/{id}/members/{uid} — 200
  49. GET  /corporate/accounts/me/departments/{id}/spend — 200
  50. GET  /admin/corporate/accounts/{id}/departments — 200
  51. GET  /admin/corporate/accounts/{id}/departments/{id}/spend — 200
  52. POST /corporate/accounts/me/departments — 403 when not member
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_cost_center import CorporateCostCenter
from app.models.corporate_department import CorporateDepartment, CorporateDepartmentMember
from app.schemas.corporate_department import (
    AddMemberRequest,
    DepartmentCreate,
    DepartmentListResponse,
    DepartmentMemberResponse,
    DepartmentMembersResponse,
    DepartmentResponse,
    DepartmentSpendResponse,
    DepartmentUpdate,
)
from app.services.corporate_department import (
    add_department_member,
    create_department,
    deactivate_department,
    get_department,
    get_department_spend,
    list_department_members,
    list_departments,
    remove_department_member,
    update_department,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 1
ADMIN_ID = 10
MEMBER_ID = 20
DEPT_ID = 100
CC_ID = 5


def _make_member(user_id: int, role: MemberRole = MemberRole.ADMIN) -> BusinessAccountMember:
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = ACCOUNT_ID
    m.user_id = user_id
    m.role = role
    m.is_active = True
    m.monthly_spend_limit = None
    return m


def _make_dept(
    dept_id: int = DEPT_ID,
    code: str = "ENG",
    is_active: bool = True,
    monthly_budget: Decimal | None = None,
    cost_center_id: int | None = None,
) -> CorporateDepartment:
    d = MagicMock(spec=CorporateDepartment)
    d.id = dept_id
    d.account_id = ACCOUNT_ID
    d.name = "Engineering"
    d.code = code
    d.description = "Engineering department"
    d.cost_center_id = cost_center_id
    d.monthly_budget = monthly_budget
    d.is_active = is_active
    d.created_by_id = ADMIN_ID
    d.created_at = NOW
    d.updated_at = NOW
    return d


def _make_dept_member(
    user_id: int = MEMBER_ID,
    is_head: bool = False,
) -> CorporateDepartmentMember:
    dm = MagicMock(spec=CorporateDepartmentMember)
    dm.department_id = DEPT_ID
    dm.user_id = user_id
    dm.is_department_head = is_head
    dm.added_by_id = ADMIN_ID
    dm.added_at = NOW
    return dm


def _db_returning(*rows):
    """Helper: build a mock db.execute result that returns the given rows."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = rows[0] if len(rows) == 1 else None
    result.scalars.return_value.all.return_value = list(rows)
    result.scalar_one.return_value = len(rows)
    result.all.return_value = list(rows)
    return result


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_department_success():
    """1. create_department — happy path."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID, MemberRole.ADMIN)

    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            r = MagicMock()
            r.scalar_one_or_none.return_value = admin
            return r
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    def _set_id(obj):
        obj.id = DEPT_ID

    db.add = MagicMock(side_effect=_set_id)

    data = DepartmentCreate(name="Engineering", code="eng")
    result = await create_department(db, ACCOUNT_ID, ADMIN_ID, data)

    assert result.name == "Engineering"
    assert result.code == "ENG"
    assert result.member_count == 0


@pytest.mark.asyncio
async def test_create_department_non_admin():
    """2. create_department — non-admin → 403."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await create_department(
            db, ACCOUNT_ID, MEMBER_ID, DepartmentCreate(name="X", code="X")
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_department_duplicate_code():
    """3. create_department — duplicate code → 409."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    dept = _make_dept()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            # duplicate found
            r.scalar_one_or_none.return_value = dept
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await create_department(
            db, ACCOUNT_ID, ADMIN_ID, DepartmentCreate(name="Engineering 2", code="ENG")
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_department_code_uppercased():
    """4. create_department — code stored uppercase."""
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
        obj.id = DEPT_ID

    db.add = MagicMock(side_effect=_set_id)

    result = await create_department(
        db, ACCOUNT_ID, ADMIN_ID, DepartmentCreate(name="Sales", code="sales")
    )
    assert result.code == "SALES"


@pytest.mark.asyncio
async def test_create_department_invalid_cost_center():
    """5. create_department — invalid cost_center_id → 404."""
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
            # cost center not found
            r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await create_department(
            db, ACCOUNT_ID, ADMIN_ID,
            DepartmentCreate(name="X", code="X", cost_center_id=999),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_department_cost_center_wrong_account():
    """6. create_department — cost_center in different account → 404."""
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
            r.scalar_one_or_none.return_value = None  # not in this account
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await create_department(
            db, ACCOUNT_ID, ADMIN_ID,
            DepartmentCreate(name="X", code="X", cost_center_id=CC_ID),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_department_success():
    """7. get_department — success."""
    db = AsyncMock()
    dept = _make_dept()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = dept
        else:
            r.scalar_one.return_value = 3
        return r

    db.execute = fake_execute

    result = await get_department(db, ACCOUNT_ID, DEPT_ID)
    assert result.id == DEPT_ID
    assert result.member_count == 3


@pytest.mark.asyncio
async def test_get_department_wrong_account():
    """8. get_department — wrong account → 404."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await get_department(db, ACCOUNT_ID, 999)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_departments_returns_active():
    """9. list_departments — returns active by default."""
    db = AsyncMock()
    dept = _make_dept()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one.return_value = 1
        elif call_count == 2:
            r.scalars.return_value.all.return_value = [dept]
        elif call_count == 3:
            r.all.return_value = []  # member counts — empty
        return r

    db.execute = fake_execute

    result = await list_departments(db, ACCOUNT_ID)
    assert result.total == 1
    assert len(result.departments) == 1


@pytest.mark.asyncio
async def test_list_departments_includes_inactive():
    """10. list_departments — active_only=False includes inactive."""
    db = AsyncMock()
    dept_active = _make_dept(dept_id=1, is_active=True)
    dept_inactive = _make_dept(dept_id=2, is_active=False)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one.return_value = 2
        elif call_count == 2:
            r.scalars.return_value.all.return_value = [dept_active, dept_inactive]
        elif call_count == 3:
            r.all.return_value = []
        return r

    db.execute = fake_execute

    result = await list_departments(db, ACCOUNT_ID, active_only=False)
    assert result.total == 2


@pytest.mark.asyncio
async def test_list_departments_empty():
    """11. list_departments — empty list."""
    db = AsyncMock()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one.return_value = 0
        elif call_count == 2:
            r.scalars.return_value.all.return_value = []
        return r

    db.execute = fake_execute

    result = await list_departments(db, ACCOUNT_ID)
    assert result.total == 0
    assert result.departments == []


@pytest.mark.asyncio
async def test_list_departments_member_counts():
    """12. list_departments — member counts populated via bulk query."""
    db = AsyncMock()
    dept = _make_dept(dept_id=10)
    call_count = 0

    class FakeCountRow:
        department_id = 10
        cnt = 5

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one.return_value = 1
        elif call_count == 2:
            r.scalars.return_value.all.return_value = [dept]
        elif call_count == 3:
            r.all.return_value = [FakeCountRow()]
        return r

    db.execute = fake_execute

    result = await list_departments(db, ACCOUNT_ID)
    assert result.departments[0].member_count == 5


@pytest.mark.asyncio
async def test_update_department_name():
    """13. update_department — name updated."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    dept = _make_dept()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one_or_none.return_value = dept
        else:
            r.scalar_one.return_value = 0
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    data = DepartmentUpdate(name="New Name")
    result = await update_department(db, ACCOUNT_ID, DEPT_ID, ADMIN_ID, data)
    assert dept.name == "New Name"


@pytest.mark.asyncio
async def test_update_department_code_uppercased():
    """14. update_department — code uppercased."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    dept = _make_dept()
    dept.code = "ENG"
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one_or_none.return_value = dept
        elif call_count == 3:
            # duplicate check returns None (no conflict)
            r.scalar_one_or_none.return_value = None
        else:
            r.scalar_one.return_value = 0
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    data = DepartmentUpdate(code="sales")
    await update_department(db, ACCOUNT_ID, DEPT_ID, ADMIN_ID, data)
    assert dept.code == "SALES"


@pytest.mark.asyncio
async def test_update_department_non_admin():
    """15. update_department — non-admin → 403."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await update_department(db, ACCOUNT_ID, DEPT_ID, MEMBER_ID, DepartmentUpdate())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_update_department_duplicate_code():
    """16. update_department — duplicate code (other dept) → 409."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    dept = _make_dept(dept_id=DEPT_ID, code="ENG")
    other_dept = _make_dept(dept_id=999, code="SALES")
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one_or_none.return_value = dept
        elif call_count == 3:
            r.scalar_one_or_none.return_value = other_dept  # conflict
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await update_department(db, ACCOUNT_ID, DEPT_ID, ADMIN_ID, DepartmentUpdate(code="SALES"))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_department_same_code_no_conflict():
    """17. update_department — updating to same code (self) → no conflict."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    dept = _make_dept(code="ENG")
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one_or_none.return_value = dept
        else:
            r.scalar_one.return_value = 0
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    # Updating code to same value — no duplicate check triggered since ENG == ENG
    data = DepartmentUpdate(code="ENG")
    result = await update_department(db, ACCOUNT_ID, DEPT_ID, ADMIN_ID, data)
    # No 409 raised — success
    assert result is not None


@pytest.mark.asyncio
async def test_deactivate_department_success():
    """18. deactivate_department — is_active set to False."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    dept = _make_dept(is_active=True)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one_or_none.return_value = dept
        else:
            r.scalar_one.return_value = 2
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    result = await deactivate_department(db, ACCOUNT_ID, DEPT_ID, ADMIN_ID)
    assert dept.is_active is False


@pytest.mark.asyncio
async def test_deactivate_department_already_inactive():
    """19. deactivate_department — already inactive → 409."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    dept = _make_dept(is_active=False)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = dept
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await deactivate_department(db, ACCOUNT_ID, DEPT_ID, ADMIN_ID)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_deactivate_department_non_admin():
    """20. deactivate_department — non-admin → 403."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await deactivate_department(db, ACCOUNT_ID, DEPT_ID, MEMBER_ID)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_add_department_member_success():
    """21. add_department_member — happy path."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    dept = _make_dept(is_active=True)
    target = _make_member(MEMBER_ID, MemberRole.MEMBER)
    dm = _make_dept_member(MEMBER_ID)
    dm.added_at = NOW
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one_or_none.return_value = dept
        elif call_count == 3:
            r.scalar_one_or_none.return_value = target
        elif call_count == 4:
            r.scalar_one_or_none.return_value = None  # no duplicate
        return r

    db.execute = fake_execute
    db.flush = AsyncMock()

    data = AddMemberRequest(user_id=MEMBER_ID, is_department_head=False)
    result = await add_department_member(db, ACCOUNT_ID, DEPT_ID, ADMIN_ID, data)
    assert result.user_id == MEMBER_ID


@pytest.mark.asyncio
async def test_add_department_member_not_account_member():
    """22. add_department_member — target not active account member → 404."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    dept = _make_dept(is_active=True)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one_or_none.return_value = dept
        elif call_count == 3:
            r.scalar_one_or_none.return_value = None  # not a member
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await add_department_member(
            db, ACCOUNT_ID, DEPT_ID, ADMIN_ID, AddMemberRequest(user_id=999)
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_add_department_member_duplicate():
    """23. add_department_member — duplicate → 409."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    dept = _make_dept(is_active=True)
    target = _make_member(MEMBER_ID)
    dm = _make_dept_member(MEMBER_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one_or_none.return_value = dept
        elif call_count == 3:
            r.scalar_one_or_none.return_value = target
        elif call_count == 4:
            r.scalar_one_or_none.return_value = dm  # already exists
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await add_department_member(
            db, ACCOUNT_ID, DEPT_ID, ADMIN_ID, AddMemberRequest(user_id=MEMBER_ID)
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_add_department_member_non_admin():
    """24. add_department_member — non-admin → 403."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await add_department_member(
            db, ACCOUNT_ID, DEPT_ID, MEMBER_ID, AddMemberRequest(user_id=99)
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_add_department_member_inactive_dept():
    """25. add_department_member — inactive department → 409."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    dept = _make_dept(is_active=False)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        else:
            r.scalar_one_or_none.return_value = dept
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await add_department_member(
            db, ACCOUNT_ID, DEPT_ID, ADMIN_ID, AddMemberRequest(user_id=MEMBER_ID)
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_remove_department_member_success():
    """26. remove_department_member — success."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    dept = _make_dept()
    dm = _make_dept_member(MEMBER_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one_or_none.return_value = dept
        elif call_count == 3:
            r.scalar_one_or_none.return_value = dm
        return r

    db.execute = fake_execute
    db.delete = AsyncMock()
    db.flush = AsyncMock()

    result = await remove_department_member(db, ACCOUNT_ID, DEPT_ID, ADMIN_ID, MEMBER_ID)
    assert result["removed"] is True
    assert result["user_id"] == MEMBER_ID


@pytest.mark.asyncio
async def test_remove_department_member_not_found():
    """27. remove_department_member — not found → 404."""
    db = AsyncMock()
    admin = _make_member(ADMIN_ID)
    dept = _make_dept()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = admin
        elif call_count == 2:
            r.scalar_one_or_none.return_value = dept
        else:
            r.scalar_one_or_none.return_value = None
        return r

    db.execute = fake_execute

    with pytest.raises(HTTPException) as exc:
        await remove_department_member(db, ACCOUNT_ID, DEPT_ID, ADMIN_ID, 999)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_remove_department_member_non_admin():
    """28. remove_department_member — non-admin → 403."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)

    with pytest.raises(HTTPException) as exc:
        await remove_department_member(db, ACCOUNT_ID, DEPT_ID, MEMBER_ID, 99)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_list_department_members_ordered():
    """29. list_department_members — heads listed first."""
    db = AsyncMock()
    dept = _make_dept()
    head = _make_dept_member(user_id=1, is_head=True)
    regular = _make_dept_member(user_id=2, is_head=False)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = dept
        else:
            r.scalars.return_value.all.return_value = [head, regular]
        return r

    db.execute = fake_execute

    result = await list_department_members(db, ACCOUNT_ID, DEPT_ID)
    assert result.total == 2
    assert result.members[0].is_department_head is True


@pytest.mark.asyncio
async def test_list_department_members_empty():
    """30. list_department_members — empty department."""
    db = AsyncMock()
    dept = _make_dept()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = dept
        else:
            r.scalars.return_value.all.return_value = []
        return r

    db.execute = fake_execute

    result = await list_department_members(db, ACCOUNT_ID, DEPT_ID)
    assert result.total == 0
    assert result.members == []


@pytest.mark.asyncio
async def test_get_department_spend_no_members():
    """31. get_department_spend — no members → zeros."""
    db = AsyncMock()
    dept = _make_dept(monthly_budget=None)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = dept
        else:
            r.scalars.return_value.all.return_value = []
        return r

    db.execute = fake_execute

    result = await get_department_spend(db, ACCOUNT_ID, DEPT_ID)
    assert result.total_rides == 0
    assert result.total_spend == Decimal("0")
    assert result.member_count == 0


@pytest.mark.asyncio
async def test_get_department_spend_aggregates():
    """32. get_department_spend — aggregates member spend."""
    db = AsyncMock()
    dept = _make_dept(monthly_budget=Decimal("1000"))
    dm1 = _make_dept_member(user_id=1)
    dm2 = _make_dept_member(user_id=2)

    class SpendRow:
        def __init__(self, user_id, rides, spend):
            self.user_id = user_id
            self.rides = rides
            self.spend = spend

    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = dept
        elif call_count == 2:
            r.scalars.return_value.all.return_value = [dm1, dm2]
        elif call_count == 3:
            r.all.return_value = [
                SpendRow(1, 3, Decimal("150.00")),
                SpendRow(2, 5, Decimal("250.00")),
            ]
        return r

    db.execute = fake_execute

    result = await get_department_spend(db, ACCOUNT_ID, DEPT_ID)
    assert result.total_rides == 8
    assert result.total_spend == Decimal("400.00")
    assert result.member_count == 2


@pytest.mark.asyncio
async def test_get_department_spend_utilization_pct():
    """33. get_department_spend — budget_utilization_pct computed."""
    db = AsyncMock()
    dept = _make_dept(monthly_budget=Decimal("500"))
    dm1 = _make_dept_member(user_id=1)

    class SpendRow:
        user_id = 1
        rides = 2
        spend = Decimal("250.00")

    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = dept
        elif call_count == 2:
            r.scalars.return_value.all.return_value = [dm1]
        elif call_count == 3:
            r.all.return_value = [SpendRow()]
        return r

    db.execute = fake_execute

    result = await get_department_spend(db, ACCOUNT_ID, DEPT_ID)
    assert result.budget_utilization_pct == 50.0


@pytest.mark.asyncio
async def test_get_department_spend_no_budget():
    """34. get_department_spend — no budget → utilization None."""
    db = AsyncMock()
    dept = _make_dept(monthly_budget=None)
    dm1 = _make_dept_member(user_id=1)

    class SpendRow:
        user_id = 1
        rides = 2
        spend = Decimal("100.00")

    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.scalar_one_or_none.return_value = dept
        elif call_count == 2:
            r.scalars.return_value.all.return_value = [dm1]
        elif call_count == 3:
            r.all.return_value = [SpendRow()]
        return r

    db.execute = fake_execute

    result = await get_department_spend(db, ACCOUNT_ID, DEPT_ID)
    assert result.budget_utilization_pct is None


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_department_create_valid():
    """35. DepartmentCreate — valid."""
    data = DepartmentCreate(name="Engineering", code="ENG", monthly_budget=Decimal("5000"))
    assert data.name == "Engineering"
    assert data.code == "ENG"


def test_department_create_code_uppercased():
    """36. DepartmentCreate — code uppercased by validator."""
    data = DepartmentCreate(name="Sales", code="sales-north")
    assert data.code == "SALES-NORTH"


def test_department_create_invalid_code_pattern():
    """37. DepartmentCreate — invalid code pattern → ValidationError."""
    with pytest.raises(ValidationError):
        DepartmentCreate(name="X", code="bad code!")


def test_department_create_negative_budget():
    """38. DepartmentCreate — negative monthly_budget → ValidationError."""
    with pytest.raises(ValidationError):
        DepartmentCreate(name="X", code="X", monthly_budget=Decimal("-100"))


def test_department_update_all_optional():
    """39. DepartmentUpdate — all fields optional."""
    data = DepartmentUpdate()
    assert data.name is None
    assert data.code is None


def test_add_member_request_with_head():
    """40. AddMemberRequest — valid with is_head=True."""
    data = AddMemberRequest(user_id=42, is_department_head=True)
    assert data.is_department_head is True


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

# Helper: build a fake user and db for dependency_overrides
def _fake_user_deps(user_id: int = ADMIN_ID, is_admin: bool = False):
    from app.models.user import User as UserModel
    u = MagicMock(spec=UserModel)
    u.id = user_id
    u.is_admin = is_admin

    async def _fake_db():
        db = AsyncMock()
        yield db

    return u, _fake_db


@pytest.mark.asyncio
async def test_api_list_departments():
    """41. GET /corporate/accounts/me/departments — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    list_response = DepartmentListResponse(account_id=ACCOUNT_ID, total=0, departments=[])

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_departments.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_departments.list_departments",
            new=AsyncMock(return_value=list_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.get("/api/v1/corporate/accounts/me/departments")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_api_create_department():
    """42. POST /corporate/accounts/me/departments — 201."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    dept_response = DepartmentResponse(
        id=DEPT_ID,
        account_id=ACCOUNT_ID,
        name="Engineering",
        code="ENG",
        description=None,
        cost_center_id=None,
        monthly_budget=None,
        is_active=True,
        created_by_id=ADMIN_ID,
        member_count=0,
        created_at=NOW,
        updated_at=NOW,
    )

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_departments.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_departments.create_department",
            new=AsyncMock(return_value=dept_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/api/v1/corporate/accounts/me/departments",
            json={"name": "Engineering", "code": "ENG"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["code"] == "ENG"


@pytest.mark.asyncio
async def test_api_get_department():
    """43. GET /corporate/accounts/me/departments/{id} — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    dept_response = DepartmentResponse(
        id=DEPT_ID,
        account_id=ACCOUNT_ID,
        name="Engineering",
        code="ENG",
        description=None,
        cost_center_id=None,
        monthly_budget=None,
        is_active=True,
        created_by_id=ADMIN_ID,
        member_count=2,
        created_at=NOW,
        updated_at=NOW,
    )

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_departments.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_departments.get_department",
            new=AsyncMock(return_value=dept_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.get(f"/api/v1/corporate/accounts/me/departments/{DEPT_ID}")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["member_count"] == 2


@pytest.mark.asyncio
async def test_api_update_department():
    """44. PUT /corporate/accounts/me/departments/{id} — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    dept_response = DepartmentResponse(
        id=DEPT_ID,
        account_id=ACCOUNT_ID,
        name="Updated Name",
        code="ENG",
        description=None,
        cost_center_id=None,
        monthly_budget=None,
        is_active=True,
        created_by_id=ADMIN_ID,
        member_count=0,
        created_at=NOW,
        updated_at=NOW,
    )

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_departments.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_departments.update_department",
            new=AsyncMock(return_value=dept_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.put(
            f"/api/v1/corporate/accounts/me/departments/{DEPT_ID}",
            json={"name": "Updated Name"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_api_deactivate_department():
    """45. DELETE /corporate/accounts/me/departments/{id}/deactivate — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    dept_response = DepartmentResponse(
        id=DEPT_ID,
        account_id=ACCOUNT_ID,
        name="Engineering",
        code="ENG",
        description=None,
        cost_center_id=None,
        monthly_budget=None,
        is_active=False,
        created_by_id=ADMIN_ID,
        member_count=0,
        created_at=NOW,
        updated_at=NOW,
    )

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_departments.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_departments.deactivate_department",
            new=AsyncMock(return_value=dept_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.delete(
            f"/api/v1/corporate/accounts/me/departments/{DEPT_ID}/deactivate"
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_api_list_department_members():
    """46. GET /corporate/accounts/me/departments/{id}/members — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    members_response = DepartmentMembersResponse(
        department_id=DEPT_ID, account_id=ACCOUNT_ID, total=0, members=[]
    )

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_departments.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_departments.list_department_members",
            new=AsyncMock(return_value=members_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.get(
            f"/api/v1/corporate/accounts/me/departments/{DEPT_ID}/members"
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_api_add_department_member():
    """47. POST /corporate/accounts/me/departments/{id}/members — 201."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    member_response = DepartmentMemberResponse(
        department_id=DEPT_ID,
        user_id=MEMBER_ID,
        is_department_head=False,
        added_by_id=ADMIN_ID,
        added_at=NOW,
    )

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_departments.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_departments.add_department_member",
            new=AsyncMock(return_value=member_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.post(
            f"/api/v1/corporate/accounts/me/departments/{DEPT_ID}/members",
            json={"user_id": MEMBER_ID, "is_department_head": False},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["user_id"] == MEMBER_ID


@pytest.mark.asyncio
async def test_api_remove_department_member():
    """48. DELETE /corporate/accounts/me/departments/{id}/members/{uid} — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_departments.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_departments.remove_department_member",
            new=AsyncMock(return_value={"removed": True, "user_id": MEMBER_ID}),
        ),
        TestClient(app) as client,
    ):
        resp = client.delete(
            f"/api/v1/corporate/accounts/me/departments/{DEPT_ID}/members/{MEMBER_ID}"
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["removed"] is True


@pytest.mark.asyncio
async def test_api_department_spend():
    """49. GET /corporate/accounts/me/departments/{id}/spend — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()
    spend_response = DepartmentSpendResponse(
        department_id=DEPT_ID,
        account_id=ACCOUNT_ID,
        department_name="Engineering",
        current_month="2026-04",
        total_rides=0,
        total_spend=Decimal("0"),
        monthly_budget=None,
        budget_utilization_pct=None,
        member_count=0,
        members=[],
    )

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_departments.get_user_account",
            new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID)),
        ),
        patch(
            "app.api.v1.corporate_departments.get_department_spend",
            new=AsyncMock(return_value=spend_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.get(
            f"/api/v1/corporate/accounts/me/departments/{DEPT_ID}/spend"
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["total_rides"] == 0


@pytest.mark.asyncio
async def test_api_platform_admin_list_departments():
    """50. GET /admin/corporate/accounts/{id}/departments — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import require_admin, get_db
    from app.models.user import User as UserModel

    fake_admin = MagicMock(spec=UserModel)
    fake_admin.id = 999
    fake_admin.is_admin = True

    async def _fake_db():
        db = AsyncMock()
        yield db

    list_response = DepartmentListResponse(account_id=ACCOUNT_ID, total=2, departments=[])

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[require_admin] = lambda: fake_admin

    with (
        patch(
            "app.api.v1.corporate_departments.list_departments",
            new=AsyncMock(return_value=list_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.get(
            f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/departments"
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


@pytest.mark.asyncio
async def test_api_platform_admin_department_spend():
    """51. GET /admin/corporate/accounts/{id}/departments/{id}/spend — 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import require_admin, get_db
    from app.models.user import User as UserModel

    fake_admin = MagicMock(spec=UserModel)
    fake_admin.id = 999
    fake_admin.is_admin = True

    async def _fake_db():
        db = AsyncMock()
        yield db

    spend_response = DepartmentSpendResponse(
        department_id=DEPT_ID,
        account_id=ACCOUNT_ID,
        department_name="Engineering",
        current_month="2026-04",
        total_rides=10,
        total_spend=Decimal("300.00"),
        monthly_budget=Decimal("1000"),
        budget_utilization_pct=30.0,
        member_count=3,
        members=[],
    )

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[require_admin] = lambda: fake_admin

    with (
        patch(
            "app.api.v1.corporate_departments.get_department_spend",
            new=AsyncMock(return_value=spend_response),
        ),
        TestClient(app) as client,
    ):
        resp = client.get(
            f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/departments/{DEPT_ID}/spend"
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["budget_utilization_pct"] == 30.0


@pytest.mark.asyncio
async def test_api_create_department_not_member():
    """52. POST /corporate/accounts/me/departments — 404 when not a member."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    fake_user, fake_db = _fake_user_deps()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with (
        patch(
            "app.api.v1.corporate_departments.get_user_account",
            new=AsyncMock(return_value=None),
        ),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/api/v1/corporate/accounts/me/departments",
            json={"name": "X", "code": "X"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 404
