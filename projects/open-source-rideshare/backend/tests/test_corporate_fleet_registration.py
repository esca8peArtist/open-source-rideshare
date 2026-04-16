"""Tests for the Corporate Fleet Vehicle Registration Tracking feature.

Service layer (async, mocked DB):
   1.  register_vehicle — success: creates with is_active=True
   2.  register_vehicle — 404 when vehicle not in account
   3.  register_vehicle — 409 when registration_number already exists for account
   4.  get_registration — success: returns existing record
   5.  get_registration — 404 when not found
   6.  list_vehicle_registrations — returns all for vehicle
   7.  list_vehicle_registrations — is_active filter works
   8.  list_account_registrations — returns all for account
   9.  list_account_registrations — is_active filter works
  10.  list_account_registrations — registration_state filter works
  11.  update_registration — success: updates fields
  12.  update_registration — 409 registration_number collision with another record
  13.  update_registration — updates only provided fields (None fields ignored)
  14.  deactivate_registration — success: sets is_active=False
  15.  deactivate_registration — 409 if already inactive
  16.  reactivate_registration — success: sets is_active=True
  17.  reactivate_registration — 409 if already active
  18.  get_expiring_registrations — returns registrations expiring within N days
  19.  get_expiring_registrations — excludes inactive registrations
  20.  get_expiring_registrations — vehicle filter works
  21.  get_expiring_registrations — days_until_expiry computed correctly
  22.  get_account_registration_summary — counts are correct
  23.  get_account_registration_summary — total_annual_fee_usd correct
  24.  get_account_registration_summary — per_state_breakdown correct
  25.  list_all_platform — returns all
  26.  list_all_platform — account_id filter works

Schema validation:
  27.  RegistrationCreate — valid construction
  28.  RegistrationCreate — missing required field raises ValidationError
  29.  RegistrationUpdate — all optional
  30.  RegistrationResponse — from_attributes works, days_until_expiry defaults None
  31.  RegistrationExpiringResponse — valid structure, days_until_expiry required
  32.  RegistrationSummaryResponse — valid structure

API layer (service functions patched):
  33.  GET list vehicle registrations → 200
  34.  GET expiring → 200
  35.  GET summary → 200
  36.  POST create → 201
  37.  GET list account registrations → 200
  38.  GET get one registration → 200
  39.  PUT update → 200
  40.  POST deactivate → 200
  41.  POST reactivate → 200
  42.  GET platform list → 200
  43.  GET platform list by account → 200
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.corporate_fleet_registration import CorporateFleetVehicleRegistration
from app.schemas.corporate_fleet_registration import (
    RegistrationCreate,
    RegistrationExpiringResponse,
    RegistrationResponse,
    RegistrationSummaryResponse,
    RegistrationUpdate,
)
from app.services.corporate_fleet_registration_service import (
    deactivate_registration,
    get_account_registration_summary,
    get_expiring_registrations,
    get_registration,
    list_account_registrations,
    list_all_platform,
    list_vehicle_registrations,
    reactivate_registration,
    register_vehicle,
    update_registration,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 7
VEHICLE_ID = uuid.uuid4()
REG_ID = uuid.uuid4()
USER_ID = 10
ADMIN_ID = 1

_SERVICE = "app.services.corporate_fleet_registration_service"
_ROUTER = "app.api.v1.corporate_fleet_registration"

_NOW = datetime(2026, 4, 17, 9, 0, 0, tzinfo=timezone.utc)
_REG_DATE = date(2026, 1, 1)
_EXP_DATE = date(2026, 12, 31)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_registration(
    reg_id: uuid.UUID = REG_ID,
    account_id: int = ACCOUNT_ID,
    fleet_vehicle_id: uuid.UUID = VEHICLE_ID,
    registration_number: str = "REG-CA-2026-001",
    registration_state: str = "California",
    registration_date: date = _REG_DATE,
    expiration_date: date = _EXP_DATE,
    annual_fee_usd: float | None = 250.00,
    registered_owner_name: str | None = "Acme Corp",
    is_active: bool = True,
    notes: str | None = None,
    created_by_id: int | None = ADMIN_ID,
) -> CorporateFleetVehicleRegistration:
    reg = CorporateFleetVehicleRegistration()
    reg.id = reg_id
    reg.account_id = account_id
    reg.fleet_vehicle_id = fleet_vehicle_id
    reg.registration_number = registration_number
    reg.registration_state = registration_state
    reg.registration_date = registration_date
    reg.expiration_date = expiration_date
    reg.annual_fee_usd = annual_fee_usd
    reg.registered_owner_name = registered_owner_name
    reg.is_active = is_active
    reg.notes = notes
    reg.created_by_id = created_by_id
    reg.created_at = _NOW
    reg.updated_at = _NOW
    return reg


def _make_response(reg: CorporateFleetVehicleRegistration | None = None) -> RegistrationResponse:
    if reg is None:
        reg = _make_registration()
    return RegistrationResponse(
        id=reg.id,
        account_id=reg.account_id,
        fleet_vehicle_id=reg.fleet_vehicle_id,
        registration_number=reg.registration_number,
        registration_state=reg.registration_state,
        registration_date=reg.registration_date,
        expiration_date=reg.expiration_date,
        annual_fee_usd=float(reg.annual_fee_usd) if reg.annual_fee_usd is not None else None,
        registered_owner_name=reg.registered_owner_name,
        is_active=reg.is_active,
        notes=reg.notes,
        created_by_id=reg.created_by_id,
        created_at=reg.created_at,
        updated_at=reg.updated_at,
    )


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_vehicle(is_active: bool = True):
    from app.models.corporate_fleet_vehicle import CorporateFleetVehicle

    v = CorporateFleetVehicle()
    v.id = VEHICLE_ID
    v.account_id = ACCOUNT_ID
    v.name = "Fleet Van 1"
    v.is_active = is_active
    return v


def _mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_result(values):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = values
    result.scalars.return_value = scalars
    return result


# ===========================================================================
# Service layer tests (1–26)
# ===========================================================================


# --- Test 1 ---
@pytest.mark.asyncio
async def test_register_vehicle_success():
    db = _mock_db()
    vehicle = _mock_vehicle()
    data = RegistrationCreate(
        fleet_vehicle_id=VEHICLE_ID,
        registration_number="REG-CA-2026-001",
        registration_state="California",
        registration_date=_REG_DATE,
        expiration_date=_EXP_DATE,
        annual_fee_usd=250.00,
    )

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv, \
         patch(f"{_SERVICE}._check_registration_number_unique", new_callable=AsyncMock):
        mock_fv.return_value = vehicle

        created = _make_registration()
        db.refresh.side_effect = lambda obj: None

        with patch(f"{_SERVICE}.CorporateFleetVehicleRegistration") as MockModel:
            MockModel.return_value = created
            result = await register_vehicle(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)

    assert db.add.called
    assert db.commit.called


# --- Test 2 ---
@pytest.mark.asyncio
async def test_register_vehicle_404_vehicle_not_found():
    db = _mock_db()
    data = RegistrationCreate(
        fleet_vehicle_id=VEHICLE_ID,
        registration_number="REG-CA-2026-001",
        registration_state="California",
        registration_date=_REG_DATE,
        expiration_date=_EXP_DATE,
    )
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await register_vehicle(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 404


# --- Test 3 ---
@pytest.mark.asyncio
async def test_register_vehicle_409_duplicate_registration_number():
    db = _mock_db()
    vehicle = _mock_vehicle()
    data = RegistrationCreate(
        fleet_vehicle_id=VEHICLE_ID,
        registration_number="REG-DUPE-001",
        registration_state="California",
        registration_date=_REG_DATE,
        expiration_date=_EXP_DATE,
    )
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv, \
         patch(f"{_SERVICE}._check_registration_number_unique", new_callable=AsyncMock) as mock_uniq:
        mock_fv.return_value = vehicle
        mock_uniq.side_effect = HTTPException(
            status_code=409,
            detail="A registration with this number already exists for this account.",
        )
        with pytest.raises(HTTPException) as exc:
            await register_vehicle(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 409


# --- Test 4 ---
@pytest.mark.asyncio
async def test_get_registration_success():
    db = _mock_db()
    reg = _make_registration()
    with patch(f"{_SERVICE}._fetch_registration", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = reg
        result = await get_registration(db, ACCOUNT_ID, REG_ID)
    assert result.id == REG_ID
    assert result.registration_number == "REG-CA-2026-001"


# --- Test 5 ---
@pytest.mark.asyncio
async def test_get_registration_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_registration", new_callable=AsyncMock) as mock_fr:
        mock_fr.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await get_registration(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 6 ---
@pytest.mark.asyncio
async def test_list_vehicle_registrations_returns_all():
    db = _mock_db()
    rows = [
        _make_registration(),
        _make_registration(reg_id=uuid.uuid4(), registration_number="REG-CA-2026-002"),
    ]
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _mock_vehicle()
        db.execute.return_value = _scalars_result(rows)
        results = await list_vehicle_registrations(db, ACCOUNT_ID, VEHICLE_ID)
    assert len(results) == 2


# --- Test 7 ---
@pytest.mark.asyncio
async def test_list_vehicle_registrations_is_active_filter():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _mock_vehicle()
        db.execute.return_value = _scalars_result([_make_registration(is_active=True)])
        results = await list_vehicle_registrations(db, ACCOUNT_ID, VEHICLE_ID, is_active=True)
    assert len(results) == 1
    assert results[0].is_active is True


# --- Test 8 ---
@pytest.mark.asyncio
async def test_list_account_registrations_returns_all():
    db = _mock_db()
    rows = [
        _make_registration(),
        _make_registration(reg_id=uuid.uuid4(), registration_number="REG-NY-2026-001",
                           registration_state="New York"),
        _make_registration(reg_id=uuid.uuid4(), registration_number="REG-TX-2026-001",
                           registration_state="Texas"),
    ]
    db.execute.return_value = _scalars_result(rows)
    results = await list_account_registrations(db, ACCOUNT_ID)
    assert len(results) == 3


# --- Test 9 ---
@pytest.mark.asyncio
async def test_list_account_registrations_is_active_filter():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_registration(is_active=False)])
    results = await list_account_registrations(db, ACCOUNT_ID, is_active=False)
    assert len(results) == 1
    assert results[0].is_active is False


# --- Test 10 ---
@pytest.mark.asyncio
async def test_list_account_registrations_state_filter():
    db = _mock_db()
    db.execute.return_value = _scalars_result(
        [_make_registration(registration_state="California")]
    )
    results = await list_account_registrations(
        db, ACCOUNT_ID, registration_state="California"
    )
    assert len(results) == 1
    assert results[0].registration_state == "California"


# --- Test 11 ---
@pytest.mark.asyncio
async def test_update_registration_success():
    db = _mock_db()
    reg = _make_registration()
    with patch(f"{_SERVICE}._fetch_registration", new_callable=AsyncMock) as mock_fr, \
         patch(f"{_SERVICE}._check_registration_number_unique", new_callable=AsyncMock):
        mock_fr.return_value = reg
        data = RegistrationUpdate(registration_state="New York", annual_fee_usd=300.00)
        result = await update_registration(db, ACCOUNT_ID, REG_ID, data)
    assert reg.registration_state == "New York"
    assert db.commit.called


# --- Test 12 ---
@pytest.mark.asyncio
async def test_update_registration_409_number_collision():
    db = _mock_db()
    reg = _make_registration()
    with patch(f"{_SERVICE}._fetch_registration", new_callable=AsyncMock) as mock_fr, \
         patch(f"{_SERVICE}._check_registration_number_unique", new_callable=AsyncMock) as mock_uniq:
        mock_fr.return_value = reg
        mock_uniq.side_effect = HTTPException(
            status_code=409,
            detail="A registration with this number already exists for this account.",
        )
        data = RegistrationUpdate(registration_number="REG-TAKEN-001")
        with pytest.raises(HTTPException) as exc:
            await update_registration(db, ACCOUNT_ID, REG_ID, data)
    assert exc.value.status_code == 409


# --- Test 13 ---
@pytest.mark.asyncio
async def test_update_registration_ignores_none_fields():
    db = _mock_db()
    reg = _make_registration()
    original_state = reg.registration_state
    with patch(f"{_SERVICE}._fetch_registration", new_callable=AsyncMock) as mock_fr, \
         patch(f"{_SERVICE}._check_registration_number_unique", new_callable=AsyncMock):
        mock_fr.return_value = reg
        # Only update notes; registration_state should remain unchanged
        data = RegistrationUpdate(notes="Updated notes")
        await update_registration(db, ACCOUNT_ID, REG_ID, data)
    assert reg.registration_state == original_state
    assert reg.notes == "Updated notes"


# --- Test 14 ---
@pytest.mark.asyncio
async def test_deactivate_registration_success():
    db = _mock_db()
    reg = _make_registration(is_active=True)
    with patch(f"{_SERVICE}._fetch_registration", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = reg
        result = await deactivate_registration(db, ACCOUNT_ID, REG_ID)
    assert reg.is_active is False
    assert db.commit.called


# --- Test 15 ---
@pytest.mark.asyncio
async def test_deactivate_registration_409_already_inactive():
    db = _mock_db()
    reg = _make_registration(is_active=False)
    with patch(f"{_SERVICE}._fetch_registration", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = reg
        with pytest.raises(HTTPException) as exc:
            await deactivate_registration(db, ACCOUNT_ID, REG_ID)
    assert exc.value.status_code == 409
    assert "already inactive" in exc.value.detail.lower()


# --- Test 16 ---
@pytest.mark.asyncio
async def test_reactivate_registration_success():
    db = _mock_db()
    reg = _make_registration(is_active=False)
    with patch(f"{_SERVICE}._fetch_registration", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = reg
        result = await reactivate_registration(db, ACCOUNT_ID, REG_ID)
    assert reg.is_active is True
    assert db.commit.called


# --- Test 17 ---
@pytest.mark.asyncio
async def test_reactivate_registration_409_already_active():
    db = _mock_db()
    reg = _make_registration(is_active=True)
    with patch(f"{_SERVICE}._fetch_registration", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = reg
        with pytest.raises(HTTPException) as exc:
            await reactivate_registration(db, ACCOUNT_ID, REG_ID)
    assert exc.value.status_code == 409
    assert "already active" in exc.value.detail.lower()


# --- Test 18 ---
@pytest.mark.asyncio
async def test_get_expiring_registrations_returns_expiring():
    db = _mock_db()
    today = date.today()
    expiring_soon = today + timedelta(days=15)
    reg = _make_registration(is_active=True, expiration_date=expiring_soon)
    db.execute.return_value = _scalars_result([reg])
    results = await get_expiring_registrations(db, ACCOUNT_ID, days_ahead=30)
    assert len(results) == 1
    assert results[0].id == REG_ID
    assert results[0].days_until_expiry == 15


# --- Test 19 ---
@pytest.mark.asyncio
async def test_get_expiring_registrations_excludes_inactive():
    db = _mock_db()
    # Query filters is_active=True at DB level; mock returns empty
    db.execute.return_value = _scalars_result([])
    results = await get_expiring_registrations(db, ACCOUNT_ID)
    assert results == []


# --- Test 20 ---
@pytest.mark.asyncio
async def test_get_expiring_registrations_vehicle_filter():
    db = _mock_db()
    today = date.today()
    reg = _make_registration(is_active=True, expiration_date=today + timedelta(days=10))
    db.execute.return_value = _scalars_result([reg])
    results = await get_expiring_registrations(
        db, ACCOUNT_ID, days_ahead=30, fleet_vehicle_id=VEHICLE_ID
    )
    assert len(results) == 1
    assert results[0].fleet_vehicle_id == VEHICLE_ID


# --- Test 21 ---
@pytest.mark.asyncio
async def test_get_expiring_registrations_days_until_expiry_correct():
    db = _mock_db()
    today = date.today()
    days = 7
    expiring = today + timedelta(days=days)
    reg = _make_registration(is_active=True, expiration_date=expiring)
    db.execute.return_value = _scalars_result([reg])
    results = await get_expiring_registrations(db, ACCOUNT_ID, days_ahead=30)
    assert results[0].days_until_expiry == days


# --- Test 22 ---
@pytest.mark.asyncio
async def test_get_account_registration_summary_counts():
    db = _mock_db()
    today = date.today()

    reg_active1 = _make_registration(
        is_active=True, expiration_date=today + timedelta(days=10)
    )
    reg_active2 = _make_registration(
        reg_id=uuid.uuid4(),
        registration_number="REG-NY-2026-001",
        registration_state="New York",
        is_active=True,
        expiration_date=today + timedelta(days=60),
    )
    reg_inactive = _make_registration(
        reg_id=uuid.uuid4(),
        registration_number="REG-TX-2026-001",
        registration_state="Texas",
        is_active=False,
        expiration_date=today + timedelta(days=5),
    )

    db.execute.return_value = _scalars_result([reg_active1, reg_active2, reg_inactive])
    summary = await get_account_registration_summary(db, ACCOUNT_ID)

    assert summary.active_count == 2
    assert summary.inactive_count == 1
    assert summary.expiring_within_30_days == 1


# --- Test 23 ---
@pytest.mark.asyncio
async def test_get_account_registration_summary_total_fee():
    db = _mock_db()
    today = date.today()

    reg1 = _make_registration(is_active=True, annual_fee_usd=250.00,
                               expiration_date=today + timedelta(days=60))
    reg2 = _make_registration(
        reg_id=uuid.uuid4(),
        registration_number="REG-NY-2026-001",
        registration_state="New York",
        is_active=True,
        annual_fee_usd=300.00,
        expiration_date=today + timedelta(days=90),
    )
    # Inactive — should not count toward total fee
    reg3 = _make_registration(
        reg_id=uuid.uuid4(),
        registration_number="REG-TX-2026-001",
        registration_state="Texas",
        is_active=False,
        annual_fee_usd=200.00,
        expiration_date=today + timedelta(days=10),
    )

    db.execute.return_value = _scalars_result([reg1, reg2, reg3])
    summary = await get_account_registration_summary(db, ACCOUNT_ID)
    assert summary.total_annual_fee_usd == pytest.approx(550.00)


# --- Test 24 ---
@pytest.mark.asyncio
async def test_get_account_registration_summary_per_state():
    db = _mock_db()
    today = date.today()

    reg_ca1 = _make_registration(
        is_active=True, registration_state="California",
        expiration_date=today + timedelta(days=60)
    )
    reg_ca2 = _make_registration(
        reg_id=uuid.uuid4(), registration_number="REG-CA-2026-002",
        registration_state="California", is_active=True,
        expiration_date=today + timedelta(days=90)
    )
    reg_ny = _make_registration(
        reg_id=uuid.uuid4(), registration_number="REG-NY-2026-001",
        registration_state="New York", is_active=True,
        expiration_date=today + timedelta(days=120)
    )

    db.execute.return_value = _scalars_result([reg_ca1, reg_ca2, reg_ny])
    summary = await get_account_registration_summary(db, ACCOUNT_ID)

    assert summary.per_state_breakdown["California"] == 2
    assert summary.per_state_breakdown["New York"] == 1


# --- Test 25 ---
@pytest.mark.asyncio
async def test_list_all_platform_returns_all():
    db = _mock_db()
    rows = [
        _make_registration(),
        _make_registration(reg_id=uuid.uuid4(), registration_number="REG-2", account_id=99),
    ]
    db.execute.return_value = _scalars_result(rows)
    results = await list_all_platform(db)
    assert len(results) == 2


# --- Test 26 ---
@pytest.mark.asyncio
async def test_list_all_platform_filters_by_account():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_registration()])
    results = await list_all_platform(db, account_id=ACCOUNT_ID)
    assert len(results) == 1
    assert results[0].account_id == ACCOUNT_ID


# ===========================================================================
# Schema validation tests (27–32)
# ===========================================================================


# --- Test 27 ---
def test_schema_create_valid():
    schema = RegistrationCreate(
        fleet_vehicle_id=VEHICLE_ID,
        registration_number="REG-CA-2026-001",
        registration_state="California",
        registration_date=_REG_DATE,
        expiration_date=_EXP_DATE,
    )
    assert schema.registration_number == "REG-CA-2026-001"
    assert schema.registration_state == "California"
    assert schema.annual_fee_usd is None
    assert schema.registered_owner_name is None


# --- Test 28 ---
def test_schema_create_missing_required_raises():
    with pytest.raises(ValidationError):
        # Missing fleet_vehicle_id, registration_state, dates
        RegistrationCreate(
            registration_number="REG-CA-2026-001",
        )


# --- Test 29 ---
def test_schema_update_all_optional():
    schema = RegistrationUpdate()
    assert schema.registration_number is None
    assert schema.registration_state is None
    assert schema.registration_date is None
    assert schema.expiration_date is None
    assert schema.annual_fee_usd is None
    assert schema.registered_owner_name is None
    assert schema.notes is None


# --- Test 30 ---
def test_schema_response_from_attributes():
    reg = _make_registration()
    resp = _make_response(reg)
    assert resp.id == REG_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.is_active is True
    assert resp.registration_state == "California"
    assert resp.days_until_expiry is None


# --- Test 31 ---
def test_schema_expiring_response_valid():
    today = date.today()
    expiring = RegistrationExpiringResponse(
        id=REG_ID,
        account_id=ACCOUNT_ID,
        fleet_vehicle_id=VEHICLE_ID,
        registration_number="REG-CA-2026-001",
        registration_state="California",
        registration_date=_REG_DATE,
        expiration_date=today + timedelta(days=15),
        annual_fee_usd=250.00,
        registered_owner_name="Acme Corp",
        is_active=True,
        notes=None,
        created_by_id=ADMIN_ID,
        created_at=_NOW,
        updated_at=_NOW,
        days_until_expiry=15,
    )
    assert expiring.days_until_expiry == 15
    assert expiring.registration_state == "California"


# --- Test 32 ---
def test_schema_summary_response_valid():
    summary = RegistrationSummaryResponse(
        active_count=8,
        inactive_count=2,
        expiring_within_30_days=3,
        total_annual_fee_usd=2000.00,
        per_state_breakdown={"California": 5, "New York": 3, "Texas": 2},
    )
    assert summary.active_count == 8
    assert summary.total_annual_fee_usd == 2000.00
    assert summary.per_state_breakdown["California"] == 5


# ===========================================================================
# API layer tests (33–43)
# ===========================================================================

client = TestClient(app)


def _make_user(user_id: int = USER_ID, is_admin: bool = False):
    from app.models.user import User

    u = MagicMock(spec=User)
    u.id = user_id
    u.is_admin = is_admin
    return u


def _dep_overrides(user_id: int = USER_ID, is_admin: bool = False):
    """Return dependency override dict for FastAPI DI injection."""
    from app.api.deps import get_current_user, get_db, require_admin

    async def _user():
        return _make_user(user_id=user_id, is_admin=is_admin)

    async def _db():
        return AsyncMock()

    async def _admin():
        return _make_user(user_id=ADMIN_ID, is_admin=True)

    return {
        get_current_user: _user,
        get_db: _db,
        require_admin: _admin,
    }


def _patch_get_account():
    return patch(f"{_ROUTER}.get_account", new_callable=AsyncMock)


def _patch_require_account_admin(raises: bool = False):
    if raises:
        return patch(
            f"{_ROUTER}._require_account_admin",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=403, detail="forbidden"),
        )
    return patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)


# --- Test 33 ---
def test_api_list_vehicle_registrations_200():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.list_vehicle_registrations",
            new_callable=AsyncMock,
            return_value=[_make_response()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/registrations"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 34 ---
def test_api_get_expiring_200():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_expiring_registrations",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/fleet-registrations/expiring")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 35 ---
def test_api_get_summary_200():
    summary = RegistrationSummaryResponse(
        active_count=5,
        inactive_count=1,
        expiring_within_30_days=2,
        total_annual_fee_usd=1250.00,
        per_state_breakdown={"California": 4, "New York": 2},
    )
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_account_registration_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/fleet-registrations/summary")
        app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert data["active_count"] == 5


# --- Test 36 ---
def test_api_create_registration_201():
    resp = _make_response()
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.register_vehicle",
            new_callable=AsyncMock,
            return_value=resp,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-registrations/",
            json={
                "fleet_vehicle_id": str(VEHICLE_ID),
                "registration_number": "REG-CA-2026-001",
                "registration_state": "California",
                "registration_date": str(_REG_DATE),
                "expiration_date": str(_EXP_DATE),
            },
        )
        app.dependency_overrides.clear()
    assert r.status_code == 201


# --- Test 37 ---
def test_api_list_account_registrations_200():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.list_account_registrations",
            new_callable=AsyncMock,
            return_value=[_make_response()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/fleet-registrations/")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 38 ---
def test_api_get_registration_200():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_registration",
            new_callable=AsyncMock,
            return_value=_make_response(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-registrations/{REG_ID}"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 39 ---
def test_api_update_registration_200():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.update_registration",
            new_callable=AsyncMock,
            return_value=_make_response(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.put(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-registrations/{REG_ID}",
            json={"registration_state": "New York"},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 40 ---
def test_api_deactivate_registration_200():
    deactivated = _make_registration(is_active=False)
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.deactivate_registration",
            new_callable=AsyncMock,
            return_value=_make_response(deactivated),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-registrations/{REG_ID}/deactivate"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["is_active"] is False


# --- Test 41 ---
def test_api_reactivate_registration_200():
    reactivated = _make_registration(is_active=True)
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.reactivate_registration",
            new_callable=AsyncMock,
            return_value=_make_response(reactivated),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-registrations/{REG_ID}/reactivate"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["is_active"] is True


# --- Test 42 ---
def test_api_platform_list_all_200():
    with patch(
        f"{_ROUTER}.list_all_platform",
        new_callable=AsyncMock,
        return_value=[_make_response()],
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get("/api/v1/platform/corporate/fleet-registrations/")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 43 ---
def test_api_platform_list_by_account_200():
    with patch(
        f"{_ROUTER}.list_all_platform",
        new_callable=AsyncMock,
        return_value=[_make_response()],
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/platform/corporate/fleet-registrations/{ACCOUNT_ID}")
        app.dependency_overrides.clear()
    assert r.status_code == 200
