"""Tests for the Corporate Guest Pass feature.

Service tests (async, mocked DB):
  1.  create_guest_pass — success with required fields only
  2.  create_guest_pass — success with all optional fields
  3.  create_guest_pass — sets uses_remaining = max_uses when max_uses given
  4.  create_guest_pass — uses_remaining is None when max_uses is None
  5.  get_guest_pass — success
  6.  get_guest_pass — wrong account → 404
  7.  list_guest_passes — all passes returned
  8.  list_guest_passes — filter by status
  9.  update_guest_pass — update label and valid_until
  10. update_guest_pass — not found → 404
  11. update_guest_pass — fails on revoked pass → 409
  12. update_guest_pass — fails on exhausted pass → 409
  13. revoke_guest_pass — success (status → revoked, revoked_at set)
  14. revoke_guest_pass — not found → 404
  15. revoke_guest_pass — already revoked → 409
  16. validate_guest_pass_token — valid pass
  17. validate_guest_pass_token — expired (valid_until past)
  18. validate_guest_pass_token — revoked
  19. validate_guest_pass_token — exhausted
  20. validate_guest_pass_token — unknown token → is_valid=False (not 404)
  21. validate_guest_pass_token — invalid UUID format → is_valid=False
  22. validate_guest_pass_token — not yet valid (valid_from in future)
  23. use_guest_pass — decrements uses_remaining
  24. use_guest_pass — last use sets status to exhausted
  25. use_guest_pass — already exhausted → 400
  26. use_guest_pass — revoked → 400
  27. use_guest_pass — unlimited uses (uses_remaining stays None)
  28. get_guest_pass_rides — returns ride IDs
  29. get_guest_pass_rides — not found → 404

Schema tests (sync):
  30. GuestPassCreate — valid minimal
  31. GuestPassCreate — max_uses < 1 → ValidationError
  32. GuestPassCreate — valid_until in past → ValidationError
  33. GuestPassUpdate — all fields optional
  34. GuestPassResponse — from_attributes
  35. GuestPassValidationResponse — is_valid=False with reason

API layer tests (asyncio, service patched):
  36. POST /corporate/accounts/me/guest-passes — 201
  37. GET  /corporate/accounts/me/guest-passes — 200
  38. GET  /corporate/accounts/me/guest-passes/{id} — 200
  39. PATCH /corporate/accounts/me/guest-passes/{id} — 200
  40. DELETE /corporate/accounts/me/guest-passes/{id} — 200 (revoked)
  41. GET  /guest-pass/{token} — valid token
  42. GET  /guest-pass/{token} — invalid token → is_valid=False
  43. GET  /admin/corporate/guest-passes — 200
  44. GET  /admin/corporate/accounts/{id}/guest-passes — 200
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_guest_pass import CorporateGuestPass, GuestPassStatus
from app.schemas.corporate_guest_pass import (
    GuestPassCreate,
    GuestPassResponse,
    GuestPassUpdate,
    GuestPassValidationResponse,
)
from app.services.corporate_guest_pass import (
    create_guest_pass,
    get_guest_pass,
    get_guest_pass_rides,
    list_guest_passes,
    revoke_guest_pass,
    update_guest_pass,
    use_guest_pass,
    validate_guest_pass_token,
)


# ---------------------------------------------------------------------------
# Shared constants and helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
FUTURE = NOW + timedelta(days=30)
PAST = NOW - timedelta(days=1)
ACCOUNT_ID = 10
OTHER_ACCOUNT_ID = 20
EMPLOYEE_ID = 1
ADMIN_ID = 2
PASS_ID = uuid.uuid4()
TOKEN = uuid.uuid4()
RIDE_ID = 99


def _make_pass(
    pass_id: uuid.UUID = PASS_ID,
    account_id: int = ACCOUNT_ID,
    employee_id: int = EMPLOYEE_ID,
    token: uuid.UUID = TOKEN,
    label: str = "Client: ACME Interview",
    max_uses: int | None = 3,
    uses_remaining: int | None = 3,
    max_ride_budget_usd=None,
    trip_purpose_id: int | None = None,
    cost_center_id: int | None = None,
    valid_from: datetime = NOW,
    valid_until: datetime = FUTURE,
    status: GuestPassStatus = GuestPassStatus.ACTIVE,
    revoked_at: datetime | None = None,
    revoked_by_id: int | None = None,
) -> MagicMock:
    p = MagicMock(spec=CorporateGuestPass)
    p.id = pass_id
    p.account_id = account_id
    p.created_by_employee_id = employee_id
    p.token = token
    p.label = label
    p.max_uses = max_uses
    p.uses_remaining = uses_remaining
    p.max_ride_budget_usd = max_ride_budget_usd
    p.trip_purpose_id = trip_purpose_id
    p.cost_center_id = cost_center_id
    p.valid_from = valid_from
    p.valid_until = valid_until
    p.status = status
    p.revoked_at = revoked_at
    p.revoked_by_id = revoked_by_id
    p.created_at = NOW
    p.updated_at = NOW
    return p


def _scalar_result(value) -> MagicMock:
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    res.scalar.return_value = value
    return res


def _scalars_result(rows: list) -> MagicMock:
    res = MagicMock()
    res.scalars.return_value.all.return_value = rows
    res.scalars.return_value.all = MagicMock(return_value=rows)
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = rows
    res.scalars.return_value = scalars_mock
    return res


def _make_ride_mock(ride_id: int = RIDE_ID) -> MagicMock:
    r = MagicMock()
    r.id = ride_id
    r.guest_pass_id = None
    return r


# ---------------------------------------------------------------------------
# 1. create_guest_pass — success with required fields only
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_guest_pass_required_fields():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    data = GuestPassCreate(
        label="Visitor: John Smith",
        valid_until=FUTURE,
    )
    result = await create_guest_pass(db, ACCOUNT_ID, EMPLOYEE_ID, data)

    db.add.assert_called_once()
    db.flush.assert_awaited_once()
    assert result.label == "Visitor: John Smith"
    assert result.account_id == ACCOUNT_ID
    assert result.created_by_employee_id == EMPLOYEE_ID
    assert result.max_uses is None
    assert result.uses_remaining is None
    assert result.status == GuestPassStatus.ACTIVE


# ---------------------------------------------------------------------------
# 2. create_guest_pass — success with all optional fields
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_guest_pass_all_optional_fields():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    data = GuestPassCreate(
        label="Client: ACME Interview",
        max_uses=5,
        max_ride_budget_usd=Decimal("50.00"),
        trip_purpose_id=101,
        cost_center_id=202,
        valid_from=NOW,
        valid_until=FUTURE,
    )
    result = await create_guest_pass(db, ACCOUNT_ID, EMPLOYEE_ID, data)

    assert result.max_uses == 5
    assert result.uses_remaining == 5
    assert result.trip_purpose_id == 101
    assert result.cost_center_id == 202


# ---------------------------------------------------------------------------
# 3. create_guest_pass — sets uses_remaining = max_uses when max_uses given
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_guest_pass_uses_remaining_equals_max_uses():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    data = GuestPassCreate(label="Test", max_uses=10, valid_until=FUTURE)
    result = await create_guest_pass(db, ACCOUNT_ID, EMPLOYEE_ID, data)

    assert result.uses_remaining == result.max_uses == 10


# ---------------------------------------------------------------------------
# 4. create_guest_pass — uses_remaining is None when max_uses is None
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_guest_pass_unlimited():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    data = GuestPassCreate(label="Unlimited Pass", valid_until=FUTURE)
    result = await create_guest_pass(db, ACCOUNT_ID, EMPLOYEE_ID, data)

    assert result.max_uses is None
    assert result.uses_remaining is None


# ---------------------------------------------------------------------------
# 5. get_guest_pass — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_guest_pass_success():
    db = AsyncMock()
    guest_pass = _make_pass()
    db.execute.return_value = _scalar_result(guest_pass)

    result = await get_guest_pass(db, PASS_ID, ACCOUNT_ID)
    assert result is guest_pass


# ---------------------------------------------------------------------------
# 6. get_guest_pass — wrong account → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_guest_pass_wrong_account():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_guest_pass(db, PASS_ID, OTHER_ACCOUNT_ID)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 7. list_guest_passes — all passes returned
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_guest_passes_all():
    db = AsyncMock()
    passes = [_make_pass(), _make_pass(pass_id=uuid.uuid4())]
    db.execute.return_value = _scalars_result(passes)

    results = await list_guest_passes(db, ACCOUNT_ID)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# 8. list_guest_passes — filter by status
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_guest_passes_status_filter():
    db = AsyncMock()
    active_pass = _make_pass(status=GuestPassStatus.ACTIVE)
    db.execute.return_value = _scalars_result([active_pass])

    results = await list_guest_passes(db, ACCOUNT_ID, status_filter=GuestPassStatus.ACTIVE)
    assert len(results) == 1
    assert results[0].status == GuestPassStatus.ACTIVE


# ---------------------------------------------------------------------------
# 9. update_guest_pass — update label and valid_until
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_guest_pass_success():
    db = AsyncMock()
    guest_pass = _make_pass()
    db.execute.return_value = _scalar_result(guest_pass)
    db.flush = AsyncMock()

    new_until = FUTURE + timedelta(days=7)
    data = GuestPassUpdate(label="Updated Label", valid_until=new_until)
    result = await update_guest_pass(db, PASS_ID, ACCOUNT_ID, data)

    assert result is guest_pass
    assert guest_pass.label == "Updated Label"
    assert guest_pass.valid_until == new_until
    db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# 10. update_guest_pass — not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_guest_pass_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await update_guest_pass(db, PASS_ID, ACCOUNT_ID, GuestPassUpdate())

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 11. update_guest_pass — fails on revoked pass → 409
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_guest_pass_revoked():
    db = AsyncMock()
    guest_pass = _make_pass(status=GuestPassStatus.REVOKED)
    db.execute.return_value = _scalar_result(guest_pass)

    with pytest.raises(HTTPException) as exc_info:
        await update_guest_pass(db, PASS_ID, ACCOUNT_ID, GuestPassUpdate(label="New"))

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 12. update_guest_pass — fails on exhausted pass → 409
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_guest_pass_exhausted():
    db = AsyncMock()
    guest_pass = _make_pass(status=GuestPassStatus.EXHAUSTED)
    db.execute.return_value = _scalar_result(guest_pass)

    with pytest.raises(HTTPException) as exc_info:
        await update_guest_pass(db, PASS_ID, ACCOUNT_ID, GuestPassUpdate(label="New"))

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 13. revoke_guest_pass — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_revoke_guest_pass_success():
    db = AsyncMock()
    guest_pass = _make_pass(status=GuestPassStatus.ACTIVE)
    db.execute.return_value = _scalar_result(guest_pass)
    db.flush = AsyncMock()

    result = await revoke_guest_pass(db, PASS_ID, ACCOUNT_ID, ADMIN_ID)

    assert result is guest_pass
    assert guest_pass.status == GuestPassStatus.REVOKED
    assert guest_pass.revoked_at is not None
    assert guest_pass.revoked_by_id == ADMIN_ID
    db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# 14. revoke_guest_pass — not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_revoke_guest_pass_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await revoke_guest_pass(db, PASS_ID, ACCOUNT_ID, ADMIN_ID)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 15. revoke_guest_pass — already revoked → 409
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_revoke_guest_pass_already_revoked():
    db = AsyncMock()
    guest_pass = _make_pass(status=GuestPassStatus.REVOKED)
    db.execute.return_value = _scalar_result(guest_pass)

    with pytest.raises(HTTPException) as exc_info:
        await revoke_guest_pass(db, PASS_ID, ACCOUNT_ID, ADMIN_ID)

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 16. validate_guest_pass_token — valid pass
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_validate_token_valid():
    db = AsyncMock()
    guest_pass = _make_pass(status=GuestPassStatus.ACTIVE)
    account_mock = MagicMock()
    account_mock.name = "ACME Corp"

    db.execute.side_effect = [
        _scalar_result(guest_pass),  # fetch by token
        _scalar_result(account_mock),  # fetch account
    ]

    result = await validate_guest_pass_token(db, str(TOKEN))

    assert result["is_valid"] is True
    assert result["reason"] is None
    assert result["label"] == guest_pass.label
    assert result["account_name"] == "ACME Corp"


# ---------------------------------------------------------------------------
# 17. validate_guest_pass_token — expired
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_validate_token_expired():
    db = AsyncMock()
    guest_pass = _make_pass(
        status=GuestPassStatus.ACTIVE,
        valid_until=PAST,
    )
    db.execute.return_value = _scalar_result(guest_pass)

    result = await validate_guest_pass_token(db, str(TOKEN))

    assert result["is_valid"] is False
    assert "expired" in result["reason"].lower()


# ---------------------------------------------------------------------------
# 18. validate_guest_pass_token — revoked
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_validate_token_revoked():
    db = AsyncMock()
    guest_pass = _make_pass(status=GuestPassStatus.REVOKED)
    db.execute.return_value = _scalar_result(guest_pass)

    result = await validate_guest_pass_token(db, str(TOKEN))

    assert result["is_valid"] is False
    assert "revoked" in result["reason"].lower()


# ---------------------------------------------------------------------------
# 19. validate_guest_pass_token — exhausted
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_validate_token_exhausted():
    db = AsyncMock()
    guest_pass = _make_pass(status=GuestPassStatus.EXHAUSTED)
    db.execute.return_value = _scalar_result(guest_pass)

    result = await validate_guest_pass_token(db, str(TOKEN))

    assert result["is_valid"] is False
    assert "no uses remaining" in result["reason"].lower()


# ---------------------------------------------------------------------------
# 20. validate_guest_pass_token — unknown token → is_valid=False (not 404)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_validate_token_unknown():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    result = await validate_guest_pass_token(db, str(uuid.uuid4()))

    assert result["is_valid"] is False
    assert result["reason"] is not None


# ---------------------------------------------------------------------------
# 21. validate_guest_pass_token — invalid UUID format → is_valid=False
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_validate_token_invalid_format():
    db = AsyncMock()

    result = await validate_guest_pass_token(db, "not-a-uuid-at-all!!")

    assert result["is_valid"] is False
    assert "invalid" in result["reason"].lower()


# ---------------------------------------------------------------------------
# 22. validate_guest_pass_token — not yet valid
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_validate_token_not_yet_valid():
    db = AsyncMock()
    future_start = NOW + timedelta(hours=1)
    guest_pass = _make_pass(
        status=GuestPassStatus.ACTIVE,
        valid_from=future_start,
        valid_until=FUTURE,
    )
    db.execute.return_value = _scalar_result(guest_pass)

    result = await validate_guest_pass_token(db, str(TOKEN))

    assert result["is_valid"] is False
    assert "not yet valid" in result["reason"].lower()


# ---------------------------------------------------------------------------
# 23. use_guest_pass — decrements uses_remaining
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_use_guest_pass_decrements():
    db = AsyncMock()
    guest_pass = _make_pass(max_uses=3, uses_remaining=3, status=GuestPassStatus.ACTIVE)
    account_mock = MagicMock()
    account_mock.name = "ACME Corp"
    ride_mock = _make_ride_mock()

    db.execute.side_effect = [
        _scalar_result(guest_pass),   # validate: fetch by token
        _scalar_result(account_mock),  # validate: fetch account
        _scalar_result(guest_pass),    # use: fetch by token
        _scalar_result(ride_mock),     # fetch ride
    ]
    db.flush = AsyncMock()

    result = await use_guest_pass(db, str(TOKEN), RIDE_ID)

    assert guest_pass.uses_remaining == 2
    assert guest_pass.status == GuestPassStatus.ACTIVE
    assert result is guest_pass


# ---------------------------------------------------------------------------
# 24. use_guest_pass — last use sets status to exhausted
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_use_guest_pass_last_use_exhausts():
    db = AsyncMock()
    guest_pass = _make_pass(max_uses=1, uses_remaining=1, status=GuestPassStatus.ACTIVE)
    account_mock = MagicMock()
    account_mock.name = "ACME Corp"
    ride_mock = _make_ride_mock()

    db.execute.side_effect = [
        _scalar_result(guest_pass),    # validate: fetch by token
        _scalar_result(account_mock),  # validate: fetch account
        _scalar_result(guest_pass),    # use: fetch by token
        _scalar_result(ride_mock),     # fetch ride
    ]
    db.flush = AsyncMock()

    result = await use_guest_pass(db, str(TOKEN), RIDE_ID)

    assert guest_pass.uses_remaining == 0
    assert guest_pass.status == GuestPassStatus.EXHAUSTED


# ---------------------------------------------------------------------------
# 25. use_guest_pass — already exhausted → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_use_guest_pass_already_exhausted():
    db = AsyncMock()
    guest_pass = _make_pass(status=GuestPassStatus.EXHAUSTED)
    db.execute.return_value = _scalar_result(guest_pass)

    with pytest.raises(HTTPException) as exc_info:
        await use_guest_pass(db, str(TOKEN), RIDE_ID)

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 26. use_guest_pass — revoked → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_use_guest_pass_revoked():
    db = AsyncMock()
    guest_pass = _make_pass(status=GuestPassStatus.REVOKED)
    db.execute.return_value = _scalar_result(guest_pass)

    with pytest.raises(HTTPException) as exc_info:
        await use_guest_pass(db, str(TOKEN), RIDE_ID)

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 27. use_guest_pass — unlimited uses (uses_remaining stays None)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_use_guest_pass_unlimited():
    db = AsyncMock()
    guest_pass = _make_pass(max_uses=None, uses_remaining=None, status=GuestPassStatus.ACTIVE)
    account_mock = MagicMock()
    account_mock.name = "ACME Corp"
    ride_mock = _make_ride_mock()

    db.execute.side_effect = [
        _scalar_result(guest_pass),    # validate: fetch by token
        _scalar_result(account_mock),  # validate: fetch account
        _scalar_result(guest_pass),    # use: fetch by token
        _scalar_result(ride_mock),     # fetch ride
    ]
    db.flush = AsyncMock()

    result = await use_guest_pass(db, str(TOKEN), RIDE_ID)

    # uses_remaining stays None for unlimited passes
    assert guest_pass.uses_remaining is None
    assert guest_pass.status == GuestPassStatus.ACTIVE


# ---------------------------------------------------------------------------
# 28. get_guest_pass_rides — returns ride IDs
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_guest_pass_rides_success():
    db = AsyncMock()
    guest_pass = _make_pass()

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [RIDE_ID, RIDE_ID + 1]
    rides_result = MagicMock()
    rides_result.scalars.return_value = scalars_mock

    db.execute.side_effect = [
        _scalar_result(guest_pass),  # fetch guest pass
        rides_result,                # fetch ride IDs
    ]

    ride_ids = await get_guest_pass_rides(db, PASS_ID, ACCOUNT_ID)
    assert RIDE_ID in ride_ids


# ---------------------------------------------------------------------------
# 29. get_guest_pass_rides — pass not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_guest_pass_rides_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_guest_pass_rides(db, PASS_ID, OTHER_ACCOUNT_ID)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Schema tests (sync)
# ---------------------------------------------------------------------------


def test_guest_pass_create_valid_minimal():
    """30. GuestPassCreate — valid minimal."""
    data = GuestPassCreate(label="Visitor", valid_until=FUTURE)
    assert data.label == "Visitor"
    assert data.max_uses is None
    assert data.trip_purpose_id is None


def test_guest_pass_create_max_uses_invalid():
    """31. GuestPassCreate — max_uses < 1 → ValidationError."""
    with pytest.raises(ValidationError):
        GuestPassCreate(label="Bad", max_uses=0, valid_until=FUTURE)


def test_guest_pass_create_valid_until_past():
    """32. GuestPassCreate — valid_until in past → ValidationError."""
    with pytest.raises(ValidationError):
        GuestPassCreate(label="Expired", valid_until=PAST)


def test_guest_pass_update_all_optional():
    """33. GuestPassUpdate — all fields optional."""
    data = GuestPassUpdate()
    assert data.label is None
    assert data.max_uses is None
    assert data.valid_until is None


def test_guest_pass_response_from_attributes():
    """34. GuestPassResponse — from_attributes."""
    resp = GuestPassResponse(
        id=PASS_ID,
        account_id=ACCOUNT_ID,
        created_by_employee_id=EMPLOYEE_ID,
        token=TOKEN,
        label="Test Pass",
        max_uses=5,
        uses_remaining=3,
        max_ride_budget_usd=Decimal("75.00"),
        trip_purpose_id=None,
        cost_center_id=None,
        valid_from=NOW,
        valid_until=FUTURE,
        status="active",
        revoked_at=None,
        revoked_by_id=None,
        created_at=NOW,
        updated_at=NOW,
    )
    assert resp.id == PASS_ID
    assert resp.label == "Test Pass"
    assert resp.uses_remaining == 3


def test_guest_pass_validation_response_invalid():
    """35. GuestPassValidationResponse — is_valid=False with reason."""
    resp = GuestPassValidationResponse(
        is_valid=False,
        reason="This guest pass has been revoked.",
        label="Old Pass",
        max_ride_budget_usd=None,
        account_name=None,
    )
    assert resp.is_valid is False
    assert "revoked" in resp.reason


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

_ROUTER = "app.api.v1.corporate_guest_pass"


def _mock_user(user_id: int = EMPLOYEE_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


def _make_pass_response() -> GuestPassResponse:
    return GuestPassResponse(
        id=PASS_ID,
        account_id=ACCOUNT_ID,
        created_by_employee_id=EMPLOYEE_ID,
        token=TOKEN,
        label="Client: ACME Interview",
        max_uses=3,
        uses_remaining=3,
        max_ride_budget_usd=None,
        trip_purpose_id=None,
        cost_center_id=None,
        valid_from=NOW,
        valid_until=FUTURE,
        status="active",
        revoked_at=None,
        revoked_by_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _make_pass_orm() -> MagicMock:
    return _make_pass()


@pytest.mark.asyncio
async def test_api_create_guest_pass():
    """36. POST /corporate/accounts/me/guest-passes — 201."""
    from app.api.v1.corporate_guest_pass import create_my_guest_pass

    user = _mock_user()
    db = AsyncMock()
    data = GuestPassCreate(label="New Guest", valid_until=FUTURE)
    guest_pass_orm = _make_pass_orm()

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.create_guest_pass", new=AsyncMock(return_value=guest_pass_orm)):
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        result = await create_my_guest_pass(data=data, user=user, db=db)

    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_api_list_guest_passes():
    """37. GET /corporate/accounts/me/guest-passes — 200."""
    from app.api.v1.corporate_guest_pass import list_my_guest_passes

    user = _mock_user()
    db = AsyncMock()
    passes = [_make_pass_orm(), _make_pass_orm()]

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.list_guest_passes", new=AsyncMock(return_value=passes)):
        result = await list_my_guest_passes(
            status_filter=None, skip=0, limit=50, user=user, db=db
        )

    assert len(result) == 2


@pytest.mark.asyncio
async def test_api_get_guest_pass():
    """38. GET /corporate/accounts/me/guest-passes/{id} — 200."""
    from app.api.v1.corporate_guest_pass import get_my_guest_pass

    user = _mock_user()
    db = AsyncMock()
    guest_pass_orm = _make_pass_orm()

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.get_guest_pass", new=AsyncMock(return_value=guest_pass_orm)):
        result = await get_my_guest_pass(pass_id=PASS_ID, user=user, db=db)

    assert result.id == PASS_ID


@pytest.mark.asyncio
async def test_api_update_guest_pass():
    """39. PATCH /corporate/accounts/me/guest-passes/{id} — 200."""
    from app.api.v1.corporate_guest_pass import update_my_guest_pass

    user = _mock_user()
    db = AsyncMock()
    data = GuestPassUpdate(label="Updated Label")
    guest_pass_orm = _make_pass_orm()
    guest_pass_orm.label = "Updated Label"

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.update_guest_pass", new=AsyncMock(return_value=guest_pass_orm)):
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        result = await update_my_guest_pass(pass_id=PASS_ID, data=data, user=user, db=db)

    assert result.label == "Updated Label"


@pytest.mark.asyncio
async def test_api_revoke_guest_pass():
    """40. DELETE /corporate/accounts/me/guest-passes/{id} — 200 with revoked pass."""
    from app.api.v1.corporate_guest_pass import revoke_my_guest_pass

    user = _mock_user()
    db = AsyncMock()
    revoked_pass = _make_pass_orm()
    revoked_pass.status = GuestPassStatus.REVOKED
    revoked_pass.revoked_at = NOW
    revoked_pass.revoked_by_id = EMPLOYEE_ID

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.revoke_guest_pass", new=AsyncMock(return_value=revoked_pass)):
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        result = await revoke_my_guest_pass(pass_id=PASS_ID, user=user, db=db)

    assert result.status == GuestPassStatus.REVOKED


@pytest.mark.asyncio
async def test_api_validate_token_valid():
    """41. GET /guest-pass/{token} — valid token."""
    from app.api.v1.corporate_guest_pass import validate_token

    db = AsyncMock()
    validation_result = {
        "is_valid": True,
        "reason": None,
        "label": "Client: ACME",
        "max_ride_budget_usd": Decimal("50.00"),
        "account_name": "ACME Corp",
    }

    with patch(f"{_ROUTER}.validate_guest_pass_token", new=AsyncMock(return_value=validation_result)):
        result = await validate_token(token=str(TOKEN), db=db)

    assert result.is_valid is True
    assert result.account_name == "ACME Corp"


@pytest.mark.asyncio
async def test_api_validate_token_invalid():
    """42. GET /guest-pass/{token} — invalid/unknown token → is_valid=False."""
    from app.api.v1.corporate_guest_pass import validate_token

    db = AsyncMock()
    validation_result = {
        "is_valid": False,
        "reason": "Token not found.",
        "label": None,
        "max_ride_budget_usd": None,
        "account_name": None,
    }

    with patch(f"{_ROUTER}.validate_guest_pass_token", new=AsyncMock(return_value=validation_result)):
        result = await validate_token(token="unknown", db=db)

    assert result.is_valid is False
    assert result.reason == "Token not found."


@pytest.mark.asyncio
async def test_api_admin_list_all_guest_passes():
    """43. GET /admin/corporate/guest-passes — 200."""
    from app.api.v1.corporate_guest_pass import admin_list_all_guest_passes

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    passes = [_make_pass_orm()]

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = passes
    exec_result = MagicMock()
    exec_result.scalars.return_value = scalars_mock
    db.execute.return_value = exec_result

    result = await admin_list_all_guest_passes(
        status_filter=None, skip=0, limit=50, _admin=admin, db=db
    )

    assert len(result) == 1


@pytest.mark.asyncio
async def test_api_admin_list_account_guest_passes():
    """44. GET /admin/corporate/accounts/{id}/guest-passes — 200."""
    from app.api.v1.corporate_guest_pass import admin_list_account_guest_passes

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    passes = [_make_pass_orm()]

    with patch(f"{_ROUTER}.list_guest_passes", new=AsyncMock(return_value=passes)):
        result = await admin_list_account_guest_passes(
            account_id=ACCOUNT_ID, status_filter=None, skip=0, limit=50,
            _admin=admin, db=db
        )

    assert len(result) == 1
    assert result[0].account_id == ACCOUNT_ID
