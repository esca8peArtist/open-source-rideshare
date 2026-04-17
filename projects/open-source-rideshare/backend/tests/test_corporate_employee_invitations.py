"""Tests for the Corporate Employee Invitation feature.

Service tests (async, mocked DB):
  1.  create_invitation — success, membership created with pending status
  2.  create_invitation — duplicate pending email+account → 409
  3.  create_invitation — non-admin caller → 403
  4.  create_invitation — custom expires_at stored
  5.  create_invitation — email normalised to lowercase
  6.  create_invitation — default expires_at is 7 days from now
  7.  get_invitation — success
  8.  get_invitation — wrong account → 404
  9.  list_invitations — returns all with total count
  10. list_invitations — status_filter applied
  11. list_invitations — empty list
  12. revoke_invitation — success: status=revoked, audit fields set
  13. revoke_invitation — non-pending status (accepted) → 409
  14. revoke_invitation — non-pending status (already revoked) → 409
  15. revoke_invitation — not found → 404
  16. revoke_invitation — non-admin caller → 403
  17. validate_invitation_token — invalid UUID format
  18. validate_invitation_token — token not found
  19. validate_invitation_token — revoked → is_valid=False
  20. validate_invitation_token — accepted → is_valid=False
  21. validate_invitation_token — expired → is_valid=False
  22. validate_invitation_token — valid: is_valid=True, fields populated
  23. validate_invitation_token — valid: account_name fetched
  24. accept_invitation — success: membership created, status=accepted
  25. accept_invitation — admin role invitation → MemberRole.ADMIN created
  26. accept_invitation — token not valid → 400
  27. accept_invitation — user already a member → 409
  28. accept_invitation — onboarding record created on success
  29. accept_invitation — existing onboarding (409 from create_onboarding) is silently ignored
  30. revoke_invitation — does NOT trigger onboarding creation

Schema tests (sync):
  28. InvitationCreate — valid default (member role, no message)
  29. InvitationCreate — admin role + message
  30. InvitationCreate — invalid email → ValidationError
  31. InvitationCreate — expires_at in past → ValidationError
  32. InvitationCreate — expires_at omitted → None (default handled in service)
  33. InvitationCreate — message too long → ValidationError

API layer tests (asyncio, service patched):
  34. POST   /corporate/accounts/me/invitations              — 201
  35. GET    /corporate/accounts/me/invitations              — 200 list
  36. GET    /corporate/accounts/me/invitations/{id}         — 200
  37. DELETE /corporate/accounts/me/invitations/{id}         — 200 revoked
  38. GET    /corporate/invitations/{token}  (valid)         — 200 is_valid=True
  39. GET    /corporate/invitations/{token}  (invalid)       — 200 is_valid=False
  40. POST   /corporate/invitations/{token}/accept           — 200
  41. GET    /admin/corporate/invitations                    — 200
  42. GET    /admin/corporate/accounts/{id}/invitations      — 200
  43. POST   /corporate/accounts/me/invitations — 403 when not member
  44. DELETE /corporate/accounts/me/invitations/{id} — 409 accepted invite
  45. POST   /corporate/invitations/{token}/accept — 409 already a member
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_employee_invitation import (
    CorporateEmployeeInvitation,
    InvitationRole,
    InvitationStatus,
)
from app.schemas.corporate_employee_invitation import (
    InvitationCreate,
    InvitationListResponse,
    InvitationResponse,
    InvitationValidationResponse,
)
from app.services.corporate_employee_invitation import (
    accept_invitation,
    create_invitation,
    get_invitation,
    list_invitations,
    revoke_invitation,
    validate_invitation_token,
)

# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 42
ADMIN_USER_ID = 1
MEMBER_USER_ID = 2
INVITE_ID = uuid.uuid4()
TOKEN_UUID = uuid.uuid4()


def _make_invitation(
    status: InvitationStatus = InvitationStatus.PENDING,
    role: InvitationRole = InvitationRole.MEMBER,
    email: str = "alice@example.com",
    account_id: int = ACCOUNT_ID,
    expires_at: datetime | None = None,
) -> CorporateEmployeeInvitation:
    inv = MagicMock(spec=CorporateEmployeeInvitation)
    inv.id = INVITE_ID
    inv.account_id = account_id
    inv.token = TOKEN_UUID
    inv.email = email
    inv.invited_by_id = ADMIN_USER_ID
    inv.role = role
    inv.message = None
    inv.expires_at = expires_at or (NOW + timedelta(days=7))
    inv.status = status
    inv.accepted_at = None
    inv.accepted_by_id = None
    inv.revoked_at = None
    inv.revoked_by_id = None
    inv.created_at = NOW
    return inv


def _admin_member_mock():
    """DB result that satisfies the admin check."""
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = ACCOUNT_ID
    m.user_id = ADMIN_USER_ID
    m.role = MemberRole.ADMIN
    m.is_active = True
    return m


def _non_admin_result():
    """DB result that returns None for admin check (non-admin user)."""
    return None


def _make_execute_sequence(db: AsyncMock, responses: list):
    """Make db.execute return different values on successive calls."""
    results = []
    for r in responses:
        mock_result = MagicMock()
        if isinstance(r, list):
            mock_result.scalars.return_value.all.return_value = r
            mock_result.scalar_one_or_none.return_value = r[0] if r else None
            mock_result.scalar.return_value = len(r)
        else:
            mock_result.scalar_one_or_none.return_value = r
            mock_result.scalar.return_value = 0 if r is None else 1
            mock_result.scalars.return_value.all.return_value = [r] if r else []
        results.append(mock_result)
    db.execute.side_effect = results


# ---------------------------------------------------------------------------
# 1–6: create_invitation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_invitation_success():
    db = AsyncMock()
    _make_execute_sequence(db, [_admin_member_mock(), None])  # admin check, dupe check

    data = InvitationCreate(email="alice@example.com", role=InvitationRole.MEMBER)
    invitation = await create_invitation(db, ACCOUNT_ID, ADMIN_USER_ID, data)

    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_create_invitation_duplicate_pending_raises_409():
    db = AsyncMock()
    existing = _make_invitation()
    _make_execute_sequence(db, [_admin_member_mock(), existing])

    data = InvitationCreate(email="alice@example.com")
    with pytest.raises(HTTPException) as exc_info:
        await create_invitation(db, ACCOUNT_ID, ADMIN_USER_ID, data)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_create_invitation_non_admin_raises_403():
    db = AsyncMock()
    # Admin check returns None → not an admin
    _make_execute_sequence(db, [None])

    data = InvitationCreate(email="alice@example.com")
    with pytest.raises(HTTPException) as exc_info:
        await create_invitation(db, ACCOUNT_ID, MEMBER_USER_ID, data)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_create_invitation_custom_expires_at():
    db = AsyncMock()
    custom_exp = NOW + timedelta(days=3)
    _make_execute_sequence(db, [_admin_member_mock(), None])

    data = InvitationCreate(email="bob@example.com", expires_at=custom_exp)
    # Should not raise; expires_at is stored as-is
    await create_invitation(db, ACCOUNT_ID, ADMIN_USER_ID, data)
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_create_invitation_email_normalized_lowercase():
    db = AsyncMock()
    _make_execute_sequence(db, [_admin_member_mock(), None])

    data = InvitationCreate(email="Alice@Example.COM")
    await create_invitation(db, ACCOUNT_ID, ADMIN_USER_ID, data)

    # The created invitation should have lowercase email
    added_obj = db.add.call_args[0][0]
    assert added_obj.email == "alice@example.com"


@pytest.mark.asyncio
async def test_create_invitation_default_expires_7_days():
    db = AsyncMock()
    _make_execute_sequence(db, [_admin_member_mock(), None])

    data = InvitationCreate(email="carol@example.com")
    with patch(
        "app.services.corporate_employee_invitation._now_utc", return_value=NOW
    ):
        await create_invitation(db, ACCOUNT_ID, ADMIN_USER_ID, data)

    added_obj = db.add.call_args[0][0]
    expected_exp = NOW + timedelta(days=7)
    assert added_obj.expires_at == expected_exp


# ---------------------------------------------------------------------------
# 7–8: get_invitation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_invitation_success():
    invitation = _make_invitation()
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = invitation
    db.execute.return_value = result

    found = await get_invitation(db, INVITE_ID, ACCOUNT_ID)
    assert found is invitation


@pytest.mark.asyncio
async def test_get_invitation_wrong_account_raises_404():
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await get_invitation(db, INVITE_ID, account_id=999)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 9–11: list_invitations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_invitations_returns_all_with_count():
    inv1 = _make_invitation()
    inv2 = _make_invitation(status=InvitationStatus.ACCEPTED)

    db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar.return_value = 2
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = [inv1, inv2]
    db.execute.side_effect = [count_result, rows_result]

    items, total = await list_invitations(db, ACCOUNT_ID)
    assert total == 2
    assert len(items) == 2


@pytest.mark.asyncio
async def test_list_invitations_status_filter():
    pending = _make_invitation(status=InvitationStatus.PENDING)

    db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar.return_value = 1
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = [pending]
    db.execute.side_effect = [count_result, rows_result]

    items, total = await list_invitations(
        db, ACCOUNT_ID, status_filter=InvitationStatus.PENDING
    )
    assert total == 1
    assert items[0].status == InvitationStatus.PENDING


@pytest.mark.asyncio
async def test_list_invitations_empty():
    db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = []
    db.execute.side_effect = [count_result, rows_result]

    items, total = await list_invitations(db, ACCOUNT_ID)
    assert total == 0
    assert items == []


# ---------------------------------------------------------------------------
# 12–16: revoke_invitation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_invitation_success():
    invitation = _make_invitation(status=InvitationStatus.PENDING)

    db = AsyncMock()
    _make_execute_sequence(db, [_admin_member_mock(), invitation])

    result = await revoke_invitation(db, INVITE_ID, ACCOUNT_ID, ADMIN_USER_ID)
    assert result.status == InvitationStatus.REVOKED
    assert result.revoked_by_id == ADMIN_USER_ID
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_revoke_invitation_accepted_raises_409():
    invitation = _make_invitation(status=InvitationStatus.ACCEPTED)

    db = AsyncMock()
    _make_execute_sequence(db, [_admin_member_mock(), invitation])

    with pytest.raises(HTTPException) as exc_info:
        await revoke_invitation(db, INVITE_ID, ACCOUNT_ID, ADMIN_USER_ID)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_revoke_invitation_already_revoked_raises_409():
    invitation = _make_invitation(status=InvitationStatus.REVOKED)

    db = AsyncMock()
    _make_execute_sequence(db, [_admin_member_mock(), invitation])

    with pytest.raises(HTTPException) as exc_info:
        await revoke_invitation(db, INVITE_ID, ACCOUNT_ID, ADMIN_USER_ID)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_revoke_invitation_not_found_raises_404():
    db = AsyncMock()
    _make_execute_sequence(db, [_admin_member_mock(), None])

    with pytest.raises(HTTPException) as exc_info:
        await revoke_invitation(db, INVITE_ID, ACCOUNT_ID, ADMIN_USER_ID)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_revoke_invitation_non_admin_raises_403():
    db = AsyncMock()
    _make_execute_sequence(db, [None])  # admin check returns None

    with pytest.raises(HTTPException) as exc_info:
        await revoke_invitation(db, INVITE_ID, ACCOUNT_ID, MEMBER_USER_ID)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 17–23: validate_invitation_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_token_invalid_format():
    db = AsyncMock()
    result = await validate_invitation_token(db, "not-a-uuid!!")
    assert result["is_valid"] is False
    assert "Invalid token format" in result["reason"]


@pytest.mark.asyncio
async def test_validate_token_not_found():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_result

    result = await validate_invitation_token(db, str(uuid.uuid4()))
    assert result["is_valid"] is False
    assert "not found" in result["reason"].lower()


@pytest.mark.asyncio
async def test_validate_token_revoked():
    invitation = _make_invitation(status=InvitationStatus.REVOKED)

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = invitation
    db.execute.return_value = mock_result

    result = await validate_invitation_token(db, str(TOKEN_UUID))
    assert result["is_valid"] is False
    assert "revoked" in result["reason"].lower()


@pytest.mark.asyncio
async def test_validate_token_accepted():
    invitation = _make_invitation(status=InvitationStatus.ACCEPTED)

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = invitation
    db.execute.return_value = mock_result

    result = await validate_invitation_token(db, str(TOKEN_UUID))
    assert result["is_valid"] is False
    assert "already been accepted" in result["reason"].lower()


@pytest.mark.asyncio
async def test_validate_token_expired():
    past = NOW - timedelta(hours=1)
    invitation = _make_invitation(status=InvitationStatus.PENDING, expires_at=past)

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = invitation
    db.execute.return_value = mock_result

    with patch(
        "app.services.corporate_employee_invitation._now_utc", return_value=NOW
    ):
        result = await validate_invitation_token(db, str(TOKEN_UUID))

    assert result["is_valid"] is False
    assert "expired" in result["reason"].lower()


@pytest.mark.asyncio
async def test_validate_token_valid():
    invitation = _make_invitation(
        status=InvitationStatus.PENDING,
        expires_at=NOW + timedelta(days=5),
    )

    db = AsyncMock()
    inv_result = MagicMock()
    inv_result.scalar_one_or_none.return_value = invitation
    acc_result = MagicMock()
    acc_result.scalar_one_or_none.return_value = None  # no account lookup needed for is_valid check
    db.execute.side_effect = [inv_result, acc_result]

    with patch(
        "app.services.corporate_employee_invitation._now_utc", return_value=NOW
    ):
        result = await validate_invitation_token(db, str(TOKEN_UUID))

    assert result["is_valid"] is True
    assert result["email"] == invitation.email
    assert result["role"] == invitation.role


@pytest.mark.asyncio
async def test_validate_token_valid_with_account_name():
    invitation = _make_invitation(
        status=InvitationStatus.PENDING,
        expires_at=NOW + timedelta(days=5),
    )
    account = MagicMock()
    account.name = "ACME Corp"

    db = AsyncMock()
    inv_result = MagicMock()
    inv_result.scalar_one_or_none.return_value = invitation
    acc_result = MagicMock()
    acc_result.scalar_one_or_none.return_value = account
    db.execute.side_effect = [inv_result, acc_result]

    with patch(
        "app.services.corporate_employee_invitation._now_utc", return_value=NOW
    ):
        result = await validate_invitation_token(db, str(TOKEN_UUID))

    assert result["account_name"] == "ACME Corp"


# ---------------------------------------------------------------------------
# 24–27: accept_invitation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_invitation_success():
    invitation = _make_invitation(
        status=InvitationStatus.PENDING,
        role=InvitationRole.MEMBER,
        expires_at=NOW + timedelta(days=3),
    )
    account = MagicMock()
    account.name = "ACME Corp"

    db = AsyncMock()
    # validate_invitation_token calls: fetch_by_token, fetch account
    # accept_invitation calls: validate (2 executes), fetch_by_token again, check existing member
    inv_result = MagicMock()
    inv_result.scalar_one_or_none.return_value = invitation
    acc_result = MagicMock()
    acc_result.scalar_one_or_none.return_value = account
    no_member_result = MagicMock()
    no_member_result.scalar_one_or_none.return_value = None  # no existing membership
    db.execute.side_effect = [inv_result, acc_result, inv_result, no_member_result]

    with patch(
        "app.services.corporate_employee_invitation._now_utc", return_value=NOW
    ), patch(
        "app.services.corporate_employee_invitation._onboarding_svc.create_onboarding",
        new=AsyncMock(return_value=MagicMock()),
    ):
        result = await accept_invitation(db, str(TOKEN_UUID), accepting_user_id=99)

    assert result.status == InvitationStatus.ACCEPTED
    assert result.accepted_by_id == 99
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_accept_invitation_admin_role_creates_admin_member():
    invitation = _make_invitation(
        status=InvitationStatus.PENDING,
        role=InvitationRole.ADMIN,
        expires_at=NOW + timedelta(days=3),
    )
    account = MagicMock()
    account.name = "ACME Corp"

    db = AsyncMock()
    inv_result = MagicMock()
    inv_result.scalar_one_or_none.return_value = invitation
    acc_result = MagicMock()
    acc_result.scalar_one_or_none.return_value = account
    no_member_result = MagicMock()
    no_member_result.scalar_one_or_none.return_value = None
    db.execute.side_effect = [inv_result, acc_result, inv_result, no_member_result]

    with patch(
        "app.services.corporate_employee_invitation._now_utc", return_value=NOW
    ), patch(
        "app.services.corporate_employee_invitation._onboarding_svc.create_onboarding",
        new=AsyncMock(return_value=MagicMock()),
    ):
        await accept_invitation(db, str(TOKEN_UUID), accepting_user_id=99)

    added_obj = db.add.call_args[0][0]
    assert added_obj.role == MemberRole.ADMIN


@pytest.mark.asyncio
async def test_accept_invitation_invalid_token_raises_400():
    db = AsyncMock()
    inv_result = MagicMock()
    inv_result.scalar_one_or_none.return_value = None  # not found
    db.execute.return_value = inv_result

    with pytest.raises(HTTPException) as exc_info:
        await accept_invitation(db, str(uuid.uuid4()), accepting_user_id=99)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_accept_invitation_already_member_raises_409():
    invitation = _make_invitation(
        status=InvitationStatus.PENDING,
        expires_at=NOW + timedelta(days=3),
    )
    account = MagicMock()
    account.name = "ACME Corp"
    existing_membership = MagicMock(spec=BusinessAccountMember)

    db = AsyncMock()
    inv_result = MagicMock()
    inv_result.scalar_one_or_none.return_value = invitation
    acc_result = MagicMock()
    acc_result.scalar_one_or_none.return_value = account
    member_result = MagicMock()
    member_result.scalar_one_or_none.return_value = existing_membership
    db.execute.side_effect = [inv_result, acc_result, inv_result, member_result]

    with patch(
        "app.services.corporate_employee_invitation._now_utc", return_value=NOW
    ):
        with pytest.raises(HTTPException) as exc_info:
            await accept_invitation(db, str(TOKEN_UUID), accepting_user_id=99)
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 28: accept_invitation — onboarding record created on success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_invitation_creates_onboarding_record():
    """Accepting an invitation must auto-create a CorporateMemberOnboarding record."""
    invitation = _make_invitation(
        status=InvitationStatus.PENDING,
        role=InvitationRole.MEMBER,
        expires_at=NOW + timedelta(days=3),
    )
    account = MagicMock()
    account.name = "ACME Corp"

    db = AsyncMock()
    inv_result = MagicMock()
    inv_result.scalar_one_or_none.return_value = invitation
    acc_result = MagicMock()
    acc_result.scalar_one_or_none.return_value = account
    no_member_result = MagicMock()
    no_member_result.scalar_one_or_none.return_value = None
    db.execute.side_effect = [inv_result, acc_result, inv_result, no_member_result]

    fake_create_onboarding = AsyncMock(return_value=MagicMock())

    with patch(
        "app.services.corporate_employee_invitation._now_utc", return_value=NOW
    ), patch(
        "app.services.corporate_employee_invitation._onboarding_svc.create_onboarding",
        new=fake_create_onboarding,
    ):
        await accept_invitation(db, str(TOKEN_UUID), accepting_user_id=99)

    fake_create_onboarding.assert_awaited_once()
    call_kwargs = fake_create_onboarding.call_args
    assert call_kwargs.kwargs["member_id"] == 99
    assert call_kwargs.kwargs["account_id"] == invitation.account_id
    assert call_kwargs.kwargs["invitation_id"] == invitation.id


# ---------------------------------------------------------------------------
# 29: accept_invitation — existing onboarding 409 is silently ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_invitation_ignores_duplicate_onboarding():
    """If create_onboarding raises 409 (already exists), accept_invitation
    should still succeed rather than propagating the error."""
    from fastapi import HTTPException as FastAPIHTTPException

    invitation = _make_invitation(
        status=InvitationStatus.PENDING,
        role=InvitationRole.MEMBER,
        expires_at=NOW + timedelta(days=3),
    )
    account = MagicMock()
    account.name = "ACME Corp"

    db = AsyncMock()
    inv_result = MagicMock()
    inv_result.scalar_one_or_none.return_value = invitation
    acc_result = MagicMock()
    acc_result.scalar_one_or_none.return_value = account
    no_member_result = MagicMock()
    no_member_result.scalar_one_or_none.return_value = None
    db.execute.side_effect = [inv_result, acc_result, inv_result, no_member_result]

    duplicate_exc = FastAPIHTTPException(
        status_code=409, detail="An active onboarding already exists for this member."
    )

    with patch(
        "app.services.corporate_employee_invitation._now_utc", return_value=NOW
    ), patch(
        "app.services.corporate_employee_invitation._onboarding_svc.create_onboarding",
        new=AsyncMock(side_effect=duplicate_exc),
    ):
        # Should NOT raise — the 409 from create_onboarding is swallowed
        result = await accept_invitation(db, str(TOKEN_UUID), accepting_user_id=99)

    assert result.status == InvitationStatus.ACCEPTED


# ---------------------------------------------------------------------------
# 30: revoke_invitation — does NOT trigger onboarding creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_invitation_does_not_create_onboarding():
    """Revoking an invitation must never create an onboarding record."""
    invitation = _make_invitation(status=InvitationStatus.PENDING)

    db = AsyncMock()
    _make_execute_sequence(db, [_admin_member_mock(), invitation])

    fake_create_onboarding = AsyncMock(return_value=MagicMock())

    with patch(
        "app.services.corporate_employee_invitation._onboarding_svc.create_onboarding",
        new=fake_create_onboarding,
    ):
        result = await revoke_invitation(db, INVITE_ID, ACCOUNT_ID, ADMIN_USER_ID)

    assert result.status == InvitationStatus.REVOKED
    fake_create_onboarding.assert_not_awaited()


# ---------------------------------------------------------------------------
# 31–36: Schema tests (previously 28–33)
# ---------------------------------------------------------------------------


def test_schema_create_valid_default():
    d = InvitationCreate(email="test@example.com")
    assert d.email == "test@example.com"
    assert d.role == InvitationRole.MEMBER
    assert d.message is None
    assert d.expires_at is None


def test_schema_create_admin_role_with_message():
    d = InvitationCreate(
        email="admin@example.com",
        role=InvitationRole.ADMIN,
        message="Welcome to the team!",
    )
    assert d.role == InvitationRole.ADMIN
    assert d.message == "Welcome to the team!"


def test_schema_create_invalid_email():
    with pytest.raises(ValidationError):
        InvitationCreate(email="not-an-email")


def test_schema_create_expires_at_in_past():
    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValidationError):
        InvitationCreate(email="x@example.com", expires_at=past)


def test_schema_create_expires_at_omitted():
    d = InvitationCreate(email="y@example.com")
    assert d.expires_at is None  # handled by service


def test_schema_create_message_too_long():
    with pytest.raises(ValidationError):
        InvitationCreate(email="z@example.com", message="x" * 1001)


# ---------------------------------------------------------------------------
# 34–45: API layer tests
# ---------------------------------------------------------------------------


def _fake_invitation_response():
    """Return a MagicMock that survives model_validate."""
    inv = MagicMock()
    inv.id = INVITE_ID
    inv.account_id = ACCOUNT_ID
    inv.token = TOKEN_UUID
    inv.email = "alice@example.com"
    inv.invited_by_id = ADMIN_USER_ID
    inv.role = InvitationRole.MEMBER
    inv.message = None
    inv.expires_at = NOW + timedelta(days=7)
    inv.status = InvitationStatus.PENDING
    inv.accepted_at = None
    inv.accepted_by_id = None
    inv.revoked_at = None
    inv.revoked_by_id = None
    inv.created_at = NOW
    return inv


def _fake_member_result(account_id: int = ACCOUNT_ID):
    m = MagicMock()
    m.account_id = account_id
    return m


@pytest.mark.asyncio
async def test_api_create_invitation_201():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    invitation = _fake_invitation_response()

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_result()
        db.execute.return_value = result
        yield db

    fake_user = MagicMock(spec=User)
    fake_user.id = ADMIN_USER_ID
    fake_user.is_admin = False

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_employee_invitations.create_invitation",
        new=AsyncMock(return_value=invitation),
    ):
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/corporate/accounts/me/invitations",
                json={"email": "alice@example.com", "role": "member"},
            )
    assert resp.status_code == 201

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_list_invitations_200():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_result()
        db.execute.return_value = result
        yield db

    fake_user = MagicMock(spec=User)
    fake_user.id = ADMIN_USER_ID

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_employee_invitations.list_invitations",
        new=AsyncMock(return_value=([], 0)),
    ):
        with TestClient(app) as client:
            resp = client.get("/api/v1/corporate/accounts/me/invitations")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_get_invitation_200():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    invitation = _fake_invitation_response()

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_result()
        db.execute.return_value = result
        yield db

    fake_user = MagicMock(spec=User)
    fake_user.id = ADMIN_USER_ID

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_employee_invitations.get_invitation",
        new=AsyncMock(return_value=invitation),
    ):
        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/corporate/accounts/me/invitations/{INVITE_ID}"
            )
    assert resp.status_code == 200

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_revoke_invitation_200():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    invitation = _fake_invitation_response()
    invitation.status = InvitationStatus.REVOKED
    invitation.revoked_at = NOW
    invitation.revoked_by_id = ADMIN_USER_ID

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_result()
        db.execute.return_value = result
        yield db

    fake_user = MagicMock(spec=User)
    fake_user.id = ADMIN_USER_ID

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_employee_invitations.revoke_invitation",
        new=AsyncMock(return_value=invitation),
    ):
        with TestClient(app) as client:
            resp = client.delete(
                f"/api/v1/corporate/accounts/me/invitations/{INVITE_ID}"
            )
    assert resp.status_code == 200

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_validate_token_valid():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_db

    async def _fake_db():
        db = AsyncMock()
        yield db

    app.dependency_overrides[get_db] = _fake_db

    fake_validation = {
        "is_valid": True,
        "reason": None,
        "email": "alice@example.com",
        "role": InvitationRole.MEMBER,
        "account_name": "ACME Corp",
        "expires_at": NOW + timedelta(days=5),
    }

    with patch(
        "app.api.v1.corporate_employee_invitations.validate_invitation_token",
        new=AsyncMock(return_value=fake_validation),
    ):
        with TestClient(app) as client:
            resp = client.get(f"/api/v1/corporate/invitations/{TOKEN_UUID}")
    assert resp.status_code == 200
    assert resp.json()["is_valid"] is True

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_validate_token_invalid():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_db

    async def _fake_db():
        db = AsyncMock()
        yield db

    app.dependency_overrides[get_db] = _fake_db

    fake_validation = {
        "is_valid": False,
        "reason": "Token not found.",
        "email": None,
        "role": None,
        "account_name": None,
        "expires_at": None,
    }

    with patch(
        "app.api.v1.corporate_employee_invitations.validate_invitation_token",
        new=AsyncMock(return_value=fake_validation),
    ):
        with TestClient(app) as client:
            resp = client.get(f"/api/v1/corporate/invitations/{TOKEN_UUID}")
    assert resp.status_code == 200
    assert resp.json()["is_valid"] is False
    assert resp.json()["reason"] == "Token not found."

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_accept_invitation_200():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    invitation = _fake_invitation_response()
    invitation.status = InvitationStatus.ACCEPTED
    invitation.accepted_at = NOW
    invitation.accepted_by_id = 99

    async def _fake_db():
        db = AsyncMock()
        yield db

    fake_user = MagicMock(spec=User)
    fake_user.id = 99

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_employee_invitations.accept_invitation",
        new=AsyncMock(return_value=invitation),
    ):
        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/corporate/invitations/{TOKEN_UUID}/accept"
            )
    assert resp.status_code == 200

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_admin_list_all_invitations_200():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_db, require_admin

    async def _fake_db():
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        db.execute.side_effect = [count_result, rows_result]
        yield db

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[require_admin] = lambda: None

    with TestClient(app) as client:
        resp = client.get("/api/v1/admin/corporate/invitations")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_admin_list_account_invitations_200():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_db, require_admin

    async def _fake_db():
        db = AsyncMock()
        yield db

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[require_admin] = lambda: None

    with patch(
        "app.api.v1.corporate_employee_invitations.list_invitations",
        new=AsyncMock(return_value=([], 0)),
    ):
        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/invitations"
            )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_create_invitation_not_member_404():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None  # not a member
        db.execute.return_value = result
        yield db

    fake_user = MagicMock(spec=User)
    fake_user.id = 999

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/corporate/accounts/me/invitations",
            json={"email": "alice@example.com"},
        )
    assert resp.status_code == 404

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_revoke_accepted_invitation_409():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_result()
        db.execute.return_value = result
        yield db

    fake_user = MagicMock(spec=User)
    fake_user.id = ADMIN_USER_ID

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_employee_invitations.revoke_invitation",
        new=AsyncMock(
            side_effect=HTTPException(status_code=409, detail="Cannot revoke.")
        ),
    ):
        with TestClient(app) as client:
            resp = client.delete(
                f"/api/v1/corporate/accounts/me/invitations/{INVITE_ID}"
            )
    assert resp.status_code == 409

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_accept_invitation_already_member_409():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    async def _fake_db():
        db = AsyncMock()
        yield db

    fake_user = MagicMock(spec=User)
    fake_user.id = 99

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_employee_invitations.accept_invitation",
        new=AsyncMock(
            side_effect=HTTPException(
                status_code=409, detail="You are already a member of a corporate account."
            )
        ),
    ):
        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/corporate/invitations/{TOKEN_UUID}/accept"
            )
    assert resp.status_code == 409

    app.dependency_overrides.clear()
