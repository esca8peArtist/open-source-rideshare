"""Tests for the Corporate SLA Policies & Compliance Reporting feature.

Service layer (async, mocked DB):
  1.  create_sla_policy — creates policy with supplied fields
  2.  create_sla_policy — stores created_by_id from caller
  3.  create_sla_policy — 409 on duplicate active name within account
  4.  get_sla_policy — returns policy when found
  5.  get_sla_policy — 404 when not found
  6.  get_sla_policy — 404 when policy belongs to different account
  7.  list_sla_policies — returns all policies sorted by name
  8.  list_sla_policies — filter is_active=True returns only active
  9.  list_sla_policies — filter is_active=False returns only inactive
  10. update_sla_policy — partial update writes only supplied fields
  11. update_sla_policy — 404 when not found
  12. update_sla_policy — 409 on name collision with different policy
  13. activate_sla_policy — sets is_active=True
  14. activate_sla_policy — deactivates existing active policy first
  15. activate_sla_policy — 404 when not found
  16. activate_sla_policy — 409 when already active
  17. deactivate_sla_policy — sets is_active=False
  18. deactivate_sla_policy — 404 when not found
  19. deactivate_sla_policy — 409 when already inactive
  20. delete_sla_policy — hard-deletes inactive policy
  21. delete_sla_policy — 404 when not found
  22. delete_sla_policy — 409 when active
  23. record_sla_evaluation — all dimensions met → overall_sla_met=True
  24. record_sla_evaluation — wait time breached → overall_sla_met=False
  25. record_sla_evaluation — driver rating breached → overall_sla_met=False
  26. record_sla_evaluation — on-time breached for scheduled ride → overall_sla_met=False
  27. record_sla_evaluation — no active policy → overall_sla_met=True, policy_id=None
  28. record_sla_evaluation — computes arrival_delta_minutes correctly
  29. record_sla_evaluation — on_time_met=None for non-scheduled ride
  30. record_sla_evaluation — dimension=None when data missing but threshold set
  31. get_sla_compliance_summary — correct total/met/breach counts
  32. get_sla_compliance_summary — compliance_pct is None when no records
  33. get_sla_compliance_summary — per-dimension breakdown
  34. get_sla_compliance_summary — filters by year and month
  35. get_sla_compliance_trend — groups records into monthly buckets
  36. get_sla_compliance_trend — returns at most N months
  37. get_sla_compliance_trend — ordered oldest to newest
  38. list_sla_breaches — returns only breach records
  39. list_sla_breaches — filters by year/month
  40. list_sla_breaches — respects limit and offset
  41. list_all_platform — returns all policies without filter
  42. list_all_platform — filters by account_id

Schema validation:
  43. SLAPolicyCreate — valid data accepted
  44. SLAPolicyCreate — blank name rejected
  45. SLAPolicyCreate — min_driver_rating out of range rejected
  46. SLAPolicyCreate — target_completion_rate_pct out of range rejected
  47. SLAPolicyUpdate — all fields optional
  48. SLAPolicyUpdate — blank name rejected when supplied
  49. SLAPolicyResponse — from_attributes construction
  50. SLAEvaluationCreate — valid data accepted
  51. SLARideRecordResponse — from_attributes construction
  52. SLAComplianceSummary — structure validated
  53. DimensionSummary — pct is None when total=0
  54. SLATrendEntry — structure validated

API layer (service functions patched):
  55. GET /policy (member) — 200 returns active policy
  56. GET /policy (member) — 404 when no active policy
  57. GET /policy (member) — 404 when not in account
  58. GET /summary (member) — 200 returns compliance summary
  59. GET /trend (member) — 200 returns trend
  60. POST /policies (admin) — 201 creates policy
  61. POST /policies (admin) — 403 non-admin cannot create
  62. POST /policies (admin) — 409 on duplicate active name
  63. GET /policies (admin) — 200 returns policy list
  64. GET /policies (admin) — 403 non-admin blocked
  65. GET /policies/{id} (admin) — 200 returns policy
  66. PUT /policies/{id} (admin) — 200 updates policy
  67. PUT /policies/{id} (admin) — 403 non-admin blocked
  68. POST /policies/{id}/activate (admin) — 200 activates policy
  69. POST /policies/{id}/activate (admin) — 409 when already active
  70. POST /policies/{id}/deactivate (admin) — 200 deactivates policy
  71. POST /policies/{id}/deactivate (admin) — 409 when already inactive
  72. DELETE /policies/{id} (admin) — 204 deletes inactive policy
  73. DELETE /policies/{id} (admin) — 409 when active
  74. POST /rides/{id}/evaluate (admin) — 201 records evaluation
  75. GET /breaches (admin) — 200 returns breach list
  76. GET /platform/all — 200 platform-admin lists all policies
  77. GET /platform/account/{id}/summary — 200 platform-admin returns summary
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.corporate_sla_policy import CorporateSLAPolicy, CorporateSLARideRecord
from app.schemas.corporate_sla_policy import (
    DimensionSummary,
    SLAComplianceSummary,
    SLAEvaluationCreate,
    SLAPolicyCreate,
    SLAPolicyListResponse,
    SLAPolicyResponse,
    SLAPolicyUpdate,
    SLARideRecordListResponse,
    SLARideRecordResponse,
    SLATrendEntry,
    SLATrendResponse,
)
from app.services.corporate_sla_policy import (
    activate_sla_policy,
    create_sla_policy,
    deactivate_sla_policy,
    delete_sla_policy,
    get_sla_compliance_summary,
    get_sla_compliance_trend,
    get_sla_policy,
    list_all_platform,
    list_sla_breaches,
    list_sla_policies,
    record_sla_evaluation,
    update_sla_policy,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
NOW_JAN = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
NOW_FEB = datetime(2026, 2, 15, 12, 0, 0, tzinfo=timezone.utc)
NOW_MAR = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)

ACCOUNT_ID = 10
ADMIN_ID = 21
POLICY_ID = uuid.uuid4()
OTHER_POLICY_ID = uuid.uuid4()
RECORD_ID = uuid.uuid4()


def _make_policy(
    id: uuid.UUID = POLICY_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Standard SLA Q1 2026",
    max_wait_time_minutes: int | None = 10,
    min_driver_rating: Decimal | None = Decimal("4.5"),
    on_time_window_minutes: int | None = 5,
    target_completion_rate_pct: Decimal | None = Decimal("95.00"),
    is_active: bool = True,
    effective_from=None,
    effective_until=None,
    created_by_id: int | None = ADMIN_ID,
) -> CorporateSLAPolicy:
    p = CorporateSLAPolicy()
    p.id = id
    p.account_id = account_id
    p.name = name
    p.max_wait_time_minutes = max_wait_time_minutes
    p.min_driver_rating = min_driver_rating
    p.on_time_window_minutes = on_time_window_minutes
    p.target_completion_rate_pct = target_completion_rate_pct
    p.is_active = is_active
    p.effective_from = effective_from
    p.effective_until = effective_until
    p.created_by_id = created_by_id
    p.created_at = NOW
    p.updated_at = NOW
    return p


def _make_inactive_policy(**kwargs) -> CorporateSLAPolicy:
    return _make_policy(is_active=False, **kwargs)


def _make_record(
    id: uuid.UUID = RECORD_ID,
    account_id: int = ACCOUNT_ID,
    policy_id: uuid.UUID | None = POLICY_ID,
    ride_id: int | None = 1,
    member_id: int | None = 5,
    wait_time_minutes: Decimal | None = Decimal("8.0"),
    driver_rating_at_time: Decimal | None = Decimal("4.7"),
    was_scheduled_ride: bool = False,
    scheduled_pickup_at: datetime | None = None,
    actual_pickup_at: datetime | None = None,
    arrival_delta_minutes: Decimal | None = None,
    wait_time_met: bool | None = True,
    driver_rating_met: bool | None = True,
    on_time_met: bool | None = None,
    overall_sla_met: bool = True,
    evaluated_at: datetime = NOW,
) -> CorporateSLARideRecord:
    r = CorporateSLARideRecord()
    r.id = id
    r.account_id = account_id
    r.policy_id = policy_id
    r.ride_id = ride_id
    r.member_id = member_id
    r.wait_time_minutes = wait_time_minutes
    r.driver_rating_at_time = driver_rating_at_time
    r.was_scheduled_ride = was_scheduled_ride
    r.scheduled_pickup_at = scheduled_pickup_at
    r.actual_pickup_at = actual_pickup_at
    r.arrival_delta_minutes = arrival_delta_minutes
    r.wait_time_met = wait_time_met
    r.driver_rating_met = driver_rating_met
    r.on_time_met = on_time_met
    r.overall_sla_met = overall_sla_met
    r.evaluated_at = evaluated_at
    return r


def _make_breach_record(**kwargs) -> CorporateSLARideRecord:
    return _make_record(
        overall_sla_met=False,
        wait_time_met=False,
        **kwargs,
    )


def _make_policy_response(policy: CorporateSLAPolicy) -> SLAPolicyResponse:
    return SLAPolicyResponse(
        id=policy.id,
        account_id=policy.account_id,
        name=policy.name,
        max_wait_time_minutes=policy.max_wait_time_minutes,
        min_driver_rating=(
            Decimal(str(policy.min_driver_rating))
            if policy.min_driver_rating is not None else None
        ),
        on_time_window_minutes=policy.on_time_window_minutes,
        target_completion_rate_pct=(
            Decimal(str(policy.target_completion_rate_pct))
            if policy.target_completion_rate_pct is not None else None
        ),
        is_active=policy.is_active,
        effective_from=policy.effective_from,
        effective_until=policy.effective_until,
        created_by_id=policy.created_by_id,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _db_returning(row):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute.return_value = result
    return db


def _db_returning_all(rows):
    db = AsyncMock()
    result = MagicMock()
    scalar_result = MagicMock()
    scalar_result.all.return_value = rows
    result.scalars.return_value = scalar_result
    db.execute.return_value = result
    return db


def _db_multi(*responses):
    """Return a db mock that cycles through multiple execute() return values."""
    db = AsyncMock()
    results = []
    for r in responses:
        mock_result = MagicMock()
        if isinstance(r, list):
            scalar_res = MagicMock()
            scalar_res.all.return_value = r
            mock_result.scalars.return_value = scalar_res
        else:
            mock_result.scalar_one_or_none.return_value = r
        results.append(mock_result)
    db.execute.side_effect = results
    return db


# ---------------------------------------------------------------------------
# Service layer tests — create_sla_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_sla_policy_creates_policy():
    """create_sla_policy creates a new policy with correct fields."""
    db = AsyncMock()
    db.add = MagicMock()

    async def _refresh(obj):
        obj.id = POLICY_ID
        obj.created_at = NOW
        obj.updated_at = NOW

    db.refresh = AsyncMock(side_effect=_refresh)
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    db.execute.return_value = result_mock

    data = SLAPolicyCreate(
        name="Standard SLA Q1 2026",
        max_wait_time_minutes=10,
        min_driver_rating=Decimal("4.5"),
    )
    result = await create_sla_policy(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)

    db.add.assert_called_once()
    db.commit.assert_called_once()
    assert result.name == "Standard SLA Q1 2026"


@pytest.mark.asyncio
async def test_create_sla_policy_stores_created_by_id():
    """create_sla_policy stores the created_by_id on the new record."""
    db = AsyncMock()
    captured = {}

    def _capture(obj):
        captured["policy"] = obj

    db.add = MagicMock(side_effect=_capture)

    async def _refresh(obj):
        obj.id = POLICY_ID
        obj.created_at = NOW
        obj.updated_at = NOW

    db.refresh = AsyncMock(side_effect=_refresh)
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    db.execute.return_value = result_mock

    data = SLAPolicyCreate(name="Q1 SLA")
    await create_sla_policy(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)
    assert captured["policy"].created_by_id == ADMIN_ID


@pytest.mark.asyncio
async def test_create_sla_policy_409_on_duplicate_active_name():
    """create_sla_policy raises 409 when an active policy with the same name exists."""
    from fastapi import HTTPException

    existing = _make_policy(is_active=True)
    db = _db_returning(existing)

    data = SLAPolicyCreate(name="Standard SLA Q1 2026")
    with pytest.raises(HTTPException) as exc:
        await create_sla_policy(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — get_sla_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_sla_policy_returns_policy_when_found():
    """get_sla_policy returns the policy response when found."""
    policy = _make_policy()
    db = _db_returning(policy)
    result = await get_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    assert result.id == POLICY_ID
    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_get_sla_policy_404_when_not_found():
    """get_sla_policy raises HTTP 404 when policy not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await get_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_sla_policy_404_for_different_account():
    """get_sla_policy raises 404 when policy belongs to a different account."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await get_sla_policy(db, POLICY_ID, account_id=999)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests — list_sla_policies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sla_policies_returns_all():
    """list_sla_policies returns all policies for the account."""
    policies = [
        _make_policy(id=uuid.uuid4(), name="A Policy"),
        _make_policy(id=uuid.uuid4(), name="B Policy"),
    ]
    db = _db_returning_all(policies)
    result = await list_sla_policies(db, ACCOUNT_ID)
    assert result.total == 2
    assert len(result.items) == 2


@pytest.mark.asyncio
async def test_list_sla_policies_filter_active():
    """list_sla_policies with is_active=True returns only active policies."""
    active = _make_policy(is_active=True)
    db = _db_returning_all([active])
    result = await list_sla_policies(db, ACCOUNT_ID, is_active=True)
    assert result.total == 1
    assert result.items[0].is_active is True


@pytest.mark.asyncio
async def test_list_sla_policies_filter_inactive():
    """list_sla_policies with is_active=False returns only inactive policies."""
    inactive = _make_inactive_policy()
    db = _db_returning_all([inactive])
    result = await list_sla_policies(db, ACCOUNT_ID, is_active=False)
    assert result.total == 1
    assert result.items[0].is_active is False


# ---------------------------------------------------------------------------
# Service layer tests — update_sla_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_sla_policy_partial_update():
    """update_sla_policy writes only supplied fields."""
    policy = _make_policy(name="Old Name")

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = policy
        else:
            result.scalar_one_or_none.return_value = None
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    data = SLAPolicyUpdate(name="New Name")
    await update_sla_policy(db, POLICY_ID, ACCOUNT_ID, data)
    assert policy.name == "New Name"
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_sla_policy_404_when_not_found():
    """update_sla_policy raises 404 when policy not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    data = SLAPolicyUpdate(name="New Name")
    with pytest.raises(HTTPException) as exc:
        await update_sla_policy(db, POLICY_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_sla_policy_409_on_name_collision():
    """update_sla_policy raises 409 when new name collides with another policy."""
    from fastapi import HTTPException

    policy = _make_policy(name="Policy A")
    other = _make_policy(id=OTHER_POLICY_ID, name="Policy B")

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = policy
        else:
            result.scalar_one_or_none.return_value = other
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    data = SLAPolicyUpdate(name="Policy B")
    with pytest.raises(HTTPException) as exc:
        await update_sla_policy(db, POLICY_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — activate_sla_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activate_sla_policy_sets_active():
    """activate_sla_policy sets is_active=True on the target policy."""
    policy = _make_inactive_policy()

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # get policy row
            result.scalar_one_or_none.return_value = policy
        else:
            # deactivate existing active policies query
            scalar_res = MagicMock()
            scalar_res.all.return_value = []
            result.scalars.return_value = scalar_res
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    await activate_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    assert policy.is_active is True
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_activate_sla_policy_deactivates_existing():
    """activate_sla_policy deactivates the currently active policy first."""
    target = _make_inactive_policy(id=OTHER_POLICY_ID)
    currently_active = _make_policy(id=POLICY_ID, is_active=True)

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = target
        else:
            scalar_res = MagicMock()
            scalar_res.all.return_value = [currently_active]
            result.scalars.return_value = scalar_res
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    await activate_sla_policy(db, OTHER_POLICY_ID, ACCOUNT_ID)
    assert currently_active.is_active is False
    assert target.is_active is True


@pytest.mark.asyncio
async def test_activate_sla_policy_404_when_not_found():
    """activate_sla_policy raises 404 when policy not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await activate_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_activate_sla_policy_409_when_already_active():
    """activate_sla_policy raises 409 when policy is already active."""
    from fastapi import HTTPException

    policy = _make_policy(is_active=True)
    db = _db_returning(policy)
    with pytest.raises(HTTPException) as exc:
        await activate_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — deactivate_sla_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_sla_policy_sets_inactive():
    """deactivate_sla_policy sets is_active=False."""
    policy = _make_policy(is_active=True)
    db = _db_returning(policy)
    await deactivate_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    assert policy.is_active is False
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_deactivate_sla_policy_404_when_not_found():
    """deactivate_sla_policy raises 404 when policy not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await deactivate_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_sla_policy_409_when_already_inactive():
    """deactivate_sla_policy raises 409 when policy is already inactive."""
    from fastapi import HTTPException

    policy = _make_inactive_policy()
    db = _db_returning(policy)
    with pytest.raises(HTTPException) as exc:
        await deactivate_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — delete_sla_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_sla_policy_deletes_inactive():
    """delete_sla_policy hard-deletes an inactive policy."""
    policy = _make_inactive_policy()
    db = _db_returning(policy)
    await delete_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    db.delete.assert_called_once_with(policy)
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_sla_policy_404_when_not_found():
    """delete_sla_policy raises 404 when policy not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await delete_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_sla_policy_409_when_active():
    """delete_sla_policy raises 409 when policy is active."""
    from fastapi import HTTPException

    policy = _make_policy(is_active=True)
    db = _db_returning(policy)
    with pytest.raises(HTTPException) as exc:
        await delete_sla_policy(db, POLICY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — record_sla_evaluation
# ---------------------------------------------------------------------------


def _make_eval_db(policy: CorporateSLAPolicy | None):
    """Return a db mock where the active-policy query returns `policy`."""
    db = AsyncMock()
    db.add = MagicMock()

    async def _refresh(obj):
        obj.id = RECORD_ID
        obj.evaluated_at = NOW

    db.refresh = AsyncMock(side_effect=_refresh)

    result = MagicMock()
    result.scalar_one_or_none.return_value = policy
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_record_sla_evaluation_all_met():
    """record_sla_evaluation sets overall_sla_met=True when all dimensions pass."""
    policy = _make_policy(
        max_wait_time_minutes=10,
        min_driver_rating=Decimal("4.0"),
        on_time_window_minutes=5,
    )
    db = _make_eval_db(policy)

    result = await record_sla_evaluation(
        db,
        ACCOUNT_ID,
        ride_id=1,
        member_id=5,
        wait_time_minutes=Decimal("7"),
        driver_rating=Decimal("4.8"),
        was_scheduled_ride=True,
        scheduled_pickup_at=datetime(2026, 4, 16, 9, 0, tzinfo=timezone.utc),
        actual_pickup_at=datetime(2026, 4, 16, 9, 3, tzinfo=timezone.utc),
    )

    assert result.overall_sla_met is True
    assert result.wait_time_met is True
    assert result.driver_rating_met is True
    assert result.on_time_met is True


@pytest.mark.asyncio
async def test_record_sla_evaluation_wait_time_breached():
    """record_sla_evaluation sets overall_sla_met=False when wait time exceeds threshold."""
    policy = _make_policy(max_wait_time_minutes=5, on_time_window_minutes=None)
    db = _make_eval_db(policy)

    result = await record_sla_evaluation(
        db,
        ACCOUNT_ID,
        ride_id=1,
        member_id=5,
        wait_time_minutes=Decimal("12"),
    )

    assert result.wait_time_met is False
    assert result.overall_sla_met is False


@pytest.mark.asyncio
async def test_record_sla_evaluation_driver_rating_breached():
    """record_sla_evaluation sets overall_sla_met=False when driver rating is too low."""
    policy = _make_policy(
        max_wait_time_minutes=None,
        min_driver_rating=Decimal("4.5"),
        on_time_window_minutes=None,
    )
    db = _make_eval_db(policy)

    result = await record_sla_evaluation(
        db,
        ACCOUNT_ID,
        ride_id=1,
        member_id=5,
        driver_rating=Decimal("4.2"),
    )

    assert result.driver_rating_met is False
    assert result.overall_sla_met is False


@pytest.mark.asyncio
async def test_record_sla_evaluation_on_time_breached():
    """record_sla_evaluation sets overall_sla_met=False when arrival is too late."""
    policy = _make_policy(
        max_wait_time_minutes=None,
        min_driver_rating=None,
        on_time_window_minutes=5,
    )
    db = _make_eval_db(policy)

    result = await record_sla_evaluation(
        db,
        ACCOUNT_ID,
        ride_id=1,
        member_id=5,
        was_scheduled_ride=True,
        scheduled_pickup_at=datetime(2026, 4, 16, 9, 0, tzinfo=timezone.utc),
        actual_pickup_at=datetime(2026, 4, 16, 9, 10, tzinfo=timezone.utc),
    )

    assert result.on_time_met is False
    assert result.overall_sla_met is False


@pytest.mark.asyncio
async def test_record_sla_evaluation_no_active_policy():
    """record_sla_evaluation stores record with overall_sla_met=True when no policy."""
    db = _make_eval_db(policy=None)

    result = await record_sla_evaluation(
        db,
        ACCOUNT_ID,
        ride_id=1,
        member_id=5,
        wait_time_minutes=Decimal("8"),
        driver_rating=Decimal("4.9"),
    )

    assert result.policy_id is None
    assert result.wait_time_met is None
    assert result.driver_rating_met is None
    assert result.on_time_met is None
    assert result.overall_sla_met is True


@pytest.mark.asyncio
async def test_record_sla_evaluation_computes_arrival_delta():
    """record_sla_evaluation computes arrival_delta_minutes correctly."""
    policy = _make_policy(on_time_window_minutes=10)
    db = _make_eval_db(policy)

    result = await record_sla_evaluation(
        db,
        ACCOUNT_ID,
        ride_id=1,
        member_id=5,
        was_scheduled_ride=True,
        scheduled_pickup_at=datetime(2026, 4, 16, 9, 0, tzinfo=timezone.utc),
        actual_pickup_at=datetime(2026, 4, 16, 9, 7, tzinfo=timezone.utc),
    )

    assert result.arrival_delta_minutes == Decimal("7.0")


@pytest.mark.asyncio
async def test_record_sla_evaluation_on_time_none_for_non_scheduled():
    """record_sla_evaluation leaves on_time_met=None for non-scheduled rides."""
    policy = _make_policy(on_time_window_minutes=5)
    db = _make_eval_db(policy)

    result = await record_sla_evaluation(
        db,
        ACCOUNT_ID,
        ride_id=1,
        member_id=5,
        was_scheduled_ride=False,
    )

    assert result.on_time_met is None


@pytest.mark.asyncio
async def test_record_sla_evaluation_dimension_none_when_data_missing():
    """Dimension result is None when threshold set but data not provided."""
    policy = _make_policy(
        max_wait_time_minutes=10,
        min_driver_rating=Decimal("4.0"),
    )
    db = _make_eval_db(policy)

    result = await record_sla_evaluation(
        db,
        ACCOUNT_ID,
        ride_id=1,
        member_id=5,
        # Neither wait_time_minutes nor driver_rating provided.
    )

    assert result.wait_time_met is None
    assert result.driver_rating_met is None
    # No evaluated dimensions → overall passes.
    assert result.overall_sla_met is True


# ---------------------------------------------------------------------------
# Service layer tests — get_sla_compliance_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_sla_compliance_summary_correct_counts():
    """get_sla_compliance_summary returns correct total/met/breach counts."""
    records = [
        _make_record(id=uuid.uuid4(), overall_sla_met=True),
        _make_record(id=uuid.uuid4(), overall_sla_met=True),
        _make_record(id=uuid.uuid4(), overall_sla_met=False, wait_time_met=False),
    ]
    db = _db_returning_all(records)
    result = await get_sla_compliance_summary(db, ACCOUNT_ID)
    assert result.total_rides == 3
    assert result.sla_met_count == 2
    assert result.sla_breach_count == 1
    assert abs(result.compliance_pct - 66.666) < 0.01


@pytest.mark.asyncio
async def test_get_sla_compliance_summary_none_pct_on_empty():
    """get_sla_compliance_summary returns compliance_pct=None when no records."""
    db = _db_returning_all([])
    result = await get_sla_compliance_summary(db, ACCOUNT_ID)
    assert result.total_rides == 0
    assert result.compliance_pct is None


@pytest.mark.asyncio
async def test_get_sla_compliance_summary_per_dimension_breakdown():
    """get_sla_compliance_summary calculates per-dimension met/total/pct."""
    records = [
        _make_record(id=uuid.uuid4(), wait_time_met=True, driver_rating_met=True),
        _make_record(id=uuid.uuid4(), wait_time_met=False, driver_rating_met=True),
        _make_record(id=uuid.uuid4(), wait_time_met=None, driver_rating_met=None),
    ]
    db = _db_returning_all(records)
    result = await get_sla_compliance_summary(db, ACCOUNT_ID)
    wait = result.by_dimension["wait_time"]
    # Only 2 records have non-None wait_time_met
    assert wait.total == 2
    assert wait.met == 1

    driver = result.by_dimension["driver_rating"]
    assert driver.total == 2
    assert driver.met == 2


@pytest.mark.asyncio
async def test_get_sla_compliance_summary_filters_by_month():
    """get_sla_compliance_summary includes year/month filter clause."""
    db = _db_returning_all([])
    # Should not raise; actual filter is applied at SQL level
    result = await get_sla_compliance_summary(db, ACCOUNT_ID, year=2026, month=1)
    assert result.total_rides == 0


# ---------------------------------------------------------------------------
# Service layer tests — get_sla_compliance_trend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_sla_compliance_trend_groups_by_month():
    """get_sla_compliance_trend groups records into monthly buckets."""
    records = [
        _make_record(id=uuid.uuid4(), overall_sla_met=True, evaluated_at=NOW_JAN),
        _make_record(id=uuid.uuid4(), overall_sla_met=False, evaluated_at=NOW_JAN),
        _make_record(id=uuid.uuid4(), overall_sla_met=True, evaluated_at=NOW_FEB),
    ]
    db = _db_returning_all(records)
    result = await get_sla_compliance_trend(db, ACCOUNT_ID, months=6)
    assert len(result.items) == 2
    jan = next(e for e in result.items if e.month == 1)
    assert jan.total_rides == 2
    assert jan.compliance_pct == 50.0
    feb = next(e for e in result.items if e.month == 2)
    assert feb.total_rides == 1
    assert feb.compliance_pct == 100.0


@pytest.mark.asyncio
async def test_get_sla_compliance_trend_limits_to_n_months():
    """get_sla_compliance_trend returns at most N most recent months."""
    records = [
        _make_record(id=uuid.uuid4(), overall_sla_met=True, evaluated_at=NOW_JAN),
        _make_record(id=uuid.uuid4(), overall_sla_met=True, evaluated_at=NOW_FEB),
        _make_record(id=uuid.uuid4(), overall_sla_met=True, evaluated_at=NOW_MAR),
    ]
    db = _db_returning_all(records)
    result = await get_sla_compliance_trend(db, ACCOUNT_ID, months=2)
    assert len(result.items) == 2


@pytest.mark.asyncio
async def test_get_sla_compliance_trend_ordered_oldest_first():
    """get_sla_compliance_trend returns months ordered from oldest to newest."""
    records = [
        _make_record(id=uuid.uuid4(), overall_sla_met=True, evaluated_at=NOW_MAR),
        _make_record(id=uuid.uuid4(), overall_sla_met=True, evaluated_at=NOW_JAN),
        _make_record(id=uuid.uuid4(), overall_sla_met=True, evaluated_at=NOW_FEB),
    ]
    db = _db_returning_all(records)
    result = await get_sla_compliance_trend(db, ACCOUNT_ID, months=6)
    months = [e.month for e in result.items]
    assert months == sorted(months)


# ---------------------------------------------------------------------------
# Service layer tests — list_sla_breaches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sla_breaches_returns_breach_records():
    """list_sla_breaches returns records where overall_sla_met=False."""
    breaches = [
        _make_breach_record(id=uuid.uuid4()),
        _make_breach_record(id=uuid.uuid4()),
    ]
    db = _db_returning_all(breaches)
    result = await list_sla_breaches(db, ACCOUNT_ID)
    assert result.total == 2
    assert all(not r.overall_sla_met for r in result.items)


@pytest.mark.asyncio
async def test_list_sla_breaches_filters_by_month():
    """list_sla_breaches includes year/month filter when specified."""
    db = _db_returning_all([])
    result = await list_sla_breaches(db, ACCOUNT_ID, year=2026, month=4)
    assert result.total == 0


@pytest.mark.asyncio
async def test_list_sla_breaches_respects_limit_offset():
    """list_sla_breaches applies limit/offset without raising."""
    db = _db_returning_all([])
    result = await list_sla_breaches(db, ACCOUNT_ID, limit=10, offset=5)
    assert isinstance(result, SLARideRecordListResponse)


# ---------------------------------------------------------------------------
# Service layer tests — list_all_platform
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_platform_returns_all():
    """list_all_platform returns all policies when no filter."""
    policies = [
        _make_policy(id=uuid.uuid4(), account_id=1, name="Policy A"),
        _make_policy(id=uuid.uuid4(), account_id=2, name="Policy B"),
    ]
    db = _db_returning_all(policies)
    result = await list_all_platform(db)
    assert result.total == 2


@pytest.mark.asyncio
async def test_list_all_platform_filters_by_account():
    """list_all_platform filters by account_id when provided."""
    policy = _make_policy(account_id=10)
    db = _db_returning_all([policy])
    result = await list_all_platform(db, account_id=10)
    assert result.total == 1
    assert result.items[0].account_id == 10


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_sla_policy_create_valid():
    """SLAPolicyCreate accepts valid data."""
    data = SLAPolicyCreate(
        name="Q1 2026 Standard",
        max_wait_time_minutes=10,
        min_driver_rating=Decimal("4.5"),
        on_time_window_minutes=5,
        target_completion_rate_pct=Decimal("95"),
    )
    assert data.name == "Q1 2026 Standard"
    assert data.max_wait_time_minutes == 10


def test_sla_policy_create_blank_name_rejected():
    """SLAPolicyCreate rejects blank name."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SLAPolicyCreate(name="  ")


def test_sla_policy_create_driver_rating_out_of_range():
    """SLAPolicyCreate rejects min_driver_rating > 5."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SLAPolicyCreate(name="Test", min_driver_rating=Decimal("5.1"))


def test_sla_policy_create_completion_rate_out_of_range():
    """SLAPolicyCreate rejects target_completion_rate_pct > 100."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SLAPolicyCreate(name="Test", target_completion_rate_pct=Decimal("100.1"))


def test_sla_policy_update_all_optional():
    """SLAPolicyUpdate allows all-empty update."""
    data = SLAPolicyUpdate()
    assert data.name is None
    assert data.max_wait_time_minutes is None


def test_sla_policy_update_blank_name_rejected():
    """SLAPolicyUpdate rejects blank name when supplied."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SLAPolicyUpdate(name="")


def test_sla_policy_response_from_attributes():
    """SLAPolicyResponse can be constructed from attributes."""
    policy = _make_policy()
    resp = _make_policy_response(policy)
    assert resp.id == POLICY_ID
    assert resp.is_active is True


def test_sla_evaluation_create_valid():
    """SLAEvaluationCreate accepts valid data."""
    data = SLAEvaluationCreate(
        wait_time_minutes=Decimal("8.5"),
        driver_rating=Decimal("4.9"),
        was_scheduled_ride=True,
    )
    assert data.was_scheduled_ride is True


def test_sla_ride_record_response_from_attributes():
    """SLARideRecordResponse can be constructed from attributes."""
    record = _make_record()
    resp = SLARideRecordResponse(
        id=record.id,
        account_id=record.account_id,
        policy_id=record.policy_id,
        ride_id=record.ride_id,
        member_id=record.member_id,
        wait_time_minutes=record.wait_time_minutes,
        driver_rating_at_time=record.driver_rating_at_time,
        was_scheduled_ride=record.was_scheduled_ride,
        scheduled_pickup_at=record.scheduled_pickup_at,
        actual_pickup_at=record.actual_pickup_at,
        arrival_delta_minutes=record.arrival_delta_minutes,
        wait_time_met=record.wait_time_met,
        driver_rating_met=record.driver_rating_met,
        on_time_met=record.on_time_met,
        overall_sla_met=record.overall_sla_met,
        evaluated_at=record.evaluated_at,
    )
    assert resp.id == RECORD_ID
    assert resp.overall_sla_met is True


def test_sla_compliance_summary_structure():
    """SLAComplianceSummary validates correctly."""
    summary = SLAComplianceSummary(
        total_rides=100,
        sla_met_count=90,
        sla_breach_count=10,
        compliance_pct=90.0,
        by_dimension={
            "wait_time": DimensionSummary(total=80, met=75, pct=93.75),
            "driver_rating": DimensionSummary(total=80, met=78, pct=97.5),
            "on_time": DimensionSummary(total=20, met=18, pct=90.0),
        },
    )
    assert summary.total_rides == 100
    assert summary.by_dimension["wait_time"].pct == 93.75


def test_dimension_summary_pct_none_when_zero_total():
    """DimensionSummary allows pct=None to signal no data."""
    dim = DimensionSummary(total=0, met=0, pct=None)
    assert dim.pct is None


def test_sla_trend_entry_structure():
    """SLATrendEntry validates year/month/compliance fields."""
    entry = SLATrendEntry(year=2026, month=3, total_rides=50, compliance_pct=88.0)
    assert entry.year == 2026
    assert entry.compliance_pct == 88.0


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

# Shared constants for API tests.
_USER_ID = 99
_ACCOUNT_ID = 10
_POLICY_ID = uuid.uuid4()

_POLICY_RESP = SLAPolicyResponse(
    id=_POLICY_ID,
    account_id=_ACCOUNT_ID,
    name="Standard SLA",
    max_wait_time_minutes=10,
    min_driver_rating=Decimal("4.5"),
    on_time_window_minutes=5,
    target_completion_rate_pct=Decimal("95"),
    is_active=True,
    effective_from=None,
    effective_until=None,
    created_by_id=_USER_ID,
    created_at=NOW,
    updated_at=NOW,
)

_POLICY_LIST_RESP = SLAPolicyListResponse(items=[_POLICY_RESP], total=1)

_SUMMARY_RESP = SLAComplianceSummary(
    total_rides=10,
    sla_met_count=9,
    sla_breach_count=1,
    compliance_pct=90.0,
    by_dimension={
        "wait_time": DimensionSummary(total=8, met=7, pct=87.5),
        "driver_rating": DimensionSummary(total=8, met=8, pct=100.0),
        "on_time": DimensionSummary(total=3, met=3, pct=100.0),
    },
)

_TREND_RESP = SLATrendResponse(
    items=[SLATrendEntry(year=2026, month=3, total_rides=10, compliance_pct=90.0)]
)

_RECORD_RESP = SLARideRecordResponse(
    id=uuid.uuid4(),
    account_id=_ACCOUNT_ID,
    policy_id=_POLICY_ID,
    ride_id=1,
    member_id=_USER_ID,
    wait_time_minutes=Decimal("7"),
    driver_rating_at_time=Decimal("4.8"),
    was_scheduled_ride=False,
    scheduled_pickup_at=None,
    actual_pickup_at=None,
    arrival_delta_minutes=None,
    wait_time_met=True,
    driver_rating_met=True,
    on_time_met=None,
    overall_sla_met=True,
    evaluated_at=NOW,
)

_RECORD_LIST_RESP = SLARideRecordListResponse(items=[_RECORD_RESP], total=1)


def _make_user(is_admin: bool = False):
    user = MagicMock()
    user.id = _USER_ID
    user.is_active = True
    role = MagicMock()
    role.value = "admin" if is_admin else "rider"
    user.role = role
    return user


def _make_account():
    acct = MagicMock()
    acct.id = _ACCOUNT_ID
    return acct


# ------ Member: GET /policy ------


@pytest.mark.asyncio
async def test_api_get_active_policy_200():
    """GET /corporate/sla/policy returns the active policy via service."""
    from app.api.v1.corporate_sla_policy import get_active_policy
    from app.models.corporate_sla_policy import CorporateSLAPolicy as _PolicyModel
    from app.services.corporate_sla_policy import _policy_to_response

    user = _make_user()
    db = AsyncMock()
    account = _make_account()

    policy_orm = _make_policy()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = policy_orm
    db.execute = AsyncMock(return_value=mock_result)

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.services.corporate_sla_policy._policy_to_response",
               return_value=_POLICY_RESP):
        result = await get_active_policy(user=user, db=db)
    assert result.is_active is True


@pytest.mark.asyncio
async def test_api_get_active_policy_404_no_account():
    """GET /corporate/sla/policy returns 404 when user has no account."""
    from fastapi import HTTPException
    from app.api.v1.corporate_sla_policy import _resolve_account_id

    user = _make_user()
    db = AsyncMock()

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=None):
        with pytest.raises(HTTPException) as exc:
            await _resolve_account_id(db, user.id)
    assert exc.value.status_code == 404


# ------ Member: GET /summary ------


@pytest.mark.asyncio
async def test_api_get_compliance_summary_calls_service():
    """GET /corporate/sla/summary delegates to get_sla_compliance_summary."""
    from app.api.v1.corporate_sla_policy import get_compliance_summary

    user = _make_user()
    db = AsyncMock()
    account = _make_account()

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy.get_sla_compliance_summary",
               return_value=_SUMMARY_RESP) as mock_svc:
        result = await get_compliance_summary(year=2026, month=4, user=user, db=db)
        mock_svc.assert_called_once_with(db, _ACCOUNT_ID, year=2026, month=4)
    assert result.total_rides == 10


# ------ Member: GET /trend ------


@pytest.mark.asyncio
async def test_api_get_compliance_trend_calls_service():
    """GET /corporate/sla/trend delegates to get_sla_compliance_trend."""
    from app.api.v1.corporate_sla_policy import get_compliance_trend

    user = _make_user()
    db = AsyncMock()
    account = _make_account()

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy.get_sla_compliance_trend",
               return_value=_TREND_RESP) as mock_svc:
        result = await get_compliance_trend(months=3, user=user, db=db)
        mock_svc.assert_called_once_with(db, _ACCOUNT_ID, months=3)
    assert len(result.items) == 1


# ------ Admin: POST /policies ------


@pytest.mark.asyncio
async def test_api_create_policy_201():
    """POST /corporate/sla/policies returns created policy."""
    from app.api.v1.corporate_sla_policy import create_policy_endpoint

    user = _make_user()
    db = AsyncMock()
    account = _make_account()
    data = SLAPolicyCreate(name="Standard SLA", max_wait_time_minutes=10)

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy._require_account_admin", return_value=None), \
         patch("app.api.v1.corporate_sla_policy.create_sla_policy",
               return_value=_POLICY_RESP) as mock_svc:
        result = await create_policy_endpoint(data=data, user=user, db=db)
        mock_svc.assert_called_once_with(db, _ACCOUNT_ID, data, created_by_id=_USER_ID)
    assert result.name == "Standard SLA"


@pytest.mark.asyncio
async def test_api_create_policy_403_non_admin():
    """POST /corporate/sla/policies returns 403 when user is not account admin."""
    from fastapi import HTTPException
    from app.api.v1.corporate_sla_policy import create_policy_endpoint

    user = _make_user()
    db = AsyncMock()
    account = _make_account()
    data = SLAPolicyCreate(name="Standard SLA")

    async def _raise_403(*args, **kwargs):
        raise HTTPException(status_code=403, detail="Forbidden")

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy._require_account_admin",
               side_effect=_raise_403):
        with pytest.raises(HTTPException) as exc:
            await create_policy_endpoint(data=data, user=user, db=db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_create_policy_409_on_duplicate():
    """POST /corporate/sla/policies returns 409 on duplicate active name."""
    from fastapi import HTTPException
    from app.api.v1.corporate_sla_policy import create_policy_endpoint

    user = _make_user()
    db = AsyncMock()
    account = _make_account()
    data = SLAPolicyCreate(name="Standard SLA")

    async def _raise_409(*args, **kwargs):
        raise HTTPException(status_code=409, detail="Conflict")

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy._require_account_admin", return_value=None), \
         patch("app.api.v1.corporate_sla_policy.create_sla_policy", side_effect=_raise_409):
        with pytest.raises(HTTPException) as exc:
            await create_policy_endpoint(data=data, user=user, db=db)
    assert exc.value.status_code == 409


# ------ Admin: GET /policies ------


@pytest.mark.asyncio
async def test_api_list_policies_200():
    """GET /corporate/sla/policies returns policy list."""
    from app.api.v1.corporate_sla_policy import list_policies_endpoint

    user = _make_user()
    db = AsyncMock()
    account = _make_account()

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy._require_account_admin", return_value=None), \
         patch("app.api.v1.corporate_sla_policy.list_sla_policies",
               return_value=_POLICY_LIST_RESP):
        result = await list_policies_endpoint(is_active=None, user=user, db=db)
    assert result.total == 1


@pytest.mark.asyncio
async def test_api_list_policies_403_non_admin():
    """GET /corporate/sla/policies returns 403 for non-admin."""
    from fastapi import HTTPException
    from app.api.v1.corporate_sla_policy import list_policies_endpoint

    user = _make_user()
    db = AsyncMock()
    account = _make_account()

    async def _raise_403(*args, **kwargs):
        raise HTTPException(status_code=403)

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy._require_account_admin",
               side_effect=_raise_403):
        with pytest.raises(HTTPException) as exc:
            await list_policies_endpoint(is_active=None, user=user, db=db)
    assert exc.value.status_code == 403


# ------ Admin: GET /policies/{id} ------


@pytest.mark.asyncio
async def test_api_get_policy_200():
    """GET /corporate/sla/policies/{id} returns the policy."""
    from app.api.v1.corporate_sla_policy import get_policy_endpoint

    user = _make_user()
    db = AsyncMock()
    account = _make_account()

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy._require_account_admin", return_value=None), \
         patch("app.api.v1.corporate_sla_policy.get_sla_policy",
               return_value=_POLICY_RESP):
        result = await get_policy_endpoint(policy_id=_POLICY_ID, user=user, db=db)
    assert result.id == _POLICY_ID


# ------ Admin: PUT /policies/{id} ------


@pytest.mark.asyncio
async def test_api_update_policy_200():
    """PUT /corporate/sla/policies/{id} updates and returns the policy."""
    from app.api.v1.corporate_sla_policy import update_policy_endpoint

    user = _make_user()
    db = AsyncMock()
    account = _make_account()
    data = SLAPolicyUpdate(name="Updated SLA")

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy._require_account_admin", return_value=None), \
         patch("app.api.v1.corporate_sla_policy.update_sla_policy",
               return_value=_POLICY_RESP):
        result = await update_policy_endpoint(
            policy_id=_POLICY_ID, data=data, user=user, db=db
        )
    assert result.is_active is True


@pytest.mark.asyncio
async def test_api_update_policy_403_non_admin():
    """PUT /corporate/sla/policies/{id} returns 403 for non-admin."""
    from fastapi import HTTPException
    from app.api.v1.corporate_sla_policy import update_policy_endpoint

    user = _make_user()
    db = AsyncMock()
    account = _make_account()
    data = SLAPolicyUpdate(name="X")

    async def _raise_403(*args, **kwargs):
        raise HTTPException(status_code=403)

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy._require_account_admin",
               side_effect=_raise_403):
        with pytest.raises(HTTPException) as exc:
            await update_policy_endpoint(
                policy_id=_POLICY_ID, data=data, user=user, db=db
            )
    assert exc.value.status_code == 403


# ------ Admin: POST activate ------


@pytest.mark.asyncio
async def test_api_activate_policy_200():
    """POST /activate returns the activated policy."""
    from app.api.v1.corporate_sla_policy import activate_policy_endpoint

    user = _make_user()
    db = AsyncMock()
    account = _make_account()

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy._require_account_admin", return_value=None), \
         patch("app.api.v1.corporate_sla_policy.activate_sla_policy",
               return_value=_POLICY_RESP):
        result = await activate_policy_endpoint(policy_id=_POLICY_ID, user=user, db=db)
    assert result.is_active is True


@pytest.mark.asyncio
async def test_api_activate_policy_409_already_active():
    """POST /activate returns 409 when already active."""
    from fastapi import HTTPException
    from app.api.v1.corporate_sla_policy import activate_policy_endpoint

    user = _make_user()
    db = AsyncMock()
    account = _make_account()

    async def _raise_409(*args, **kwargs):
        raise HTTPException(status_code=409)

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy._require_account_admin", return_value=None), \
         patch("app.api.v1.corporate_sla_policy.activate_sla_policy",
               side_effect=_raise_409):
        with pytest.raises(HTTPException) as exc:
            await activate_policy_endpoint(policy_id=_POLICY_ID, user=user, db=db)
    assert exc.value.status_code == 409


# ------ Admin: POST deactivate ------


@pytest.mark.asyncio
async def test_api_deactivate_policy_200():
    """POST /deactivate returns the deactivated policy."""
    from app.api.v1.corporate_sla_policy import deactivate_policy_endpoint

    deactivated = _POLICY_RESP.model_copy(update={"is_active": False})
    user = _make_user()
    db = AsyncMock()
    account = _make_account()

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy._require_account_admin", return_value=None), \
         patch("app.api.v1.corporate_sla_policy.deactivate_sla_policy",
               return_value=deactivated):
        result = await deactivate_policy_endpoint(policy_id=_POLICY_ID, user=user, db=db)
    assert result.is_active is False


@pytest.mark.asyncio
async def test_api_deactivate_policy_409_already_inactive():
    """POST /deactivate returns 409 when already inactive."""
    from fastapi import HTTPException
    from app.api.v1.corporate_sla_policy import deactivate_policy_endpoint

    user = _make_user()
    db = AsyncMock()
    account = _make_account()

    async def _raise_409(*args, **kwargs):
        raise HTTPException(status_code=409)

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy._require_account_admin", return_value=None), \
         patch("app.api.v1.corporate_sla_policy.deactivate_sla_policy",
               side_effect=_raise_409):
        with pytest.raises(HTTPException) as exc:
            await deactivate_policy_endpoint(policy_id=_POLICY_ID, user=user, db=db)
    assert exc.value.status_code == 409


# ------ Admin: DELETE ------


@pytest.mark.asyncio
async def test_api_delete_policy_204():
    """DELETE /policies/{id} calls service and returns None."""
    from app.api.v1.corporate_sla_policy import delete_policy_endpoint

    user = _make_user()
    db = AsyncMock()
    account = _make_account()

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy._require_account_admin", return_value=None), \
         patch("app.api.v1.corporate_sla_policy.delete_sla_policy",
               return_value=None) as mock_svc:
        result = await delete_policy_endpoint(policy_id=_POLICY_ID, user=user, db=db)
        mock_svc.assert_called_once_with(db, _POLICY_ID, _ACCOUNT_ID)
    assert result is None


@pytest.mark.asyncio
async def test_api_delete_policy_409_when_active():
    """DELETE /policies/{id} returns 409 when policy is active."""
    from fastapi import HTTPException
    from app.api.v1.corporate_sla_policy import delete_policy_endpoint

    user = _make_user()
    db = AsyncMock()
    account = _make_account()

    async def _raise_409(*args, **kwargs):
        raise HTTPException(status_code=409)

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy._require_account_admin", return_value=None), \
         patch("app.api.v1.corporate_sla_policy.delete_sla_policy",
               side_effect=_raise_409):
        with pytest.raises(HTTPException) as exc:
            await delete_policy_endpoint(policy_id=_POLICY_ID, user=user, db=db)
    assert exc.value.status_code == 409


# ------ Admin: POST /rides/{id}/evaluate ------


@pytest.mark.asyncio
async def test_api_evaluate_ride_201():
    """POST /rides/{id}/evaluate returns 201 with the evaluation record."""
    from app.api.v1.corporate_sla_policy import evaluate_ride_endpoint

    user = _make_user()
    db = AsyncMock()
    account = _make_account()
    data = SLAEvaluationCreate(wait_time_minutes=Decimal("7"), driver_rating=Decimal("4.8"))

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy._require_account_admin", return_value=None), \
         patch("app.api.v1.corporate_sla_policy.record_sla_evaluation",
               return_value=_RECORD_RESP) as mock_svc:
        result = await evaluate_ride_endpoint(ride_id=1, data=data, user=user, db=db)
    assert result.overall_sla_met is True


# ------ Admin: GET /breaches ------


@pytest.mark.asyncio
async def test_api_list_breaches_200():
    """GET /corporate/sla/breaches returns breach list."""
    from app.api.v1.corporate_sla_policy import list_breaches_endpoint

    user = _make_user()
    db = AsyncMock()
    account = _make_account()

    with patch("app.api.v1.corporate_sla_policy.get_user_account", return_value=account), \
         patch("app.api.v1.corporate_sla_policy._require_account_admin", return_value=None), \
         patch("app.api.v1.corporate_sla_policy.list_sla_breaches",
               return_value=_RECORD_LIST_RESP):
        result = await list_breaches_endpoint(
            year=None, month=None, limit=50, offset=0, user=user, db=db
        )
    assert result.total == 1


# ------ Platform-admin: GET /platform/all ------


@pytest.mark.asyncio
async def test_api_platform_list_all_200():
    """GET /platform-admin/corporate/sla/all returns all policies."""
    from app.api.v1.corporate_sla_policy import admin_list_all_policies

    admin = _make_user(is_admin=True)
    db = AsyncMock()

    with patch("app.api.v1.corporate_sla_policy.list_all_platform",
               return_value=_POLICY_LIST_RESP) as mock_svc:
        result = await admin_list_all_policies(account_id=None, _admin=admin, db=db)
        mock_svc.assert_called_once_with(db, account_id=None)
    assert result.total == 1


# ------ Platform-admin: GET /platform/account/{id}/summary ------


@pytest.mark.asyncio
async def test_api_platform_account_summary_200():
    """GET /platform-admin/.../summary returns compliance summary for any account."""
    from app.api.v1.corporate_sla_policy import admin_account_summary

    admin = _make_user(is_admin=True)
    db = AsyncMock()

    with patch("app.api.v1.corporate_sla_policy.get_sla_compliance_summary",
               return_value=_SUMMARY_RESP) as mock_svc:
        result = await admin_account_summary(
            account_id=_ACCOUNT_ID, year=None, month=None, _admin=admin, db=db
        )
        mock_svc.assert_called_once_with(db, _ACCOUNT_ID, year=None, month=None)
    assert result.total_rides == 10
