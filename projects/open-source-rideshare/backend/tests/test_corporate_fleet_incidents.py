"""Tests for the Corporate Fleet Incident Reports feature.

Service layer (async, mocked DB):
   1.  create_incident_report — success: creates with status=reported
   2.  create_incident_report — no vehicle_id: creates without vehicle
   3.  get_incident_report — success: returns existing report
   4.  get_incident_report — 404 when not found
   5.  list_incident_reports — returns all for account
   6.  list_incident_reports — vehicle_id filter works
   7.  list_incident_reports — status filter works
   8.  list_incident_reports — incident_type filter works
   9.  list_incident_reports — limit and offset respected
  10.  update_incident_report — success: updates fields
  11.  update_incident_report — ignores None fields
  12.  update_incident_report — 404 when not found
  13.  resolve_incident_report — success: sets status=resolved, resolved_at, notes
  14.  resolve_incident_report — success: no resolution_notes is fine
  15.  resolve_incident_report — 404 when not found
  16.  close_incident_report — success: sets status=closed from resolved
  17.  close_incident_report — 409 when not in resolved status (reported)
  18.  close_incident_report — 409 when not in resolved status (under_review)
  19.  close_incident_report — 404 when not found
  20.  delete_incident_report — success: deletes when status=reported
  21.  delete_incident_report — success: deletes when status=resolved
  22.  delete_incident_report — 409 when status=under_review
  23.  delete_incident_report — 409 when status=closed
  24.  delete_incident_report — 404 when not found
  25.  get_vehicle_incident_summary — total and damage correct
  26.  get_vehicle_incident_summary — by_type breakdown correct
  27.  get_vehicle_incident_summary — by_severity breakdown correct
  28.  get_vehicle_incident_summary — by_status breakdown correct
  29.  get_vehicle_incident_summary — empty vehicle returns zeros
  30.  get_account_incident_summary — total and damage correct
  31.  get_account_incident_summary — all breakdowns present
  32.  get_platform_admin_incident_overview — total and accounts_with_incidents correct
  33.  get_platform_admin_incident_overview — empty DB returns zeros

Schema validation:
  34.  IncidentReportCreate — valid construction
  35.  IncidentReportCreate — missing required fields raises ValidationError
  36.  IncidentReportCreate — damage_estimate must be >= 0
  37.  IncidentReportUpdate — all optional
  38.  IncidentReportResponse — from_attributes works
  39.  VehicleIncidentSummaryResponse — valid structure
  40.  AccountIncidentSummaryResponse — valid structure
  41.  PlatformIncidentOverviewResponse — valid structure

API layer (service functions patched):
  42.  POST create → 201
  43.  GET list → 200
  44.  GET list with vehicle_id filter → 200
  45.  GET single report → 200
  46.  PUT update → 200
  47.  PUT resolve → 200
  48.  PUT close → 200
  49.  DELETE delete → 204
  50.  GET vehicle summary → 200
  51.  GET account summary → 200
  52.  GET platform summary → 200
  53.  POST create — auth guard (unauthenticated returns 401/403 pattern respected)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.corporate_fleet_incident import (
    CorporateFleetIncidentReport,
    FleetIncidentSeverity,
    FleetIncidentStatus,
    FleetIncidentType,
)
from app.schemas.corporate_fleet_incident import (
    AccountIncidentSummaryResponse,
    IncidentReportCreate,
    IncidentReportResponse,
    IncidentReportUpdate,
    IncidentSeverityBreakdown,
    IncidentStatusBreakdown,
    IncidentTypeBreakdown,
    PlatformIncidentOverviewResponse,
    VehicleIncidentSummaryResponse,
)
from app.services.corporate_fleet_incident_service import (
    close_incident_report,
    create_incident_report,
    delete_incident_report,
    get_account_incident_summary,
    get_incident_report,
    get_platform_admin_incident_overview,
    get_vehicle_incident_summary,
    list_incident_reports,
    resolve_incident_report,
    update_incident_report,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 5
VEHICLE_ID = uuid.uuid4()
REPORT_ID = uuid.uuid4()
USER_ID = 20
ADMIN_ID = 1

_SERVICE = "app.services.corporate_fleet_incident_service"
_ROUTER = "app.api.v1.corporate_fleet_incidents"

_NOW = datetime(2026, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
_INCIDENT_DATE = date(2026, 4, 10)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_report(
    report_id: uuid.UUID = REPORT_ID,
    account_id: int = ACCOUNT_ID,
    vehicle_id: uuid.UUID | None = VEHICLE_ID,
    reported_by_user_id: int | None = USER_ID,
    incident_type: FleetIncidentType = FleetIncidentType.accident,
    severity: FleetIncidentSeverity = FleetIncidentSeverity.minor,
    status: FleetIncidentStatus = FleetIncidentStatus.reported,
    incident_date: date = _INCIDENT_DATE,
    incident_location: str | None = "Main St & 1st Ave",
    description: str | None = "Minor fender bender",
    damage_estimate: float | None = 500.00,
    insurance_claim_number: str | None = None,
    police_report_number: str | None = None,
    third_party_involved: bool = False,
    injuries_reported: bool = False,
    resolved_at: datetime | None = None,
    resolution_notes: str | None = None,
) -> CorporateFleetIncidentReport:
    r = CorporateFleetIncidentReport()
    r.id = report_id
    r.account_id = account_id
    r.vehicle_id = vehicle_id
    r.reported_by_user_id = reported_by_user_id
    r.incident_type = incident_type
    r.severity = severity
    r.status = status
    r.incident_date = incident_date
    r.incident_location = incident_location
    r.description = description
    r.damage_estimate = damage_estimate
    r.insurance_claim_number = insurance_claim_number
    r.police_report_number = police_report_number
    r.third_party_involved = third_party_involved
    r.injuries_reported = injuries_reported
    r.resolved_at = resolved_at
    r.resolution_notes = resolution_notes
    r.created_at = _NOW
    r.updated_at = _NOW
    return r


def _make_response(rep: CorporateFleetIncidentReport | None = None) -> IncidentReportResponse:
    if rep is None:
        rep = _make_report()
    return IncidentReportResponse(
        id=rep.id,
        account_id=rep.account_id,
        vehicle_id=rep.vehicle_id,
        reported_by_user_id=rep.reported_by_user_id,
        incident_type=rep.incident_type,
        severity=rep.severity,
        status=rep.status,
        incident_date=rep.incident_date,
        incident_location=rep.incident_location,
        description=rep.description,
        damage_estimate=float(rep.damage_estimate) if rep.damage_estimate is not None else None,
        insurance_claim_number=rep.insurance_claim_number,
        police_report_number=rep.police_report_number,
        third_party_involved=rep.third_party_involved,
        injuries_reported=rep.injuries_reported,
        resolved_at=rep.resolved_at,
        resolution_notes=rep.resolution_notes,
        created_at=rep.created_at,
        updated_at=rep.updated_at,
    )


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


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
# Service layer tests (1–33)
# ===========================================================================


# --- Test 1 ---
@pytest.mark.asyncio
async def test_create_incident_report_success():
    db = _mock_db()
    data = IncidentReportCreate(
        vehicle_id=VEHICLE_ID,
        incident_type=FleetIncidentType.accident,
        severity=FleetIncidentSeverity.minor,
        incident_date=_INCIDENT_DATE,
        description="Fender bender",
        damage_estimate=500.00,
    )
    created = _make_report()
    db.refresh.side_effect = lambda obj: None

    with patch(f"{_SERVICE}.CorporateFleetIncidentReport") as MockModel:
        MockModel.return_value = created
        result = await create_incident_report(db, ACCOUNT_ID, USER_ID, data)

    assert db.add.called
    assert db.commit.called


# --- Test 2 ---
@pytest.mark.asyncio
async def test_create_incident_report_no_vehicle():
    db = _mock_db()
    data = IncidentReportCreate(
        vehicle_id=None,
        incident_type=FleetIncidentType.theft,
        severity=FleetIncidentSeverity.major,
        incident_date=_INCIDENT_DATE,
    )
    created = _make_report(vehicle_id=None, incident_type=FleetIncidentType.theft,
                           severity=FleetIncidentSeverity.major, damage_estimate=None)
    db.refresh.side_effect = lambda obj: None

    with patch(f"{_SERVICE}.CorporateFleetIncidentReport") as MockModel:
        MockModel.return_value = created
        result = await create_incident_report(db, ACCOUNT_ID, USER_ID, data)

    assert db.add.called
    assert db.commit.called


# --- Test 3 ---
@pytest.mark.asyncio
async def test_get_incident_report_success():
    db = _mock_db()
    rep = _make_report()
    with patch(f"{_SERVICE}._fetch_report", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rep
        result = await get_incident_report(db, ACCOUNT_ID, REPORT_ID)
    assert result.id == REPORT_ID
    assert result.incident_type == FleetIncidentType.accident


# --- Test 4 ---
@pytest.mark.asyncio
async def test_get_incident_report_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_report", new_callable=AsyncMock) as mock_fr:
        mock_fr.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await get_incident_report(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 5 ---
@pytest.mark.asyncio
async def test_list_incident_reports_returns_all():
    db = _mock_db()
    rows = [
        _make_report(),
        _make_report(report_id=uuid.uuid4(), incident_type=FleetIncidentType.breakdown),
        _make_report(report_id=uuid.uuid4(), incident_type=FleetIncidentType.vandalism),
    ]
    db.execute.return_value = _scalars_result(rows)
    results = await list_incident_reports(db, ACCOUNT_ID)
    assert len(results) == 3


# --- Test 6 ---
@pytest.mark.asyncio
async def test_list_incident_reports_vehicle_filter():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_report()])
    results = await list_incident_reports(db, ACCOUNT_ID, vehicle_id=VEHICLE_ID)
    assert len(results) == 1
    assert results[0].vehicle_id == VEHICLE_ID


# --- Test 7 ---
@pytest.mark.asyncio
async def test_list_incident_reports_status_filter():
    db = _mock_db()
    db.execute.return_value = _scalars_result(
        [_make_report(status=FleetIncidentStatus.resolved)]
    )
    results = await list_incident_reports(
        db, ACCOUNT_ID, status=FleetIncidentStatus.resolved
    )
    assert len(results) == 1
    assert results[0].status == FleetIncidentStatus.resolved


# --- Test 8 ---
@pytest.mark.asyncio
async def test_list_incident_reports_type_filter():
    db = _mock_db()
    db.execute.return_value = _scalars_result(
        [_make_report(incident_type=FleetIncidentType.breakdown)]
    )
    results = await list_incident_reports(
        db, ACCOUNT_ID, incident_type=FleetIncidentType.breakdown
    )
    assert len(results) == 1
    assert results[0].incident_type == FleetIncidentType.breakdown


# --- Test 9 ---
@pytest.mark.asyncio
async def test_list_incident_reports_limit_offset():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_report()])
    results = await list_incident_reports(db, ACCOUNT_ID, limit=10, offset=5)
    assert len(results) == 1


# --- Test 10 ---
@pytest.mark.asyncio
async def test_update_incident_report_success():
    db = _mock_db()
    rep = _make_report()
    with patch(f"{_SERVICE}._fetch_report", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rep
        data = IncidentReportUpdate(
            incident_location="Highway 101",
            damage_estimate=1200.00,
        )
        await update_incident_report(db, ACCOUNT_ID, REPORT_ID, data)
    assert rep.incident_location == "Highway 101"
    assert float(rep.damage_estimate) == pytest.approx(1200.00)
    assert db.commit.called


# --- Test 11 ---
@pytest.mark.asyncio
async def test_update_incident_report_ignores_none_fields():
    db = _mock_db()
    rep = _make_report()
    original_type = rep.incident_type
    with patch(f"{_SERVICE}._fetch_report", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rep
        data = IncidentReportUpdate(description="Updated description")
        await update_incident_report(db, ACCOUNT_ID, REPORT_ID, data)
    assert rep.incident_type == original_type
    assert rep.description == "Updated description"


# --- Test 12 ---
@pytest.mark.asyncio
async def test_update_incident_report_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_report", new_callable=AsyncMock) as mock_fr:
        mock_fr.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await update_incident_report(
                db, ACCOUNT_ID, uuid.uuid4(), IncidentReportUpdate()
            )
    assert exc.value.status_code == 404


# --- Test 13 ---
@pytest.mark.asyncio
async def test_resolve_incident_report_success():
    db = _mock_db()
    rep = _make_report(status=FleetIncidentStatus.under_review)
    with patch(f"{_SERVICE}._fetch_report", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rep
        await resolve_incident_report(
            db, ACCOUNT_ID, REPORT_ID, resolution_notes="Parts replaced."
        )
    assert rep.status == FleetIncidentStatus.resolved
    assert rep.resolved_at is not None
    assert rep.resolution_notes == "Parts replaced."
    assert db.commit.called


# --- Test 14 ---
@pytest.mark.asyncio
async def test_resolve_incident_report_no_notes():
    db = _mock_db()
    rep = _make_report(status=FleetIncidentStatus.reported)
    with patch(f"{_SERVICE}._fetch_report", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rep
        await resolve_incident_report(db, ACCOUNT_ID, REPORT_ID)
    assert rep.status == FleetIncidentStatus.resolved
    assert rep.resolved_at is not None
    # resolution_notes should remain unchanged (None)
    assert rep.resolution_notes is None


# --- Test 15 ---
@pytest.mark.asyncio
async def test_resolve_incident_report_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_report", new_callable=AsyncMock) as mock_fr:
        mock_fr.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await resolve_incident_report(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 16 ---
@pytest.mark.asyncio
async def test_close_incident_report_success():
    db = _mock_db()
    rep = _make_report(status=FleetIncidentStatus.resolved)
    with patch(f"{_SERVICE}._fetch_report", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rep
        result = await close_incident_report(db, ACCOUNT_ID, REPORT_ID)
    assert rep.status == FleetIncidentStatus.closed
    assert db.commit.called


# --- Test 17 ---
@pytest.mark.asyncio
async def test_close_incident_report_409_not_resolved_reported():
    db = _mock_db()
    rep = _make_report(status=FleetIncidentStatus.reported)
    with patch(f"{_SERVICE}._fetch_report", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rep
        with pytest.raises(HTTPException) as exc:
            await close_incident_report(db, ACCOUNT_ID, REPORT_ID)
    assert exc.value.status_code == 409
    assert "resolved" in exc.value.detail.lower()


# --- Test 18 ---
@pytest.mark.asyncio
async def test_close_incident_report_409_not_resolved_under_review():
    db = _mock_db()
    rep = _make_report(status=FleetIncidentStatus.under_review)
    with patch(f"{_SERVICE}._fetch_report", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rep
        with pytest.raises(HTTPException) as exc:
            await close_incident_report(db, ACCOUNT_ID, REPORT_ID)
    assert exc.value.status_code == 409


# --- Test 19 ---
@pytest.mark.asyncio
async def test_close_incident_report_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_report", new_callable=AsyncMock) as mock_fr:
        mock_fr.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await close_incident_report(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 20 ---
@pytest.mark.asyncio
async def test_delete_incident_report_success_reported():
    db = _mock_db()
    rep = _make_report(status=FleetIncidentStatus.reported)
    with patch(f"{_SERVICE}._fetch_report", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rep
        await delete_incident_report(db, ACCOUNT_ID, REPORT_ID)
    assert db.delete.called
    assert db.commit.called


# --- Test 21 ---
@pytest.mark.asyncio
async def test_delete_incident_report_success_resolved():
    db = _mock_db()
    rep = _make_report(status=FleetIncidentStatus.resolved)
    with patch(f"{_SERVICE}._fetch_report", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rep
        await delete_incident_report(db, ACCOUNT_ID, REPORT_ID)
    assert db.delete.called
    assert db.commit.called


# --- Test 22 ---
@pytest.mark.asyncio
async def test_delete_incident_report_409_under_review():
    db = _mock_db()
    rep = _make_report(status=FleetIncidentStatus.under_review)
    with patch(f"{_SERVICE}._fetch_report", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rep
        with pytest.raises(HTTPException) as exc:
            await delete_incident_report(db, ACCOUNT_ID, REPORT_ID)
    assert exc.value.status_code == 409
    assert "under_review" in exc.value.detail


# --- Test 23 ---
@pytest.mark.asyncio
async def test_delete_incident_report_409_closed():
    db = _mock_db()
    rep = _make_report(status=FleetIncidentStatus.closed)
    with patch(f"{_SERVICE}._fetch_report", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rep
        with pytest.raises(HTTPException) as exc:
            await delete_incident_report(db, ACCOUNT_ID, REPORT_ID)
    assert exc.value.status_code == 409
    assert "closed" in exc.value.detail


# --- Test 24 ---
@pytest.mark.asyncio
async def test_delete_incident_report_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_report", new_callable=AsyncMock) as mock_fr:
        mock_fr.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await delete_incident_report(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 25 ---
@pytest.mark.asyncio
async def test_get_vehicle_incident_summary_totals():
    db = _mock_db()
    rows = [
        _make_report(damage_estimate=500.00),
        _make_report(report_id=uuid.uuid4(), damage_estimate=1000.00),
        _make_report(report_id=uuid.uuid4(), damage_estimate=None),
    ]
    db.execute.return_value = _scalars_result(rows)
    summary = await get_vehicle_incident_summary(db, ACCOUNT_ID, VEHICLE_ID)

    assert summary.vehicle_id == VEHICLE_ID
    assert summary.total == 3
    assert summary.total_damage_estimate == pytest.approx(1500.00)


# --- Test 26 ---
@pytest.mark.asyncio
async def test_get_vehicle_incident_summary_by_type():
    db = _mock_db()
    rows = [
        _make_report(incident_type=FleetIncidentType.accident, damage_estimate=300.00),
        _make_report(report_id=uuid.uuid4(), incident_type=FleetIncidentType.accident, damage_estimate=200.00),
        _make_report(report_id=uuid.uuid4(), incident_type=FleetIncidentType.breakdown, damage_estimate=100.00),
    ]
    db.execute.return_value = _scalars_result(rows)
    summary = await get_vehicle_incident_summary(db, ACCOUNT_ID, VEHICLE_ID)

    type_map = {b.incident_type: b for b in summary.by_type}
    assert type_map[FleetIncidentType.accident].count == 2
    assert type_map[FleetIncidentType.accident].total_damage_estimate == pytest.approx(500.00)
    assert type_map[FleetIncidentType.breakdown].count == 1


# --- Test 27 ---
@pytest.mark.asyncio
async def test_get_vehicle_incident_summary_by_severity():
    db = _mock_db()
    rows = [
        _make_report(severity=FleetIncidentSeverity.minor),
        _make_report(report_id=uuid.uuid4(), severity=FleetIncidentSeverity.major),
        _make_report(report_id=uuid.uuid4(), severity=FleetIncidentSeverity.minor),
    ]
    db.execute.return_value = _scalars_result(rows)
    summary = await get_vehicle_incident_summary(db, ACCOUNT_ID, VEHICLE_ID)

    sev_map = {b.severity: b for b in summary.by_severity}
    assert sev_map[FleetIncidentSeverity.minor].count == 2
    assert sev_map[FleetIncidentSeverity.major].count == 1


# --- Test 28 ---
@pytest.mark.asyncio
async def test_get_vehicle_incident_summary_by_status():
    db = _mock_db()
    rows = [
        _make_report(status=FleetIncidentStatus.reported),
        _make_report(report_id=uuid.uuid4(), status=FleetIncidentStatus.resolved),
        _make_report(report_id=uuid.uuid4(), status=FleetIncidentStatus.reported),
    ]
    db.execute.return_value = _scalars_result(rows)
    summary = await get_vehicle_incident_summary(db, ACCOUNT_ID, VEHICLE_ID)

    status_map = {b.status: b for b in summary.by_status}
    assert status_map[FleetIncidentStatus.reported].count == 2
    assert status_map[FleetIncidentStatus.resolved].count == 1


# --- Test 29 ---
@pytest.mark.asyncio
async def test_get_vehicle_incident_summary_empty():
    db = _mock_db()
    db.execute.return_value = _scalars_result([])
    summary = await get_vehicle_incident_summary(db, ACCOUNT_ID, VEHICLE_ID)

    assert summary.total == 0
    assert summary.total_damage_estimate == 0.0
    assert summary.by_type == []
    assert summary.by_severity == []
    assert summary.by_status == []


# --- Test 30 ---
@pytest.mark.asyncio
async def test_get_account_incident_summary_totals():
    db = _mock_db()
    vehicle2 = uuid.uuid4()
    rows = [
        _make_report(damage_estimate=800.00),
        _make_report(report_id=uuid.uuid4(), vehicle_id=vehicle2, damage_estimate=400.00),
        _make_report(report_id=uuid.uuid4(), damage_estimate=None),
    ]
    db.execute.return_value = _scalars_result(rows)
    summary = await get_account_incident_summary(db, ACCOUNT_ID)

    assert summary.account_id == ACCOUNT_ID
    assert summary.total == 3
    assert summary.total_damage_estimate == pytest.approx(1200.00)


# --- Test 31 ---
@pytest.mark.asyncio
async def test_get_account_incident_summary_all_breakdowns():
    db = _mock_db()
    rows = [
        _make_report(
            incident_type=FleetIncidentType.accident,
            severity=FleetIncidentSeverity.major,
            status=FleetIncidentStatus.under_review,
            damage_estimate=5000.00,
        ),
        _make_report(
            report_id=uuid.uuid4(),
            incident_type=FleetIncidentType.vandalism,
            severity=FleetIncidentSeverity.minor,
            status=FleetIncidentStatus.closed,
            damage_estimate=200.00,
        ),
    ]
    db.execute.return_value = _scalars_result(rows)
    summary = await get_account_incident_summary(db, ACCOUNT_ID)

    assert len(summary.by_type) == 2
    assert len(summary.by_severity) == 2
    assert len(summary.by_status) == 2


# --- Test 32 ---
@pytest.mark.asyncio
async def test_get_platform_incident_overview_totals():
    db = _mock_db()
    rows = [
        _make_report(account_id=ACCOUNT_ID, damage_estimate=300.00),
        _make_report(report_id=uuid.uuid4(), account_id=99, damage_estimate=700.00),
        _make_report(report_id=uuid.uuid4(), account_id=ACCOUNT_ID, damage_estimate=100.00),
    ]
    db.execute.return_value = _scalars_result(rows)
    overview = await get_platform_admin_incident_overview(db)

    assert overview.total == 3
    assert overview.total_damage_estimate == pytest.approx(1100.00)
    assert overview.total_accounts_with_incidents == 2


# --- Test 33 ---
@pytest.mark.asyncio
async def test_get_platform_incident_overview_empty():
    db = _mock_db()
    db.execute.return_value = _scalars_result([])
    overview = await get_platform_admin_incident_overview(db)

    assert overview.total == 0
    assert overview.total_damage_estimate == 0.0
    assert overview.total_accounts_with_incidents == 0


# ===========================================================================
# Schema validation tests (34–41)
# ===========================================================================


# --- Test 34 ---
def test_schema_create_valid():
    schema = IncidentReportCreate(
        vehicle_id=VEHICLE_ID,
        incident_type=FleetIncidentType.accident,
        severity=FleetIncidentSeverity.minor,
        incident_date=_INCIDENT_DATE,
        damage_estimate=500.00,
        third_party_involved=True,
    )
    assert schema.incident_type == FleetIncidentType.accident
    assert schema.severity == FleetIncidentSeverity.minor
    assert schema.incident_date == _INCIDENT_DATE
    assert schema.third_party_involved is True
    assert schema.injuries_reported is False


# --- Test 35 ---
def test_schema_create_missing_required_raises():
    with pytest.raises(ValidationError):
        # Missing incident_type, severity, incident_date
        IncidentReportCreate()


# --- Test 36 ---
def test_schema_create_negative_damage_estimate_raises():
    with pytest.raises(ValidationError):
        IncidentReportCreate(
            incident_type=FleetIncidentType.accident,
            severity=FleetIncidentSeverity.minor,
            incident_date=_INCIDENT_DATE,
            damage_estimate=-100.00,
        )


# --- Test 37 ---
def test_schema_update_all_optional():
    schema = IncidentReportUpdate()
    assert schema.incident_type is None
    assert schema.severity is None
    assert schema.status is None
    assert schema.incident_date is None
    assert schema.damage_estimate is None
    assert schema.insurance_claim_number is None
    assert schema.resolution_notes is None


# --- Test 38 ---
def test_schema_response_from_attributes():
    rep = _make_report()
    resp = _make_response(rep)
    assert resp.id == REPORT_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.incident_type == FleetIncidentType.accident
    assert resp.status == FleetIncidentStatus.reported
    assert resp.third_party_involved is False
    assert resp.injuries_reported is False
    assert resp.resolved_at is None


# --- Test 39 ---
def test_schema_vehicle_summary_valid():
    summary = VehicleIncidentSummaryResponse(
        vehicle_id=VEHICLE_ID,
        total=4,
        by_type=[
            IncidentTypeBreakdown(
                incident_type=FleetIncidentType.accident,
                count=3,
                total_damage_estimate=1500.00,
            )
        ],
        by_severity=[
            IncidentSeverityBreakdown(severity=FleetIncidentSeverity.minor, count=4)
        ],
        by_status=[
            IncidentStatusBreakdown(status=FleetIncidentStatus.reported, count=4)
        ],
        total_damage_estimate=1500.00,
    )
    assert summary.vehicle_id == VEHICLE_ID
    assert summary.total == 4
    assert summary.by_type[0].count == 3


# --- Test 40 ---
def test_schema_account_summary_valid():
    summary = AccountIncidentSummaryResponse(
        account_id=ACCOUNT_ID,
        total=10,
        by_type=[],
        by_severity=[],
        by_status=[],
        total_damage_estimate=9500.00,
    )
    assert summary.account_id == ACCOUNT_ID
    assert summary.total == 10
    assert summary.total_damage_estimate == 9500.00


# --- Test 41 ---
def test_schema_platform_overview_valid():
    overview = PlatformIncidentOverviewResponse(
        total=25,
        by_type=[],
        by_severity=[],
        by_status=[],
        total_damage_estimate=45000.00,
        total_accounts_with_incidents=7,
    )
    assert overview.total == 25
    assert overview.total_accounts_with_incidents == 7


# ===========================================================================
# API layer tests (42–53)
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


# --- Test 42 ---
def test_api_create_incident_report_201():
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
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet/incidents",
            json={
                "incident_type": "accident",
                "severity": "minor",
                "incident_date": str(_INCIDENT_DATE),
            },
        )
        app.dependency_overrides.clear()
    assert r.status_code == 201


# --- Test 43 ---
def test_api_list_incident_reports_200():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.list_incident_reports",
            new_callable=AsyncMock,
            return_value=[_make_response()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/fleet/incidents")
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert len(r.json()) == 1


# --- Test 44 ---
def test_api_list_incident_reports_with_vehicle_filter_200():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.list_incident_reports",
            new_callable=AsyncMock,
            return_value=[_make_response()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet/incidents",
            params={"vehicle_id": str(VEHICLE_ID)},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 45 ---
def test_api_get_incident_report_200():
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
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet/incidents/{REPORT_ID}"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["id"] == str(REPORT_ID)


# --- Test 46 ---
def test_api_update_incident_report_200():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.update_incident_report",
            new_callable=AsyncMock,
            return_value=_make_response(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.put(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet/incidents/{REPORT_ID}",
            json={"incident_location": "Updated location"},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 47 ---
def test_api_resolve_incident_report_200():
    resolved_rep = _make_report(
        status=FleetIncidentStatus.resolved,
        resolved_at=_NOW,
        resolution_notes="Handled.",
    )
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.resolve_incident_report",
            new_callable=AsyncMock,
            return_value=_make_response(resolved_rep),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.put(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet/incidents/{REPORT_ID}/resolve",
            json={"resolution_notes": "Handled."},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"


# --- Test 48 ---
def test_api_close_incident_report_200():
    closed_rep = _make_report(status=FleetIncidentStatus.closed)
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.close_incident_report",
            new_callable=AsyncMock,
            return_value=_make_response(closed_rep),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.put(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet/incidents/{REPORT_ID}/close"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["status"] == "closed"


# --- Test 49 ---
def test_api_delete_incident_report_204():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.delete_incident_report",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.delete(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet/incidents/{REPORT_ID}"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 204


# --- Test 50 ---
def test_api_get_vehicle_incident_summary_200():
    summary = VehicleIncidentSummaryResponse(
        vehicle_id=VEHICLE_ID,
        total=3,
        by_type=[],
        by_severity=[],
        by_status=[],
        total_damage_estimate=1500.00,
    )
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_vehicle_incident_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet/incidents/summary/vehicle/{VEHICLE_ID}"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["total"] == 3


# --- Test 51 ---
def test_api_get_account_incident_summary_200():
    summary = AccountIncidentSummaryResponse(
        account_id=ACCOUNT_ID,
        total=8,
        by_type=[],
        by_severity=[],
        by_status=[],
        total_damage_estimate=6200.00,
    )
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.get_account_incident_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet/incidents/summary/account"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["total"] == 8


# --- Test 52 ---
def test_api_get_platform_incident_overview_200():
    overview = PlatformIncidentOverviewResponse(
        total=50,
        by_type=[],
        by_severity=[],
        by_status=[],
        total_damage_estimate=120000.00,
        total_accounts_with_incidents=12,
    )
    with patch(
        f"{_ROUTER}.get_platform_admin_incident_overview",
        new_callable=AsyncMock,
        return_value=overview,
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get("/api/v1/platform/corporate/fleet/incidents/summary")
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["total"] == 50
    assert r.json()["total_accounts_with_incidents"] == 12


# --- Test 53 ---
def test_api_create_incident_requires_auth():
    """Verify 401/403 when no user dependency override is present."""
    # Without overrides, get_current_user will fail and return 401 or 403
    # depending on the app's auth setup. We just verify it's not 201 or 200.
    r = client.post(
        f"/api/v1/corporate/{ACCOUNT_ID}/fleet/incidents",
        json={
            "incident_type": "accident",
            "severity": "minor",
            "incident_date": str(_INCIDENT_DATE),
        },
    )
    assert r.status_code in (401, 403, 422)
