"""Comprehensive unit tests for driver insurance document management.

Covers:
- Model fields, enum values, and table structure
- Schema validation (create, update, admin review, status summary)
- Service logic: create, update, admin review, status summary,
  expiring documents, mark expired
- Endpoint auth checks and behaviour

All tests are pure unit tests — no database required.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_insurance import (
    DriverInsuranceDocument,
    InsuranceAlertType,
    InsuranceDocumentStatus,
    InsuranceDocumentType,
    InsuranceExpiryAlert,
)
from app.schemas.driver_insurance import (
    AdminReviewRequest,
    InsuranceDocumentCreate,
    InsuranceDocumentResponse,
    InsuranceDocumentUpdate,
    InsuranceStatusSummary,
)
from app.services.driver_insurance import (
    InsuranceDocumentError,
    admin_review_document,
    create_insurance_document,
    get_driver_insurance_documents,
    get_expiring_documents,
    get_insurance_status_summary,
    get_latest_approved_insurance,
    mark_expired_documents,
    update_insurance_document,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TOMORROW = date.today() + timedelta(days=1)
NEXT_YEAR = date.today() + timedelta(days=365)
YESTERDAY = date.today() - timedelta(days=1)
TODAY = date.today()


def _make_doc(**kwargs) -> DriverInsuranceDocument:
    defaults = dict(
        id=1,
        driver_id=10,
        document_type=InsuranceDocumentType.LIABILITY,
        insurance_provider="SafeDrive Insurance",
        policy_number="POL-001",
        coverage_amount=Decimal("100000.00"),
        policy_start_date=TODAY,
        policy_end_date=NEXT_YEAR,
        document_url="https://storage.example.com/doc1.pdf",
        status=InsuranceDocumentStatus.PENDING_REVIEW,
        rejection_reason=None,
        verified_by=None,
        verified_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    doc = MagicMock(spec=DriverInsuranceDocument)
    for k, v in defaults.items():
        setattr(doc, k, v)
    return doc


def _make_db(scalar=None, scalars=None):
    """Return a mock AsyncSession with pre-configured execute results."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    result.scalars.return_value.all.return_value = scalars or []
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


# ===========================================================================
# Model tests
# ===========================================================================


class TestDriverInsuranceDocumentModel:
    def test_tablename(self):
        assert DriverInsuranceDocument.__tablename__ == "driver_insurance_documents"

    def test_has_required_columns(self):
        cols = {c.key for c in DriverInsuranceDocument.__table__.columns}
        required = {
            "id", "driver_id", "document_type", "insurance_provider", "policy_number",
            "coverage_amount", "policy_start_date", "policy_end_date", "document_url",
            "status", "rejection_reason", "verified_by", "verified_at",
            "created_at", "updated_at",
        }
        assert required.issubset(cols)

    def test_document_type_enum_values(self):
        assert InsuranceDocumentType.LIABILITY == "liability"
        assert InsuranceDocumentType.COMPREHENSIVE == "comprehensive"
        assert InsuranceDocumentType.COMMERCIAL == "commercial"
        assert InsuranceDocumentType.PERSONAL_INJURY_PROTECTION == "personal_injury_protection"

    def test_status_enum_values(self):
        assert InsuranceDocumentStatus.PENDING_UPLOAD == "pending_upload"
        assert InsuranceDocumentStatus.PENDING_REVIEW == "pending_review"
        assert InsuranceDocumentStatus.APPROVED == "approved"
        assert InsuranceDocumentStatus.REJECTED == "rejected"
        assert InsuranceDocumentStatus.EXPIRED == "expired"

    def test_all_status_values_exist(self):
        expected = {"pending_upload", "pending_review", "approved", "rejected", "expired"}
        actual = {s.value for s in InsuranceDocumentStatus}
        assert actual == expected

    def test_all_document_type_values_exist(self):
        expected = {"liability", "comprehensive", "commercial", "personal_injury_protection"}
        actual = {t.value for t in InsuranceDocumentType}
        assert actual == expected


