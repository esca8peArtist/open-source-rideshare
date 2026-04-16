"""Tests for the Corporate Mileage Reimbursement feature.

Service tests (async, mocked DB):
  1.  get_or_create_policy — creates policy on first call
  2.  get_or_create_policy — returns existing policy on second call
  3.  update_policy — updates supplied fields
  4.  get_policy — 404 when absent
  5.  create_claim — success with computed amount_usd
  6.  create_claim — miles exceeds max → 422
  7.  get_claim — 404 when not in account
  8.  list_member_claims — returns member's claims
  9.  list_member_claims — status filter works
  10. update_claim — success when draft
  11. update_claim — 409 when not draft
  12. update_claim — recomputes amount_usd when miles changes
  13. submit_claim — auto-approves when under thresholds
  14. submit_claim — stays submitted when above threshold
  15. submit_claim — 409 if not draft
  16. submit_claim — 422 if trip purpose required but missing
  17. review_claim — approve sets status=approved
  18. review_claim — reject sets status=rejected
  19. review_claim — 409 if not submitted
  20. mark_claim_paid — success
  21. mark_claim_paid — 409 if not approved
  22. get_account_claim_summary — returns correct structure
  23. list_all_platform — returns all claims
  24. list_all_platform — account filter works

Schema tests (sync):
  25. MileagePolicyUpdateRequest — valid
  26. MileageClaimCreateRequest — valid
  27. MileageClaimCreateRequest — miles must be > 0
  28. MileageClaimReviewRequest — valid approve
  29. MileageClaimReviewRequest — invalid action raises error
  30. MileageClaimResponse — from_attributes works
  31. MileageClaimSummaryResponse — valid

API layer tests (services patched):
  32. GET  policy → 200
  33. PUT  policy → 200
  34. POST create claim → 201
  35. GET  my claims → 200
  36. GET  claim by id → 200
  37. PUT  update claim → 200
  38. PUT  update claim → 409
  39. POST submit → 200
  40. GET  all claims (admin) → 200
  41. GET  summary (admin) → 200
  42. POST review → 200
  43. POST paid → 200
  44. GET  platform admin → 200
  45. list_all_platform — status filter works
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate_mileage_reimbursement import (
    ClaimStatus,
    CorporateMileageClaim,
    CorporateMileagePolicy,
)
from app.schemas.corporate_mileage_reimbursement import (
    MileageClaimCreateRequest,
    MileageClaimListResponse,
    MileageClaimResponse,
    MileageClaimReviewRequest,
    MileageClaimSummaryResponse,
    MileagePolicyUpdateRequest,
)
from app.services.corporate_mileage_reimbursement import (
    create_claim,
    get_account_claim_summary,
    get_claim,
    get_or_create_policy,
    get_policy,
    list_all_platform,
    list_member_claims,
    mark_claim_paid,
    review_claim,
    submit_claim,
    update_claim,
    update_policy,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
_TODAY = date(2026, 4, 16)
_ACCOUNT_ID = 1
_MEMBER_ID = 5
_ADMIN_ID = 10
_CLAIM_ID = 42
_POLICY_ID = 7
_RATE = Decimal("0.6700")
_MILES = Decimal("50.00")
_AMOUNT = Decimal("33.50")  # 50 * 0.6700

_BASE = "/api/v1/corporate/accounts/me/mileage"
_ADMIN_BASE = "/api/v1/admin/corporate/accounts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_policy(
    id: int = _POLICY_ID,
    account_id: int = _ACCOUNT_ID,
    rate_per_mile: Decimal = _RATE,
    max_miles_per_claim: int | None = None,
    requires_approval_above_usd: Decimal | None = None,
    requires_approval_above_miles: int | None = None,
    require_trip_purpose: bool = False,
    is_active: bool = True,
    created_by_id: int | None = _ADMIN_ID,
) -> CorporateMileagePolicy:
    policy = CorporateMileagePolicy(
        id=id,
        account_id=account_id,
        rate_per_mile=rate_per_mile,
        max_miles_per_claim=max_miles_per_claim,
        requires_approval_above_usd=requires_approval_above_usd,
        requires_approval_above_miles=requires_approval_above_miles,
        require_trip_purpose=require_trip_purpose,
        is_active=is_active,
        created_by_id=created_by_id,
    )
    return policy


def _make_claim(
    id: int = _CLAIM_ID,
    account_id: int = _ACCOUNT_ID,
    member_id: int = _MEMBER_ID,
    trip_date: date = _TODAY,
    miles: Decimal = _MILES,
    rate_used_usd: Decimal = _RATE,
    amount_usd: Decimal = _AMOUNT,
    description: str = "Client visit",
    trip_purpose_id: int | None = None,
    cost_center_id: int | None = None,
    status: ClaimStatus = ClaimStatus.DRAFT,
    submitted_at: datetime | None = None,
    reviewed_by_id: int | None = None,
    reviewed_at: datetime | None = None,
    review_note: str | None = None,
    paid_at: datetime | None = None,
) -> CorporateMileageClaim:
    claim = CorporateMileageClaim(
        id=id,
        account_id=account_id,
        member_id=member_id,
        trip_date=trip_date,
        miles=miles,
        rate_used_usd=rate_used_usd,
        amount_usd=amount_usd,
        description=description,
        trip_purpose_id=trip_purpose_id,
        cost_center_id=cost_center_id,
        status=status,
        submitted_at=submitted_at,
        reviewed_by_id=reviewed_by_id,
        reviewed_at=reviewed_at,
        review_note=review_note,
        paid_at=paid_at,
    )
    return claim


def _mock_db_scalar(value) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    db.execute.return_value = result
    return db


def _mock_db_scalars(values: list) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    return db


_DUMMY_POLICY = _make_policy()
_DUMMY_CLAIM = _make_claim()


# ---------------------------------------------------------------------------
# Service: get_or_create_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_policy_creates_on_first_call():
    """get_or_create_policy creates a new policy when none exists."""
    db = _mock_db_scalar(None)
    policy = await get_or_create_policy(db, account_id=_ACCOUNT_ID, created_by_id=_ADMIN_ID)
    assert policy.account_id == _ACCOUNT_ID
    assert policy.rate_per_mile == Decimal("0.6700")
    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_get_or_create_policy_returns_existing():
    """get_or_create_policy returns existing policy without creating a new one."""
    existing = _make_policy()
    db = _mock_db_scalar(existing)
    policy = await get_or_create_policy(db, account_id=_ACCOUNT_ID, created_by_id=_ADMIN_ID)
    assert policy.id == _POLICY_ID
    db.add.assert_not_called()


# ---------------------------------------------------------------------------
# Service: update_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_policy_updates_fields():
    """update_policy updates supplied fields and returns policy."""
    existing = _make_policy()
    db = _mock_db_scalar(existing)
    policy = await update_policy(db, account_id=_ACCOUNT_ID, rate_per_mile=Decimal("0.7000"))
    assert policy.rate_per_mile == Decimal("0.7000")
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_update_policy_404_when_absent():
    """update_policy raises 404 when no policy exists for the account."""
    db = _mock_db_scalar(None)
    with pytest.raises(HTTPException) as exc_info:
        await update_policy(db, account_id=_ACCOUNT_ID, rate_per_mile=Decimal("0.7000"))
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: get_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_policy_404_when_absent():
    """get_policy raises 404 when no policy exists."""
    db = _mock_db_scalar(None)
    with pytest.raises(HTTPException) as exc_info:
        await get_policy(db, account_id=_ACCOUNT_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: create_claim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_claim_success():
    """create_claim computes amount_usd correctly and creates a draft claim."""
    policy = _make_policy(rate_per_mile=Decimal("0.6700"))
    db = _mock_db_scalar(policy)
    claim = await create_claim(
        db,
        account_id=_ACCOUNT_ID,
        member_id=_MEMBER_ID,
        trip_date=_TODAY,
        miles=Decimal("50"),
        description="Client visit",
    )
    assert claim.status == ClaimStatus.DRAFT
    assert claim.rate_used_usd == Decimal("0.6700")
    assert claim.amount_usd == Decimal("33.50")
    db.add.assert_called_once()
    db.flush.assert_called()


@pytest.mark.asyncio
async def test_create_claim_exceeds_max_raises_422():
    """create_claim raises 422 when miles exceed policy max_miles_per_claim."""
    policy = _make_policy(max_miles_per_claim=30)
    db = _mock_db_scalar(policy)
    with pytest.raises(HTTPException) as exc_info:
        await create_claim(
            db,
            account_id=_ACCOUNT_ID,
            member_id=_MEMBER_ID,
            trip_date=_TODAY,
            miles=Decimal("50"),
            description="Too far",
        )
    assert exc_info.value.status_code == 422
    assert "30" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Service: get_claim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_claim_404_when_not_found():
    """get_claim raises 404 when the claim does not exist in the account."""
    db = _mock_db_scalar(None)
    with pytest.raises(HTTPException) as exc_info:
        await get_claim(db, account_id=_ACCOUNT_ID, claim_id=_CLAIM_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service: list_member_claims
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_member_claims_returns_claims():
    """list_member_claims returns the member's claims."""
    claims = [_make_claim(), _make_claim(id=43, trip_date=date(2026, 4, 10))]
    db = _mock_db_scalars(claims)
    result = await list_member_claims(db, account_id=_ACCOUNT_ID, member_id=_MEMBER_ID)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_member_claims_status_filter():
    """list_member_claims respects the status_filter parameter."""
    claims = [_make_claim(status=ClaimStatus.SUBMITTED)]
    db = _mock_db_scalars(claims)
    result = await list_member_claims(
        db,
        account_id=_ACCOUNT_ID,
        member_id=_MEMBER_ID,
        status_filter=ClaimStatus.SUBMITTED,
    )
    assert len(result) == 1
    assert result[0].status == ClaimStatus.SUBMITTED


