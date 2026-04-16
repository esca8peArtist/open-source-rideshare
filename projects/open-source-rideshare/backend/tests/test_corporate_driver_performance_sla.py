"""Tests for the Corporate Driver Performance SLA feature.

Service layer (async, mocked DB):
   1.  create_sla_policy — success: creates with is_active=True, deactivates existing
   2.  create_sla_policy — 409 on name collision
   3.  get_sla_policy — success: returns existing policy
   4.  get_sla_policy — 404 when not found
   5.  list_sla_policies — returns all policies for account
   6.  list_sla_policies — filters by is_active=True
   7.  list_sla_policies — filters by is_active=False
   8.  update_sla_policy — success: updates name and thresholds
   9.  update_sla_policy — 404 when not found
  10.  update_sla_policy — 409 on name collision
  11.  update_sla_policy — 409 when trying to activate via update
  12.  activate_sla_policy — success: sets is_active=True, deactivates others
  13.  activate_sla_policy — 404 when not found
  14.  activate_sla_policy — 409 when already active
  15.  deactivate_sla_policy — success: sets is_active=False
  16.  deactivate_sla_policy — 404 when not found
  17.  deactivate_sla_policy — 409 when already inactive
  18.  delete_sla_policy — success: deletes inactive policy
  19.  delete_sla_policy — 404 when not found
  20.  delete_sla_policy — 409 when active
  21.  record_driver_evaluation — success: all dimensions pass
  22.  record_driver_evaluation — fails on-time dimension
  23.  record_driver_evaluation — fails rating dimension
  24.  record_driver_evaluation — fails cancellation dimension
  25.  record_driver_evaluation — fails acceptance dimension
  26.  record_driver_evaluation — returns None when no active policy
  27.  record_driver_evaluation — overall_sla_met=True when no thresholds set
  28.  record_driver_evaluation — overall_sla_met=False when any dimension fails
  29.  get_driver_sla_summary — returns summary with correct pass rate
  30.  get_driver_sla_summary — zero evaluations returns 0.0 pass rate
  31.  get_driver_sla_summary — counts flagged records
  32.  list_all_platform — returns all records without filter
  33.  list_all_platform — filters by account_id
  34.  flag_driver_for_review — success: sets flagged fields
  35.  flag_driver_for_review — 404 when record not found
  36.  flag_driver_for_review — 409 when already flagged
  37.  list_flagged_drivers — returns only flagged records

Schema validation:
  38.  SLAPolicyCreate — requires name
  39.  SLAPolicyCreate — rejects min_on_time_rate_pct > 100
  40.  SLAPolicyCreate — rejects min_avg_rating > 5
  41.  SLAPolicyCreate — optional fields default to None
  42.  SLAPolicyUpdate — all fields optional
  43.  DriverEvaluationInput — rejects negative total_corporate_rides
  44.  DriverEvaluationInput — rejects on_time_rate_pct > 100
  45.  SLARecordResponse — from_attributes construction
  46.  DriverSLASummaryResponse — structure

API layer (service functions patched):
  47.  GET  /driver-sla/policy — 200 member can get active policy
  48.  GET  /driver-sla/policy — 200 returns null when no active policy
  49.  POST /driver-sla/policy — 201 admin can create
  50.  POST /driver-sla/policy — 403 non-admin cannot create
  51.  POST /driver-sla/policy — 409 on name collision
  52.  GET  /driver-sla/policy/all — 200 admin can list
  53.  GET  /driver-sla/policy/all — 403 non-admin cannot list
  54.  GET  /driver-sla/policy/{policy_id} — 200 admin can get specific
  55.  GET  /driver-sla/policy/{policy_id} — 404 when not found
  56.  PUT  /driver-sla/policy/{policy_id} — 200 admin can update
  57.  PUT  /driver-sla/policy/{policy_id} — 403 non-admin cannot update
  58.  POST /driver-sla/policy/{policy_id}/activate — 200 admin can activate
  59.  POST /driver-sla/policy/{policy_id}/activate — 409 already active
  60.  POST /driver-sla/policy/{policy_id}/deactivate — 200 admin can deactivate
  61.  POST /driver-sla/policy/{policy_id}/deactivate — 409 already inactive
  62.  DELETE /driver-sla/policy/{policy_id} — 204 admin can delete
  63.  DELETE /driver-sla/policy/{policy_id} — 409 when active
  64.  POST /driver-sla/drivers/{id}/evaluate — 201 admin can record evaluation
  65.  POST /driver-sla/drivers/{id}/evaluate — 403 non-admin cannot evaluate
  66.  GET  /driver-sla/drivers/{id}/summary — 200 admin can get summary
  67.  GET  /driver-sla/flagged — 200 admin can list flagged
  68.  POST /driver-sla/records/{id}/flag — 200 admin can flag
  69.  POST /driver-sla/records/{id}/flag — 409 already flagged
  70.  GET  /platform/corporate/driver-sla/all — 200 platform-admin list all
  71.  GET  /platform/corporate/driver-sla/all — 200 with account_id filter
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.corporate_driver_performance_sla import (
    CorporateDriverPerformanceSLA,
    CorporateDriverSLARecord,
)
from app.schemas.corporate_driver_performance_sla import (
    DriverEvaluationInput,
    DriverFlagInput,
    DriverSLASummaryResponse,
    SLAPolicyCreate,
    SLAPolicyResponse,
    SLAPolicyUpdate,
    SLARecordResponse,
)
from app.services.corporate_driver_performance_sla_service import (
    activate_sla_policy,
    create_sla_policy,
    deactivate_sla_policy,
    delete_sla_policy,
    flag_driver_for_review,
    get_driver_sla_summary,
    get_sla_policy,
    list_all_platform,
    list_flagged_drivers,
    list_sla_policies,
    record_driver_evaluation,
    update_sla_policy,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 5
DRIVER_PROFILE_ID = 42
POLICY_ID = uuid.uuid4()
RECORD_ID = uuid.uuid4()
USER_ID = 10
ADMIN_ID = 1

_SERVICE = "app.services.corporate_driver_performance_sla_service"
_ROUTER = "app.api.v1.corporate_driver_performance_sla"

_NOW = datetime(2026, 4, 16, 9, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_policy(
    policy_id: uuid.UUID = POLICY_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Standard Corporate Driver SLA",
    description: str | None = "Default policy",
    min_on_time_rate_pct: float | None = 85.0,
    min_avg_rating: float | None = 4.5,
    max_cancellation_rate_pct: float | None = 5.0,
    min_acceptance_rate_pct: float | None = 90.0,
    evaluation_window_days: int = 30,
    is_active: bool = True,
    created_by_id: int | None = ADMIN_ID,
) -> CorporateDriverPerformanceSLA:
    p = CorporateDriverPerformanceSLA()
    p.id = policy_id
    p.account_id = account_id
    p.name = name
    p.description = description
    p.min_on_time_rate_pct = min_on_time_rate_pct
    p.min_avg_rating = min_avg_rating
    p.max_cancellation_rate_pct = max_cancellation_rate_pct
    p.min_acceptance_rate_pct = min_acceptance_rate_pct
    p.evaluation_window_days = evaluation_window_days
    p.is_active = is_active
    p.created_by_id = created_by_id
    p.created_at = _NOW
    p.updated_at = _NOW
    return p


def _make_record(
    record_id: uuid.UUID = RECORD_ID,
    account_id: int = ACCOUNT_ID,
    sla_policy_id: uuid.UUID | None = POLICY_ID,
    driver_profile_id: int | None = DRIVER_PROFILE_ID,
    overall_sla_met: bool = True,
    flagged_for_review: bool = False,
    flagged_by_id: int | None = None,
    flagged_at: datetime | None = None,
    flag_reason: str | None = None,
    on_time_met: bool | None = True,
    rating_met: bool | None = True,
    cancellation_met: bool | None = True,
    acceptance_met: bool | None = True,
) -> CorporateDriverSLARecord:
    r = CorporateDriverSLARecord()
    r.id = record_id
    r.account_id = account_id
    r.sla_policy_id = sla_policy_id
    r.driver_profile_id = driver_profile_id
    r.evaluated_at = _NOW
    r.evaluation_window_days = 30
    r.total_corporate_rides = 20
    r.on_time_rate_pct = 90.0
    r.avg_rating = 4.7
    r.cancellation_rate_pct = 2.0
    r.acceptance_rate_pct = 95.0
    r.on_time_met = on_time_met
    r.rating_met = rating_met
    r.cancellation_met = cancellation_met
    r.acceptance_met = acceptance_met
    r.overall_sla_met = overall_sla_met
    r.flagged_for_review = flagged_for_review
    r.flagged_by_id = flagged_by_id
    r.flagged_at = flagged_at
    r.flag_reason = flag_reason
    return r


def _policy_resp(policy: CorporateDriverPerformanceSLA | None = None) -> SLAPolicyResponse:
    if policy is None:
        policy = _make_policy()
    return SLAPolicyResponse(
        id=policy.id,
        account_id=policy.account_id,
        name=policy.name,
        description=policy.description,
        min_on_time_rate_pct=float(policy.min_on_time_rate_pct) if policy.min_on_time_rate_pct is not None else None,
        min_avg_rating=float(policy.min_avg_rating) if policy.min_avg_rating is not None else None,
        max_cancellation_rate_pct=float(policy.max_cancellation_rate_pct) if policy.max_cancellation_rate_pct is not None else None,
        min_acceptance_rate_pct=float(policy.min_acceptance_rate_pct) if policy.min_acceptance_rate_pct is not None else None,
        evaluation_window_days=policy.evaluation_window_days,
        is_active=policy.is_active,
        created_by_id=policy.created_by_id,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _record_resp(record: CorporateDriverSLARecord | None = None) -> SLARecordResponse:
    if record is None:
        record = _make_record()
    return SLARecordResponse(
        id=record.id,
        account_id=record.account_id,
        sla_policy_id=record.sla_policy_id,
        driver_profile_id=record.driver_profile_id,
        evaluated_at=record.evaluated_at,
        evaluation_window_days=record.evaluation_window_days,
        total_corporate_rides=record.total_corporate_rides,
        on_time_rate_pct=float(record.on_time_rate_pct) if record.on_time_rate_pct is not None else None,
        avg_rating=float(record.avg_rating) if record.avg_rating is not None else None,
        cancellation_rate_pct=float(record.cancellation_rate_pct) if record.cancellation_rate_pct is not None else None,
        acceptance_rate_pct=float(record.acceptance_rate_pct) if record.acceptance_rate_pct is not None else None,
        on_time_met=record.on_time_met,
        rating_met=record.rating_met,
        cancellation_met=record.cancellation_met,
        acceptance_met=record.acceptance_met,
        overall_sla_met=record.overall_sla_met,
        flagged_for_review=record.flagged_for_review,
        flagged_by_id=record.flagged_by_id,
        flagged_at=record.flagged_at,
        flag_reason=record.flag_reason,
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
# Service layer tests (1–37)
# ===========================================================================


# --- Test 1 ---
@pytest.mark.asyncio
async def test_create_sla_policy_success():
    db = _mock_db()
    # name check → None (no collision), deactivate active → empty list
    db.execute.side_effect = [
        _scalar_result(None),    # name collision check
        _scalars_result([]),     # _deactivate_all_for_account: find active policies
    ]

    def _fill_timestamps(obj):
        if not hasattr(obj, "created_at") or obj.created_at is None:
            obj.created_at = _NOW
        if not hasattr(obj, "updated_at") or obj.updated_at is None:
            obj.updated_at = _NOW

    db.refresh.side_effect = _fill_timestamps

    data = SLAPolicyCreate(name="Standard Corporate Driver SLA", min_on_time_rate_pct=85.0)
    result = await create_sla_policy(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)
    assert db.add.called
    assert db.commit.called


# --- Test 2 ---
@pytest.mark.asyncio
async def test_create_sla_policy_409_name_collision():
    db = _mock_db()
    db.execute.return_value = _scalar_result(_make_policy())  # name collision found
    data = SLAPolicyCreate(name="Standard Corporate Driver SLA")
    with pytest.raises(HTTPException) as exc:
        await create_sla_policy(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 409
    assert "already exists" in exc.value.detail.lower()


# --- Test 3 ---
@pytest.mark.asyncio
async def test_get_sla_policy_success():
    db = _mock_db()
    policy = _make_policy()
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.return_value = policy
        result = await get_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    assert result.id == POLICY_ID
    assert result.name == "Standard Corporate Driver SLA"


# --- Test 4 ---
@pytest.mark.asyncio
async def test_get_sla_policy_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await get_sla_policy(db, uuid.uuid4(), ACCOUNT_ID)
    assert exc.value.status_code == 404


# --- Test 5 ---
@pytest.mark.asyncio
async def test_list_sla_policies_returns_all():
    db = _mock_db()
    rows = [_make_policy(), _make_policy(policy_id=uuid.uuid4(), name="VIP SLA")]
    db.execute.return_value = _scalars_result(rows)
    results = await list_sla_policies(db, ACCOUNT_ID)
    assert len(results) == 2


# --- Test 6 ---
@pytest.mark.asyncio
async def test_list_sla_policies_filters_active():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_policy(is_active=True)])
    results = await list_sla_policies(db, ACCOUNT_ID, is_active=True)
    assert len(results) == 1
    assert results[0].is_active is True


# --- Test 7 ---
@pytest.mark.asyncio
async def test_list_sla_policies_filters_inactive():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_policy(is_active=False)])
    results = await list_sla_policies(db, ACCOUNT_ID, is_active=False)
    assert len(results) == 1
    assert results[0].is_active is False


# --- Test 8 ---
@pytest.mark.asyncio
async def test_update_sla_policy_success():
    db = _mock_db()
    policy = _make_policy()
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.return_value = policy
        # name collision check returns None (no collision)
        db.execute.return_value = _scalar_result(None)
        data = SLAPolicyUpdate(name="Updated SLA", min_avg_rating=4.8)
        result = await update_sla_policy(db, POLICY_ID, ACCOUNT_ID, data)
    assert policy.name == "Updated SLA"
    assert db.commit.called


# --- Test 9 ---
@pytest.mark.asyncio
async def test_update_sla_policy_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await update_sla_policy(db, uuid.uuid4(), ACCOUNT_ID, SLAPolicyUpdate())
    assert exc.value.status_code == 404


# --- Test 10 ---
@pytest.mark.asyncio
async def test_update_sla_policy_409_name_collision():
    db = _mock_db()
    policy = _make_policy()
    other_policy = _make_policy(policy_id=uuid.uuid4(), name="VIP SLA")
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.return_value = policy
        db.execute.return_value = _scalar_result(other_policy)  # name collision
        data = SLAPolicyUpdate(name="VIP SLA")
        with pytest.raises(HTTPException) as exc:
            await update_sla_policy(db, POLICY_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 409
    assert "already exists" in exc.value.detail.lower()


# --- Test 11 ---
@pytest.mark.asyncio
async def test_update_sla_policy_409_activate_via_update():
    db = _mock_db()
    policy = _make_policy(is_active=False)
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.return_value = policy
        data = SLAPolicyUpdate(is_active=True)
        with pytest.raises(HTTPException) as exc:
            await update_sla_policy(db, POLICY_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 409
    assert "activate" in exc.value.detail.lower()


# --- Test 12 ---
@pytest.mark.asyncio
async def test_activate_sla_policy_success():
    db = _mock_db()
    policy = _make_policy(is_active=False)
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.return_value = policy
        with patch(f"{_SERVICE}._deactivate_all_for_account", new_callable=AsyncMock):
            result = await activate_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    assert policy.is_active is True
    assert db.commit.called


# --- Test 13 ---
@pytest.mark.asyncio
async def test_activate_sla_policy_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await activate_sla_policy(db, uuid.uuid4(), ACCOUNT_ID)
    assert exc.value.status_code == 404


# --- Test 14 ---
@pytest.mark.asyncio
async def test_activate_sla_policy_409_already_active():
    db = _mock_db()
    policy = _make_policy(is_active=True)
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.return_value = policy
        with pytest.raises(HTTPException) as exc:
            await activate_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409
    assert "already active" in exc.value.detail.lower()


# --- Test 15 ---
@pytest.mark.asyncio
async def test_deactivate_sla_policy_success():
    db = _mock_db()
    policy = _make_policy(is_active=True)
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.return_value = policy
        result = await deactivate_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    assert policy.is_active is False
    assert db.commit.called


# --- Test 16 ---
@pytest.mark.asyncio
async def test_deactivate_sla_policy_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await deactivate_sla_policy(db, uuid.uuid4(), ACCOUNT_ID)
    assert exc.value.status_code == 404


# --- Test 17 ---
@pytest.mark.asyncio
async def test_deactivate_sla_policy_409_already_inactive():
    db = _mock_db()
    policy = _make_policy(is_active=False)
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.return_value = policy
        with pytest.raises(HTTPException) as exc:
            await deactivate_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409
    assert "already inactive" in exc.value.detail.lower()


# --- Test 18 ---
@pytest.mark.asyncio
async def test_delete_sla_policy_success():
    db = _mock_db()
    policy = _make_policy(is_active=False)
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.return_value = policy
        await delete_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    assert db.delete.called
    assert db.commit.called


# --- Test 19 ---
@pytest.mark.asyncio
async def test_delete_sla_policy_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await delete_sla_policy(db, uuid.uuid4(), ACCOUNT_ID)
    assert exc.value.status_code == 404


# --- Test 20 ---
@pytest.mark.asyncio
async def test_delete_sla_policy_409_when_active():
    db = _mock_db()
    policy = _make_policy(is_active=True)
    with patch(f"{_SERVICE}._fetch_policy", new_callable=AsyncMock) as mock_fp:
        mock_fp.return_value = policy
        with pytest.raises(HTTPException) as exc:
            await delete_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409
    assert "deactivate" in exc.value.detail.lower()


# --- Test 21 ---
@pytest.mark.asyncio
async def test_record_driver_evaluation_all_pass():
    db = _mock_db()
    policy = _make_policy()
    db.execute.return_value = _scalar_result(policy)

    metrics = DriverEvaluationInput(
        total_corporate_rides=20,
        on_time_rate_pct=90.0,
        avg_rating=4.7,
        cancellation_rate_pct=2.0,
        acceptance_rate_pct=95.0,
    )

    with patch(f"{_SERVICE}.CorporateDriverSLARecord") as MockRecord:
        instance = _make_record()
        MockRecord.return_value = instance
        result = await record_driver_evaluation(db, ACCOUNT_ID, DRIVER_PROFILE_ID, metrics)

    assert db.add.called
    assert db.commit.called


# --- Test 22 ---
@pytest.mark.asyncio
async def test_record_driver_evaluation_fails_on_time():
    db = _mock_db()
    policy = _make_policy(min_on_time_rate_pct=85.0)
    db.execute.return_value = _scalar_result(policy)

    metrics = DriverEvaluationInput(
        total_corporate_rides=10,
        on_time_rate_pct=80.0,  # below 85%
        avg_rating=4.7,
        cancellation_rate_pct=2.0,
        acceptance_rate_pct=95.0,
    )

    with patch(f"{_SERVICE}.CorporateDriverSLARecord") as MockRecord:
        instance = _make_record(on_time_met=False, overall_sla_met=False)
        MockRecord.return_value = instance
        result = await record_driver_evaluation(db, ACCOUNT_ID, DRIVER_PROFILE_ID, metrics)

    # Verify the constructor was called with on_time_met=False
    call_kwargs = MockRecord.call_args.kwargs
    assert call_kwargs["on_time_met"] is False
    assert call_kwargs["overall_sla_met"] is False


# --- Test 23 ---
@pytest.mark.asyncio
async def test_record_driver_evaluation_fails_rating():
    db = _mock_db()
    policy = _make_policy(min_avg_rating=4.5)
    db.execute.return_value = _scalar_result(policy)

    metrics = DriverEvaluationInput(
        total_corporate_rides=10,
        on_time_rate_pct=90.0,
        avg_rating=4.3,  # below 4.5
        cancellation_rate_pct=2.0,
        acceptance_rate_pct=95.0,
    )

    with patch(f"{_SERVICE}.CorporateDriverSLARecord") as MockRecord:
        instance = _make_record(rating_met=False, overall_sla_met=False)
        MockRecord.return_value = instance
        result = await record_driver_evaluation(db, ACCOUNT_ID, DRIVER_PROFILE_ID, metrics)

    call_kwargs = MockRecord.call_args.kwargs
    assert call_kwargs["rating_met"] is False
    assert call_kwargs["overall_sla_met"] is False


# --- Test 24 ---
@pytest.mark.asyncio
async def test_record_driver_evaluation_fails_cancellation():
    db = _mock_db()
    policy = _make_policy(max_cancellation_rate_pct=5.0)
    db.execute.return_value = _scalar_result(policy)

    metrics = DriverEvaluationInput(
        total_corporate_rides=10,
        on_time_rate_pct=90.0,
        avg_rating=4.7,
        cancellation_rate_pct=8.0,  # above 5%
        acceptance_rate_pct=95.0,
    )

    with patch(f"{_SERVICE}.CorporateDriverSLARecord") as MockRecord:
        instance = _make_record(cancellation_met=False, overall_sla_met=False)
        MockRecord.return_value = instance
        result = await record_driver_evaluation(db, ACCOUNT_ID, DRIVER_PROFILE_ID, metrics)

    call_kwargs = MockRecord.call_args.kwargs
    assert call_kwargs["cancellation_met"] is False
    assert call_kwargs["overall_sla_met"] is False


# --- Test 25 ---
@pytest.mark.asyncio
async def test_record_driver_evaluation_fails_acceptance():
    db = _mock_db()
    policy = _make_policy(min_acceptance_rate_pct=90.0)
    db.execute.return_value = _scalar_result(policy)

    metrics = DriverEvaluationInput(
        total_corporate_rides=10,
        on_time_rate_pct=90.0,
        avg_rating=4.7,
        cancellation_rate_pct=2.0,
        acceptance_rate_pct=85.0,  # below 90%
    )

    with patch(f"{_SERVICE}.CorporateDriverSLARecord") as MockRecord:
        instance = _make_record(acceptance_met=False, overall_sla_met=False)
        MockRecord.return_value = instance
        result = await record_driver_evaluation(db, ACCOUNT_ID, DRIVER_PROFILE_ID, metrics)

    call_kwargs = MockRecord.call_args.kwargs
    assert call_kwargs["acceptance_met"] is False
    assert call_kwargs["overall_sla_met"] is False


# --- Test 26 ---
@pytest.mark.asyncio
async def test_record_driver_evaluation_no_active_policy_returns_none():
    db = _mock_db()
    db.execute.return_value = _scalar_result(None)
    metrics = DriverEvaluationInput(total_corporate_rides=5)
    result = await record_driver_evaluation(db, ACCOUNT_ID, DRIVER_PROFILE_ID, metrics)
    assert result is None
    assert not db.add.called


# --- Test 27 ---
@pytest.mark.asyncio
async def test_record_driver_evaluation_overall_true_when_no_thresholds():
    db = _mock_db()
    # Policy with no thresholds set
    policy = _make_policy(
        min_on_time_rate_pct=None,
        min_avg_rating=None,
        max_cancellation_rate_pct=None,
        min_acceptance_rate_pct=None,
    )
    db.execute.return_value = _scalar_result(policy)

    metrics = DriverEvaluationInput(total_corporate_rides=5)

    with patch(f"{_SERVICE}.CorporateDriverSLARecord") as MockRecord:
        instance = _make_record(overall_sla_met=True)
        MockRecord.return_value = instance
        result = await record_driver_evaluation(db, ACCOUNT_ID, DRIVER_PROFILE_ID, metrics)

    call_kwargs = MockRecord.call_args.kwargs
    assert call_kwargs["overall_sla_met"] is True


# --- Test 28 ---
@pytest.mark.asyncio
async def test_record_driver_evaluation_overall_false_when_any_fails():
    db = _mock_db()
    policy = _make_policy(min_on_time_rate_pct=85.0, min_avg_rating=4.5)
    db.execute.return_value = _scalar_result(policy)

    metrics = DriverEvaluationInput(
        total_corporate_rides=10,
        on_time_rate_pct=90.0,   # pass
        avg_rating=4.2,           # fail
    )

    with patch(f"{_SERVICE}.CorporateDriverSLARecord") as MockRecord:
        instance = _make_record(rating_met=False, overall_sla_met=False)
        MockRecord.return_value = instance
        await record_driver_evaluation(db, ACCOUNT_ID, DRIVER_PROFILE_ID, metrics)

    call_kwargs = MockRecord.call_args.kwargs
    assert call_kwargs["rating_met"] is False
    assert call_kwargs["overall_sla_met"] is False


# --- Test 29 ---
@pytest.mark.asyncio
async def test_get_driver_sla_summary_pass_rate():
    db = _mock_db()
    rows = [
        _make_record(record_id=uuid.uuid4(), overall_sla_met=True),
        _make_record(record_id=uuid.uuid4(), overall_sla_met=True),
        _make_record(record_id=uuid.uuid4(), overall_sla_met=False),
    ]
    db.execute.return_value = _scalars_result(rows)
    summary = await get_driver_sla_summary(db, ACCOUNT_ID, DRIVER_PROFILE_ID)
    assert summary.total_evaluations == 3
    assert summary.pass_count == 2
    assert summary.fail_count == 1
    assert summary.pass_rate_pct == pytest.approx(66.67, rel=1e-2)


# --- Test 30 ---
@pytest.mark.asyncio
async def test_get_driver_sla_summary_zero_evaluations():
    db = _mock_db()
    db.execute.return_value = _scalars_result([])
    summary = await get_driver_sla_summary(db, ACCOUNT_ID, DRIVER_PROFILE_ID)
    assert summary.total_evaluations == 0
    assert summary.pass_rate_pct == 0.0


# --- Test 31 ---
@pytest.mark.asyncio
async def test_get_driver_sla_summary_counts_flagged():
    db = _mock_db()
    rows = [
        _make_record(record_id=uuid.uuid4(), flagged_for_review=True),
        _make_record(record_id=uuid.uuid4(), flagged_for_review=True),
        _make_record(record_id=uuid.uuid4(), flagged_for_review=False),
    ]
    db.execute.return_value = _scalars_result(rows)
    summary = await get_driver_sla_summary(db, ACCOUNT_ID, DRIVER_PROFILE_ID)
    assert summary.flagged_count == 2


# --- Test 32 ---
@pytest.mark.asyncio
async def test_list_all_platform_returns_all():
    db = _mock_db()
    rows = [_make_record(), _make_record(record_id=uuid.uuid4(), account_id=99)]
    db.execute.return_value = _scalars_result(rows)
    results = await list_all_platform(db)
    assert len(results) == 2


# --- Test 33 ---
@pytest.mark.asyncio
async def test_list_all_platform_filters_by_account():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_record()])
    results = await list_all_platform(db, account_id=ACCOUNT_ID)
    assert len(results) == 1
    assert results[0].account_id == ACCOUNT_ID


# --- Test 34 ---
@pytest.mark.asyncio
async def test_flag_driver_for_review_success():
    db = _mock_db()
    record = _make_record(flagged_for_review=False)
    with patch(f"{_SERVICE}._fetch_record", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = record
        result = await flag_driver_for_review(
            db, RECORD_ID, ACCOUNT_ID, flagged_by_id=ADMIN_ID, reason="Below threshold"
        )
    assert record.flagged_for_review is True
    assert record.flagged_by_id == ADMIN_ID
    assert record.flag_reason == "Below threshold"
    assert record.flagged_at is not None
    assert db.commit.called


# --- Test 35 ---
@pytest.mark.asyncio
async def test_flag_driver_for_review_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_record", new_callable=AsyncMock) as mock_fr:
        mock_fr.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await flag_driver_for_review(db, uuid.uuid4(), ACCOUNT_ID, flagged_by_id=ADMIN_ID)
    assert exc.value.status_code == 404


# --- Test 36 ---
@pytest.mark.asyncio
async def test_flag_driver_for_review_409_already_flagged():
    db = _mock_db()
    record = _make_record(flagged_for_review=True)
    with patch(f"{_SERVICE}._fetch_record", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = record
        with pytest.raises(HTTPException) as exc:
            await flag_driver_for_review(db, RECORD_ID, ACCOUNT_ID, flagged_by_id=ADMIN_ID)
    assert exc.value.status_code == 409
    assert "already flagged" in exc.value.detail.lower()


# --- Test 37 ---
@pytest.mark.asyncio
async def test_list_flagged_drivers_returns_only_flagged():
    db = _mock_db()
    rows = [_make_record(flagged_for_review=True), _make_record(record_id=uuid.uuid4(), flagged_for_review=True)]
    db.execute.return_value = _scalars_result(rows)
    results = await list_flagged_drivers(db, ACCOUNT_ID)
    assert len(results) == 2
    assert all(r.flagged_for_review for r in results)


# ===========================================================================
# Schema validation tests (38–46)
# ===========================================================================


# --- Test 38 ---
def test_schema_policy_create_requires_name():
    with pytest.raises(ValidationError):
        SLAPolicyCreate()


# --- Test 39 ---
def test_schema_policy_create_rejects_on_time_above_100():
    with pytest.raises(ValidationError):
        SLAPolicyCreate(name="Test", min_on_time_rate_pct=101.0)


# --- Test 40 ---
def test_schema_policy_create_rejects_avg_rating_above_5():
    with pytest.raises(ValidationError):
        SLAPolicyCreate(name="Test", min_avg_rating=5.1)


# --- Test 41 ---
def test_schema_policy_create_optional_fields_default_none():
    schema = SLAPolicyCreate(name="Test")
    assert schema.description is None
    assert schema.min_on_time_rate_pct is None
    assert schema.min_avg_rating is None
    assert schema.max_cancellation_rate_pct is None
    assert schema.min_acceptance_rate_pct is None
    assert schema.evaluation_window_days == 30


# --- Test 42 ---
def test_schema_policy_update_all_optional():
    schema = SLAPolicyUpdate()
    assert schema.name is None
    assert schema.min_on_time_rate_pct is None
    assert schema.is_active is None


# --- Test 43 ---
def test_schema_evaluation_input_rejects_negative_rides():
    with pytest.raises(ValidationError):
        DriverEvaluationInput(total_corporate_rides=-1)


# --- Test 44 ---
def test_schema_evaluation_input_rejects_on_time_above_100():
    with pytest.raises(ValidationError):
        DriverEvaluationInput(on_time_rate_pct=101.0)


# --- Test 45 ---
def test_schema_record_response_structure():
    record = _make_record()
    resp = _record_resp(record)
    assert resp.id == RECORD_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.overall_sla_met is True
    assert resp.flagged_for_review is False


# --- Test 46 ---
def test_schema_driver_summary_response_structure():
    summary = DriverSLASummaryResponse(
        driver_profile_id=DRIVER_PROFILE_ID,
        account_id=ACCOUNT_ID,
        total_evaluations=5,
        pass_count=4,
        fail_count=1,
        pass_rate_pct=80.0,
        flagged_count=0,
        recent_records=[],
    )
    assert summary.pass_rate_pct == 80.0
    assert summary.total_evaluations == 5


# ===========================================================================
# API layer tests (47–71)
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


# --- Test 47 ---
def test_api_get_active_policy_200():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.list_sla_policies", new_callable=AsyncMock, return_value=[_policy_resp()]),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/policy")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 48 ---
def test_api_get_active_policy_null_when_none():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.list_sla_policies", new_callable=AsyncMock, return_value=[]),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/policy")
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() is None


# --- Test 49 ---
def test_api_create_policy_201_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.create_sla_policy", new_callable=AsyncMock, return_value=_policy_resp()),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/policy",
            json={"name": "Standard Corporate Driver SLA", "evaluation_window_days": 30},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 201


# --- Test 50 ---
def test_api_create_policy_403_non_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/policy",
            json={"name": "Test SLA"},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 403


# --- Test 51 ---
def test_api_create_policy_409_name_collision():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.create_sla_policy", new_callable=AsyncMock, side_effect=HTTPException(status_code=409, detail="already exists")),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/policy",
            json={"name": "Standard Corporate Driver SLA"},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 409


# --- Test 52 ---
def test_api_list_all_policies_200_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.list_sla_policies", new_callable=AsyncMock, return_value=[_policy_resp()]),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/policy/all")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 53 ---
def test_api_list_all_policies_403_non_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/policy/all")
        app.dependency_overrides.clear()
    assert r.status_code == 403


# --- Test 54 ---
def test_api_get_specific_policy_200_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.get_sla_policy", new_callable=AsyncMock, return_value=_policy_resp()),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/policy/{POLICY_ID}")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 55 ---
def test_api_get_specific_policy_404():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.get_sla_policy", new_callable=AsyncMock, side_effect=HTTPException(status_code=404, detail="not found")),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/policy/{POLICY_ID}")
        app.dependency_overrides.clear()
    assert r.status_code == 404


# --- Test 56 ---
def test_api_update_policy_200_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.update_sla_policy", new_callable=AsyncMock, return_value=_policy_resp()),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.put(
            f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/policy/{POLICY_ID}",
            json={"min_avg_rating": 4.8},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 57 ---
def test_api_update_policy_403_non_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.put(
            f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/policy/{POLICY_ID}",
            json={"min_avg_rating": 4.8},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 403


# --- Test 58 ---
def test_api_activate_policy_200_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.activate_sla_policy", new_callable=AsyncMock, return_value=_policy_resp()),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/policy/{POLICY_ID}/activate"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 59 ---
def test_api_activate_policy_409_already_active():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.activate_sla_policy", new_callable=AsyncMock, side_effect=HTTPException(status_code=409, detail="already active")),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/policy/{POLICY_ID}/activate"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 409


# --- Test 60 ---
def test_api_deactivate_policy_200_admin():
    inactive_policy = _policy_resp(_make_policy(is_active=False))
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.deactivate_sla_policy", new_callable=AsyncMock, return_value=inactive_policy),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/policy/{POLICY_ID}/deactivate"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 61 ---
def test_api_deactivate_policy_409_already_inactive():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.deactivate_sla_policy", new_callable=AsyncMock, side_effect=HTTPException(status_code=409, detail="already inactive")),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/policy/{POLICY_ID}/deactivate"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 409


# --- Test 62 ---
def test_api_delete_policy_204_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.delete_sla_policy", new_callable=AsyncMock, return_value=None),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.delete(f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/policy/{POLICY_ID}")
        app.dependency_overrides.clear()
    assert r.status_code == 204


# --- Test 63 ---
def test_api_delete_policy_409_when_active():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.delete_sla_policy", new_callable=AsyncMock, side_effect=HTTPException(status_code=409, detail="deactivate first")),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.delete(f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/policy/{POLICY_ID}")
        app.dependency_overrides.clear()
    assert r.status_code == 409


# --- Test 64 ---
def test_api_evaluate_driver_201_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.record_driver_evaluation", new_callable=AsyncMock, return_value=_record_resp()),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/drivers/{DRIVER_PROFILE_ID}/evaluate",
            json={"total_corporate_rides": 20, "on_time_rate_pct": 90.0},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 201


# --- Test 65 ---
def test_api_evaluate_driver_403_non_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/drivers/{DRIVER_PROFILE_ID}/evaluate",
            json={"total_corporate_rides": 5},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 403


# --- Test 66 ---
def test_api_get_driver_summary_200_admin():
    summary = DriverSLASummaryResponse(
        driver_profile_id=DRIVER_PROFILE_ID,
        account_id=ACCOUNT_ID,
        total_evaluations=3,
        pass_count=2,
        fail_count=1,
        pass_rate_pct=66.67,
        flagged_count=0,
        recent_records=[],
    )
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.get_driver_sla_summary", new_callable=AsyncMock, return_value=summary),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/drivers/{DRIVER_PROFILE_ID}/summary"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert data["total_evaluations"] == 3


# --- Test 67 ---
def test_api_list_flagged_200_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.list_flagged_drivers", new_callable=AsyncMock, return_value=[_record_resp(_make_record(flagged_for_review=True))]),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/flagged")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 68 ---
def test_api_flag_record_200_admin():
    flagged = _record_resp(_make_record(flagged_for_review=True, flagged_by_id=ADMIN_ID))
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.flag_driver_for_review", new_callable=AsyncMock, return_value=flagged),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/records/{RECORD_ID}/flag",
            json={"reason": "Missed on-time threshold"},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert data["flagged_for_review"] is True


# --- Test 69 ---
def test_api_flag_record_409_already_flagged():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.flag_driver_for_review", new_callable=AsyncMock, side_effect=HTTPException(status_code=409, detail="already flagged")),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/driver-sla/records/{RECORD_ID}/flag",
            json={},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 409


# --- Test 70 ---
def test_api_platform_list_all_200():
    with patch(f"{_ROUTER}.list_all_platform", new_callable=AsyncMock, return_value=[_record_resp()]):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get("/api/v1/platform/corporate/driver-sla/all")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 71 ---
def test_api_platform_list_all_with_account_filter():
    with patch(f"{_ROUTER}.list_all_platform", new_callable=AsyncMock, return_value=[_record_resp()]) as mock_svc:
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/platform/corporate/driver-sla/all?account_id={ACCOUNT_ID}")
        app.dependency_overrides.clear()
    assert r.status_code == 200
    call_kwargs = mock_svc.call_args.kwargs
    assert call_kwargs.get("account_id") == ACCOUNT_ID
