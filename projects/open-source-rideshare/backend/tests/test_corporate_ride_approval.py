"""Tests for the Corporate Ride Approval feature.

Service layer (async, mocked DB):
  1.  request_approval — creates pending approval with UUID code
  2.  request_approval — raises 403 when user is not an active member
  3.  request_approval — raises 400 when pending limit reached
  4.  list_pending_approvals — returns only PENDING approvals
  5.  list_member_approvals — returns all of a member's approvals
  6.  get_approval — returns approval by ID
  7.  get_approval — raises 404 when not found
  8.  get_approval — raises 404 when account_id mismatch
  9.  approve — sets status=APPROVED and records reviewer
  10. approve — raises 403 when caller is not account admin
  11. approve — raises 400 when approval is not PENDING
  12. approve — raises 404 when approval not found
  13. deny — sets status=DENIED and records reviewer
  14. deny — raises 403 when caller is not account admin
  15. deny — raises 400 when approval is not PENDING
  16. cancel — sets status=CANCELLED
  17. cancel — raises 400 when requester_user_id mismatch
  18. cancel — raises 400 when approval is not PENDING
  19. verify_approval — returns valid=True for approved, unexpired approval
  20. verify_approval — returns valid=False when code not found
  21. verify_approval — returns valid=False when status is not APPROVED
  22. verify_approval — returns valid=False when approval has expired
  23. verify_approval — returns valid=False when cost exceeds max_cost_usd
  24. verify_approval — valid=True when max_cost_usd is None (no ceiling)
  25. verify_approval — valid=True when estimated_cost_usd is None

Schema validation:
  26. RideApprovalRequest — valid minimal payload accepted
  27. RideApprovalRequest — estimated_cost_usd must be > 0
  28. RideApprovalRequest — validity_hours must be 1–168
  29. RideApprovalDecision — max_cost_usd must be > 0
  30. ApprovalVerifyRequest — valid payload accepted

API layer (service functions patched):
  31. POST /corporate/accounts/me/approvals — calls request_approval (201)
  32. GET  /corporate/accounts/me/approvals — calls list_member_approvals
  33. DELETE /corporate/accounts/me/approvals/{id} — calls cancel (204)
  34. GET  /corporate/accounts/me/approvals/pending — calls list_pending_approvals
  35. PUT  /corporate/accounts/me/approvals/{id}/approve — calls approve
  36. PUT  /corporate/accounts/me/approvals/{id}/deny — calls deny
  37. POST /corporate/accounts/me/approvals/verify — calls verify_approval
  38. GET  /admin/corporate/accounts/{id}/approvals — admin view
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_ride_approval import ApprovalStatus, CorporateRideApproval
from app.schemas.corporate_ride_approval import (
    ApprovalVerifyRequest,
    ApprovalVerifyResponse,
    CorporateRideApprovalResponse,
    RideApprovalDecision,
    RideApprovalRequest,
    RideDenialRequest,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ACCOUNT_ID = 10
REQUESTER_ID = 101
ADMIN_ID = 102
OTHER_USER_ID = 200


def _make_approval(
    *,
    status: ApprovalStatus = ApprovalStatus.PENDING,
    requester_user_id: int = REQUESTER_ID,
    account_id: int = ACCOUNT_ID,
    max_cost_usd: Decimal | None = None,
    expires_at: datetime | None = None,
) -> CorporateRideApproval:
    now = datetime.now(timezone.utc)
    approval = CorporateRideApproval()
    approval.id = 1
    approval.account_id = account_id
    approval.requester_user_id = requester_user_id
    approval.approved_by_user_id = None
    approval.purpose = "Client meeting"
    approval.destination_description = "Downtown HQ"
    approval.estimated_cost_usd = Decimal("35.00")
    approval.status = status
    approval.approval_code = str(uuid.uuid4())
    approval.max_cost_usd = max_cost_usd
    approval.expires_at = expires_at or (now + timedelta(hours=48))
    approval.review_note = None
    approval.reviewed_at = None
    approval.used_at = None
    approval.requested_at = now
    return approval


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_approval_creates_pending():
    """request_approval creates a PENDING approval with a UUID code."""
    from app.services.corporate_ride_approval import request_approval

    db = _mock_db()
    data = RideApprovalRequest(purpose="Client call", validity_hours=24)

    # Member exists
    member_mock = MagicMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = member_mock
    # Pending count query returns empty list
    pending_result = MagicMock()
    pending_result.scalars.return_value.all.return_value = []

    db.execute = AsyncMock(side_effect=[exec_result, pending_result])

    created = MagicMock(spec=CorporateRideApproval)
    created.status = ApprovalStatus.PENDING
    db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", 99) or None)

    result = await request_approval(db, ACCOUNT_ID, REQUESTER_ID, data)
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_approval_raises_403_when_not_member():
    """request_approval raises 403 when the user is not an active member."""
    from app.services.corporate_ride_approval import request_approval

    db = _mock_db()
    data = RideApprovalRequest()

    # No member found
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=exec_result)

    with pytest.raises(HTTPException) as exc:
        await request_approval(db, ACCOUNT_ID, REQUESTER_ID, data)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_request_approval_raises_400_when_pending_limit_reached():
    """request_approval raises 400 when the member has too many pending requests."""
    from app.services.corporate_ride_approval import request_approval, MAX_PENDING_PER_MEMBER

    db = _mock_db()
    data = RideApprovalRequest()

    member_mock = MagicMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = member_mock

    pending_approvals = [MagicMock() for _ in range(MAX_PENDING_PER_MEMBER)]
    pending_result = MagicMock()
    pending_result.scalars.return_value.all.return_value = pending_approvals

    db.execute = AsyncMock(side_effect=[exec_result, pending_result])

    with pytest.raises(HTTPException) as exc:
        await request_approval(db, ACCOUNT_ID, REQUESTER_ID, data)
    assert exc.value.status_code == 400
    assert "pending" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_list_pending_approvals_returns_pending_only():
    """list_pending_approvals returns only PENDING approval rows."""
    from app.services.corporate_ride_approval import list_pending_approvals

    db = _mock_db()
    approval = _make_approval(status=ApprovalStatus.PENDING)

    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = [approval]
    db.execute = AsyncMock(return_value=exec_result)

    result = await list_pending_approvals(db, ACCOUNT_ID)
    assert result == [approval]


@pytest.mark.asyncio
async def test_list_member_approvals():
    """list_member_approvals returns all approvals for a member."""
    from app.services.corporate_ride_approval import list_member_approvals

    db = _mock_db()
    approvals = [
        _make_approval(status=ApprovalStatus.APPROVED),
        _make_approval(status=ApprovalStatus.DENIED),
    ]
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = approvals
    db.execute = AsyncMock(return_value=exec_result)

    result = await list_member_approvals(db, ACCOUNT_ID, REQUESTER_ID)
    assert result == approvals


@pytest.mark.asyncio
async def test_get_approval_returns_by_id():
    """get_approval returns the approval when it exists."""
    from app.services.corporate_ride_approval import get_approval

    db = _mock_db()
    approval = _make_approval()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = approval
    db.execute = AsyncMock(return_value=exec_result)

    result = await get_approval(db, 1)
    assert result is approval


@pytest.mark.asyncio
async def test_get_approval_raises_404_when_not_found():
    """get_approval raises HTTP 404 when the approval does not exist."""
    from app.services.corporate_ride_approval import get_approval

    db = _mock_db()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=exec_result)

    with pytest.raises(HTTPException) as exc:
        await get_approval(db, 999)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_approval_raises_404_on_account_mismatch():
    """get_approval raises 404 when approval belongs to a different account."""
    from app.services.corporate_ride_approval import get_approval

    db = _mock_db()
    # approval not found when queried with wrong account_id
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=exec_result)

    with pytest.raises(HTTPException) as exc:
        await get_approval(db, 1, account_id=99)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_approve_sets_approved_status():
    """approve transitions a PENDING approval to APPROVED."""
    from app.services.corporate_ride_approval import approve

    db = _mock_db()
    approval = _make_approval(status=ApprovalStatus.PENDING)
    data = RideApprovalDecision(max_cost_usd=Decimal("50.00"), review_note="Approved")

    # Admin check passes, then get_approval
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = MagicMock()
    approval_result = MagicMock()
    approval_result.scalar_one_or_none.return_value = approval
    db.execute = AsyncMock(side_effect=[admin_result, approval_result])

    result = await approve(db, 1, ACCOUNT_ID, ADMIN_ID, data)
    assert result.status == ApprovalStatus.APPROVED
    assert result.approved_by_user_id == ADMIN_ID
    assert result.max_cost_usd == Decimal("50.00")
    assert result.reviewed_at is not None


@pytest.mark.asyncio
async def test_approve_raises_403_when_not_admin():
    """approve raises 403 when the caller is not an account admin."""
    from app.services.corporate_ride_approval import approve

    db = _mock_db()
    data = RideApprovalDecision()

    # Admin check fails
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=admin_result)

    with pytest.raises(HTTPException) as exc:
        await approve(db, 1, ACCOUNT_ID, OTHER_USER_ID, data)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_approve_raises_400_when_not_pending():
    """approve raises 400 when the approval is not in PENDING status."""
    from app.services.corporate_ride_approval import approve

    db = _mock_db()
    approval = _make_approval(status=ApprovalStatus.APPROVED)
    data = RideApprovalDecision()

    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = MagicMock()
    approval_result = MagicMock()
    approval_result.scalar_one_or_none.return_value = approval
    db.execute = AsyncMock(side_effect=[admin_result, approval_result])

    with pytest.raises(HTTPException) as exc:
        await approve(db, 1, ACCOUNT_ID, ADMIN_ID, data)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_approve_raises_404_when_not_found():
    """approve raises 404 when the approval does not exist."""
    from app.services.corporate_ride_approval import approve

    db = _mock_db()
    data = RideApprovalDecision()

    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = MagicMock()
    not_found_result = MagicMock()
    not_found_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[admin_result, not_found_result])

    with pytest.raises(HTTPException) as exc:
        await approve(db, 999, ACCOUNT_ID, ADMIN_ID, data)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deny_sets_denied_status():
    """deny transitions a PENDING approval to DENIED."""
    from app.services.corporate_ride_approval import deny

    db = _mock_db()
    approval = _make_approval(status=ApprovalStatus.PENDING)
    data = RideDenialRequest(review_note="Out of policy")

    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = MagicMock()
    approval_result = MagicMock()
    approval_result.scalar_one_or_none.return_value = approval
    db.execute = AsyncMock(side_effect=[admin_result, approval_result])

    result = await deny(db, 1, ACCOUNT_ID, ADMIN_ID, data)
    assert result.status == ApprovalStatus.DENIED
    assert result.approved_by_user_id == ADMIN_ID
    assert result.review_note == "Out of policy"


@pytest.mark.asyncio
async def test_deny_raises_403_when_not_admin():
    """deny raises 403 when the caller is not an account admin."""
    from app.services.corporate_ride_approval import deny

    db = _mock_db()
    data = RideDenialRequest()

    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=admin_result)

    with pytest.raises(HTTPException) as exc:
        await deny(db, 1, ACCOUNT_ID, OTHER_USER_ID, data)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_deny_raises_400_when_not_pending():
    """deny raises 400 when the approval is not in PENDING status."""
    from app.services.corporate_ride_approval import deny

    db = _mock_db()
    approval = _make_approval(status=ApprovalStatus.DENIED)
    data = RideDenialRequest()

    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = MagicMock()
    approval_result = MagicMock()
    approval_result.scalar_one_or_none.return_value = approval
    db.execute = AsyncMock(side_effect=[admin_result, approval_result])

    with pytest.raises(HTTPException) as exc:
        await deny(db, 1, ACCOUNT_ID, ADMIN_ID, data)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_cancel_sets_cancelled_status():
    """cancel transitions a PENDING approval to CANCELLED."""
    from app.services.corporate_ride_approval import cancel

    db = _mock_db()
    approval = _make_approval(status=ApprovalStatus.PENDING, requester_user_id=REQUESTER_ID)

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = approval
    db.execute = AsyncMock(return_value=exec_result)

    result = await cancel(db, 1, ACCOUNT_ID, REQUESTER_ID)
    assert result.status == ApprovalStatus.CANCELLED


@pytest.mark.asyncio
async def test_cancel_raises_400_when_wrong_owner():
    """cancel raises 400 when the caller is not the original requester."""
    from app.services.corporate_ride_approval import cancel

    db = _mock_db()
    approval = _make_approval(status=ApprovalStatus.PENDING, requester_user_id=REQUESTER_ID)

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = approval
    db.execute = AsyncMock(return_value=exec_result)

    with pytest.raises(HTTPException) as exc:
        await cancel(db, 1, ACCOUNT_ID, OTHER_USER_ID)
    assert exc.value.status_code == 400
    assert "own" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_cancel_raises_400_when_not_pending():
    """cancel raises 400 when the approval is not in PENDING status."""
    from app.services.corporate_ride_approval import cancel

    db = _mock_db()
    approval = _make_approval(status=ApprovalStatus.APPROVED, requester_user_id=REQUESTER_ID)

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = approval
    db.execute = AsyncMock(return_value=exec_result)

    with pytest.raises(HTTPException) as exc:
        await cancel(db, 1, ACCOUNT_ID, REQUESTER_ID)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_verify_approval_valid_approved():
    """verify_approval returns valid=True for an approved, unexpired approval."""
    from app.services.corporate_ride_approval import verify_approval

    db = _mock_db()
    code = str(uuid.uuid4())
    approval = _make_approval(
        status=ApprovalStatus.APPROVED,
        max_cost_usd=Decimal("100.00"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=10),
    )
    approval.approval_code = code

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = approval
    db.execute = AsyncMock(return_value=exec_result)

    result = await verify_approval(db, ACCOUNT_ID, code, Decimal("45.00"))
    assert result.valid is True
    assert result.approval_id == approval.id
    assert result.max_cost_usd == Decimal("100.00")


@pytest.mark.asyncio
async def test_verify_approval_code_not_found():
    """verify_approval returns valid=False when the code does not exist."""
    from app.services.corporate_ride_approval import verify_approval

    db = _mock_db()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=exec_result)

    result = await verify_approval(db, ACCOUNT_ID, "bad-code", None)
    assert result.valid is False
    assert "not found" in result.reason.lower()


@pytest.mark.asyncio
async def test_verify_approval_wrong_status():
    """verify_approval returns valid=False when approval is not APPROVED."""
    from app.services.corporate_ride_approval import verify_approval

    db = _mock_db()
    code = str(uuid.uuid4())
    approval = _make_approval(status=ApprovalStatus.PENDING)
    approval.approval_code = code

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = approval
    db.execute = AsyncMock(return_value=exec_result)

    result = await verify_approval(db, ACCOUNT_ID, code, None)
    assert result.valid is False
    assert "pending" in result.reason.lower()


@pytest.mark.asyncio
async def test_verify_approval_expired():
    """verify_approval returns valid=False when the approval has expired."""
    from app.services.corporate_ride_approval import verify_approval

    db = _mock_db()
    code = str(uuid.uuid4())
    approval = _make_approval(
        status=ApprovalStatus.APPROVED,
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    approval.approval_code = code

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = approval
    db.execute = AsyncMock(return_value=exec_result)

    result = await verify_approval(db, ACCOUNT_ID, code, None)
    assert result.valid is False
    assert "expired" in result.reason.lower()


@pytest.mark.asyncio
async def test_verify_approval_cost_exceeds_ceiling():
    """verify_approval returns valid=False when estimated cost exceeds max_cost_usd."""
    from app.services.corporate_ride_approval import verify_approval

    db = _mock_db()
    code = str(uuid.uuid4())
    approval = _make_approval(
        status=ApprovalStatus.APPROVED,
        max_cost_usd=Decimal("30.00"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=10),
    )
    approval.approval_code = code

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = approval
    db.execute = AsyncMock(return_value=exec_result)

    result = await verify_approval(db, ACCOUNT_ID, code, Decimal("50.00"))
    assert result.valid is False
    assert "exceeds" in result.reason.lower()
    assert result.max_cost_usd == Decimal("30.00")


@pytest.mark.asyncio
async def test_verify_approval_no_ceiling():
    """verify_approval is valid when max_cost_usd is None (no ceiling)."""
    from app.services.corporate_ride_approval import verify_approval

    db = _mock_db()
    code = str(uuid.uuid4())
    approval = _make_approval(
        status=ApprovalStatus.APPROVED,
        max_cost_usd=None,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=10),
    )
    approval.approval_code = code

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = approval
    db.execute = AsyncMock(return_value=exec_result)

    result = await verify_approval(db, ACCOUNT_ID, code, Decimal("999.00"))
    assert result.valid is True


@pytest.mark.asyncio
async def test_verify_approval_no_estimated_cost():
    """verify_approval is valid when estimated_cost_usd is None (cost check skipped)."""
    from app.services.corporate_ride_approval import verify_approval

    db = _mock_db()
    code = str(uuid.uuid4())
    approval = _make_approval(
        status=ApprovalStatus.APPROVED,
        max_cost_usd=Decimal("50.00"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=10),
    )
    approval.approval_code = code

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = approval
    db.execute = AsyncMock(return_value=exec_result)

    result = await verify_approval(db, ACCOUNT_ID, code, None)
    assert result.valid is True


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_ride_approval_request_valid_minimal():
    """RideApprovalRequest accepts a fully-default payload."""
    req = RideApprovalRequest()
    assert req.validity_hours == 48
    assert req.purpose is None
    assert req.estimated_cost_usd is None


def test_ride_approval_request_estimated_cost_must_be_positive():
    """RideApprovalRequest rejects estimated_cost_usd <= 0."""
    with pytest.raises(ValidationError):
        RideApprovalRequest(estimated_cost_usd=Decimal("0.00"))
    with pytest.raises(ValidationError):
        RideApprovalRequest(estimated_cost_usd=Decimal("-5.00"))


def test_ride_approval_request_validity_hours_bounds():
    """RideApprovalRequest enforces validity_hours 1–168."""
    with pytest.raises(ValidationError):
        RideApprovalRequest(validity_hours=0)
    with pytest.raises(ValidationError):
        RideApprovalRequest(validity_hours=169)
    # Boundary values are valid
    RideApprovalRequest(validity_hours=1)
    RideApprovalRequest(validity_hours=168)


def test_ride_approval_decision_max_cost_must_be_positive():
    """RideApprovalDecision rejects max_cost_usd <= 0."""
    with pytest.raises(ValidationError):
        RideApprovalDecision(max_cost_usd=Decimal("0.00"))


def test_approval_verify_request_valid():
    """ApprovalVerifyRequest accepts a valid payload."""
    req = ApprovalVerifyRequest(
        approval_code="abc-123",
        estimated_cost_usd=Decimal("25.00"),
    )
    assert req.approval_code == "abc-123"
    assert req.estimated_cost_usd == Decimal("25.00")


# ---------------------------------------------------------------------------
# API layer tests (handler functions called directly, services patched)
# ---------------------------------------------------------------------------


def _mock_user(user_id: int = REQUESTER_ID) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    return user


def _make_membership(account_id: int = ACCOUNT_ID, user_id: int = REQUESTER_ID) -> MagicMock:
    m = MagicMock()
    m.account_id = account_id
    m.user_id = user_id
    m.is_active = True
    return m


def _scalar_result(value) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _make_mock_approval(status: ApprovalStatus = ApprovalStatus.PENDING) -> MagicMock:
    """Return a MagicMock(spec=CorporateRideApproval) with all required attributes."""
    a = MagicMock(spec=CorporateRideApproval)
    a.id = 1
    a.account_id = ACCOUNT_ID
    a.requester_user_id = REQUESTER_ID
    a.approved_by_user_id = None
    a.purpose = "Client visit"
    a.destination_description = "HQ"
    a.estimated_cost_usd = Decimal("35.00")
    a.status = status
    a.approval_code = str(uuid.uuid4())
    a.max_cost_usd = None
    a.expires_at = datetime.now(timezone.utc) + timedelta(hours=48)
    a.review_note = None
    a.reviewed_at = None
    a.used_at = None
    a.requested_at = datetime.now(timezone.utc)
    return a


@pytest.mark.asyncio
async def test_api_create_approval():
    """31. POST /corporate/accounts/me/approvals calls request_approval and returns result."""
    from app.api.v1.corporate_ride_approval import create_approval_request

    user = _mock_user()
    membership = _make_membership()
    mock_approval = _make_mock_approval()

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(membership))

    data = RideApprovalRequest(purpose="Client call")

    with patch(
        "app.api.v1.corporate_ride_approval.request_approval",
        new=AsyncMock(return_value=mock_approval),
    ):
        result = await create_approval_request(data=data, db=db, current_user=user)

    assert result.account_id == ACCOUNT_ID
    assert result.requester_user_id == REQUESTER_ID


@pytest.mark.asyncio
async def test_api_list_my_approvals():
    """32. GET /corporate/accounts/me/approvals calls list_member_approvals."""
    from app.api.v1.corporate_ride_approval import list_my_approvals

    user = _mock_user()
    membership = _make_membership()

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(membership))

    with patch(
        "app.api.v1.corporate_ride_approval.list_member_approvals",
        new=AsyncMock(return_value=[]),
    ):
        result = await list_my_approvals(db=db, current_user=user)

    assert result == []


@pytest.mark.asyncio
async def test_api_cancel_approval():
    """33. DELETE /corporate/accounts/me/approvals/{id} calls cancel."""
    from app.api.v1.corporate_ride_approval import cancel_my_approval

    user = _mock_user()
    membership = _make_membership()

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(membership))

    with patch(
        "app.api.v1.corporate_ride_approval.cancel",
        new=AsyncMock(return_value=_make_mock_approval(status=ApprovalStatus.CANCELLED)),
    ) as mock_cancel:
        await cancel_my_approval(approval_id=1, db=db, current_user=user)

    mock_cancel.assert_called_once()


@pytest.mark.asyncio
async def test_api_list_pending():
    """34. GET /corporate/accounts/me/approvals/pending calls list_pending_approvals."""
    from app.api.v1.corporate_ride_approval import list_pending

    user = _mock_user(user_id=ADMIN_ID)
    membership = _make_membership(user_id=ADMIN_ID)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(membership))

    with patch(
        "app.api.v1.corporate_ride_approval.list_pending_approvals",
        new=AsyncMock(return_value=[]),
    ):
        result = await list_pending(db=db, current_user=user)

    assert result == []


@pytest.mark.asyncio
async def test_api_approve_request():
    """35. PUT /corporate/accounts/me/approvals/{id}/approve calls approve."""
    from app.api.v1.corporate_ride_approval import approve_request

    user = _mock_user(user_id=ADMIN_ID)
    membership = _make_membership(user_id=ADMIN_ID)
    mock_approval = _make_mock_approval(status=ApprovalStatus.APPROVED)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(membership))
    data = RideApprovalDecision(review_note="Approved")

    with patch(
        "app.api.v1.corporate_ride_approval.approve",
        new=AsyncMock(return_value=mock_approval),
    ):
        result = await approve_request(approval_id=1, data=data, db=db, current_user=user)

    assert result.status == ApprovalStatus.APPROVED


@pytest.mark.asyncio
async def test_api_deny_request():
    """36. PUT /corporate/accounts/me/approvals/{id}/deny calls deny."""
    from app.api.v1.corporate_ride_approval import deny_request

    user = _mock_user(user_id=ADMIN_ID)
    membership = _make_membership(user_id=ADMIN_ID)
    mock_approval = _make_mock_approval(status=ApprovalStatus.DENIED)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(membership))
    data = RideDenialRequest(review_note="Out of policy")

    with patch(
        "app.api.v1.corporate_ride_approval.deny",
        new=AsyncMock(return_value=mock_approval),
    ):
        result = await deny_request(approval_id=1, data=data, db=db, current_user=user)

    assert result.status == ApprovalStatus.DENIED


@pytest.mark.asyncio
async def test_api_verify_approval():
    """37. POST /corporate/accounts/me/approvals/verify calls verify_approval."""
    from app.api.v1.corporate_ride_approval import verify_approval_code

    user = _mock_user()
    membership = _make_membership()

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(membership))

    verify_result = ApprovalVerifyResponse(
        valid=True, approval_id=1, max_cost_usd=Decimal("50.00")
    )
    req = ApprovalVerifyRequest(approval_code="abc-123", estimated_cost_usd=Decimal("30.00"))

    with patch(
        "app.api.v1.corporate_ride_approval.verify_approval",
        new=AsyncMock(return_value=verify_result),
    ):
        result = await verify_approval_code(data=req, db=db, current_user=user)

    assert result.valid is True
    assert result.approval_id == 1


@pytest.mark.asyncio
async def test_api_admin_list_approvals():
    """38. GET /admin/corporate/accounts/{id}/approvals returns all approvals."""
    from app.api.v1.corporate_ride_approval import admin_list_approvals

    mock_approval = _make_mock_approval()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = [mock_approval]

    db = AsyncMock()
    db.execute = AsyncMock(return_value=exec_result)

    result = await admin_list_approvals(account_id=ACCOUNT_ID, db=db)

    assert len(result) == 1
    assert result[0].account_id == ACCOUNT_ID
