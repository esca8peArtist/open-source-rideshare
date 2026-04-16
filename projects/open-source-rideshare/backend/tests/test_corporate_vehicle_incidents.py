"""Tests for the Corporate Vehicle Incident Reports feature.

Service layer (async, mocked DB):
   1.  create_incident_report — success: creates with incident_status=draft
   2.  create_incident_report — 404 when vehicle not in account
   3.  create_incident_report — 409 when vehicle is inactive
   4.  create_incident_report — success with insurance_policy_id
   5.  create_incident_report — 404 when insurance_policy_id invalid
   6.  get_incident_report — success: returns existing report
   7.  get_incident_report — 404 when not found
   8.  list_vehicle_incidents — returns all for vehicle
   9.  list_vehicle_incidents — incident_type filter works
  10.  list_vehicle_incidents — incident_status filter works
  11.  list_vehicle_incidents — from_date / to_date filter works
  12.  list_account_incidents — returns all for account
  13.  list_account_incidents — multi-filter works
  14.  update_incident_report — success: updates mutable fields
  15.  update_incident_report — 409 when status is closed
  16.  update_incident_report — 409 when status is resolved
  17.  submit_incident — draft → reported
  18.  submit_incident — 409 if not in draft
  19.  mark_under_review — reported → under_review
  20.  mark_under_review — 409 if not in reported
  21.  resolve_incident — under_review → resolved; sets resolved_at
  22.  resolve_incident — 409 if not under_review
  23.  close_incident — resolved → closed
  24.  close_incident — 409 if not resolved
  25.  get_incident_summary — totals, by_status, by_type counts
  26.  get_incident_summary — open_count correct
  27.  get_incident_summary — total_estimated_damage_usd sums open incidents only
  28.  list_all_platform — returns all records
  29.  list_all_platform — account_id filter works

Schema validation:
  30.  IncidentReportCreate — valid construction
  31.  IncidentReportCreate — missing required field raises ValidationError
  32.  IncidentReportUpdate — all optional
  33.  IncidentReportResponse — from_attributes works
  34.  IncidentSummaryResponse — valid structure

API layer (service functions patched):
  35.  GET list vehicle incidents → 200
  36.  GET get single incident → 200
  37.  POST create incident → 201
  38.  PUT update incident → 200
  39.  POST submit incident → 200
  40.  POST mark under review → 200
  41.  POST resolve → 200
  42.  POST close → 200
  43.  GET list account incidents → 200
  44.  GET summary → 200
  45.  GET platform list all → 200
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.corporate_vehicle_incident import (
    CorporateVehicleIncidentReport,
    IncidentStatus,
    IncidentType,
)
from app.schemas.corporate_vehicle_incidents import (
    IncidentReportCreate,
    IncidentReportResponse,
    IncidentReportUpdate,
    IncidentSummaryResponse,
)
from app.services.corporate_vehicle_incident_service import (
    close_incident,
    create_incident_report,
    get_incident_report,
    get_incident_summary,
    list_account_incidents,
    list_all_platform,
    list_vehicle_incidents,
    mark_under_review,
    resolve_incident,
    submit_incident,
    update_incident_report,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 5
VEHICLE_ID = uuid.uuid4()
INCIDENT_ID = uuid.uuid4()
POLICY_ID = uuid.uuid4()
USER_ID = 20
ADMIN_ID = 1
DRIVER_ID = 30

_SERVICE = "app.services.corporate_vehicle_incident_service"
_ROUTER = "app.api.v1.corporate_vehicle_incidents"

_NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
_TODAY = date(2026, 4, 16)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_incident(
    incident_id: uuid.UUID = INCIDENT_ID,
    account_id: int = ACCOUNT_ID,
    fleet_vehicle_id: uuid.UUID = VEHICLE_ID,
    incident_type: IncidentType = IncidentType.collision,
    incident_status: IncidentStatus = IncidentStatus.draft,
    incident_date: date = _TODAY,
    incident_time: time | None = None,
    incident_location: str | None = "Main St and 5th Ave",
    description: str = "Vehicle struck a bollard while parking.",
    estimated_damage_usd: float | None = 1_500.00,
    police_report_number: str | None = None,
    driver_id: int | None = DRIVER_ID,
    insurance_policy_id: uuid.UUID | None = None,
    insurance_claim_number: str | None = None,
    witness_info: str | None = None,
    reported_by_id: int | None = USER_ID,
    reviewed_by_id: int | None = None,
    resolved_at: datetime | None = None,
    notes: str | None = None,
) -> CorporateVehicleIncidentReport:
    inc = CorporateVehicleIncidentReport()
    inc.id = incident_id
    inc.account_id = account_id
    inc.fleet_vehicle_id = fleet_vehicle_id
    inc.incident_type = incident_type
    inc.incident_status = incident_status
    inc.incident_date = incident_date
    inc.incident_time = incident_time
    inc.incident_location = incident_location
    inc.description = description
    inc.estimated_damage_usd = estimated_damage_usd
    inc.police_report_number = police_report_number
    inc.driver_id = driver_id
    inc.insurance_policy_id = insurance_policy_id
    inc.insurance_claim_number = insurance_claim_number
    inc.witness_info = witness_info
    inc.reported_by_id = reported_by_id
    inc.reviewed_by_id = reviewed_by_id
    inc.resolved_at = resolved_at
    inc.notes = notes
    inc.created_at = _NOW
    inc.updated_at = _NOW
    return inc


def _make_response(inc: CorporateVehicleIncidentReport | None = None) -> IncidentReportResponse:
    if inc is None:
        inc = _make_incident()
    return IncidentReportResponse(
        id=inc.id,
        account_id=inc.account_id,
        fleet_vehicle_id=inc.fleet_vehicle_id,
        incident_type=inc.incident_type.value
        if hasattr(inc.incident_type, "value")
        else str(inc.incident_type),
        incident_status=inc.incident_status.value
        if hasattr(inc.incident_status, "value")
        else str(inc.incident_status),
        incident_date=inc.incident_date,
        incident_time=inc.incident_time,
        incident_location=inc.incident_location,
        description=inc.description,
        estimated_damage_usd=float(inc.estimated_damage_usd)
        if inc.estimated_damage_usd is not None
        else None,
        police_report_number=inc.police_report_number,
        driver_id=inc.driver_id,
        insurance_policy_id=inc.insurance_policy_id,
        insurance_claim_number=inc.insurance_claim_number,
        witness_info=inc.witness_info,
        reported_by_id=inc.reported_by_id,
        reviewed_by_id=inc.reviewed_by_id,
        resolved_at=inc.resolved_at,
        notes=inc.notes,
        created_at=inc.created_at,
        updated_at=inc.updated_at,
    )


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_vehicle(is_active: bool = True):
    from app.models.corporate_fleet_vehicle import CorporateFleetVehicle

    v = CorporateFleetVehicle()
    v.id = VEHICLE_ID
    v.account_id = ACCOUNT_ID
    v.name = "Fleet SUV 1"
    v.is_active = is_active
    return v


def _mock_policy():
    from app.models.corporate_fleet_insurance import CorporateFleetInsurancePolicy

    p = CorporateFleetInsurancePolicy()
    p.id = POLICY_ID
    p.account_id = ACCOUNT_ID
    return p


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
# Service layer tests (1–29)
# ===========================================================================


# --- Test 1 ---
@pytest.mark.asyncio
async def test_create_incident_success():
    db = _mock_db()
    vehicle = _mock_vehicle()
    data = IncidentReportCreate(
        fleet_vehicle_id=VEHICLE_ID,
        incident_type=IncidentType.collision,
        incident_date=_TODAY,
        description="Vehicle struck a bollard.",
        reported_by_id=USER_ID,
        estimated_damage_usd=1500.00,
    )
    created = _make_incident()
    db.refresh.side_effect = lambda obj: None

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv, \
         patch(f"{_SERVICE}.CorporateVehicleIncidentReport") as MockModel:
        mock_fv.return_value = vehicle
        MockModel.return_value = created
        result = await create_incident_report(db, ACCOUNT_ID, data)

    assert db.add.called
    assert db.commit.called


# --- Test 2 ---
@pytest.mark.asyncio
async def test_create_incident_404_vehicle_not_found():
    db = _mock_db()
    data = IncidentReportCreate(
        fleet_vehicle_id=VEHICLE_ID,
        incident_type=IncidentType.vandalism,
        incident_date=_TODAY,
        description="Graffiti on door panel.",
        reported_by_id=USER_ID,
    )
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await create_incident_report(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 404


# --- Test 3 ---
@pytest.mark.asyncio
async def test_create_incident_409_inactive_vehicle():
    db = _mock_db()
    vehicle = _mock_vehicle(is_active=False)
    data = IncidentReportCreate(
        fleet_vehicle_id=VEHICLE_ID,
        incident_type=IncidentType.theft,
        incident_date=_TODAY,
        description="Vehicle stolen from parking lot.",
        reported_by_id=USER_ID,
    )
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        with pytest.raises(HTTPException) as exc:
            await create_incident_report(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 409
    assert "not active" in exc.value.detail.lower()


# --- Test 4 ---
@pytest.mark.asyncio
async def test_create_incident_with_insurance_policy():
    db = _mock_db()
    vehicle = _mock_vehicle()
    policy = _mock_policy()
    data = IncidentReportCreate(
        fleet_vehicle_id=VEHICLE_ID,
        incident_type=IncidentType.collision,
        incident_date=_TODAY,
        description="Rear-end collision at intersection.",
        reported_by_id=USER_ID,
        insurance_policy_id=POLICY_ID,
        insurance_claim_number="CLM-2026-001",
    )
    created = _make_incident(insurance_policy_id=POLICY_ID, insurance_claim_number="CLM-2026-001")
    db.refresh.side_effect = lambda obj: None

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv, \
         patch(f"{_SERVICE}._fetch_insurance_policy", new_callable=AsyncMock) as mock_fp, \
         patch(f"{_SERVICE}.CorporateVehicleIncidentReport") as MockModel:
        mock_fv.return_value = vehicle
        mock_fp.return_value = policy
        MockModel.return_value = created
        result = await create_incident_report(db, ACCOUNT_ID, data)

    mock_fp.assert_called_once_with(db, ACCOUNT_ID, POLICY_ID)
    assert db.add.called


# --- Test 5 ---
@pytest.mark.asyncio
async def test_create_incident_404_invalid_insurance_policy():
    db = _mock_db()
    vehicle = _mock_vehicle()
    data = IncidentReportCreate(
        fleet_vehicle_id=VEHICLE_ID,
        incident_type=IncidentType.parking_damage,
        incident_date=_TODAY,
        description="Parking lot scrape.",
        reported_by_id=USER_ID,
        insurance_policy_id=uuid.uuid4(),
    )
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv, \
         patch(f"{_SERVICE}._fetch_insurance_policy", new_callable=AsyncMock) as mock_fp:
        mock_fv.return_value = vehicle
        mock_fp.side_effect = HTTPException(status_code=404, detail="Insurance policy not found.")
        with pytest.raises(HTTPException) as exc:
            await create_incident_report(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 404


# --- Test 6 ---
@pytest.mark.asyncio
async def test_get_incident_success():
    db = _mock_db()
    inc = _make_incident()
    with patch(f"{_SERVICE}._fetch_incident", new_callable=AsyncMock) as mock_fi:
        mock_fi.return_value = inc
        result = await get_incident_report(db, ACCOUNT_ID, INCIDENT_ID)
    assert result.id == INCIDENT_ID
    assert result.description == "Vehicle struck a bollard while parking."


# --- Test 7 ---
@pytest.mark.asyncio
async def test_get_incident_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_incident", new_callable=AsyncMock) as mock_fi:
        mock_fi.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await get_incident_report(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 8 ---
@pytest.mark.asyncio
async def test_list_vehicle_incidents_returns_all():
    db = _mock_db()
    rows = [
        _make_incident(),
        _make_incident(incident_id=uuid.uuid4(), incident_type=IncidentType.vandalism),
    ]
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _mock_vehicle()
        db.execute.return_value = _scalars_result(rows)
        results = await list_vehicle_incidents(db, ACCOUNT_ID, VEHICLE_ID)
    assert len(results) == 2


# --- Test 9 ---
@pytest.mark.asyncio
async def test_list_vehicle_incidents_type_filter():
    db = _mock_db()
    rows = [_make_incident(incident_type=IncidentType.theft)]
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _mock_vehicle()
        db.execute.return_value = _scalars_result(rows)
        results = await list_vehicle_incidents(
            db, ACCOUNT_ID, VEHICLE_ID, incident_type=IncidentType.theft
        )
    assert len(results) == 1
    assert results[0].incident_type == "theft"


# --- Test 10 ---
@pytest.mark.asyncio
async def test_list_vehicle_incidents_status_filter():
    db = _mock_db()
    rows = [_make_incident(incident_status=IncidentStatus.reported)]
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _mock_vehicle()
        db.execute.return_value = _scalars_result(rows)
        results = await list_vehicle_incidents(
            db, ACCOUNT_ID, VEHICLE_ID, incident_status=IncidentStatus.reported
        )
    assert len(results) == 1
    assert results[0].incident_status == "reported"


# --- Test 11 ---
@pytest.mark.asyncio
async def test_list_vehicle_incidents_date_range_filter():
    db = _mock_db()
    rows = [_make_incident(incident_date=_TODAY)]
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _mock_vehicle()
        db.execute.return_value = _scalars_result(rows)
        results = await list_vehicle_incidents(
            db,
            ACCOUNT_ID,
            VEHICLE_ID,
            from_date=date(2026, 4, 1),
            to_date=date(2026, 4, 30),
        )
    assert len(results) == 1


# --- Test 12 ---
@pytest.mark.asyncio
async def test_list_account_incidents_returns_all():
    db = _mock_db()
    rows = [
        _make_incident(),
        _make_incident(incident_id=uuid.uuid4(), incident_type=IncidentType.mechanical_failure),
        _make_incident(incident_id=uuid.uuid4(), incident_type=IncidentType.parking_damage),
    ]
    db.execute.return_value = _scalars_result(rows)
    results = await list_account_incidents(db, ACCOUNT_ID)
    assert len(results) == 3


# --- Test 13 ---
@pytest.mark.asyncio
async def test_list_account_incidents_multi_filter():
    db = _mock_db()
    rows = [_make_incident(incident_status=IncidentStatus.resolved, incident_type=IncidentType.theft)]
    db.execute.return_value = _scalars_result(rows)
    results = await list_account_incidents(
        db,
        ACCOUNT_ID,
        incident_type=IncidentType.theft,
        incident_status=IncidentStatus.resolved,
    )
    assert len(results) == 1
    assert results[0].incident_type == "theft"
    assert results[0].incident_status == "resolved"


# --- Test 14 ---
@pytest.mark.asyncio
async def test_update_incident_success():
    db = _mock_db()
    inc = _make_incident(incident_status=IncidentStatus.draft)
    with patch(f"{_SERVICE}._fetch_incident", new_callable=AsyncMock) as mock_fi:
        mock_fi.return_value = inc
        data = IncidentReportUpdate(
            incident_location="Updated corner location",
            estimated_damage_usd=2000.00,
        )
        result = await update_incident_report(db, ACCOUNT_ID, INCIDENT_ID, data)
    assert inc.incident_location == "Updated corner location"
    assert db.commit.called


# --- Test 15 ---
@pytest.mark.asyncio
async def test_update_incident_409_when_closed():
    db = _mock_db()
    inc = _make_incident(incident_status=IncidentStatus.closed)
    with patch(f"{_SERVICE}._fetch_incident", new_callable=AsyncMock) as mock_fi:
        mock_fi.return_value = inc
        with pytest.raises(HTTPException) as exc:
            await update_incident_report(
                db, ACCOUNT_ID, INCIDENT_ID, IncidentReportUpdate(description="Updated")
            )
    assert exc.value.status_code == 409
    assert "closed" in exc.value.detail.lower()


# --- Test 16 ---
@pytest.mark.asyncio
async def test_update_incident_409_when_resolved():
    db = _mock_db()
    inc = _make_incident(incident_status=IncidentStatus.resolved)
    with patch(f"{_SERVICE}._fetch_incident", new_callable=AsyncMock) as mock_fi:
        mock_fi.return_value = inc
        with pytest.raises(HTTPException) as exc:
            await update_incident_report(
                db, ACCOUNT_ID, INCIDENT_ID, IncidentReportUpdate(description="Updated")
            )
    assert exc.value.status_code == 409
    assert "resolved" in exc.value.detail.lower()


# --- Test 17 ---
@pytest.mark.asyncio
async def test_submit_incident_draft_to_reported():
    db = _mock_db()
    inc = _make_incident(incident_status=IncidentStatus.draft)
    with patch(f"{_SERVICE}._fetch_incident", new_callable=AsyncMock) as mock_fi:
        mock_fi.return_value = inc
        result = await submit_incident(db, ACCOUNT_ID, INCIDENT_ID, reported_by_id=USER_ID)
    assert inc.incident_status == IncidentStatus.reported
    assert inc.reported_by_id == USER_ID
    assert db.commit.called


# --- Test 18 ---
@pytest.mark.asyncio
async def test_submit_incident_409_if_not_draft():
    db = _mock_db()
    inc = _make_incident(incident_status=IncidentStatus.reported)
    with patch(f"{_SERVICE}._fetch_incident", new_callable=AsyncMock) as mock_fi:
        mock_fi.return_value = inc
        with pytest.raises(HTTPException) as exc:
            await submit_incident(db, ACCOUNT_ID, INCIDENT_ID, reported_by_id=USER_ID)
    assert exc.value.status_code == 409
    assert "draft" in exc.value.detail.lower()


# --- Test 19 ---
@pytest.mark.asyncio
async def test_mark_under_review_reported_to_under_review():
    db = _mock_db()
    inc = _make_incident(incident_status=IncidentStatus.reported)
    with patch(f"{_SERVICE}._fetch_incident", new_callable=AsyncMock) as mock_fi:
        mock_fi.return_value = inc
        result = await mark_under_review(db, ACCOUNT_ID, INCIDENT_ID, reviewed_by_id=ADMIN_ID)
    assert inc.incident_status == IncidentStatus.under_review
    assert inc.reviewed_by_id == ADMIN_ID
    assert db.commit.called


# --- Test 20 ---
@pytest.mark.asyncio
async def test_mark_under_review_409_if_not_reported():
    db = _mock_db()
    inc = _make_incident(incident_status=IncidentStatus.draft)
    with patch(f"{_SERVICE}._fetch_incident", new_callable=AsyncMock) as mock_fi:
        mock_fi.return_value = inc
        with pytest.raises(HTTPException) as exc:
            await mark_under_review(db, ACCOUNT_ID, INCIDENT_ID, reviewed_by_id=ADMIN_ID)
    assert exc.value.status_code == 409
    assert "reported" in exc.value.detail.lower()


# --- Test 21 ---
@pytest.mark.asyncio
async def test_resolve_incident_sets_resolved_at():
    db = _mock_db()
    inc = _make_incident(incident_status=IncidentStatus.under_review)
    with patch(f"{_SERVICE}._fetch_incident", new_callable=AsyncMock) as mock_fi:
        mock_fi.return_value = inc
        result = await resolve_incident(
            db, ACCOUNT_ID, INCIDENT_ID, reviewed_by_id=ADMIN_ID, notes="All damages assessed."
        )
    assert inc.incident_status == IncidentStatus.resolved
    assert inc.resolved_at is not None
    assert inc.notes == "All damages assessed."
    assert db.commit.called


# --- Test 22 ---
@pytest.mark.asyncio
async def test_resolve_incident_409_if_not_under_review():
    db = _mock_db()
    inc = _make_incident(incident_status=IncidentStatus.reported)
    with patch(f"{_SERVICE}._fetch_incident", new_callable=AsyncMock) as mock_fi:
        mock_fi.return_value = inc
        with pytest.raises(HTTPException) as exc:
            await resolve_incident(db, ACCOUNT_ID, INCIDENT_ID, reviewed_by_id=ADMIN_ID)
    assert exc.value.status_code == 409
    assert "under review" in exc.value.detail.lower()


# --- Test 23 ---
@pytest.mark.asyncio
async def test_close_incident_resolved_to_closed():
    db = _mock_db()
    inc = _make_incident(incident_status=IncidentStatus.resolved)
    with patch(f"{_SERVICE}._fetch_incident", new_callable=AsyncMock) as mock_fi:
        mock_fi.return_value = inc
        result = await close_incident(db, ACCOUNT_ID, INCIDENT_ID)
    assert inc.incident_status == IncidentStatus.closed
    assert db.commit.called


# --- Test 24 ---
@pytest.mark.asyncio
async def test_close_incident_409_if_not_resolved():
    db = _mock_db()
    inc = _make_incident(incident_status=IncidentStatus.under_review)
    with patch(f"{_SERVICE}._fetch_incident", new_callable=AsyncMock) as mock_fi:
        mock_fi.return_value = inc
        with pytest.raises(HTTPException) as exc:
            await close_incident(db, ACCOUNT_ID, INCIDENT_ID)
    assert exc.value.status_code == 409
    assert "resolved" in exc.value.detail.lower()


# --- Test 25 ---
@pytest.mark.asyncio
async def test_get_incident_summary_counts():
    db = _mock_db()
    rows = [
        _make_incident(incident_status=IncidentStatus.draft, incident_type=IncidentType.collision),
        _make_incident(
            incident_id=uuid.uuid4(),
            incident_status=IncidentStatus.reported,
            incident_type=IncidentType.vandalism,
        ),
        _make_incident(
            incident_id=uuid.uuid4(),
            incident_status=IncidentStatus.closed,
            incident_type=IncidentType.theft,
            estimated_damage_usd=5000.00,
        ),
    ]
    db.execute.return_value = _scalars_result(rows)
    summary = await get_incident_summary(db, ACCOUNT_ID)

    assert summary.total_incidents == 3
    assert summary.by_status["draft"] == 1
    assert summary.by_status["reported"] == 1
    assert summary.by_status["closed"] == 1
    assert summary.by_type["collision"] == 1
    assert summary.by_type["vandalism"] == 1
    assert summary.by_type["theft"] == 1


# --- Test 26 ---
@pytest.mark.asyncio
async def test_get_incident_summary_open_count():
    db = _mock_db()
    rows = [
        _make_incident(incident_status=IncidentStatus.draft),
        _make_incident(incident_id=uuid.uuid4(), incident_status=IncidentStatus.reported),
        _make_incident(incident_id=uuid.uuid4(), incident_status=IncidentStatus.under_review),
        _make_incident(incident_id=uuid.uuid4(), incident_status=IncidentStatus.resolved),
        _make_incident(incident_id=uuid.uuid4(), incident_status=IncidentStatus.closed),
    ]
    db.execute.return_value = _scalars_result(rows)
    summary = await get_incident_summary(db, ACCOUNT_ID)

    assert summary.open_count == 3  # draft + reported + under_review


# --- Test 27 ---
@pytest.mark.asyncio
async def test_get_incident_summary_damage_open_only():
    db = _mock_db()
    open_inc = _make_incident(
        incident_status=IncidentStatus.draft, estimated_damage_usd=2000.00
    )
    resolved_inc = _make_incident(
        incident_id=uuid.uuid4(),
        incident_status=IncidentStatus.resolved,
        estimated_damage_usd=10000.00,
    )
    db.execute.return_value = _scalars_result([open_inc, resolved_inc])
    summary = await get_incident_summary(db, ACCOUNT_ID)

    # Only open incident (draft) damage should be counted
    assert summary.total_estimated_damage_usd == pytest.approx(2000.00)


# --- Test 28 ---
@pytest.mark.asyncio
async def test_list_all_platform_returns_all():
    db = _mock_db()
    rows = [
        _make_incident(),
        _make_incident(incident_id=uuid.uuid4(), account_id=99),
    ]
    db.execute.return_value = _scalars_result(rows)
    results = await list_all_platform(db)
    assert len(results) == 2


# --- Test 29 ---
@pytest.mark.asyncio
async def test_list_all_platform_account_id_filter():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_incident()])
    results = await list_all_platform(db, account_id=ACCOUNT_ID)
    assert len(results) == 1
    assert results[0].account_id == ACCOUNT_ID


# ===========================================================================
# Schema validation tests (30–34)
# ===========================================================================


# --- Test 30 ---
def test_schema_create_valid():
    schema = IncidentReportCreate(
        fleet_vehicle_id=VEHICLE_ID,
        incident_type=IncidentType.collision,
        incident_date=_TODAY,
        description="Side-swipe collision on highway.",
        reported_by_id=USER_ID,
        estimated_damage_usd=3000.00,
    )
    assert schema.incident_type == IncidentType.collision
    assert schema.insurance_policy_id is None
    assert schema.driver_id is None


# --- Test 31 ---
def test_schema_create_missing_required_raises():
    with pytest.raises(ValidationError):
        # Missing fleet_vehicle_id, incident_type, incident_date, description, reported_by_id
        IncidentReportCreate(description="Some description")


# --- Test 32 ---
def test_schema_update_all_optional():
    schema = IncidentReportUpdate()
    assert schema.incident_date is None
    assert schema.description is None
    assert schema.estimated_damage_usd is None
    assert schema.incident_location is None
    assert schema.insurance_policy_id is None


# --- Test 33 ---
def test_schema_response_from_attributes():
    inc = _make_incident()
    resp = _make_response(inc)
    assert resp.id == INCIDENT_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.incident_type == "collision"
    assert resp.incident_status == "draft"
    assert resp.description == "Vehicle struck a bollard while parking."
    assert resp.estimated_damage_usd == pytest.approx(1500.00)


# --- Test 34 ---
def test_schema_summary_valid():
    summary = IncidentSummaryResponse(
        total_incidents=10,
        open_count=4,
        by_status={"draft": 2, "reported": 1, "under_review": 1, "resolved": 3, "closed": 3},
        by_type={"collision": 5, "vandalism": 2, "theft": 1, "parking_damage": 1, "mechanical_failure": 1, "other": 0},
        total_estimated_damage_usd=15000.00,
    )
    assert summary.total_incidents == 10
    assert summary.open_count == 4
    assert summary.total_estimated_damage_usd == 15000.00
    assert summary.by_type["collision"] == 5


# ===========================================================================
# API layer tests (35–45)
# ===========================================================================

client = TestClient(app)


def _make_user(user_id: int = USER_ID, is_admin: bool = False):
    from app.models.user import User

    u = MagicMock(spec=User)
    u.id = user_id
    u.is_admin = is_admin
    return u


def _dep_overrides(user_id: int = USER_ID, is_admin: bool = False):
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


def _resp_dict(inc: CorporateVehicleIncidentReport | None = None) -> dict:
    r = _make_response(inc)
    return r.model_dump(mode="json")


# --- Test 35 ---
def test_api_list_vehicle_incidents_200():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.list_vehicle_incidents",
            new_callable=AsyncMock,
            return_value=[_make_response()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/incidents"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert len(r.json()) == 1


# --- Test 36 ---
def test_api_get_incident_200():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_incident_report",
            new_callable=AsyncMock,
            return_value=_make_response(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-incidents/{INCIDENT_ID}"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["incident_status"] == "draft"


# --- Test 37 ---
def test_api_create_incident_201():
    resp = _make_response()
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.create_incident_report",
            new_callable=AsyncMock,
            return_value=resp,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-incidents/",
            json={
                "fleet_vehicle_id": str(VEHICLE_ID),
                "incident_type": "collision",
                "incident_date": str(_TODAY),
                "description": "Vehicle struck a bollard.",
                "reported_by_id": USER_ID,
            },
        )
        app.dependency_overrides.clear()
    assert r.status_code == 201


# --- Test 38 ---
def test_api_update_incident_200():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.update_incident_report",
            new_callable=AsyncMock,
            return_value=_make_response(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.put(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-incidents/{INCIDENT_ID}",
            json={"description": "Updated description after review."},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 39 ---
def test_api_submit_incident_200():
    submitted = _make_incident(incident_status=IncidentStatus.reported)
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.submit_incident",
            new_callable=AsyncMock,
            return_value=_make_response(submitted),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-incidents/{INCIDENT_ID}/submit"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["incident_status"] == "reported"


# --- Test 40 ---
def test_api_mark_under_review_200():
    under_review = _make_incident(incident_status=IncidentStatus.under_review)
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.mark_under_review",
            new_callable=AsyncMock,
            return_value=_make_response(under_review),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-incidents/{INCIDENT_ID}/review"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["incident_status"] == "under_review"


# --- Test 41 ---
def test_api_resolve_incident_200():
    resolved = _make_incident(
        incident_status=IncidentStatus.resolved, resolved_at=_NOW
    )
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.resolve_incident",
            new_callable=AsyncMock,
            return_value=_make_response(resolved),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-incidents/{INCIDENT_ID}/resolve"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["incident_status"] == "resolved"


# --- Test 42 ---
def test_api_close_incident_200():
    closed = _make_incident(incident_status=IncidentStatus.closed)
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.close_incident",
            new_callable=AsyncMock,
            return_value=_make_response(closed),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-incidents/{INCIDENT_ID}/close"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["incident_status"] == "closed"


# --- Test 43 ---
def test_api_list_account_incidents_200():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.list_account_incidents",
            new_callable=AsyncMock,
            return_value=[_make_response()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-incidents/")
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert len(r.json()) == 1


# --- Test 44 ---
def test_api_get_summary_200():
    summary = IncidentSummaryResponse(
        total_incidents=6,
        open_count=3,
        by_status={"draft": 1, "reported": 1, "under_review": 1, "resolved": 2, "closed": 1},
        by_type={"collision": 3, "vandalism": 1, "theft": 1, "parking_damage": 1, "mechanical_failure": 0, "other": 0},
        total_estimated_damage_usd=8500.00,
    )
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.get_incident_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-incidents/summary")
        app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert data["total_incidents"] == 6
    assert data["open_count"] == 3
    assert data["total_estimated_damage_usd"] == pytest.approx(8500.00)


# --- Test 45 ---
def test_api_platform_list_all_200():
    with patch(
        f"{_ROUTER}.list_all_platform",
        new_callable=AsyncMock,
        return_value=[_make_response()],
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get("/api/v1/platform/corporate/vehicle-incidents/")
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert len(r.json()) == 1
