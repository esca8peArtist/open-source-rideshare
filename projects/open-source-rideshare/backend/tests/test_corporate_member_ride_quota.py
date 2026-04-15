"""Tests for the Corporate Member Ride Quota feature.

Schema tests (sync):
  1.  QuotaPeriod — valid values
  2.  QuotaCreate — valid payload
  3.  QuotaCreate — max_rides below 1 → ValidationError
  4.  QuotaCreate — max_rides above 500 → ValidationError
  5.  QuotaUpdate — all optional fields
  6.  QuotaUpdate — max_rides 0 → ValidationError
  7.  QuotaResponse — from_attributes
  8.  QuotaWithUsageResponse — computed fields present
  9.  QuotaListResponse — structure
  10. QuotaCheckResponse — quota_active False when unrestricted

Service / helper tests (async, mocked DB):
  11. _period_start — daily returns today midnight UTC
  12. _period_start — weekly returns Monday midnight UTC
  13. _period_start — monthly returns 1st of month midnight UTC
  14. _period_start — unknown period raises ValueError
  15. set_quota — success creates new row
  16. set_quota — active duplicate raises 409
  17. set_quota — inactive duplicate reactivates row
  18. update_quota — updates max_rides
  19. update_quota — updates is_active
  20. update_quota — not found raises 404
  21. deactivate_quota — sets is_active False
  22. deactivate_quota — not found raises 404
  23. delete_quota — hard deletes row
  24. delete_quota — not found raises 404
  25. get_quota — returns quota
  26. get_quota — not found raises 404
  27. list_member_quotas — returns all active quotas
  28. list_member_quotas — filtered by member_id
  29. list_member_quotas — filtered by period
  30. get_quota_usage — no active quota returns quota_active=False
  31. get_quota_usage — active quota returns usage data
  32. get_quota_usage — quota_exceeded when rides >= max
  33. get_account_quota_summary — enriches rows with usage

API layer tests (endpoint functions called directly):
  34. POST /corporate/accounts/{id}/ride-quotas — 201 happy path
  35. POST /corporate/accounts/{id}/ride-quotas — 409 propagated
  36. GET  /corporate/accounts/{id}/ride-quotas — 200 list
  37. GET  /corporate/accounts/{id}/ride-quotas/summary — 200
  38. GET  /corporate/accounts/{id}/ride-quotas/{id} — 200
  39. PUT  /corporate/accounts/{id}/ride-quotas/{id} — 200
  40. DELETE /corporate/accounts/{id}/ride-quotas/{id} — 204
  41. GET  /corporate/accounts/me/ride-quotas/check — 200 member
  42. GET  /corporate/accounts/me/ride-quotas/check — 404 not a member
  43. POST /admin/corporate/accounts/{id}/ride-quotas — 201
  44. GET  /admin/corporate/accounts/{id}/ride-quotas — 200
  45. GET  /admin/corporate/ride-quotas/exceeded — 200 returns exceeded
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_member_ride_quota import CorporateMemberRideQuota
from app.schemas.corporate_member_ride_quota import (
    QuotaCheckResponse,
    QuotaCreate,
    QuotaListResponse,
    QuotaPeriod,
    QuotaResponse,
    QuotaUpdate,
    QuotaWithUsageResponse,
)
from app.services.corporate_member_ride_quota import (
    _period_start,
    deactivate_quota,
    delete_quota,
    get_account_quota_summary,
    get_quota,
    get_quota_usage,
    list_member_quotas,
    set_quota,
    update_quota,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)  # Wednesday

ACCOUNT_ID = 10
MEMBER_ID = 20
ADMIN_ID = 99


def _make_quota(
    quota_id: int = 1,
    account_id: int = ACCOUNT_ID,
    member_id: int = MEMBER_ID,
    period: str = "daily",
    max_rides: int = 5,
    is_active: bool = True,
    created_by_id: int = ADMIN_ID,
) -> CorporateMemberRideQuota:
    q = CorporateMemberRideQuota()
    q.id = quota_id
    q.account_id = account_id
    q.member_id = member_id
    q.period = period
    q.max_rides = max_rides
    q.is_active = is_active
    q.created_by_id = created_by_id
    q.created_at = _NOW
    q.updated_at = _NOW
    return q


def _make_quota_response(**kwargs) -> QuotaResponse:
    defaults = dict(
        id=1,
        account_id=ACCOUNT_ID,
        member_id=MEMBER_ID,
        period="daily",
        max_rides=5,
        is_active=True,
        created_by_id=ADMIN_ID,
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(kwargs)
    return QuotaResponse(**defaults)


def _make_db(
    scalar_one: CorporateMemberRideQuota | None = None,
    scalars_all: list | None = None,
) -> AsyncMock:
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_one
    mock_result.scalar_one.return_value = 0
    mock_result.scalars.return_value.all.return_value = scalars_all or []
    mock_result.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


def _populate_quota(template: CorporateMemberRideQuota):
    """Side-effect for db.refresh — copies server-default fields."""
    def _side_effect(obj):
        obj.id = template.id
        obj.created_at = template.created_at
        obj.updated_at = template.updated_at
    return _side_effect


def _mock_user(user_id: int = ADMIN_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


# ===========================================================================
# 1–10  Schema tests
# ===========================================================================


def test_quota_period_valid_values():
    """QuotaPeriod — valid values."""
    assert QuotaPeriod.daily == "daily"
    assert QuotaPeriod.weekly == "weekly"
    assert QuotaPeriod.monthly == "monthly"


def test_quota_create_valid():
    """QuotaCreate — valid payload."""
    q = QuotaCreate(member_id=5, period=QuotaPeriod.daily, max_rides=10)
    assert q.member_id == 5
    assert q.period == QuotaPeriod.daily
    assert q.max_rides == 10


def test_quota_create_max_rides_below_1_raises():
    """QuotaCreate — max_rides below 1 → ValidationError."""
    with pytest.raises(ValidationError):
        QuotaCreate(member_id=5, period=QuotaPeriod.daily, max_rides=0)


def test_quota_create_max_rides_above_500_raises():
    """QuotaCreate — max_rides above 500 → ValidationError."""
    with pytest.raises(ValidationError):
        QuotaCreate(member_id=5, period=QuotaPeriod.weekly, max_rides=501)


def test_quota_update_all_optional():
    """QuotaUpdate — all optional fields."""
    u = QuotaUpdate()
    assert u.max_rides is None
    assert u.is_active is None

    u2 = QuotaUpdate(max_rides=3, is_active=False)
    assert u2.max_rides == 3
    assert u2.is_active is False


def test_quota_update_max_rides_zero_raises():
    """QuotaUpdate — max_rides 0 → ValidationError."""
    with pytest.raises(ValidationError):
        QuotaUpdate(max_rides=0)


def test_quota_response_from_attributes():
    """QuotaResponse — from_attributes."""
    q = _make_quota()
    resp = QuotaResponse.model_validate(q)
    assert resp.id == 1
    assert resp.account_id == ACCOUNT_ID
    assert resp.member_id == MEMBER_ID
    assert resp.period == "daily"
    assert resp.max_rides == 5
    assert resp.is_active is True


def test_quota_with_usage_response_computed_fields():
    """QuotaWithUsageResponse — computed fields present."""
    r = QuotaWithUsageResponse(
        id=1,
        account_id=ACCOUNT_ID,
        member_id=MEMBER_ID,
        period="daily",
        max_rides=5,
        is_active=True,
        created_by_id=ADMIN_ID,
        created_at=_NOW,
        updated_at=_NOW,
        current_period_rides=3,
        remaining_rides=2,
        quota_exceeded=False,
    )
    assert r.current_period_rides == 3
    assert r.remaining_rides == 2
    assert r.quota_exceeded is False


def test_quota_list_response_structure():
    """QuotaListResponse — structure."""
    lr = QuotaListResponse(quotas=[], total=0)
    assert lr.total == 0
    assert lr.quotas == []


def test_quota_check_response_quota_active_false():
    """QuotaCheckResponse — quota_active False when unrestricted."""
    cr = QuotaCheckResponse(
        member_id=MEMBER_ID,
        period="daily",
        max_rides=0,
        current_period_rides=0,
        remaining_rides=0,
        quota_exceeded=False,
        quota_active=False,
    )
    assert cr.quota_active is False
    assert cr.quota_exceeded is False


# ===========================================================================
# 11–14  _period_start helper tests
# ===========================================================================


def test_period_start_daily():
    """_period_start — daily returns today midnight UTC."""
    result = _period_start("daily")
    now = datetime.now(tz=timezone.utc)
    assert result.hour == 0
    assert result.minute == 0
    assert result.second == 0
    assert result.date() == now.date()
    assert result.tzinfo is not None


def test_period_start_weekly():
    """_period_start — weekly returns Monday midnight UTC."""
    result = _period_start("weekly")
    assert result.weekday() == 0  # Monday
    assert result.hour == 0
    assert result.tzinfo is not None


def test_period_start_monthly():
    """_period_start — monthly returns 1st of month midnight UTC."""
    result = _period_start("monthly")
    now = datetime.now(tz=timezone.utc)
    assert result.day == 1
    assert result.month == now.month
    assert result.hour == 0
    assert result.tzinfo is not None


def test_period_start_unknown_raises():
    """_period_start — unknown period raises ValueError."""
    with pytest.raises(ValueError, match="Unknown period"):
        _period_start("quarterly")


# ===========================================================================
# 15–33  Service tests
# ===========================================================================


@pytest.mark.asyncio
async def test_set_quota_success():
    """set_quota — success creates new row."""
    quota_row = _make_quota()
    db = _make_db(scalar_one=None)
    db.refresh.side_effect = _populate_quota(quota_row)

    result = await set_quota(
        db,
        account_id=ACCOUNT_ID,
        member_id=MEMBER_ID,
        period="daily",
        max_rides=5,
        created_by_id=ADMIN_ID,
    )

    db.add.assert_called_once()
    db.commit.assert_called_once()
    assert result.period == "daily"
    assert result.max_rides == 5


@pytest.mark.asyncio
async def test_set_quota_active_duplicate_raises_409():
    """set_quota — active duplicate raises 409."""
    existing = _make_quota(is_active=True)
    db = _make_db(scalar_one=existing)

    with pytest.raises(HTTPException) as exc_info:
        await set_quota(
            db,
            account_id=ACCOUNT_ID,
            member_id=MEMBER_ID,
            period="daily",
            max_rides=5,
            created_by_id=ADMIN_ID,
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_set_quota_inactive_duplicate_reactivates():
    """set_quota — inactive duplicate reactivates row."""
    existing = _make_quota(is_active=False, max_rides=3)
    db = _make_db(scalar_one=existing)

    result = await set_quota(
        db,
        account_id=ACCOUNT_ID,
        member_id=MEMBER_ID,
        period="daily",
        max_rides=10,
        created_by_id=ADMIN_ID,
    )

    db.commit.assert_called_once()
    assert existing.is_active is True
    assert existing.max_rides == 10


@pytest.mark.asyncio
async def test_update_quota_max_rides():
    """update_quota — updates max_rides."""
    quota_row = _make_quota()
    db = _make_db(scalar_one=quota_row)

    result = await update_quota(
        db,
        quota_id=1,
        account_id=ACCOUNT_ID,
        payload=QuotaUpdate(max_rides=20),
    )

    assert quota_row.max_rides == 20
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_quota_is_active():
    """update_quota — updates is_active."""
    quota_row = _make_quota()
    db = _make_db(scalar_one=quota_row)

    await update_quota(
        db,
        quota_id=1,
        account_id=ACCOUNT_ID,
        payload=QuotaUpdate(is_active=False),
    )

    assert quota_row.is_active is False


@pytest.mark.asyncio
async def test_update_quota_not_found_raises_404():
    """update_quota — not found raises 404."""
    db = _make_db(scalar_one=None)

    with pytest.raises(HTTPException) as exc_info:
        await update_quota(db, quota_id=999, account_id=ACCOUNT_ID, payload=QuotaUpdate())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_quota_sets_inactive():
    """deactivate_quota — sets is_active False."""
    quota_row = _make_quota(is_active=True)
    db = _make_db(scalar_one=quota_row)

    await deactivate_quota(db, quota_id=1, account_id=ACCOUNT_ID)

    assert quota_row.is_active is False
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_deactivate_quota_not_found_raises_404():
    """deactivate_quota — not found raises 404."""
    db = _make_db(scalar_one=None)

    with pytest.raises(HTTPException) as exc_info:
        await deactivate_quota(db, quota_id=999, account_id=ACCOUNT_ID)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_quota_hard_deletes():
    """delete_quota — hard deletes row."""
    quota_row = _make_quota()
    db = _make_db(scalar_one=quota_row)

    await delete_quota(db, quota_id=1, account_id=ACCOUNT_ID)

    db.delete.assert_called_once_with(quota_row)
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_quota_not_found_raises_404():
    """delete_quota — not found raises 404."""
    db = _make_db(scalar_one=None)

    with pytest.raises(HTTPException) as exc_info:
        await delete_quota(db, quota_id=999, account_id=ACCOUNT_ID)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_quota_returns_quota():
    """get_quota — returns quota."""
    quota_row = _make_quota()
    db = _make_db(scalar_one=quota_row)

    result = await get_quota(db, quota_id=1, account_id=ACCOUNT_ID)

    assert result.id == 1
    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_get_quota_not_found_raises_404():
    """get_quota — not found raises 404."""
    db = _make_db(scalar_one=None)

    with pytest.raises(HTTPException) as exc_info:
        await get_quota(db, quota_id=999, account_id=ACCOUNT_ID)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_member_quotas_returns_all_active():
    """list_member_quotas — returns all active quotas."""
    rows = [_make_quota(quota_id=1), _make_quota(quota_id=2, period="weekly")]
    db = _make_db(scalars_all=rows)

    result = await list_member_quotas(db, account_id=ACCOUNT_ID)

    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_member_quotas_filtered_by_member():
    """list_member_quotas — filtered by member_id."""
    rows = [_make_quota()]
    db = _make_db(scalars_all=rows)

    result = await list_member_quotas(db, account_id=ACCOUNT_ID, member_id=MEMBER_ID)

    assert len(result) == 1
    assert result[0].member_id == MEMBER_ID


@pytest.mark.asyncio
async def test_list_member_quotas_filtered_by_period():
    """list_member_quotas — filtered by period."""
    rows = [_make_quota(period="monthly")]
    db = _make_db(scalars_all=rows)

    result = await list_member_quotas(db, account_id=ACCOUNT_ID, period="monthly")

    assert len(result) == 1
    assert result[0].period == "monthly"


@pytest.mark.asyncio
async def test_get_quota_usage_no_active_quota():
    """get_quota_usage — no active quota returns quota_active=False."""
    db = _make_db(scalar_one=None)

    result = await get_quota_usage(db, account_id=ACCOUNT_ID, member_id=MEMBER_ID, period="daily")

    assert result.quota_active is False
    assert result.max_rides == 0
    assert result.current_period_rides == 0


@pytest.mark.asyncio
async def test_get_quota_usage_active_quota_with_rides():
    """get_quota_usage — active quota returns usage data."""
    quota_row = _make_quota(max_rides=10)

    # First execute call returns the quota row, second returns ride count
    call_count = [0]
    count_result = MagicMock()
    count_result.scalar_one.return_value = 3

    quota_result = MagicMock()
    quota_result.scalar_one_or_none.return_value = quota_row

    db = AsyncMock()

    async def execute_side_effect(query):
        call_count[0] += 1
        if call_count[0] == 1:
            return quota_result
        return count_result

    db.execute = AsyncMock(side_effect=execute_side_effect)

    result = await get_quota_usage(db, account_id=ACCOUNT_ID, member_id=MEMBER_ID, period="daily")

    assert result.quota_active is True
    assert result.max_rides == 10
    assert result.current_period_rides == 3
    assert result.remaining_rides == 7
    assert result.quota_exceeded is False


@pytest.mark.asyncio
async def test_get_quota_usage_quota_exceeded():
    """get_quota_usage — quota_exceeded when rides >= max."""
    quota_row = _make_quota(max_rides=3)

    call_count = [0]
    count_result = MagicMock()
    count_result.scalar_one.return_value = 5

    quota_result = MagicMock()
    quota_result.scalar_one_or_none.return_value = quota_row

    db = AsyncMock()

    async def execute_side_effect(query):
        call_count[0] += 1
        if call_count[0] == 1:
            return quota_result
        return count_result

    db.execute = AsyncMock(side_effect=execute_side_effect)

    result = await get_quota_usage(db, account_id=ACCOUNT_ID, member_id=MEMBER_ID, period="daily")

    assert result.quota_exceeded is True
    assert result.remaining_rides == 0  # floor at 0


@pytest.mark.asyncio
async def test_get_account_quota_summary():
    """get_account_quota_summary — enriches rows with usage."""
    rows = [_make_quota(max_rides=5)]

    scalars_result = MagicMock()
    scalars_result.scalars.return_value.all.return_value = rows

    count_result = MagicMock()
    count_result.scalar_one.return_value = 2

    call_count = [0]
    db = AsyncMock()

    async def execute_side_effect(query):
        call_count[0] += 1
        if call_count[0] == 1:
            return scalars_result
        return count_result

    db.execute = AsyncMock(side_effect=execute_side_effect)

    result = await get_account_quota_summary(db, account_id=ACCOUNT_ID)

    assert len(result) == 1
    assert result[0].current_period_rides == 2
    assert result[0].remaining_rides == 3
    assert result[0].quota_exceeded is False


# ===========================================================================
# 34–45  API layer tests
# ===========================================================================

_ROUTER = "app.api.v1.corporate_member_ride_quota"


@pytest.mark.asyncio
async def test_api_admin_set_quota_201():
    """POST /corporate/accounts/{id}/ride-quotas — 201 happy path."""
    from app.api.v1.corporate_member_ride_quota import admin_set_quota

    user = _mock_user()
    db = AsyncMock()
    payload = QuotaCreate(member_id=MEMBER_ID, period=QuotaPeriod.daily, max_rides=5)
    expected = _make_quota_response()

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.set_quota", new=AsyncMock(return_value=expected)):
        result = await admin_set_quota(account_id=ACCOUNT_ID, payload=payload, user=user, db=db)

    assert result.max_rides == 5
    assert result.member_id == MEMBER_ID


@pytest.mark.asyncio
async def test_api_admin_set_quota_409_propagated():
    """POST /corporate/accounts/{id}/ride-quotas — 409 propagated."""
    from app.api.v1.corporate_member_ride_quota import admin_set_quota

    user = _mock_user()
    db = AsyncMock()
    payload = QuotaCreate(member_id=MEMBER_ID, period=QuotaPeriod.daily, max_rides=5)

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.set_quota", new=AsyncMock(side_effect=HTTPException(status_code=409, detail="conflict"))):
        with pytest.raises(HTTPException) as exc_info:
            await admin_set_quota(account_id=ACCOUNT_ID, payload=payload, user=user, db=db)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_api_admin_list_quotas_200():
    """GET /corporate/accounts/{id}/ride-quotas — 200 list."""
    from app.api.v1.corporate_member_ride_quota import admin_list_quotas

    user = _mock_user()
    db = AsyncMock()
    quotas = [_make_quota_response()]

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.list_member_quotas", new=AsyncMock(return_value=quotas)):
        result = await admin_list_quotas(
            account_id=ACCOUNT_ID,
            member_id=None,
            period=None,
            active_only=True,
            user=user,
            db=db,
        )

    assert result.total == 1
    assert result.quotas[0].period == "daily"


@pytest.mark.asyncio
async def test_api_admin_quota_summary_200():
    """GET /corporate/accounts/{id}/ride-quotas/summary — 200."""
    from app.api.v1.corporate_member_ride_quota import admin_quota_summary

    user = _mock_user()
    db = AsyncMock()
    summary = [
        QuotaWithUsageResponse(
            id=1,
            account_id=ACCOUNT_ID,
            member_id=MEMBER_ID,
            period="daily",
            max_rides=5,
            is_active=True,
            created_by_id=ADMIN_ID,
            created_at=_NOW,
            updated_at=_NOW,
            current_period_rides=2,
            remaining_rides=3,
            quota_exceeded=False,
        )
    ]

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.get_account_quota_summary", new=AsyncMock(return_value=summary)):
        result = await admin_quota_summary(account_id=ACCOUNT_ID, user=user, db=db)

    assert len(result) == 1
    assert result[0].current_period_rides == 2


@pytest.mark.asyncio
async def test_api_admin_get_quota_200():
    """GET /corporate/accounts/{id}/ride-quotas/{id} — 200."""
    from app.api.v1.corporate_member_ride_quota import admin_get_quota

    user = _mock_user()
    db = AsyncMock()
    expected = _make_quota_response()

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.get_quota", new=AsyncMock(return_value=expected)):
        result = await admin_get_quota(account_id=ACCOUNT_ID, quota_id=1, user=user, db=db)

    assert result.id == 1


@pytest.mark.asyncio
async def test_api_admin_update_quota_200():
    """PUT /corporate/accounts/{id}/ride-quotas/{id} — 200."""
    from app.api.v1.corporate_member_ride_quota import admin_update_quota

    user = _mock_user()
    db = AsyncMock()
    updated = _make_quota_response(max_rides=20)
    payload = QuotaUpdate(max_rides=20)

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.update_quota", new=AsyncMock(return_value=updated)):
        result = await admin_update_quota(
            account_id=ACCOUNT_ID, quota_id=1, payload=payload, user=user, db=db
        )

    assert result.max_rides == 20


@pytest.mark.asyncio
async def test_api_admin_delete_quota_204():
    """DELETE /corporate/accounts/{id}/ride-quotas/{id} — 204."""
    from app.api.v1.corporate_member_ride_quota import admin_delete_quota

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)), \
         patch(f"{_ROUTER}.delete_quota", new=AsyncMock(return_value=None)):
        result = await admin_delete_quota(account_id=ACCOUNT_ID, quota_id=1, user=user, db=db)

    assert result is None


@pytest.mark.asyncio
async def test_api_member_check_quota_200():
    """GET /corporate/accounts/me/ride-quotas/check — 200 member."""
    from app.api.v1.corporate_member_ride_quota import member_check_quota

    user = _mock_user(user_id=MEMBER_ID)
    db = AsyncMock()
    mock_account = MagicMock()
    mock_account.id = ACCOUNT_ID
    check = QuotaCheckResponse(
        member_id=MEMBER_ID,
        period="daily",
        max_rides=5,
        current_period_rides=1,
        remaining_rides=4,
        quota_exceeded=False,
        quota_active=True,
    )

    with patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=mock_account)), \
         patch(f"{_ROUTER}.get_quota_usage", new=AsyncMock(return_value=check)):
        result = await member_check_quota(period=QuotaPeriod.daily, user=user, db=db)

    assert result.quota_active is True
    assert result.remaining_rides == 4


@pytest.mark.asyncio
async def test_api_member_check_quota_not_member_404():
    """GET /corporate/accounts/me/ride-quotas/check — 404 not a member."""
    from app.api.v1.corporate_member_ride_quota import member_check_quota

    user = _mock_user(user_id=MEMBER_ID)
    db = AsyncMock()

    with patch(f"{_ROUTER}.get_user_account", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc_info:
            await member_check_quota(period=QuotaPeriod.daily, user=user, db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_api_platform_admin_set_quota_201():
    """POST /admin/corporate/accounts/{id}/ride-quotas — 201."""
    from app.api.v1.corporate_member_ride_quota import platform_admin_set_quota

    admin = _mock_user()
    db = AsyncMock()
    payload = QuotaCreate(member_id=MEMBER_ID, period=QuotaPeriod.weekly, max_rides=15)
    expected = _make_quota_response(period="weekly", max_rides=15)

    with patch(f"{_ROUTER}.set_quota", new=AsyncMock(return_value=expected)):
        result = await platform_admin_set_quota(account_id=ACCOUNT_ID, payload=payload, admin=admin, db=db)

    assert result.max_rides == 15
    assert result.period == "weekly"


@pytest.mark.asyncio
async def test_api_platform_admin_list_quotas_200():
    """GET /admin/corporate/accounts/{id}/ride-quotas — 200."""
    from app.api.v1.corporate_member_ride_quota import platform_admin_list_quotas

    admin = _mock_user()
    db = AsyncMock()
    quotas = [_make_quota_response(), _make_quota_response(quota_id=2, period="weekly")]

    with patch(f"{_ROUTER}.list_member_quotas", new=AsyncMock(return_value=quotas)):
        result = await platform_admin_list_quotas(
            account_id=ACCOUNT_ID,
            member_id=None,
            period=None,
            active_only=False,
            _admin=admin,
            db=db,
        )

    assert result.total == 2


@pytest.mark.asyncio
async def test_api_platform_admin_exceeded_quotas_200():
    """GET /admin/corporate/ride-quotas/exceeded — 200 returns exceeded."""
    from app.api.v1.corporate_member_ride_quota import platform_admin_exceeded_quotas

    admin = _mock_user()
    db = AsyncMock()

    quota_row = _make_quota(max_rides=3)
    scalars_result = MagicMock()
    scalars_result.scalars.return_value.all.return_value = [quota_row]

    count_result = MagicMock()
    count_result.scalar_one.return_value = 5  # exceeded

    call_count = [0]

    async def execute_side_effect(query):
        call_count[0] += 1
        if call_count[0] == 1:
            return scalars_result
        return count_result

    db.execute = AsyncMock(side_effect=execute_side_effect)

    result = await platform_admin_exceeded_quotas(_admin=admin, db=db)

    assert len(result) == 1
    assert result[0].quota_exceeded is True
    assert result[0].current_period_rides == 5