# ---------------------------------------------------------------------------
# Service: update_claim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_claim_success_when_draft():
    """update_claim updates fields on a draft claim."""
    claim = _make_claim(status=ClaimStatus.DRAFT)
    db = _mock_db_scalar(claim)
    updated = await update_claim(
        db,
        account_id=_ACCOUNT_ID,
        claim_id=_CLAIM_ID,
        description="Updated description",
    )
    assert updated.description == "Updated description"
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_update_claim_409_when_not_draft():
    """update_claim raises 409 when the claim is not in draft status."""
    claim = _make_claim(status=ClaimStatus.SUBMITTED)
    db = _mock_db_scalar(claim)
    with pytest.raises(HTTPException) as exc_info:
        await update_claim(db, account_id=_ACCOUNT_ID, claim_id=_CLAIM_ID, description="x")
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_update_claim_recomputes_amount_when_miles_changes():
    """update_claim recomputes amount_usd when miles is updated."""
    claim = _make_claim(
        status=ClaimStatus.DRAFT,
        miles=Decimal("50"),
        rate_used_usd=Decimal("0.6700"),
        amount_usd=Decimal("33.50"),
    )
    db = _mock_db_scalar(claim)
    updated = await update_claim(
        db,
        account_id=_ACCOUNT_ID,
        claim_id=_CLAIM_ID,
        miles=Decimal("100"),
    )
    assert updated.amount_usd == Decimal("67.00")


