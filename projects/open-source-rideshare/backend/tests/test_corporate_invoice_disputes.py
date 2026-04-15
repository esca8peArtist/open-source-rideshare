"""Tests for the Corporate Invoice Disputes feature.

Service layer (async, mocked DB):
  1.  submit_dispute — happy path creates dispute with status=submitted
  2.  submit_dispute — 404 when invoice not found
  3.  submit_dispute — 404 when invoice belongs to different account
  4.  submit_dispute — 409 when active dispute exists (submitted)
  5.  submit_dispute — 409 when active dispute exists (under_review)
  6.  submit_dispute — allows new dispute after previous was resolved
  7.  get_dispute — returns None when not found
  8.  get_dispute — returns dispute when found
  9.  list_account_disputes — returns disputes ordered by created_at desc
  10. list_account_disputes — filters by status
  11. update_dispute — happy path updates description and type
  12. update_dispute — 404 when dispute not found
  13. update_dispute — 409 when not in submitted status
  14. mark_under_review — happy path sets status=under_review
  15. mark_under_review — 409 when already resolved
  16. resolve_dispute — happy path upheld sets resolved fields
  17. resolve_dispute — happy path denied
  18. resolve_dispute — 409 when already resolved
  19. withdraw_dispute — happy path sets status=withdrawn
  20. withdraw_dispute — 409 when already resolved
  21. withdraw_dispute — 404 wrong account
  22. list_all_disputes — returns all disputes across accounts
  23. list_all_disputes — filters by status

Schema validation tests:
  24. SubmitDisputeRequest — valid construction
  25. SubmitDisputeRequest — description min length enforced
  26. SubmitDisputeRequest — disputed_amount_usd must be >= 0
  27. ResolveDisputeRequest — resolved_upheld valid
  28. ResolveDisputeRequest — resolved_denied valid
  29. ResolveDisputeRequest — submitted not valid (must be upheld/denied)
  30. InvoiceDisputeResponse — from_attributes config
  31. InvoiceDisputeListResponse — valid construction

API layer tests (services patched):
  32. POST /corporate/invoices/{id}/disputes — 201 happy path
  33. POST /corporate/invoices/{id}/disputes — 404 not a member
  34. GET  /corporate/invoices/{id}/disputes — 200 returns list
  35. PUT  /corporate/disputes/{id} — 200 updates dispute
  36. DELETE /corporate/disputes/{id}/withdraw — 200 withdraws
  37. POST /corporate/disputes/{id}/review — 200 admin marks under review
  38. POST /corporate/disputes/{id}/resolve — 200 admin resolves
  39. GET  /admin/corporate/disputes — 200 admin lists all
  40. POST /corporate/disputes/{id}/review — 403 non-admin
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_invoice_dispute import (
    CorporateInvoiceDispute,
    DisputeStatus,
    DisputeType,
)
from app.schemas.corporate_invoice_dispute import (
    InvoiceDisputeListResponse,
    InvoiceDisputeResponse,
    ResolveDisputeRequest,
    SubmitDisputeRequest,
)
from app.services.corporate_invoice_dispute import (
    get_dispute,
    list_account_disputes,
    list_all_disputes,
    mark_under_review,
    resolve_dispute,
    submit_dispute,
    update_dispute,
    withdraw_dispute,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 10
ADMIN_ID = 99
USER_ID = 7
DISPUTE_ID = 1
INVOICE_ID = 42

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)

_ROUTER = "app.api.v1.corporate_invoice_disputes"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dispute(
    dispute_id: int = DISPUTE_ID,
    invoice_id: int = INVOICE_ID,
    account_id: int = ACCOUNT_ID,
    submitted_by_id: int | None = USER_ID,
    dispute_type: DisputeType = DisputeType.incorrect_charge,
    description: str = "This charge is incorrect and should be refunded.",
    status: DisputeStatus = DisputeStatus.submitted,
    disputed_rides: list | None = None,
    disputed_amount_usd: Decimal | None = None,
    resolution_note: str | None = None,
    resolved_by_id: int | None = None,
    resolved_at: datetime | None = None,
) -> CorporateInvoiceDispute:
    """Build a minimal CorporateInvoiceDispute model instance for testing."""
    d = CorporateInvoiceDispute()
    d.id = dispute_id
    d.invoice_id = invoice_id
    d.account_id = account_id
    d.submitted_by_id = submitted_by_id
    d.dispute_type = dispute_type
    d.description = description
    d.status = status
    d.disputed_rides = disputed_rides
    d.disputed_amount_usd = disputed_amount_usd
    d.resolution_note = resolution_note
    d.resolved_by_id = resolved_by_id
    d.resolved_at = resolved_at
    d.created_at = _NOW
    d.updated_at = _NOW
    return d


def _make_invoice_mock(invoice_id: int = INVOICE_ID, account_id: int = ACCOUNT_ID):
    """Build a minimal mock invoice object."""
    inv = MagicMock()
    inv.id = invoice_id
    inv.account_id = account_id
    return inv


def _make_response(
    dispute_id: int = DISPUTE_ID,
    account_id: int = ACCOUNT_ID,
    status: DisputeStatus = DisputeStatus.submitted,
) -> InvoiceDisputeResponse:
    return InvoiceDisputeResponse(
        id=dispute_id,
        invoice_id=INVOICE_ID,
        account_id=account_id,
        submitted_by_id=USER_ID,
        dispute_type=DisputeType.incorrect_charge,
        description="This charge is incorrect and should be refunded.",
        disputed_rides=None,
        disputed_amount_usd=None,
        status=status,
        resolution_note=None,
        resolved_by_id=None,
        resolved_at=None,
        created_at=_NOW,
        updated_at=_NOW,
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
# 1. submit_dispute — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_dispute_success():
    db = AsyncMock()
    invoice = _make_invoice_mock()

    # First execute: invoice lookup; second execute: active dispute check
    db.execute = AsyncMock(
        side_effect=[
            _make_execute_result_scalar(invoice),
            _make_execute_result_scalar(None),
        ]
    )
    db.commit = AsyncMock()

    added = []

    def _add(obj):
        added.append(obj)
        obj.id = DISPUTE_ID
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.add = _add
    db.refresh = AsyncMock()

    result = await submit_dispute(
        db,
        invoice_id=INVOICE_ID,
        account_id=ACCOUNT_ID,
        submitted_by_id=USER_ID,
        dispute_type=DisputeType.incorrect_charge,
        description="This charge is incorrect and should be refunded.",
        disputed_rides=None,
        disputed_amount_usd=None,
    )

    assert len(added) == 1
    dispute = added[0]
    assert dispute.invoice_id == INVOICE_ID
    assert dispute.account_id == ACCOUNT_ID
    assert dispute.submitted_by_id == USER_ID
    assert dispute.status == DisputeStatus.submitted
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 2. submit_dispute — 404 when invoice not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_dispute_404_invoice_not_found():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(None))

    with pytest.raises(HTTPException) as exc_info:
        await submit_dispute(
            db,
            invoice_id=INVOICE_ID,
            account_id=ACCOUNT_ID,
            submitted_by_id=USER_ID,
            dispute_type=DisputeType.incorrect_charge,
            description="This charge is incorrect and should be refunded.",
            disputed_rides=None,
            disputed_amount_usd=None,
        )

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 3. submit_dispute — 404 when invoice belongs to different account
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_dispute_404_wrong_account():
    db = AsyncMock()
    # Invoice query returns None (doesn't match account_id filter)
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(None))

    with pytest.raises(HTTPException) as exc_info:
        await submit_dispute(
            db,
            invoice_id=INVOICE_ID,
            account_id=999,  # wrong account
            submitted_by_id=USER_ID,
            dispute_type=DisputeType.incorrect_charge,
            description="This charge is incorrect and should be refunded.",
            disputed_rides=None,
            disputed_amount_usd=None,
        )

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 4. submit_dispute — 409 when active dispute exists (submitted)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_dispute_409_active_submitted():
    db = AsyncMock()
    invoice = _make_invoice_mock()
    existing = _make_dispute(status=DisputeStatus.submitted)

    db.execute = AsyncMock(
        side_effect=[
            _make_execute_result_scalar(invoice),
            _make_execute_result_scalar(existing),
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await submit_dispute(
            db,
            invoice_id=INVOICE_ID,
            account_id=ACCOUNT_ID,
            submitted_by_id=USER_ID,
            dispute_type=DisputeType.incorrect_charge,
            description="This charge is incorrect and should be refunded.",
            disputed_rides=None,
            disputed_amount_usd=None,
        )

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 5. submit_dispute — 409 when active dispute exists (under_review)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_dispute_409_active_under_review():
    db = AsyncMock()
    invoice = _make_invoice_mock()
    existing = _make_dispute(status=DisputeStatus.under_review)

    db.execute = AsyncMock(
        side_effect=[
            _make_execute_result_scalar(invoice),
            _make_execute_result_scalar(existing),
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await submit_dispute(
            db,
            invoice_id=INVOICE_ID,
            account_id=ACCOUNT_ID,
            submitted_by_id=USER_ID,
            dispute_type=DisputeType.incorrect_charge,
            description="This charge is incorrect and should be refunded.",
            disputed_rides=None,
            disputed_amount_usd=None,
        )

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 6. submit_dispute — allows new dispute after previous was resolved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_dispute_allows_after_resolved():
    db = AsyncMock()
    invoice = _make_invoice_mock()

    # No active dispute found (previous was resolved)
    db.execute = AsyncMock(
        side_effect=[
            _make_execute_result_scalar(invoice),
            _make_execute_result_scalar(None),
        ]
    )
    db.commit = AsyncMock()

    added = []

    def _add(obj):
        added.append(obj)
        obj.id = DISPUTE_ID + 1
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.add = _add
    db.refresh = AsyncMock()

    result = await submit_dispute(
        db,
        invoice_id=INVOICE_ID,
        account_id=ACCOUNT_ID,
        submitted_by_id=USER_ID,
        dispute_type=DisputeType.duplicate_charge,
        description="This charge appeared twice on our statement.",
        disputed_rides=None,
        disputed_amount_usd=None,
    )

    assert len(added) == 1
    assert added[0].dispute_type == DisputeType.duplicate_charge


# ---------------------------------------------------------------------------
# 7. get_dispute — returns None when not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_dispute_returns_none():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(None))

    result = await get_dispute(db, DISPUTE_ID)

    assert result is None


# ---------------------------------------------------------------------------
# 8. get_dispute — returns dispute when found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_dispute_returns_record():
    db = AsyncMock()
    dispute = _make_dispute()
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(dispute))

    result = await get_dispute(db, DISPUTE_ID)

    assert result is dispute
    assert result.id == DISPUTE_ID


# ---------------------------------------------------------------------------
# 9. list_account_disputes — returns disputes ordered by created_at desc
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_account_disputes_returns_ordered():
    db = AsyncMock()
    d1 = _make_dispute(dispute_id=2)
    d2 = _make_dispute(dispute_id=1)
    db.execute = AsyncMock(return_value=_make_execute_result_scalars([d1, d2]))

    result = await list_account_disputes(db, ACCOUNT_ID)

    assert len(result) == 2
    assert result[0].id == 2
    assert result[1].id == 1


# ---------------------------------------------------------------------------
# 10. list_account_disputes — filters by status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_account_disputes_filters_by_status():
    db = AsyncMock()
    d = _make_dispute(status=DisputeStatus.under_review)
    db.execute = AsyncMock(return_value=_make_execute_result_scalars([d]))

    result = await list_account_disputes(db, ACCOUNT_ID, status_filter=DisputeStatus.under_review)

    assert len(result) == 1
    assert result[0].status == DisputeStatus.under_review


# ---------------------------------------------------------------------------
# 11. update_dispute — happy path updates fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_dispute_success():
    db = AsyncMock()
    dispute = _make_dispute(status=DisputeStatus.submitted)
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(dispute))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    result = await update_dispute(
        db,
        dispute_id=DISPUTE_ID,
        account_id=ACCOUNT_ID,
        description="Updated description that is long enough.",
        dispute_type=DisputeType.service_failure,
    )

    assert dispute.description == "Updated description that is long enough."
    assert dispute.dispute_type == DisputeType.service_failure
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 12. update_dispute — 404 when dispute not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_dispute_404_not_found():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(None))

    with pytest.raises(HTTPException) as exc_info:
        await update_dispute(db, dispute_id=DISPUTE_ID, account_id=ACCOUNT_ID)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 13. update_dispute — 409 when not in submitted status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_dispute_409_not_submitted():
    db = AsyncMock()
    dispute = _make_dispute(status=DisputeStatus.under_review)
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(dispute))

    with pytest.raises(HTTPException) as exc_info:
        await update_dispute(
            db,
            dispute_id=DISPUTE_ID,
            account_id=ACCOUNT_ID,
            description="Trying to update after review started.",
        )

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 14. mark_under_review — happy path sets status=under_review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_under_review_success():
    db = AsyncMock()
    dispute = _make_dispute(status=DisputeStatus.submitted)
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(dispute))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    result = await mark_under_review(db, dispute_id=DISPUTE_ID, reviewed_by_id=ADMIN_ID)

    assert dispute.status == DisputeStatus.under_review
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 15. mark_under_review — 409 when already resolved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_under_review_409_already_resolved():
    db = AsyncMock()
    dispute = _make_dispute(status=DisputeStatus.resolved_upheld)
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(dispute))

    with pytest.raises(HTTPException) as exc_info:
        await mark_under_review(db, dispute_id=DISPUTE_ID, reviewed_by_id=ADMIN_ID)

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 16. resolve_dispute — happy path upheld sets resolved fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_dispute_upheld():
    db = AsyncMock()
    dispute = _make_dispute(status=DisputeStatus.under_review)
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(dispute))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    before = datetime.now(timezone.utc)
    result = await resolve_dispute(
        db,
        dispute_id=DISPUTE_ID,
        resolved_by_id=ADMIN_ID,
        resolution=DisputeStatus.resolved_upheld,
        resolution_note="Charge was indeed incorrect.",
    )
    after = datetime.now(timezone.utc)

    assert dispute.status == DisputeStatus.resolved_upheld
    assert dispute.resolved_by_id == ADMIN_ID
    assert dispute.resolution_note == "Charge was indeed incorrect."
    assert dispute.resolved_at is not None
    assert before <= dispute.resolved_at <= after
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 17. resolve_dispute — happy path denied
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_dispute_denied():
    db = AsyncMock()
    dispute = _make_dispute(status=DisputeStatus.under_review)
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(dispute))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    await resolve_dispute(
        db,
        dispute_id=DISPUTE_ID,
        resolved_by_id=ADMIN_ID,
        resolution=DisputeStatus.resolved_denied,
        resolution_note="Charge is valid per contract terms.",
    )

    assert dispute.status == DisputeStatus.resolved_denied
    assert dispute.resolution_note == "Charge is valid per contract terms."


# ---------------------------------------------------------------------------
# 18. resolve_dispute — 409 when already resolved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_dispute_409_already_resolved():
    db = AsyncMock()
    dispute = _make_dispute(status=DisputeStatus.resolved_denied)
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(dispute))

    with pytest.raises(HTTPException) as exc_info:
        await resolve_dispute(
            db,
            dispute_id=DISPUTE_ID,
            resolved_by_id=ADMIN_ID,
            resolution=DisputeStatus.resolved_upheld,
            resolution_note=None,
        )

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 19. withdraw_dispute — happy path sets status=withdrawn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_withdraw_dispute_success():
    db = AsyncMock()
    dispute = _make_dispute(status=DisputeStatus.submitted)
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(dispute))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    result = await withdraw_dispute(db, dispute_id=DISPUTE_ID, account_id=ACCOUNT_ID)

    assert dispute.status == DisputeStatus.withdrawn
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 20. withdraw_dispute — 409 when already resolved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_withdraw_dispute_409_already_resolved():
    db = AsyncMock()
    dispute = _make_dispute(status=DisputeStatus.resolved_upheld)
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(dispute))

    with pytest.raises(HTTPException) as exc_info:
        await withdraw_dispute(db, dispute_id=DISPUTE_ID, account_id=ACCOUNT_ID)

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 21. withdraw_dispute — 404 wrong account
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_withdraw_dispute_404_wrong_account():
    db = AsyncMock()
    dispute = _make_dispute(account_id=ACCOUNT_ID)
    db.execute = AsyncMock(return_value=_make_execute_result_scalar(dispute))

    with pytest.raises(HTTPException) as exc_info:
        await withdraw_dispute(db, dispute_id=DISPUTE_ID, account_id=999)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 22. list_all_disputes — returns all disputes across accounts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_disputes_returns_all():
    db = AsyncMock()
    d1 = _make_dispute(dispute_id=1, account_id=10)
    d2 = _make_dispute(dispute_id=2, account_id=20)
    db.execute = AsyncMock(return_value=_make_execute_result_scalars([d1, d2]))

    result = await list_all_disputes(db)

    assert len(result) == 2


# ---------------------------------------------------------------------------
# 23. list_all_disputes — filters by status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_disputes_filters_by_status():
    db = AsyncMock()
    d = _make_dispute(status=DisputeStatus.submitted)
    db.execute = AsyncMock(return_value=_make_execute_result_scalars([d]))

    result = await list_all_disputes(db, status_filter=DisputeStatus.submitted)

    assert len(result) == 1
    assert result[0].status == DisputeStatus.submitted


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


# 24. SubmitDisputeRequest — valid construction
def test_submit_dispute_request_valid():
    req = SubmitDisputeRequest(
        dispute_type=DisputeType.incorrect_charge,
        description="This charge is incorrect and should be refunded.",
    )
    assert req.dispute_type == DisputeType.incorrect_charge
    assert req.disputed_rides is None
    assert req.disputed_amount_usd is None


# 25. SubmitDisputeRequest — description min length enforced
def test_submit_dispute_request_description_too_short():
    with pytest.raises(ValidationError):
        SubmitDisputeRequest(
            dispute_type=DisputeType.other,
            description="Short",  # less than 10 chars
        )


# 26. SubmitDisputeRequest — disputed_amount_usd must be >= 0
def test_submit_dispute_request_negative_amount():
    with pytest.raises(ValidationError):
        SubmitDisputeRequest(
            dispute_type=DisputeType.pricing_discrepancy,
            description="This amount is wrong and should be corrected.",
            disputed_amount_usd=Decimal("-10.00"),
        )


# 27. ResolveDisputeRequest — resolved_upheld valid
def test_resolve_request_upheld_valid():
    req = ResolveDisputeRequest(resolution=DisputeStatus.resolved_upheld)
    assert req.resolution == DisputeStatus.resolved_upheld


# 28. ResolveDisputeRequest — resolved_denied valid
def test_resolve_request_denied_valid():
    req = ResolveDisputeRequest(resolution=DisputeStatus.resolved_denied)
    assert req.resolution == DisputeStatus.resolved_denied


# 29. ResolveDisputeRequest — submitted not valid
def test_resolve_request_submitted_invalid():
    with pytest.raises(ValidationError):
        ResolveDisputeRequest(resolution=DisputeStatus.submitted)


# 30. InvoiceDisputeResponse — from_attributes config
def test_invoice_dispute_response_from_attributes():
    resp = _make_response()
    assert resp.id == DISPUTE_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.status == DisputeStatus.submitted
    assert resp.dispute_type == DisputeType.incorrect_charge


# 31. InvoiceDisputeListResponse — valid construction
def test_invoice_dispute_list_response_valid():
    resp = InvoiceDisputeListResponse(
        disputes=[_make_response()],
        total=1,
    )
    assert resp.total == 1
    assert len(resp.disputes) == 1


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------


# 32. POST /corporate/invoices/{id}/disputes — 201 happy path
@pytest.mark.asyncio
async def test_api_submit_dispute_201():
    from app.api.v1.corporate_invoice_disputes import submit_invoice_dispute

    user = _mock_user()
    db = AsyncMock()
    payload = SubmitDisputeRequest(
        dispute_type=DisputeType.incorrect_charge,
        description="This charge is incorrect and should be refunded.",
    )
    mock_response = _make_response()

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.submit_dispute", new=AsyncMock(return_value=mock_response)):
        result = await submit_invoice_dispute(
            invoice_id=INVOICE_ID,
            payload=payload,
            user=user,
            db=db,
        )

    assert result.account_id == ACCOUNT_ID
    assert result.status == DisputeStatus.submitted


# 33. POST /corporate/invoices/{id}/disputes — 404 not a member
@pytest.mark.asyncio
async def test_api_submit_dispute_404_not_member():
    from app.api.v1.corporate_invoice_disputes import submit_invoice_dispute

    user = _mock_user()
    db = AsyncMock()
    payload = SubmitDisputeRequest(
        dispute_type=DisputeType.incorrect_charge,
        description="This charge is incorrect and should be refunded.",
    )

    with patch(
        f"{_ROUTER}._get_member_account_id",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not a member")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await submit_invoice_dispute(
                invoice_id=INVOICE_ID, payload=payload, user=user, db=db
            )

    assert exc_info.value.status_code == 404


# 34. GET /corporate/invoices/{id}/disputes — 200 returns list
@pytest.mark.asyncio
async def test_api_list_invoice_disputes_200():
    from app.api.v1.corporate_invoice_disputes import list_invoice_disputes

    user = _mock_user()
    db = AsyncMock()
    records = [_make_dispute()]

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.get_dispute_by_invoice", new=AsyncMock(return_value=records)):
        result = await list_invoice_disputes(invoice_id=INVOICE_ID, user=user, db=db)

    assert result.total == 1
    assert len(result.disputes) == 1


# 35. PUT /corporate/disputes/{id} — 200 updates dispute
@pytest.mark.asyncio
async def test_api_update_dispute_200():
    from app.api.v1.corporate_invoice_disputes import update_invoice_dispute
    from app.schemas.corporate_invoice_dispute import UpdateDisputeRequest

    user = _mock_user()
    db = AsyncMock()
    payload = UpdateDisputeRequest(description="Updated description that is long enough.")
    mock_response = _make_response()

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.update_dispute", new=AsyncMock(return_value=mock_response)):
        result = await update_invoice_dispute(
            dispute_id=DISPUTE_ID, payload=payload, user=user, db=db
        )

    assert result.id == DISPUTE_ID


# 36. DELETE /corporate/disputes/{id}/withdraw — 200 withdraws
@pytest.mark.asyncio
async def test_api_withdraw_dispute_200():
    from app.api.v1.corporate_invoice_disputes import withdraw_invoice_dispute

    user = _mock_user()
    db = AsyncMock()
    mock_response = _make_response(status=DisputeStatus.withdrawn)

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.withdraw_dispute", new=AsyncMock(return_value=mock_response)):
        result = await withdraw_invoice_dispute(dispute_id=DISPUTE_ID, user=user, db=db)

    assert result.status == DisputeStatus.withdrawn


# 37. POST /corporate/disputes/{id}/review — 200 admin marks under review
@pytest.mark.asyncio
async def test_api_mark_under_review_200():
    from app.api.v1.corporate_invoice_disputes import admin_mark_dispute_under_review
    from app.schemas.corporate_invoice_dispute import ReviewDisputeRequest

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    mock_response = _make_response(status=DisputeStatus.under_review)

    with patch(f"{_ROUTER}.mark_under_review", new=AsyncMock(return_value=mock_response)):
        result = await admin_mark_dispute_under_review(
            dispute_id=DISPUTE_ID,
            _payload=ReviewDisputeRequest(),
            _admin=admin,
            db=db,
        )

    assert result.status == DisputeStatus.under_review


# 38. POST /corporate/disputes/{id}/resolve — 200 admin resolves
@pytest.mark.asyncio
async def test_api_resolve_dispute_200():
    from app.api.v1.corporate_invoice_disputes import admin_resolve_dispute

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    payload = ResolveDisputeRequest(
        resolution=DisputeStatus.resolved_upheld,
        resolution_note="Charge verified as incorrect.",
    )
    mock_response = _make_response(status=DisputeStatus.resolved_upheld)

    with patch(f"{_ROUTER}.resolve_dispute", new=AsyncMock(return_value=mock_response)):
        result = await admin_resolve_dispute(
            dispute_id=DISPUTE_ID, payload=payload, _admin=admin, db=db
        )

    assert result.status == DisputeStatus.resolved_upheld


# 39. GET /admin/corporate/disputes — 200 admin lists all
@pytest.mark.asyncio
async def test_api_admin_list_all_disputes_200():
    from app.api.v1.corporate_invoice_disputes import admin_list_all_disputes

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    records = [_make_dispute(account_id=10), _make_dispute(dispute_id=2, account_id=20)]

    with patch(f"{_ROUTER}.list_all_disputes", new=AsyncMock(return_value=records)):
        result = await admin_list_all_disputes(
            dispute_status=None, skip=0, limit=50, _admin=admin, db=db
        )

    assert result.total == 2
    assert len(result.disputes) == 2


# 40. POST /corporate/disputes/{id}/review — 403 non-admin
@pytest.mark.asyncio
async def test_api_mark_under_review_403_non_admin():
    from app.api.deps import require_admin
    from app.models.user import User

    non_admin = MagicMock(spec=User)
    non_admin.role = MagicMock()
    non_admin.role.value = "member"

    with pytest.raises(HTTPException) as exc_info:
        await require_admin(non_admin)

    assert exc_info.value.status_code == 403