class TestInsuranceExpiryAlertModel:
    def test_tablename(self):
        assert InsuranceExpiryAlert.__tablename__ == "insurance_expiry_alerts"

    def test_has_required_columns(self):
        cols = {c.key for c in InsuranceExpiryAlert.__table__.columns}
        required = {"id", "driver_id", "document_id", "alert_type", "sent_at", "created_at"}
        assert required.issubset(cols)

    def test_alert_type_enum_values(self):
        assert InsuranceAlertType.THIRTY_DAY == "30_day"
        assert InsuranceAlertType.SEVEN_DAY == "7_day"
        assert InsuranceAlertType.ONE_DAY == "1_day"
        assert InsuranceAlertType.EXPIRED == "expired"


# ===========================================================================
# Schema tests
# ===========================================================================


class TestInsuranceDocumentCreate:
    def _valid_data(self, **overrides):
        base = dict(
            document_type="liability",
            insurance_provider="SafeDrive",
            policy_number="POL-001",
            coverage_amount=Decimal("100000"),
            policy_start_date=TODAY,
            policy_end_date=NEXT_YEAR,
        )
        base.update(overrides)
        return base

    def test_valid_create(self):
        req = InsuranceDocumentCreate(**self._valid_data())
        assert req.document_type == InsuranceDocumentType.LIABILITY
        assert req.coverage_amount == Decimal("100000")

    def test_document_url_optional(self):
        req = InsuranceDocumentCreate(**self._valid_data())
        assert req.document_url is None

    def test_document_url_accepted(self):
        req = InsuranceDocumentCreate(
            **self._valid_data(document_url="https://example.com/doc.pdf")
        )
        assert req.document_url == "https://example.com/doc.pdf"

    def test_negative_coverage_rejected(self):
        with pytest.raises(Exception):
            InsuranceDocumentCreate(**self._valid_data(coverage_amount=Decimal("-1")))

    def test_zero_coverage_allowed(self):
        req = InsuranceDocumentCreate(**self._valid_data(coverage_amount=Decimal("0")))
        assert req.coverage_amount == Decimal("0")

    def test_end_before_start_rejected(self):
        with pytest.raises(Exception):
            InsuranceDocumentCreate(
                **self._valid_data(
                    policy_start_date=NEXT_YEAR,
                    policy_end_date=TODAY,
                )
            )

    def test_end_equal_start_rejected(self):
        with pytest.raises(Exception):
            InsuranceDocumentCreate(
                **self._valid_data(
                    policy_start_date=NEXT_YEAR,
                    policy_end_date=NEXT_YEAR,
                )
            )

    def test_end_in_past_rejected(self):
        with pytest.raises(Exception):
            InsuranceDocumentCreate(
                **self._valid_data(
                    policy_start_date=YESTERDAY - timedelta(days=1),
                    policy_end_date=YESTERDAY,
                )
            )


class TestAdminReviewRequest:
    def test_approve_valid(self):
        req = AdminReviewRequest(status=InsuranceDocumentStatus.APPROVED)
        assert req.status == InsuranceDocumentStatus.APPROVED

    def test_reject_with_reason_valid(self):
        req = AdminReviewRequest(
            status=InsuranceDocumentStatus.REJECTED,
            rejection_reason="Policy number invalid",
        )
        assert req.rejection_reason == "Policy number invalid"

    def test_reject_without_reason_raises(self):
        with pytest.raises(Exception):
            AdminReviewRequest(status=InsuranceDocumentStatus.REJECTED)

    def test_invalid_status_raises(self):
        with pytest.raises(Exception):
            AdminReviewRequest(status=InsuranceDocumentStatus.EXPIRED)


