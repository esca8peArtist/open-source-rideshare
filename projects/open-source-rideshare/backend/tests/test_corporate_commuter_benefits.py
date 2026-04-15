"""Tests for the Corporate Commuter Benefits feature.

Service tests (async, mocked DB):
  1.  create_program — success creates new program
  2.  create_program — duplicate account → 409
  3.  get_program — returns program when found
  4.  get_program — returns None when not found
  5.  update_program — success updates fields
  6.  update_program — not found → 404
  7.  deactivate_program — sets is_active=False
  8.  deactivate_program — not found → 404
  9.  get_or_create_allotment — creates new allotment without rollover
  10. get_or_create_allotment — returns existing allotment
  11. get_or_create_allotment — applies rollover from prior month
  12. get_or_create_allotment — rollover capped by max_rollover_usd
  13. get_or_create_allotment — no rollover when prior month has no allotment
  14. list_allotments — no filters returns all
  15. list_allotments — filtered by year and month
  16. list_allotments — filtered by member_id
  17. get_member_allotment — returns allotment when program and allotment exist
  18. get_member_allotment — returns None when no program
  19. record_commuter_ride_usage — success increments used_usd
  20. record_commuter_ride_usage — exceeds balance → 409
  21. record_commuter_ride_usage — allotment not found → 404
  22. get_program_stats — returns correct aggregate values

Schema tests (sync):
  23. CommuterProgramCreate — valid schema
  24. CommuterProgramCreate — monthly_allowance_usd must be positive
  25. CommuterProgramUpdate — all fields optional
  26. CommuterProgramResponse — from_attributes works
  27. CommuterAllotmentResponse — from_attributes works
  28. CommuterStatsResponse — fields present

API layer tests (services patched):
  29. GET  /my-allotment — 200 returns allotment
  30. GET  /my-allotment — 404 when no allotment
  31. GET  /my-allotment/history — 200 returns list
  32. POST /program — 201 create program
  33. POST /program — 409 duplicate
  34. GET  /program — 200 returns program
  35. GET  /program — 404 not found
  36. PATCH /program — 200 update
  37. POST /program/deactivate — 200 deactivated
  38. GET  /allotments — 200 list allotments
  39. GET  /program/stats — 200 returns stats
  40. GET  /platform-admin/... — 200 list all programs
  41. GET  /platform-admin/.../{account_id} — 200 get for account
  42. GET  /platform-admin/.../{account_id} — 404 not found
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate_commuter_benefit import (
    CorporateCommuterAllotment,
    CorporateCommuterProgram,
)
from app.schemas.corporate_commuter_benefit import (
    CommuterAllotmentResponse,
    CommuterProgramCreate,
    CommuterProgramResponse,
    CommuterProgramUpdate,
    CommuterStatsResponse,
)
from app.services.corporate_commuter_benefit import (
    create_program,
    deactivate_program,
    get_member_allotment,
    get_or_create_allotment,
    get_program,
    get_program_stats,
    list_allotments,
    record_commuter_ride_usage,
    update_program,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
_ACCOUNT_ID = 1
_PROGRAM_ID = 10
_MEMBER_ID = 5
_USER_ID = 20
_ALLOTMENT_ID = 99
_YEAR = 2026
_MONTH = 4


def _make_program(
    id: int = _PROGRAM_ID,
    account_id: int = _ACCOUNT_ID,
    name: str = "Employee Commuter Benefit",
    description: str | None = "Monthly commute subsidy",
    monthly_allowance_usd: float = 150.00,
    rollover_enabled: bool = False,
    max_rollover_usd: float | None = None,
    eligible_trip_purpose_ids: list | None = None,
    eligible_group_ids: list | None = None,
    is_active: bool = True,
    valid_from=None,
    valid_until=None,
    created_by_id: int | None = _USER_ID,
) -> CorporateCommuterProgram:
    program = CorporateCommuterProgram(
        id=id,
        account_id=account_id,
        name=name,
        description=description,
        monthly_allowance_usd=monthly_allowance_usd,
        rollover_enabled=rollover_enabled,
        max_rollover_usd=max_rollover_usd,
        eligible_trip_purpose_ids=eligible_trip_purpose_ids,
        eligible_group_ids=eligible_group_ids,
        is_active=is_active,
        valid_from=valid_from,
        valid_until=valid_until,
        created_by_id=created_by_id,
        created_at=_NOW,
        updated_at=_NOW,
    )
    return program


def _make_allotment(
    id: int = _ALLOTMENT_ID,
    program_id: int = _PROGRAM_ID,
    member_id: int = _MEMBER_ID,
    period_year: int = _YEAR,
    period_month: int = _MONTH,
    allotted_usd: float = 150.00,
    used_usd: float = 0.00,
    rolled_over_usd: float = 0.00,
) -> CorporateCommuterAllotment:
    allotment = CorporateCommuterAllotment(
        id=id,
        program_id=program_id,
        member_id=member_id,
        period_year=period_year,
        period_month=period_month,
        allotted_usd=allotted_usd,
        used_usd=used_usd,
        rolled_over_usd=rolled_over_usd,
        created_at=_NOW,
    )
    return allotment


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
# Service: create_program
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_program_success():
    """create_program adds a new program when none exists for the account."""
    db = _mock_db_with_one(None)
    data = CommuterProgramCreate(
        name="Employee Commuter Benefit",
        monthly_allowance_usd=150.00,
    )
    program = await create_program(db, account_id=_ACCOUNT_ID, data=data, created_by_id=_USER_ID)
    assert program.name == "Employee Commuter Benefit"
    assert program.account_id == _ACCOUNT_ID
    assert program.is_active is True
    assert float(program.monthly_allowance_usd) == 150.00
    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_create_program_duplicate_raises_409():
    """create_program raises 409 when a program already exists for the account."""
    existing = _make_program()
    db = _mock_db_with_one(existing)
    data = CommuterProgramCreate(name="Another Program", monthly_allowance_usd=100.00)
    with pytest.raises(HTTPException) as exc_info:
        await create_program(db, account_id=_ACCOUNT_ID, data=data, created_by_id=_USER_ID)
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service: get_program
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_program_returns_program():
    """get_program returns the program when found."""
    program = _make_program()
    db = _mock_db_with_one(program)
    result = await get_program(db, account_id=_ACCOUNT_ID)
    assert result is not None
    assert result.id == _PROGRAM_ID


@pytest.mark.asyncio
async def test_get_program_returns_none_when_not_found():
    """get_program returns None when no program exists for the account."""
    db = _mock_db_with_one(None)
    result = await get_program(db, account_id=_ACCOUNT_ID)
    assert result is None


# ---------------------------------------------------------------------------
# Service: update_program
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_program_success():
    """update_program modifies the program fields."""
    program = _make_program()
    db = _mock_db_with_one(program)
    data = CommuterProgramUpdate(name="Updated Name", monthly_allowance_usd=200.00)
    updated = await update_program(db, account_id=_ACCOUNT_ID, data=data)
    assert updated.name == "Updated Name"
    assert float(updated.monthly_allowance_usd) == 200.00
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_update_program_not_found_raises_404():
    """update_program raises 404 when no program exists for the account."""
    db = _mock_db_with_one(None)
    data = CommuterProgramUpdate(name="Doesn't matter")
    with pytest.raises(HTTPException) as exc_info:
        await update_program(db, account_id=_ACCOUNT_ID, data=data)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: deactivate_program
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_program_sets_inactive():
    """deactivate_program sets is_active=False."""
    program = _make_program(is_active=True)
    db = _mock_db_with_one(program)
    result = await deactivate_program(db, account_id=_ACCOUNT_ID)
    assert result.is_active is False
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_deactivate_program_not_found_raises_404():
    """deactivate_program raises 404 when no program exists."""
    db = _mock_db_with_one(None)
    with pytest.raises(HTTPException) as exc_info:
        await deactivate_program(db, account_id=_ACCOUNT_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: get_or_create_allotment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_allotment_creates_new():
    """get_or_create_allotment creates a new allotment when none exists."""
    program = _make_program(rollover_enabled=False)

    db = AsyncMock()
    # Calls: 1) load program, 2) existing allotment check → None, (no prior month)
    r_prog = MagicMock(); r_prog.scalar_one_or_none.return_value = program
    r_existing = MagicMock(); r_existing.scalar_one_or_none.return_value = None
    db.execute.side_effect = [r_prog, r_existing]

    allotment = await get_or_create_allotment(db, _PROGRAM_ID, _MEMBER_ID, _YEAR, _MONTH)
    assert allotment.program_id == _PROGRAM_ID
    assert allotment.member_id == _MEMBER_ID
    assert allotment.period_year == _YEAR
    assert allotment.period_month == _MONTH
    assert float(allotment.allotted_usd) == 150.00
    assert float(allotment.rolled_over_usd) == 0.00
    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_get_or_create_allotment_returns_existing():
    """get_or_create_allotment returns the existing allotment without creating."""
    program = _make_program()
    existing_allotment = _make_allotment()

    db = AsyncMock()
    r_prog = MagicMock(); r_prog.scalar_one_or_none.return_value = program
    r_existing = MagicMock(); r_existing.scalar_one_or_none.return_value = existing_allotment
    db.execute.side_effect = [r_prog, r_existing]

    result = await get_or_create_allotment(db, _PROGRAM_ID, _MEMBER_ID, _YEAR, _MONTH)
    assert result.id == _ALLOTMENT_ID
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_create_allotment_applies_rollover():
    """get_or_create_allotment carries forward unused balance when rollover_enabled."""
    program = _make_program(rollover_enabled=True, monthly_allowance_usd=150.00)
    prior_allotment = _make_allotment(
        period_year=2026,
        period_month=3,
        allotted_usd=150.00,
        used_usd=100.00,
        rolled_over_usd=0.00,
    )  # remaining = 50.00

    db = AsyncMock()
    r_prog = MagicMock(); r_prog.scalar_one_or_none.return_value = program
    r_existing = MagicMock(); r_existing.scalar_one_or_none.return_value = None
    r_prior = MagicMock(); r_prior.scalar_one_or_none.return_value = prior_allotment
    db.execute.side_effect = [r_prog, r_existing, r_prior]

    allotment = await get_or_create_allotment(db, _PROGRAM_ID, _MEMBER_ID, _YEAR, _MONTH)
    assert float(allotment.rolled_over_usd) == 50.00


@pytest.mark.asyncio
async def test_get_or_create_allotment_rollover_capped():
    """get_or_create_allotment caps rollover at max_rollover_usd."""
    program = _make_program(
        rollover_enabled=True,
        monthly_allowance_usd=150.00,
        max_rollover_usd=30.00,
    )
    prior_allotment = _make_allotment(
        period_year=2026,
        period_month=3,
        allotted_usd=150.00,
        used_usd=50.00,
        rolled_over_usd=0.00,
    )  # remaining = 100.00, capped at 30.00

    db = AsyncMock()
    r_prog = MagicMock(); r_prog.scalar_one_or_none.return_value = program
    r_existing = MagicMock(); r_existing.scalar_one_or_none.return_value = None
    r_prior = MagicMock(); r_prior.scalar_one_or_none.return_value = prior_allotment
    db.execute.side_effect = [r_prog, r_existing, r_prior]

    allotment = await get_or_create_allotment(db, _PROGRAM_ID, _MEMBER_ID, _YEAR, _MONTH)
    assert float(allotment.rolled_over_usd) == 30.00


@pytest.mark.asyncio
async def test_get_or_create_allotment_no_rollover_when_no_prior():
    """get_or_create_allotment sets rolled_over_usd=0 when no prior month exists."""
    program = _make_program(rollover_enabled=True)

    db = AsyncMock()
    r_prog = MagicMock(); r_prog.scalar_one_or_none.return_value = program
    r_existing = MagicMock(); r_existing.scalar_one_or_none.return_value = None
    r_prior = MagicMock(); r_prior.scalar_one_or_none.return_value = None
    db.execute.side_effect = [r_prog, r_existing, r_prior]

    allotment = await get_or_create_allotment(db, _PROGRAM_ID, _MEMBER_ID, _YEAR, _MONTH)
    assert float(allotment.rolled_over_usd) == 0.00


# ---------------------------------------------------------------------------
# Service: list_allotments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_allotments_no_filters():
    """list_allotments returns all allotments for a program."""
    items = [_make_allotment(), _make_allotment(id=100, member_id=6)]
    db = _mock_db_with_list(items)
    result = await list_allotments(db, program_id=_PROGRAM_ID)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_allotments_filtered_by_month():
    """list_allotments with year/month filters builds correct query."""
    items = [_make_allotment()]
    db = _mock_db_with_list(items)
    result = await list_allotments(db, program_id=_PROGRAM_ID, year=_YEAR, month=_MONTH)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_allotments_filtered_by_member():
    """list_allotments with member_id filter builds correct query."""
    items = [_make_allotment()]
    db = _mock_db_with_list(items)
    result = await list_allotments(db, program_id=_PROGRAM_ID, member_id=_MEMBER_ID)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Service: get_member_allotment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_member_allotment_returns_allotment():
    """get_member_allotment returns allotment when program and allotment both exist."""
    program = _make_program()
    allotment = _make_allotment()

    db = AsyncMock()
    r_prog = MagicMock(); r_prog.scalar_one_or_none.return_value = program
    r_allot = MagicMock(); r_allot.scalar_one_or_none.return_value = allotment
    db.execute.side_effect = [r_prog, r_allot]

    result = await get_member_allotment(db, account_id=_ACCOUNT_ID, member_id=_MEMBER_ID, year=_YEAR, month=_MONTH)
    assert result is not None
    assert result.id == _ALLOTMENT_ID


@pytest.mark.asyncio
async def test_get_member_allotment_returns_none_when_no_program():
    """get_member_allotment returns None when the account has no commuter program."""
    db = _mock_db_with_one(None)
    result = await get_member_allotment(db, account_id=_ACCOUNT_ID, member_id=_MEMBER_ID, year=_YEAR, month=_MONTH)
    assert result is None


# ---------------------------------------------------------------------------
# Service: record_commuter_ride_usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_commuter_ride_usage_success():
    """record_commuter_ride_usage increments used_usd."""
    allotment = _make_allotment(allotted_usd=150.00, used_usd=50.00, rolled_over_usd=0.00)
    db = _mock_db_with_one(allotment)

    result = await record_commuter_ride_usage(db, _PROGRAM_ID, _MEMBER_ID, _YEAR, _MONTH, amount_usd=30.00)
    assert float(result.used_usd) == 80.00
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_record_commuter_ride_usage_exceeds_balance_raises_409():
    """record_commuter_ride_usage raises 409 when charge exceeds available balance."""
    allotment = _make_allotment(allotted_usd=150.00, used_usd=140.00, rolled_over_usd=0.00)
    db = _mock_db_with_one(allotment)

    with pytest.raises(HTTPException) as exc_info:
        await record_commuter_ride_usage(db, _PROGRAM_ID, _MEMBER_ID, _YEAR, _MONTH, amount_usd=20.00)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_record_commuter_ride_usage_allotment_not_found_raises_404():
    """record_commuter_ride_usage raises 404 when the allotment does not exist."""
    db = _mock_db_with_one(None)
    with pytest.raises(HTTPException) as exc_info:
        await record_commuter_ride_usage(db, _PROGRAM_ID, _MEMBER_ID, _YEAR, _MONTH, amount_usd=10.00)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: get_program_stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_program_stats_returns_correct_values():
    """get_program_stats returns correct aggregate statistics."""
    program = _make_program()

    db = AsyncMock()
    r_prog = MagicMock(); r_prog.scalar_one_or_none.return_value = program
    # Aggregate row: (count, sum_allotted, sum_used)
    r_agg = MagicMock()
    r_agg.one.return_value = (10, Decimal("1500.00"), Decimal("900.00"))
    db.execute.side_effect = [r_prog, r_agg]

    stats = await get_program_stats(db, account_id=_ACCOUNT_ID, year=_YEAR, month=_MONTH)
    assert stats.total_members_enrolled == 10
    assert stats.total_allotted == 1500.00
    assert stats.total_used == 900.00
    assert stats.total_remaining == 600.00
    assert stats.utilization_pct == 60.00


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_commuter_program_create_valid():
    data = CommuterProgramCreate(
        name="Employee Commuter Benefit",
        monthly_allowance_usd=150.00,
        rollover_enabled=True,
        max_rollover_usd=50.00,
        eligible_trip_purpose_ids=[1, 2],
    )
    assert data.name == "Employee Commuter Benefit"
    assert data.monthly_allowance_usd == 150.00
    assert data.rollover_enabled is True


def test_commuter_program_create_allowance_must_be_positive():
    with pytest.raises(ValidationError):
        CommuterProgramCreate(name="Bad", monthly_allowance_usd=0)


def test_commuter_program_update_all_optional():
    data = CommuterProgramUpdate()
    assert data.name is None
    assert data.monthly_allowance_usd is None
    assert data.rollover_enabled is None
    assert data.is_active is None


def test_commuter_program_response_from_attributes():
    program = _make_program()
    resp = CommuterProgramResponse.model_validate(program)
    assert resp.id == _PROGRAM_ID
    assert resp.name == "Employee Commuter Benefit"
    assert resp.is_active is True
    assert float(resp.monthly_allowance_usd) == 150.00


def test_commuter_allotment_response_from_attributes():
    allotment = _make_allotment()
    resp = CommuterAllotmentResponse.model_validate(allotment)
    assert resp.id == _ALLOTMENT_ID
    assert resp.program_id == _PROGRAM_ID
    assert resp.member_id == _MEMBER_ID
    assert resp.period_year == _YEAR
    assert resp.period_month == _MONTH


def test_commuter_stats_response_fields():
    stats = CommuterStatsResponse(
        total_members_enrolled=5,
        total_allotted=750.00,
        total_used=300.00,
        total_remaining=450.00,
        utilization_pct=40.0,
    )
    assert stats.total_members_enrolled == 5
    assert stats.utilization_pct == 40.0


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

_BASE = f"/api/v1/corporate/{_ACCOUNT_ID}/commuter-benefits"
_PLATFORM_BASE = "/api/v1/platform-admin/corporate-commuter-benefits"

_DUMMY_PROGRAM = _make_program()
_DUMMY_ALLOTMENT = _make_allotment()


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


# Member: get my allotment (200)
@patch(
    "app.api.v1.corporate_commuter_benefits._get_member_id_for_user",
    new_callable=AsyncMock,
    return_value=_MEMBER_ID,
)
@patch(
    "app.api.v1.corporate_commuter_benefits.get_member_allotment",
    new_callable=AsyncMock,
    return_value=_DUMMY_ALLOTMENT,
)
def test_api_get_my_allotment_200(mock_allot, mock_member):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/my-allotment?year={_YEAR}&month={_MONTH}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == _ALLOTMENT_ID


# Member: get my allotment (404 no allotment)
@patch(
    "app.api.v1.corporate_commuter_benefits._get_member_id_for_user",
    new_callable=AsyncMock,
    return_value=_MEMBER_ID,
)
@patch(
    "app.api.v1.corporate_commuter_benefits.get_member_allotment",
    new_callable=AsyncMock,
    return_value=None,
)
def test_api_get_my_allotment_404(mock_allot, mock_member):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/my-allotment?year={_YEAR}&month={_MONTH}")
    assert resp.status_code == 404


# Member: get my allotment history (200)
@patch(
    "app.api.v1.corporate_commuter_benefits._get_member_id_for_user",
    new_callable=AsyncMock,
    return_value=_MEMBER_ID,
)
@patch(
    "app.api.v1.corporate_commuter_benefits.get_program",
    new_callable=AsyncMock,
    return_value=_DUMMY_PROGRAM,
)
@patch(
    "app.api.v1.corporate_commuter_benefits.list_allotments",
    new_callable=AsyncMock,
    return_value=[_DUMMY_ALLOTMENT],
)
def test_api_get_my_allotment_history_200(mock_list, mock_prog, mock_member):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/my-allotment/history")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1


# Admin: create program (201)
@patch(
    "app.api.v1.corporate_commuter_benefits.create_program",
    new_callable=AsyncMock,
    return_value=_DUMMY_PROGRAM,
)
def test_api_create_program_201(mock_create):
    client = _make_app_client()
    resp = client.post(
        f"{_BASE}/program",
        json={"name": "Employee Commuter Benefit", "monthly_allowance_usd": 150.0},
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Employee Commuter Benefit"


# Admin: create program (409 duplicate)
@patch(
    "app.api.v1.corporate_commuter_benefits.create_program",
    new_callable=AsyncMock,
    side_effect=HTTPException(status_code=409, detail="Already exists"),
)
def test_api_create_program_409(mock_create):
    client = _make_app_client()
    resp = client.post(
        f"{_BASE}/program",
        json={"name": "Employee Commuter Benefit", "monthly_allowance_usd": 150.0},
    )
    assert resp.status_code == 409


# Admin/Member: get program (200)
@patch(
    "app.api.v1.corporate_commuter_benefits.get_program",
    new_callable=AsyncMock,
    return_value=_DUMMY_PROGRAM,
)
def test_api_get_program_200(mock_get):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/program")
    assert resp.status_code == 200
    assert resp.json()["id"] == _PROGRAM_ID


# Admin/Member: get program (404)
@patch(
    "app.api.v1.corporate_commuter_benefits.get_program",
    new_callable=AsyncMock,
    return_value=None,
)
def test_api_get_program_404(mock_get):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/program")
    assert resp.status_code == 404


# Admin: update program (200)
@patch(
    "app.api.v1.corporate_commuter_benefits.update_program",
    new_callable=AsyncMock,
    return_value=_DUMMY_PROGRAM,
)
def test_api_update_program_200(mock_update):
    client = _make_app_client()
    resp = client.patch(f"{_BASE}/program", json={"name": "Updated"})
    assert resp.status_code == 200


# Admin: deactivate program (200)
@patch(
    "app.api.v1.corporate_commuter_benefits.deactivate_program",
    new_callable=AsyncMock,
    return_value=_make_program(is_active=False),
)
def test_api_deactivate_program_200(mock_deactivate):
    client = _make_app_client()
    resp = client.post(f"{_BASE}/program/deactivate")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


# Admin: list allotments (200)
@patch(
    "app.api.v1.corporate_commuter_benefits.get_program",
    new_callable=AsyncMock,
    return_value=_DUMMY_PROGRAM,
)
@patch(
    "app.api.v1.corporate_commuter_benefits.list_allotments",
    new_callable=AsyncMock,
    return_value=[_DUMMY_ALLOTMENT],
)
def test_api_list_allotments_200(mock_list, mock_prog):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/allotments")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1


# Admin: program stats (200)
@patch(
    "app.api.v1.corporate_commuter_benefits.get_program_stats",
    new_callable=AsyncMock,
    return_value=CommuterStatsResponse(
        total_members_enrolled=10,
        total_allotted=1500.0,
        total_used=900.0,
        total_remaining=600.0,
        utilization_pct=60.0,
    ),
)
def test_api_get_program_stats_200(mock_stats):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/program/stats?year={_YEAR}&month={_MONTH}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_members_enrolled"] == 10
    assert data["utilization_pct"] == 60.0


# Platform-admin: list all programs (200)
def test_api_platform_admin_list_programs_200():
    """Platform admin list all programs endpoint returns 200 with paginated results."""
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = _USER_ID

    async def override_user():
        return mock_user

    async def override_admin():
        return mock_user

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [_DUMMY_PROGRAM]
    mock_db.execute.return_value = result

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[require_admin] = override_admin
    app.dependency_overrides[get_db] = override_db

    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get(f"{_PLATFORM_BASE}/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1


# Platform-admin: get program for specific account (200)
@patch(
    "app.api.v1.corporate_commuter_benefits.get_program",
    new_callable=AsyncMock,
    return_value=_DUMMY_PROGRAM,
)
def test_api_platform_admin_get_program_200(mock_get):
    client = _make_app_client()
    resp = client.get(f"{_PLATFORM_BASE}/{_ACCOUNT_ID}")
    assert resp.status_code == 200
    assert resp.json()["account_id"] == _ACCOUNT_ID


# Platform-admin: get program for specific account (404)
@patch(
    "app.api.v1.corporate_commuter_benefits.get_program",
    new_callable=AsyncMock,
    return_value=None,
)
def test_api_platform_admin_get_program_404(mock_get):
    client = _make_app_client()
    resp = client.get(f"{_PLATFORM_BASE}/9999")
    assert resp.status_code == 404