# ---------------------------------------------------------------------------
# Service: submit_claim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_claim_auto_approves_under_thresholds():
    """submit_claim auto-approves when amount and miles are within policy thresholds."""
    policy = _make_policy(
        requires_approval_above_usd=Decimal("100.00"),
        requires_approval_above_miles=200,
    )
    claim = _make_claim(
        status=ClaimStatus.DRAFT,
        miles=Decimal("50"),
        amount_usd=Decimal("33.50"),
    )

    db = AsyncMock()
    result_policy = MagicMock()
    result_policy.scalar_one_or_none.return_value = policy
    result_claim = MagicMock()
    result_claim.scalar_one_or_none.return_value = claim
    db.execute.side_effect = [result_claim, result_policy]

    updated = await submit_claim(db, account_id=_ACCOUNT_ID, claim_id=_CLAIM_ID, member_id=_MEMBER_ID)
    assert updated.status == ClaimStatus.APPROVED
    assert updated.submitted_at is not None


@pytest.mark.asyncio
async def test_submit_claim_stays_submitted_above_threshold():
    """submit_claim keeps status=submitted when amount exceeds the approval threshold."""
    policy = _make_policy(
        requires_approval_above_usd=Decimal("20.00"),
        requires_approval_above_miles=None,
    )
    claim = _make_claim(
        status=ClaimStatus.DRAFT,
        miles=Decimal("50"),
        amount_usd=Decimal("33.50"),
    )

    db = AsyncMock()
    result_claim = MagicMock()
    result_claim.scalar_one_or_none.return_value = claim
    result_policy = MagicMock()
    result_policy.scalar_one_or_none.return_value = policy
    db.execute.side_effect = [result_claim, result_policy]

    updated = await submit_claim(db, account_id=_ACCOUNT_ID, claim_id=_CLAIM_ID, member_id=_MEMBER_ID)
    assert updated.status == ClaimStatus.SUBMITTED


