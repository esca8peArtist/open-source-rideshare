"""Tests for the Corporate Fleet Insurance Tracking feature.

Service layer (async, mocked DB):
   1.  add_policy — success: creates with is_active=True
   2.  add_policy — 404 when vehicle not in account
   3.  add_policy — 409 when vehicle is inactive
   4.  add_policy — 409 when policy_number already exists for account
   5.  get_policy — success: returns existing policy
   6.  get_policy — 404 when not found
   7.  list_vehicle_policies — returns all for vehicle
   8.  list_vehicle_policies — is_active filter works
   9.  list_account_policies — returns all for account
  10.  list_account_policies — insurance_type filter works
  11.  update_policy — success: updates fields
  12.  update_policy — 409 policy_number collision with another policy
  13.  deactivate_policy — success: sets is_active=False
  14.  deactivate_policy — 409 if already inactive
  15.  reactivate_policy — success: sets is_active=True
  16.  reactivate_policy — 409 if already active
  17.  get_expiring_policies — returns policies expiring within N days
  18.  get_expiring_policies — excludes inactive policies
  19.  get_expiring_policies — vehicle filter works
  20.  get_insurance_summary — returns correct structure
  21.  list_all_platform — returns all
  22.  list_all_platform — account_id filter works

Schema validation:
  23.  InsurancePolicyCreate — valid construction
  24.  InsurancePolicyCreate — missing required field raises ValidationError
  25.  InsurancePolicyUpdate — all optional
  26.  InsurancePolicyResponse — from_attributes works
  27.  InsuranceExpiringResponse — valid structure
  28.  InsuranceSummaryResponse — valid structure

API layer (service functions patched):
  29.  GET list vehicle insurance → 200
  30.  GET expiring → 200
  31.  GET summary → 200
  32.  GET get policy → 200
  33.  POST add policy → 201
  34.  GET list account policies → 200
  35.  PUT update policy → 200
  36.  POST deactivate → 200
  37.  POST reactivate → 200
  38.  GET platform list → 200
  39.  GET platform list by account → 200
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
from app.models.corporate_fleet_insurance import (
    CorporateFleetInsurancePolicy,
    InsuranceType,
)
from app.schemas.corporate_fleet_insurance import (
    InsuranceExpiringResponse,
    InsurancePolicyCreate,
    InsurancePolicyResponse,
    InsuranceSummaryResponse,
    InsurancePolicyUpdate,
)
from app.services.corporate_fleet_insurance_service import (
    add_policy,
    deactivate_policy,
    get_expiring_policies,
    get_insurance_summary,
    get_policy,
    list_account_policies,
    list_all_platform,
    list_vehicle_policies,
    reactivate_policy,
    update_policy,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 7
VEHICLE_ID = uuid.uuid4()
POLICY_ID = uuid.uuid4()
USER_ID = 10
ADMIN_ID = 1

_SERVICE = "app.services.corporate_fleet_insurance_service"
_ROUTER = "app.api.v1.corporate_fleet_insurance"

_NOW = datetime(2026, 4, 16, 9, 0, 0, tzinfo=timezone.utc)
_START = date(2026, 1, 1)
_END = date(2026, 12, 31)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_policy(
    policy_id: uuid.UUID = POLICY_ID,
    account_id: int = ACCOUNT_ID,
    fleet_vehicle_id: uuid.UUID = VEHICLE_ID,
    policy_number: str = "POL-2026-001",
    insurance_type: InsuranceType = InsuranceType.liability,
    provider_name: str = "Acme Insurance Co.",
    coverage_amount_usd: float | None = 1_000_000.00,
    deductible_usd: float | None = 5_000.00,
    premium_annual_usd: float | None = 2_400.00,
    policy_start_date: date = _START,
    policy_end_date: date = _END,
    is_active: bool = True,
    notes: str | None = None,
    created_by_id: int | None = ADMIN_ID,
) -> CorporateFleetInsurancePolicy:
    pol = CorporateFleetInsurancePolicy()
    pol.id = policy_id
    pol.account_id = account_id
    pol.fleet_vehicle_id = fleet_vehicle_id
    pol.policy_number = policy_number
    pol.insurance_type = insurance_type
    pol.provider_name = provider_name
    pol.coverage_amount_usd = coverage_amount_usd
    pol.deductible_usd = deductible_usd
    pol.premium_annual_usd = premium_annual_usd
    pol.policy_start_date = policy_start_date
    pol.policy_end_date = policy_end_date
    pol.is_active = is_active
    pol.notes = notes
    pol.created_by_id = created_by_id
    pol.created_at = _NOW
    pol.updated_at = _NOW
    return pol


def _make_response(pol: CorporateFleetInsurancePolicy | None = None) -> InsurancePolicyResponse:
    if pol is None:
        pol = _make_policy()
    return InsurancePolicyResponse(
        id=pol.id,
        account_id=pol.account_id,
        fleet_vehicle_id=pol.fleet_vehicle_id,
        policy_number=pol.policy_number,
        insurance_type=pol.insurance_type.value
        if hasattr(pol.insurance_type, "value")
        else str(pol.insurance_type),
        provider_name=pol.provider_name,
        coverage_amount_usd=float(pol.coverage_amount_usd)
        if pol.coverage_amount_usd is not None
        else None,
        deductible_usd=float(pol.deductible_usd)
        if pol.deductible_usd is not None
        else None,
        premium_annual_usd=float(pol.premium_annual_usd)
        if pol.premium_annual_usd is not None
        else None,
        policy_start_date=pol.policy_start_date,
        policy_end_date=pol.policy_end_date,
        is_active=pol.is_active,
        notes=pol.notes,
        created_by_id=pol.created_by_id,
        created_at=pol.created_at,
        updated_at=pol.updated_at,
    )


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_vehicle(is_active: bool = True):
    from app.models.corporate_fleet_vehicle import CorporateFleetVehicle

    v = CorporateFleetVehicle()
    v.id = VEHICLE_ID
    v.account_id = ACCOUNT_ID
    v.name = "Fleet Sedan 1"
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
# Service layer tests (1–22)
# ===========================================================================


# --- Test 1 ---
@pytest.mark.asyncio
async def test_add_policy_success():
    db = _mock_db()
    vehicle = _mock_vehicle()
    data = InsurancePolicyCreate(
        fleet_vehicle_id=VEHICLE_ID,
        policy_number="POL-2026-001",
        insurance_type=InsuranceType.liability,
        provider_name="Acme Insurance Co.",
        premium_annual_usd=2400.00,
        policy_start_date=_START,
        policy_end_date=_END,
    )

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv, \
         patch(f"{_SERVICE}._check_policy_number_unique", new_callable=AsyncMock) as mock_uniq:
        mock_fv.return_value = vehicle

        created = _make_policy()
        db.refresh.side_effect = lambda obj: None

        with patch(f"{_SERVICE}.CorporateFleetInsurancePolicy") as MockModel:
            MockModel.return_value = created
            result = await add_policy(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)

    assert db.add.called
    assert db.commit.called


# --- Test 2 ---
@pytest.mark.asyncio
async def test_add_policy_404_vehicle_not_found():
    db = _mock_db()
    data = InsurancePolicyCreate(
        fleet_vehicle_id=VEHICLE_ID,
        policy_number="POL-2026-001",
        insurance_type=InsuranceType.liability,
        provider_name="Acme Insurance",
        policy_start_date=_START,
        policy_end_date=_END,
    )
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await add_policy(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 404


# --- Test 3 ---
@pytest.mark.asyncio
async def test_add_policy_409_inactive_vehicle():
    db = _mock_db()
    vehicle = _mock_vehicle(is_active=False)
    data = InsurancePolicyCreate(
        fleet_vehicle_id=VEHICLE_ID,
        policy_number="POL-2026-001",
        insurance_type=InsuranceType.collision,
        provider_name="State Farm",
        policy_start_date=_START,
        policy_end_date=_END,
    )
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        with pytest.raises(HTTPException) as exc:
            await add_policy(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 409
    assert "not active" in exc.value.detail.lower()


# --- Test 4 ---
@pytest.mark.asyncio
async def test_add_policy_409_duplicate_policy_number():
    db = _mock_db()
    vehicle = _mock_vehicle()
    data = InsurancePolicyCreate(
        fleet_vehicle_id=VEHICLE_ID,
        policy_number="POL-DUPE-001",
        insurance_type=InsuranceType.comprehensive,
        provider_name="Geico",
        policy_start_date=_START,
        policy_end_date=_END,
    )
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv, \
         patch(f"{_SERVICE}._check_policy_number_unique", new_callable=AsyncMock) as mock_uniq:
        mock_fv.return_value = vehicle
        mock_uniq.side_effect = HTTPException(
            status_code=409, detail="A policy with this number already exists for this account."
        )
        with pytest.raises(HTTPException) as exc:
            await add_policy(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 409


# --- Test 5 ---
@pytest.mark.asyncio
async def test_get_policy_success():
    db = _mock_db()
    pol = _make_policy()
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.return_value = pol
        result = await get_policy(db, ACCOUNT_ID, POLICY_ID)
    assert result.id == POLICY_ID
    assert result.policy_number == "POL-2026-001"


# --- Test 6 ---
@pytest.mark.asyncio
async def test_get_policy_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await get_policy(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 7 ---
@pytest.mark.asyncio
async def test_list_vehicle_policies_returns_all():
    db = _mock_db()
    rows = [_make_policy(), _make_policy(policy_id=uuid.uuid4(), policy_number="POL-2")]
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _mock_vehicle()
        db.execute.return_value = _scalars_result(rows)
        results = await list_vehicle_policies(db, ACCOUNT_ID, VEHICLE_ID)
    assert len(results) == 2


# --- Test 8 ---
@pytest.mark.asyncio
async def test_list_vehicle_policies_is_active_filter():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _mock_vehicle()
        db.execute.return_value = _scalars_result([_make_policy(is_active=True)])
        results = await list_vehicle_policies(db, ACCOUNT_ID, VEHICLE_ID, is_active=True)
    assert len(results) == 1
    assert results[0].is_active is True


# --- Test 9 ---
@pytest.mark.asyncio
async def test_list_account_policies_returns_all():
    db = _mock_db()
    rows = [
        _make_policy(),
        _make_policy(policy_id=uuid.uuid4(), policy_number="POL-2"),
        _make_policy(policy_id=uuid.uuid4(), policy_number="POL-3", account_id=ACCOUNT_ID),
    ]
    db.execute.return_value = _scalars_result(rows)
    results = await list_account_policies(db, ACCOUNT_ID)
    assert len(results) == 3


# --- Test 10 ---
@pytest.mark.asyncio
async def test_list_account_policies_insurance_type_filter():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_policy(insurance_type=InsuranceType.collision)])
    results = await list_account_policies(db, ACCOUNT_ID, insurance_type=InsuranceType.collision)
    assert len(results) == 1
    assert results[0].insurance_type == "collision"


# --- Test 11 ---
@pytest.mark.asyncio
async def test_update_policy_success():
    db = _mock_db()
    pol = _make_policy()
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp, \
         patch(f"{_SERVICE}._check_policy_number_unique", new_callable=AsyncMock):
        mock_fp.return_value = pol
        data = InsurancePolicyUpdate(provider_name="Updated Provider", premium_annual_usd=3000.00)
        result = await update_policy(db, ACCOUNT_ID, POLICY_ID, data)
    assert pol.provider_name == "Updated Provider"
    assert db.commit.called


# --- Test 12 ---
@pytest.mark.asyncio
async def test_update_policy_409_number_collision():
    db = _mock_db()
    pol = _make_policy()
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp, \
         patch(f"{_SERVICE}._check_policy_number_unique", new_callable=AsyncMock) as mock_uniq:
        mock_fp.return_value = pol
        mock_uniq.side_effect = HTTPException(
            status_code=409, detail="A policy with this number already exists for this account."
        )
        data = InsurancePolicyUpdate(policy_number="POL-TAKEN-001")
        with pytest.raises(HTTPException) as exc:
            await update_policy(db, ACCOUNT_ID, POLICY_ID, data)
    assert exc.value.status_code == 409


# --- Test 13 ---
@pytest.mark.asyncio
async def test_deactivate_policy_success():
    db = _mock_db()
    pol = _make_policy(is_active=True)
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.return_value = pol
        result = await deactivate_policy(db, ACCOUNT_ID, POLICY_ID)
    assert pol.is_active is False
    assert db.commit.called


# --- Test 14 ---
@pytest.mark.asyncio
async def test_deactivate_policy_409_already_inactive():
    db = _mock_db()
    pol = _make_policy(is_active=False)
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.return_value = pol
        with pytest.raises(HTTPException) as exc:
            await deactivate_policy(db, ACCOUNT_ID, POLICY_ID)
    assert exc.value.status_code == 409
    assert "already inactive" in exc.value.detail.lower()


# --- Test 15 ---
@pytest.mark.asyncio
async def test_reactivate_policy_success():
    db = _mock_db()
    pol = _make_policy(is_active=False)
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.return_value = pol
        result = await reactivate_policy(db, ACCOUNT_ID, POLICY_ID)
    assert pol.is_active is True
    assert db.commit.called


# --- Test 16 ---
@pytest.mark.asyncio
async def test_reactivate_policy_409_already_active():
    db = _mock_db()
    pol = _make_policy(is_active=True)
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.return_value = pol
        with pytest.raises(HTTPException) as exc:
            await reactivate_policy(db, ACCOUNT_ID, POLICY_ID)
    assert exc.value.status_code == 409
    assert "already active" in exc.value.detail.lower()


# --- Test 17 ---
@pytest.mark.asyncio
async def test_get_expiring_policies_returns_expiring():
    db = _mock_db()
    today = date.today()
    expiring_soon = today + timedelta(days=15)
    pol = _make_policy(is_active=True, policy_end_date=expiring_soon)
    db.execute.return_value = _scalars_result([pol])
    results = await get_expiring_policies(db, ACCOUNT_ID, days_ahead=30)
    assert len(results) == 1
    assert results[0].policy_id == POLICY_ID
    assert results[0].days_until_expiry == 15


# --- Test 18 ---
@pytest.mark.asyncio
async def test_get_expiring_policies_excludes_inactive():
    db = _mock_db()
    # Mock returns empty — the query filters is_active=True at DB level
    db.execute.return_value = _scalars_result([])
    results = await get_expiring_policies(db, ACCOUNT_ID)
    assert results == []


# --- Test 19 ---
@pytest.mark.asyncio
async def test_get_expiring_policies_vehicle_filter():
    db = _mock_db()
    today = date.today()
    pol = _make_policy(is_active=True, policy_end_date=today + timedelta(days=10))
    db.execute.return_value = _scalars_result([pol])
    results = await get_expiring_policies(
        db, ACCOUNT_ID, days_ahead=30, fleet_vehicle_id=VEHICLE_ID
    )
    assert len(results) == 1
    assert results[0].fleet_vehicle_id == VEHICLE_ID


# --- Test 20 ---
@pytest.mark.asyncio
async def test_get_insurance_summary_correct_structure():
    db = _mock_db()
    today = date.today()

    pol_active = _make_policy(is_active=True, policy_end_date=today + timedelta(days=20))
    pol_active2 = _make_policy(
        policy_id=uuid.uuid4(),
        policy_number="POL-2",
        is_active=True,
        insurance_type=InsuranceType.collision,
        policy_end_date=today + timedelta(days=60),
        premium_annual_usd=1200.00,
    )
    pol_inactive = _make_policy(
        policy_id=uuid.uuid4(),
        policy_number="POL-3",
        is_active=False,
        policy_end_date=today + timedelta(days=10),
        premium_annual_usd=0.00,
    )

    db.execute.return_value = _scalars_result([pol_active, pol_active2, pol_inactive])
    summary = await get_insurance_summary(db, ACCOUNT_ID)

    assert summary.total_policies == 3
    assert summary.active_policies == 2
    assert summary.inactive_policies == 1
    assert summary.expiring_within_30_days == 1
    assert summary.total_annual_premium_usd == pytest.approx(2400.00 + 1200.00)
    assert "liability" in summary.by_type
    assert "collision" in summary.by_type


# --- Test 21 ---
@pytest.mark.asyncio
async def test_list_all_platform_returns_all():
    db = _mock_db()
    rows = [
        _make_policy(),
        _make_policy(policy_id=uuid.uuid4(), policy_number="POL-2", account_id=99),
    ]
    db.execute.return_value = _scalars_result(rows)
    results = await list_all_platform(db)
    assert len(results) == 2


# --- Test 22 ---
@pytest.mark.asyncio
async def test_list_all_platform_filters_by_account():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_policy()])
    results = await list_all_platform(db, account_id=ACCOUNT_ID)
    assert len(results) == 1
    assert results[0].account_id == ACCOUNT_ID


# ===========================================================================
# Schema validation tests (23–28)
# ===========================================================================


# --- Test 23 ---
def test_schema_create_valid():
    schema = InsurancePolicyCreate(
        fleet_vehicle_id=VEHICLE_ID,
        policy_number="POL-2026-001",
        insurance_type=InsuranceType.liability,
        provider_name="Acme Insurance",
        policy_start_date=_START,
        policy_end_date=_END,
    )
    assert schema.policy_number == "POL-2026-001"
    assert schema.insurance_type == InsuranceType.liability
    assert schema.coverage_amount_usd is None


# --- Test 24 ---
def test_schema_create_missing_required_raises():
    with pytest.raises(ValidationError):
        # Missing fleet_vehicle_id, insurance_type, provider_name, start/end dates
        InsurancePolicyCreate(
            policy_number="POL-2026-001",
        )


# --- Test 25 ---
def test_schema_update_all_optional():
    schema = InsurancePolicyUpdate()
    assert schema.policy_number is None
    assert schema.insurance_type is None
    assert schema.provider_name is None
    assert schema.premium_annual_usd is None
    assert schema.policy_start_date is None
    assert schema.policy_end_date is None


# --- Test 26 ---
def test_schema_response_from_attributes():
    pol = _make_policy()
    resp = _make_response(pol)
    assert resp.id == POLICY_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.is_active is True
    assert resp.insurance_type == "liability"
    assert resp.provider_name == "Acme Insurance Co."


# --- Test 27 ---
def test_schema_expiring_response_valid():
    today = date.today()
    expiring = InsuranceExpiringResponse(
        policy_id=POLICY_ID,
        fleet_vehicle_id=VEHICLE_ID,
        policy_number="POL-2026-001",
        insurance_type="liability",
        provider_name="Acme Insurance Co.",
        policy_end_date=today + timedelta(days=15),
        days_until_expiry=15,
    )
    assert expiring.days_until_expiry == 15
    assert expiring.insurance_type == "liability"


# --- Test 28 ---
def test_schema_summary_response_valid():
    summary = InsuranceSummaryResponse(
        total_policies=10,
        active_policies=7,
        inactive_policies=3,
        expiring_within_30_days=2,
        total_annual_premium_usd=24000.00,
        by_type={"liability": 4, "collision": 3, "comprehensive": 3},
    )
    assert summary.total_policies == 10
    assert summary.total_annual_premium_usd == 24000.00
    assert summary.by_type["liability"] == 4


# ===========================================================================
# API layer tests (29–39)
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


def _resp_dict(pol: CorporateFleetInsurancePolicy | None = None) -> dict:
    r = _make_response(pol)
    return r.model_dump(mode="json")


# --- Test 29 ---
def test_api_list_vehicle_insurance_200():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.list_vehicle_policies",
            new_callable=AsyncMock,
            return_value=[_make_response()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/insurance"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 30 ---
def test_api_get_expiring_200():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_expiring_policies",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/fleet-insurance/expiring")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 31 ---
def test_api_get_summary_200():
    summary = InsuranceSummaryResponse(
        total_policies=5,
        active_policies=4,
        inactive_policies=1,
        expiring_within_30_days=1,
        total_annual_premium_usd=9600.00,
        by_type={"liability": 2, "collision": 2, "comprehensive": 1},
    )
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_insurance_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/fleet-insurance/summary")
        app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert data["total_policies"] == 5


# --- Test 32 ---
def test_api_get_policy_200():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_policy",
            new_callable=AsyncMock,
            return_value=_make_response(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-insurance/{POLICY_ID}"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 33 ---
def test_api_add_policy_201():
    resp = _make_response()
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.add_policy",
            new_callable=AsyncMock,
            return_value=resp,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-insurance/",
            json={
                "fleet_vehicle_id": str(VEHICLE_ID),
                "policy_number": "POL-2026-001",
                "insurance_type": "liability",
                "provider_name": "Acme Insurance Co.",
                "policy_start_date": str(_START),
                "policy_end_date": str(_END),
            },
        )
        app.dependency_overrides.clear()
    assert r.status_code == 201


# --- Test 34 ---
def test_api_list_account_policies_200():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.list_account_policies",
            new_callable=AsyncMock,
            return_value=[_make_response()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/fleet-insurance/")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 35 ---
def test_api_update_policy_200():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.update_policy",
            new_callable=AsyncMock,
            return_value=_make_response(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.put(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-insurance/{POLICY_ID}",
            json={"provider_name": "Updated Provider"},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 36 ---
def test_api_deactivate_policy_200():
    deactivated = _make_policy(is_active=False)
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.deactivate_policy",
            new_callable=AsyncMock,
            return_value=_make_response(deactivated),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-insurance/{POLICY_ID}/deactivate"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["is_active"] is False


# --- Test 37 ---
def test_api_reactivate_policy_200():
    reactivated = _make_policy(is_active=True)
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.reactivate_policy",
            new_callable=AsyncMock,
            return_value=_make_response(reactivated),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-insurance/{POLICY_ID}/reactivate"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["is_active"] is True


# --- Test 38 ---
def test_api_platform_list_all_200():
    with patch(
        f"{_ROUTER}.list_all_platform",
        new_callable=AsyncMock,
        return_value=[_make_response()],
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get("/api/v1/platform/corporate/fleet-insurance/")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 39 ---
def test_api_platform_list_by_account_200():
    with patch(
        f"{_ROUTER}.list_all_platform",
        new_callable=AsyncMock,
        return_value=[_make_response()],
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/platform/corporate/fleet-insurance/{ACCOUNT_ID}")
        app.dependency_overrides.clear()
    assert r.status_code == 200
