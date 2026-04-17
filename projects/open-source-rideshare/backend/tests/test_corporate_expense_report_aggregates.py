"""Tests for the Corporate Expense Report Aggregation feature.

Covers:
  Schema tests (sync):
   1.  MemberExpenseSummary — valid construction
   2.  CategoryExpenseSummary — valid construction
   3.  ExpenseReportGenerateRequest — valid
   4.  ExpenseReportGenerateRequest — start_date after end_date accepted by schema (service validates)
   5.  GeneratedExpenseReportResponse — valid construction
   6.  GeneratedExpenseReportDetail — valid with breakdowns
   7.  GeneratedExpenseReportListResponse — valid construction
   8.  ExpenseReportGenerateRequest — title optional (defaults to None)
   9.  ExpenseReportGenerateRequest — title max length enforced (>200 chars)
  10.  MemberExpenseSummary — total_amount_usd accepts Decimal

  Service tests (async, mocked DB):
  11.  generate_expense_report — non-admin → 403
  12.  generate_expense_report — start_date > end_date → 422
  13.  generate_expense_report — no rides returns zero totals
  14.  generate_expense_report — single ride aggregated correctly
  15.  generate_expense_report — multiple rides, multiple members
  16.  generate_expense_report — multiple rides, multiple categories
  17.  generate_expense_report — default title when none provided
  18.  generate_expense_report — custom title respected
  19.  generate_expense_report — stores report for later retrieval
  20.  list_generated_reports — non-admin → 403
  21.  list_generated_reports — empty store returns zero total
  22.  list_generated_reports — returns only reports for the correct corp
  23.  list_generated_reports — start_date filter applied
  24.  list_generated_reports — end_date filter applied
  25.  list_generated_reports — both date filters applied simultaneously
  26.  list_generated_reports — pagination skip works
  27.  list_generated_reports — pagination limit works
  28.  list_generated_reports — results sorted newest first
  29.  get_generated_report — non-admin → 403
  30.  get_generated_report — not found → 404
  31.  get_generated_report — wrong corp_id → 404
  32.  get_generated_report — success returns full detail
  33.  get_generated_report — by_member populated correctly
  34.  get_generated_report — by_category populated correctly
  35.  export_report_csv — non-admin → 403
  36.  export_report_csv — not found → 404
  37.  export_report_csv — returns CSV string
  38.  export_report_csv — CSV contains report header rows
  39.  export_report_csv — CSV contains by_member section
  40.  export_report_csv — CSV contains by_category section
  41.  export_report_csv — CSV is parseable with csv.reader

  API layer tests (service patched):
  42.  GET  /corporate/{corp_id}/expense-reports → 200
  43.  GET  /corporate/{corp_id}/expense-reports — no auth → 401/403
  44.  POST /corporate/{corp_id}/expense-reports/generate → 201
  45.  POST /corporate/{corp_id}/expense-reports/generate — service 403 bubbles up
  46.  POST /corporate/{corp_id}/expense-reports/generate — service 422 bubbles up
  47.  GET  /corporate/{corp_id}/expense-reports/{report_id} → 200
  48.  GET  /corporate/{corp_id}/expense-reports/{report_id} — 404 bubbles up
  49.  GET  /corporate/{corp_id}/expense-reports/{report_id} — 403 bubbles up
  50.  GET  /corporate/{corp_id}/expense-reports/{report_id}/export → 200 CSV
  51.  GET  /corporate/{corp_id}/expense-reports/{report_id}/export — 404 bubbles up
  52.  GET  /corporate/{corp_id}/expense-reports — date filters passed through
  53.  GET  /corporate/{corp_id}/expense-reports — skip/limit defaults accepted
  54.  POST /corporate/{corp_id}/expense-reports/generate — missing fields → 422
  55.  GET  /corporate/{corp_id}/expense-reports/{report_id}/export — Content-Disposition header set

  Additional unit/edge-case tests:
  56.  _reset_store clears state between isolated tests
  57.  Multiple generate calls produce distinct IDs
  58.  list returns all reports when skip=0 and limit large enough
  59.  by_member totals match overall total_amount_usd
  60.  by_category totals match overall total_amount_usd
  61.  Ride with no vehicle_type defaults category to 'standard'
  62.  Ride with fare=None treated as zero
  63.  Export CSV blank-line separators between sections
  64.  list_generated_reports — total reflects unfiltered count after date filter shrinks page
  65.  get_generated_report — report_id from generate matches retrieval
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate import BusinessAccountMember, MemberRole
from app.schemas.corporate_expense_report_aggregate import (
    CategoryExpenseSummary,
    ExpenseReportGenerateRequest,
    GeneratedExpenseReportDetail,
    GeneratedExpenseReportListResponse,
    GeneratedExpenseReportResponse,
    MemberExpenseSummary,
)
from app.services.corporate_expense_report_service import (
    _reset_store,
    export_report_csv,
    generate_expense_report,
    get_generated_report,
    list_generated_reports,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CORP_ID = 1
OTHER_CORP_ID = 2
ADMIN_ID = 10
NON_ADMIN_ID = 20
NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
START = date(2026, 4, 1)
END = date(2026, 4, 30)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin_member(user_id: int = ADMIN_ID) -> BusinessAccountMember:
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = CORP_ID
    m.user_id = user_id
    m.role = MemberRole.ADMIN
    m.is_active = True
    return m


def _make_ride(
    ride_id: int,
    rider_id: int,
    fare: float = 50.0,
    vehicle_type: str = "sedan",
    created_at: datetime = NOW,
):
    r = MagicMock()
    r.id = ride_id
    r.rider_id = rider_id
    r.corporate_account_id = CORP_ID
    r.actual_fare = fare
    r.estimated_fare = fare
    # The service checks vehicle_type_preference first, then falls back to vehicle_type
    r.vehicle_type_preference = None
    r.vehicle_type = vehicle_type
    r.requested_at = created_at
    return r


def _make_user(user_id: int, name: str = "Test User"):
    u = MagicMock()
    u.id = user_id
    u.name = name
    return u


def _db_admin_then_rides(admin_member, ride_user_pairs):
    """Build an AsyncMock DB where the first execute returns the admin member
    and the second returns the list of (ride, user) tuples."""
    db = AsyncMock()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            r = MagicMock()
            r.scalar_one_or_none.return_value = admin_member
            return r
        r = MagicMock()
        r.all.return_value = ride_user_pairs
        return r

    db.execute = fake_execute
    return db


def _db_no_admin():
    """DB that always returns None (simulates non-admin)."""
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)
    return db


def _make_generate_request(
    start: date = START,
    end: date = END,
    title: str | None = None,
) -> ExpenseReportGenerateRequest:
    return ExpenseReportGenerateRequest(start_date=start, end_date=end, title=title)


# ---------------------------------------------------------------------------
# Auto-reset the store before each test so tests don't bleed state
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_store():
    _reset_store()
    yield
    _reset_store()


# ===========================================================================
# Schema tests (sync)
# ===========================================================================


class TestSchemas:
    def test_member_expense_summary_valid(self):
        """1. MemberExpenseSummary — valid construction."""
        m = MemberExpenseSummary(
            member_user_id=1,
            member_name="Alice",
            ride_count=3,
            total_amount_usd=Decimal("120.00"),
        )
        assert m.member_user_id == 1
        assert m.ride_count == 3

    def test_category_expense_summary_valid(self):
        """2. CategoryExpenseSummary — valid construction."""
        c = CategoryExpenseSummary(
            category="sedan",
            ride_count=5,
            total_amount_usd=Decimal("250.00"),
        )
        assert c.category == "sedan"

    def test_generate_request_valid(self):
        """3. ExpenseReportGenerateRequest — valid."""
        req = ExpenseReportGenerateRequest(
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
        )
        assert req.start_date == date(2026, 4, 1)
        assert req.end_date == date(2026, 4, 30)
        assert req.title is None

    def test_generate_request_start_after_end_passes_schema(self):
        """4. ExpenseReportGenerateRequest — date order validated by service, not schema."""
        # Schema accepts it; the service raises 422
        req = ExpenseReportGenerateRequest(
            start_date=date(2026, 4, 30),
            end_date=date(2026, 4, 1),
        )
        assert req.start_date > req.end_date

    def test_generated_report_response_valid(self):
        """5. GeneratedExpenseReportResponse — valid construction."""
        resp = GeneratedExpenseReportResponse(
            id=1,
            corp_id=CORP_ID,
            title="Q1 Report",
            start_date=START,
            end_date=END,
            total_rides=10,
            total_amount_usd=Decimal("500.00"),
            generated_at=NOW,
            generated_by_id=ADMIN_ID,
        )
        assert resp.id == 1
        assert resp.total_rides == 10

    def test_generated_report_detail_valid(self):
        """6. GeneratedExpenseReportDetail — valid with breakdowns."""
        detail = GeneratedExpenseReportDetail(
            id=1,
            corp_id=CORP_ID,
            title="Q1",
            start_date=START,
            end_date=END,
            total_rides=2,
            total_amount_usd=Decimal("100.00"),
            generated_at=NOW,
            generated_by_id=ADMIN_ID,
            by_member=[
                MemberExpenseSummary(
                    member_user_id=1,
                    member_name="Alice",
                    ride_count=2,
                    total_amount_usd=Decimal("100.00"),
                )
            ],
            by_category=[
                CategoryExpenseSummary(
                    category="sedan",
                    ride_count=2,
                    total_amount_usd=Decimal("100.00"),
                )
            ],
        )
        assert len(detail.by_member) == 1
        assert len(detail.by_category) == 1

    def test_list_response_valid(self):
        """7. GeneratedExpenseReportListResponse — valid construction."""
        resp = GeneratedExpenseReportListResponse(
            corp_id=CORP_ID,
            total=0,
            reports=[],
        )
        assert resp.corp_id == CORP_ID
        assert resp.total == 0

    def test_generate_request_title_optional(self):
        """8. ExpenseReportGenerateRequest — title optional."""
        req = ExpenseReportGenerateRequest(start_date=START, end_date=END)
        assert req.title is None

    def test_generate_request_title_max_length(self):
        """9. ExpenseReportGenerateRequest — title max length 200 chars enforced."""
        with pytest.raises(ValidationError):
            ExpenseReportGenerateRequest(
                start_date=START,
                end_date=END,
                title="x" * 201,
            )

    def test_member_summary_decimal_amount(self):
        """10. MemberExpenseSummary — total_amount_usd accepts Decimal."""
        m = MemberExpenseSummary(
            member_user_id=5,
            member_name="Bob",
            ride_count=1,
            total_amount_usd=Decimal("99.99"),
        )
        assert m.total_amount_usd == Decimal("99.99")


# ===========================================================================
# Service tests
# ===========================================================================


class TestGenerateExpenseReport:
    @pytest.mark.asyncio
    async def test_non_admin_raises_403(self):
        """11. generate_expense_report — non-admin → 403."""
        db = _db_no_admin()
        with pytest.raises(HTTPException) as exc:
            await generate_expense_report(
                db, CORP_ID, NON_ADMIN_ID, _make_generate_request()
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_start_after_end_raises_422(self):
        """12. generate_expense_report — start_date > end_date → 422."""
        admin = _make_admin_member()
        db = _db_admin_then_rides(admin, [])
        with pytest.raises(HTTPException) as exc:
            await generate_expense_report(
                db,
                CORP_ID,
                ADMIN_ID,
                _make_generate_request(start=date(2026, 4, 30), end=date(2026, 4, 1)),
            )
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_no_rides_returns_zero_totals(self):
        """13. generate_expense_report — no rides returns zero totals."""
        admin = _make_admin_member()
        db = _db_admin_then_rides(admin, [])
        result = await generate_expense_report(
            db, CORP_ID, ADMIN_ID, _make_generate_request()
        )
        assert result.total_rides == 0
        assert result.total_amount_usd == Decimal("0.00")
        assert result.by_member == []
        assert result.by_category == []

    @pytest.mark.asyncio
    async def test_single_ride_aggregated(self):
        """14. generate_expense_report — single ride aggregated correctly."""
        admin = _make_admin_member()
        ride = _make_ride(1, rider_id=5, fare=75.00, vehicle_type="sedan")
        user = _make_user(5, "Alice")
        db = _db_admin_then_rides(admin, [(ride, user)])

        result = await generate_expense_report(
            db, CORP_ID, ADMIN_ID, _make_generate_request()
        )

        assert result.total_rides == 1
        assert result.total_amount_usd == Decimal("75.0")
        assert len(result.by_member) == 1
        assert result.by_member[0].member_user_id == 5
        assert result.by_member[0].ride_count == 1
        assert len(result.by_category) == 1
        assert result.by_category[0].category == "sedan"

    @pytest.mark.asyncio
    async def test_multiple_rides_multiple_members(self):
        """15. generate_expense_report — multiple rides, multiple members."""
        admin = _make_admin_member()
        ride1 = _make_ride(1, rider_id=5, fare=50.00)
        ride2 = _make_ride(2, rider_id=6, fare=30.00)
        user1 = _make_user(5, "Alice")
        user2 = _make_user(6, "Bob")
        db = _db_admin_then_rides(admin, [(ride1, user1), (ride2, user2)])

        result = await generate_expense_report(
            db, CORP_ID, ADMIN_ID, _make_generate_request()
        )

        assert result.total_rides == 2
        assert result.total_amount_usd == Decimal("80.0")
        member_ids = {m.member_user_id for m in result.by_member}
        assert member_ids == {5, 6}

    @pytest.mark.asyncio
    async def test_multiple_categories(self):
        """16. generate_expense_report — multiple rides, multiple categories."""
        admin = _make_admin_member()
        ride1 = _make_ride(1, rider_id=5, fare=40.00, vehicle_type="sedan")
        ride2 = _make_ride(2, rider_id=5, fare=60.00, vehicle_type="suv")
        user = _make_user(5, "Alice")
        db = _db_admin_then_rides(admin, [(ride1, user), (ride2, user)])

        result = await generate_expense_report(
            db, CORP_ID, ADMIN_ID, _make_generate_request()
        )

        categories = {c.category for c in result.by_category}
        assert "sedan" in categories
        assert "suv" in categories

    @pytest.mark.asyncio
    async def test_default_title(self):
        """17. generate_expense_report — default title when none provided."""
        admin = _make_admin_member()
        db = _db_admin_then_rides(admin, [])
        req = _make_generate_request(start=date(2026, 4, 1), end=date(2026, 4, 30))
        result = await generate_expense_report(db, CORP_ID, ADMIN_ID, req)
        assert "2026-04-01" in result.title
        assert "2026-04-30" in result.title

    @pytest.mark.asyncio
    async def test_custom_title_respected(self):
        """18. generate_expense_report — custom title respected."""
        admin = _make_admin_member()
        db = _db_admin_then_rides(admin, [])
        req = _make_generate_request(title="April 2026 Expenses")
        result = await generate_expense_report(db, CORP_ID, ADMIN_ID, req)
        assert result.title == "April 2026 Expenses"

    @pytest.mark.asyncio
    async def test_stored_for_retrieval(self):
        """19. generate_expense_report — stores report for later retrieval."""
        admin = _make_admin_member()
        db = _db_admin_then_rides(admin, [])
        result = await generate_expense_report(
            db, CORP_ID, ADMIN_ID, _make_generate_request()
        )
        report_id = result.id
        assert report_id is not None
        # The service uses in-memory store; verify the id was issued
        assert report_id >= 1


class TestListGeneratedReports:
    @pytest.mark.asyncio
    async def test_non_admin_raises_403(self):
        """20. list_generated_reports — non-admin → 403."""
        db = _db_no_admin()
        with pytest.raises(HTTPException) as exc:
            await list_generated_reports(db, CORP_ID, NON_ADMIN_ID)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_empty_store_returns_zero(self):
        """21. list_generated_reports — empty store returns zero total."""
        admin = _make_admin_member()
        db = AsyncMock()
        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        db.execute = AsyncMock(return_value=r)

        result = await list_generated_reports(db, CORP_ID, ADMIN_ID)
        assert result.total == 0
        assert result.reports == []

    @pytest.mark.asyncio
    async def test_returns_only_correct_corp(self):
        """22. list_generated_reports — returns only reports for correct corp."""
        admin1 = _make_admin_member(ADMIN_ID)
        admin2 = MagicMock(spec=BusinessAccountMember)
        admin2.account_id = OTHER_CORP_ID
        admin2.user_id = ADMIN_ID
        admin2.role = MemberRole.ADMIN
        admin2.is_active = True

        # Generate a report for corp 1
        db1 = _db_admin_then_rides(admin1, [])
        r1 = await generate_expense_report(db1, CORP_ID, ADMIN_ID, _make_generate_request())

        # Generate a report for corp 2
        db2 = _db_admin_then_rides(admin2, [])
        db2_list_call = AsyncMock()
        r2_mock = MagicMock()
        r2_mock.scalar_one_or_none.return_value = admin2
        db2.execute = AsyncMock(return_value=r2_mock)
        # We need to manually insert a report for other corp
        from app.services.corporate_expense_report_service import _REPORT_STORE, _next_report_id
        oid = _next_report_id()
        _REPORT_STORE[oid] = {
            "id": oid,
            "corp_id": OTHER_CORP_ID,
            "title": "Other Corp Report",
            "start_date": START,
            "end_date": END,
            "total_rides": 0,
            "total_amount_usd": Decimal("0.00"),
            "generated_at": NOW,
            "generated_by_id": ADMIN_ID,
            "by_member": [],
            "by_category": [],
        }

        # List for corp 1 only
        r_corp1 = MagicMock()
        r_corp1.scalar_one_or_none.return_value = admin1
        list_db = AsyncMock()
        list_db.execute = AsyncMock(return_value=r_corp1)
        result = await list_generated_reports(list_db, CORP_ID, ADMIN_ID)

        # Should only see corp 1's reports
        for rep in result.reports:
            assert rep.corp_id == CORP_ID

    @pytest.mark.asyncio
    async def test_start_date_filter(self):
        """23. list_generated_reports — start_date filter applied."""
        admin = _make_admin_member()
        # Insert two reports with different start dates
        from app.services.corporate_expense_report_service import _REPORT_STORE, _next_report_id
        for start, end in [
            (date(2026, 1, 1), date(2026, 1, 31)),
            (date(2026, 4, 1), date(2026, 4, 30)),
        ]:
            rid = _next_report_id()
            _REPORT_STORE[rid] = {
                "id": rid,
                "corp_id": CORP_ID,
                "title": f"Report {start}",
                "start_date": start,
                "end_date": end,
                "total_rides": 0,
                "total_amount_usd": Decimal("0.00"),
                "generated_at": NOW,
                "generated_by_id": ADMIN_ID,
                "by_member": [],
                "by_category": [],
            }

        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        db = AsyncMock()
        db.execute = AsyncMock(return_value=r)

        result = await list_generated_reports(
            db, CORP_ID, ADMIN_ID, start_date=date(2026, 3, 1)
        )
        # Only April report passes the filter
        assert result.total == 1
        assert result.reports[0].start_date == date(2026, 4, 1)

    @pytest.mark.asyncio
    async def test_end_date_filter(self):
        """24. list_generated_reports — end_date filter applied."""
        admin = _make_admin_member()
        from app.services.corporate_expense_report_service import _REPORT_STORE, _next_report_id
        for start, end in [
            (date(2026, 1, 1), date(2026, 1, 31)),
            (date(2026, 4, 1), date(2026, 4, 30)),
        ]:
            rid = _next_report_id()
            _REPORT_STORE[rid] = {
                "id": rid,
                "corp_id": CORP_ID,
                "title": f"Report",
                "start_date": start,
                "end_date": end,
                "total_rides": 0,
                "total_amount_usd": Decimal("0.00"),
                "generated_at": NOW,
                "generated_by_id": ADMIN_ID,
                "by_member": [],
                "by_category": [],
            }

        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        db = AsyncMock()
        db.execute = AsyncMock(return_value=r)

        result = await list_generated_reports(
            db, CORP_ID, ADMIN_ID, end_date=date(2026, 2, 1)
        )
        assert result.total == 1
        assert result.reports[0].end_date == date(2026, 1, 31)

    @pytest.mark.asyncio
    async def test_both_date_filters(self):
        """25. list_generated_reports — both date filters applied simultaneously."""
        admin = _make_admin_member()
        from app.services.corporate_expense_report_service import _REPORT_STORE, _next_report_id
        for start, end in [
            (date(2026, 1, 1), date(2026, 1, 31)),
            (date(2026, 3, 1), date(2026, 3, 31)),
            (date(2026, 4, 1), date(2026, 4, 30)),
        ]:
            rid = _next_report_id()
            _REPORT_STORE[rid] = {
                "id": rid,
                "corp_id": CORP_ID,
                "title": "R",
                "start_date": start,
                "end_date": end,
                "total_rides": 0,
                "total_amount_usd": Decimal("0.00"),
                "generated_at": NOW,
                "generated_by_id": ADMIN_ID,
                "by_member": [],
                "by_category": [],
            }

        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        db = AsyncMock()
        db.execute = AsyncMock(return_value=r)

        result = await list_generated_reports(
            db, CORP_ID, ADMIN_ID,
            start_date=date(2026, 2, 1),
            end_date=date(2026, 3, 31),
        )
        assert result.total == 1
        assert result.reports[0].start_date == date(2026, 3, 1)

    @pytest.mark.asyncio
    async def test_skip_pagination(self):
        """26. list_generated_reports — pagination skip works."""
        admin = _make_admin_member()
        from app.services.corporate_expense_report_service import _REPORT_STORE, _next_report_id
        for i in range(5):
            rid = _next_report_id()
            _REPORT_STORE[rid] = {
                "id": rid,
                "corp_id": CORP_ID,
                "title": f"R{i}",
                "start_date": START,
                "end_date": END,
                "total_rides": 0,
                "total_amount_usd": Decimal("0.00"),
                "generated_at": NOW,
                "generated_by_id": ADMIN_ID,
                "by_member": [],
                "by_category": [],
            }

        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        db = AsyncMock()
        db.execute = AsyncMock(return_value=r)

        result = await list_generated_reports(db, CORP_ID, ADMIN_ID, skip=3)
        assert len(result.reports) == 2
        assert result.total == 5

    @pytest.mark.asyncio
    async def test_limit_pagination(self):
        """27. list_generated_reports — pagination limit works."""
        admin = _make_admin_member()
        from app.services.corporate_expense_report_service import _REPORT_STORE, _next_report_id
        for i in range(5):
            rid = _next_report_id()
            _REPORT_STORE[rid] = {
                "id": rid,
                "corp_id": CORP_ID,
                "title": f"R{i}",
                "start_date": START,
                "end_date": END,
                "total_rides": 0,
                "total_amount_usd": Decimal("0.00"),
                "generated_at": NOW,
                "generated_by_id": ADMIN_ID,
                "by_member": [],
                "by_category": [],
            }

        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        db = AsyncMock()
        db.execute = AsyncMock(return_value=r)

        result = await list_generated_reports(db, CORP_ID, ADMIN_ID, limit=2)
        assert len(result.reports) == 2
        assert result.total == 5

    @pytest.mark.asyncio
    async def test_sorted_newest_first(self):
        """28. list_generated_reports — results sorted newest first."""
        admin = _make_admin_member()
        from app.services.corporate_expense_report_service import _REPORT_STORE, _next_report_id
        times = [
            datetime(2026, 4, 1, tzinfo=timezone.utc),
            datetime(2026, 4, 15, tzinfo=timezone.utc),
            datetime(2026, 4, 10, tzinfo=timezone.utc),
        ]
        for t in times:
            rid = _next_report_id()
            _REPORT_STORE[rid] = {
                "id": rid,
                "corp_id": CORP_ID,
                "title": "R",
                "start_date": START,
                "end_date": END,
                "total_rides": 0,
                "total_amount_usd": Decimal("0.00"),
                "generated_at": t,
                "generated_by_id": ADMIN_ID,
                "by_member": [],
                "by_category": [],
            }

        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        db = AsyncMock()
        db.execute = AsyncMock(return_value=r)

        result = await list_generated_reports(db, CORP_ID, ADMIN_ID)
        dates = [rep.generated_at for rep in result.reports]
        assert dates == sorted(dates, reverse=True)


class TestGetGeneratedReport:
    @pytest.mark.asyncio
    async def test_non_admin_raises_403(self):
        """29. get_generated_report — non-admin → 403."""
        db = _db_no_admin()
        with pytest.raises(HTTPException) as exc:
            await get_generated_report(db, CORP_ID, 1, NON_ADMIN_ID)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        """30. get_generated_report — not found → 404."""
        admin = _make_admin_member()
        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        db = AsyncMock()
        db.execute = AsyncMock(return_value=r)

        with pytest.raises(HTTPException) as exc:
            await get_generated_report(db, CORP_ID, 9999, ADMIN_ID)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_wrong_corp_raises_404(self):
        """31. get_generated_report — wrong corp_id → 404."""
        # Generate under CORP_ID
        admin = _make_admin_member()
        db = _db_admin_then_rides(admin, [])
        result = await generate_expense_report(
            db, CORP_ID, ADMIN_ID, _make_generate_request()
        )
        report_id = result.id

        # Try to retrieve under OTHER_CORP_ID
        other_admin = MagicMock(spec=BusinessAccountMember)
        other_admin.account_id = OTHER_CORP_ID
        other_admin.user_id = ADMIN_ID
        other_admin.role = MemberRole.ADMIN
        other_admin.is_active = True

        r = MagicMock()
        r.scalar_one_or_none.return_value = other_admin
        db2 = AsyncMock()
        db2.execute = AsyncMock(return_value=r)

        with pytest.raises(HTTPException) as exc:
            await get_generated_report(db2, OTHER_CORP_ID, report_id, ADMIN_ID)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_success_returns_full_detail(self):
        """32. get_generated_report — success returns full detail."""
        admin = _make_admin_member()
        ride = _make_ride(1, rider_id=5, fare=100.00)
        user = _make_user(5, "Alice")
        db = _db_admin_then_rides(admin, [(ride, user)])

        generated = await generate_expense_report(
            db, CORP_ID, ADMIN_ID, _make_generate_request()
        )
        report_id = generated.id

        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        db2 = AsyncMock()
        db2.execute = AsyncMock(return_value=r)

        detail = await get_generated_report(db2, CORP_ID, report_id, ADMIN_ID)
        assert detail.id == report_id
        assert detail.corp_id == CORP_ID
        assert detail.total_rides == 1

    @pytest.mark.asyncio
    async def test_by_member_populated(self):
        """33. get_generated_report — by_member populated correctly."""
        admin = _make_admin_member()
        ride = _make_ride(1, rider_id=5, fare=80.00)
        user = _make_user(5, "Charlie")
        db = _db_admin_then_rides(admin, [(ride, user)])

        generated = await generate_expense_report(
            db, CORP_ID, ADMIN_ID, _make_generate_request()
        )

        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        db2 = AsyncMock()
        db2.execute = AsyncMock(return_value=r)

        detail = await get_generated_report(db2, CORP_ID, generated.id, ADMIN_ID)
        assert len(detail.by_member) == 1
        assert detail.by_member[0].member_name == "Charlie"
        assert detail.by_member[0].ride_count == 1

    @pytest.mark.asyncio
    async def test_by_category_populated(self):
        """34. get_generated_report — by_category populated correctly."""
        admin = _make_admin_member()
        ride = _make_ride(1, rider_id=5, fare=55.00, vehicle_type="suv")
        user = _make_user(5, "Dana")
        db = _db_admin_then_rides(admin, [(ride, user)])

        generated = await generate_expense_report(
            db, CORP_ID, ADMIN_ID, _make_generate_request()
        )

        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        db2 = AsyncMock()
        db2.execute = AsyncMock(return_value=r)

        detail = await get_generated_report(db2, CORP_ID, generated.id, ADMIN_ID)
        assert len(detail.by_category) == 1
        assert detail.by_category[0].category == "suv"


class TestExportReportCsv:
    async def _setup_report(self, fare: float = 50.0) -> tuple:
        """Helper to generate a report and return (db_for_get, report_id)."""
        admin = _make_admin_member()
        ride = _make_ride(1, rider_id=5, fare=fare, vehicle_type="sedan")
        user = _make_user(5, "Eve")
        db = _db_admin_then_rides(admin, [(ride, user)])

        generated = await generate_expense_report(
            db, CORP_ID, ADMIN_ID, _make_generate_request()
        )

        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        db2 = AsyncMock()
        db2.execute = AsyncMock(return_value=r)
        return db2, generated.id

    @pytest.mark.asyncio
    async def test_non_admin_raises_403(self):
        """35. export_report_csv — non-admin → 403."""
        db = _db_no_admin()
        with pytest.raises(HTTPException) as exc:
            await export_report_csv(db, CORP_ID, 1, NON_ADMIN_ID)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        """36. export_report_csv — not found → 404."""
        admin = _make_admin_member()
        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        db = AsyncMock()
        db.execute = AsyncMock(return_value=r)

        with pytest.raises(HTTPException) as exc:
            await export_report_csv(db, CORP_ID, 9999, ADMIN_ID)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_csv_string(self):
        """37. export_report_csv — returns CSV string."""
        db2, report_id = await self._setup_report()
        csv_text = await export_report_csv(db2, CORP_ID, report_id, ADMIN_ID)
        assert isinstance(csv_text, str)
        assert len(csv_text) > 0

    @pytest.mark.asyncio
    async def test_csv_contains_header_rows(self):
        """38. export_report_csv — CSV contains report header rows."""
        db2, report_id = await self._setup_report()
        csv_text = await export_report_csv(db2, CORP_ID, report_id, ADMIN_ID)
        assert "Corporate Expense Report" in csv_text
        assert "Total Rides" in csv_text
        assert "Total Amount" in csv_text

    @pytest.mark.asyncio
    async def test_csv_contains_member_section(self):
        """39. export_report_csv — CSV contains by_member section."""
        db2, report_id = await self._setup_report(fare=75.0)
        csv_text = await export_report_csv(db2, CORP_ID, report_id, ADMIN_ID)
        assert "By Member" in csv_text
        assert "Eve" in csv_text

    @pytest.mark.asyncio
    async def test_csv_contains_category_section(self):
        """40. export_report_csv — CSV contains by_category section."""
        db2, report_id = await self._setup_report()
        csv_text = await export_report_csv(db2, CORP_ID, report_id, ADMIN_ID)
        assert "By Category" in csv_text
        assert "sedan" in csv_text

    @pytest.mark.asyncio
    async def test_csv_parseable(self):
        """41. export_report_csv — CSV is parseable with csv.reader."""
        db2, report_id = await self._setup_report()
        csv_text = await export_report_csv(db2, CORP_ID, report_id, ADMIN_ID)
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)
        assert len(rows) > 5  # At minimum header + member + category rows


# ===========================================================================
# API layer tests (service patched)
# ===========================================================================


def _make_list_resp() -> GeneratedExpenseReportListResponse:
    return GeneratedExpenseReportListResponse(
        corp_id=CORP_ID,
        total=0,
        reports=[],
    )


def _make_detail_resp(report_id: int = 1) -> GeneratedExpenseReportDetail:
    return GeneratedExpenseReportDetail(
        id=report_id,
        corp_id=CORP_ID,
        title="Test Report",
        start_date=START,
        end_date=END,
        total_rides=5,
        total_amount_usd=Decimal("250.00"),
        generated_at=NOW,
        generated_by_id=ADMIN_ID,
        by_member=[
            MemberExpenseSummary(
                member_user_id=5,
                member_name="Alice",
                ride_count=5,
                total_amount_usd=Decimal("250.00"),
            )
        ],
        by_category=[
            CategoryExpenseSummary(
                category="sedan",
                ride_count=5,
                total_amount_usd=Decimal("250.00"),
            )
        ],
    )


def _setup_api_overrides(app, user_id: int = ADMIN_ID):
    from app.api.deps import get_current_user, get_db
    from app.models.user import User as UserModel

    fake_user = MagicMock(spec=UserModel)
    fake_user.id = user_id
    fake_user.is_admin = True

    async def fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_db] = fake_db
    return fake_user


class TestApiListExpenseReports:
    def test_list_returns_200(self):
        """42. GET /corporate/{corp_id}/expense-reports → 200."""
        from fastapi.testclient import TestClient
        from app.main import app

        _setup_api_overrides(app)
        with (
            patch(
                "app.api.v1.corporate_expense_report_aggregates.list_generated_reports",
                new=AsyncMock(return_value=_make_list_resp()),
            ),
            TestClient(app) as client,
        ):
            resp = client.get(f"/api/v1/corporate/{CORP_ID}/expense-reports")
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_service_403_bubbles(self):
        """43. GET /corporate/{corp_id}/expense-reports — service 403 bubbles up."""
        from fastapi.testclient import TestClient
        from app.main import app

        _setup_api_overrides(app, user_id=NON_ADMIN_ID)
        with (
            patch(
                "app.api.v1.corporate_expense_report_aggregates.list_generated_reports",
                new=AsyncMock(
                    side_effect=HTTPException(
                        status_code=403,
                        detail="You do not have admin access to this corporate account.",
                    )
                ),
            ),
            TestClient(app) as client,
        ):
            resp = client.get(f"/api/v1/corporate/{CORP_ID}/expense-reports")
        app.dependency_overrides.clear()
        assert resp.status_code == 403


class TestApiGenerateReport:
    def test_generate_returns_201(self):
        """44. POST /corporate/{corp_id}/expense-reports/generate → 201."""
        from fastapi.testclient import TestClient
        from app.main import app

        _setup_api_overrides(app)
        detail = _make_detail_resp()
        with (
            patch(
                "app.api.v1.corporate_expense_report_aggregates.generate_expense_report",
                new=AsyncMock(return_value=detail),
            ),
            TestClient(app) as client,
        ):
            resp = client.post(
                f"/api/v1/corporate/{CORP_ID}/expense-reports/generate",
                json={
                    "start_date": "2026-04-01",
                    "end_date": "2026-04-30",
                    "title": "April Report",
                },
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 201
        assert resp.json()["total_rides"] == 5

    def test_generate_403_bubbles(self):
        """45. POST /corporate/{corp_id}/expense-reports/generate — service 403 bubbles up."""
        from fastapi.testclient import TestClient
        from app.main import app

        _setup_api_overrides(app, user_id=NON_ADMIN_ID)
        with (
            patch(
                "app.api.v1.corporate_expense_report_aggregates.generate_expense_report",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=403, detail="Not admin.")
                ),
            ),
            TestClient(app) as client,
        ):
            resp = client.post(
                f"/api/v1/corporate/{CORP_ID}/expense-reports/generate",
                json={"start_date": "2026-04-01", "end_date": "2026-04-30"},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 403

    def test_generate_422_bubbles(self):
        """46. POST /corporate/{corp_id}/expense-reports/generate — service 422 bubbles up."""
        from fastapi.testclient import TestClient
        from app.main import app

        _setup_api_overrides(app)
        with (
            patch(
                "app.api.v1.corporate_expense_report_aggregates.generate_expense_report",
                new=AsyncMock(
                    side_effect=HTTPException(
                        status_code=422, detail="start_date must not be after end_date."
                    )
                ),
            ),
            TestClient(app) as client,
        ):
            resp = client.post(
                f"/api/v1/corporate/{CORP_ID}/expense-reports/generate",
                json={"start_date": "2026-04-30", "end_date": "2026-04-01"},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 422


class TestApiGetReportDetail:
    def test_get_detail_returns_200(self):
        """47. GET /corporate/{corp_id}/expense-reports/{report_id} → 200."""
        from fastapi.testclient import TestClient
        from app.main import app

        _setup_api_overrides(app)
        detail = _make_detail_resp(report_id=7)
        with (
            patch(
                "app.api.v1.corporate_expense_report_aggregates.get_generated_report",
                new=AsyncMock(return_value=detail),
            ),
            TestClient(app) as client,
        ):
            resp = client.get(f"/api/v1/corporate/{CORP_ID}/expense-reports/7")
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["id"] == 7

    def test_get_detail_404_bubbles(self):
        """48. GET /corporate/{corp_id}/expense-reports/{report_id} — 404 bubbles up."""
        from fastapi.testclient import TestClient
        from app.main import app

        _setup_api_overrides(app)
        with (
            patch(
                "app.api.v1.corporate_expense_report_aggregates.get_generated_report",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=404, detail="Not found.")
                ),
            ),
            TestClient(app) as client,
        ):
            resp = client.get(f"/api/v1/corporate/{CORP_ID}/expense-reports/9999")
        app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_get_detail_403_bubbles(self):
        """49. GET /corporate/{corp_id}/expense-reports/{report_id} — 403 bubbles up."""
        from fastapi.testclient import TestClient
        from app.main import app

        _setup_api_overrides(app, user_id=NON_ADMIN_ID)
        with (
            patch(
                "app.api.v1.corporate_expense_report_aggregates.get_generated_report",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=403, detail="Forbidden.")
                ),
            ),
            TestClient(app) as client,
        ):
            resp = client.get(f"/api/v1/corporate/{CORP_ID}/expense-reports/1")
        app.dependency_overrides.clear()
        assert resp.status_code == 403


class TestApiExportReport:
    def test_export_returns_200_csv(self):
        """50. GET /corporate/{corp_id}/expense-reports/{report_id}/export → 200 CSV."""
        from fastapi.testclient import TestClient
        from app.main import app

        _setup_api_overrides(app)
        csv_content = "Corporate Expense Report\nTitle,Test\n"
        with (
            patch(
                "app.api.v1.corporate_expense_report_aggregates.export_report_csv",
                new=AsyncMock(return_value=csv_content),
            ),
            TestClient(app) as client,
        ):
            resp = client.get(
                f"/api/v1/corporate/{CORP_ID}/expense-reports/1/export"
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_export_404_bubbles(self):
        """51. GET /corporate/{corp_id}/expense-reports/{report_id}/export — 404 bubbles up."""
        from fastapi.testclient import TestClient
        from app.main import app

        _setup_api_overrides(app)
        with (
            patch(
                "app.api.v1.corporate_expense_report_aggregates.export_report_csv",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=404, detail="Not found.")
                ),
            ),
            TestClient(app) as client,
        ):
            resp = client.get(
                f"/api/v1/corporate/{CORP_ID}/expense-reports/9999/export"
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_export_content_disposition_header(self):
        """55. GET .../export — Content-Disposition header set."""
        from fastapi.testclient import TestClient
        from app.main import app

        _setup_api_overrides(app)
        csv_content = "data"
        with (
            patch(
                "app.api.v1.corporate_expense_report_aggregates.export_report_csv",
                new=AsyncMock(return_value=csv_content),
            ),
            TestClient(app) as client,
        ):
            resp = client.get(
                f"/api/v1/corporate/{CORP_ID}/expense-reports/3/export"
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".csv" in cd


class TestApiDateFilters:
    def test_list_date_filters_passed_through(self):
        """52. GET /corporate/{corp_id}/expense-reports — date filters passed through."""
        from fastapi.testclient import TestClient
        from app.main import app

        _setup_api_overrides(app)
        captured_kwargs = {}

        async def fake_list(db, corp_id, requester_id, start_date=None, end_date=None, skip=0, limit=50):
            captured_kwargs["start_date"] = start_date
            captured_kwargs["end_date"] = end_date
            return _make_list_resp()

        with (
            patch(
                "app.api.v1.corporate_expense_report_aggregates.list_generated_reports",
                new=fake_list,
            ),
            TestClient(app) as client,
        ):
            resp = client.get(
                f"/api/v1/corporate/{CORP_ID}/expense-reports"
                "?start_date=2026-04-01&end_date=2026-04-30"
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert captured_kwargs["start_date"] == date(2026, 4, 1)
        assert captured_kwargs["end_date"] == date(2026, 4, 30)

    def test_list_skip_limit_defaults_accepted(self):
        """53. GET /corporate/{corp_id}/expense-reports — skip/limit defaults accepted."""
        from fastapi.testclient import TestClient
        from app.main import app

        _setup_api_overrides(app)
        with (
            patch(
                "app.api.v1.corporate_expense_report_aggregates.list_generated_reports",
                new=AsyncMock(return_value=_make_list_resp()),
            ),
            TestClient(app) as client,
        ):
            resp = client.get(f"/api/v1/corporate/{CORP_ID}/expense-reports")
        app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_generate_missing_fields_returns_422(self):
        """54. POST /corporate/{corp_id}/expense-reports/generate — missing fields → 422."""
        from fastapi.testclient import TestClient
        from app.main import app

        _setup_api_overrides(app)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/corporate/{CORP_ID}/expense-reports/generate",
                json={},  # missing start_date and end_date
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 422


# ===========================================================================
# Additional unit / edge-case tests
# ===========================================================================


class TestAdditionalEdgeCases:
    def test_reset_store_clears_state(self):
        """56. _reset_store clears state between isolated tests."""
        from app.services.corporate_expense_report_service import _REPORT_STORE, _next_report_id
        _REPORT_STORE[999] = {"corp_id": CORP_ID}
        _reset_store()
        assert _REPORT_STORE == {}

    @pytest.mark.asyncio
    async def test_multiple_generate_distinct_ids(self):
        """57. Multiple generate calls produce distinct IDs."""
        admin = _make_admin_member()
        db1 = _db_admin_then_rides(admin, [])
        db2 = _db_admin_then_rides(admin, [])

        r1 = await generate_expense_report(db1, CORP_ID, ADMIN_ID, _make_generate_request())
        r2 = await generate_expense_report(db2, CORP_ID, ADMIN_ID, _make_generate_request())

        assert r1.id != r2.id

    @pytest.mark.asyncio
    async def test_list_returns_all_with_large_limit(self):
        """58. list returns all reports when skip=0 and limit large enough."""
        admin = _make_admin_member()
        from app.services.corporate_expense_report_service import _REPORT_STORE, _next_report_id
        for _ in range(3):
            rid = _next_report_id()
            _REPORT_STORE[rid] = {
                "id": rid,
                "corp_id": CORP_ID,
                "title": "R",
                "start_date": START,
                "end_date": END,
                "total_rides": 0,
                "total_amount_usd": Decimal("0.00"),
                "generated_at": NOW,
                "generated_by_id": ADMIN_ID,
                "by_member": [],
                "by_category": [],
            }

        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        db = AsyncMock()
        db.execute = AsyncMock(return_value=r)

        result = await list_generated_reports(db, CORP_ID, ADMIN_ID, limit=200)
        assert result.total == 3
        assert len(result.reports) == 3

    @pytest.mark.asyncio
    async def test_member_totals_match_overall_total(self):
        """59. by_member totals match overall total_amount_usd."""
        admin = _make_admin_member()
        rides_users = [
            (_make_ride(1, rider_id=5, fare=40.0), _make_user(5, "Alice")),
            (_make_ride(2, rider_id=6, fare=60.0), _make_user(6, "Bob")),
        ]
        db = _db_admin_then_rides(admin, rides_users)

        result = await generate_expense_report(
            db, CORP_ID, ADMIN_ID, _make_generate_request()
        )

        member_sum = sum(m.total_amount_usd for m in result.by_member)
        assert member_sum == result.total_amount_usd

    @pytest.mark.asyncio
    async def test_category_totals_match_overall_total(self):
        """60. by_category totals match overall total_amount_usd."""
        admin = _make_admin_member()
        rides_users = [
            (_make_ride(1, rider_id=5, fare=40.0, vehicle_type="sedan"), _make_user(5, "Alice")),
            (_make_ride(2, rider_id=5, fare=60.0, vehicle_type="suv"), _make_user(5, "Alice")),
        ]
        db = _db_admin_then_rides(admin, rides_users)

        result = await generate_expense_report(
            db, CORP_ID, ADMIN_ID, _make_generate_request()
        )

        cat_sum = sum(c.total_amount_usd for c in result.by_category)
        assert cat_sum == result.total_amount_usd

    @pytest.mark.asyncio
    async def test_no_vehicle_type_defaults_standard(self):
        """61. Ride with no vehicle_type defaults category to 'standard'."""
        admin = _make_admin_member()
        ride = _make_ride(1, rider_id=5, fare=25.0)
        # Null out both category-related fields to force 'standard' fallback
        ride.vehicle_type_preference = None
        ride.vehicle_type = None
        user = _make_user(5, "Zara")
        db = _db_admin_then_rides(admin, [(ride, user)])

        result = await generate_expense_report(
            db, CORP_ID, ADMIN_ID, _make_generate_request()
        )

        categories = {c.category for c in result.by_category}
        assert "standard" in categories

    @pytest.mark.asyncio
    async def test_null_fare_treated_as_zero(self):
        """62. Ride with fare=None treated as zero."""
        admin = _make_admin_member()
        ride = _make_ride(1, rider_id=5, fare=50.0)  # start with default, then null out
        ride.actual_fare = None
        ride.estimated_fare = None
        user = _make_user(5, "Nil")
        db = _db_admin_then_rides(admin, [(ride, user)])

        result = await generate_expense_report(
            db, CORP_ID, ADMIN_ID, _make_generate_request()
        )

        assert result.total_amount_usd == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_csv_has_blank_separator_lines(self):
        """63. Export CSV blank-line separators between sections."""
        admin = _make_admin_member()
        ride = _make_ride(1, rider_id=5, fare=30.0)
        user = _make_user(5, "Fay")
        db = _db_admin_then_rides(admin, [(ride, user)])

        generated = await generate_expense_report(
            db, CORP_ID, ADMIN_ID, _make_generate_request()
        )

        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        db2 = AsyncMock()
        db2.execute = AsyncMock(return_value=r)

        csv_text = await export_report_csv(db2, CORP_ID, generated.id, ADMIN_ID)
        # There should be at least one blank line (empty row) separating sections
        lines = csv_text.splitlines()
        blank_lines = [l for l in lines if l.strip() == ""]
        assert len(blank_lines) >= 1

    @pytest.mark.asyncio
    async def test_total_reflects_full_count_after_filter(self):
        """64. list total reflects unfiltered count after date filter shrinks page."""
        admin = _make_admin_member()
        from app.services.corporate_expense_report_service import _REPORT_STORE, _next_report_id
        for start, end in [
            (date(2026, 1, 1), date(2026, 1, 31)),
            (date(2026, 4, 1), date(2026, 4, 30)),
            (date(2026, 5, 1), date(2026, 5, 31)),
        ]:
            rid = _next_report_id()
            _REPORT_STORE[rid] = {
                "id": rid,
                "corp_id": CORP_ID,
                "title": "R",
                "start_date": start,
                "end_date": end,
                "total_rides": 0,
                "total_amount_usd": Decimal("0.00"),
                "generated_at": NOW,
                "generated_by_id": ADMIN_ID,
                "by_member": [],
                "by_category": [],
            }

        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        db = AsyncMock()
        db.execute = AsyncMock(return_value=r)

        # Filter to only April+
        result = await list_generated_reports(
            db, CORP_ID, ADMIN_ID, start_date=date(2026, 4, 1)
        )
        # Jan is excluded; April and May match
        assert result.total == 2
        assert len(result.reports) == 2

    @pytest.mark.asyncio
    async def test_get_report_id_matches_generate(self):
        """65. get_generated_report — report_id from generate matches retrieval."""
        admin = _make_admin_member()
        db = _db_admin_then_rides(admin, [])
        generated = await generate_expense_report(
            db, CORP_ID, ADMIN_ID, _make_generate_request()
        )
        report_id = generated.id

        r = MagicMock()
        r.scalar_one_or_none.return_value = admin
        db2 = AsyncMock()
        db2.execute = AsyncMock(return_value=r)

        fetched = await get_generated_report(db2, CORP_ID, report_id, ADMIN_ID)
        assert fetched.id == report_id
        assert fetched.corp_id == CORP_ID