@pytest.mark.asyncio
async def test_submit_claim_409_if_not_draft():
    """submit_claim raises 409 when the claim is already submitted."""
    claim = _make_claim(status=ClaimStatus.SUBMITTED)
    db = _mock_db_scalar(claim)
    with pytest.raises(HTTPException) as exc_info:
        await submit_claim(db, account_id=_ACCOUNT_ID, claim_id=_CLAIM_ID, member_id=_MEMBER_ID)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_submit_claim_422_if_trip_purpose_required_but_missing():
    """submit_claim raises 422 when policy requires trip purpose but claim has none."""
    policy = _make_policy(require_trip_purpose=True)
    claim = _make_claim(status=ClaimStatus.DRAFT, trip_purpose_id=None)

    db = AsyncMock()
    result_claim = MagicMock()
    result_claim.scalar_one_or_none.return_value = claim
    result_policy = MagicMock()
    result_policy.scalar_one_or_none.return_value = policy
    db.execute.side_effect = [result_claim, result_policy]

    with pytest.raises(HTTPException) as exc_info:
        await submit_claim(db, account_id=_ACCOUNT_ID, claim_id=_CLAIM_ID, member_id=_MEMBER_ID)
    assert exc_info.value.status_code == 422
    assert "trip purpose" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# Service: review_claim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_claim_approve():
    """review_claim sets status=approved for action='approve'."""
    claim = _make_claim(status=ClaimStatus.SUBMITTED)
    db = _mock_db_scalar(claim)
    updated = await review_claim(
        db,
        account_id=_ACCOUNT_ID,
        claim_id=_CLAIM_ID,
        reviewer_id=_ADMIN_ID,
        action="approve",
        note="Looks good",
    )
    assert updated.status == ClaimStatus.APPROVED
    assert updated.reviewed_by_id == _ADMIN_ID
    assert updated.review_note == "Looks good"


@pytest.mark.asyncio
async def test_review_claim_reject():
    """review_claim sets status=rejected for action='reject'."""
    claim = _make_claim(status=ClaimStatus.SUBMITTED)
    db = _mock_db_scalar(claim)
    updated = await review_claim(
        db,
        account_id=_ACCOUNT_ID,
        claim_id=_CLAIM_ID,
        reviewer_id=_ADMIN_ID,
        action="reject",
        note="Missing receipt",
    )
    assert updated.status == ClaimStatus.REJECTED
    assert updated.review_note == "Missing receipt"


