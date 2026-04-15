"""Tests for the Corporate Bulk Employee Invitations feature.

Service tests (async, mocked DB):
  1.  create_bulk_invitations — all items succeed
  2.  create_bulk_invitations — non-admin caller → 403
  3.  create_bulk_invitations — one duplicate pending → skipped with reason
  4.  create_bulk_invitations — one email already active member → skipped
  5.  create_bulk_invitations — mixed batch: some created, some skipped
  6.  create_bulk_invitations — duplicate email within batch → second skipped
  7.  create_bulk_invitations — custom expires_at applied to all created items
  8.  create_bulk_invitations — emails normalized to lowercase
  9.  create_bulk_invitations — result counts match actual outcomes
  10. create_bulk_invitations — empty items list still runs (schema enforces ≥1)

Schema tests (sync):
  11. BulkInvitationRequest — valid single item
  12. BulkInvitationRequest — valid multiple items
  13. BulkInvitationRequest — empty list → ValidationError
  14. BulkInvitationRequest — over 100 items → ValidationError
  15. BulkInvitationRequest — expires_at in past → ValidationError
  16. BulkInvitationRequest — expires_at omitted → None (defaults in service)
  17. BulkInvitationItem — default role is MEMBER
  18. BulkInvitationItem — admin role accepted
  19. BulkInvitationItem — message too long → ValidationError
  20. BulkInvitationItem — invalid email → ValidationError

API layer tests (asyncio, service patched):
  21. POST /bulk — 200 all created, correct counts
  22. POST /bulk — 200 partial success (mix created + skipped)
  23. POST /bulk — 403 when not an account member
  24. POST /bulk — 422 empty invitations list
  25. POST /bulk — 422 over 100 items
  26. POST /bulk — results list length matches total_requested
  27. POST /bulk — skipped items have no invitation object
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_employee_invitation import (
    CorporateEmployeeInvitation,
    InvitationRole,
    InvitationStatus,
)
from app.schemas.corporate_employee_invitation import (
    BulkInvitationItem,
    BulkInvitationRequest,
    BulkInvitationResponse,
    InvitationResponse,
)
from app.services.corporate_employee_invitation import create_bulk_invitations

# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 77
ADMIN_USER_ID = 10
MEMBER_USER_ID = 20


def _make_invitation(
    email: str = "alice@example.com",
    role: InvitationRole = InvitationRole.MEMBER,
    account_id: int = ACCOUNT_ID,
    expires_at: datetime | None = None,
) -> CorporateEmployeeInvitation:
    inv = MagicMock(spec=CorporateEmployeeInvitation)
    inv.id = uuid.uuid4()
    inv.account_id = account_id
    inv.token = uuid.uuid4()
    inv.email = email
    inv.invited_by_id = ADMIN_USER_ID
    inv.role = role
    inv.message = None
    inv.expires_at = expires_at or (NOW + timedelta(days=7))
    inv.status = InvitationStatus.PENDING
    inv.accepted_at = None
    inv.accepted_by_id = None
    inv.revoked_at = None
    inv.revoked_by_id = None
    inv.created_at = NOW
    return inv


def _admin_member_mock() -> BusinessAccountMember:
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = ACCOUNT_ID
    m.user_id = ADMIN_USER_ID
    m.role = MemberRole.ADMIN
    m.is_active = True
    return m


def _make_execute_sequence(db: AsyncMock, responses: list) -> None:
    """Make db.execute return different mock results on successive calls."""
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
# 1–10: create_bulk_invitations service tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_create_all_succeed():
    """All items created when no conflicts exist."""
    db = AsyncMock()
    # admin check, then per-item: pending-check, member-check (×2 items)
    _make_execute_sequence(
        db,
        [_admin_member_mock(), None, None, None, None],
    )

    items = [
        BulkInvitationItem(email="alice@example.com"),
        BulkInvitationItem(email="bob@example.com"),
    ]
    results = await create_bulk_invitations(db, ACCOUNT_ID, ADMIN_USER_ID, items)

    assert len(results) == 2
    assert all(r["status"] == "created" for r in results)
    assert db.add.call_count == 2
    assert db.flush.call_count == 2


@pytest.mark.asyncio
async def test_bulk_create_non_admin_raises_403():
    """Non-admin caller raises HTTP 403 before processing any items."""
    db = AsyncMock()
    # admin check returns None → not an admin
    _make_execute_sequence(db, [None])

    items = [BulkInvitationItem(email="alice@example.com")]
    with pytest.raises(HTTPException) as exc_info:
        await create_bulk_invitations(db, ACCOUNT_ID, MEMBER_USER_ID, items)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_bulk_create_duplicate_pending_skipped():
    """An email with an existing pending invitation is skipped."""
    db = AsyncMock()
    existing_invite = _make_invitation(email="alice@example.com")
    # admin check OK, pending-check returns existing invite → skip, no member-check
    _make_execute_sequence(db, [_admin_member_mock(), existing_invite])

    items = [BulkInvitationItem(email="alice@example.com")]
    results = await create_bulk_invitations(db, ACCOUNT_ID, ADMIN_USER_ID, items)

    assert len(results) == 1
    assert results[0]["status"] == "skipped"
    assert "already exists" in results[0]["reason"]
    assert results[0]["invitation"] is None
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_bulk_create_existing_member_skipped():
    """An email that belongs to an existing active member is skipped."""
    db = AsyncMock()
    existing_member = MagicMock(spec=BusinessAccountMember)
    # admin check OK, pending-check: no pending, member-check: found → skip
    _make_execute_sequence(db, [_admin_member_mock(), None, existing_member])

    items = [BulkInvitationItem(email="bob@example.com")]
    results = await create_bulk_invitations(db, ACCOUNT_ID, ADMIN_USER_ID, items)

    assert len(results) == 1
    assert results[0]["status"] == "skipped"
    assert "already an active member" in results[0]["reason"]
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_bulk_create_mixed_batch():
    """Mixed batch: some created, one duplicate-pending, one active member."""
    db = AsyncMock()
    existing_invite = _make_invitation(email="dup@example.com")
    existing_member = MagicMock(spec=BusinessAccountMember)
    # admin check, then per item:
    # item1 (new): pending=None, member=None → created
    # item2 (dup pending): pending=existing_invite → skipped
    # item3 (active member): pending=None, member=existing_member → skipped
    _make_execute_sequence(
        db,
        [
            _admin_member_mock(),
            None, None,            # item1
            existing_invite,       # item2 pending-check
            None, existing_member, # item3
        ],
    )

    items = [
        BulkInvitationItem(email="new@example.com"),
        BulkInvitationItem(email="dup@example.com"),
        BulkInvitationItem(email="member@example.com"),
    ]
    results = await create_bulk_invitations(db, ACCOUNT_ID, ADMIN_USER_ID, items)

    assert len(results) == 3
    statuses = [r["status"] for r in results]
    assert statuses.count("created") == 1
    assert statuses.count("skipped") == 2
    assert results[0]["status"] == "created"
    assert results[1]["status"] == "skipped"
    assert results[2]["status"] == "skipped"


@pytest.mark.asyncio
async def test_bulk_create_duplicate_email_within_batch():
    """When the same email appears twice, the first is created and second is skipped."""
    db = AsyncMock()
    # admin check, item1 (no conflicts): pending=None, member=None → created
    # item2 (same email, now pending from item1): pending=created_invite → skipped
    created_invite = _make_invitation(email="same@example.com")
    _make_execute_sequence(
        db,
        [
            _admin_member_mock(),
            None, None,          # item1 checks
            created_invite,      # item2 pending-check finds item1's invite
        ],
    )

    items = [
        BulkInvitationItem(email="same@example.com"),
        BulkInvitationItem(email="same@example.com"),
    ]
    results = await create_bulk_invitations(db, ACCOUNT_ID, ADMIN_USER_ID, items)

    assert len(results) == 2
    assert results[0]["status"] == "created"
    assert results[1]["status"] == "skipped"


@pytest.mark.asyncio
async def test_bulk_create_custom_expires_at_applied():
    """Custom expires_at is used for all created invitations."""
    db = AsyncMock()
    custom_expiry = NOW + timedelta(days=30)
    _make_execute_sequence(db, [_admin_member_mock(), None, None])

    items = [BulkInvitationItem(email="carol@example.com")]
    results = await create_bulk_invitations(
        db, ACCOUNT_ID, ADMIN_USER_ID, items, expires_at=custom_expiry
    )

    assert results[0]["status"] == "created"
    # The invitation added to the DB should have the custom expiry
    added_inv = db.add.call_args[0][0]
    assert added_inv.expires_at == custom_expiry


@pytest.mark.asyncio
async def test_bulk_create_emails_normalized_lowercase():
    """Email addresses are stored in lowercase."""
    db = AsyncMock()
    _make_execute_sequence(db, [_admin_member_mock(), None, None])

    items = [BulkInvitationItem(email="Charlie@Example.COM")]
    results = await create_bulk_invitations(db, ACCOUNT_ID, ADMIN_USER_ID, items)

    assert results[0]["status"] == "created"
    assert results[0]["email"] == "charlie@example.com"
    added_inv = db.add.call_args[0][0]
    assert added_inv.email == "charlie@example.com"


@pytest.mark.asyncio
async def test_bulk_create_result_counts_correct():
    """Result dicts accurately reflect created/skipped/error counts."""
    db = AsyncMock()
    existing_invite = _make_invitation(email="b@example.com")
    _make_execute_sequence(
        db,
        [
            _admin_member_mock(),
            None, None,        # a: OK
            existing_invite,   # b: pending dup
        ],
    )

    items = [
        BulkInvitationItem(email="a@example.com"),
        BulkInvitationItem(email="b@example.com"),
    ]
    results = await create_bulk_invitations(db, ACCOUNT_ID, ADMIN_USER_ID, items)

    created = [r for r in results if r["status"] == "created"]
    skipped = [r for r in results if r["status"] == "skipped"]
    assert len(created) == 1
    assert len(skipped) == 1


@pytest.mark.asyncio
async def test_bulk_create_single_item_succeeds():
    """Minimal valid batch of one item works correctly."""
    db = AsyncMock()
    _make_execute_sequence(db, [_admin_member_mock(), None, None])

    items = [BulkInvitationItem(email="solo@example.com")]
    results = await create_bulk_invitations(db, ACCOUNT_ID, ADMIN_USER_ID, items)

    assert len(results) == 1
    assert results[0]["status"] == "created"
    assert results[0]["email"] == "solo@example.com"


# ---------------------------------------------------------------------------
# 11–20: Schema tests
# ---------------------------------------------------------------------------


def test_bulk_request_valid_single():
    """Valid single-item bulk request."""
    req = BulkInvitationRequest(
        invitations=[BulkInvitationItem(email="x@example.com")]
    )
    assert len(req.invitations) == 1
    assert req.expires_at is None


def test_bulk_request_valid_multiple():
    """Valid multi-item bulk request with mixed roles."""
    req = BulkInvitationRequest(
        invitations=[
            BulkInvitationItem(email="a@example.com", role=InvitationRole.ADMIN),
            BulkInvitationItem(email="b@example.com", role=InvitationRole.MEMBER),
        ]
    )
    assert len(req.invitations) == 2
    assert req.invitations[0].role == InvitationRole.ADMIN


def test_bulk_request_empty_list_raises():
    """Empty invitations list fails Pydantic validation."""
    with pytest.raises(ValidationError):
        BulkInvitationRequest(invitations=[])


def test_bulk_request_over_100_items_raises():
    """More than 100 items fails Pydantic validation."""
    with pytest.raises(ValidationError):
        BulkInvitationRequest(
            invitations=[
                BulkInvitationItem(email=f"user{i}@example.com")
                for i in range(101)
            ]
        )


def test_bulk_request_expires_in_past_raises():
    """expires_at in the past fails validation."""
    past = datetime.now(tz=timezone.utc) - timedelta(days=1)
    with pytest.raises(ValidationError):
        BulkInvitationRequest(
            invitations=[BulkInvitationItem(email="x@example.com")],
            expires_at=past,
        )


def test_bulk_request_expires_at_none_default():
    """expires_at omitted produces None (service applies default)."""
    req = BulkInvitationRequest(
        invitations=[BulkInvitationItem(email="x@example.com")]
    )
    assert req.expires_at is None


def test_bulk_item_default_role_is_member():
    """BulkInvitationItem defaults role to MEMBER."""
    item = BulkInvitationItem(email="z@example.com")
    assert item.role == InvitationRole.MEMBER


def test_bulk_item_admin_role_accepted():
    """BulkInvitationItem accepts ADMIN role."""
    item = BulkInvitationItem(email="z@example.com", role=InvitationRole.ADMIN)
    assert item.role == InvitationRole.ADMIN


def test_bulk_item_message_too_long_raises():
    """Message exceeding 1000 chars fails validation."""
    with pytest.raises(ValidationError):
        BulkInvitationItem(email="z@example.com", message="x" * 1001)


def test_bulk_item_invalid_email_raises():
    """Invalid email address fails Pydantic validation."""
    with pytest.raises(ValidationError):
        BulkInvitationItem(email="not-an-email")


# ---------------------------------------------------------------------------
# 21–27: API layer tests (uses app.dependency_overrides pattern)
# ---------------------------------------------------------------------------

_BULK_ENDPOINT = "/api/v1/corporate/accounts/me/invitations/bulk"


def _make_service_result(
    email: str,
    role: InvitationRole = InvitationRole.MEMBER,
    status_val: str = "created",
    reason: str | None = None,
) -> dict:
    if status_val == "created":
        inv = _make_invitation(email=email, role=role)
        return {"email": email, "role": role, "status": "created", "reason": None, "invitation": inv}
    return {"email": email, "role": role, "status": status_val, "reason": reason, "invitation": None}


def _fake_member_result(account_id: int = ACCOUNT_ID):
    m = MagicMock()
    m.account_id = account_id
    return m


@pytest.mark.asyncio
async def test_api_bulk_create_all_succeed():
    """POST /bulk — 200 all created, correct aggregate counts."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    fake_user = MagicMock(spec=User)
    fake_user.id = ADMIN_USER_ID

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_result()
        db.execute.return_value = result
        yield db

    service_results = [
        _make_service_result("a@example.com"),
        _make_service_result("b@example.com"),
    ]

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_employee_invitations.create_bulk_invitations",
        new=AsyncMock(return_value=service_results),
    ):
        with TestClient(app) as client:
            resp = client.post(
                _BULK_ENDPOINT,
                json={
                    "invitations": [
                        {"email": "a@example.com"},
                        {"email": "b@example.com"},
                    ]
                },
            )

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_requested"] == 2
    assert body["total_created"] == 2
    assert body["total_skipped"] == 0
    assert body["total_errors"] == 0
    assert len(body["results"]) == 2