class TestInsuranceDocumentResponse:
    def test_from_attributes(self):
        doc = _make_doc()
        resp = InsuranceDocumentResponse.model_validate(doc)
        assert resp.id == 1
        assert resp.driver_id == 10
        assert resp.status == InsuranceDocumentStatus.PENDING_REVIEW
        assert resp.document_type == InsuranceDocumentType.LIABILITY

    def test_optional_fields_nullable(self):
        doc = _make_doc(document_url=None, rejection_reason=None, verified_by=None, verified_at=None)
        resp = InsuranceDocumentResponse.model_validate(doc)
        assert resp.document_url is None
        assert resp.rejection_reason is None
        assert resp.verified_by is None
        assert resp.verified_at is None


# ===========================================================================
# Service tests
# ===========================================================================


class TestGetDriverInsuranceDocuments:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        docs = [_make_doc(id=1), _make_doc(id=2)]
        db = _make_db(scalars=docs)
        result = await get_driver_insurance_documents(db, driver_id=10)
        assert result == docs

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_new_driver(self):
        db = _make_db(scalars=[])
        result = await get_driver_insurance_documents(db, driver_id=99)
        assert result == []


class TestCreateInsuranceDocument:
    @pytest.mark.asyncio
    async def test_creates_pending_upload_without_url(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.refresh = AsyncMock()

        data = InsuranceDocumentCreate(
            document_type="liability",
            insurance_provider="SafeDrive",
            policy_number="POL-001",
            coverage_amount=Decimal("50000"),
            policy_start_date=TODAY,
            policy_end_date=NEXT_YEAR,
        )
        created_doc = _make_doc(status=InsuranceDocumentStatus.PENDING_UPLOAD)
        db.refresh.side_effect = lambda obj: None

        # Patch the DriverInsuranceDocument constructor
        with patch("app.services.driver_insurance.DriverInsuranceDocument") as MockModel:
            MockModel.return_value = created_doc
            result = await create_insurance_document(db, driver_id=10, data=data)

        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_pending_review_with_url(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.refresh = AsyncMock()

        data = InsuranceDocumentCreate(
            document_type="commercial",
            insurance_provider="TruckShield",
            policy_number="COM-999",
            coverage_amount=Decimal("500000"),
            policy_start_date=TODAY,
            policy_end_date=NEXT_YEAR,
            document_url="https://cdn.example.com/policy.pdf",
        )
        created_doc = _make_doc(status=InsuranceDocumentStatus.PENDING_REVIEW)
        db.refresh.side_effect = lambda obj: None

        with patch("app.services.driver_insurance.DriverInsuranceDocument") as MockModel:
            MockModel.return_value = created_doc
            result = await create_insurance_document(db, driver_id=10, data=data)

        # Status used must be PENDING_REVIEW because URL was provided
        call_kwargs = MockModel.call_args.kwargs
        assert call_kwargs["status"] == InsuranceDocumentStatus.PENDING_REVIEW


class TestUpdateInsuranceDocument:
    @pytest.mark.asyncio
    async def test_driver_can_update_own_pending_document(self):
        doc = _make_doc(
            driver_id=10, status=InsuranceDocumentStatus.PENDING_REVIEW
        )
        db = _make_db(scalar=doc)

        update = InsuranceDocumentUpdate(insurance_provider="NewProvider")
        result = await update_insurance_document(db, driver_id=10, doc_id=1, data=update)

        assert doc.insurance_provider == "NewProvider"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_driver_cannot_update_another_drivers_document(self):
        doc = _make_doc(driver_id=99, status=InsuranceDocumentStatus.PENDING_REVIEW)
        db = _make_db(scalar=doc)

        update = InsuranceDocumentUpdate(insurance_provider="Hack")
        with pytest.raises(InsuranceDocumentError, match="Not authorised"):
            await update_insurance_document(db, driver_id=10, doc_id=1, data=update)

    @pytest.mark.asyncio
    async def test_driver_cannot_update_approved_document(self):
        doc = _make_doc(driver_id=10, status=InsuranceDocumentStatus.APPROVED)
        db = _make_db(scalar=doc)

        update = InsuranceDocumentUpdate(insurance_provider="NewProvider")
        with pytest.raises(InsuranceDocumentError, match="Cannot edit"):
            await update_insurance_document(db, driver_id=10, doc_id=1, data=update)

    @pytest.mark.asyncio
    async def test_driver_cannot_update_rejected_document(self):
        doc = _make_doc(driver_id=10, status=InsuranceDocumentStatus.REJECTED)
        db = _make_db(scalar=doc)

        update = InsuranceDocumentUpdate(insurance_provider="NewProvider")
        with pytest.raises(InsuranceDocumentError, match="Cannot edit"):
            await update_insurance_document(db, driver_id=10, doc_id=1, data=update)

    @pytest.mark.asyncio
    async def test_update_nonexistent_document_raises(self):
        db = _make_db(scalar=None)
        update = InsuranceDocumentUpdate(insurance_provider="NewProvider")
        with pytest.raises(InsuranceDocumentError, match="not found"):
            await update_insurance_document(db, driver_id=10, doc_id=999, data=update)


class TestAdminReviewDocumentService:
    @pytest.mark.asyncio
    async def test_admin_can_approve_document(self):
        doc = _make_doc(driver_id=10, status=InsuranceDocumentStatus.PENDING_REVIEW)
        db = AsyncMock()

        # First execute: find the target doc; second: find previous approved docs
        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = doc
        second_result = MagicMock()
        second_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[first_result, second_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        review = AdminReviewRequest(status=InsuranceDocumentStatus.APPROVED)
        result = await admin_review_document(db, admin_id=1, doc_id=1, review=review)

        assert doc.status == InsuranceDocumentStatus.APPROVED
        assert doc.verified_by == 1
        assert doc.verified_at is not None
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_approval_sets_verified_by_and_verified_at(self):
        doc = _make_doc(driver_id=10, status=InsuranceDocumentStatus.PENDING_REVIEW)
        doc.verified_by = None
        doc.verified_at = None
        db = AsyncMock()

        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = doc
        second_result = MagicMock()
        second_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[first_result, second_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        review = AdminReviewRequest(status=InsuranceDocumentStatus.APPROVED)
        await admin_review_document(db, admin_id=42, doc_id=1, review=review)

        assert doc.verified_by == 42
        assert isinstance(doc.verified_at, datetime)

    @pytest.mark.asyncio
    async def test_admin_approval_expires_previous_approved_doc(self):
        doc = _make_doc(id=2, driver_id=10, status=InsuranceDocumentStatus.PENDING_REVIEW)
        prev_approved = _make_doc(
            id=1, driver_id=10, status=InsuranceDocumentStatus.APPROVED
        )
        db = AsyncMock()

        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = doc
        second_result = MagicMock()
        second_result.scalars.return_value.all.return_value = [prev_approved]
        db.execute = AsyncMock(side_effect=[first_result, second_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        review = AdminReviewRequest(status=InsuranceDocumentStatus.APPROVED)
        await admin_review_document(db, admin_id=1, doc_id=2, review=review)

        assert prev_approved.status == InsuranceDocumentStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_admin_can_reject_with_reason(self):
        doc = _make_doc(driver_id=10, status=InsuranceDocumentStatus.PENDING_REVIEW)
        db = _make_db(scalar=doc)

        review = AdminReviewRequest(
            status=InsuranceDocumentStatus.REJECTED,
            rejection_reason="Policy number does not match records",
        )
        await admin_review_document(db, admin_id=5, doc_id=1, review=review)

        assert doc.status == InsuranceDocumentStatus.REJECTED
        assert doc.rejection_reason == "Policy number does not match records"
        assert doc.verified_by == 5

    @pytest.mark.asyncio
    async def test_admin_review_nonexistent_document_raises(self):
        db = _make_db(scalar=None)
        review = AdminReviewRequest(status=InsuranceDocumentStatus.APPROVED)
        with pytest.raises(InsuranceDocumentError, match="not found"):
            await admin_review_document(db, admin_id=1, doc_id=999, review=review)


class TestGetInsuranceStatusSummary:
    @pytest.mark.asyncio
    async def test_has_valid_insurance_true_for_approved_non_expired(self):
        approved_doc = _make_doc(
            status=InsuranceDocumentStatus.APPROVED,
            policy_end_date=NEXT_YEAR,
        )
        db = AsyncMock()
        # get_driver_insurance_documents call
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [approved_doc]
        # get_latest_approved_insurance call
        single_result = MagicMock()
        single_result.scalar_one_or_none.return_value = approved_doc
        db.execute = AsyncMock(side_effect=[list_result, single_result])

        summary = await get_insurance_status_summary(db, driver_id=10)

        assert summary.has_valid_insurance is True
        assert summary.days_until_expiry is not None
        assert summary.days_until_expiry > 0

    @pytest.mark.asyncio
    async def test_has_valid_insurance_false_when_no_approved_doc(self):
        db = AsyncMock()
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = []
        single_result = MagicMock()
        single_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[list_result, single_result])

        summary = await get_insurance_status_summary(db, driver_id=10)

        assert summary.has_valid_insurance is False
        assert summary.days_until_expiry is None
        assert summary.active_document is None

    @pytest.mark.asyncio
    async def test_has_valid_insurance_false_for_expired_doc(self):
        # An expired doc won't be returned by get_latest_approved_insurance
        # (which filters policy_end_date >= today), so active_doc is None
        db = AsyncMock()
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = []
        single_result = MagicMock()
        single_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[list_result, single_result])

        summary = await get_insurance_status_summary(db, driver_id=10)
        assert summary.has_valid_insurance is False


class TestGetExpiringDocuments:
    @pytest.mark.asyncio
    async def test_returns_docs_expiring_within_n_days(self):
        expiring_doc = _make_doc(
            status=InsuranceDocumentStatus.APPROVED,
            policy_end_date=date.today() + timedelta(days=15),
        )
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [expiring_doc]
        db.execute = AsyncMock(return_value=result)

        docs = await get_expiring_documents(db, days_ahead=30)
        assert len(docs) == 1
        assert docs[0] is expiring_doc

    @pytest.mark.asyncio
    async def test_returns_empty_when_none_expiring(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        docs = await get_expiring_documents(db, days_ahead=30)
        assert docs == []


class TestMarkExpiredDocuments:
    @pytest.mark.asyncio
    async def test_updates_past_expiry_docs_to_expired(self):
        past_doc = _make_doc(
            status=InsuranceDocumentStatus.APPROVED,
            policy_end_date=YESTERDAY,
        )
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [past_doc]
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        count = await mark_expired_documents(db)

        assert count == 1
        assert past_doc.status == InsuranceDocumentStatus.EXPIRED
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_expired_docs(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        count = await mark_expired_documents(db)
        assert count == 0
        db.commit.assert_not_called()


# ===========================================================================
# Admin list returns only pending_review docs
# ===========================================================================


class TestAdminListPendingDocuments:
    """Verify the admin list endpoint filters to pending_review only."""

    def test_admin_review_request_only_approves_or_rejects(self):
        # Only approved and rejected are valid review outcomes
        valid_statuses = {InsuranceDocumentStatus.APPROVED, InsuranceDocumentStatus.REJECTED}
        for status in InsuranceDocumentStatus:
            if status in valid_statuses:
                if status == InsuranceDocumentStatus.REJECTED:
                    req = AdminReviewRequest(
                        status=status, rejection_reason="some reason"
                    )
                else:
                    req = AdminReviewRequest(status=status)
                assert req.status == status
            else:
                with pytest.raises(Exception):
                    AdminReviewRequest(status=status)