@pytest.mark.asyncio
async def test_review_claim_409_if_not_submitted():
    """review_claim raises 409 when the claim is not in submitted status."""
    claim = _make_claim(status=ClaimStatus.DRAFT)
    db = _mock_db_scalar(claim)
    with pytest.raises(HTTPException) as exc_info:
        await review_claim(
            db, account_id=_ACCOUNT_ID, claim_id=_CLAIM_ID, reviewer_id=_ADMIN_ID, action="approve"
        )
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service: mark_claim_paid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_claim_paid_success():
    """mark_claim_paid sets status=paid and records paid_at."""
    claim = _make_claim(status=ClaimStatus.APPROVED)
    db = _mock_db_scalar(claim)
    updated = await mark_claim_paid(
        db, account_id=_ACCOUNT_ID, claim_id=_CLAIM_ID, paid_by_id=_ADMIN_ID
    )
    assert updated.status == ClaimStatus.PAID
    assert updated.paid_at is not None


@pytest.mark.asyncio
async def test_mark_claim_paid_409_if_not_approved():
    """mark_claim_paid raises 409 when the claim is not approved."""
    claim = _make_claim(status=ClaimStatus.SUBMITTED)
    db = _mock_db_scalar(claim)
    with pytest.raises(HTTPException) as exc_info:
        await mark_claim_paid(
            db, account_id=_ACCOUNT_ID, claim_id=_CLAIM_ID, paid_by_id=_ADMIN_ID
        )
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service: get_account_claim_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_account_claim_summary_returns_correct_structure():
    """get_account_claim_summary returns expected keys and values."""
    db = AsyncMock()
    rows_result = MagicMock()
    rows_result.__iter__ = MagicMock(
        return_value=iter(
            [
                (ClaimStatus.DRAFT, 2, Decimal("40"), Decimal("26.80")),
                (ClaimStatus.SUBMITTED, 1, Decimal("30"), Decimal("20.10")),
                (ClaimStatus.APPROVED, 1, Decimal("50"), Decimal("33.50")),
            ]
        )
    )
    db.execute.return_value = rows_result

    summary = await get_account_claim_summary(db, account_id=_ACCOUNT_ID)
    assert summary["account_id"] == _ACCOUNT_ID
    assert summary["total_claims"] == 4
    assert summary["total_miles"] == Decimal("120")
    assert summary["total_amount_usd"] == Decimal("80.40")
    assert summary["pending_approval_count"] == 1
    assert summary["pending_approval_amount_usd"] == Decimal("20.10")
    assert len(summary["by_status"]) == 3


# ---------------------------------------------------------------------------
# Service: list_all_platform
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_platform_returns_all_claims():
    """list_all_platform returns claims across all accounts."""
    claims = [_make_claim(id=1, account_id=1), _make_claim(id=2, account_id=2)]
    db = _mock_db_scalars(claims)
    result = await list_all_platform(db)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_all_platform_account_filter():
    """list_all_platform filters by account_id when provided."""
    claims = [_make_claim(id=1, account_id=1)]
    db = _mock_db_scalars(claims)
    result = await list_all_platform(db, account_id=1)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_all_platform_status_filter():
    """list_all_platform filters by status when provided."""
    claims = [_make_claim(status=ClaimStatus.APPROVED)]
    db = _mock_db_scalars(claims)
    result = await list_all_platform(db, status_filter=ClaimStatus.APPROVED)
    assert len(result) == 1
    assert result[0].status == ClaimStatus.APPROVED


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_schema_policy_update_request_valid():
    """MileagePolicyUpdateRequest accepts valid optional fields."""
    req = MileagePolicyUpdateRequest(
        rate_per_mile=Decimal("0.7000"),
        max_miles_per_claim=500,
        requires_approval_above_usd=Decimal("200.00"),
    )
    assert req.rate_per_mile == Decimal("0.7000")
    assert req.max_miles_per_claim == 500


def test_schema_claim_create_request_valid():
    """MileageClaimCreateRequest accepts valid fields."""
    req = MileageClaimCreateRequest(
        trip_date=_TODAY,
        miles=Decimal("75.5"),
        description="Off-site meeting",
    )
    assert req.miles == Decimal("75.5")


def test_schema_claim_create_request_miles_zero_raises():
    """MileageClaimCreateRequest rejects miles <= 0."""
    with pytest.raises(ValidationError):
        MileageClaimCreateRequest(
            trip_date=_TODAY,
            miles=Decimal("0"),
            description="No distance",
        )


