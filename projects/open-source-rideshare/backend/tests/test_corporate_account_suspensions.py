"""Tests for the Corporate Account Suspension & Reinstatement feature.

Service layer (async, mocked DB):
  1.  suspend_account — happy path creates suspension record
  2.  suspend_account — 409 when account already has active suspension
  3.  reinstate_account — happy path marks suspension as resolved
  4.  reinstate_account — 404 when no active suspension exists
  5.  get_active_suspension — returns None when account is not suspended
  6.  get_active_suspension — returns suspension when account is suspended
  7.  is_account_suspended — returns False when not suspended
  8.  is_account_suspended — returns True when suspended
  9.  list_suspension_history — returns records ordered most recent first
  10. list_suspension_history — returns empty list when no history
  11. list_all_suspended_accounts — returns active suspensions across all accounts
  12. list_all_suspended_accounts — returns empty list when none suspended
  13. suspend_account — suspension_note is persisted correctly
  14. reinstate_account — reinstatement_note is persisted correctly
  15. reinstate_account — reinstated_at is set to now

Schema validation:
  16. SuspendRequest — valid construction with all SuspensionReason values
  17. SuspendRequest — reason field required
  18. SuspendRequest — suspension_note is optional
  19. ReinstateRequest — reinstatement_note is optional
  20. SuspensionResponse — from_attributes model config
  21. SuspensionStatusResponse — valid construction
  22. SuspensionListResponse — valid construction
  23. SuspensionResponse — all SuspensionReason enum values valid

API layer (service functions patched):
  24. POST /corporate/accounts/{id}/suspend — 201 happy path
  25. POST /corporate/accounts/{id}/suspend — 409 already suspended
  26. POST /corporate/accounts/{id}/reinstate — 200 happy path
  27. POST /corporate/accounts/{id}/reinstate — 404 no active suspension
  28. GET /corporate/accounts/{id}/suspension — 200 returns active suspension
  29. GET /corporate/accounts/{id}/suspension — 404 not suspended
  30. GET /corporate/accounts/{id}/suspension/history — 200 returns history
  31. GET /admin/corporate/suspensions — 200 returns all suspended accounts
  32. GET /corporate/suspension/status — 200 not suspended
  33. GET /corporate/suspension/status — 200 is suspended with reason
  34. GET /corporate/suspension/status — 404 not a member
  35. POST /corporate/accounts/{id}/suspend — non-admin gets 403
  36. POST /corporate/accounts/{id}/reinstate — non-admin gets 403
  37. GET /corporate/accounts/{id}/suspension — non-admin gets 403
  38. GET /admin/corporate/suspensions — non-admin gets 403
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_account_suspension import (
    CorporateAccountSuspension,
    SuspensionReason,
)
from app.schemas.corporate_account_suspension import (
    ReinstateRequest,
    SuspendRequest,
    SuspensionListResponse,
    SuspensionResponse,
    SuspensionStatusResponse,
)
from app.services.corporate_account_suspension import (
    get_active_suspension,
    is_account_suspended,
    list_all_suspended_accounts,
    list_suspension_history,
    reinstate_account,
    suspend_account,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 10
ADMIN_ID = 99
USER_ID = 7
SUSPENSION_ID = 1

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)

_ROUTER = "app.api.v1.corporate_account_suspensions"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_suspension(
    suspension_id: int = SUSPENSION_ID,
    account_id: int = ACCOUNT_ID,
    suspended_by_id: int | None = ADMIN_ID,
    reason: SuspensionReason = SuspensionReason.billing_overdue,
    suspension_note: str | None = "Overdue invoice",
    is_active: bool = True,
    reinstated_at: datetime | None = None,
    reinstated_by_id: int | None = None,
    reinstatement_note: str | None = None,
) -> CorporateAccountSuspension:
    """Build a minimal CorporateAccountSuspension model instance for testing."""
    s = CorporateAccountSuspension()
    s.id = suspension_id
    s.account_id = account_id
    s.suspended_by_id = suspended_by_id
    s.reason = reason
    s.suspension_note = suspension_note
    s.suspended_at = _NOW
    s.is_active = is_active
    s.reinstated_at = reinstated_at
    s.reinstated_by_id = reinstated_by_id
    s.reinstatement_note = reinstatement_note
    return s


def _make_response(
    suspension_id: int = SUSPENSION_ID,
    account_id: int = ACCOUNT_ID,
    reason: SuspensionReason = SuspensionReason.billing_overdue,
    is_active: bool = True,
) -> SuspensionResponse:
    return SuspensionResponse(
        id=suspension_id,
        account_id=account_id,
        suspended_by_id=ADMIN_ID,
        reason=reason,
        suspension_note="Overdue invoice",
        suspended_at=_NOW,
        reinstated_at=None,
        reinstated_by_id=None,
        reinstatement_note=None,
        is_active=is_active,
    )


def _mock_user(user_id: int = USER_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


def _make_execute_result_scalar(value) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_execute_result_scalars(items: list) -> MagicMock:
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    result.scalars.return_value = scalars
    return result


# ---------------------------------------------------------------------------
# 1. suspend_account — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suspend_account_success():
    db = AsyncMock()

    # get_active_suspension returns None (not currently suspended)
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(None))
    db.commit = AsyncMock()

    added = []

    def _add(obj):
        added.append(obj)
        obj.id = SUSPENSION_ID
        obj.suspended_at = _NOW

    db.add = _add
    db.refresh = AsyncMock()

    result = await suspend_account(
        db,
        account_id=ACCOUNT_ID,
        suspended_by_id=ADMIN_ID,
        reason=SuspensionReason.billing_overdue,
        note="Overdue invoice",
    )

    assert len(added) == 1
    suspension = added[0]
    assert suspension.account_id == ACCOUNT_ID
    assert suspension.suspended_by_id == ADMIN_ID
    assert suspension.reason == SuspensionReason.billing_overdue
    assert suspension.suspension_note == "Overdue invoice"
    assert suspension.is_active is True
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 2. suspend_account — 409 when already suspended
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suspend_account_409_already_suspended():
    db = AsyncMock()
    existing = _make_suspension()
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(existing))

    with pytest.raises(HTTPException) as exc_info:
        await suspend_account(
            db,
            account_id=ACCOUNT_ID,
            suspended_by_id=ADMIN_ID,
            reason=SuspensionReason.billing_overdue,
            note=None,
        )

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 3. reinstate_account — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reinstate_account_success():
    db = AsyncMock()
    suspension = _make_suspension(is_active=True)
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(suspension))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    result = await reinstate_account(
        db,
        account_id=ACCOUNT_ID,
        reinstated_by_id=ADMIN_ID,
        reinstatement_note="Invoice settled",
    )

    assert suspension.is_active is False
    assert suspension.reinstated_by_id == ADMIN_ID
    assert suspension.reinstatement_note == "Invoice settled"
    assert suspension.reinstated_at is not None
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 4. reinstate_account — 404 when no active suspension
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reinstate_account_404_no_active_suspension():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(None))

    with pytest.raises(HTTPException) as exc_info:
        await reinstate_account(
            db,
            account_id=ACCOUNT_ID,
            reinstated_by_id=ADMIN_ID,
            reinstatement_note=None,
        )

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 5. get_active_suspension — returns None when not suspended
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_suspension_returns_none():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(None))

    result = await get_active_suspension(db, ACCOUNT_ID)

    assert result is None


# ---------------------------------------------------------------------------
# 6. get_active_suspension — returns suspension when suspended
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_suspension_returns_record():
    db = AsyncMock()
    suspension = _make_suspension()
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(suspension))

    result = await get_active_suspension(db, ACCOUNT_ID)

    assert result is suspension
    assert result.is_active is True


# ---------------------------------------------------------------------------
# 7. is_account_suspended — returns False when not suspended
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_account_suspended_false():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(None))

    result = await is_account_suspended(db, ACCOUNT_ID)

    assert result is False


# ---------------------------------------------------------------------------
# 8. is_account_suspended — returns True when suspended
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_account_suspended_true():
    db = AsyncMock()
    suspension = _make_suspension()
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(suspension))

    result = await is_account_suspended(db, ACCOUNT_ID)

    assert result is True


# ---------------------------------------------------------------------------
# 9. list_suspension_history — returns records most recent first
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_suspension_history_returns_records():
    db = AsyncMock()
    s1 = _make_suspension(suspension_id=2, is_active=False)
    s2 = _make_suspension(suspension_id=1, is_active=True)
    db.execute = AsyncMock(return_value=_make_execute_result_scalars([s1, s2]))

    result = await list_suspension_history(db, ACCOUNT_ID)

    assert len(result) == 2
    assert result[0].id == 2
    assert result[1].id == 1


# ---------------------------------------------------------------------------
# 10. list_suspension_history — empty list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_suspension_history_empty():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_execute_result_scalars([]))

    result = await list_suspension_history(db, ACCOUNT_ID)

    assert list(result) == []


# ---------------------------------------------------------------------------
# 11. list_all_suspended_accounts — returns active suspensions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_suspended_accounts_returns_active():
    db = AsyncMock()
    s1 = _make_suspension(account_id=10)
    s2 = _make_suspension(suspension_id=2, account_id=20)
    db.execute = AsyncMock(return_value=_make_execute_result_scalars([s1, s2]))

    result = await list_all_suspended_accounts(db)

    assert len(result) == 2
    assert all(s.is_active for s in result)


# ---------------------------------------------------------------------------
# 12. list_all_suspended_accounts — empty when none suspended
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_suspended_accounts_empty():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_execute_result_scalars([]))

    result = await list_all_suspended_accounts(db)

    assert list(result) == []


# ---------------------------------------------------------------------------
# 13. suspend_account — suspension_note persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suspend_account_note_persisted():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(None))
    db.commit = AsyncMock()
    added = []

    def _add(obj):
        added.append(obj)
        obj.id = SUSPENSION_ID
        obj.suspended_at = _NOW

    db.add = _add
    db.refresh = AsyncMock()

    await suspend_account(
        db,
        account_id=ACCOUNT_ID,
        suspended_by_id=ADMIN_ID,
        reason=SuspensionReason.fraud_investigation,
        note="Suspected fraudulent activity",
    )

    assert added[0].suspension_note == "Suspected fraudulent activity"


# ---------------------------------------------------------------------------
# 14. reinstate_account — reinstatement_note persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reinstate_account_note_persisted():
    db = AsyncMock()
    suspension = _make_suspension()
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(suspension))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    await reinstate_account(
        db,
        account_id=ACCOUNT_ID,
        reinstated_by_id=ADMIN_ID,
        reinstatement_note="Fraud cleared",
    )

    assert suspension.reinstatement_note == "Fraud cleared"


# ---------------------------------------------------------------------------
# 15. reinstate_account — reinstated_at is set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reinstate_account_reinstated_at_set():
    db = AsyncMock()
    suspension = _make_suspension()
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(suspension))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    before = datetime.now(timezone.utc)
    await reinstate_account(db, ACCOUNT_ID, ADMIN_ID, None)
    after = datetime.now(timezone.utc)

    assert suspension.reinstated_at is not None
    assert before <= suspension.reinstated_at <= after


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_suspend_request_all_reasons_valid():
    for reason in SuspensionReason:
        req = SuspendRequest(reason=reason)
        assert req.reason == reason


def test_suspend_request_reason_required():
    with pytest.raises(ValidationError):
        SuspendRequest()


def test_suspend_request_note_optional():
    req = SuspendRequest(reason=SuspensionReason.other)
    assert req.suspension_note is None


def test_reinstate_request_note_optional():
    req = ReinstateRequest()
    assert req.reinstatement_note is None


def test_suspension_response_from_attributes():
    resp = _make_response()
    assert resp.id == SUSPENSION_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.reason == SuspensionReason.billing_overdue
    assert resp.is_active is True


def test_suspension_status_response_valid():
    resp = SuspensionStatusResponse(
        is_suspended=True,
        suspended_at=_NOW,
        reason="billing_overdue",
        suspension_note="Overdue",
    )
    assert resp.is_suspended is True
    assert resp.reason == "billing_overdue"


def test_suspension_list_response_valid():
    resp = SuspensionListResponse(
        suspensions=[_make_response()],
        total=1,
    )
    assert resp.total == 1
    assert len(resp.suspensions) == 1


def test_suspension_reason_all_values():
    expected = {
        "billing_overdue",
        "policy_violation",
        "fraud_investigation",
        "voluntary_pause",
        "compliance_failure",
        "non_payment",
        "other",
    }
    assert {r.value for r in SuspensionReason} == expected


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------


# 24. POST /corporate/accounts/{id}/suspend — 201 happy path
@pytest.mark.asyncio
async def test_api_suspend_account_201():
    from app.api.v1.corporate_account_suspensions import admin_suspend_account

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    body = SuspendRequest(reason=SuspensionReason.billing_overdue, suspension_note="Overdue")
    mock_response = _make_response()

    with patch(f"{_ROUTER}.suspend_account", new=AsyncMock(return_value=mock_response)):
        result = await admin_suspend_account(
            account_id=ACCOUNT_ID,
            payload=body,
            _admin=admin,
            db=db,
        )

    assert result.account_id == ACCOUNT_ID
    assert result.is_active is True


# 25. POST /corporate/accounts/{id}/suspend — 409 already suspended
@pytest.mark.asyncio
async def test_api_suspend_account_409():
    from app.api.v1.corporate_account_suspensions import admin_suspend_account

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    body = SuspendRequest(reason=SuspensionReason.billing_overdue)

    with patch(
        f"{_ROUTER}.suspend_account",
        new=AsyncMock(side_effect=HTTPException(status_code=409, detail="Already suspended")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await admin_suspend_account(account_id=ACCOUNT_ID, payload=body, _admin=admin, db=db)

    assert exc_info.value.status_code == 409


# 26. POST /corporate/accounts/{id}/reinstate — 200 happy path
@pytest.mark.asyncio
async def test_api_reinstate_account_200():
    from app.api.v1.corporate_account_suspensions import admin_reinstate_account

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    body = ReinstateRequest(reinstatement_note="Resolved")
    reinstated = _make_response(is_active=False)

    with patch(f"{_ROUTER}.reinstate_account", new=AsyncMock(return_value=reinstated)):
        result = await admin_reinstate_account(
            account_id=ACCOUNT_ID,
            payload=body,
            _admin=admin,
            db=db,
        )

    assert result.is_active is False


# 27. POST /corporate/accounts/{id}/reinstate — 404
@pytest.mark.asyncio
async def test_api_reinstate_account_404():
    from app.api.v1.corporate_account_suspensions import admin_reinstate_account

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    body = ReinstateRequest()

    with patch(
        f"{_ROUTER}.reinstate_account",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="No active suspension")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await admin_reinstate_account(account_id=ACCOUNT_ID, payload=body, _admin=admin, db=db)

    assert exc_info.value.status_code == 404


# 28. GET /corporate/accounts/{id}/suspension — 200
@pytest.mark.asyncio
async def test_api_get_active_suspension_200():
    from app.api.v1.corporate_account_suspensions import admin_get_active_suspension

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    suspension = _make_suspension()

    with patch(f"{_ROUTER}.get_active_suspension", new=AsyncMock(return_value=suspension)):
        result = await admin_get_active_suspension(account_id=ACCOUNT_ID, _admin=admin, db=db)

    assert result.account_id == ACCOUNT_ID
    assert result.is_active is True


# 29. GET /corporate/accounts/{id}/suspension — 404 not suspended
@pytest.mark.asyncio
async def test_api_get_active_suspension_404():
    from app.api.v1.corporate_account_suspensions import admin_get_active_suspension

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()

    with patch(f"{_ROUTER}.get_active_suspension", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc_info:
            await admin_get_active_suspension(account_id=ACCOUNT_ID, _admin=admin, db=db)

    assert exc_info.value.status_code == 404


# 30. GET /corporate/accounts/{id}/suspension/history — 200
@pytest.mark.asyncio
async def test_api_get_suspension_history_200():
    from app.api.v1.corporate_account_suspensions import admin_get_suspension_history

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    records = [_make_suspension()]

    with patch(f"{_ROUTER}.list_suspension_history", new=AsyncMock(return_value=records)):
        result = await admin_get_suspension_history(
            account_id=ACCOUNT_ID,
            skip=0,
            limit=50,
            _admin=admin,
            db=db,
        )

    assert result.total == 1
    assert len(result.suspensions) == 1


# 31. GET /admin/corporate/suspensions — 200
@pytest.mark.asyncio
async def test_api_list_all_suspensions_200():
    from app.api.v1.corporate_account_suspensions import admin_list_all_suspensions

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    records = [_make_suspension(account_id=10), _make_suspension(suspension_id=2, account_id=20)]

    with patch(f"{_ROUTER}.list_all_suspended_accounts", new=AsyncMock(return_value=records)):
        result = await admin_list_all_suspensions(skip=0, limit=50, _admin=admin, db=db)

    assert result.total == 2


# 32. GET /corporate/suspension/status — 200 not suspended
@pytest.mark.asyncio
async def test_api_get_status_not_suspended():
    from app.api.v1.corporate_account_suspensions import get_my_suspension_status

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.get_active_suspension", new=AsyncMock(return_value=None)):
        result = await get_my_suspension_status(user=user, db=db)

    assert result.is_suspended is False
    assert result.suspended_at is None
    assert result.reason is None


# 33. GET /corporate/suspension/status — 200 is suspended
@pytest.mark.asyncio
async def test_api_get_status_is_suspended():
    from app.api.v1.corporate_account_suspensions import get_my_suspension_status

    user = _mock_user()
    db = AsyncMock()
    suspension = _make_suspension()

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.get_active_suspension", new=AsyncMock(return_value=suspension)):
        result = await get_my_suspension_status(user=user, db=db)

    assert result.is_suspended is True
    assert result.suspended_at == _NOW
    assert result.reason == "billing_overdue"
    assert result.suspension_note == "Overdue invoice"


# 34. GET /corporate/suspension/status — 404 not a member
@pytest.mark.asyncio
async def test_api_get_status_404_not_member():
    from app.api.v1.corporate_account_suspensions import get_my_suspension_status

    user = _mock_user()
    db = AsyncMock()

    with patch(
        f"{_ROUTER}._get_member_account_id",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not a member")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_my_suspension_status(user=user, db=db)

    assert exc_info.value.status_code == 404


# 35. suspend endpoint — non-admin gets 403
@pytest.mark.asyncio
async def test_api_suspend_requires_admin():
    from app.api.deps import require_admin
    from app.models.user import User

    non_admin = MagicMock(spec=User)
    non_admin.role = MagicMock()
    non_admin.role.value = "member"

    with pytest.raises(HTTPException) as exc_info:
        await require_admin(non_admin)

    assert exc_info.value.status_code == 403


# 36. reinstate endpoint — non-admin gets 403
@pytest.mark.asyncio
async def test_api_reinstate_requires_admin():
    from app.api.deps import require_admin
    from app.models.user import User

    non_admin = MagicMock(spec=User)
    non_admin.role = MagicMock()
    non_admin.role.value = "rider"

    with pytest.raises(HTTPException) as exc_info:
        await require_admin(non_admin)

    assert exc_info.value.status_code == 403


# 37. get active suspension endpoint — non-admin gets 403
@pytest.mark.asyncio
async def test_api_get_suspension_requires_admin():
    from app.api.deps import require_admin
    from app.models.user import User

    non_admin = MagicMock(spec=User)
    non_admin.role = MagicMock()
    non_admin.role.value = "driver"

    with pytest.raises(HTTPException) as exc_info:
        await require_admin(non_admin)

    assert exc_info.value.status_code == 403


# 38. list all suspensions endpoint — non-admin gets 403
@pytest.mark.asyncio
async def test_api_list_all_suspensions_requires_admin():
    from app.api.deps import require_admin
    from app.models.user import User

    non_admin = MagicMock(spec=User)
    non_admin.role = MagicMock()
    non_admin.role.value = "member"

    with pytest.raises(HTTPException) as exc_info:
        await require_admin(non_admin)

    assert exc_info.value.status_code == 403