@pytest.mark.asyncio
async def test_api_bulk_create_partial_success():
    """POST /bulk — 200 with mixed created + skipped."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    fake_user = MagicMock(spec=User)
    fake_user.id = ADMIN_USER_ID

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_result()
        db.execute.return_value = result
        yield db

    service_results = [
        _make_service_result("new@example.com", status_val="created"),
        _make_service_result(
            "dup@example.com",
            status_val="skipped",
            reason="A pending invitation for this email already exists.",
        ),
    ]

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_employee_invitations.create_bulk_invitations",
        new=AsyncMock(return_value=service_results),
    ):
        with TestClient(app) as client:
            resp = client.post(
                _BULK_ENDPOINT,
                json={
                    "invitations": [
                        {"email": "new@example.com"},
                        {"email": "dup@example.com"},
                    ]
                },
            )

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_created"] == 1
    assert body["total_skipped"] == 1
    assert body["total_errors"] == 0


@pytest.mark.asyncio
async def test_api_bulk_create_not_member_404():
    """POST /bulk — 404 when user is not an active account member."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    fake_user = MagicMock(spec=User)
    fake_user.id = 999

    async def _fake_db():
        db = AsyncMock()
        # membership lookup returns None → _get_member_account_id raises 404
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result
        yield db

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            _BULK_ENDPOINT,
            json={"invitations": [{"email": "x@example.com"}]},
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 404