def test_schema_claim_create_request_miles_negative_raises():
    """MileageClaimCreateRequest rejects negative miles."""
    with pytest.raises(ValidationError):
        MileageClaimCreateRequest(
            trip_date=_TODAY,
            miles=Decimal("-5"),
            description="Negative miles",
        )


def test_schema_review_request_valid_approve():
    """MileageClaimReviewRequest accepts action='approve'."""
    req = MileageClaimReviewRequest(action="approve", note="All good")
    assert req.action == "approve"
    assert req.note == "All good"


def test_schema_review_request_invalid_action_raises():
    """MileageClaimReviewRequest rejects invalid action values."""
    with pytest.raises(ValidationError):
        MileageClaimReviewRequest(action="cancel")


def test_schema_claim_response_from_attributes():
    """MileageClaimResponse.model_validate works on the ORM model."""
    resp = MileageClaimResponse.model_validate(_DUMMY_CLAIM)
    assert resp.id == _CLAIM_ID
    assert resp.member_id == _MEMBER_ID
    assert resp.status == ClaimStatus.DRAFT
    assert resp.miles == _MILES


def test_schema_claim_summary_response_valid():
    """MileageClaimSummaryResponse can be instantiated with correct fields."""
    resp = MileageClaimSummaryResponse(
        account_id=_ACCOUNT_ID,
        total_claims=5,
        total_miles=Decimal("200"),
        total_amount_usd=Decimal("134.00"),
        pending_approval_count=2,
        pending_approval_amount_usd=Decimal("40.00"),
        by_status=[],
    )
    assert resp.total_claims == 5
    assert resp.total_miles == Decimal("200")


# ---------------------------------------------------------------------------
# API fixtures
# ---------------------------------------------------------------------------


def _make_app_client() -> TestClient:
    from app.main import app
    from app.api.deps import get_current_user, get_db, require_admin
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.id = _ADMIN_ID

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


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------

_MODULE = "app.api.v1.corporate_mileage_reimbursement"

_DUMMY_POLICY_RESP = {
    "id": _POLICY_ID,
    "account_id": _ACCOUNT_ID,
    "rate_per_mile": "0.6700",
    "max_miles_per_claim": None,
    "requires_approval_above_usd": None,
    "requires_approval_above_miles": None,
    "require_trip_purpose": False,
    "is_active": True,
    "created_by_id": _ADMIN_ID,
}

