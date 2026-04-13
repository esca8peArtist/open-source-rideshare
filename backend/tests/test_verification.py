"""Comprehensive tests for driver document verification.

Covers:
- Verification schemas (submit, review, response, status)
- Model enums and transitions
- Verification service (submit, review, get_status, auto-approve)
- Driver verification endpoints (GET status, POST submit)
- Admin verification endpoints (list, get, review, driver status, stats)
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.verification import DocumentType, DriverDocument, VerificationStatus
from app.schemas.verification import (
    DocumentResponse,
    DocumentReviewRequest,
    DocumentSubmitRequest,
    VerificationStatusResponse,
)
from app.services.verification import (
    REQUIRED_DOCUMENTS,
    VerificationError,
    _VALID_TRANSITIONS,
    get_verification_status,
    review_document,
    submit_document,
)


# ============================================================
# Schema tests
# ============================================================


class TestDocumentSubmitRequest:
    def test_basic_submission(self):
        req = DocumentSubmitRequest(
            document_type="drivers_license",
            document_ref="s3://uploads/license.pdf",
        )
        assert req.document_type == "drivers_license"
        assert req.document_ref == "s3://uploads/license.pdf"
        assert req.document_number is None
        assert req.expiry_date is None

    def test_with_all_fields(self):
        expiry = datetime(2027, 6, 15, tzinfo=timezone.utc)
        req = DocumentSubmitRequest(
            document_type="insurance",
            document_ref="s3://uploads/ins.pdf",
            document_number="INS-ABC-123",
            expiry_date=expiry,
        )
        assert req.document_number == "INS-ABC-123"
        assert req.expiry_date == expiry

    def test_vehicle_registration(self):
        req = DocumentSubmitRequest(
            document_type="vehicle_registration",
            document_ref="s3://uploads/reg.pdf",
            document_number="REG-2025-001",
        )
        assert req.document_type == "vehicle_registration"
        assert req.document_number == "REG-2025-001"

    def test_background_check(self):
        req = DocumentSubmitRequest(
            document_type="background_check",
            document_ref="checkr://report/abc123",
        )
        assert req.document_type == "background_check"

    def test_vehicle_inspection(self):
        req = DocumentSubmitRequest(
            document_type="vehicle_inspection",
            document_ref="s3://uploads/inspection.pdf",
            expiry_date=datetime(2027, 1, 1, tzinfo=timezone.utc),
        )
        assert req.document_type == "vehicle_inspection"


class TestDocumentReviewRequest:
    def test_approve(self):
        req = DocumentReviewRequest(status="approved", review_notes="All verified")
        assert req.status == "approved"
        assert req.review_notes == "All verified"
        assert req.rejection_reason is None

    def test_reject(self):
        req = DocumentReviewRequest(
            status="rejected",
            rejection_reason="Blurry image, cannot read details",
        )
        assert req.status == "rejected"
        assert req.rejection_reason == "Blurry image, cannot read details"

    def test_under_review(self):
        req = DocumentReviewRequest(status="under_review")
        assert req.status == "under_review"

    def test_reject_with_notes(self):
        req = DocumentReviewRequest(
            status="rejected",
            rejection_reason="Expired",
            review_notes="Document expired 2024-01",
        )
        assert req.rejection_reason == "Expired"
        assert req.review_notes == "Document expired 2024-01"


class TestDocumentResponse:
    def test_pending_document(self):
        now = datetime.now(timezone.utc)
        resp = DocumentResponse(
            id=1,
            driver_profile_id=10,
            document_type="drivers_license",
            status="pending",
            document_ref="s3://uploads/license.pdf",
            document_number="DL-001",
            expiry_date=None,
            reviewed_by=None,
            reviewed_at=None,
            rejection_reason=None,
            review_notes=None,
            submitted_at=now,
        )
        assert resp.id == 1
        assert resp.status == "pending"
        assert resp.reviewed_by is None

    def test_approved_document(self):
        now = datetime.now(timezone.utc)
        resp = DocumentResponse(
            id=2,
            driver_profile_id=10,
            document_type="insurance",
            status="approved",
            document_ref="s3://uploads/ins.pdf",
            document_number=None,
            expiry_date=datetime(2027, 1, 1, tzinfo=timezone.utc),
            reviewed_by=99,
            reviewed_at=now,
            rejection_reason=None,
            review_notes="Verified with issuer",
            submitted_at=now,
        )
        assert resp.status == "approved"
        assert resp.reviewed_by == 99

    def test_rejected_document(self):
        now = datetime.now(timezone.utc)
        resp = DocumentResponse(
            id=3,
            driver_profile_id=10,
            document_type="vehicle_registration",
            status="rejected",
            document_ref="s3://uploads/reg.pdf",
            document_number=None,
            expiry_date=None,
            reviewed_by=99,
            reviewed_at=now,
            rejection_reason="Document expired 6 months ago",
            review_notes=None,
            submitted_at=now,
        )
        assert resp.status == "rejected"
        assert resp.rejection_reason == "Document expired 6 months ago"

    def test_from_attributes(self):
        assert DocumentResponse.model_config["from_attributes"] is True


class TestVerificationStatusResponse:
    def test_no_documents(self):
        resp = VerificationStatusResponse(
            documents=[],
            missing_required=["drivers_license", "vehicle_registration", "insurance"],
            all_required_approved=False,
        )
        assert len(resp.documents) == 0
        assert len(resp.missing_required) == 3
        assert resp.all_required_approved is False

    def test_partial_verification(self):
        now = datetime.now(timezone.utc)
        resp = VerificationStatusResponse(
            documents=[
                DocumentResponse(
                    id=1, driver_profile_id=10, document_type="drivers_license",
                    status="approved", document_ref="s3://license.pdf",
                    document_number=None, expiry_date=None, reviewed_by=99,
                    reviewed_at=now, rejection_reason=None, review_notes=None,
                    submitted_at=now,
                ),
            ],
            missing_required=["vehicle_registration", "insurance"],
            all_required_approved=False,
        )
        assert len(resp.documents) == 1
        assert len(resp.missing_required) == 2
        assert resp.all_required_approved is False

    def test_fully_verified(self):
        now = datetime.now(timezone.utc)
        docs = []
        for dt in ["drivers_license", "vehicle_registration", "insurance"]:
            docs.append(DocumentResponse(
                id=len(docs) + 1, driver_profile_id=10, document_type=dt,
                status="approved", document_ref=f"s3://{dt}.pdf",
                document_number=None, expiry_date=None, reviewed_by=99,
                reviewed_at=now, rejection_reason=None, review_notes=None,
                submitted_at=now,
            ))
        resp = VerificationStatusResponse(
            documents=docs,
            missing_required=[],
            all_required_approved=True,
        )
        assert len(resp.documents) == 3
        assert resp.all_required_approved is True


# ============================================================
# Model / Enum tests
# ============================================================


class TestDocumentType:
    def test_all_types_exist(self):
        assert DocumentType.DRIVERS_LICENSE == "drivers_license"
        assert DocumentType.VEHICLE_REGISTRATION == "vehicle_registration"
        assert DocumentType.INSURANCE == "insurance"
        assert DocumentType.BACKGROUND_CHECK == "background_check"
        assert DocumentType.VEHICLE_INSPECTION == "vehicle_inspection"

    def test_required_documents_are_subset(self):
        for dt in REQUIRED_DOCUMENTS:
            assert dt in DocumentType

    def test_five_document_types(self):
        assert len(DocumentType) == 5


class TestVerificationStatus:
    def test_all_statuses_exist(self):
        assert VerificationStatus.PENDING == "pending"
        assert VerificationStatus.UNDER_REVIEW == "under_review"
        assert VerificationStatus.APPROVED == "approved"
        assert VerificationStatus.REJECTED == "rejected"
        assert VerificationStatus.EXPIRED == "expired"

    def test_five_statuses(self):
        assert len(VerificationStatus) == 5


class TestValidTransitions:
    def test_pending_can_go_to_under_review(self):
        assert VerificationStatus.UNDER_REVIEW in _VALID_TRANSITIONS[VerificationStatus.PENDING]

    def test_pending_can_go_to_rejected(self):
        assert VerificationStatus.REJECTED in _VALID_TRANSITIONS[VerificationStatus.PENDING]

    def test_pending_cannot_go_to_approved(self):
        assert VerificationStatus.APPROVED not in _VALID_TRANSITIONS[VerificationStatus.PENDING]

    def test_under_review_can_approve(self):
        assert VerificationStatus.APPROVED in _VALID_TRANSITIONS[VerificationStatus.UNDER_REVIEW]

    def test_under_review_can_reject(self):
        assert VerificationStatus.REJECTED in _VALID_TRANSITIONS[VerificationStatus.UNDER_REVIEW]

    def test_rejected_can_resubmit(self):
        assert VerificationStatus.PENDING in _VALID_TRANSITIONS[VerificationStatus.REJECTED]

    def test_approved_can_expire(self):
        assert VerificationStatus.EXPIRED in _VALID_TRANSITIONS[VerificationStatus.APPROVED]

    def test_expired_can_resubmit(self):
        assert VerificationStatus.PENDING in _VALID_TRANSITIONS[VerificationStatus.EXPIRED]

    def test_approved_cannot_go_back_to_under_review(self):
        assert VerificationStatus.UNDER_REVIEW not in _VALID_TRANSITIONS[VerificationStatus.APPROVED]

    def test_all_statuses_have_transitions(self):
        for status in VerificationStatus:
            assert status in _VALID_TRANSITIONS

    def test_pending_cannot_go_to_expired(self):
        assert VerificationStatus.EXPIRED not in _VALID_TRANSITIONS[VerificationStatus.PENDING]

    def test_under_review_cannot_go_to_pending(self):
        assert VerificationStatus.PENDING not in _VALID_TRANSITIONS[VerificationStatus.UNDER_REVIEW]


class TestRequiredDocuments:
    def test_three_required(self):
        assert len(REQUIRED_DOCUMENTS) == 3

    def test_license_required(self):
        assert DocumentType.DRIVERS_LICENSE in REQUIRED_DOCUMENTS

    def test_registration_required(self):
        assert DocumentType.VEHICLE_REGISTRATION in REQUIRED_DOCUMENTS

    def test_insurance_required(self):
        assert DocumentType.INSURANCE in REQUIRED_DOCUMENTS

    def test_background_check_not_required(self):
        assert DocumentType.BACKGROUND_CHECK not in REQUIRED_DOCUMENTS

    def test_vehicle_inspection_not_required(self):
        assert DocumentType.VEHICLE_INSPECTION not in REQUIRED_DOCUMENTS


# ============================================================
# Service tests (mocked DB)
# ============================================================


def _make_mock_doc(
    doc_id=1,
    driver_profile_id=10,
    doc_type=DocumentType.DRIVERS_LICENSE,
    status=VerificationStatus.PENDING,
    submitted_at=None,
):
    doc = MagicMock(spec=DriverDocument)
    doc.id = doc_id
    doc.driver_profile_id = driver_profile_id
    doc.document_type = doc_type
    doc.status = status
    doc.document_ref = f"s3://uploads/{doc_type.value}.pdf"
    doc.document_number = None
    doc.expiry_date = None
    doc.reviewed_by = None
    doc.reviewed_at = None
    doc.rejection_reason = None
    doc.review_notes = None
    doc.submitted_at = submitted_at or datetime.now(timezone.utc)
    return doc


class TestSubmitDocumentService:
    @pytest.mark.asyncio
    async def test_submit_new_document(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        doc = await submit_document(
            mock_db,
            driver_profile_id=10,
            document_type=DocumentType.DRIVERS_LICENSE,
            document_ref="s3://license.pdf",
        )
        assert doc.document_type == DocumentType.DRIVERS_LICENSE
        assert doc.status == VerificationStatus.PENDING
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_submit_duplicate_active_raises(self):
        mock_db = AsyncMock()
        existing = _make_mock_doc(status=VerificationStatus.PENDING)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        with pytest.raises(VerificationError, match="already exists"):
            await submit_document(
                mock_db,
                driver_profile_id=10,
                document_type=DocumentType.DRIVERS_LICENSE,
                document_ref="s3://new.pdf",
            )

    @pytest.mark.asyncio
    async def test_submit_after_rejection_allowed(self):
        mock_db = AsyncMock()
        # No active doc (rejected ones are excluded from the "active" query)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        doc = await submit_document(
            mock_db,
            driver_profile_id=10,
            document_type=DocumentType.DRIVERS_LICENSE,
            document_ref="s3://resubmit.pdf",
            document_number="DL-RESUBMIT",
        )
        assert doc.document_number == "DL-RESUBMIT"

    @pytest.mark.asyncio
    async def test_submit_with_expiry_date(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        expiry = datetime(2027, 12, 31, tzinfo=timezone.utc)
        doc = await submit_document(
            mock_db,
            driver_profile_id=10,
            document_type=DocumentType.INSURANCE,
            document_ref="s3://ins.pdf",
            expiry_date=expiry,
        )
        assert doc.expiry_date == expiry

    @pytest.mark.asyncio
    async def test_submit_approved_doc_blocks_duplicate(self):
        mock_db = AsyncMock()
        existing = _make_mock_doc(status=VerificationStatus.APPROVED)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        with pytest.raises(VerificationError, match="already exists"):
            await submit_document(
                mock_db,
                driver_profile_id=10,
                document_type=DocumentType.DRIVERS_LICENSE,
                document_ref="s3://dup.pdf",
            )

    @pytest.mark.asyncio
    async def test_submit_under_review_blocks_duplicate(self):
        mock_db = AsyncMock()
        existing = _make_mock_doc(status=VerificationStatus.UNDER_REVIEW)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        with pytest.raises(VerificationError, match="already exists"):
            await submit_document(
                mock_db,
                driver_profile_id=10,
                document_type=DocumentType.DRIVERS_LICENSE,
                document_ref="s3://dup2.pdf",
            )


class TestReviewDocumentService:
    @pytest.mark.asyncio
    async def test_review_pending_to_under_review(self):
        mock_db = AsyncMock()
        doc = _make_mock_doc(status=VerificationStatus.PENDING)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        mock_db.execute.return_value = mock_result

        with patch("app.services.verification._check_auto_approve", new_callable=AsyncMock):
            result = await review_document(
                mock_db,
                document_id=1,
                reviewer_id=99,
                new_status=VerificationStatus.UNDER_REVIEW,
            )
        assert result.status == VerificationStatus.UNDER_REVIEW
        assert result.reviewed_by == 99

    @pytest.mark.asyncio
    async def test_review_under_review_to_approved(self):
        mock_db = AsyncMock()
        doc = _make_mock_doc(status=VerificationStatus.UNDER_REVIEW)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        mock_db.execute.return_value = mock_result

        with patch("app.services.verification._check_auto_approve", new_callable=AsyncMock) as mock_auto:
            result = await review_document(
                mock_db,
                document_id=1,
                reviewer_id=99,
                new_status=VerificationStatus.APPROVED,
                review_notes="Looks good",
            )
        assert result.status == VerificationStatus.APPROVED
        assert result.review_notes == "Looks good"
        mock_auto.assert_awaited_once_with(mock_db, doc.driver_profile_id)

    @pytest.mark.asyncio
    async def test_review_reject_requires_reason(self):
        mock_db = AsyncMock()
        doc = _make_mock_doc(status=VerificationStatus.UNDER_REVIEW)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        mock_db.execute.return_value = mock_result

        with pytest.raises(VerificationError, match="Rejection reason is required"):
            await review_document(
                mock_db,
                document_id=1,
                reviewer_id=99,
                new_status=VerificationStatus.REJECTED,
            )

    @pytest.mark.asyncio
    async def test_review_reject_with_reason(self):
        mock_db = AsyncMock()
        doc = _make_mock_doc(status=VerificationStatus.UNDER_REVIEW)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        mock_db.execute.return_value = mock_result

        result = await review_document(
            mock_db,
            document_id=1,
            reviewer_id=99,
            new_status=VerificationStatus.REJECTED,
            rejection_reason="Blurry scan",
        )
        assert result.status == VerificationStatus.REJECTED
        assert result.rejection_reason == "Blurry scan"

    @pytest.mark.asyncio
    async def test_review_not_found(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(VerificationError, match="not found"):
            await review_document(
                mock_db,
                document_id=999,
                reviewer_id=99,
                new_status=VerificationStatus.APPROVED,
            )

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self):
        mock_db = AsyncMock()
        doc = _make_mock_doc(status=VerificationStatus.PENDING)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        mock_db.execute.return_value = mock_result

        with pytest.raises(VerificationError, match="Cannot transition"):
            await review_document(
                mock_db,
                document_id=1,
                reviewer_id=99,
                new_status=VerificationStatus.APPROVED,
            )

    @pytest.mark.asyncio
    async def test_review_sets_reviewed_at(self):
        mock_db = AsyncMock()
        doc = _make_mock_doc(status=VerificationStatus.PENDING)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        mock_db.execute.return_value = mock_result

        with patch("app.services.verification._check_auto_approve", new_callable=AsyncMock):
            result = await review_document(
                mock_db,
                document_id=1,
                reviewer_id=99,
                new_status=VerificationStatus.UNDER_REVIEW,
            )
        assert result.reviewed_at is not None


class TestGetVerificationStatusService:
    @pytest.mark.asyncio
    async def test_no_documents(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        status = await get_verification_status(mock_db, 10)
        assert status["all_required_approved"] is False
        assert len(status["missing_required"]) == 3
        assert len(status["documents"]) == 0

    @pytest.mark.asyncio
    async def test_partial_documents(self):
        mock_db = AsyncMock()
        doc1 = _make_mock_doc(
            doc_id=1,
            doc_type=DocumentType.DRIVERS_LICENSE,
            status=VerificationStatus.APPROVED,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [doc1]
        mock_db.execute.return_value = mock_result

        status = await get_verification_status(mock_db, 10)
        assert status["all_required_approved"] is False
        assert len(status["missing_required"]) == 2
        assert "vehicle_registration" in status["missing_required"]
        assert "insurance" in status["missing_required"]

    @pytest.mark.asyncio
    async def test_all_required_approved(self):
        mock_db = AsyncMock()
        now = datetime.now(timezone.utc)
        docs = [
            _make_mock_doc(doc_id=1, doc_type=DocumentType.DRIVERS_LICENSE, status=VerificationStatus.APPROVED, submitted_at=now),
            _make_mock_doc(doc_id=2, doc_type=DocumentType.VEHICLE_REGISTRATION, status=VerificationStatus.APPROVED, submitted_at=now),
            _make_mock_doc(doc_id=3, doc_type=DocumentType.INSURANCE, status=VerificationStatus.APPROVED, submitted_at=now),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = docs
        mock_db.execute.return_value = mock_result

        status = await get_verification_status(mock_db, 10)
        assert status["all_required_approved"] is True
        assert len(status["missing_required"]) == 0

    @pytest.mark.asyncio
    async def test_keeps_most_recent_per_type(self):
        mock_db = AsyncMock()
        old = _make_mock_doc(
            doc_id=1,
            doc_type=DocumentType.DRIVERS_LICENSE,
            status=VerificationStatus.REJECTED,
            submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        new = _make_mock_doc(
            doc_id=2,
            doc_type=DocumentType.DRIVERS_LICENSE,
            status=VerificationStatus.APPROVED,
            submitted_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [old, new]
        mock_db.execute.return_value = mock_result

        status = await get_verification_status(mock_db, 10)
        # Should keep the newer doc
        doc_list = status["documents"]
        assert len(doc_list) == 1
        assert doc_list[0].id == 2

    @pytest.mark.asyncio
    async def test_pending_not_counted_as_approved(self):
        mock_db = AsyncMock()
        now = datetime.now(timezone.utc)
        docs = [
            _make_mock_doc(doc_id=1, doc_type=DocumentType.DRIVERS_LICENSE, status=VerificationStatus.APPROVED, submitted_at=now),
            _make_mock_doc(doc_id=2, doc_type=DocumentType.VEHICLE_REGISTRATION, status=VerificationStatus.PENDING, submitted_at=now),
            _make_mock_doc(doc_id=3, doc_type=DocumentType.INSURANCE, status=VerificationStatus.APPROVED, submitted_at=now),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = docs
        mock_db.execute.return_value = mock_result

        status = await get_verification_status(mock_db, 10)
        assert status["all_required_approved"] is False


# ============================================================
# Driver verification endpoint tests
# ============================================================


class TestDriverVerificationEndpoints:
    @pytest.mark.asyncio
    async def test_get_verification_no_profile(self, client, driver_token):
        """Driver with no profile gets 404."""
        from tests.conftest import auth_header
        resp = await client.get("/api/v1/driver/verification", headers=auth_header(driver_token))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_verification_empty(self, client, driver_user, driver_profile, driver_token):
        """Driver with profile but no documents sees all missing."""
        from tests.conftest import auth_header
        resp = await client.get("/api/v1/driver/verification", headers=auth_header(driver_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["all_required_approved"] is False
        assert len(data["missing_required"]) == 3
        assert len(data["documents"]) == 0

    @pytest.mark.asyncio
    async def test_submit_document_no_profile(self, client, driver_token):
        """Submit without profile gets 404."""
        from tests.conftest import auth_header
        resp = await client.post(
            "/api/v1/driver/verification/documents",
            json={"document_type": "drivers_license", "document_ref": "s3://test.pdf"},
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_submit_document_success(self, client, driver_user, driver_profile, driver_token, db):
        """Submit a valid document returns 201."""
        from tests.conftest import auth_header
        resp = await client.post(
            "/api/v1/driver/verification/documents",
            json={
                "document_type": "drivers_license",
                "document_ref": "s3://uploads/license.pdf",
                "document_number": "DL-001",
            },
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["document_type"] == "drivers_license"
        assert data["status"] == "pending"
        assert data["document_ref"] == "s3://uploads/license.pdf"
        assert data["document_number"] == "DL-001"

    @pytest.mark.asyncio
    async def test_submit_invalid_document_type(self, client, driver_user, driver_profile, driver_token):
        """Invalid document type returns 422."""
        from tests.conftest import auth_header
        resp = await client.post(
            "/api/v1/driver/verification/documents",
            json={"document_type": "invalid_type", "document_ref": "s3://test.pdf"},
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_submit_duplicate_document(self, client, driver_user, driver_profile, driver_token, db):
        """Submitting same document type twice returns 409."""
        from tests.conftest import auth_header
        payload = {"document_type": "insurance", "document_ref": "s3://ins.pdf"}
        resp1 = await client.post(
            "/api/v1/driver/verification/documents",
            json=payload,
            headers=auth_header(driver_token),
        )
        assert resp1.status_code == 201

        resp2 = await client.post(
            "/api/v1/driver/verification/documents",
            json=payload,
            headers=auth_header(driver_token),
        )
        assert resp2.status_code == 409

    @pytest.mark.asyncio
    async def test_rider_cannot_access_driver_verification(self, client, rider_token):
        """Riders should get 403 on driver endpoints."""
        from tests.conftest import auth_header
        resp = await client.get("/api/v1/driver/verification", headers=auth_header(rider_token))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_unauthenticated_cannot_access(self, client):
        """No token gets 403."""
        resp = await client.get("/api/v1/driver/verification")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_submit_and_check_verification_status(self, client, driver_user, driver_profile, driver_token, db):
        """Submit a document then check it appears in verification status."""
        from tests.conftest import auth_header
        headers = auth_header(driver_token)

        # Submit
        resp = await client.post(
            "/api/v1/driver/verification/documents",
            json={"document_type": "vehicle_registration", "document_ref": "s3://reg.pdf"},
            headers=headers,
        )
        assert resp.status_code == 201

        # Check status
        resp = await client.get("/api/v1/driver/verification", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["documents"]) == 1
        assert data["documents"][0]["document_type"] == "vehicle_registration"
        assert "vehicle_registration" not in data["missing_required"]


# ============================================================
# Admin verification endpoint tests
# ============================================================


class TestAdminDocumentList:
    @pytest.mark.asyncio
    async def test_list_empty(self, client, admin_token):
        """List documents when none exist."""
        from tests.conftest import auth_header
        resp = await client.get(
            "/api/v1/admin/verification/documents",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["documents"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["per_page"] == 20

    @pytest.mark.asyncio
    async def test_list_with_documents(self, client, admin_token, driver_user, driver_profile, driver_token, db):
        """List returns submitted documents."""
        from tests.conftest import auth_header

        # Submit a document as driver
        await client.post(
            "/api/v1/driver/verification/documents",
            json={"document_type": "drivers_license", "document_ref": "s3://license.pdf"},
            headers=auth_header(driver_token),
        )

        # List as admin
        resp = await client.get(
            "/api/v1/admin/verification/documents",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any(d["document_type"] == "drivers_license" for d in data["documents"])

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self, client, admin_token, driver_user, driver_profile, driver_token, db):
        """Filter by status=pending."""
        from tests.conftest import auth_header

        await client.post(
            "/api/v1/driver/verification/documents",
            json={"document_type": "insurance", "document_ref": "s3://ins.pdf"},
            headers=auth_header(driver_token),
        )

        resp = await client.get(
            "/api/v1/admin/verification/documents?status=pending",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        for doc in data["documents"]:
            assert doc["status"] == "pending"

    @pytest.mark.asyncio
    async def test_list_filter_by_document_type(self, client, admin_token, driver_user, driver_profile, driver_token, db):
        """Filter by document_type."""
        from tests.conftest import auth_header

        await client.post(
            "/api/v1/driver/verification/documents",
            json={"document_type": "vehicle_registration", "document_ref": "s3://reg.pdf"},
            headers=auth_header(driver_token),
        )

        resp = await client.get(
            "/api/v1/admin/verification/documents?document_type=vehicle_registration",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        for doc in resp.json()["documents"]:
            assert doc["document_type"] == "vehicle_registration"

    @pytest.mark.asyncio
    async def test_list_pagination(self, client, admin_token):
        """Pagination parameters are respected."""
        from tests.conftest import auth_header
        resp = await client.get(
            "/api/v1/admin/verification/documents?page=2&per_page=5",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["per_page"] == 5

    @pytest.mark.asyncio
    async def test_non_admin_cannot_list(self, client, driver_token):
        """Drivers cannot access admin endpoints."""
        from tests.conftest import auth_header
        resp = await client.get(
            "/api/v1/admin/verification/documents",
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_rider_cannot_list(self, client, rider_token):
        """Riders cannot access admin endpoints."""
        from tests.conftest import auth_header
        resp = await client.get(
            "/api/v1/admin/verification/documents",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403


class TestAdminGetDocument:
    @pytest.mark.asyncio
    async def test_get_existing_document(self, client, admin_token, driver_user, driver_profile, driver_token, db):
        """Get a single document by ID."""
        from tests.conftest import auth_header

        create_resp = await client.post(
            "/api/v1/driver/verification/documents",
            json={"document_type": "drivers_license", "document_ref": "s3://lic.pdf", "document_number": "DL-GET"},
            headers=auth_header(driver_token),
        )
        doc_id = create_resp.json()["id"]

        resp = await client.get(
            f"/api/v1/admin/verification/documents/{doc_id}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == doc_id
        assert data["document_number"] == "DL-GET"
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_nonexistent_document(self, client, admin_token):
        """Non-existent document returns 404."""
        from tests.conftest import auth_header
        resp = await client.get(
            "/api/v1/admin/verification/documents/99999",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404


class TestAdminReviewDocument:
    @pytest.mark.asyncio
    async def test_mark_under_review(self, client, admin_token, driver_user, driver_profile, driver_token, db):
        """Admin marks pending document as under_review."""
        from tests.conftest import auth_header

        create_resp = await client.post(
            "/api/v1/driver/verification/documents",
            json={"document_type": "drivers_license", "document_ref": "s3://lic.pdf"},
            headers=auth_header(driver_token),
        )
        doc_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/admin/verification/documents/{doc_id}/review",
            json={"status": "under_review"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "under_review"

    @pytest.mark.asyncio
    async def test_approve_after_review(self, client, admin_token, driver_user, driver_profile, driver_token, db):
        """Full flow: submit → under_review → approved."""
        from tests.conftest import auth_header

        # Submit
        create_resp = await client.post(
            "/api/v1/driver/verification/documents",
            json={"document_type": "insurance", "document_ref": "s3://ins.pdf"},
            headers=auth_header(driver_token),
        )
        doc_id = create_resp.json()["id"]

        # Mark under review
        await client.post(
            f"/api/v1/admin/verification/documents/{doc_id}/review",
            json={"status": "under_review"},
            headers=auth_header(admin_token),
        )

        # Approve
        resp = await client.post(
            f"/api/v1/admin/verification/documents/{doc_id}/review",
            json={"status": "approved", "review_notes": "Verified"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["review_notes"] == "Verified"
        assert data["reviewed_by"] is not None

    @pytest.mark.asyncio
    async def test_reject_requires_reason(self, client, admin_token, driver_user, driver_profile, driver_token, db):
        """Rejecting without reason returns 409."""
        from tests.conftest import auth_header

        create_resp = await client.post(
            "/api/v1/driver/verification/documents",
            json={"document_type": "vehicle_registration", "document_ref": "s3://reg.pdf"},
            headers=auth_header(driver_token),
        )
        doc_id = create_resp.json()["id"]

        # Mark under review first
        await client.post(
            f"/api/v1/admin/verification/documents/{doc_id}/review",
            json={"status": "under_review"},
            headers=auth_header(admin_token),
        )

        # Try reject without reason
        resp = await client.post(
            f"/api/v1/admin/verification/documents/{doc_id}/review",
            json={"status": "rejected"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_reject_with_reason(self, client, admin_token, driver_user, driver_profile, driver_token, db):
        """Rejecting with reason succeeds."""
        from tests.conftest import auth_header

        create_resp = await client.post(
            "/api/v1/driver/verification/documents",
            json={"document_type": "drivers_license", "document_ref": "s3://bad-lic.pdf"},
            headers=auth_header(driver_token),
        )
        doc_id = create_resp.json()["id"]

        # under_review
        await client.post(
            f"/api/v1/admin/verification/documents/{doc_id}/review",
            json={"status": "under_review"},
            headers=auth_header(admin_token),
        )

        resp = await client.post(
            f"/api/v1/admin/verification/documents/{doc_id}/review",
            json={"status": "rejected", "rejection_reason": "Blurry photo"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["rejection_reason"] == "Blurry photo"

    @pytest.mark.asyncio
    async def test_invalid_transition_returns_409(self, client, admin_token, driver_user, driver_profile, driver_token, db):
        """Invalid state transition returns 409."""
        from tests.conftest import auth_header

        create_resp = await client.post(
            "/api/v1/driver/verification/documents",
            json={"document_type": "insurance", "document_ref": "s3://ins2.pdf"},
            headers=auth_header(driver_token),
        )
        doc_id = create_resp.json()["id"]

        # Try to approve directly from pending (must go through under_review)
        resp = await client.post(
            f"/api/v1/admin/verification/documents/{doc_id}/review",
            json={"status": "approved"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_review_nonexistent_document(self, client, admin_token):
        """Review non-existent document returns 404."""
        from tests.conftest import auth_header
        resp = await client.post(
            "/api/v1/admin/verification/documents/99999/review",
            json={"status": "under_review"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_non_admin_cannot_review(self, client, driver_token):
        """Drivers cannot review documents."""
        from tests.conftest import auth_header
        resp = await client.post(
            "/api/v1/admin/verification/documents/1/review",
            json={"status": "under_review"},
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 403


class TestAdminDriverVerificationStatus:
    @pytest.mark.asyncio
    async def test_get_driver_status(self, client, admin_token, driver_user, driver_profile):
        """Get verification status for a specific driver."""
        from tests.conftest import auth_header
        resp = await client.get(
            f"/api/v1/admin/verification/drivers/{driver_profile.id}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["all_required_approved"] is False
        assert len(data["missing_required"]) == 3

    @pytest.mark.asyncio
    async def test_get_nonexistent_driver(self, client, admin_token):
        """Non-existent driver profile returns 404."""
        from tests.conftest import auth_header
        resp = await client.get(
            "/api/v1/admin/verification/drivers/99999",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_driver_status_reflects_submissions(self, client, admin_token, driver_user, driver_profile, driver_token, db):
        """Status updates as documents are submitted."""
        from tests.conftest import auth_header

        # Submit one document
        await client.post(
            "/api/v1/driver/verification/documents",
            json={"document_type": "drivers_license", "document_ref": "s3://lic.pdf"},
            headers=auth_header(driver_token),
        )

        resp = await client.get(
            f"/api/v1/admin/verification/drivers/{driver_profile.id}",
            headers=auth_header(admin_token),
        )
        data = resp.json()
        assert len(data["documents"]) == 1
        assert len(data["missing_required"]) == 2


class TestAdminVerificationStats:
    @pytest.mark.asyncio
    async def test_stats_empty(self, client, admin_token):
        """Stats when no documents exist."""
        from tests.conftest import auth_header
        resp = await client.get(
            "/api/v1/admin/verification/stats",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_documents"] == 0
        assert data["pending_review"] == 0
        assert isinstance(data["by_status"], dict)
        assert isinstance(data["by_type"], dict)

    @pytest.mark.asyncio
    async def test_stats_with_documents(self, client, admin_token, driver_user, driver_profile, driver_token, db):
        """Stats reflect submitted documents."""
        from tests.conftest import auth_header

        await client.post(
            "/api/v1/driver/verification/documents",
            json={"document_type": "drivers_license", "document_ref": "s3://lic.pdf"},
            headers=auth_header(driver_token),
        )
        await client.post(
            "/api/v1/driver/verification/documents",
            json={"document_type": "insurance", "document_ref": "s3://ins.pdf"},
            headers=auth_header(driver_token),
        )

        resp = await client.get(
            "/api/v1/admin/verification/stats",
            headers=auth_header(admin_token),
        )
        data = resp.json()
        assert data["total_documents"] >= 2
        assert data["pending_review"] >= 2

    @pytest.mark.asyncio
    async def test_stats_non_admin_blocked(self, client, rider_token):
        """Non-admins cannot access stats."""
        from tests.conftest import auth_header
        resp = await client.get(
            "/api/v1/admin/verification/stats",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_stats_includes_driver_counts(self, client, admin_token, driver_user, driver_profile):
        """Stats include total and approved driver counts."""
        from tests.conftest import auth_header
        resp = await client.get(
            "/api/v1/admin/verification/stats",
            headers=auth_header(admin_token),
        )
        data = resp.json()
        assert "total_drivers" in data
        assert "approved_drivers" in data
        assert data["total_drivers"] >= 1
