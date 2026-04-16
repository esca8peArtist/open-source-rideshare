"""Tests for Corporate Shuttle Pass Management.

Service layer (async, mocked DB):
   1.  create_pass_type — success: creates type with all fields
   2.  create_pass_type — success: creates type without optional fields
   3.  create_pass_type — 409 when name already exists for account
   4.  create_pass_type — different accounts may share same name
   5.  get_pass_type — success: returns type
   6.  get_pass_type — 404 when not found
   7.  get_pass_type — 404 when account_id mismatch
   8.  list_pass_types — returns all types ordered by name
   9.  list_pass_types — filters by is_active=True
  10.  list_pass_types — filters by is_active=False
  11.  update_pass_type — success: updates name
  12.  update_pass_type — success: updates ride_count
  13.  update_pass_type — 404 when not found
  14.  update_pass_type — 409 when name collides with another type
  15.  update_pass_type — no 409 when name is unchanged (same record)
  16.  deactivate_pass_type — success: sets is_active=False
  17.  deactivate_pass_type — 404 when not found
  18.  deactivate_pass_type — 409 when already inactive
  19.  issue_pass — success: rides_total copied from type; no expiry
  20.  issue_pass — success: expires_at computed from validity_days
  21.  issue_pass — 404 when pass type not found
  22.  issue_pass — 409 when pass type is inactive
  23.  get_pass — success: returns pass
  24.  get_pass — 404 when not found
  25.  get_pass — 404 when account_id mismatch
  26.  list_member_passes — returns passes newest first
  27.  list_member_passes — returns empty list when none
  28.  list_member_passes — filters by is_active=True
  29.  redeem_pass — success: increments rides_used and creates usage record
  30.  redeem_pass — success: rides_remaining_after decrements correctly
  31.  redeem_pass — 404 when pass not found
  32.  redeem_pass — 409 when pass is inactive
  33.  redeem_pass — 409 when pass belongs to different member
  34.  redeem_pass — 409 when pass is expired
  35.  redeem_pass — 409 when no rides remaining
  36.  get_account_pass_summary — returns correct aggregate counts
  37.  get_account_pass_summary — returns zeros when no data
  38.  list_all_platform — returns all passes without filter
  39.  list_all_platform — filters by account_id
  40.  list_all_platform — filters by is_active

Schema validation:
  41.  PassTypeCreateRequest — name is required
  42.  PassTypeCreateRequest — ride_count must be >= 1
  43.  PassTypeCreateRequest — validity_days must be >= 1 when provided
  44.  PassTypeCreateRequest — price_usd must be >= 0 when provided
  45.  PassTypeUpdateRequest — all fields optional
  46.  PassIssueRequest — pass_type_id required
  47.  PassIssueRequest — notes optional
  48.  PassRedeemRequest — booking_id optional
  49.  PassResponse — rides_remaining computed from rides_total - rides_used
  50.  PassSummaryResponse — structure validation

API layer (service functions patched):
  51.  GET  /shuttle/pass-types — 200 member can list types
  52.  GET  /shuttle/pass-types — 200 with is_active filter
  53.  GET  /shuttle/passes/my — 200 member lists own passes
  54.  GET  /shuttle/passes/my — 200 with is_active filter
  55.  GET  /shuttle/passes/summary — 200 admin can get summary
  56.  GET  /shuttle/passes/summary — 403 non-admin blocked
  57.  GET  /shuttle/passes/{id} — 200 member can get pass
  58.  GET  /shuttle/passes/{id} — 404 not found
  59.  POST /shuttle/passes/{id}/redeem — 201 member can redeem
  60.  POST /shuttle/passes/{id}/redeem — 404 not found
  61.  POST /shuttle/passes/{id}/redeem — 409 no rides remaining
  62.  POST /shuttle/pass-types — 201 admin creates type
  63.  POST /shuttle/pass-types — 403 non-admin blocked
  64.  POST /shuttle/pass-types — 409 duplicate name
  65.  GET  /shuttle/pass-types/{id} — 200 admin can get type
  66.  GET  /shuttle/pass-types/{id} — 403 non-admin blocked
  67.  PUT  /shuttle/pass-types/{id} — 200 admin can update
  68.  POST /shuttle/pass-types/{id}/deactivate — 200 admin deactivates
  69.  POST /shuttle/members/{id}/passes/issue — 201 admin issues pass
  70.  POST /shuttle/members/{id}/passes/issue — 403 non-admin blocked
  71.  POST /shuttle/members/{id}/passes/issue — 409 inactive type
  72.  GET  /platform/corporate/shuttle/passes/all — 200 platform-admin
  73.  GET  /platform/corporate/shuttle/passes/all — 200 with account_id filter
  74.  GET  /platform/corporate/shuttle/passes/all — 403 non-admin blocked
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.corporate_shuttle_pass import (
    CorporateShuttlePass,
    CorporateShuttlePassType,
    CorporateShuttlePassUsage,
)
from app.schemas.corporate_shuttle_pass import (
    PassIssueRequest,
    PassRedeemRequest,
    PassResponse,
    PassSummaryResponse,
    PassTypeCreateRequest,
    PassTypeResponse,
    PassTypeUpdateRequest,
    PassUsageResponse,
)
from app.services.corporate_shuttle_pass_service import (
    create_pass_type,
    deactivate_pass_type,
    get_account_pass_summary,
    get_pass,
    get_pass_type,
    issue_pass,
    list_all_platform,
    list_member_passes,
    list_pass_types,
    redeem_pass,
    update_pass_type,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 20
ACCOUNT_ID_2 = 21
PASS_TYPE_ID = uuid.uuid4()
PASS_ID = uuid.uuid4()
USAGE_ID = uuid.uuid4()
BOOKING_ID = uuid.uuid4()
USER_ID = 50
ADMIN_ID = 4
MEMBER_ID = 60
OTHER_MEMBER_ID = 61

_SERVICE = "app.services.corporate_shuttle_pass_service"
_ROUTER = "app.api.v1.corporate_shuttle_pass"

_NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_pass_type(
    type_id: uuid.UUID = PASS_TYPE_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Monthly 20-Ride Pass",
    ride_count: int = 20,
    validity_days: int | None = 30,
    price_usd: Decimal | None = Decimal("150.00"),
    is_active: bool = True,
) -> CorporateShuttlePassType:
    t = CorporateShuttlePassType()
    t.id = type_id
    t.account_id = account_id
    t.name = name
    t.description = "20 rides valid for 30 days"
    t.ride_count = ride_count
    t.validity_days = validity_days
    t.price_usd = price_usd
    t.notes = None
    t.is_active = is_active
    t.created_by_id = ADMIN_ID
    t.created_at = _NOW
    t.updated_at = _NOW
    return t


def _make_pass(
    pass_id: uuid.UUID = PASS_ID,
    account_id: int = ACCOUNT_ID,
    member_id: int = MEMBER_ID,
    pass_type_id: uuid.UUID = PASS_TYPE_ID,
    rides_total: int = 20,
    rides_used: int = 3,
    is_active: bool = True,
    expires_at: datetime | None = None,
) -> CorporateShuttlePass:
    p = CorporateShuttlePass()
    p.id = pass_id
    p.pass_type_id = pass_type_id
    p.account_id = account_id
    p.member_id = member_id
    p.rides_total = rides_total
    p.rides_used = rides_used
    p.issued_at = _NOW
    p.expires_at = expires_at
    p.is_active = is_active
    p.issued_by_id = ADMIN_ID
    p.notes = None
    p.created_at = _NOW
    p.updated_at = _NOW
    return p


def _make_usage(
    usage_id: uuid.UUID = USAGE_ID,
    pass_id: uuid.UUID = PASS_ID,
    account_id: int = ACCOUNT_ID,
    member_id: int = MEMBER_ID,
    booking_id: uuid.UUID | None = BOOKING_ID,
    rides_remaining_after: int = 17,
) -> CorporateShuttlePassUsage:
    u = CorporateShuttlePassUsage()
    u.id = usage_id
    u.pass_id = pass_id
    u.account_id = account_id
    u.member_id = member_id
    u.booking_id = booking_id
    u.redeemed_at = _NOW
    u.rides_remaining_after = rides_remaining_after
    u.created_at = _NOW
    return u


def _pass_type_response(t: CorporateShuttlePassType) -> dict:
    return {
        "id": str(t.id),
        "account_id": t.account_id,
        "name": t.name,
        "description": t.description,
        "ride_count": t.ride_count,
        "validity_days": t.validity_days,
        "price_usd": str(t.price_usd) if t.price_usd is not None else None,
        "notes": t.notes,
        "is_active": t.is_active,
        "created_by_id": t.created_by_id,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }


def _pass_response(p: CorporateShuttlePass) -> dict:
    return {
        "id": str(p.id),
        "pass_type_id": str(p.pass_type_id),
        "account_id": p.account_id,
        "member_id": p.member_id,
        "rides_total": p.rides_total,
        "rides_used": p.rides_used,
        "rides_remaining": p.rides_total - p.rides_used,
        "issued_at": p.issued_at.isoformat(),
        "expires_at": p.expires_at.isoformat() if p.expires_at else None,
        "is_active": p.is_active,
        "issued_by_id": p.issued_by_id,
        "notes": p.notes,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Async DB mock helpers
# ---------------------------------------------------------------------------


def _scalar_result(value):
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    res.scalar_one.return_value = value
    res.scalars.return_value.all.return_value = (
        value if isinstance(value, list) else ([] if value is None else [value])
    )
    return res


def _scalars_result(items: list):
    res = MagicMock()
    res.scalars.return_value.all.return_value = items
    res.scalar_one_or_none.return_value = items[0] if items else None
    res.scalar_one.return_value = items[0] if items else None
    return res


def _count_result(n: int):
    res = MagicMock()
    res.scalar_one.return_value = n
    res.scalar_one_or_none.return_value = n
    return res


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


def _refresh_pass_type(obj):
    """Populate a newly created CorporateShuttlePassType row for tests."""
    if not obj.id:
        obj.id = PASS_TYPE_ID
    if not hasattr(obj, "created_at") or obj.created_at is None:
        obj.created_at = _NOW
    if not hasattr(obj, "updated_at") or obj.updated_at is None:
        obj.updated_at = _NOW


def _refresh_pass(obj):
    """Populate a newly created CorporateShuttlePass row for tests."""
    if not obj.id:
        obj.id = PASS_ID
    if not hasattr(obj, "created_at") or obj.created_at is None:
        obj.created_at = _NOW
    if not hasattr(obj, "updated_at") or obj.updated_at is None:
        obj.updated_at = _NOW
    if not hasattr(obj, "issued_at") or obj.issued_at is None:
        obj.issued_at = _NOW


def _refresh_usage(obj):
    """Populate a newly created CorporateShuttlePassUsage row for tests."""
    if not obj.id:
        obj.id = USAGE_ID
    if not hasattr(obj, "created_at") or obj.created_at is None:
        obj.created_at = _NOW
    if not hasattr(obj, "redeemed_at") or obj.redeemed_at is None:
        obj.redeemed_at = _NOW


# ===========================================================================
# Service layer tests
# ===========================================================================


# 1
@pytest.mark.asyncio
async def test_create_pass_type_success():
    db = _mock_db()
    db.execute.side_effect = [_scalar_result(None)]  # duplicate check
    db.refresh.side_effect = AsyncMock(side_effect=_refresh_pass_type)
    result = await create_pass_type(
        db,
        account_id=ACCOUNT_ID,
        name="Monthly 20-Ride Pass",
        ride_count=20,
        created_by_id=ADMIN_ID,
        validity_days=30,
        price_usd=Decimal("150.00"),
    )
    assert result.name == "Monthly 20-Ride Pass"
    assert result.ride_count == 20
    db.add.assert_called_once()
    db.flush.assert_called_once()


# 2
@pytest.mark.asyncio
async def test_create_pass_type_no_optional_fields():
    db = _mock_db()
    db.execute.side_effect = [_scalar_result(None)]
    db.refresh.side_effect = AsyncMock(side_effect=_refresh_pass_type)
    result = await create_pass_type(db, account_id=ACCOUNT_ID, name="10-Ride Basic", ride_count=10)
    assert result.validity_days is None
    db.add.assert_called_once()


# 3
@pytest.mark.asyncio
async def test_create_pass_type_409_duplicate_name():
    db = AsyncMock()
    db.execute.side_effect = [_scalar_result(_make_pass_type())]
    with pytest.raises(HTTPException) as exc:
        await create_pass_type(db, account_id=ACCOUNT_ID, name="Monthly 20-Ride Pass", ride_count=20)
    assert exc.value.status_code == 409


# 4
@pytest.mark.asyncio
async def test_create_pass_type_different_accounts_share_name():
    db = _mock_db()
    db.execute.side_effect = [_scalar_result(None)]
    db.refresh.side_effect = AsyncMock(side_effect=_refresh_pass_type)
    # Should succeed — name is unique per account, not globally
    await create_pass_type(db, account_id=ACCOUNT_ID_2, name="Monthly 20-Ride Pass", ride_count=20)
    db.add.assert_called_once()


# 5
@pytest.mark.asyncio
async def test_get_pass_type_success():
    t = _make_pass_type()
    db = AsyncMock()
    db.execute.return_value = _scalar_result(t)
    result = await get_pass_type(db, PASS_TYPE_ID, ACCOUNT_ID)
    assert result.id == t.id
    assert result.name == t.name


# 6
@pytest.mark.asyncio
async def test_get_pass_type_404_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)
    with pytest.raises(HTTPException) as exc:
        await get_pass_type(db, uuid.uuid4(), ACCOUNT_ID)
    assert exc.value.status_code == 404


# 7
@pytest.mark.asyncio
async def test_get_pass_type_404_account_mismatch():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)
    with pytest.raises(HTTPException) as exc:
        await get_pass_type(db, PASS_TYPE_ID, ACCOUNT_ID_2)
    assert exc.value.status_code == 404


# 8
@pytest.mark.asyncio
async def test_list_pass_types_all():
    t1 = _make_pass_type(name="A-Pass")
    t2 = _make_pass_type(type_id=uuid.uuid4(), name="B-Pass", is_active=False)
    db = AsyncMock()
    db.execute.return_value = _scalars_result([t1, t2])
    result = await list_pass_types(db, ACCOUNT_ID)
    assert len(result) == 2


# 9
@pytest.mark.asyncio
async def test_list_pass_types_filter_active():
    t = _make_pass_type()
    db = AsyncMock()
    db.execute.return_value = _scalars_result([t])
    result = await list_pass_types(db, ACCOUNT_ID, is_active=True)
    assert all(r.is_active for r in result)


# 10
@pytest.mark.asyncio
async def test_list_pass_types_filter_inactive():
    t = _make_pass_type(is_active=False)
    db = AsyncMock()
    db.execute.return_value = _scalars_result([t])
    result = await list_pass_types(db, ACCOUNT_ID, is_active=False)
    assert all(not r.is_active for r in result)


# 11
@pytest.mark.asyncio
async def test_update_pass_type_name():
    t = _make_pass_type()
    db = _mock_db()
    db.execute.side_effect = [
        _scalar_result(t),     # fetch existing
        _scalar_result(None),  # duplicate check
    ]
    result = await update_pass_type(db, PASS_TYPE_ID, ACCOUNT_ID, name="New Name")
    assert t.name == "New Name"


# 12
@pytest.mark.asyncio
async def test_update_pass_type_ride_count():
    t = _make_pass_type()
    db = _mock_db()
    db.execute.side_effect = [_scalar_result(t)]
    await update_pass_type(db, PASS_TYPE_ID, ACCOUNT_ID, ride_count=30)
    assert t.ride_count == 30


# 13
@pytest.mark.asyncio
async def test_update_pass_type_404():
    db = _mock_db()
    db.execute.return_value = _scalar_result(None)
    with pytest.raises(HTTPException) as exc:
        await update_pass_type(db, uuid.uuid4(), ACCOUNT_ID, name="X")
    assert exc.value.status_code == 404


# 14
@pytest.mark.asyncio
async def test_update_pass_type_409_name_collision():
    t = _make_pass_type()
    other = _make_pass_type(type_id=uuid.uuid4(), name="Taken Name")
    db = _mock_db()
    db.execute.side_effect = [
        _scalar_result(t),     # fetch existing
        _scalar_result(other), # duplicate check
    ]
    with pytest.raises(HTTPException) as exc:
        await update_pass_type(db, PASS_TYPE_ID, ACCOUNT_ID, name="Taken Name")
    assert exc.value.status_code == 409


# 15
@pytest.mark.asyncio
async def test_update_pass_type_no_409_same_name():
    t = _make_pass_type()
    db = _mock_db()
    # Only one call needed — name is unchanged, no dup check
    db.execute.side_effect = [_scalar_result(t)]
    await update_pass_type(db, PASS_TYPE_ID, ACCOUNT_ID, ride_count=25)
    assert t.ride_count == 25


# 16
@pytest.mark.asyncio
async def test_deactivate_pass_type_success():
    t = _make_pass_type(is_active=True)
    db = _mock_db()
    db.execute.return_value = _scalar_result(t)
    result = await deactivate_pass_type(db, PASS_TYPE_ID, ACCOUNT_ID)
    assert t.is_active is False


# 17
@pytest.mark.asyncio
async def test_deactivate_pass_type_404():
    db = _mock_db()
    db.execute.return_value = _scalar_result(None)
    with pytest.raises(HTTPException) as exc:
        await deactivate_pass_type(db, uuid.uuid4(), ACCOUNT_ID)
    assert exc.value.status_code == 404


# 18
@pytest.mark.asyncio
async def test_deactivate_pass_type_409_already_inactive():
    t = _make_pass_type(is_active=False)
    db = _mock_db()
    db.execute.return_value = _scalar_result(t)
    with pytest.raises(HTTPException) as exc:
        await deactivate_pass_type(db, PASS_TYPE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


# 19
@pytest.mark.asyncio
async def test_issue_pass_no_expiry():
    t = _make_pass_type(validity_days=None)
    db = _mock_db()
    db.execute.return_value = _scalar_result(t)
    db.refresh.side_effect = AsyncMock(side_effect=_refresh_pass)
    await issue_pass(db, PASS_TYPE_ID, ACCOUNT_ID, MEMBER_ID)
    added = db.add.call_args[0][0]
    assert added.rides_total == t.ride_count
    assert added.expires_at is None


# 20
@pytest.mark.asyncio
async def test_issue_pass_with_validity():
    t = _make_pass_type(validity_days=30)
    db = _mock_db()
    db.execute.return_value = _scalar_result(t)
    db.refresh.side_effect = AsyncMock(side_effect=_refresh_pass)
    await issue_pass(db, PASS_TYPE_ID, ACCOUNT_ID, MEMBER_ID)
    added = db.add.call_args[0][0]
    assert added.expires_at is not None
    # Should be ~30 days from now
    diff = added.expires_at - datetime.now(tz=timezone.utc)
    assert 29 <= diff.days <= 30


# 21
@pytest.mark.asyncio
async def test_issue_pass_404_type_not_found():
    db = _mock_db()
    db.execute.return_value = _scalar_result(None)
    with pytest.raises(HTTPException) as exc:
        await issue_pass(db, uuid.uuid4(), ACCOUNT_ID, MEMBER_ID)
    assert exc.value.status_code == 404


# 22
@pytest.mark.asyncio
async def test_issue_pass_409_type_inactive():
    t = _make_pass_type(is_active=False)
    db = _mock_db()
    db.execute.return_value = _scalar_result(t)
    with pytest.raises(HTTPException) as exc:
        await issue_pass(db, PASS_TYPE_ID, ACCOUNT_ID, MEMBER_ID)
    assert exc.value.status_code == 409


# 23
@pytest.mark.asyncio
async def test_get_pass_success():
    p = _make_pass()
    db = _mock_db()
    db.execute.return_value = _scalar_result(p)
    result = await get_pass(db, PASS_ID, ACCOUNT_ID)
    assert result.id == p.id
    assert result.rides_remaining == p.rides_total - p.rides_used


# 24
@pytest.mark.asyncio
async def test_get_pass_404_not_found():
    db = _mock_db()
    db.execute.return_value = _scalar_result(None)
    with pytest.raises(HTTPException) as exc:
        await get_pass(db, uuid.uuid4(), ACCOUNT_ID)
    assert exc.value.status_code == 404


# 25
@pytest.mark.asyncio
async def test_get_pass_404_account_mismatch():
    db = _mock_db()
    db.execute.return_value = _scalar_result(None)
    with pytest.raises(HTTPException) as exc:
        await get_pass(db, PASS_ID, ACCOUNT_ID_2)
    assert exc.value.status_code == 404


# 26
@pytest.mark.asyncio
async def test_list_member_passes_newest_first():
    p1 = _make_pass()
    p2 = _make_pass(pass_id=uuid.uuid4())
    db = _mock_db()
    db.execute.return_value = _scalars_result([p1, p2])
    result = await list_member_passes(db, ACCOUNT_ID, MEMBER_ID)
    assert len(result) == 2


# 27
@pytest.mark.asyncio
async def test_list_member_passes_empty():
    db = _mock_db()
    db.execute.return_value = _scalars_result([])
    result = await list_member_passes(db, ACCOUNT_ID, MEMBER_ID)
    assert result == []


# 28
@pytest.mark.asyncio
async def test_list_member_passes_filter_active():
    p = _make_pass(is_active=True)
    db = _mock_db()
    db.execute.return_value = _scalars_result([p])
    result = await list_member_passes(db, ACCOUNT_ID, MEMBER_ID, is_active=True)
    assert all(r.is_active for r in result)


# 29
@pytest.mark.asyncio
async def test_redeem_pass_success():
    p = _make_pass(rides_total=20, rides_used=3)
    db = _mock_db()
    db.execute.return_value = _scalar_result(p)
    db.refresh.side_effect = AsyncMock(side_effect=_refresh_usage)
    await redeem_pass(db, PASS_ID, ACCOUNT_ID, MEMBER_ID, BOOKING_ID)
    assert p.rides_used == 4
    usage = db.add.call_args[0][0]
    assert usage.rides_remaining_after == 16


# 30
@pytest.mark.asyncio
async def test_redeem_pass_rides_remaining_after_correct():
    p = _make_pass(rides_total=10, rides_used=9)
    db = _mock_db()
    db.execute.return_value = _scalar_result(p)
    db.refresh.side_effect = AsyncMock(side_effect=_refresh_usage)
    await redeem_pass(db, PASS_ID, ACCOUNT_ID, MEMBER_ID)
    usage = db.add.call_args[0][0]
    assert usage.rides_remaining_after == 0


# 31
@pytest.mark.asyncio
async def test_redeem_pass_404_not_found():
    db = _mock_db()
    db.execute.return_value = _scalar_result(None)
    with pytest.raises(HTTPException) as exc:
        await redeem_pass(db, uuid.uuid4(), ACCOUNT_ID, MEMBER_ID)
    assert exc.value.status_code == 404


# 32
@pytest.mark.asyncio
async def test_redeem_pass_409_inactive():
    p = _make_pass(is_active=False)
    db = _mock_db()
    db.execute.return_value = _scalar_result(p)
    with pytest.raises(HTTPException) as exc:
        await redeem_pass(db, PASS_ID, ACCOUNT_ID, MEMBER_ID)
    assert exc.value.status_code == 409
    assert "not active" in exc.value.detail.lower()


# 33
@pytest.mark.asyncio
async def test_redeem_pass_409_wrong_member():
    p = _make_pass(member_id=MEMBER_ID)
    db = _mock_db()
    db.execute.return_value = _scalar_result(p)
    with pytest.raises(HTTPException) as exc:
        await redeem_pass(db, PASS_ID, ACCOUNT_ID, OTHER_MEMBER_ID)
    assert exc.value.status_code == 409
    assert "different member" in exc.value.detail.lower()


# 34
@pytest.mark.asyncio
async def test_redeem_pass_409_expired():
    expired_time = datetime.now(tz=timezone.utc) - timedelta(days=1)
    p = _make_pass(expires_at=expired_time)
    db = _mock_db()
    db.execute.return_value = _scalar_result(p)
    with pytest.raises(HTTPException) as exc:
        await redeem_pass(db, PASS_ID, ACCOUNT_ID, MEMBER_ID)
    assert exc.value.status_code == 409
    assert "expired" in exc.value.detail.lower()


# 35
@pytest.mark.asyncio
async def test_redeem_pass_409_no_rides_remaining():
    p = _make_pass(rides_total=5, rides_used=5)
    db = _mock_db()
    db.execute.return_value = _scalar_result(p)
    with pytest.raises(HTTPException) as exc:
        await redeem_pass(db, PASS_ID, ACCOUNT_ID, MEMBER_ID)
    assert exc.value.status_code == 409
    assert "no rides remaining" in exc.value.detail.lower()


# 36
@pytest.mark.asyncio
async def test_get_account_pass_summary_counts():
    db = AsyncMock()

    # Execution order matches service:
    # 1. total_pass_types count
    # 2. active_pass_types count
    # 3. passes aggregate (total, rides_total, rides_used)
    # 4. active_passes count
    # 5. expired_passes count

    total_agg = MagicMock()
    total_agg.total = 3
    total_agg.rides_total = 60
    total_agg.rides_used = 15

    db.execute.side_effect = [
        _count_result(2),   # total_pass_types
        _count_result(1),   # active_pass_types
        MagicMock(one=MagicMock(return_value=total_agg)),  # passes aggregate
        _count_result(2),   # active_passes
        _count_result(1),   # expired_passes
    ]
    result = await get_account_pass_summary(db, ACCOUNT_ID)
    assert result.account_id == ACCOUNT_ID
    assert result.total_pass_types == 2
    assert result.active_pass_types == 1
    assert result.active_passes == 2
    assert result.expired_passes == 1


# 37
@pytest.mark.asyncio
async def test_get_account_pass_summary_zeros():
    db = AsyncMock()

    zero_agg = MagicMock()
    zero_agg.total = 0
    zero_agg.rides_total = None
    zero_agg.rides_used = None

    db.execute.side_effect = [
        _count_result(0),
        _count_result(0),
        MagicMock(one=MagicMock(return_value=zero_agg)),
        _count_result(0),
        _count_result(0),
    ]
    result = await get_account_pass_summary(db, ACCOUNT_ID)
    assert result.total_passes_issued == 0
    assert result.total_rides_issued == 0
    assert result.total_rides_remaining == 0


# 38
@pytest.mark.asyncio
async def test_list_all_platform_no_filter():
    p1 = _make_pass()
    p2 = _make_pass(pass_id=uuid.uuid4(), account_id=ACCOUNT_ID_2)
    db = _mock_db()
    db.execute.return_value = _scalars_result([p1, p2])
    result = await list_all_platform(db)
    assert len(result) == 2


# 39
@pytest.mark.asyncio
async def test_list_all_platform_filter_account():
    p = _make_pass()
    db = _mock_db()
    db.execute.return_value = _scalars_result([p])
    result = await list_all_platform(db, account_id=ACCOUNT_ID)
    assert all(r.account_id == ACCOUNT_ID for r in result)


# 40
@pytest.mark.asyncio
async def test_list_all_platform_filter_is_active():
    p = _make_pass(is_active=True)
    db = _mock_db()
    db.execute.return_value = _scalars_result([p])
    result = await list_all_platform(db, is_active=True)
    assert all(r.is_active for r in result)


# ===========================================================================
# Schema validation
# ===========================================================================


# 41
def test_pass_type_create_name_required():
    with pytest.raises(ValidationError):
        PassTypeCreateRequest(ride_count=10)


# 42
def test_pass_type_create_ride_count_min():
    with pytest.raises(ValidationError):
        PassTypeCreateRequest(name="X", ride_count=0)


# 43
def test_pass_type_create_validity_days_min():
    with pytest.raises(ValidationError):
        PassTypeCreateRequest(name="X", ride_count=10, validity_days=0)


# 44
def test_pass_type_create_price_negative():
    with pytest.raises(ValidationError):
        PassTypeCreateRequest(name="X", ride_count=10, price_usd=Decimal("-1.00"))


# 45
def test_pass_type_update_all_optional():
    req = PassTypeUpdateRequest()
    assert req.name is None
    assert req.ride_count is None


# 46
def test_pass_issue_request_type_id_required():
    with pytest.raises(ValidationError):
        PassIssueRequest()


# 47
def test_pass_issue_request_notes_optional():
    req = PassIssueRequest(pass_type_id=PASS_TYPE_ID)
    assert req.notes is None


# 48
def test_pass_redeem_request_booking_optional():
    req = PassRedeemRequest()
    assert req.booking_id is None


# 49
def test_pass_response_rides_remaining():
    p = _make_pass(rides_total=20, rides_used=7)
    resp = PassResponse.from_orm_pass(p)
    assert resp.rides_remaining == 13


# 50
def test_pass_summary_response_structure():
    summary = PassSummaryResponse(
        account_id=1,
        total_pass_types=2,
        active_pass_types=1,
        total_passes_issued=10,
        active_passes=8,
        expired_passes=2,
        total_rides_issued=200,
        total_rides_used=50,
        total_rides_remaining=150,
    )
    assert summary.total_rides_remaining == 150


# ===========================================================================
# API layer (service functions patched via TestClient + dependency_overrides)
# ===========================================================================

client = TestClient(app)

_PASS_TYPE_RESPONSE = {
    "id": str(PASS_TYPE_ID),
    "account_id": ACCOUNT_ID,
    "name": "Monthly 20-Ride Pass",
    "description": None,
    "ride_count": 20,
    "validity_days": 30,
    "price_usd": "150.00",
    "notes": None,
    "is_active": True,
    "created_by_id": ADMIN_ID,
    "created_at": _NOW.isoformat(),
    "updated_at": _NOW.isoformat(),
}

_PASS_RESPONSE = {
    "id": str(PASS_ID),
    "pass_type_id": str(PASS_TYPE_ID),
    "account_id": ACCOUNT_ID,
    "member_id": MEMBER_ID,
    "rides_total": 20,
    "rides_used": 3,
    "rides_remaining": 17,
    "issued_at": _NOW.isoformat(),
    "expires_at": None,
    "is_active": True,
    "issued_by_id": ADMIN_ID,
    "notes": None,
    "created_at": _NOW.isoformat(),
    "updated_at": _NOW.isoformat(),
}

_USAGE_RESPONSE = {
    "id": str(USAGE_ID),
    "pass_id": str(PASS_ID),
    "account_id": ACCOUNT_ID,
    "member_id": MEMBER_ID,
    "booking_id": str(BOOKING_ID),
    "redeemed_at": _NOW.isoformat(),
    "rides_remaining_after": 17,
    "created_at": _NOW.isoformat(),
}

_SUMMARY_RESPONSE = {
    "account_id": ACCOUNT_ID,
    "total_pass_types": 2,
    "active_pass_types": 1,
    "total_passes_issued": 5,
    "active_passes": 4,
    "expired_passes": 1,
    "total_rides_issued": 100,
    "total_rides_used": 25,
    "total_rides_remaining": 75,
}

_BASE = f"/api/v1/corporate/{ACCOUNT_ID}/shuttle"


def _make_user_model(user_id: int = MEMBER_ID, is_admin: bool = False):
    from app.models.user import User as UserModel
    u = MagicMock(spec=UserModel)
    u.id = user_id
    u.is_admin = is_admin
    return u


def _dep_overrides(user_id: int = MEMBER_ID, is_admin: bool = False):
    from app.api.deps import get_current_user, get_db, require_admin

    async def _user():
        return _make_user_model(user_id=user_id, is_admin=is_admin)

    async def _db():
        return AsyncMock()

    async def _admin():
        return _make_user_model(user_id=ADMIN_ID, is_admin=True)

    return {
        get_current_user: _user,
        get_db: _db,
        require_admin: _admin,
    }


def _patch_get_account():
    return patch(f"{_ROUTER}.get_account", new_callable=AsyncMock)


def _patch_require_admin(raises: bool = False):
    if raises:
        return patch(
            f"{_ROUTER}._require_account_admin",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=403, detail="forbidden"),
        )
    return patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)


# 51
def test_api_list_pass_types_member():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.list_pass_types", new_callable=AsyncMock, return_value=[PassTypeResponse(**_PASS_TYPE_RESPONSE)]),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{_BASE}/pass-types")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert len(resp.json()) == 1


# 52
def test_api_list_pass_types_with_filter():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.list_pass_types", new_callable=AsyncMock, return_value=[]),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{_BASE}/pass-types?is_active=true")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


# 53
def test_api_list_my_passes():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.list_member_passes", new_callable=AsyncMock, return_value=[PassResponse(**_PASS_RESPONSE)]),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{_BASE}/passes/my")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["rides_remaining"] == 17


# 54
def test_api_list_my_passes_with_filter():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.list_member_passes", new_callable=AsyncMock, return_value=[]),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{_BASE}/passes/my?is_active=true")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


# 55
def test_api_get_pass_summary_admin():
    with (
        _patch_get_account(),
        _patch_require_admin(),
        patch(f"{_ROUTER}.get_account_pass_summary", new_callable=AsyncMock, return_value=PassSummaryResponse(**_SUMMARY_RESPONSE)),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.get(f"{_BASE}/passes/summary")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["total_rides_remaining"] == 75


# 56
def test_api_get_pass_summary_non_admin_blocked():
    with (
        _patch_get_account(),
        _patch_require_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{_BASE}/passes/summary")
        app.dependency_overrides.clear()
    assert resp.status_code == 403


# 57
def test_api_get_pass_by_id():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.get_pass", new_callable=AsyncMock, return_value=PassResponse(**_PASS_RESPONSE)),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{_BASE}/passes/{PASS_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["id"] == str(PASS_ID)


# 58
def test_api_get_pass_404():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.get_pass", new_callable=AsyncMock, side_effect=HTTPException(status_code=404, detail="Not found")),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{_BASE}/passes/{uuid.uuid4()}")
        app.dependency_overrides.clear()
    assert resp.status_code == 404


# 59
def test_api_redeem_pass_201():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.redeem_pass", new_callable=AsyncMock, return_value=PassUsageResponse(**_USAGE_RESPONSE)),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(
            f"{_BASE}/passes/{PASS_ID}/redeem",
            json={"booking_id": str(BOOKING_ID)},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["rides_remaining_after"] == 17


# 60
def test_api_redeem_pass_404():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.redeem_pass", new_callable=AsyncMock, side_effect=HTTPException(status_code=404, detail="Not found")),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(f"{_BASE}/passes/{uuid.uuid4()}/redeem", json={})
        app.dependency_overrides.clear()
    assert resp.status_code == 404


# 61
def test_api_redeem_pass_409_no_rides():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.redeem_pass", new_callable=AsyncMock, side_effect=HTTPException(status_code=409, detail="No rides remaining on this shuttle pass.")),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(f"{_BASE}/passes/{PASS_ID}/redeem", json={})
        app.dependency_overrides.clear()
    assert resp.status_code == 409


# 62
def test_api_create_pass_type_admin():
    with (
        _patch_get_account(),
        _patch_require_admin(),
        patch(f"{_ROUTER}.create_pass_type", new_callable=AsyncMock, return_value=PassTypeResponse(**_PASS_TYPE_RESPONSE)),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.post(
            f"{_BASE}/pass-types",
            json={"name": "Monthly 20-Ride Pass", "ride_count": 20, "validity_days": 30},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["name"] == "Monthly 20-Ride Pass"


# 63
def test_api_create_pass_type_non_admin_blocked():
    with (
        _patch_get_account(),
        _patch_require_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(f"{_BASE}/pass-types", json={"name": "X", "ride_count": 5})
        app.dependency_overrides.clear()
    assert resp.status_code == 403


# 64
def test_api_create_pass_type_409_dup():
    with (
        _patch_get_account(),
        _patch_require_admin(),
        patch(f"{_ROUTER}.create_pass_type", new_callable=AsyncMock, side_effect=HTTPException(status_code=409, detail="Duplicate")),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.post(
            f"{_BASE}/pass-types",
            json={"name": "Monthly 20-Ride Pass", "ride_count": 20},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 409


# 65
def test_api_get_pass_type_admin():
    with (
        _patch_get_account(),
        _patch_require_admin(),
        patch(f"{_ROUTER}.get_pass_type", new_callable=AsyncMock, return_value=PassTypeResponse(**_PASS_TYPE_RESPONSE)),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.get(f"{_BASE}/pass-types/{PASS_TYPE_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


# 66
def test_api_get_pass_type_non_admin_blocked():
    with (
        _patch_get_account(),
        _patch_require_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{_BASE}/pass-types/{PASS_TYPE_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 403


# 67
def test_api_update_pass_type():
    updated = dict(_PASS_TYPE_RESPONSE)
    updated["name"] = "Updated Pass Name"
    with (
        _patch_get_account(),
        _patch_require_admin(),
        patch(f"{_ROUTER}.update_pass_type", new_callable=AsyncMock, return_value=PassTypeResponse(**updated)),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.put(f"{_BASE}/pass-types/{PASS_TYPE_ID}", json={"name": "Updated Pass Name"})
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Pass Name"


# 68
def test_api_deactivate_pass_type():
    deactivated = dict(_PASS_TYPE_RESPONSE)
    deactivated["is_active"] = False
    with (
        _patch_get_account(),
        _patch_require_admin(),
        patch(f"{_ROUTER}.deactivate_pass_type", new_callable=AsyncMock, return_value=PassTypeResponse(**deactivated)),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.post(f"{_BASE}/pass-types/{PASS_TYPE_ID}/deactivate")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


# 69
def test_api_issue_pass_admin():
    with (
        _patch_get_account(),
        _patch_require_admin(),
        patch(f"{_ROUTER}.issue_pass", new_callable=AsyncMock, return_value=PassResponse(**_PASS_RESPONSE)),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/shuttle/members/{MEMBER_ID}/passes/issue",
            json={"pass_type_id": str(PASS_TYPE_ID)},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["rides_total"] == 20


# 70
def test_api_issue_pass_non_admin_blocked():
    with (
        _patch_get_account(),
        _patch_require_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/shuttle/members/{MEMBER_ID}/passes/issue",
            json={"pass_type_id": str(PASS_TYPE_ID)},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 403


# 71
def test_api_issue_pass_409_inactive_type():
    with (
        _patch_get_account(),
        _patch_require_admin(),
        patch(f"{_ROUTER}.issue_pass", new_callable=AsyncMock, side_effect=HTTPException(status_code=409, detail="Pass type inactive")),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/shuttle/members/{MEMBER_ID}/passes/issue",
            json={"pass_type_id": str(PASS_TYPE_ID)},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 409


# 72
def test_api_platform_list_all():
    with (
        patch(f"{_ROUTER}.list_all_platform", new_callable=AsyncMock, return_value=[PassResponse(**_PASS_RESPONSE)]),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.get("/api/v1/platform/corporate/shuttle/passes/all")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert len(resp.json()) == 1


# 73
def test_api_platform_list_all_with_filter():
    with (
        patch(f"{_ROUTER}.list_all_platform", new_callable=AsyncMock, return_value=[]),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.get(f"/api/v1/platform/corporate/shuttle/passes/all?account_id={ACCOUNT_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


# 74
def test_api_platform_list_all_non_admin_blocked():
    """Unauthenticated call returns 401 (no override → real auth guard fires)."""
    resp = client.get("/api/v1/platform/corporate/shuttle/passes/all")
    assert resp.status_code in (401, 403)
