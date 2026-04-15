"""Tests for the Corporate Policy Violation Tracking feature.

Schema tests (sync):
  1.  ViolationType — all 8 values defined
  2.  ViolationCreate — valid payload (minimal)
  3.  ViolationCreate — valid payload with all optional fields
  4.  AcknowledgeRequest — all optional
  5.  AcknowledgeRequest — note max_length enforced
  6.  BulkAcknowledgeRequest — valid list of IDs
  7.  BulkAcknowledgeRequest — empty list raises ValidationError
  8.  BulkAcknowledgeRequest — list over 100 raises ValidationError
  9.  ViolationResponse — from_attributes
  10. ViolationListResponse — structure
  11. TopOffender — structure
  12. ViolationSummaryResponse — all fields present

Service tests (async, mocked DB):
  13. record_violation — success creates row
  14. record_violation — with all optional fields
  15. get_violation — returns violation
  16. get_violation — not found raises 404
  17. get_violation — wrong account raises 404
  18. list_violations — returns violations for account
  19. list_violations — filtered by member_id
  20. list_violations — filtered by violation_type
  21. list_violations — filtered by is_acknowledged False
  22. list_violations — filtered by is_acknowledged True
  23. acknowledge_violation — success sets fields
  24. acknowledge_violation — not found raises 404
  25. acknowledge_violation — already acknowledged raises 409
  26. bulk_acknowledge_violations — acknowledges matching unacked rows
  27. bulk_acknowledge_violations — already acknowledged rows skipped
  28. bulk_acknowledge_violations — returns empty list when none match
  29. get_violation_summary — counts by type and top offenders
  30. get_violation_summary — empty period returns zeros
  31. list_all_violations — returns all without filter
  32. list_all_violations — filtered by account_id
  33. list_all_violations — filtered by violation_type

API layer tests (endpoint functions called directly):
  34. GET  /corporate/accounts/me/violations — 200 member
  35. GET  /corporate/accounts/me/violations — 404 not a member
  36. GET  /corporate/accounts/{id}/violations — 200 admin
  37. GET  /corporate/accounts/{id}/violations/summary — 200 admin
  38. GET  /corporate/accounts/{id}/violations/{id} — 200 admin
  39. GET  /corporate/accounts/{id}/violations/{id} — 404 propagated
  40. POST /corporate/accounts/{id}/violations/{id}/acknowledge — 200
  41. POST /corporate/accounts/{id}/violations/{id}/acknowledge — 409 propagated
  42. POST /corporate/accounts/{id}/violations/bulk-acknowledge — 200
  43. GET  /admin/corporate/violations — 200 platform-admin
  44. GET  /admin/corporate/violations — filtered by violation_type
  45. POST /admin/corporate/{id}/violations — 201 platform-admin
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_policy_violation import CorporatePolicyViolation
from app.schemas.corporate_policy_violation import (
    AcknowledgeRequest,
    BulkAcknowledgeRequest,
    TopOffender,
    ViolationCreate,
    ViolationListResponse,
    ViolationResponse,
    ViolationSummaryResponse,
    ViolationType,
)
from app.services.corporate_policy_violation import (
    acknowledge_violation,
    bulk_acknowledge_violations,
    get_violation,
    get_violation_summary,
    list_all_violations,
    list_violations,
    record_violation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)

ACCOUNT_ID = 10
MEMBER_ID = 20
ADMIN_ID = 99
VIOLATION_ID = 1


def _make_violation(
    vid: int = VIOLATION_ID,
    account_id: int = ACCOUNT_ID,
    member_id: int = MEMBER_ID,
    violation_type: str = "vehicle_type",
    is_acknowledged: bool = False,
    acknowledged_by_id: int | None = None,
    acknowledged_at: datetime | None = None,
    acknowledgement_note: str | None = None,
    ride_id: int | None = None,
    violation_details: dict | None = None,
    policy_snapshot: dict | None = None,
) -> CorporatePolicyViolation:
    v = CorporatePolicyViolation()
    v.id = vid
    v.account_id = account_id
    v.member_id = member_id
    v.ride_id = ride_id
    v.violation_type = violation_type
    v.violation_details = violation_details
    v.policy_snapshot = policy_snapshot
    v.is_acknowledged = is_acknowledged
    v.acknowledged_by_id = acknowledged_by_id
    v.acknowledged_at = acknowledged_at
    v.acknowledgement_note = acknowledgement_note
    v.created_at = _NOW
    return v


def _make_violation_response(**kwargs) -> ViolationResponse:
    defaults = dict(
        id=VIOLATION_ID,
        account_id=ACCOUNT_ID,
        member_id=MEMBER_ID,
        ride_id=None,
        violation_type="vehicle_type",
        violation_details=None,
        policy_snapshot=None,
        is_acknowledged=False,
        acknowledged_by_id=None,
        acknowledged_at=None,
        acknowledgement_note=None,
        created_at=_NOW,
    )
    defaults.update(kwargs)
    return ViolationResponse(**defaults)


def _make_db(
    scalar_one: CorporatePolicyViolation | None = None,
    scalars_all: list | None = None,
) -> AsyncMock:
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_one
    mock_result.scalars.return_value.all.return_value = scalars_all or []
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


def _populate_violation(template: CorporatePolicyViolation):
    def _side_effect(obj):
        obj.id = template.id
        obj.created_at = template.created_at
        obj.is_acknowledged = template.is_acknowledged
    return _side_effect


def _mock_user(user_id: int = ADMIN_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


# ===========================================================================
# 1–12  Schema tests
# ===========================================================================


def test_violation_type_all_values():
    """ViolationType — all 8 values defined."""
    expected = {
        "vehicle_type",
        "per_ride_cost_exceeded",
        "business_hours",
        "missing_purpose",
        "unapproved_purpose",
        "spend_limit_exceeded",
        "ride_quota_exceeded",
        "blackout_period",
    }
    assert {v.value for v in ViolationType} == expected


def test_violation_create_minimal():
    """ViolationCreate — valid payload (minimal)."""
    vc = ViolationCreate(member_id=5, violation_type=ViolationType.vehicle_type)
    assert vc.member_id == 5
    assert vc.violation_type == ViolationType.vehicle_type
    assert vc.violation_details is None
    assert vc.ride_id is None
    assert vc.policy_snapshot is None


def test_violation_create_full():
    """ViolationCreate — valid payload with all optional fields."""
    vc = ViolationCreate(
        member_id=5,
        violation_type=ViolationType.per_ride_cost_exceeded,
        violation_details={"attempted_fare_usd": 55.0, "max_per_ride_usd": 40.0},
        ride_id=101,
        policy_snapshot={"max_per_ride_usd": "40.00"},
    )
    assert vc.ride_id == 101
    assert vc.violation_details["attempted_fare_usd"] == 55.0


def test_acknowledge_request_all_optional():
    """AcknowledgeRequest — all optional."""
    req = AcknowledgeRequest()
    assert req.acknowledgement_note is None

    req2 = AcknowledgeRequest(acknowledgement_note="reviewed and resolved")
    assert req2.acknowledgement_note == "reviewed and resolved"


def test_acknowledge_request_note_max_length():
    """AcknowledgeRequest — note max_length enforced."""
    with pytest.raises(ValidationError):
        AcknowledgeRequest(acknowledgement_note="x" * 2001)


def test_bulk_acknowledge_request_valid():
    """BulkAcknowledgeRequest — valid list of IDs."""
    req = BulkAcknowledgeRequest(violation_ids=[1, 2, 3])
    assert req.violation_ids == [1, 2, 3]
    assert req.acknowledgement_note is None


def test_bulk_acknowledge_request_empty_raises():
    """BulkAcknowledgeRequest — empty list raises ValidationError."""
    with pytest.raises(ValidationError):
        BulkAcknowledgeRequest(violation_ids=[])


def test_bulk_acknowledge_request_over_100_raises():
    """BulkAcknowledgeRequest — list over 100 raises ValidationError."""
    with pytest.raises(ValidationError):
        BulkAcknowledgeRequest(violation_ids=list(range(101)))


def test_violation_response_from_attributes():
    """ViolationResponse — from_attributes."""
    v = _make_violation()
    resp = ViolationResponse.model_validate(v)
    assert resp.id == VIOLATION_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.violation_type == "vehicle_type"
    assert resp.is_acknowledged is False
    assert resp.acknowledged_by_id is None


def test_violation_list_response_structure():
    """ViolationListResponse — structure."""
    lr = ViolationListResponse(violations=[], total=0)
    assert lr.total == 0
    assert lr.violations == []


def test_top_offender_structure():
    """TopOffender — structure."""
    to = TopOffender(member_id=5, count=3)
    assert to.member_id == 5
    assert to.count == 3


def test_violation_summary_response_all_fields():
    """ViolationSummaryResponse — all fields present."""
    sr = ViolationSummaryResponse(
        total_violations=10,
        unacknowledged=4,
        by_type={"vehicle_type": 5, "business_hours": 5},
        top_offenders=[TopOffender(member_id=MEMBER_ID, count=3)],
        period_days=30,
    )
    assert sr.total_violations == 10
    assert sr.unacknowledged == 4
    assert sr.by_type["vehicle_type"] == 5
    assert len(sr.top_offenders) == 1
    assert sr.period_days == 30


# ===========================================================================
# 13–33  Service tests
# ===========================================================================


@pytest.mark.asyncio
async def test_record_violation_success():
    """record_violation — success creates row."""
    violation_row = _make_violation()
    db = _make_db()
    db.refresh.side_effect = _populate_violation(violation_row)

    result = await record_violation(
        db,
        account_id=ACCOUNT_ID,
        member_id=MEMBER_ID,
        violation_type="vehicle_type",
    )

    db.add.assert_called_once()
    db.commit.assert_called_once()
    assert result.violation_type == "vehicle_type"
    assert result.is_acknowledged is False


@pytest.mark.asyncio
async def test_record_violation_with_all_fields():
    """record_violation — with all optional fields."""
    violation_row = _make_violation(
        ride_id=55,
        violation_details={"attempted": "xl", "allowed": ["standard"]},
        policy_snapshot={"allowed_vehicle_categories": ["standard"]},
    )
    db = _make_db()
    db.refresh.side_effect = _populate_violation(violation_row)

    result = await record_violation(
        db,
        account_id=ACCOUNT_ID,
        member_id=MEMBER_ID,
        violation_type="vehicle_type",
        violation_details={"attempted": "xl", "allowed": ["standard"]},
        ride_id=55,
        policy_snapshot={"allowed_vehicle_categories": ["standard"]},
    )

    db.add.assert_called_once()
    # violation row fields are set on the instance passed to db.add
    added_obj = db.add.call_args[0][0]
    assert added_obj.ride_id == 55
    assert added_obj.violation_details is not None


@pytest.mark.asyncio
async def test_get_violation_returns_violation():
    """get_violation — returns violation."""
    violation_row = _make_violation()
    db = _make_db(scalar_one=violation_row)

    result = await get_violation(db, violation_id=VIOLATION_ID, account_id=ACCOUNT_ID)

    assert result.id == VIOLATION_ID
    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_get_violation_not_found_raises_404():
    """get_violation — not found raises 404."""
    db = _make_db(scalar_one=None)

    with pytest.raises(HTTPException) as exc_info:
        await get_violation(db, violation_id=999, account_id=ACCOUNT_ID)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_violation_wrong_account_raises_404():
    """get_violation — wrong account raises 404 (DB query scoped by account)."""
    # When the DB returns None (account scope filtered out the row), we 404
    db = _make_db(scalar_one=None)

    with pytest.raises(HTTPException) as exc_info:
        await get_violation(db, violation_id=VIOLATION_ID, account_id=999)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_violations_returns_rows():
    """list_violations — returns violations for account."""
    rows = [_make_violation(vid=1), _make_violation(vid=2)]
    db = _make_db(scalars_all=rows)

    result = await list_violations(db, ACCOUNT_ID)

    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_violations_filtered_by_member():
    """list_violations — filtered by member_id."""
    rows = [_make_violation()]
    db = _make_db(scalars_all=rows)

    result = await list_violations(db, ACCOUNT_ID, member_id=MEMBER_ID)

    assert len(result) == 1
    assert result[0].member_id == MEMBER_ID


@pytest.mark.asyncio
async def test_list_violations_filtered_by_type():
    """list_violations — filtered by violation_type."""
    rows = [_make_violation(violation_type="business_hours")]
    db = _make_db(scalars_all=rows)

    result = await list_violations(db, ACCOUNT_ID, violation_type="business_hours")

    assert len(result) == 1
    assert result[0].violation_type == "business_hours"


@pytest.mark.asyncio
async def test_list_violations_unacknowledged_filter():
    """list_violations — filtered by is_acknowledged False."""
    rows = [_make_violation(is_acknowledged=False)]
    db = _make_db(scalars_all=rows)

    result = await list_violations(db, ACCOUNT_ID, is_acknowledged=False)

    assert len(result) == 1
    assert result[0].is_acknowledged is False


@pytest.mark.asyncio
async def test_list_violations_acknowledged_filter():
    """list_violations — filtered by is_acknowledged True."""
    rows = [_make_violation(is_acknowledged=True, acknowledged_by_id=ADMIN_ID)]
    db = _make_db(scalars_all=rows)

    result = await list_violations(db, ACCOUNT_ID, is_acknowledged=True)

    assert len(result) == 1
    assert result[0].is_acknowledged is True


@pytest.mark.asyncio
async def test_acknowledge_violation_success():
    """acknowledge_violation — success sets fields."""
    violation_row = _make_violation(is_acknowledged=False)
    db = _make_db(scalar_one=violation_row)

    result = await acknowledge_violation(
        db,
        violation_id=VIOLATION_ID,
        account_id=ACCOUNT_ID,
        acknowledged_by_id=ADMIN_ID,
        note="Reviewed — policy reminder sent to employee.",
    )

    assert violation_row.is_acknowledged is True
    assert violation_row.acknowledged_by_id == ADMIN_ID
    assert violation_row.acknowledged_at is not None
    assert violation_row.acknowledgement_note == "Reviewed — policy reminder sent to employee."
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_acknowledge_violation_not_found_raises_404():
    """acknowledge_violation — not found raises 404."""
    db = _make_db(scalar_one=None)

    with pytest.raises(HTTPException) as exc_info:
        await acknowledge_violation(
            db,
            violation_id=999,
            account_id=ACCOUNT_ID,
            acknowledged_by_id=ADMIN_ID,
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_acknowledge_violation_already_acknowledged_raises_409():
    """acknowledge_violation — already acknowledged raises 409."""
    violation_row = _make_violation(is_acknowledged=True)
    db = _make_db(scalar_one=violation_row)

    with pytest.raises(HTTPException) as exc_info:
        await acknowledge_violation(
            db,
            violation_id=VIOLATION_ID,
            account_id=ACCOUNT_ID,
            acknowledged_by_id=ADMIN_ID,
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_bulk_acknowledge_violations_success():
    """bulk_acknowledge_violations — acknowledges matching unacked rows."""
    rows = [
        _make_violation(vid=1, is_acknowledged=False),
        _make_violation(vid=2, is_acknowledged=False),
    ]
    db = _make_db(scalars_all=rows)

    result = await bulk_acknowledge_violations(
        db,
        account_id=ACCOUNT_ID,
        violation_ids=[1, 2],
        acknowledged_by_id=ADMIN_ID,
        note="bulk review",
    )

    assert len(result) == 2
    for row in rows:
        assert row.is_acknowledged is True
        assert row.acknowledged_by_id == ADMIN_ID
        assert row.acknowledgement_note == "bulk review"
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_bulk_acknowledge_violations_already_acked_skipped():
    """bulk_acknowledge_violations — already acknowledged rows skipped."""
    # DB returns only unacked rows (service filters is_acknowledged=False)
    rows = []  # All were already acked — DB returns empty
    db = _make_db(scalars_all=rows)

    result = await bulk_acknowledge_violations(
        db,
        account_id=ACCOUNT_ID,
        violation_ids=[1, 2, 3],
        acknowledged_by_id=ADMIN_ID,
    )

    assert result == []
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_bulk_acknowledge_violations_empty_returns_empty():
    """bulk_acknowledge_violations — returns empty list when none match."""
    db = _make_db(scalars_all=[])

    result = await bulk_acknowledge_violations(
        db,
        account_id=ACCOUNT_ID,
        violation_ids=[999, 998],
        acknowledged_by_id=ADMIN_ID,
    )

    assert result == []


@pytest.mark.asyncio
async def test_get_violation_summary_with_data():
    """get_violation_summary — counts by type and top offenders."""
    rows = [
        _make_violation(vid=1, violation_type="vehicle_type", is_acknowledged=False),
        _make_violation(vid=2, violation_type="vehicle_type", is_acknowledged=True),
        _make_violation(
            vid=3,
            violation_type="business_hours",
            is_acknowledged=False,
            member_id=30,
        ),
        _make_violation(
            vid=4,
            violation_type="business_hours",
            is_acknowledged=False,
            member_id=MEMBER_ID,
        ),
    ]
    db = _make_db(scalars_all=rows)

    result = await get_violation_summary(db, account_id=ACCOUNT_ID, period_days=30)

    assert result.total_violations == 4
    assert result.unacknowledged == 3
    assert result.by_type["vehicle_type"] == 2
    assert result.by_type["business_hours"] == 2
    assert result.period_days == 30
    # Top offenders — MEMBER_ID has 2 violations (rows 1, 2, 4), member 30 has 1
    member_counts = {to.member_id: to.count for to in result.top_offenders}
    assert member_counts[MEMBER_ID] == 3


@pytest.mark.asyncio
async def test_get_violation_summary_empty():
    """get_violation_summary — empty period returns zeros."""
    db = _make_db(scalars_all=[])

    result = await get_violation_summary(db, account_id=ACCOUNT_ID, period_days=7)

    assert result.total_violations == 0
    assert result.unacknowledged == 0
    assert result.by_type == {}
    assert result.top_offenders == []


@pytest.mark.asyncio
async def test_list_all_violations_no_filter():
    """list_all_violations — returns all without filter."""
    rows = [
        _make_violation(vid=1, account_id=ACCOUNT_ID),
        _make_violation(vid=2, account_id=50),
    ]
    db = _make_db(scalars_all=rows)

    result = await list_all_violations(db)

    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_all_violations_filtered_by_account():
    """list_all_violations — filtered by account_id."""
    rows = [_make_violation(vid=1, account_id=ACCOUNT_ID)]
    db = _make_db(scalars_all=rows)

    result = await list_all_violations(db, account_id=ACCOUNT_ID)

    assert len(result) == 1
    assert result[0].account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_list_all_violations_filtered_by_type():
    """list_all_violations — filtered by violation_type."""
    rows = [_make_violation(violation_type="missing_purpose")]
    db = _make_db(scalars_all=rows)

    result = await list_all_violations(db, violation_type="missing_purpose")

    assert len(result) == 1
    assert result[0].violation_type == "missing_purpose"


# ===========================================================================
# 34–45  API layer tests
# ===========================================================================

_ROUTER = "app.api.v1.corporate_policy_violations"


@pytest.mark.asyncio
async def test_api_member_list_own_violations_200():
    """GET /corporate/accounts/me/violations — 200 member."""
    from app.api.v1.corporate_policy_violations import member_list_own_violations

    user = _mock_user(user_id=MEMBER_ID)
    db = AsyncMock()
    mock_account = MagicMock()
    mock_account.id = ACCOUNT_ID
    violations = [_make_violation_response()]

    with patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=mock_account)), \
         patch(f"{_ROUTER}.list_violations", new=AsyncMock(return_value=violations)):
        result = await member_list_own_violations(
            is_acknowledged=None,
            limit=50,
            offset=0,
            user=user,
            db=db,
        )

    assert result.total == 1
    assert result.violations[0].violation_type == "vehicle_type"


@pytest.mark.asyncio
async def test_api_member_list_own_violations_not_member_404():
    """GET /corporate/accounts/me/violations — 404 not a member."""
    from app.api.v1.corporate_policy_violations import member_list_own_violations

    user = _mock_user(user_id=MEMBER_ID)
    db = AsyncMock()

    with patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc_info:
            await member_list_own_violations(
                is_acknowledged=None,
                limit=50,
                offset=0,
                user=user,
                db=db,
            )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_api_admin_list_violations_200():
    """GET /corporate/accounts/{id}/violations — 200 admin."""
    from app.api.v1.corporate_policy_violations import admin_list_violations

    user = _mock_user()
    db = AsyncMock()
    violations = [_make_violation_response(), _make_violation_response(id=2)]

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.list_violations", new=AsyncMock(return_value=violations)):
        result = await admin_list_violations(
            account_id=ACCOUNT_ID,
            member_id=None,
            violation_type=None,
            is_acknowledged=None,
            from_dt=None,
            to_dt=None,
            limit=100,
            offset=0,
            user=user,
            db=db,
        )

    assert result.total == 2


@pytest.mark.asyncio
async def test_api_admin_violation_summary_200():
    """GET /corporate/accounts/{id}/violations/summary — 200 admin."""
    from app.api.v1.corporate_policy_violations import admin_violation_summary

    user = _mock_user()
    db = AsyncMock()
    summary = ViolationSummaryResponse(
        total_violations=5,
        unacknowledged=3,
        by_type={"vehicle_type": 3, "business_hours": 2},
        top_offenders=[TopOffender(member_id=MEMBER_ID, count=5)],
        period_days=30,
    )

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.get_violation_summary", new=AsyncMock(return_value=summary)):
        result = await admin_violation_summary(
            account_id=ACCOUNT_ID, period_days=30, user=user, db=db
        )

    assert result.total_violations == 5
    assert result.unacknowledged == 3
    assert len(result.top_offenders) == 1


@pytest.mark.asyncio
async def test_api_admin_get_violation_200():
    """GET /corporate/accounts/{id}/violations/{id} — 200 admin."""
    from app.api.v1.corporate_policy_violations import admin_get_violation

    user = _mock_user()
    db = AsyncMock()
    expected = _make_violation_response()

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.get_violation", new=AsyncMock(return_value=expected)):
        result = await admin_get_violation(
            account_id=ACCOUNT_ID, violation_id=VIOLATION_ID, user=user, db=db
        )

    assert result.id == VIOLATION_ID


@pytest.mark.asyncio
async def test_api_admin_get_violation_404_propagated():
    """GET /corporate/accounts/{id}/violations/{id} — 404 propagated."""
    from app.api.v1.corporate_policy_violations import admin_get_violation

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.get_violation", new=AsyncMock(
             side_effect=HTTPException(status_code=404, detail="not found")
         )):
        with pytest.raises(HTTPException) as exc_info:
            await admin_get_violation(
                account_id=ACCOUNT_ID, violation_id=999, user=user, db=db
            )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_api_admin_acknowledge_violation_200():
    """POST /corporate/accounts/{id}/violations/{id}/acknowledge — 200."""
    from app.api.v1.corporate_policy_violations import admin_acknowledge_violation

    user = _mock_user()
    db = AsyncMock()
    payload = AcknowledgeRequest(acknowledgement_note="reviewed")
    acknowledged = _make_violation_response(
        is_acknowledged=True,
        acknowledged_by_id=ADMIN_ID,
        acknowledged_at=_NOW,
        acknowledgement_note="reviewed",
    )

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.acknowledge_violation", new=AsyncMock(return_value=acknowledged)):
        result = await admin_acknowledge_violation(
            account_id=ACCOUNT_ID,
            violation_id=VIOLATION_ID,
            payload=payload,
            user=user,
            db=db,
        )

    assert result.is_acknowledged is True
    assert result.acknowledgement_note == "reviewed"


@pytest.mark.asyncio
async def test_api_admin_acknowledge_violation_409_propagated():
    """POST /corporate/accounts/{id}/violations/{id}/acknowledge — 409 propagated."""
    from app.api.v1.corporate_policy_violations import admin_acknowledge_violation

    user = _mock_user()
    db = AsyncMock()
    payload = AcknowledgeRequest()

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.acknowledge_violation", new=AsyncMock(
             side_effect=HTTPException(status_code=409, detail="already acknowledged")
         )):
        with pytest.raises(HTTPException) as exc_info:
            await admin_acknowledge_violation(
                account_id=ACCOUNT_ID,
                violation_id=VIOLATION_ID,
                payload=payload,
                user=user,
                db=db,
            )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_api_admin_bulk_acknowledge_200():
    """POST /corporate/accounts/{id}/violations/bulk-acknowledge — 200."""
    from app.api.v1.corporate_policy_violations import admin_bulk_acknowledge_violations

    user = _mock_user()
    db = AsyncMock()
    payload = BulkAcknowledgeRequest(violation_ids=[1, 2, 3], acknowledgement_note="batch review")
    acknowledged = [
        _make_violation_response(id=1, is_acknowledged=True),
        _make_violation_response(id=2, is_acknowledged=True),
    ]

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.bulk_acknowledge_violations", new=AsyncMock(return_value=acknowledged)):
        result = await admin_bulk_acknowledge_violations(
            account_id=ACCOUNT_ID, payload=payload, user=user, db=db
        )

    assert result.total == 2
    assert all(v.is_acknowledged for v in result.violations)


@pytest.mark.asyncio
async def test_api_platform_admin_list_violations_200():
    """GET /admin/corporate/violations — 200 platform-admin."""
    from app.api.v1.corporate_policy_violations import platform_admin_list_violations

    admin = _mock_user()
    db = AsyncMock()
    violations = [_make_violation_response(), _make_violation_response(id=2, account_id=50)]

    with patch(f"{_ROUTER}.list_all_violations", new=AsyncMock(return_value=violations)):
        result = await platform_admin_list_violations(
            account_id=None,
            violation_type=None,
            is_acknowledged=None,
            limit=200,
            offset=0,
            _admin=admin,
            db=db,
        )

    assert result.total == 2


@pytest.mark.asyncio
async def test_api_platform_admin_list_violations_filtered_by_type():
    """GET /admin/corporate/violations — filtered by violation_type."""
    from app.api.v1.corporate_policy_violations import platform_admin_list_violations

    admin = _mock_user()
    db = AsyncMock()
    violations = [_make_violation_response(violation_type="blackout_period")]

    with patch(f"{_ROUTER}.list_all_violations", new=AsyncMock(return_value=violations)):
        result = await platform_admin_list_violations(
            account_id=None,
            violation_type=ViolationType.blackout_period,
            is_acknowledged=None,
            limit=200,
            offset=0,
            _admin=admin,
            db=db,
        )

    assert result.total == 1
    assert result.violations[0].violation_type == "blackout_period"


@pytest.mark.asyncio
async def test_api_platform_admin_record_violation_201():
    """POST /admin/corporate/{id}/violations — 201 platform-admin."""
    from app.api.v1.corporate_policy_violations import platform_admin_record_violation

    admin = _mock_user()
    db = AsyncMock()
    payload = ViolationCreate(
        member_id=MEMBER_ID,
        violation_type=ViolationType.spend_limit_exceeded,
        violation_details={"monthly_limit_usd": 200.0, "current_spend_usd": 205.0},
    )
    expected = _make_violation_response(
        violation_type="spend_limit_exceeded",
        violation_details={"monthly_limit_usd": 200.0, "current_spend_usd": 205.0},
    )

    with patch(f"{_ROUTER}.record_violation", new=AsyncMock(return_value=expected)):
        result = await platform_admin_record_violation(
            account_id=ACCOUNT_ID, payload=payload, admin=admin, db=db
        )

    assert result.violation_type == "spend_limit_exceeded"
    assert result.violation_details["monthly_limit_usd"] == 200.0
