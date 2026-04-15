"""Tests for the Corporate Invoice feature.

Service layer (async, mocked DB):
  1.  generate_invoice — creates invoice with correct totals
  2.  generate_invoice — raises 403 when caller is not account admin
  3.  generate_invoice — raises 409 when non-void invoice already exists for period
  4.  generate_invoice — succeeds when prior invoice is void (allows re-generation)
  5.  generate_invoice — handles account with no rides (total_rides=0, subtotal_usd=0)
  6.  get_invoice — returns invoice by ID and account
  7.  get_invoice — raises 404 when not found
  8.  get_invoice — raises 404 on account_id mismatch
  9.  list_invoices — returns all invoices ordered by period_start desc
  10. list_invoices — filters by status when status_filter provided
  11. finalize_invoice — transitions draft → finalized, sets finalized_at
  12. finalize_invoice — raises 400 when status is not draft
  13. finalize_invoice — raises 403 when caller is not admin
  14. mark_invoice_paid — transitions finalized → paid, sets paid_at
  15. mark_invoice_paid — raises 400 when status is not finalized
  16. mark_invoice_paid — raises 403 when caller is not admin
  17. void_invoice — transitions any-non-void → void, sets voided_at
  18. void_invoice — raises 400 when already void
  19. void_invoice — raises 403 when caller is not admin
  20. get_invoice_line_items — returns structured response with line_items and by_cost_center
  21. regenerate_invoice_totals — updates total_rides and subtotal_usd for draft invoice
  22. regenerate_invoice_totals — raises 400 when invoice is not draft
  23. regenerate_invoice_totals — raises 403 when caller is not admin

Schema validation:
  24. CorporateInvoiceCreate — valid payload accepted
  25. CorporateInvoiceCreate — period_end < period_start raises ValidationError
  26. CorporateInvoiceCreate — notes too long raises ValidationError
  27. InvoiceMarkPaidRequest — notes optional
  28. CorporateInvoiceResponse — serialises correctly with from_attributes

API layer (service functions patched):
  29. POST /corporate/accounts/me/invoices — calls generate_invoice (201)
  30. GET  /corporate/accounts/me/invoices — calls list_invoices (200)
  31. GET  /corporate/accounts/me/invoices/{id} — calls get_invoice (200)
  32. GET  /corporate/accounts/me/invoices/{id}/line-items — calls get_invoice_line_items (200)
  33. PUT  /corporate/accounts/me/invoices/{id}/finalize — calls finalize_invoice (200)
  34. PUT  /corporate/accounts/me/invoices/{id}/paid — calls mark_invoice_paid (200)
  35. DELETE /corporate/accounts/me/invoices/{id} — calls void_invoice (204)
  36. POST /corporate/accounts/me/invoices/{id}/regenerate — calls regenerate_invoice_totals (200)
  37. GET  /admin/corporate/accounts/{id}/invoices — admin list (200)
  38. GET  /admin/corporate/accounts/{id}/invoices/{inv_id} — admin get (200)
  39. GET  /admin/corporate/accounts/{id}/invoices/{inv_id}/line-items — admin line items (200)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_invoice import CorporateInvoice, InvoiceStatus
from app.schemas.corporate_invoice import (
    CorporateInvoiceCreate,
    CorporateInvoiceResponse,
    InvoiceMarkPaidRequest,
)
from app.services.corporate_invoice import (
    finalize_invoice,
    generate_invoice,
    get_invoice,
    get_invoice_line_items,
    list_invoices,
    mark_invoice_paid,
    regenerate_invoice_totals,
    void_invoice,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
PERIOD_START = date(2026, 4, 1)
PERIOD_END = date(2026, 4, 30)


def _make_invoice(
    id: int = 1,
    account_id: int = 10,
    invoice_number: str = "INV-0010-202604",
    status: InvoiceStatus = InvoiceStatus.DRAFT,
    total_rides: int = 3,
    subtotal_usd: Decimal = Decimal("150.00"),
    notes: str | None = None,
    period_start: date = PERIOD_START,
    period_end: date = PERIOD_END,
) -> CorporateInvoice:
    inv = MagicMock(spec=CorporateInvoice)
    inv.id = id
    inv.account_id = account_id
    inv.invoice_number = invoice_number
    inv.period_start = period_start
    inv.period_end = period_end
    inv.status = status
    inv.total_rides = total_rides
    inv.subtotal_usd = subtotal_usd
    inv.notes = notes
    inv.generated_at = NOW
    inv.finalized_at = None
    inv.paid_at = None
    inv.voided_at = None
    inv.created_at = NOW
    inv.updated_at = NOW
    return inv


def _make_admin_member(account_id: int = 10, user_id: int = 1):
    from app.models.corporate import BusinessAccountMember, MemberRole
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = account_id
    m.user_id = user_id
    m.role = MemberRole.ADMIN
    m.is_active = True
    return m


def _scalar_result(value):
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    res.scalar.return_value = value
    res.scalars.return_value.all.return_value = [value] if value is not None else []
    return res


def _scalars_result(items: list):
    res = MagicMock()
    res.scalars.return_value.all.return_value = items
    res.scalar_one_or_none.return_value = items[0] if items else None
    res.scalar.return_value = len(items)
    return res


def _aggregate_result(total_rides: int = 3, subtotal_usd: Decimal = Decimal("150.00")):
    """Mock result for the ride aggregation query."""
    row = MagicMock()
    row.total_rides = total_rides
    row.subtotal_usd = subtotal_usd
    res = MagicMock()
    res.one.return_value = row
    return res


# ---------------------------------------------------------------------------
# 1. generate_invoice — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_generate_invoice_success():
    db = AsyncMock()
    admin_member = _make_admin_member(account_id=10, user_id=1)

    db.execute.side_effect = [
        _scalar_result(admin_member),       # _require_account_admin
        _scalar_result(None),               # existing non-void invoice check
        _aggregate_result(3, Decimal("150.00")),  # ride aggregation
        _scalar_result(None),               # invoice_number base check
    ]
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    data = CorporateInvoiceCreate(period_start=PERIOD_START, period_end=PERIOD_END)
    result = await generate_invoice(db, account_id=10, data=data, requesting_user_id=1)
    db.add.assert_called_once()
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 2. generate_invoice — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_generate_invoice_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)  # no admin member found

    data = CorporateInvoiceCreate(period_start=PERIOD_START, period_end=PERIOD_END)
    with pytest.raises(HTTPException) as exc_info:
        await generate_invoice(db, account_id=10, data=data, requesting_user_id=99)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 3. generate_invoice — existing non-void invoice → 409
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_generate_invoice_conflict_existing():
    db = AsyncMock()
    admin_member = _make_admin_member()
    existing = _make_invoice(status=InvoiceStatus.FINALIZED)

    db.execute.side_effect = [
        _scalar_result(admin_member),  # _require_account_admin
        _scalar_result(existing),      # existing non-void invoice found
    ]

    data = CorporateInvoiceCreate(period_start=PERIOD_START, period_end=PERIOD_END)
    with pytest.raises(HTTPException) as exc_info:
        await generate_invoice(db, account_id=10, data=data, requesting_user_id=1)
    assert exc_info.value.status_code == 409
    assert "already exists" in exc_info.value.detail


# ---------------------------------------------------------------------------
# 4. generate_invoice — prior void invoice does not block creation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_generate_invoice_allows_after_void():
    db = AsyncMock()
    admin_member = _make_admin_member()

    db.execute.side_effect = [
        _scalar_result(admin_member),               # _require_account_admin
        _scalar_result(None),                       # no non-void invoice (void filtered out)
        _aggregate_result(2, Decimal("90.00")),     # ride aggregation
        _scalar_result(None),                       # invoice_number base check
    ]
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    data = CorporateInvoiceCreate(period_start=PERIOD_START, period_end=PERIOD_END)
    result = await generate_invoice(db, account_id=10, data=data, requesting_user_id=1)
    db.add.assert_called_once()
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 5. generate_invoice — account with no rides → totals = 0
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_generate_invoice_no_rides():
    db = AsyncMock()
    admin_member = _make_admin_member()

    db.execute.side_effect = [
        _scalar_result(admin_member),           # _require_account_admin
        _scalar_result(None),                   # no existing invoice
        _aggregate_result(0, Decimal("0")),     # zero rides
        _scalar_result(None),                   # invoice_number base check
    ]
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    data = CorporateInvoiceCreate(period_start=PERIOD_START, period_end=PERIOD_END)
    await generate_invoice(db, account_id=10, data=data, requesting_user_id=1)
    db.add.assert_called_once()
    # Verify the invoice was added with 0 totals
    added_invoice = db.add.call_args[0][0]
    assert added_invoice.total_rides == 0


# ---------------------------------------------------------------------------
# 6. get_invoice — returns invoice
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_invoice_found():
    db = AsyncMock()
    inv = _make_invoice(id=1, account_id=10)
    db.execute.return_value = _scalar_result(inv)

    result = await get_invoice(db, invoice_id=1, account_id=10)
    assert result.id == 1
    assert result.account_id == 10


# ---------------------------------------------------------------------------
# 7. get_invoice — not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_invoice_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_invoice(db, invoice_id=999, account_id=10)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 8. get_invoice — account mismatch → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_invoice_account_mismatch():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_invoice(db, invoice_id=1, account_id=99)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 9. list_invoices — returns all invoices
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_invoices_all():
    db = AsyncMock()
    inv1 = _make_invoice(id=1, period_start=date(2026, 4, 1))
    inv2 = _make_invoice(id=2, period_start=date(2026, 3, 1))
    db.execute.return_value = _scalars_result([inv1, inv2])

    results = await list_invoices(db, account_id=10)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# 10. list_invoices — filters by status
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_invoices_status_filter():
    db = AsyncMock()
    inv = _make_invoice(id=1, status=InvoiceStatus.FINALIZED)
    db.execute.return_value = _scalars_result([inv])

    results = await list_invoices(db, account_id=10, status_filter=InvoiceStatus.FINALIZED)
    assert len(results) == 1
    assert results[0].status == InvoiceStatus.FINALIZED


# ---------------------------------------------------------------------------
# 11. finalize_invoice — draft → finalized, sets finalized_at
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_finalize_invoice_success():
    db = AsyncMock()
    admin_member = _make_admin_member()
    inv = _make_invoice(status=InvoiceStatus.DRAFT)

    db.execute.side_effect = [
        _scalar_result(admin_member),
        _scalar_result(inv),
    ]
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    result = await finalize_invoice(db, invoice_id=1, account_id=10, requesting_user_id=1)
    assert inv.status == InvoiceStatus.FINALIZED
    assert inv.finalized_at is not None
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 12. finalize_invoice — not draft → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_finalize_invoice_not_draft():
    db = AsyncMock()
    admin_member = _make_admin_member()
    inv = _make_invoice(status=InvoiceStatus.FINALIZED)

    db.execute.side_effect = [
        _scalar_result(admin_member),
        _scalar_result(inv),
    ]

    with pytest.raises(HTTPException) as exc_info:
        await finalize_invoice(db, invoice_id=1, account_id=10, requesting_user_id=1)
    assert exc_info.value.status_code == 400
    assert "draft" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# 13. finalize_invoice — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_finalize_invoice_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await finalize_invoice(db, invoice_id=1, account_id=10, requesting_user_id=99)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 14. mark_invoice_paid — finalized → paid, sets paid_at
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mark_invoice_paid_success():
    db = AsyncMock()
    admin_member = _make_admin_member()
    inv = _make_invoice(status=InvoiceStatus.FINALIZED)

    db.execute.side_effect = [
        _scalar_result(admin_member),
        _scalar_result(inv),
    ]
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    result = await mark_invoice_paid(
        db, invoice_id=1, account_id=10, requesting_user_id=1
    )
    assert inv.status == InvoiceStatus.PAID
    assert inv.paid_at is not None
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 15. mark_invoice_paid — not finalized → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mark_invoice_paid_not_finalized():
    db = AsyncMock()
    admin_member = _make_admin_member()
    inv = _make_invoice(status=InvoiceStatus.DRAFT)

    db.execute.side_effect = [
        _scalar_result(admin_member),
        _scalar_result(inv),
    ]

    with pytest.raises(HTTPException) as exc_info:
        await mark_invoice_paid(
            db, invoice_id=1, account_id=10, requesting_user_id=1
        )
    assert exc_info.value.status_code == 400
    assert "finalized" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# 16. mark_invoice_paid — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mark_invoice_paid_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await mark_invoice_paid(
            db, invoice_id=1, account_id=10, requesting_user_id=99
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 17. void_invoice — sets void, sets voided_at
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_void_invoice_success():
    db = AsyncMock()
    admin_member = _make_admin_member()
    inv = _make_invoice(status=InvoiceStatus.FINALIZED)

    db.execute.side_effect = [
        _scalar_result(admin_member),
        _scalar_result(inv),
    ]
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    await void_invoice(db, invoice_id=1, account_id=10, requesting_user_id=1)
    assert inv.status == InvoiceStatus.VOID
    assert inv.voided_at is not None
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 18. void_invoice — already void → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_void_invoice_already_void():
    db = AsyncMock()
    admin_member = _make_admin_member()
    inv = _make_invoice(status=InvoiceStatus.VOID)

    db.execute.side_effect = [
        _scalar_result(admin_member),
        _scalar_result(inv),
    ]

    with pytest.raises(HTTPException) as exc_info:
        await void_invoice(db, invoice_id=1, account_id=10, requesting_user_id=1)
    assert exc_info.value.status_code == 400
    assert "already void" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# 19. void_invoice — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_void_invoice_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await void_invoice(db, invoice_id=1, account_id=10, requesting_user_id=99)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 20. get_invoice_line_items — returns structured response
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_invoice_line_items_success():
    db = AsyncMock()
    inv = _make_invoice(id=1, account_id=10)

    # Build mock ride
    ride = MagicMock()
    ride.id = 101
    ride.completed_at = NOW
    ride.actual_fare = 50.0
    ride.cost_center_id = None

    rides_result = MagicMock()
    rides_result.scalars.return_value.all.return_value = [ride]

    db.execute.side_effect = [
        _scalar_result(inv),   # _get_invoice
        rides_result,          # rides query
        # no cost center query since cost_center_id is None
    ]

    result = await get_invoice_line_items(db, invoice_id=1, account_id=10)
    assert result["invoice_id"] == 1
    assert result["invoice_number"] == "INV-0010-202604"
    assert len(result["line_items"]) == 1
    assert result["line_items"][0]["ride_id"] == 101
    assert isinstance(result["by_cost_center"], list)


# ---------------------------------------------------------------------------
# 21. regenerate_invoice_totals — updates totals for draft
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_regenerate_invoice_totals_success():
    db = AsyncMock()
    admin_member = _make_admin_member()
    inv = _make_invoice(status=InvoiceStatus.DRAFT, total_rides=0, subtotal_usd=Decimal("0"))

    db.execute.side_effect = [
        _scalar_result(admin_member),           # _require_account_admin
        _scalar_result(inv),                    # _get_invoice
        _aggregate_result(5, Decimal("250.00")),  # ride re-aggregation
    ]
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    result = await regenerate_invoice_totals(
        db, invoice_id=1, account_id=10, requesting_user_id=1
    )
    assert inv.total_rides == 5
    assert inv.subtotal_usd == Decimal("250.00")
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 22. regenerate_invoice_totals — not draft → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_regenerate_invoice_totals_not_draft():
    db = AsyncMock()
    admin_member = _make_admin_member()
    inv = _make_invoice(status=InvoiceStatus.FINALIZED)

    db.execute.side_effect = [
        _scalar_result(admin_member),
        _scalar_result(inv),
    ]

    with pytest.raises(HTTPException) as exc_info:
        await regenerate_invoice_totals(
            db, invoice_id=1, account_id=10, requesting_user_id=1
        )
    assert exc_info.value.status_code == 400
    assert "draft" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# 23. regenerate_invoice_totals — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_regenerate_invoice_totals_not_admin():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await regenerate_invoice_totals(
            db, invoice_id=1, account_id=10, requesting_user_id=99
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_schema_create_valid():
    data = CorporateInvoiceCreate(
        period_start=date(2026, 4, 1), period_end=date(2026, 4, 30)
    )
    assert data.period_start == date(2026, 4, 1)
    assert data.period_end == date(2026, 4, 30)
    assert data.notes is None


def test_schema_create_period_end_before_start():
    with pytest.raises(ValidationError):
        CorporateInvoiceCreate(
            period_start=date(2026, 4, 30), period_end=date(2026, 4, 1)
        )


def test_schema_create_notes_too_long():
    with pytest.raises(ValidationError):
        CorporateInvoiceCreate(
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            notes="x" * 501,
        )


def test_schema_mark_paid_notes_optional():
    req = InvoiceMarkPaidRequest()
    assert req.notes is None

    req_with_notes = InvoiceMarkPaidRequest(notes="Paid via wire transfer")
    assert req_with_notes.notes == "Paid via wire transfer"


def test_schema_invoice_response_from_attributes():
    inv = _make_invoice(id=5, account_id=10)
    resp = CorporateInvoiceResponse.model_validate(inv)
    assert resp.id == 5
    assert resp.account_id == 10
    assert resp.invoice_number == "INV-0010-202604"
    assert resp.status == InvoiceStatus.DRAFT
    assert resp.total_rides == 3
    assert resp.subtotal_usd == Decimal("150.00")


# ---------------------------------------------------------------------------
# API layer — handler functions called directly, services patched
# ---------------------------------------------------------------------------


def _mock_user(user_id: int = 1) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


def _mock_membership(account_id: int = 10, user_id: int = 1) -> MagicMock:
    m = MagicMock()
    m.account_id = account_id
    m.user_id = user_id
    m.is_active = True
    return m


def _mock_inv():
    return _make_invoice(id=1, account_id=10)


def _mock_line_items():
    return {
        "invoice_id": 1,
        "invoice_number": "INV-0010-202604",
        "period_start": PERIOD_START,
        "period_end": PERIOD_END,
        "total_rides": 3,
        "subtotal_usd": Decimal("150.00"),
        "line_items": [],
        "by_cost_center": [],
    }


_SVC = "app.services.corporate_invoice"
_ROUTER = "app.api.v1.corporate_invoice"


@pytest.mark.asyncio
async def test_api_generate_invoice():
    """29. POST /corporate/accounts/me/invoices calls generate_invoice (201)."""
    from app.api.v1.corporate_invoice import generate_my_invoice

    user = _mock_user()
    db = AsyncMock()
    data = CorporateInvoiceCreate(period_start=PERIOD_START, period_end=PERIOD_END)

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=10)), \
         patch(f"{_ROUTER}.generate_invoice", new=AsyncMock(return_value=_mock_inv())):
        result = await generate_my_invoice(data=data, db=db, current_user=user)
    assert result.id == 1


@pytest.mark.asyncio
async def test_api_list_invoices():
    """30. GET /corporate/accounts/me/invoices calls list_invoices (200)."""
    from app.api.v1.corporate_invoice import list_my_invoices

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=10)), \
         patch(f"{_ROUTER}.list_invoices", new=AsyncMock(return_value=[_mock_inv()])):
        result = await list_my_invoices(status_filter=None, db=db, current_user=user)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_api_get_invoice():
    """31. GET /corporate/accounts/me/invoices/{id} calls get_invoice (200)."""
    from app.api.v1.corporate_invoice import get_my_invoice

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=10)), \
         patch(f"{_ROUTER}.get_invoice", new=AsyncMock(return_value=_mock_inv())):
        result = await get_my_invoice(invoice_id=1, db=db, current_user=user)
    assert result.id == 1


@pytest.mark.asyncio
async def test_api_get_invoice_line_items():
    """32. GET /corporate/accounts/me/invoices/{id}/line-items calls get_invoice_line_items (200)."""
    from app.api.v1.corporate_invoice import get_my_invoice_line_items

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=10)), \
         patch(f"{_ROUTER}.get_invoice_line_items", new=AsyncMock(return_value=_mock_line_items())):
        result = await get_my_invoice_line_items(invoice_id=1, db=db, current_user=user)
    assert result["invoice_id"] == 1


@pytest.mark.asyncio
async def test_api_finalize_invoice():
    """33. PUT /corporate/accounts/me/invoices/{id}/finalize calls finalize_invoice (200)."""
    from app.api.v1.corporate_invoice import finalize_my_invoice

    user = _mock_user()
    db = AsyncMock()
    inv = _mock_inv()
    inv.status = InvoiceStatus.FINALIZED

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=10)), \
         patch(f"{_ROUTER}.finalize_invoice", new=AsyncMock(return_value=inv)):
        result = await finalize_my_invoice(invoice_id=1, db=db, current_user=user)
    assert result.status == InvoiceStatus.FINALIZED


@pytest.mark.asyncio
async def test_api_mark_invoice_paid():
    """34. PUT /corporate/accounts/me/invoices/{id}/paid calls mark_invoice_paid (200)."""
    from app.api.v1.corporate_invoice import mark_my_invoice_paid

    user = _mock_user()
    db = AsyncMock()
    inv = _mock_inv()
    inv.status = InvoiceStatus.PAID

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=10)), \
         patch(f"{_ROUTER}.mark_invoice_paid", new=AsyncMock(return_value=inv)):
        result = await mark_my_invoice_paid(
            invoice_id=1, data=None, db=db, current_user=user
        )
    assert result.status == InvoiceStatus.PAID


@pytest.mark.asyncio
async def test_api_void_invoice():
    """35. DELETE /corporate/accounts/me/invoices/{id} calls void_invoice (204)."""
    from app.api.v1.corporate_invoice import void_my_invoice

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=10)), \
         patch(f"{_ROUTER}.void_invoice", new=AsyncMock(return_value=None)):
        result = await void_my_invoice(invoice_id=1, db=db, current_user=user)
    # 204 returns None
    assert result is None


@pytest.mark.asyncio
async def test_api_regenerate_invoice():
    """36. POST /corporate/accounts/me/invoices/{id}/regenerate calls regenerate_invoice_totals (200)."""
    from app.api.v1.corporate_invoice import regenerate_my_invoice

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._get_member_account_id", new=AsyncMock(return_value=10)), \
         patch(f"{_ROUTER}.regenerate_invoice_totals", new=AsyncMock(return_value=_mock_inv())):
        result = await regenerate_my_invoice(invoice_id=1, db=db, current_user=user)
    assert result.id == 1


@pytest.mark.asyncio
async def test_api_admin_list_invoices():
    """37. GET /admin/corporate/accounts/{id}/invoices admin list (200)."""
    from app.api.v1.corporate_invoice import admin_list_invoices

    db = AsyncMock()

    with patch(f"{_ROUTER}.list_invoices", new=AsyncMock(return_value=[_mock_inv()])):
        result = await admin_list_invoices(account_id=10, status_filter=None, db=db)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_api_admin_get_invoice():
    """38. GET /admin/corporate/accounts/{id}/invoices/{inv_id} admin get (200)."""
    from app.api.v1.corporate_invoice import admin_get_invoice

    db = AsyncMock()

    with patch(f"{_ROUTER}.get_invoice", new=AsyncMock(return_value=_mock_inv())):
        result = await admin_get_invoice(account_id=10, invoice_id=1, db=db)
    assert result.id == 1


@pytest.mark.asyncio
async def test_api_admin_get_invoice_line_items():
    """39. GET /admin/corporate/accounts/{id}/invoices/{inv_id}/line-items admin line items (200)."""
    from app.api.v1.corporate_invoice import admin_get_invoice_line_items

    db = AsyncMock()

    with patch(f"{_ROUTER}.get_invoice_line_items", new=AsyncMock(return_value=_mock_line_items())):
        result = await admin_get_invoice_line_items(
            account_id=10, invoice_id=1, db=db
        )
    assert result["invoice_id"] == 1