def test_api_bulk_create_empty_list_422():
    """POST /bulk — 422 for empty invitations list (Pydantic validation)."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    fake_user = MagicMock(spec=User)
    fake_user.id = ADMIN_USER_ID

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_result()
        db.execute.return_value = result
        yield db

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(_BULK_ENDPOINT, json={"invitations": []})

    app.dependency_overrides.clear()

    assert resp.status_code == 422


def test_api_bulk_create_over_100_items_422():
    """POST /bulk — 422 for more than 100 items."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    fake_user = MagicMock(spec=User)
    fake_user.id = ADMIN_USER_ID

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_result()
        db.execute.return_value = result
        yield db

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            _BULK_ENDPOINT,
            json={"invitations": [{"email": f"u{i}@example.com"} for i in range(101)]},
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_api_bulk_results_length_matches_total_requested():
    """results list length always equals total_requested."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    fake_user = MagicMock(spec=User)
    fake_user.id = ADMIN_USER_ID

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_result()
        db.execute.return_value = result
        yield db

    service_results = [
        _make_service_result("a@example.com", status_val="created"),
        _make_service_result("b@example.com", status_val="skipped", reason="dup"),
        _make_service_result("c@example.com", status_val="created"),
    ]

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_employee_invitations.create_bulk_invitations",
        new=AsyncMock(return_value=service_results),
    ):
        with TestClient(app) as client:
            resp = client.post(
                _BULK_ENDPOINT,
                json={
                    "invitations": [
                        {"email": "a@example.com"},
                        {"email": "b@example.com"},
                        {"email": "c@example.com"},
                    ]
                },
            )

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == body["total_requested"] == 3


@pytest.mark.asyncio
async def test_api_bulk_skipped_items_have_no_invitation():
    """Skipped items must not include an invitation object in the response."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db
    from app.models.user import User

    fake_user = MagicMock(spec=User)
    fake_user.id = ADMIN_USER_ID

    async def _fake_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = _fake_member_result()
        db.execute.return_value = result
        yield db

    service_results = [
        _make_service_result(
            "dup@example.com",
            status_val="skipped",
            reason="A pending invitation for this email already exists.",
        ),
    ]

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with patch(
        "app.api.v1.corporate_employee_invitations.create_bulk_invitations",
        new=AsyncMock(return_value=service_results),
    ):
        with TestClient(app) as client:
            resp = client.post(
                _BULK_ENDPOINT,
                json={"invitations": [{"email": "dup@example.com"}]},
            )

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    result_item = resp.json()["results"][0]
    assert result_item["status"] == "skipped"
    assert result_item["invitation"] is None
    assert "already exists" in result_item["reason"]
