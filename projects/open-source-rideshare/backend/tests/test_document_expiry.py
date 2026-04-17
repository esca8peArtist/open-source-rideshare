"""Tests for the driver document expiry alert service and schemas.

Covers:
  - get_driver_expiry_status (async, mocked DB)
  - get_all_expiring_documents (async, mocked DB)
  - run_expiry_scan (async, mocked DB)
  - Helper functions _days_until and _classify (pure)
  - Pydantic schemas (ExpiringDocumentItem, DriverExpiryStatusResponse, etc.)

No live database is used. All DB interactions are mocked with AsyncMock /
MagicMock following the same pattern used in test_cancellation_policies.py.
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.document_expiry import (
    AdminExpiringDocumentRow,
    AdminExpiringDocumentsResponse,
    DriverExpiryStatusResponse,
    ExpiringDocumentItem,
    ExpiryScaResponse,
)
from app.services.document_expiry_alerts import (
    ExpiryScaResult,
    ExpiryStatusResult,
    ExpiringDocument,
    DriverExpiryRow,
    _classify,
    _days_until,
    get_all_expiring_documents,
    get_driver_expiry_status,
    run_expiry_scan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TODAY = date.today()


def _make_license_mock(
    doc_id=1,
    driver_id=10,
    expiry_date=None,
    status_value="approved",
):
    """Build a mock DriverLicense ORM object."""
    from app.models.driver_documents import DocumentStatus
    lic = MagicMock()
    lic.id = doc_id
    lic.driver_id = driver_id
    lic.expiry_date = expiry_date
    status = MagicMock()
    status.value = status_value
    lic.status = status
    return lic


def _make_registration_mock(
    doc_id=2,
    driver_id=10,
    expiry_date=None,
    status_value="approved",
):
    reg = MagicMock()
    reg.id = doc_id
    reg.driver_id = driver_id
    reg.expiry_date = expiry_date
    status = MagicMock()
    status.value = status_value
    reg.status = status
    return reg


def _make_insurance_mock(
    doc_id=3,
    driver_id=10,
    policy_end_date=None,
    status_value="approved",
):
    ins = MagicMock()
    ins.id = doc_id
    ins.driver_id = driver_id
    ins.policy_end_date = policy_end_date
    status = MagicMock()
    status.value = status_value
    ins.status = status
    return ins


def _make_inspection_mock(
    doc_id=4,
    driver_id=10,
    expiry_date=None,
    status_value="approved",
):
    insp = MagicMock()
    insp.id = doc_id
    insp.driver_id = driver_id
    insp.expiry_date = expiry_date
    status = MagicMock()
    status.value = status_value
    insp.status = status
    return insp


def _db_with_scalars_sequence(*doc_lists):
    """Build an AsyncSession mock where each execute() call returns a list of docs.

    Each element of *doc_lists* is a list of ORM mocks to return from
    result.scalars() for that particular execute() call.

    The service iterates directly over result.scalars() so we make the scalars
    return value itself be the list (which is directly iterable).
    """
    db = AsyncMock()
    results = []
    for doc_list in doc_lists:
        result = MagicMock()
        # The service code does: `for item in lic_rows.scalars():`
        # so scalars() must return something iterable — use the list directly.
        result.scalars.return_value = doc_list
        results.append(result)
    db.execute = AsyncMock(side_effect=results)
    db.commit = AsyncMock()
    return db


def _db_with_rowcount_sequence(*rowcounts):
    """Build an AsyncSession mock for run_expiry_scan (update statements)."""
    db = AsyncMock()
    results = []
    for rc in rowcounts:
        result = MagicMock()
        result.rowcount = rc
        results.append(result)
    db.execute = AsyncMock(side_effect=results)
    db.commit = AsyncMock()
    return db


# ===========================================================================
# TestClassifyHelper
# ===========================================================================


class TestClassifyHelper:
    """Tests for the pure _classify helper function."""

    def test_none_expiry_returns_none(self):
        assert _classify(None, _TODAY, 30) is None

    def test_past_expiry_returns_expired(self):
        past = _TODAY - timedelta(days=1)
        assert _classify(past, _TODAY, 30) == "expired"

    def test_today_returns_expiring(self):
        assert _classify(_TODAY, _TODAY, 30) == "expiring"

    def test_within_window_returns_expiring(self):
        soon = _TODAY + timedelta(days=15)
        assert _classify(soon, _TODAY, 30) == "expiring"

    def test_at_window_boundary_returns_expiring(self):
        boundary = _TODAY + timedelta(days=30)
        assert _classify(boundary, _TODAY, 30) == "expiring"

    def test_beyond_window_returns_none(self):
        far = _TODAY + timedelta(days=31)
        assert _classify(far, _TODAY, 30) is None

    def test_expiry_yesterday_is_expired(self):
        yesterday = _TODAY - timedelta(days=1)
        assert _classify(yesterday, _TODAY, 30) == "expired"

    def test_short_window_1_day(self):
        tomorrow = _TODAY + timedelta(days=1)
        assert _classify(tomorrow, _TODAY, 1) == "expiring"

    def test_just_outside_short_window(self):
        two_days = _TODAY + timedelta(days=2)
        assert _classify(two_days, _TODAY, 1) is None


# ===========================================================================
# TestDaysUntilHelper
# ===========================================================================


class TestDaysUntilHelper:
    """Tests for the pure _days_until helper function."""

    def test_none_expiry_returns_none(self):
        assert _days_until(None, _TODAY) is None

    def test_today_returns_zero(self):
        assert _days_until(_TODAY, _TODAY) == 0

    def test_tomorrow_returns_one(self):
        tomorrow = _TODAY + timedelta(days=1)
        assert _days_until(tomorrow, _TODAY) == 1

    def test_yesterday_returns_negative_one(self):
        yesterday = _TODAY - timedelta(days=1)
        assert _days_until(yesterday, _TODAY) == -1

    def test_far_future(self):
        future = _TODAY + timedelta(days=365)
        assert _days_until(future, _TODAY) == 365

    def test_far_past(self):
        past = _TODAY - timedelta(days=100)
        assert _days_until(past, _TODAY) == -100


# ===========================================================================
# TestExpiryStatusResult
# ===========================================================================


class TestExpiryStatusResult:
    """Tests for the ExpiryStatusResult dataclass."""

    def test_has_issues_false_when_empty(self):
        result = ExpiryStatusResult(driver_id=1)
        assert result.has_issues is False

    def test_has_issues_true_with_expiring(self):
        doc = ExpiringDocument(
            doc_type="license",
            doc_id=1,
            expiry_date=_TODAY + timedelta(days=5),
            days_until_expiry=5,
            status="approved",
        )
        result = ExpiryStatusResult(driver_id=1, expiring=[doc])
        assert result.has_issues is True

    def test_has_issues_true_with_expired(self):
        doc = ExpiringDocument(
            doc_type="license",
            doc_id=1,
            expiry_date=_TODAY - timedelta(days=5),
            days_until_expiry=-5,
            status="approved",
        )
        result = ExpiryStatusResult(driver_id=1, expired=[doc])
        assert result.has_issues is True

    def test_default_lists_are_empty(self):
        result = ExpiryStatusResult(driver_id=42)
        assert result.expiring == []
        assert result.expired == []


# ===========================================================================
# TestExpiryScaResult
# ===========================================================================


class TestExpiryScaResult:
    """Tests for ExpiryScaResult total_marked_expired property."""

    def test_total_zero_when_all_zero(self):
        r = ExpiryScaResult()
        assert r.total_marked_expired == 0

    def test_total_sums_all_fields(self):
        r = ExpiryScaResult(
            licenses_marked_expired=3,
            registrations_marked_expired=2,
            insurance_marked_expired=1,
            inspections_marked_expired=4,
        )
        assert r.total_marked_expired == 10

    def test_partial_fields(self):
        r = ExpiryScaResult(licenses_marked_expired=5)
        assert r.total_marked_expired == 5


# ===========================================================================
# TestGetDriverExpiryStatus
# ===========================================================================


class TestGetDriverExpiryStatus:
    """Tests for get_driver_expiry_status (async, mocked DB)."""

    @pytest.mark.asyncio
    async def test_no_documents_returns_empty_result(self):
        db = _db_with_scalars_sequence([], [], [], [])
        result = await get_driver_expiry_status(driver_id=1, db=db, days_ahead=30)
        assert result.driver_id == 1
        assert result.expiring == []
        assert result.expired == []
        assert result.has_issues is False

    @pytest.mark.asyncio
    async def test_driver_id_preserved(self):
        db = _db_with_scalars_sequence([], [], [], [])
        result = await get_driver_expiry_status(driver_id=99, db=db)
        assert result.driver_id == 99

    @pytest.mark.asyncio
    async def test_license_expiring_soon_added_to_expiring(self):
        soon = _TODAY + timedelta(days=10)
        lic = _make_license_mock(doc_id=1, driver_id=5, expiry_date=soon, status_value="approved")
        db = _db_with_scalars_sequence([lic], [], [], [])
        result = await get_driver_expiry_status(driver_id=5, db=db, days_ahead=30)
        assert len(result.expiring) == 1
        assert result.expiring[0].doc_type == "license"
        assert result.expiring[0].doc_id == 1
        assert result.expiring[0].days_until_expiry == (soon - _TODAY).days

    @pytest.mark.asyncio
    async def test_license_expired_added_to_expired(self):
        past = _TODAY - timedelta(days=5)
        lic = _make_license_mock(doc_id=2, driver_id=5, expiry_date=past, status_value="approved")
        db = _db_with_scalars_sequence([lic], [], [], [])
        result = await get_driver_expiry_status(driver_id=5, db=db, days_ahead=30)
        assert len(result.expired) == 1
        assert result.expired[0].doc_type == "license"
        assert result.expired[0].days_until_expiry == (past - _TODAY).days

    @pytest.mark.asyncio
    async def test_registration_expiring_soon(self):
        soon = _TODAY + timedelta(days=7)
        reg = _make_registration_mock(doc_id=3, driver_id=5, expiry_date=soon)
        db = _db_with_scalars_sequence([], [reg], [], [])
        result = await get_driver_expiry_status(driver_id=5, db=db, days_ahead=30)
        assert len(result.expiring) == 1
        assert result.expiring[0].doc_type == "registration"

    @pytest.mark.asyncio
    async def test_insurance_expiring_soon(self):
        soon = _TODAY + timedelta(days=20)
        ins = _make_insurance_mock(doc_id=4, driver_id=5, policy_end_date=soon)
        db = _db_with_scalars_sequence([], [], [ins], [])
        result = await get_driver_expiry_status(driver_id=5, db=db, days_ahead=30)
        assert len(result.expiring) == 1
        assert result.expiring[0].doc_type == "insurance"

    @pytest.mark.asyncio
    async def test_inspection_expiring_soon(self):
        soon = _TODAY + timedelta(days=3)
        insp = _make_inspection_mock(doc_id=5, driver_id=5, expiry_date=soon)
        db = _db_with_scalars_sequence([], [], [], [insp])
        result = await get_driver_expiry_status(driver_id=5, db=db, days_ahead=30)
        assert len(result.expiring) == 1
        assert result.expiring[0].doc_type == "inspection"

    @pytest.mark.asyncio
    async def test_document_far_in_future_not_included(self):
        far = _TODAY + timedelta(days=100)
        lic = _make_license_mock(doc_id=1, driver_id=5, expiry_date=far, status_value="approved")
        db = _db_with_scalars_sequence([lic], [], [], [])
        result = await get_driver_expiry_status(driver_id=5, db=db, days_ahead=30)
        assert result.expiring == []
        assert result.expired == []
        assert result.has_issues is False

    @pytest.mark.asyncio
    async def test_mixed_expiring_and_expired(self):
        past = _TODAY - timedelta(days=2)
        soon = _TODAY + timedelta(days=14)
        lic_expired = _make_license_mock(doc_id=1, driver_id=5, expiry_date=past)
        reg_expiring = _make_registration_mock(doc_id=2, driver_id=5, expiry_date=soon)
        db = _db_with_scalars_sequence([lic_expired], [reg_expiring], [], [])
        result = await get_driver_expiry_status(driver_id=5, db=db, days_ahead=30)
        assert len(result.expired) == 1
        assert len(result.expiring) == 1
        assert result.has_issues is True

    @pytest.mark.asyncio
    async def test_four_execute_calls_made(self):
        db = _db_with_scalars_sequence([], [], [], [])
        await get_driver_expiry_status(driver_id=1, db=db, days_ahead=30)
        assert db.execute.await_count == 4

    @pytest.mark.asyncio
    async def test_custom_days_ahead_used(self):
        soon_5 = _TODAY + timedelta(days=5)
        lic = _make_license_mock(expiry_date=soon_5)
        db = _db_with_scalars_sequence([lic], [], [], [])
        # With days_ahead=3, a doc expiring in 5 days should NOT appear
        result = await get_driver_expiry_status(driver_id=1, db=db, days_ahead=3)
        assert result.expiring == []

    @pytest.mark.asyncio
    async def test_status_value_preserved(self):
        soon = _TODAY + timedelta(days=5)
        lic = _make_license_mock(doc_id=1, expiry_date=soon, status_value="pending_review")
        db = _db_with_scalars_sequence([lic], [], [], [])
        result = await get_driver_expiry_status(driver_id=1, db=db, days_ahead=30)
        assert result.expiring[0].status == "pending_review"


# ===========================================================================
# TestGetAllExpiringDocuments
# ===========================================================================


class TestGetAllExpiringDocuments:
    """Tests for get_all_expiring_documents (async, mocked DB)."""

    @pytest.mark.asyncio
    async def test_no_documents_returns_empty_list(self):
        db = _db_with_scalars_sequence([], [], [], [])
        rows = await get_all_expiring_documents(db, days_ahead=30)
        assert rows == []

    @pytest.mark.asyncio
    async def test_returns_license_rows(self):
        soon = _TODAY + timedelta(days=5)
        lic = _make_license_mock(doc_id=1, driver_id=10, expiry_date=soon)
        db = _db_with_scalars_sequence([lic], [], [], [])
        rows = await get_all_expiring_documents(db, days_ahead=30)
        assert len(rows) == 1
        assert rows[0].doc_type == "license"
        assert rows[0].driver_id == 10
        assert rows[0].doc_id == 1

    @pytest.mark.asyncio
    async def test_doc_type_filter_license_only_one_query(self):
        soon = _TODAY + timedelta(days=5)
        lic = _make_license_mock(doc_id=1, driver_id=10, expiry_date=soon)
        # With doc_type="license" only one DB query should run
        db = _db_with_scalars_sequence([lic])
        rows = await get_all_expiring_documents(db, days_ahead=30, doc_type="license")
        assert len(rows) == 1
        assert rows[0].doc_type == "license"
        assert db.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_doc_type_filter_registration_only(self):
        soon = _TODAY + timedelta(days=5)
        reg = _make_registration_mock(doc_id=2, driver_id=11, expiry_date=soon)
        db = _db_with_scalars_sequence([reg])
        rows = await get_all_expiring_documents(db, days_ahead=30, doc_type="registration")
        assert len(rows) == 1
        assert rows[0].doc_type == "registration"

    @pytest.mark.asyncio
    async def test_doc_type_filter_insurance_only(self):
        soon = _TODAY + timedelta(days=5)
        ins = _make_insurance_mock(doc_id=3, driver_id=12, policy_end_date=soon)
        db = _db_with_scalars_sequence([ins])
        rows = await get_all_expiring_documents(db, days_ahead=30, doc_type="insurance")
        assert len(rows) == 1
        assert rows[0].doc_type == "insurance"

    @pytest.mark.asyncio
    async def test_doc_type_filter_inspection_only(self):
        soon = _TODAY + timedelta(days=5)
        insp = _make_inspection_mock(doc_id=4, driver_id=13, expiry_date=soon)
        db = _db_with_scalars_sequence([insp])
        rows = await get_all_expiring_documents(db, days_ahead=30, doc_type="inspection")
        assert len(rows) == 1
        assert rows[0].doc_type == "inspection"

    @pytest.mark.asyncio
    async def test_no_filter_runs_four_queries(self):
        db = _db_with_scalars_sequence([], [], [], [])
        await get_all_expiring_documents(db, days_ahead=30)
        assert db.execute.await_count == 4

    @pytest.mark.asyncio
    async def test_sort_expired_before_expiring(self):
        past = _TODAY - timedelta(days=2)
        soon = _TODAY + timedelta(days=10)
        lic_expired = _make_license_mock(doc_id=1, driver_id=10, expiry_date=past)
        reg_expiring = _make_registration_mock(doc_id=2, driver_id=11, expiry_date=soon)
        db = _db_with_scalars_sequence([reg_expiring], [lic_expired], [], [])
        rows = await get_all_expiring_documents(db, days_ahead=30)
        # Expired docs come first (negative days_until_expiry)
        assert rows[0].days_until_expiry < 0

    @pytest.mark.asyncio
    async def test_pagination_skip(self):
        soon = _TODAY + timedelta(days=5)
        docs = [_make_license_mock(doc_id=i, driver_id=i, expiry_date=soon) for i in range(1, 4)]
        db = _db_with_scalars_sequence(docs, [], [], [])
        rows = await get_all_expiring_documents(db, days_ahead=30, skip=2, limit=10)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_pagination_limit(self):
        soon = _TODAY + timedelta(days=5)
        docs = [_make_license_mock(doc_id=i, driver_id=i, expiry_date=soon) for i in range(1, 6)]
        db = _db_with_scalars_sequence(docs, [], [], [])
        rows = await get_all_expiring_documents(db, days_ahead=30, skip=0, limit=2)
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_days_until_expiry_computed_correctly(self):
        soon = _TODAY + timedelta(days=8)
        lic = _make_license_mock(doc_id=1, driver_id=5, expiry_date=soon)
        db = _db_with_scalars_sequence([lic], [], [], [])
        rows = await get_all_expiring_documents(db, days_ahead=30)
        assert rows[0].days_until_expiry == 8

    @pytest.mark.asyncio
    async def test_driver_expiry_row_fields_populated(self):
        soon = _TODAY + timedelta(days=5)
        lic = _make_license_mock(doc_id=7, driver_id=42, expiry_date=soon, status_value="pending_review")
        db = _db_with_scalars_sequence([lic], [], [], [])
        rows = await get_all_expiring_documents(db, days_ahead=30)
        row = rows[0]
        assert isinstance(row, DriverExpiryRow)
        assert row.driver_id == 42
        assert row.doc_id == 7
        assert row.expiry_date == soon
        assert row.status == "pending_review"


# ===========================================================================
# TestRunExpiryScan
# ===========================================================================


class TestRunExpiryScan:
    """Tests for run_expiry_scan (async, mocked DB)."""

    @pytest.mark.asyncio
    async def test_returns_expiry_sca_result(self):
        db = _db_with_rowcount_sequence(0, 0, 0, 0)
        result = await run_expiry_scan(db)
        assert isinstance(result, ExpiryScaResult)

    @pytest.mark.asyncio
    async def test_zero_counts_when_no_overdue(self):
        db = _db_with_rowcount_sequence(0, 0, 0, 0)
        result = await run_expiry_scan(db)
        assert result.licenses_marked_expired == 0
        assert result.registrations_marked_expired == 0
        assert result.insurance_marked_expired == 0
        assert result.inspections_marked_expired == 0
        assert result.total_marked_expired == 0

    @pytest.mark.asyncio
    async def test_counts_from_rowcount(self):
        db = _db_with_rowcount_sequence(3, 1, 2, 0)
        result = await run_expiry_scan(db)
        assert result.licenses_marked_expired == 3
        assert result.registrations_marked_expired == 1
        assert result.insurance_marked_expired == 2
        assert result.inspections_marked_expired == 0

    @pytest.mark.asyncio
    async def test_total_is_sum_of_parts(self):
        db = _db_with_rowcount_sequence(3, 1, 2, 4)
        result = await run_expiry_scan(db)
        assert result.total_marked_expired == 10

    @pytest.mark.asyncio
    async def test_four_update_statements_executed(self):
        db = _db_with_rowcount_sequence(0, 0, 0, 0)
        await run_expiry_scan(db)
        assert db.execute.await_count == 4

    @pytest.mark.asyncio
    async def test_commit_called(self):
        db = _db_with_rowcount_sequence(0, 0, 0, 0)
        await run_expiry_scan(db)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_idempotent_second_call_zero(self):
        """Calling scan a second time when nothing is overdue returns zeros."""
        db = _db_with_rowcount_sequence(0, 0, 0, 0)
        result = await run_expiry_scan(db)
        assert result.total_marked_expired == 0

    @pytest.mark.asyncio
    async def test_large_counts(self):
        db = _db_with_rowcount_sequence(1000, 500, 250, 750)
        result = await run_expiry_scan(db)
        assert result.total_marked_expired == 2500


# ===========================================================================
# TestDocumentExpirySchemas
# ===========================================================================


class TestDocumentExpirySchemas:
    """Pydantic validation tests for document expiry schemas."""

    def test_expiring_document_item_basic(self):
        item = ExpiringDocumentItem(
            doc_type="license",
            doc_id=1,
            expiry_date=_TODAY + timedelta(days=10),
            days_until_expiry=10,
            status="approved",
        )
        assert item.doc_type == "license"
        assert item.doc_id == 1
        assert item.days_until_expiry == 10

    def test_expiring_document_item_no_expiry_date(self):
        item = ExpiringDocumentItem(
            doc_type="registration",
            doc_id=2,
            expiry_date=None,
            days_until_expiry=None,
            status="approved",
        )
        assert item.expiry_date is None
        assert item.days_until_expiry is None

    def test_expiring_document_item_negative_days(self):
        item = ExpiringDocumentItem(
            doc_type="insurance",
            doc_id=3,
            expiry_date=_TODAY - timedelta(days=5),
            days_until_expiry=-5,
            status="approved",
        )
        assert item.days_until_expiry == -5

    def test_expiring_document_item_all_doc_types_valid(self):
        for doc_type in ("license", "registration", "insurance", "inspection"):
            item = ExpiringDocumentItem(
                doc_type=doc_type,
                doc_id=1,
                expiry_date=None,
                days_until_expiry=None,
                status="approved",
            )
            assert item.doc_type == doc_type

    def test_driver_expiry_status_response_empty(self):
        resp = DriverExpiryStatusResponse(
            driver_id=1,
            expiring=[],
            expired=[],
            has_issues=False,
        )
        assert resp.driver_id == 1
        assert resp.has_issues is False

    def test_driver_expiry_status_response_with_items(self):
        item = ExpiringDocumentItem(
            doc_type="license",
            doc_id=1,
            expiry_date=_TODAY + timedelta(days=5),
            days_until_expiry=5,
            status="approved",
        )
        resp = DriverExpiryStatusResponse(
            driver_id=10,
            expiring=[item],
            expired=[],
            has_issues=True,
        )
        assert len(resp.expiring) == 1
        assert resp.has_issues is True

    def test_admin_expiring_document_row(self):
        row = AdminExpiringDocumentRow(
            driver_id=5,
            doc_type="inspection",
            doc_id=99,
            expiry_date=_TODAY + timedelta(days=2),
            days_until_expiry=2,
            status="pending_review",
        )
        assert row.driver_id == 5
        assert row.doc_type == "inspection"
        assert row.status == "pending_review"

    def test_admin_expiring_documents_response(self):
        row = AdminExpiringDocumentRow(
            driver_id=1,
            doc_type="license",
            doc_id=1,
            expiry_date=_TODAY,
            days_until_expiry=0,
            status="approved",
        )
        resp = AdminExpiringDocumentsResponse(
            items=[row],
            total=1,
            days_ahead=30,
            doc_type_filter=None,
        )
        assert resp.total == 1
        assert resp.days_ahead == 30
        assert resp.doc_type_filter is None

    def test_admin_expiring_documents_response_with_filter(self):
        resp = AdminExpiringDocumentsResponse(
            items=[],
            total=0,
            days_ahead=7,
            doc_type_filter="license",
        )
        assert resp.doc_type_filter == "license"

    def test_expiry_sca_response(self):
        resp = ExpiryScaResponse(
            licenses_marked_expired=3,
            registrations_marked_expired=1,
            insurance_marked_expired=2,
            inspections_marked_expired=0,
            total_marked_expired=6,
        )
        assert resp.total_marked_expired == 6
        assert resp.licenses_marked_expired == 3

    def test_expiry_sca_response_all_zero(self):
        resp = ExpiryScaResponse(
            licenses_marked_expired=0,
            registrations_marked_expired=0,
            insurance_marked_expired=0,
            inspections_marked_expired=0,
            total_marked_expired=0,
        )
        assert resp.total_marked_expired == 0

    def test_expiring_document_item_from_attributes_config(self):
        assert ExpiringDocumentItem.model_config.get("from_attributes") is True

    def test_admin_expiring_document_row_from_attributes_config(self):
        assert AdminExpiringDocumentRow.model_config.get("from_attributes") is True
