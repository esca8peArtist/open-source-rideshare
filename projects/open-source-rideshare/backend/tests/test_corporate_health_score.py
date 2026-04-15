"""Tests for the Corporate Account Health Score feature.

Service layer (async, mocked DB):
  1.  compute_health_score — happy path creates snapshot, returns response
  2.  compute_health_score — overall_score is weighted average of sub-scores
  3.  compute_health_score — computed_by_id stored when provided
  4.  compute_health_score — computed_by_id is None for automatic computation
  5.  compute_health_score — score_details contains all six domain keys
  6.  _compute_payment_score — 100 when no unpaid invoices
  7.  _compute_payment_score — deducts 20 per unpaid finalized invoice
  8.  _compute_payment_score — floors at 0 with many unpaid invoices
  9.  _compute_compliance_score — 100 when no denied approvals
  10. _compute_compliance_score — deducts 15 per denial
  11. _compute_credit_score — 100 when no credit account
  12. _compute_credit_score — 0 when balance is zero
  13. _compute_credit_score — 100 when balance >= 2x threshold
  14. _compute_credit_score — 70 when balance between threshold and 2x
  15. _compute_credit_score — 40 when balance below threshold
  16. _compute_dispute_score — 100 when no open disputes
  17. _compute_dispute_score — deducts 25 per open dispute
  18. _compute_contract_score — 100 for active contract
  19. _compute_contract_score — 80 when no contract
  20. _compute_contract_score — 0 for terminated contract
  21. _compute_suspension_score — 100 when never suspended
  22. _compute_suspension_score — 0 when currently suspended
  23. _compute_suspension_score — 70 when past suspensions but currently active
  24. get_latest_health_score — returns most recent snapshot
  25. get_latest_health_score — returns None when no snapshots exist
  26. get_health_score_history — returns list ordered newest-first
  27. get_health_score_history — returns empty list when no snapshots
  28. get_at_risk_summary — returns correct distribution counts

Schema validation:
  29. HealthScoreResponse — from_attributes model config
  30. HealthScoreListResponse — valid construction
  31. RiskDistribution — valid construction
  32. AtRiskSummaryResponse — at_risk_count equals poor + critical
  33. HealthRiskLevel — all five values valid

API layer (service functions patched):
  34. GET /corporate/accounts/me/health-score — 200 happy path
  35. GET /corporate/accounts/me/health-score — 404 no snapshot yet
  36. GET /corporate/accounts/me/health-score — 404 not a member
  37. GET /corporate/accounts/me/health-score/history — 200 returns list
  38. POST /corporate/accounts/me/health-score/refresh — 201 happy path
  39. POST /corporate/accounts/me/health-score/refresh — 403 non-admin member
  40. GET /admin/corporate/accounts/{id}/health-score — 200 happy path
  41. GET /admin/corporate/accounts/{id}/health-score — 404 no snapshot
  42. POST /admin/corporate/accounts/{id}/health-score/recompute — 201 happy path
  43. GET /admin/corporate/health-scores — 200 returns list
  44. GET /admin/corporate/health-scores/at-risk — 200 returns summary
  45. GET /admin/corporate/health-scores — non-admin gets 403
  46. GET /admin/corporate/accounts/{id}/health-score — non-admin gets 403
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_health_score import (
    CorporateAccountHealthScore,
    HealthRiskLevel,
    _risk_level_from_score,
)
from app.schemas.corporate_health_score import (
    AtRiskSummaryResponse,
    HealthScoreListResponse,
    HealthScoreResponse,
    RiskDistribution,
)
from app.services.corporate_health_score import (
    _compute_compliance_score,
    _compute_contract_score,
    _compute_credit_score,
    _compute_dispute_score,
    _compute_payment_score,
    _compute_suspension_score,
    compute_health_score,
    get_at_risk_summary,
    get_health_score_history,
    get_latest_health_score,
    _to_response,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 42
ADMIN_ID = 99
USER_ID = 7
SCORE_ID = 1

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)

_ROUTER = "app.api.v1.corporate_health_score"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(
    score_id: int = SCORE_ID,
    account_id: int = ACCOUNT_ID,
    overall_score: int = 85,
    risk_level: HealthRiskLevel = HealthRiskLevel.good,
    payment_score: int = 100,
    compliance_score: int = 85,
    credit_score: int = 100,
    dispute_score: int = 75,
    contract_score: int = 100,
    suspension_score: int = 100,
    computed_by_id: int | None = None,
) -> CorporateAccountHealthScore:
    """Build a minimal CorporateAccountHealthScore instance for testing."""
    s = CorporateAccountHealthScore()
    s.id = score_id
    s.account_id = account_id
    s.overall_score = overall_score
    s.risk_level = risk_level
    s.payment_score = payment_score
    s.compliance_score = compliance_score
    s.credit_score = credit_score
    s.dispute_score = dispute_score
    s.contract_score = contract_score
    s.suspension_score = suspension_score
    s.score_details = {
        "payment": {},
        "compliance": {},
        "credit": {},
        "dispute": {},
        "contract": {},
        "suspension": {},
    }
    s.computed_at = _NOW
    s.computed_by_id = computed_by_id
    return s


def _make_response(
    score_id: int = SCORE_ID,
    account_id: int = ACCOUNT_ID,
    overall_score: int = 85,
    risk_level: HealthRiskLevel = HealthRiskLevel.good,
) -> HealthScoreResponse:
    return HealthScoreResponse(
        id=score_id,
        account_id=account_id,
        overall_score=overall_score,
        risk_level=risk_level,
        payment_score=100,
        compliance_score=85,
        credit_score=100,
        dispute_score=75,
        contract_score=100,
        suspension_score=100,
        score_details={
            "payment": {},
            "compliance": {},
            "credit": {},
            "dispute": {},
            "contract": {},
            "suspension": {},
        },
        computed_at=_NOW,
        computed_by_id=None,
    )


def _mock_user(user_id: int = USER_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


def _make_scalar_result(value) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    result.scalar_one_or_none.return_value = value
    return result


def _make_scalars_result(items: list) -> MagicMock:
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    result.scalars.return_value = scalars
    return result


def _make_all_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


_SVC = "app.services.corporate_health_score"

_ALL_100 = (100, {})


def _patch_all_subscores(monkeypatch=None):
    """Return a context-manager stack that patches all six sub-score helpers to (100, {})."""
    from contextlib import ExitStack

    stack = ExitStack()
    for name in (
        "_compute_payment_score",
        "_compute_compliance_score",
        "_compute_credit_score",
        "_compute_dispute_score",
        "_compute_contract_score",
        "_compute_suspension_score",
    ):
        stack.enter_context(
            patch(f"{_SVC}.{name}", new=AsyncMock(return_value=_ALL_100))
        )
    return stack


# ---------------------------------------------------------------------------
# 1. compute_health_score — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_health_score_creates_snapshot():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    added = []

    def _add(obj):
        added.append(obj)
        obj.id = SCORE_ID
        obj.computed_at = _NOW

    db.add = _add

    with _patch_all_subscores():
        await compute_health_score(db, account_id=ACCOUNT_ID)

    assert len(added) == 1
    snapshot = added[0]
    assert snapshot.account_id == ACCOUNT_ID
    assert 0 <= snapshot.overall_score <= 100
    assert isinstance(snapshot.risk_level, HealthRiskLevel)


# ---------------------------------------------------------------------------
# 2. compute_health_score — overall_score is weighted average
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_health_score_weighted_average():
    """When all sub-scores are 100, overall must be 100."""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    added = []

    def _add(obj):
        added.append(obj)
        obj.id = SCORE_ID
        obj.computed_at = _NOW

    db.add = _add

    with _patch_all_subscores():
        await compute_health_score(db, account_id=ACCOUNT_ID)

    snapshot = added[0]
    assert snapshot.overall_score == 100


# ---------------------------------------------------------------------------
# 3. compute_health_score — computed_by_id stored when provided
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_health_score_computed_by_id_stored():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    added = []

    def _add(obj):
        added.append(obj)
        obj.id = SCORE_ID
        obj.computed_at = _NOW

    db.add = _add

    with _patch_all_subscores():
        await compute_health_score(db, account_id=ACCOUNT_ID, computed_by_id=ADMIN_ID)

    assert added[0].computed_by_id == ADMIN_ID


# ---------------------------------------------------------------------------
# 4. compute_health_score — computed_by_id None for automatic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_health_score_computed_by_id_none():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    added = []

    def _add(obj):
        added.append(obj)
        obj.id = SCORE_ID
        obj.computed_at = _NOW

    db.add = _add

    with _patch_all_subscores():
        await compute_health_score(db, account_id=ACCOUNT_ID)

    assert added[0].computed_by_id is None


# ---------------------------------------------------------------------------
# 5. compute_health_score — score_details contains all six domain keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_health_score_details_keys():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    added = []

    def _add(obj):
        added.append(obj)
        obj.id = SCORE_ID
        obj.computed_at = _NOW

    db.add = _add

    with _patch_all_subscores():
        await compute_health_score(db, account_id=ACCOUNT_ID)

    details = added[0].score_details
    for key in ("payment", "compliance", "credit", "dispute", "contract", "suspension"):
        assert key in details


# ---------------------------------------------------------------------------
# 6–8. _compute_payment_score tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_payment_score_100_no_unpaid():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalar_result(0))
    score, evidence = await _compute_payment_score(db, ACCOUNT_ID)
    assert score == 100
    assert evidence["unpaid_finalized_invoices"] == 0


@pytest.mark.asyncio
async def test_payment_score_deducts_20_per_invoice():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalar_result(2))
    score, evidence = await _compute_payment_score(db, ACCOUNT_ID)
    assert score == 60
    assert evidence["unpaid_finalized_invoices"] == 2


@pytest.mark.asyncio
async def test_payment_score_floors_at_zero():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalar_result(10))
    score, _ = await _compute_payment_score(db, ACCOUNT_ID)
    assert score == 0


# ---------------------------------------------------------------------------
# 9–10. _compute_compliance_score tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compliance_score_100_no_denials():
    db = AsyncMock()
    # Two calls: total count then denied count
    db.execute = AsyncMock(side_effect=[
        _make_scalar_result(5),  # total
        _make_scalar_result(0),  # denied
    ])
    score, evidence = await _compute_compliance_score(db, ACCOUNT_ID)
    assert score == 100
    assert evidence["denied_ride_approvals"] == 0


@pytest.mark.asyncio
async def test_compliance_score_deducts_15_per_denial():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _make_scalar_result(10),  # total
        _make_scalar_result(3),   # denied
    ])
    score, evidence = await _compute_compliance_score(db, ACCOUNT_ID)
    assert score == 55
    assert evidence["denied_ride_approvals"] == 3


# ---------------------------------------------------------------------------
# 11–15. _compute_credit_score tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credit_score_100_no_credit_account():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalar_result(None))
    score, evidence = await _compute_credit_score(db, ACCOUNT_ID)
    assert score == 100
    assert evidence["credit_account"] == "not_configured"


@pytest.mark.asyncio
async def test_credit_score_zero_on_empty_balance():
    credit = MagicMock()
    credit.balance_usd = Decimal("0")
    credit.low_balance_threshold_usd = Decimal("50")
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalar_result(credit))
    score, _ = await _compute_credit_score(db, ACCOUNT_ID)
    assert score == 0


@pytest.mark.asyncio
async def test_credit_score_100_above_double_threshold():
    credit = MagicMock()
    credit.balance_usd = Decimal("200")
    credit.low_balance_threshold_usd = Decimal("50")
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalar_result(credit))
    score, _ = await _compute_credit_score(db, ACCOUNT_ID)
    assert score == 100


@pytest.mark.asyncio
async def test_credit_score_70_between_threshold_and_double():
    credit = MagicMock()
    credit.balance_usd = Decimal("75")
    credit.low_balance_threshold_usd = Decimal("50")
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalar_result(credit))
    score, _ = await _compute_credit_score(db, ACCOUNT_ID)
    assert score == 70


@pytest.mark.asyncio
async def test_credit_score_40_below_threshold():
    credit = MagicMock()
    credit.balance_usd = Decimal("30")
    credit.low_balance_threshold_usd = Decimal("50")
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalar_result(credit))
    score, _ = await _compute_credit_score(db, ACCOUNT_ID)
    assert score == 40


# ---------------------------------------------------------------------------
# 16–17. _compute_dispute_score tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispute_score_100_no_open_disputes():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalar_result(0))
    score, evidence = await _compute_dispute_score(db, ACCOUNT_ID)
    assert score == 100
    assert evidence["open_disputes"] == 0


@pytest.mark.asyncio
async def test_dispute_score_deducts_25_per_dispute():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalar_result(2))
    score, evidence = await _compute_dispute_score(db, ACCOUNT_ID)
    assert score == 50
    assert evidence["open_disputes"] == 2


# ---------------------------------------------------------------------------
# 18–20. _compute_contract_score tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contract_score_100_active_contract():
    from app.models.corporate_account_contract import ContractStatus, CorporateAccountContract

    contract = MagicMock(spec=CorporateAccountContract)
    contract.status = ContractStatus.active
    contract.id = 1

    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = contract
    db.execute = AsyncMock(return_value=result)

    score, evidence = await _compute_contract_score(db, ACCOUNT_ID)
    assert score == 100
    assert evidence["contract_status"] == "active"


@pytest.mark.asyncio
async def test_contract_score_80_no_contract():
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    score, evidence = await _compute_contract_score(db, ACCOUNT_ID)
    assert score == 80
    assert evidence["contract_status"] == "none"


@pytest.mark.asyncio
async def test_contract_score_0_terminated():
    from app.models.corporate_account_contract import ContractStatus, CorporateAccountContract

    contract = MagicMock(spec=CorporateAccountContract)
    contract.status = ContractStatus.terminated
    contract.id = 1

    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = contract
    db.execute = AsyncMock(return_value=result)

    score, _ = await _compute_contract_score(db, ACCOUNT_ID)
    assert score == 0


# ---------------------------------------------------------------------------
# 21–23. _compute_suspension_score tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suspension_score_100_never_suspended():
    db = AsyncMock()
    # active count = 0, history count = 0
    db.execute = AsyncMock(side_effect=[
        _make_scalar_result(0),
        _make_scalar_result(0),
    ])
    score, evidence = await _compute_suspension_score(db, ACCOUNT_ID)
    assert score == 100
    assert evidence["currently_suspended"] is False
    assert evidence["past_suspensions"] == 0


@pytest.mark.asyncio
async def test_suspension_score_0_currently_suspended():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalar_result(1))  # active count = 1
    score, evidence = await _compute_suspension_score(db, ACCOUNT_ID)
    assert score == 0
    assert evidence["currently_suspended"] is True


@pytest.mark.asyncio
async def test_suspension_score_70_past_suspensions():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _make_scalar_result(0),   # active = 0
        _make_scalar_result(2),   # past = 2
    ])
    score, evidence = await _compute_suspension_score(db, ACCOUNT_ID)
    assert score == 70
    assert evidence["past_suspensions"] == 2


# ---------------------------------------------------------------------------
# 24–25. get_latest_health_score tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_latest_health_score_returns_most_recent():
    snapshot = _make_snapshot()
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = snapshot
    db.execute = AsyncMock(return_value=result)

    response = await get_latest_health_score(db, ACCOUNT_ID)
    assert response is not None
    assert response.account_id == ACCOUNT_ID
    assert response.overall_score == 85


@pytest.mark.asyncio
async def test_get_latest_health_score_returns_none_when_empty():
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    response = await get_latest_health_score(db, ACCOUNT_ID)
    assert response is None


# ---------------------------------------------------------------------------
# 26–27. get_health_score_history tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_health_score_history_returns_list():
    snapshots = [_make_snapshot(score_id=i) for i in range(1, 4)]
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalars_result(snapshots))

    responses = await get_health_score_history(db, ACCOUNT_ID, limit=10)
    assert len(responses) == 3
    assert all(r.account_id == ACCOUNT_ID for r in responses)


@pytest.mark.asyncio
async def test_get_health_score_history_empty():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalars_result([]))

    responses = await get_health_score_history(db, ACCOUNT_ID)
    assert responses == []


# ---------------------------------------------------------------------------
# 28. get_at_risk_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_at_risk_summary_returns_distribution():
    from unittest.mock import MagicMock

    row_excellent = MagicMock()
    row_excellent.risk_level = HealthRiskLevel.excellent
    row_excellent.cnt = 10
    row_poor = MagicMock()
    row_poor.risk_level = HealthRiskLevel.poor
    row_poor.cnt = 3
    row_critical = MagicMock()
    row_critical.risk_level = HealthRiskLevel.critical
    row_critical.cnt = 1

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_all_result([row_excellent, row_poor, row_critical]))

    summary = await get_at_risk_summary(db)
    assert summary.total_accounts_scored == 14
    assert summary.distribution.excellent == 10
    assert summary.distribution.poor == 3
    assert summary.distribution.critical == 1
    assert summary.at_risk_count == 4


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_health_score_response_from_attributes():
    snapshot = _make_snapshot()
    r = _to_response(snapshot)
    assert r.id == SCORE_ID
    assert r.account_id == ACCOUNT_ID
    assert r.overall_score == 85


def test_health_score_list_response():
    scores = [_make_response(), _make_response(score_id=2)]
    resp = HealthScoreListResponse(scores=scores, total=2)
    assert resp.total == 2
    assert len(resp.scores) == 2


def test_risk_distribution_valid():
    d = RiskDistribution(excellent=5, good=10, fair=3, poor=2, critical=1)
    assert d.excellent == 5
    assert d.critical == 1


def test_at_risk_summary_at_risk_count():
    summary = AtRiskSummaryResponse(
        total_accounts_scored=20,
        distribution=RiskDistribution(excellent=10, good=5, fair=2, poor=2, critical=1),
        at_risk_count=3,
    )
    assert summary.at_risk_count == 3


def test_health_risk_level_all_values():
    expected = {"excellent", "good", "fair", "poor", "critical"}
    assert {lvl.value for lvl in HealthRiskLevel} == expected


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------


# 34. GET /corporate/accounts/me/health-score — 200 happy path
@pytest.mark.asyncio
async def test_api_get_my_health_score_200():
    from app.api.v1.corporate_health_score import get_my_health_score

    user = _mock_user()
    db = AsyncMock()
    mock_score = _make_response()

    with (
        patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch(f"{_ROUTER}.get_latest_health_score", new=AsyncMock(return_value=mock_score)),
    ):
        result = await get_my_health_score(user=user, db=db)

    assert result.account_id == ACCOUNT_ID
    assert result.overall_score == 85


# 35. GET /corporate/accounts/me/health-score — 404 no snapshot
@pytest.mark.asyncio
async def test_api_get_my_health_score_404_no_snapshot():
    from app.api.v1.corporate_health_score import get_my_health_score

    user = _mock_user()
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch(f"{_ROUTER}.get_latest_health_score", new=AsyncMock(return_value=None)),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_my_health_score(user=user, db=db)

    assert exc_info.value.status_code == 404


# 36. GET /corporate/accounts/me/health-score — 404 not a member
@pytest.mark.asyncio
async def test_api_get_my_health_score_404_not_member():
    from app.api.v1.corporate_health_score import get_my_health_score

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc_info:
            await get_my_health_score(user=user, db=db)

    assert exc_info.value.status_code == 404


# 37. GET /corporate/accounts/me/health-score/history — 200 returns list
@pytest.mark.asyncio
async def test_api_get_my_health_score_history_200():
    from app.api.v1.corporate_health_score import get_my_health_score_history

    user = _mock_user()
    db = AsyncMock()
    scores = [_make_response(), _make_response(score_id=2)]

    with (
        patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch(f"{_ROUTER}.get_health_score_history", new=AsyncMock(return_value=scores)),
    ):
        result = await get_my_health_score_history(limit=30, user=user, db=db)

    assert result.total == 2
    assert len(result.scores) == 2


# 38. POST /corporate/accounts/me/health-score/refresh — 201 admin happy path
@pytest.mark.asyncio
async def test_api_refresh_my_health_score_201():
    from app.api.v1.corporate_health_score import refresh_my_health_score

    user = _mock_user()
    db = AsyncMock()
    mock_score = _make_response()

    with (
        patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=MagicMock())),
        patch(f"{_ROUTER}.compute_health_score", new=AsyncMock(return_value=mock_score)),
    ):
        result = await refresh_my_health_score(user=user, db=db)

    assert result.account_id == ACCOUNT_ID


# 39. POST /corporate/accounts/me/health-score/refresh — 403 non-admin
@pytest.mark.asyncio
async def test_api_refresh_my_health_score_403_non_admin():
    from app.api.v1.corporate_health_score import refresh_my_health_score

    user = _mock_user()
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=MagicMock(id=ACCOUNT_ID))),
        patch(
            f"{_ROUTER}._require_account_admin",
            new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Not admin")),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await refresh_my_health_score(user=user, db=db)

    assert exc_info.value.status_code == 403


# 40. GET /admin/corporate/accounts/{id}/health-score — 200 happy path
@pytest.mark.asyncio
async def test_api_admin_get_health_score_200():
    from app.api.v1.corporate_health_score import admin_get_health_score

    admin_user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_score = _make_response()

    with patch(f"{_ROUTER}.get_latest_health_score", new=AsyncMock(return_value=mock_score)):
        result = await admin_get_health_score(account_id=ACCOUNT_ID, _admin=admin_user, db=db)

    assert result.account_id == ACCOUNT_ID


# 41. GET /admin/corporate/accounts/{id}/health-score — 404 no snapshot
@pytest.mark.asyncio
async def test_api_admin_get_health_score_404():
    from app.api.v1.corporate_health_score import admin_get_health_score

    admin_user = _mock_user(ADMIN_ID)
    db = AsyncMock()

    with patch(f"{_ROUTER}.get_latest_health_score", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc_info:
            await admin_get_health_score(account_id=ACCOUNT_ID, _admin=admin_user, db=db)

    assert exc_info.value.status_code == 404


# 42. POST /admin/corporate/accounts/{id}/health-score/recompute — 201 happy path
@pytest.mark.asyncio
async def test_api_admin_recompute_health_score_201():
    from app.api.v1.corporate_health_score import admin_recompute_health_score

    admin_user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_score = _make_response()

    with patch(f"{_ROUTER}.compute_health_score", new=AsyncMock(return_value=mock_score)):
        result = await admin_recompute_health_score(
            account_id=ACCOUNT_ID, admin=admin_user, db=db
        )

    assert result.account_id == ACCOUNT_ID


# 43. GET /admin/corporate/health-scores — 200 returns list
@pytest.mark.asyncio
async def test_api_admin_list_health_scores_200():
    from app.api.v1.corporate_health_score import admin_list_health_scores

    admin_user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    scores = [_make_response(), _make_response(score_id=2, account_id=11)]

    with patch(f"{_ROUTER}.list_accounts_by_health", new=AsyncMock(return_value=scores)):
        result = await admin_list_health_scores(
            risk_level=None, below_score=None, skip=0, limit=50,
            _admin=admin_user, db=db,
        )

    assert result.total == 2
    assert len(result.scores) == 2


# 44. GET /admin/corporate/health-scores/at-risk — 200 returns summary
@pytest.mark.asyncio
async def test_api_admin_at_risk_summary_200():
    from app.api.v1.corporate_health_score import admin_at_risk_summary

    admin_user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_summary = AtRiskSummaryResponse(
        total_accounts_scored=20,
        distribution=RiskDistribution(excellent=10, good=5, fair=2, poor=2, critical=1),
        at_risk_count=3,
    )

    with patch(f"{_ROUTER}.get_at_risk_summary", new=AsyncMock(return_value=mock_summary)):
        result = await admin_at_risk_summary(_admin=admin_user, db=db)

    assert result.total_accounts_scored == 20
    assert result.at_risk_count == 3


# 45. GET /admin/corporate/health-scores — non-admin gets 403
@pytest.mark.asyncio
async def test_api_admin_list_health_scores_403():
    from app.api.v1.corporate_health_score import admin_list_health_scores

    db = AsyncMock()

    with patch(
        f"{_ROUTER}.list_accounts_by_health",
        new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await admin_list_health_scores(
                risk_level=None, below_score=None, skip=0, limit=50,
                _admin=MagicMock(), db=db,
            )

    assert exc_info.value.status_code == 403


# 46. GET /admin/corporate/accounts/{id}/health-score — non-admin gets 403
@pytest.mark.asyncio
async def test_api_admin_get_health_score_403():
    from app.api.v1.corporate_health_score import admin_get_health_score

    db = AsyncMock()

    with patch(
        f"{_ROUTER}.get_latest_health_score",
        new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await admin_get_health_score(account_id=ACCOUNT_ID, _admin=MagicMock(), db=db)

    assert exc_info.value.status_code == 403