_DUMMY_CLAIM_RESP = {
    "id": _CLAIM_ID,
    "account_id": _ACCOUNT_ID,
    "member_id": _MEMBER_ID,
    "trip_date": str(_TODAY),
    "miles": "50.00",
    "rate_used_usd": "0.6700",
    "amount_usd": "33.50",
    "description": "Client visit",
    "trip_purpose_id": None,
    "cost_center_id": None,
    "status": "draft",
    "submitted_at": None,
    "reviewed_by_id": None,
    "reviewed_at": None,
    "review_note": None,
    "paid_at": None,
}


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(f"{_MODULE}.get_or_create_policy", new_callable=AsyncMock, return_value=_DUMMY_POLICY)
def test_api_get_policy_200(mock_get, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/policy")
    assert resp.status_code == 200
    data = resp.json()
    assert data["account_id"] == _ACCOUNT_ID


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(f"{_MODULE}.update_policy", new_callable=AsyncMock, return_value=_DUMMY_POLICY)
def test_api_put_policy_200(mock_update, mock_resolve):
    client = _make_app_client()
    resp = client.put(f"{_BASE}/policy", json={"rate_per_mile": "0.7000"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["account_id"] == _ACCOUNT_ID


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(f"{_MODULE}.create_claim", new_callable=AsyncMock, return_value=_DUMMY_CLAIM)
def test_api_create_claim_201(mock_create, mock_resolve):
    client = _make_app_client()
    resp = client.post(
        f"{_BASE}/claims",
        json={
            "trip_date": str(_TODAY),
            "miles": "50.00",
            "description": "Client visit",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["member_id"] == _MEMBER_ID


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(f"{_MODULE}.list_member_claims", new_callable=AsyncMock, return_value=[_DUMMY_CLAIM])
def test_api_get_my_claims_200(mock_list, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/claims")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(f"{_MODULE}.get_claim", new_callable=AsyncMock, return_value=_DUMMY_CLAIM)
def test_api_get_claim_200(mock_get, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/claims/{_CLAIM_ID}")
    assert resp.status_code == 200
    assert resp.json()["id"] == _CLAIM_ID


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(f"{_MODULE}.update_claim", new_callable=AsyncMock, return_value=_DUMMY_CLAIM)
def test_api_update_claim_200(mock_update, mock_resolve):
    client = _make_app_client()
    resp = client.put(
        f"{_BASE}/claims/{_CLAIM_ID}",
        json={"description": "Updated description"},
    )
    assert resp.status_code == 200


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(
    f"{_MODULE}.update_claim",
    new_callable=AsyncMock,
    side_effect=HTTPException(status_code=409, detail="Only draft claims can be updated."),
)
def test_api_update_claim_409(mock_update, mock_resolve):
    client = _make_app_client()
    resp = client.put(
        f"{_BASE}/claims/{_CLAIM_ID}",
        json={"description": "Updated description"},
    )
    assert resp.status_code == 409


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(
    f"{_MODULE}.submit_claim",
    new_callable=AsyncMock,
    return_value=_make_claim(status=ClaimStatus.APPROVED),
)
def test_api_submit_claim_200(mock_submit, mock_resolve):
    client = _make_app_client()
    resp = client.post(f"{_BASE}/claims/{_CLAIM_ID}/submit")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(
    f"{_MODULE}.list_all_platform",
    new_callable=AsyncMock,
    return_value=[_DUMMY_CLAIM, _make_claim(id=43)],
)
def test_api_list_all_account_claims_200(mock_list, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/claims/all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(
    f"{_MODULE}.get_account_claim_summary",
    new_callable=AsyncMock,
    return_value={
        "account_id": _ACCOUNT_ID,
        "total_claims": 3,
        "total_miles": Decimal("120"),
        "total_amount_usd": Decimal("80.40"),
        "pending_approval_count": 1,
        "pending_approval_amount_usd": Decimal("20.10"),
        "by_status": [
            {"status": ClaimStatus.DRAFT, "count": 1, "total_amount_usd": Decimal("33.50")},
            {"status": ClaimStatus.SUBMITTED, "count": 1, "total_amount_usd": Decimal("20.10")},
            {"status": ClaimStatus.APPROVED, "count": 1, "total_amount_usd": Decimal("26.80")},
        ],
    },
)
def test_api_get_summary_200(mock_summary, mock_resolve):
    client = _make_app_client()
    resp = client.get(f"{_BASE}/claims/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_claims"] == 3
    assert data["pending_approval_count"] == 1
    assert len(data["by_status"]) == 3


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(
    f"{_MODULE}.review_claim",
    new_callable=AsyncMock,
    return_value=_make_claim(status=ClaimStatus.APPROVED),
)
def test_api_review_claim_200(mock_review, mock_resolve):
    client = _make_app_client()
    resp = client.post(
        f"{_BASE}/claims/{_CLAIM_ID}/review",
        json={"action": "approve", "note": "Approved"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


@patch(f"{_MODULE}._resolve_account_id", new_callable=AsyncMock, return_value=_ACCOUNT_ID)
@patch(
    f"{_MODULE}.mark_claim_paid",
    new_callable=AsyncMock,
    return_value=_make_claim(status=ClaimStatus.PAID),
)
def test_api_mark_paid_200(mock_paid, mock_resolve):
    client = _make_app_client()
    resp = client.post(f"{_BASE}/claims/{_CLAIM_ID}/paid")
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"


@patch(
    f"{_MODULE}.list_all_platform",
    new_callable=AsyncMock,
    return_value=[_DUMMY_CLAIM],
)
def test_api_platform_admin_list_claims_200(mock_list):
    client = _make_app_client()
    resp = client.get(f"{_ADMIN_BASE}/{_ACCOUNT_ID}/mileage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
