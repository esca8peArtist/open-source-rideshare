"""Tests for the Corporate Fleet Vehicle Acquisition and Disposal feature.

Service layer (async, mocked DB):
   1.  record_acquisition — success: creates new active acquisition
   2.  record_acquisition — success: deactivates previous active acquisition
   3.  record_acquisition — 404 when vehicle not in account
   4.  get_acquisition — success: returns existing acquisition
   5.  get_acquisition — 404 when not found
   6.  get_vehicle_acquisition — returns active acquisition
   7.  get_vehicle_acquisition — returns None when no active acquisition
   8.  list_vehicle_acquisitions — returns full history
   9.  list_vehicle_acquisitions — returns empty list when none exist
  10.  update_acquisition — success: updates fields
  11.  update_acquisition — 404 when not found
  12.  dispose_vehicle — success: creates disposal, deactivates vehicle and acquisition
  13.  dispose_vehicle — 404 when vehicle not found
  14.  dispose_vehicle — 409 when vehicle already disposed
  15.  dispose_vehicle — success when no active acquisition exists
  16.  get_disposal — success: returns disposal record
  17.  get_disposal — 404 when not found
  18.  get_vehicle_disposal — returns disposal when exists
  19.  get_vehicle_disposal — returns None when not disposed
  20.  list_account_disposals — returns all for account
  21.  list_account_disposals — filters by disposal_reason
  22.  list_account_disposals — filters by from_date
  23.  list_account_disposals — filters by to_date
  24.  get_fleet_ownership_summary — counts active and total vehicles
  25.  get_fleet_ownership_summary — by_acquisition_type counts active acquisitions
  26.  get_fleet_ownership_summary — sums monthly lease payments
  27.  get_fleet_ownership_summary — sums monthly loan payments
  28.  get_fleet_ownership_summary — counts leases expiring within 90 days
  29.  get_fleet_ownership_summary — does not count expired or far-future leases
  30.  list_all_platform — returns all acquisitions
  31.  list_all_platform — filters by account_id

Schema validation:
  32.  AcquisitionCreate — valid construction
  33.  AcquisitionCreate — acquisition_type required
  34.  AcquisitionCreate — acquisition_date required
  35.  AcquisitionUpdate — all optional
  36.  AcquisitionResponse — from_attributes works
  37.  DisposalCreate — valid construction
  38.  DisposalCreate — disposal_reason required
  39.  DisposalResponse — from_attributes works
  40.  FleetOwnershipSummary — valid structure

API layer (service functions patched):
  41.  GET active acquisition → 200
  42.  GET acquisition history → 200
  43.  GET vehicle disposal → 200
  44.  GET fleet ownership summary → 200
  45.  POST record acquisition → 201
  46.  PUT update acquisition → 200
  47.  POST dispose vehicle → 201
  48.  GET list account disposals → 200
  49.  GET get disposal by id → 200
  50.  GET platform list all → 200
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.corporate_fleet_acquisition import (
    AcquisitionType,
    CorporateFleetVehicleAcquisition,
    CorporateFleetVehicleDisposal,
    DisposalReason,
)
from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
from app.schemas.corporate_fleet_acquisition import (
    AcquisitionCreate,
    AcquisitionResponse,
    AcquisitionUpdate,
    DisposalCreate,
    DisposalResponse,
    FleetOwnershipSummary,
)
from app.services.corporate_fleet_acquisition_service import (
    dispose_vehicle,
    get_acquisition,
    get_disposal,
    get_fleet_ownership_summary,
    get_vehicle_acquisition,
    get_vehicle_disposal,
    list_account_disposals,
    list_all_platform,
    list_vehicle_acquisitions,
    record_acquisition,
    update_acquisition,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 5
VEHICLE_ID = uuid.uuid4()
ACQ_ID = uuid.uuid4()
DISPOSAL_ID = uuid.uuid4()
USER_ID = 20
ADMIN_ID = 1

_SERVICE = "app.services.corporate_fleet_acquisition_service"
_ROUTER = "app.api.v1.corporate_fleet_acquisition"

_NOW = datetime(2026, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
_ACQ_DATE = date(2024, 3, 15)
_DISPOSAL_DATE = date(2026, 4, 1)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_vehicle(is_active: bool = True) -> CorporateFleetVehicle:
    v = CorporateFleetVehicle()
    v.id = VEHICLE_ID
    v.account_id = ACCOUNT_ID
    v.name = "Fleet SUV 1"
    v.is_active = is_active
    return v


def _make_acquisition(
    acq_id: uuid.UUID = ACQ_ID,
    account_id: int = ACCOUNT_ID,
    fleet_vehicle_id: uuid.UUID = VEHICLE_ID,
    acquisition_type: AcquisitionType = AcquisitionType.purchased,
    vendor_name: str | None = "Acme Motors",
    acquisition_date: date = _ACQ_DATE,
    acquisition_cost_usd: float | None = 35_000.00,
    lease_start_date: date | None = None,
    lease_end_date: date | None = None,
    monthly_lease_payment_usd: float | None = None,
    lease_mileage_allowance_annual: int | None = None,
    financed_amount_usd: float | None = None,
    loan_term_months: int | None = None,
    monthly_loan_payment_usd: float | None = None,
    notes: str | None = None,
    is_active: bool = True,
    created_by_id: int | None = ADMIN_ID,
) -> CorporateFleetVehicleAcquisition:
    acq = CorporateFleetVehicleAcquisition()
    acq.id = acq_id
    acq.account_id = account_id
    acq.fleet_vehicle_id = fleet_vehicle_id
    acq.acquisition_type = acquisition_type
    acq.vendor_name = vendor_name
    acq.acquisition_date = acquisition_date
    acq.acquisition_cost_usd = acquisition_cost_usd
    acq.lease_start_date = lease_start_date
    acq.lease_end_date = lease_end_date
    acq.monthly_lease_payment_usd = monthly_lease_payment_usd
    acq.lease_mileage_allowance_annual = lease_mileage_allowance_annual
    acq.financed_amount_usd = financed_amount_usd
    acq.loan_term_months = loan_term_months
    acq.monthly_loan_payment_usd = monthly_loan_payment_usd
    acq.notes = notes
    acq.is_active = is_active
    acq.created_by_id = created_by_id
    acq.created_at = _NOW
    acq.updated_at = _NOW
    return acq


def _make_disposal(
    disposal_id: uuid.UUID = DISPOSAL_ID,
    account_id: int = ACCOUNT_ID,
    fleet_vehicle_id: uuid.UUID = VEHICLE_ID,
    disposal_reason: DisposalReason = DisposalReason.sold,
    disposal_date: date = _DISPOSAL_DATE,
    sale_price_usd: float | None = 20_000.00,
    buyer_name: str | None = "Used Car Lot",
    notes: str | None = None,
    disposed_by_id: int | None = ADMIN_ID,
) -> CorporateFleetVehicleDisposal:
    d = CorporateFleetVehicleDisposal()
    d.id = disposal_id
    d.account_id = account_id
    d.fleet_vehicle_id = fleet_vehicle_id
    d.disposal_reason = disposal_reason
    d.disposal_date = disposal_date
    d.sale_price_usd = sale_price_usd
    d.buyer_name = buyer_name
    d.notes = notes
    d.disposed_by_id = disposed_by_id
    d.created_at = _NOW
    return d


def _make_acq_response(acq: CorporateFleetVehicleAcquisition | None = None) -> AcquisitionResponse:
    if acq is None:
        acq = _make_acquisition()
    return AcquisitionResponse(
        id=acq.id,
        fleet_vehicle_id=acq.fleet_vehicle_id,
        account_id=acq.account_id,
        acquisition_type=acq.acquisition_type.value
        if hasattr(acq.acquisition_type, "value")
        else str(acq.acquisition_type),
        vendor_name=acq.vendor_name,
        acquisition_date=acq.acquisition_date,
        acquisition_cost_usd=float(acq.acquisition_cost_usd)
        if acq.acquisition_cost_usd is not None
        else None,
        lease_start_date=acq.lease_start_date,
        lease_end_date=acq.lease_end_date,
        monthly_lease_payment_usd=float(acq.monthly_lease_payment_usd)
        if acq.monthly_lease_payment_usd is not None
        else None,
        lease_mileage_allowance_annual=acq.lease_mileage_allowance_annual,
        financed_amount_usd=float(acq.financed_amount_usd)
        if acq.financed_amount_usd is not None
        else None,
        loan_term_months=acq.loan_term_months,
        monthly_loan_payment_usd=float(acq.monthly_loan_payment_usd)
        if acq.monthly_loan_payment_usd is not None
        else None,
        notes=acq.notes,
        is_active=acq.is_active,
        created_by_id=acq.created_by_id,
        created_at=acq.created_at,
        updated_at=acq.updated_at,
    )


def _make_disposal_response(d: CorporateFleetVehicleDisposal | None = None) -> DisposalResponse:
    if d is None:
        d = _make_disposal()
    return DisposalResponse(
        id=d.id,
        fleet_vehicle_id=d.fleet_vehicle_id,
        account_id=d.account_id,
        disposal_reason=d.disposal_reason.value
        if hasattr(d.disposal_reason, "value")
        else str(d.disposal_reason),
        disposal_date=d.disposal_date,
        sale_price_usd=float(d.sale_price_usd) if d.sale_price_usd is not None else None,
        buyer_name=d.buyer_name,
        notes=d.notes,
        disposed_by_id=d.disposed_by_id,
        created_at=d.created_at,
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
# Service layer tests (1–31)
# ===========================================================================


# --- Test 1 ---
@pytest.mark.asyncio
async def test_record_acquisition_success_no_prior():
    db = _mock_db()
    data = AcquisitionCreate(
        acquisition_type=AcquisitionType.purchased,
        acquisition_date=_ACQ_DATE,
        acquisition_cost_usd=35_000.00,
        vendor_name="Acme Motors",
    )

    def _refresh_acq(obj):
        obj.created_at = _NOW
        obj.updated_at = _NOW

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _make_vehicle()
        # No prior active acquisition.
        db.execute.return_value = _scalar_result(None)
        db.refresh.side_effect = _refresh_acq
        await record_acquisition(db, ACCOUNT_ID, VEHICLE_ID, data, created_by_id=ADMIN_ID)

    assert db.add.called
    assert db.commit.called


# --- Test 2 ---
@pytest.mark.asyncio
async def test_record_acquisition_deactivates_previous():
    db = _mock_db()
    data = AcquisitionCreate(
        acquisition_type=AcquisitionType.leased,
        acquisition_date=date.today(),
        monthly_lease_payment_usd=600.00,
    )
    old_acq = _make_acquisition(is_active=True)

    def _refresh_acq(obj):
        obj.created_at = _NOW
        obj.updated_at = _NOW

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _make_vehicle()
        db.execute.return_value = _scalar_result(old_acq)
        db.refresh.side_effect = _refresh_acq
        await record_acquisition(db, ACCOUNT_ID, VEHICLE_ID, data)

    assert old_acq.is_active is False
    assert db.commit.called


# --- Test 3 ---
@pytest.mark.asyncio
async def test_record_acquisition_404_vehicle_not_found():
    db = _mock_db()
    data = AcquisitionCreate(
        acquisition_type=AcquisitionType.purchased,
        acquisition_date=_ACQ_DATE,
    )
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await record_acquisition(db, ACCOUNT_ID, VEHICLE_ID, data)
    assert exc.value.status_code == 404


# --- Test 4 ---
@pytest.mark.asyncio
async def test_get_acquisition_success():
    db = _mock_db()
    acq = _make_acquisition()
    with patch(f"{_SERVICE}._fetch_acquisition", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = acq
        result = await get_acquisition(db, ACCOUNT_ID, ACQ_ID)
    assert result.id == ACQ_ID
    assert result.acquisition_type == "purchased"


# --- Test 5 ---
@pytest.mark.asyncio
async def test_get_acquisition_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_acquisition", new_callable=AsyncMock) as mock_fa:
        mock_fa.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await get_acquisition(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 6 ---
@pytest.mark.asyncio
async def test_get_vehicle_acquisition_returns_active():
    db = _mock_db()
    acq = _make_acquisition(is_active=True)
    db.execute.return_value = _scalar_result(acq)
    result = await get_vehicle_acquisition(db, VEHICLE_ID, ACCOUNT_ID)
    assert result is not None
    assert result.id == ACQ_ID
    assert result.is_active is True


# --- Test 7 ---
@pytest.mark.asyncio
async def test_get_vehicle_acquisition_returns_none_when_absent():
    db = _mock_db()
    db.execute.return_value = _scalar_result(None)
    result = await get_vehicle_acquisition(db, VEHICLE_ID, ACCOUNT_ID)
    assert result is None


# --- Test 8 ---
@pytest.mark.asyncio
async def test_list_vehicle_acquisitions_returns_history():
    db = _mock_db()
    acqs = [
        _make_acquisition(is_active=True),
        _make_acquisition(acq_id=uuid.uuid4(), is_active=False),
    ]
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _make_vehicle()
        db.execute.return_value = _scalars_result(acqs)
        results = await list_vehicle_acquisitions(db, VEHICLE_ID, ACCOUNT_ID)
    assert len(results) == 2


# --- Test 9 ---
@pytest.mark.asyncio
async def test_list_vehicle_acquisitions_empty():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _make_vehicle()
        db.execute.return_value = _scalars_result([])
        results = await list_vehicle_acquisitions(db, VEHICLE_ID, ACCOUNT_ID)
    assert results == []


# --- Test 10 ---
@pytest.mark.asyncio
async def test_update_acquisition_success():
    db = _mock_db()
    acq = _make_acquisition()
    with patch(f"{_SERVICE}._fetch_acquisition", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = acq
        data = AcquisitionUpdate(vendor_name="New Dealer", acquisition_cost_usd=38_000.00)
        await update_acquisition(db, ACCOUNT_ID, ACQ_ID, data)
    assert acq.vendor_name == "New Dealer"
    assert float(acq.acquisition_cost_usd) == 38_000.00
    assert db.commit.called


# --- Test 11 ---
@pytest.mark.asyncio
async def test_update_acquisition_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_acquisition", new_callable=AsyncMock) as mock_fa:
        mock_fa.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await update_acquisition(db, ACCOUNT_ID, uuid.uuid4(), AcquisitionUpdate())
    assert exc.value.status_code == 404


# --- Test 12 ---
@pytest.mark.asyncio
async def test_dispose_vehicle_success():
    db = _mock_db()
    vehicle = _make_vehicle(is_active=True)
    acq = _make_acquisition(is_active=True)
    data = DisposalCreate(
        disposal_reason=DisposalReason.sold,
        disposal_date=_DISPOSAL_DATE,
        sale_price_usd=20_000.00,
        buyer_name="Used Car Lot",
    )

    def _refresh_disposal(obj):
        obj.created_at = _NOW

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        # No existing disposal, has active acquisition.
        db.execute.side_effect = [
            _scalar_result(None),   # existing disposal check
            _scalar_result(acq),    # active acquisition lookup
        ]
        db.refresh.side_effect = _refresh_disposal
        await dispose_vehicle(db, ACCOUNT_ID, VEHICLE_ID, data, disposed_by_id=ADMIN_ID)

    assert vehicle.is_active is False
    assert acq.is_active is False
    assert db.add.called
    assert db.commit.called


# --- Test 13 ---
@pytest.mark.asyncio
async def test_dispose_vehicle_404():
    db = _mock_db()
    data = DisposalCreate(
        disposal_reason=DisposalReason.scrapped,
        disposal_date=_DISPOSAL_DATE,
    )
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await dispose_vehicle(db, ACCOUNT_ID, VEHICLE_ID, data)
    assert exc.value.status_code == 404


# --- Test 14 ---
@pytest.mark.asyncio
async def test_dispose_vehicle_409_already_disposed():
    db = _mock_db()
    vehicle = _make_vehicle(is_active=False)
    existing_disposal = _make_disposal()
    data = DisposalCreate(
        disposal_reason=DisposalReason.scrapped,
        disposal_date=_DISPOSAL_DATE,
    )

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        db.execute.return_value = _scalar_result(existing_disposal)
        with pytest.raises(HTTPException) as exc:
            await dispose_vehicle(db, ACCOUNT_ID, VEHICLE_ID, data)
    assert exc.value.status_code == 409
    assert "already been disposed" in exc.value.detail.lower()


# --- Test 15 ---
@pytest.mark.asyncio
async def test_dispose_vehicle_no_prior_acquisition():
    db = _mock_db()
    vehicle = _make_vehicle(is_active=True)
    data = DisposalCreate(
        disposal_reason=DisposalReason.donated,
        disposal_date=_DISPOSAL_DATE,
    )

    def _refresh_disposal(obj):
        obj.created_at = _NOW

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        # No existing disposal, no active acquisition.
        db.execute.side_effect = [
            _scalar_result(None),  # existing disposal check
            _scalar_result(None),  # active acquisition lookup
        ]
        db.refresh.side_effect = _refresh_disposal
        await dispose_vehicle(db, ACCOUNT_ID, VEHICLE_ID, data)

    assert vehicle.is_active is False
    assert db.commit.called


# --- Test 16 ---
@pytest.mark.asyncio
async def test_get_disposal_success():
    db = _mock_db()
    disposal = _make_disposal()
    with patch(f"{_SERVICE}._fetch_disposal", new_callable=AsyncMock) as mock_fd:
        mock_fd.return_value = disposal
        result = await get_disposal(db, ACCOUNT_ID, DISPOSAL_ID)
    assert result.id == DISPOSAL_ID
    assert result.disposal_reason == "sold"


# --- Test 17 ---
@pytest.mark.asyncio
async def test_get_disposal_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_disposal", new_callable=AsyncMock) as mock_fd:
        mock_fd.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await get_disposal(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 18 ---
@pytest.mark.asyncio
async def test_get_vehicle_disposal_returns_record():
    db = _mock_db()
    disposal = _make_disposal()
    db.execute.return_value = _scalar_result(disposal)
    result = await get_vehicle_disposal(db, VEHICLE_ID, ACCOUNT_ID)
    assert result is not None
    assert result.id == DISPOSAL_ID


# --- Test 19 ---
@pytest.mark.asyncio
async def test_get_vehicle_disposal_returns_none():
    db = _mock_db()
    db.execute.return_value = _scalar_result(None)
    result = await get_vehicle_disposal(db, VEHICLE_ID, ACCOUNT_ID)
    assert result is None


# --- Test 20 ---
@pytest.mark.asyncio
async def test_list_account_disposals_returns_all():
    db = _mock_db()
    disposals = [
        _make_disposal(),
        _make_disposal(disposal_id=uuid.uuid4(), disposal_reason=DisposalReason.scrapped),
    ]
    db.execute.return_value = _scalars_result(disposals)
    results = await list_account_disposals(db, ACCOUNT_ID)
    assert len(results) == 2


# --- Test 21 ---
@pytest.mark.asyncio
async def test_list_account_disposals_filter_by_reason():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_disposal(disposal_reason=DisposalReason.sold)])
    results = await list_account_disposals(db, ACCOUNT_ID, disposal_reason=DisposalReason.sold)
    assert len(results) == 1
    assert results[0].disposal_reason == "sold"


# --- Test 22 ---
@pytest.mark.asyncio
async def test_list_account_disposals_filter_from_date():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_disposal()])
    results = await list_account_disposals(
        db, ACCOUNT_ID, from_date=date(2026, 1, 1)
    )
    assert len(results) == 1


# --- Test 23 ---
@pytest.mark.asyncio
async def test_list_account_disposals_filter_to_date():
    db = _mock_db()
    db.execute.return_value = _scalars_result([])
    results = await list_account_disposals(
        db, ACCOUNT_ID, to_date=date(2025, 12, 31)
    )
    assert results == []


# --- Test 24 ---
@pytest.mark.asyncio
async def test_get_fleet_ownership_summary_vehicle_counts():
    db = _mock_db()
    v_active = _make_vehicle(is_active=True)
    v_retired = _make_vehicle(is_active=False)
    v_retired.id = uuid.uuid4()
    disposal = _make_disposal(fleet_vehicle_id=v_retired.id)

    db.execute.side_effect = [
        _scalars_result([v_active, v_retired]),  # all vehicles
        _scalars_result([disposal]),              # disposals
        _scalars_result([]),                      # active acquisitions
    ]
    summary = await get_fleet_ownership_summary(db, ACCOUNT_ID)
    assert summary.total_vehicles == 2
    assert summary.active_vehicles == 1
    assert summary.retired_vehicles == 1


# --- Test 25 ---
@pytest.mark.asyncio
async def test_get_fleet_ownership_summary_by_acquisition_type():
    db = _mock_db()
    acq_purchased = _make_acquisition(acquisition_type=AcquisitionType.purchased)
    acq_leased = _make_acquisition(
        acq_id=uuid.uuid4(),
        acquisition_type=AcquisitionType.leased,
        monthly_lease_payment_usd=500.00,
        lease_end_date=date.today() + timedelta(days=200),
    )

    db.execute.side_effect = [
        _scalars_result([_make_vehicle(), _make_vehicle()]),  # all vehicles
        _scalars_result([]),                                   # disposals
        _scalars_result([acq_purchased, acq_leased]),         # active acquisitions
    ]
    summary = await get_fleet_ownership_summary(db, ACCOUNT_ID)
    assert summary.by_acquisition_type["purchased"] == 1
    assert summary.by_acquisition_type["leased"] == 1
    assert summary.by_acquisition_type["financed"] == 0


# --- Test 26 ---
@pytest.mark.asyncio
async def test_get_fleet_ownership_summary_lease_payments():
    db = _mock_db()
    acq1 = _make_acquisition(
        acquisition_type=AcquisitionType.leased,
        monthly_lease_payment_usd=500.00,
        lease_end_date=date.today() + timedelta(days=200),
    )
    acq2 = _make_acquisition(
        acq_id=uuid.uuid4(),
        acquisition_type=AcquisitionType.leased,
        monthly_lease_payment_usd=750.00,
        lease_end_date=date.today() + timedelta(days=300),
    )

    db.execute.side_effect = [
        _scalars_result([_make_vehicle(), _make_vehicle()]),
        _scalars_result([]),
        _scalars_result([acq1, acq2]),
    ]
    summary = await get_fleet_ownership_summary(db, ACCOUNT_ID)
    assert summary.total_monthly_lease_payments_usd == pytest.approx(1250.00)
    assert summary.total_monthly_loan_payments_usd == 0.0


# --- Test 27 ---
@pytest.mark.asyncio
async def test_get_fleet_ownership_summary_loan_payments():
    db = _mock_db()
    acq = _make_acquisition(
        acquisition_type=AcquisitionType.financed,
        financed_amount_usd=25_000.00,
        loan_term_months=60,
        monthly_loan_payment_usd=450.00,
    )

    db.execute.side_effect = [
        _scalars_result([_make_vehicle()]),
        _scalars_result([]),
        _scalars_result([acq]),
    ]
    summary = await get_fleet_ownership_summary(db, ACCOUNT_ID)
    assert summary.total_monthly_loan_payments_usd == pytest.approx(450.00)
    assert summary.total_monthly_lease_payments_usd == 0.0


# --- Test 28 ---
@pytest.mark.asyncio
async def test_get_fleet_ownership_summary_leases_expiring_within_90_days():
    db = _mock_db()
    today = date.today()
    acq_expiring = _make_acquisition(
        acquisition_type=AcquisitionType.leased,
        monthly_lease_payment_usd=600.00,
        lease_end_date=today + timedelta(days=45),  # within 90 days
    )

    db.execute.side_effect = [
        _scalars_result([_make_vehicle()]),
        _scalars_result([]),
        _scalars_result([acq_expiring]),
    ]
    summary = await get_fleet_ownership_summary(db, ACCOUNT_ID)
    assert summary.leases_expiring_within_90_days == 1


# --- Test 29 ---
@pytest.mark.asyncio
async def test_get_fleet_ownership_summary_no_expiring_leases():
    db = _mock_db()
    today = date.today()
    acq_far = _make_acquisition(
        acquisition_type=AcquisitionType.leased,
        monthly_lease_payment_usd=600.00,
        lease_end_date=today + timedelta(days=200),  # beyond 90 days
    )

    db.execute.side_effect = [
        _scalars_result([_make_vehicle()]),
        _scalars_result([]),
        _scalars_result([acq_far]),
    ]
    summary = await get_fleet_ownership_summary(db, ACCOUNT_ID)
    assert summary.leases_expiring_within_90_days == 0


# --- Test 30 ---
@pytest.mark.asyncio
async def test_list_all_platform_returns_all():
    db = _mock_db()
    rows = [
        _make_acquisition(),
        _make_acquisition(acq_id=uuid.uuid4(), account_id=99),
    ]
    db.execute.return_value = _scalars_result(rows)
    results = await list_all_platform(db)
    assert len(results) == 2


# --- Test 31 ---
@pytest.mark.asyncio
async def test_list_all_platform_filter_by_account():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_acquisition()])
    results = await list_all_platform(db, account_id=ACCOUNT_ID)
    assert len(results) == 1
    assert results[0].account_id == ACCOUNT_ID


# ===========================================================================
# Schema validation tests (32–40)
# ===========================================================================


# --- Test 32 ---
def test_schema_acquisition_create_valid():
    schema = AcquisitionCreate(
        acquisition_type=AcquisitionType.purchased,
        acquisition_date=_ACQ_DATE,
        acquisition_cost_usd=35_000.00,
        vendor_name="Acme Motors",
    )
    assert schema.acquisition_type == AcquisitionType.purchased
    assert schema.acquisition_cost_usd == 35_000.00
    assert schema.lease_start_date is None


# --- Test 33 ---
def test_schema_acquisition_create_requires_type():
    with pytest.raises(ValidationError):
        AcquisitionCreate(acquisition_date=_ACQ_DATE)


# --- Test 34 ---
def test_schema_acquisition_create_requires_date():
    with pytest.raises(ValidationError):
        AcquisitionCreate(acquisition_type=AcquisitionType.purchased)


# --- Test 35 ---
def test_schema_acquisition_update_all_optional():
    schema = AcquisitionUpdate()
    assert schema.acquisition_type is None
    assert schema.acquisition_date is None
    assert schema.vendor_name is None
    assert schema.acquisition_cost_usd is None
    assert schema.monthly_lease_payment_usd is None


# --- Test 36 ---
def test_schema_acquisition_response_from_attributes():
    acq = _make_acquisition()
    resp = _make_acq_response(acq)
    assert resp.id == ACQ_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.acquisition_type == "purchased"
    assert resp.is_active is True
    assert resp.vendor_name == "Acme Motors"


# --- Test 37 ---
def test_schema_disposal_create_valid():
    schema = DisposalCreate(
        disposal_reason=DisposalReason.sold,
        disposal_date=_DISPOSAL_DATE,
        sale_price_usd=18_000.00,
        buyer_name="Car Buyer",
    )
    assert schema.disposal_reason == DisposalReason.sold
    assert schema.sale_price_usd == 18_000.00


# --- Test 38 ---
def test_schema_disposal_create_requires_reason():
    with pytest.raises(ValidationError):
        DisposalCreate(disposal_date=_DISPOSAL_DATE)


# --- Test 39 ---
def test_schema_disposal_response_from_attributes():
    d = _make_disposal()
    resp = _make_disposal_response(d)
    assert resp.id == DISPOSAL_ID
    assert resp.disposal_reason == "sold"
    assert resp.sale_price_usd == 20_000.00
    assert resp.buyer_name == "Used Car Lot"


# --- Test 40 ---
def test_schema_fleet_ownership_summary_valid():
    summary = FleetOwnershipSummary(
        total_vehicles=10,
        active_vehicles=8,
        retired_vehicles=2,
        by_acquisition_type={"purchased": 5, "leased": 2, "financed": 1, "donated": 0, "other": 0},
        total_monthly_lease_payments_usd=1200.00,
        total_monthly_loan_payments_usd=450.00,
        leases_expiring_within_90_days=1,
    )
    assert summary.total_vehicles == 10
    assert summary.retired_vehicles == 2
    assert summary.by_acquisition_type["purchased"] == 5
    assert summary.total_monthly_lease_payments_usd == 1200.00


# ===========================================================================
# API layer tests (41–50)
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


def _patch_require_account_admin():
    return patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)


# --- Test 41 ---
def test_api_get_vehicle_acquisition_200():
    resp = _make_acq_response()
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_vehicle_acquisition",
            new_callable=AsyncMock,
            return_value=resp,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/acquisition"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert data["acquisition_type"] == "purchased"


# --- Test 42 ---
def test_api_get_acquisition_history_200():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.list_vehicle_acquisitions",
            new_callable=AsyncMock,
            return_value=[_make_acq_response()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/acquisition/history"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert len(r.json()) == 1


# --- Test 43 ---
def test_api_get_vehicle_disposal_200():
    resp = _make_disposal_response()
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_vehicle_disposal",
            new_callable=AsyncMock,
            return_value=resp,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/disposal"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert data["disposal_reason"] == "sold"


# --- Test 44 ---
def test_api_get_fleet_ownership_summary_200():
    summary = FleetOwnershipSummary(
        total_vehicles=5,
        active_vehicles=4,
        retired_vehicles=1,
        by_acquisition_type={"purchased": 2, "leased": 1, "financed": 1, "donated": 0, "other": 0},
        total_monthly_lease_payments_usd=600.00,
        total_monthly_loan_payments_usd=450.00,
        leases_expiring_within_90_days=0,
    )
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_fleet_ownership_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/fleet-acquisition/summary")
        app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert data["total_vehicles"] == 5
    assert data["active_vehicles"] == 4


# --- Test 45 ---
def test_api_record_acquisition_201():
    resp = _make_acq_response()
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.record_acquisition",
            new_callable=AsyncMock,
            return_value=resp,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/acquisition",
            json={
                "acquisition_type": "purchased",
                "acquisition_date": str(_ACQ_DATE),
                "acquisition_cost_usd": 35000.00,
                "vendor_name": "Acme Motors",
            },
        )
        app.dependency_overrides.clear()
    assert r.status_code == 201
    assert r.json()["acquisition_type"] == "purchased"


# --- Test 46 ---
def test_api_update_acquisition_200():
    resp = _make_acq_response()
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.update_acquisition",
            new_callable=AsyncMock,
            return_value=resp,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.put(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-acquisition/{ACQ_ID}",
            json={"vendor_name": "Updated Dealer"},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 47 ---
def test_api_dispose_vehicle_201():
    resp = _make_disposal_response()
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.dispose_vehicle",
            new_callable=AsyncMock,
            return_value=resp,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/dispose",
            json={
                "disposal_reason": "sold",
                "disposal_date": str(_DISPOSAL_DATE),
                "sale_price_usd": 20000.00,
                "buyer_name": "Used Car Lot",
            },
        )
        app.dependency_overrides.clear()
    assert r.status_code == 201
    assert r.json()["disposal_reason"] == "sold"


# --- Test 48 ---
def test_api_list_account_disposals_200():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.list_account_disposals",
            new_callable=AsyncMock,
            return_value=[_make_disposal_response()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/fleet-acquisition/disposals")
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert len(r.json()) == 1


# --- Test 49 ---
def test_api_get_disposal_by_id_200():
    resp = _make_disposal_response()
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.get_disposal",
            new_callable=AsyncMock,
            return_value=resp,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-acquisition/disposals/{DISPOSAL_ID}"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["id"] == str(DISPOSAL_ID)


# --- Test 50 ---
def test_api_platform_list_all_200():
    with patch(
        f"{_ROUTER}.list_all_platform",
        new_callable=AsyncMock,
        return_value=[_make_acq_response()],
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get("/api/v1/platform/corporate/fleet-acquisition/")
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert len(r.json()) == 1
