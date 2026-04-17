"""Tests for corporate invoice due date and overdue tracking.

Covers:
  - Pydantic schemas (SetInvoiceDueDateRequest, OverdueInvoiceRow,
    OverdueInvoicesResponse, InvoiceOverdueScanResponse)
  - Service: set_invoice_due_date (mocked DB)
  - Service: get_overdue_invoices (mocked DB)
  - Service: run_overdue_scan (mocked DB)
  - API endpoints:
      PUT  /corporate/accounts/me/invoices/{invoice_id}/due-date
      GET  /corporate/accounts/me/invoices/overdue
      GET  /admin/corporate/invoices/overdue
      POST /admin/corporate/invoices/overdue-scan

No live database is used.  All DB interactions are mocked with AsyncMock /
MagicMock following the same pattern as test_background_check_expiry.py.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.corporate_invoice import InvoiceStatus
from app.schemas.corporate_invoice_due_date import (
    InvoiceOverdueScanResponse,
    OverdueInvoiceRow,
    OverdueInvoicesResponse,
    SetInvoiceDueDateRequest,
)

TODAY = date(2026, 4, 17)


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


def _make_invoice(
    invoice_id: int = 1,
    account_id: int = 10,
    invoice_number: str = "INV-0010-202604",
    status: InvoiceStatus = InvoiceStatus.FINALIZED,
    due_date: date | None = None,
    payment_terms_days: int | None = None,
    subtotal_usd: Decimal = Decimal("500.00"),
    notes: str | None = None,
) -> MagicMock:
    inv = MagicMock()
    inv.id = invoice_id
    inv.account_id = account_id
    inv.invoice_number = invoice_number
    inv.status = status
    inv.due_date = due_date
    inv.payment_terms_days = payment_terms_days
    inv.subtotal_usd = subtotal_usd
    inv.notes = notes
    return inv


def _make_membership(account_id: int = 10) -> MagicMock:
    m = MagicMock()
    m.account_id = account_id
    m.is_active = True
    return m


def _make_user(user_id: int = 1) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


def _db_with_scalar_one_or_none(*values):
    """Build a DB mock that returns values from scalar_one_or_none() in sequence."""
    db = AsyncMock()
    results = []
    for v in values:
        r = MagicMock()
        r.scalar_one_or_none.return_value = v
        results.append(r)
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _db_with_scalars(*lists_of_rows):
    """Build an AsyncSession mock for sequential scalars().all() calls."""
    db = AsyncMock()
    results = []
    for row_list in lists_of_rows:
        result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = row_list
        scalars_mock.__iter__ = lambda self, rl=row_list: iter(rl)
        result.scalars.return_value = scalars_mock
        results.append(result)
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ===========================================================================
# Schema tests
# ===========================================================================


class TestSetInvoiceDueDateRequestSchema:
    """Pydantic validation for SetInvoiceDueDateRequest."""

    def test_all_none_is_valid(self):
        req = SetInvoiceDueDateRequest()
        assert req.due_date is None
        assert req.payment_terms_days is None

    def test_valid_due_date(self):
        req = SetInvoiceDueDateRequest(due_date=TODAY + timedelta(days=30))
        assert req.due_date == TODAY + timedelta(days=30)

    def test_valid_payment_terms_days(self):
        req = SetInvoiceDueDateRequest(payment_terms_days=30)
        assert req.payment_terms_days == 30

    def test_payment_terms_days_min_boundary(self):
        req = SetInvoiceDueDateRequest(payment_terms_days=1)
        assert req.payment_terms_days == 1

    def test_payment_terms_days_max_boundary(self):
        req = SetInvoiceDueDateRequest(payment_terms_days=365)
        assert req.payment_terms_days == 365

    def test_payment_terms_days_zero_rejected(self):
        with pytest.raises(Exception):
            SetInvoiceDueDateRequest(payment_terms_days=0)

    def test_payment_terms_days_negative_rejected(self):
        with pytest.raises(Exception):
            SetInvoiceDueDateRequest(payment_terms_days=-1)

    def test_payment_terms_days_over_365_rejected(self):
        with pytest.raises(Exception):
            SetInvoiceDueDateRequest(payment_terms_days=366)

    def test_both_fields_set(self):
        req = SetInvoiceDueDateRequest(
            due_date=TODAY + timedelta(days=45),
            payment_terms_days=45,
        )
        assert req.due_date == TODAY + timedelta(days=45)
        assert req.payment_terms_days == 45


class TestOverdueInvoiceRowSchema:
    """Pydantic validation for OverdueInvoiceRow."""

    def test_basic_construction(self):
        row = OverdueInvoiceRow(
            invoice_id=1,
            account_id=10,
            invoice_number="INV-0010-202604",
            due_date=TODAY - timedelta(days=5),
            days_overdue=5,
            subtotal_usd=Decimal("250.00"),
            status=InvoiceStatus.FINALIZED,
        )
        assert row.invoice_id == 1
        assert row.days_overdue == 5

    def test_from_attributes_config(self):
        assert OverdueInvoiceRow.model_config.get("from_attributes") is True

    def test_status_field_accepts_enum(self):
        row = OverdueInvoiceRow(
            invoice_id=2,
            account_id=10,
            invoice_number="INV-0010-202603",
            due_date=TODAY - timedelta(days=1),
            days_overdue=1,
            subtotal_usd=Decimal("100.00"),
            status=InvoiceStatus.FINALIZED,
        )
        assert row.status == InvoiceStatus.FINALIZED

    def test_due_date_is_date_type(self):
        row = OverdueInvoiceRow(
            invoice_id=3,
            account_id=10,
            invoice_number="INV-0010-202602",
            due_date=TODAY - timedelta(days=10),
            days_overdue=10,
            subtotal_usd=Decimal("75.00"),
            status=InvoiceStatus.FINALIZED,
        )
        assert isinstance(row.due_date, date)


class TestOverdueInvoicesResponseSchema:
    """Pydantic validation for OverdueInvoicesResponse."""

    def test_empty_response(self):
        resp = OverdueInvoicesResponse(invoices=[], total=0)
        assert resp.invoices == []
        assert resp.total == 0

    def test_response_with_items(self):
        row = OverdueInvoiceRow(
            invoice_id=1,
            account_id=10,
            invoice_number="INV-0010-202604",
            due_date=TODAY - timedelta(days=3),
            days_overdue=3,
            subtotal_usd=Decimal("500.00"),
            status=InvoiceStatus.FINALIZED,
        )
        resp = OverdueInvoicesResponse(invoices=[row], total=1)
        assert resp.total == 1
        assert len(resp.invoices) == 1


class TestInvoiceOverdueScanResponseSchema:
    """Pydantic validation for InvoiceOverdueScanResponse."""

    def test_basic_construction(self):
        resp = InvoiceOverdueScanResponse(
            scanned=10,
            overdue_count=3,
            newly_flagged=2,
            as_of=TODAY,
        )
        assert resp.scanned == 10
        assert resp.overdue_count == 3
        assert resp.newly_flagged == 2
        assert resp.as_of == TODAY

    def test_zero_counts(self):
        resp = InvoiceOverdueScanResponse(
            scanned=0,
            overdue_count=0,
            newly_flagged=0,
            as_of=TODAY,
        )
        assert resp.scanned == 0


# ===========================================================================
# Service: set_invoice_due_date
# ===========================================================================


class TestSetInvoiceDueDate:
    """Tests for set_invoice_due_date with mocked DB."""

    @pytest.mark.asyncio
    async def test_success_sets_due_date(self):
        from app.services.corporate_invoice_due_date import set_invoice_due_date

        invoice = _make_invoice(status=InvoiceStatus.FINALIZED)
        db = _db_with_scalar_one_or_none(invoice)
        db.refresh = AsyncMock(return_value=None)

        req = SetInvoiceDueDateRequest(due_date=TODAY + timedelta(days=30))
        result = await set_invoice_due_date(db, invoice_id=1, account_id=10, req=req)

        assert invoice.due_date == TODAY + timedelta(days=30)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_success_sets_payment_terms_days(self):
        from app.services.corporate_invoice_due_date import set_invoice_due_date

        invoice = _make_invoice(status=InvoiceStatus.DRAFT)
        db = _db_with_scalar_one_or_none(invoice)
        db.refresh = AsyncMock(return_value=None)

        req = SetInvoiceDueDateRequest(payment_terms_days=30)
        await set_invoice_due_date(db, invoice_id=1, account_id=10, req=req)

        assert invoice.payment_terms_days == 30

    @pytest.mark.asyncio
    async def test_invoice_not_found_raises_404(self):
        from app.services.corporate_invoice_due_date import set_invoice_due_date
        from fastapi import HTTPException

        db = _db_with_scalar_one_or_none(None)
        req = SetInvoiceDueDateRequest(due_date=TODAY + timedelta(days=30))

        with pytest.raises(HTTPException) as exc_info:
            await set_invoice_due_date(db, invoice_id=99, account_id=10, req=req)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_paid_invoice_raises_400(self):
        from app.services.corporate_invoice_due_date import set_invoice_due_date
        from fastapi import HTTPException

        invoice = _make_invoice(status=InvoiceStatus.PAID)
        db = _db_with_scalar_one_or_none(invoice)
        req = SetInvoiceDueDateRequest(due_date=TODAY + timedelta(days=30))

        with pytest.raises(HTTPException) as exc_info:
            await set_invoice_due_date(db, invoice_id=1, account_id=10, req=req)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_void_invoice_raises_400(self):
        from app.services.corporate_invoice_due_date import set_invoice_due_date
        from fastapi import HTTPException

        invoice = _make_invoice(status=InvoiceStatus.VOID)
        db = _db_with_scalar_one_or_none(invoice)
        req = SetInvoiceDueDateRequest(due_date=TODAY + timedelta(days=30))

        with pytest.raises(HTTPException) as exc_info:
            await set_invoice_due_date(db, invoice_id=1, account_id=10, req=req)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_account_mismatch_raises_404(self):
        """invoice.account_id != account_id passed in — DB query returns None."""
        from app.services.corporate_invoice_due_date import set_invoice_due_date
        from fastapi import HTTPException

        # DB returns None because the WHERE clause filters by account_id
        db = _db_with_scalar_one_or_none(None)
        req = SetInvoiceDueDateRequest(due_date=TODAY + timedelta(days=30))

        with pytest.raises(HTTPException) as exc_info:
            await set_invoice_due_date(db, invoice_id=1, account_id=999, req=req)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_clears_due_date_when_none(self):
        from app.services.corporate_invoice_due_date import set_invoice_due_date

        invoice = _make_invoice(
            status=InvoiceStatus.FINALIZED, due_date=TODAY + timedelta(days=10)
        )
        db = _db_with_scalar_one_or_none(invoice)
        db.refresh = AsyncMock(return_value=None)

        req = SetInvoiceDueDateRequest(due_date=None, payment_terms_days=None)
        await set_invoice_due_date(db, invoice_id=1, account_id=10, req=req)

        assert invoice.due_date is None
        assert invoice.payment_terms_days is None


# ===========================================================================
# Service: get_overdue_invoices
# ===========================================================================


class TestGetOverdueInvoices:
    """Tests for get_overdue_invoices with mocked DB."""

    @pytest.mark.asyncio
    async def test_no_overdue_invoices_returns_empty(self):
        from app.services.corporate_invoice_due_date import get_overdue_invoices

        db = _db_with_scalars([])
        with patch("app.services.corporate_invoice_due_date.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_overdue_invoices(db)
        assert rows == []

    @pytest.mark.asyncio
    async def test_one_overdue_invoice_returned(self):
        from app.services.corporate_invoice_due_date import get_overdue_invoices

        inv = _make_invoice(due_date=TODAY - timedelta(days=5))
        db = _db_with_scalars([inv])
        with patch("app.services.corporate_invoice_due_date.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_overdue_invoices(db)

        assert len(rows) == 1
        assert rows[0].invoice_id == inv.id
        assert rows[0].days_overdue == 5

    @pytest.mark.asyncio
    async def test_days_overdue_computed_correctly(self):
        from app.services.corporate_invoice_due_date import get_overdue_invoices

        inv = _make_invoice(due_date=TODAY - timedelta(days=14))
        db = _db_with_scalars([inv])
        with patch("app.services.corporate_invoice_due_date.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_overdue_invoices(db)

        assert rows[0].days_overdue == 14

    @pytest.mark.asyncio
    async def test_multiple_overdue_invoices(self):
        from app.services.corporate_invoice_due_date import get_overdue_invoices

        invoices = [
            _make_invoice(invoice_id=i, due_date=TODAY - timedelta(days=i))
            for i in range(1, 4)
        ]
        db = _db_with_scalars(invoices)
        with patch("app.services.corporate_invoice_due_date.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_overdue_invoices(db)

        assert len(rows) == 3

    @pytest.mark.asyncio
    async def test_account_filter_passed_to_query(self):
        """Verify the function runs when account_id filter is provided."""
        from app.services.corporate_invoice_due_date import get_overdue_invoices

        inv = _make_invoice(account_id=42, due_date=TODAY - timedelta(days=2))
        db = _db_with_scalars([inv])
        with patch("app.services.corporate_invoice_due_date.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_overdue_invoices(db, account_id=42)

        assert len(rows) == 1
        assert rows[0].account_id == 42

    @pytest.mark.asyncio
    async def test_as_of_date_overrides_today(self):
        from app.services.corporate_invoice_due_date import get_overdue_invoices

        past_due_date = date(2026, 3, 1)
        inv = _make_invoice(due_date=past_due_date)
        db = _db_with_scalars([inv])
        custom_as_of = date(2026, 4, 1)
        rows = await get_overdue_invoices(db, as_of=custom_as_of)

        assert len(rows) == 1
        assert rows[0].days_overdue == (custom_as_of - past_due_date).days

    @pytest.mark.asyncio
    async def test_subtotal_and_status_in_row(self):
        from app.services.corporate_invoice_due_date import get_overdue_invoices

        inv = _make_invoice(
            due_date=TODAY - timedelta(days=1),
            subtotal_usd=Decimal("1234.56"),
            status=InvoiceStatus.FINALIZED,
        )
        db = _db_with_scalars([inv])
        with patch("app.services.corporate_invoice_due_date.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_overdue_invoices(db)

        assert rows[0].subtotal_usd == Decimal("1234.56")
        assert rows[0].status == InvoiceStatus.FINALIZED


# ===========================================================================
# Service: run_overdue_scan
# ===========================================================================


class TestRunOverdueScan:
    """Tests for run_overdue_scan with mocked DB."""

    @pytest.mark.asyncio
    async def test_empty_returns_zero_counts(self):
        from app.services.corporate_invoice_due_date import run_overdue_scan

        db = _db_with_scalars([])
        result = await run_overdue_scan(db, as_of=TODAY)

        assert result.scanned == 0
        assert result.overdue_count == 0
        assert result.newly_flagged == 0
        assert result.as_of == TODAY

    @pytest.mark.asyncio
    async def test_one_overdue_invoice_flagged(self):
        from app.services.corporate_invoice_due_date import run_overdue_scan

        inv = _make_invoice(due_date=TODAY - timedelta(days=3), notes=None)
        db = _db_with_scalars([inv])
        result = await run_overdue_scan(db, as_of=TODAY)

        assert result.scanned == 1
        assert result.overdue_count == 1
        assert result.newly_flagged == 1

    @pytest.mark.asyncio
    async def test_already_flagged_not_double_counted(self):
        from app.services.corporate_invoice_due_date import run_overdue_scan

        inv = _make_invoice(
            due_date=TODAY - timedelta(days=3), notes="Previous note [OVERDUE]"
        )
        db = _db_with_scalars([inv])
        result = await run_overdue_scan(db, as_of=TODAY)

        assert result.overdue_count == 1
        assert result.newly_flagged == 0

    @pytest.mark.asyncio
    async def test_not_overdue_invoice_not_flagged(self):
        from app.services.corporate_invoice_due_date import run_overdue_scan

        inv = _make_invoice(due_date=TODAY + timedelta(days=5), notes=None)
        db = _db_with_scalars([inv])
        result = await run_overdue_scan(db, as_of=TODAY)

        assert result.scanned == 1
        assert result.overdue_count == 0
        assert result.newly_flagged == 0

    @pytest.mark.asyncio
    async def test_commit_called(self):
        from app.services.corporate_invoice_due_date import run_overdue_scan

        db = _db_with_scalars([])
        await run_overdue_scan(db, as_of=TODAY)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mixed_overdue_and_current(self):
        from app.services.corporate_invoice_due_date import run_overdue_scan

        overdue1 = _make_invoice(invoice_id=1, due_date=TODAY - timedelta(days=5))
        overdue2 = _make_invoice(invoice_id=2, due_date=TODAY - timedelta(days=1))
        not_due = _make_invoice(invoice_id=3, due_date=TODAY + timedelta(days=10))
        db = _db_with_scalars([overdue1, overdue2, not_due])
        result = await run_overdue_scan(db, as_of=TODAY)

        assert result.scanned == 3
        assert result.overdue_count == 2
        assert result.newly_flagged == 2

    @pytest.mark.asyncio
    async def test_notes_appended_correctly(self):
        from app.services.corporate_invoice_due_date import run_overdue_scan

        inv = _make_invoice(
            due_date=TODAY - timedelta(days=3), notes="Pay promptly."
        )
        db = _db_with_scalars([inv])
        await run_overdue_scan(db, as_of=TODAY)

        assert "[OVERDUE]" in inv.notes
        assert "Pay promptly." in inv.notes

    @pytest.mark.asyncio
    async def test_overdue_marker_added_when_no_notes(self):
        from app.services.corporate_invoice_due_date import run_overdue_scan

        inv = _make_invoice(due_date=TODAY - timedelta(days=2), notes=None)
        db = _db_with_scalars([inv])
        await run_overdue_scan(db, as_of=TODAY)

        assert inv.notes == "[OVERDUE]"

    @pytest.mark.asyncio
    async def test_uses_today_when_as_of_not_provided(self):
        from app.services.corporate_invoice_due_date import run_overdue_scan

        db = _db_with_scalars([])
        with patch("app.services.corporate_invoice_due_date.date") as mock_date:
            mock_date.today.return_value = TODAY
            result = await run_overdue_scan(db)
        assert result.as_of == TODAY


# ===========================================================================
# API endpoint tests
# ===========================================================================


class TestSetDueDateEndpoint:
    """Tests for PUT /corporate/accounts/me/invoices/{invoice_id}/due-date."""

    @pytest.mark.asyncio
    async def test_200_success(self):
        from app.api.v1.corporate_invoice_due_date import set_my_invoice_due_date

        user = _make_user()
        db = AsyncMock()
        invoice = _make_invoice()

        with patch(
            "app.api.v1.corporate_invoice_due_date._get_member_account_id",
            new_callable=AsyncMock,
            return_value=10,
        ), patch(
            "app.api.v1.corporate_invoice_due_date.set_invoice_due_date",
            new_callable=AsyncMock,
            return_value=invoice,
        ) as mock_svc:
            req = SetInvoiceDueDateRequest(due_date=TODAY + timedelta(days=30))
            result = await set_my_invoice_due_date(
                invoice_id=1, data=req, db=db, current_user=user
            )
            mock_svc.assert_awaited_once_with(db, 1, 10, req)

        assert result.id == invoice.id

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        from app.api.v1.corporate_invoice_due_date import set_my_invoice_due_date
        from fastapi import HTTPException

        user = _make_user()
        db = AsyncMock()

        with patch(
            "app.api.v1.corporate_invoice_due_date._get_member_account_id",
            new_callable=AsyncMock,
            return_value=10,
        ), patch(
            "app.api.v1.corporate_invoice_due_date.set_invoice_due_date",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Invoice not found."),
        ):
            req = SetInvoiceDueDateRequest(due_date=TODAY + timedelta(days=30))
            with pytest.raises(HTTPException) as exc_info:
                await set_my_invoice_due_date(
                    invoice_id=99, data=req, db=db, current_user=user
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_403_wrong_account(self):
        """User is not a member of any account."""
        from app.api.v1.corporate_invoice_due_date import set_my_invoice_due_date
        from fastapi import HTTPException

        user = _make_user()
        db = AsyncMock()

        with patch(
            "app.api.v1.corporate_invoice_due_date._get_member_account_id",
            new_callable=AsyncMock,
            side_effect=HTTPException(
                status_code=404, detail="You are not a member of any corporate account."
            ),
        ):
            req = SetInvoiceDueDateRequest(due_date=TODAY + timedelta(days=30))
            with pytest.raises(HTTPException) as exc_info:
                await set_my_invoice_due_date(
                    invoice_id=1, data=req, db=db, current_user=user
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_422_invalid_data_rejected_by_schema(self):
        """payment_terms_days = 0 is rejected at schema level."""
        with pytest.raises(Exception):
            SetInvoiceDueDateRequest(payment_terms_days=0)

    @pytest.mark.asyncio
    async def test_400_paid_invoice(self):
        from app.api.v1.corporate_invoice_due_date import set_my_invoice_due_date
        from fastapi import HTTPException

        user = _make_user()
        db = AsyncMock()

        with patch(
            "app.api.v1.corporate_invoice_due_date._get_member_account_id",
            new_callable=AsyncMock,
            return_value=10,
        ), patch(
            "app.api.v1.corporate_invoice_due_date.set_invoice_due_date",
            new_callable=AsyncMock,
            side_effect=HTTPException(
                status_code=400, detail="Cannot set due date on a PAID or VOID invoice."
            ),
        ):
            req = SetInvoiceDueDateRequest(due_date=TODAY + timedelta(days=30))
            with pytest.raises(HTTPException) as exc_info:
                await set_my_invoice_due_date(
                    invoice_id=1, data=req, db=db, current_user=user
                )
        assert exc_info.value.status_code == 400


class TestMemberOverdueEndpoint:
    """Tests for GET /corporate/accounts/me/invoices/overdue."""

    @pytest.mark.asyncio
    async def test_returns_overdue_list(self):
        from app.api.v1.corporate_invoice_due_date import list_my_overdue_invoices

        user = _make_user()
        db = AsyncMock()
        mock_rows = [
            OverdueInvoiceRow(
                invoice_id=1,
                account_id=10,
                invoice_number="INV-0010-202604",
                due_date=TODAY - timedelta(days=3),
                days_overdue=3,
                subtotal_usd=Decimal("500.00"),
                status=InvoiceStatus.FINALIZED,
            )
        ]

        with patch(
            "app.api.v1.corporate_invoice_due_date._get_member_account_id",
            new_callable=AsyncMock,
            return_value=10,
        ), patch(
            "app.api.v1.corporate_invoice_due_date.get_overdue_invoices",
            new_callable=AsyncMock,
            return_value=mock_rows,
        ) as mock_svc:
            result = await list_my_overdue_invoices(
                as_of=None, db=db, current_user=user
            )
            mock_svc.assert_awaited_once_with(db, account_id=10, as_of=None)

        assert result.total == 1
        assert len(result.invoices) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_none_overdue(self):
        from app.api.v1.corporate_invoice_due_date import list_my_overdue_invoices

        user = _make_user()
        db = AsyncMock()

        with patch(
            "app.api.v1.corporate_invoice_due_date._get_member_account_id",
            new_callable=AsyncMock,
            return_value=10,
        ), patch(
            "app.api.v1.corporate_invoice_due_date.get_overdue_invoices",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await list_my_overdue_invoices(
                as_of=None, db=db, current_user=user
            )

        assert result.total == 0
        assert result.invoices == []

    @pytest.mark.asyncio
    async def test_as_of_forwarded_to_service(self):
        from app.api.v1.corporate_invoice_due_date import list_my_overdue_invoices

        user = _make_user()
        db = AsyncMock()
        custom_date = date(2026, 3, 15)

        with patch(
            "app.api.v1.corporate_invoice_due_date._get_member_account_id",
            new_callable=AsyncMock,
            return_value=10,
        ), patch(
            "app.api.v1.corporate_invoice_due_date.get_overdue_invoices",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_svc:
            await list_my_overdue_invoices(
                as_of=custom_date, db=db, current_user=user
            )
            mock_svc.assert_awaited_once_with(db, account_id=10, as_of=custom_date)


class TestAdminOverdueEndpoint:
    """Tests for GET /admin/corporate/invoices/overdue."""

    @pytest.mark.asyncio
    async def test_returns_all_overdue_invoices(self):
        from app.api.v1.corporate_invoice_due_date import admin_list_overdue_invoices

        db = AsyncMock()
        mock_rows = [
            OverdueInvoiceRow(
                invoice_id=i,
                account_id=i * 10,
                invoice_number=f"INV-{i:04d}-202604",
                due_date=TODAY - timedelta(days=i),
                days_overdue=i,
                subtotal_usd=Decimal("100.00"),
                status=InvoiceStatus.FINALIZED,
            )
            for i in range(1, 4)
        ]

        with patch(
            "app.api.v1.corporate_invoice_due_date.get_overdue_invoices",
            new_callable=AsyncMock,
            return_value=mock_rows,
        ) as mock_svc:
            result = await admin_list_overdue_invoices(
                account_id=None, as_of=None, db=db
            )
            mock_svc.assert_awaited_once_with(db, account_id=None, as_of=None)

        assert result.total == 3

    @pytest.mark.asyncio
    async def test_account_id_filter_forwarded(self):
        from app.api.v1.corporate_invoice_due_date import admin_list_overdue_invoices

        db = AsyncMock()

        with patch(
            "app.api.v1.corporate_invoice_due_date.get_overdue_invoices",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_svc:
            await admin_list_overdue_invoices(account_id=42, as_of=None, db=db)
            mock_svc.assert_awaited_once_with(db, account_id=42, as_of=None)

    @pytest.mark.asyncio
    async def test_empty_result(self):
        from app.api.v1.corporate_invoice_due_date import admin_list_overdue_invoices

        db = AsyncMock()

        with patch(
            "app.api.v1.corporate_invoice_due_date.get_overdue_invoices",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await admin_list_overdue_invoices(
                account_id=None, as_of=None, db=db
            )

        assert result.total == 0
        assert result.invoices == []


class TestAdminOverdueScanEndpoint:
    """Tests for POST /admin/corporate/invoices/overdue-scan."""

    @pytest.mark.asyncio
    async def test_returns_scan_result(self):
        from app.api.v1.corporate_invoice_due_date import admin_overdue_scan

        db = AsyncMock()
        mock_result = InvoiceOverdueScanResponse(
            scanned=20,
            overdue_count=5,
            newly_flagged=3,
            as_of=TODAY,
        )

        with patch(
            "app.api.v1.corporate_invoice_due_date.run_overdue_scan",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_svc:
            result = await admin_overdue_scan(as_of=None, db=db)
            mock_svc.assert_awaited_once_with(db, as_of=None)

        assert result.scanned == 20
        assert result.overdue_count == 5
        assert result.newly_flagged == 3

    @pytest.mark.asyncio
    async def test_zero_results(self):
        from app.api.v1.corporate_invoice_due_date import admin_overdue_scan

        db = AsyncMock()
        mock_result = InvoiceOverdueScanResponse(
            scanned=0, overdue_count=0, newly_flagged=0, as_of=TODAY
        )

        with patch(
            "app.api.v1.corporate_invoice_due_date.run_overdue_scan",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await admin_overdue_scan(as_of=None, db=db)

        assert result.scanned == 0

    @pytest.mark.asyncio
    async def test_as_of_forwarded_to_service(self):
        from app.api.v1.corporate_invoice_due_date import admin_overdue_scan

        db = AsyncMock()
        custom_date = date(2026, 3, 1)
        mock_result = InvoiceOverdueScanResponse(
            scanned=5, overdue_count=2, newly_flagged=1, as_of=custom_date
        )

        with patch(
            "app.api.v1.corporate_invoice_due_date.run_overdue_scan",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_svc:
            await admin_overdue_scan(as_of=custom_date, db=db)
            mock_svc.assert_awaited_once_with(db, as_of=custom_date)

    @pytest.mark.asyncio
    async def test_service_called_with_db(self):
        from app.api.v1.corporate_invoice_due_date import admin_overdue_scan

        db = AsyncMock()
        mock_result = InvoiceOverdueScanResponse(
            scanned=0, overdue_count=0, newly_flagged=0, as_of=TODAY
        )

        with patch(
            "app.api.v1.corporate_invoice_due_date.run_overdue_scan",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_svc:
            await admin_overdue_scan(as_of=None, db=db)

        mock_svc.assert_awaited_once_with(db, as_of=None)
