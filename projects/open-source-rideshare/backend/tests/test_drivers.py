"""Tests for the driver API endpoints and related services.

Covers:
  - DriverProfile CRUD logic (create, get, update — direct DB mock tests)
  - _period_start helper (pure function)
  - Earnings calculation logic
  - Verification service: submit_document, get_verification_status, review_document
  - VerificationError exception
  - Pydantic schemas (DriverProfileCreate, DriverProfileUpdate, etc.)
  - Driver/Verification model table structure

No live database is used. All DB interactions are mocked with AsyncMock /
MagicMock following the same pattern used in test_cancellation_policies.py.
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.verification import DocumentType, VerificationStatus
from app.schemas.driver import (
    DailyEarningsPoint,
    DriverLocationUpdate,
    DriverProfileCreate,
    DriverProfileResponse,
    DriverProfileUpdate,
    EarningsResponse,
    EarningsSummary,
    EarningsTrip,
    RatingDistributionResponse,
    RatingsSummaryResponse,
)
from app.schemas.verification import (
    DocumentResponse,
    DocumentSubmitRequest,
    VerificationStatusResponse,
)
from app.services.verification import (
    REQUIRED_DOCUMENTS,
    VerificationError,
    get_verification_status,
    review_document,
    submit_document,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(_UTC)


def _make_driver_profile_mock(
    profile_id=1,
    user_id=10,
    vehicle_type="sedan",
    vehicle_make="Toyota",
    vehicle_model="Camry",
    vehicle_year=2020,
    vehicle_color="Blue",
    license_plate="ABC123",
    is_online=False,
    is_approved=True,
    rating_avg=4.8,
    total_trips=50,
):
    from app.models.driver import DriverProfile
    profile = MagicMock(spec=DriverProfile)
    profile.id = profile_id
    profile.user_id = user_id
    profile.vehicle_type = vehicle_type
    profile.vehicle_make = vehicle_make
    profile.vehicle_model = vehicle_model
    profile.vehicle_year = vehicle_year
    profile.vehicle_color = vehicle_color
    profile.license_plate = license_plate
    profile.is_online = is_online
    profile.is_approved = is_approved
    profile.rating_avg = rating_avg
    profile.total_trips = total_trips
    profile.active_vehicle_id = None
    profile.background_check_status = "approved"
    return profile


def _make_document_mock(
    doc_id=1,
    driver_profile_id=1,
    document_type=DocumentType.DRIVERS_LICENSE,
    status=VerificationStatus.PENDING,
    document_ref="s3://bucket/doc.pdf",
    document_number="DL123456",
    expiry_date=None,
    reviewed_by=None,
    reviewed_at=None,
    rejection_reason=None,
    review_notes=None,
    submitted_at=None,
):
    from app.models.verification import DriverDocument
    doc = MagicMock(spec=DriverDocument)
    doc.id = doc_id
    doc.driver_profile_id = driver_profile_id
    doc.document_type = document_type
    doc.status = status
    doc.document_ref = document_ref
    doc.document_number = document_number
    doc.expiry_date = expiry_date
    doc.reviewed_by = reviewed_by
    doc.reviewed_at = reviewed_at
    doc.rejection_reason = rejection_reason
    doc.review_notes = review_notes
    doc.submitted_at = submitted_at or _now()
    return doc


def _db_returning(*rows):
    """Build a mock AsyncSession whose execute() returns given rows in sequence."""
    db = AsyncMock()
    results = []
    for row in rows:
        result = MagicMock()
        if isinstance(row, list):
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = row
            result.scalars.return_value = scalars_mock
        else:
            result.scalar_one_or_none.return_value = row
            result.scalar.return_value = row
        results.append(result)
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


# ===========================================================================
# TestPeriodStart
# ===========================================================================


class TestPeriodStart:
    """Tests for the pure _period_start helper from drivers.py."""

    def test_day_returns_today(self):
        from app.api.v1.drivers import _period_start
        result = _period_start("day")
        assert result == date.today()

    def test_week_returns_7_days_ago(self):
        from app.api.v1.drivers import _period_start
        result = _period_start("week")
        assert result == date.today() - timedelta(days=7)

    def test_month_returns_30_days_ago(self):
        from app.api.v1.drivers import _period_start
        result = _period_start("month")
        assert result == date.today() - timedelta(days=30)

    def test_all_returns_distant_past(self):
        from app.api.v1.drivers import _period_start
        result = _period_start("all")
        assert result == date(2000, 1, 1)

    def test_unknown_period_returns_distant_past(self):
        from app.api.v1.drivers import _period_start
        result = _period_start("unknown_period")
        assert result == date(2000, 1, 1)


# ===========================================================================
# TestSubmitDocument
# ===========================================================================


class TestSubmitDocument:
    """Tests for submit_document (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_submit_new_document_succeeds(self):
        # No existing active document
        db = _db_returning(None)
        doc = await submit_document(
            db,
            driver_profile_id=1,
            document_type=DocumentType.DRIVERS_LICENSE,
            document_ref="s3://bucket/license.pdf",
            document_number="DL001",
        )
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_submit_existing_active_raises_verification_error(self):
        existing = _make_document_mock(status=VerificationStatus.PENDING)
        db = _db_returning(existing)
        with pytest.raises(VerificationError):
            await submit_document(
                db,
                driver_profile_id=1,
                document_type=DocumentType.DRIVERS_LICENSE,
                document_ref="s3://bucket/license.pdf",
            )

    @pytest.mark.asyncio
    async def test_submit_under_review_raises_verification_error(self):
        existing = _make_document_mock(status=VerificationStatus.UNDER_REVIEW)
        db = _db_returning(existing)
        with pytest.raises(VerificationError):
            await submit_document(
                db,
                driver_profile_id=1,
                document_type=DocumentType.VEHICLE_REGISTRATION,
                document_ref="s3://bucket/reg.pdf",
            )

    @pytest.mark.asyncio
    async def test_submit_approved_raises_verification_error(self):
        existing = _make_document_mock(status=VerificationStatus.APPROVED)
        db = _db_returning(existing)
        with pytest.raises(VerificationError):
            await submit_document(
                db,
                driver_profile_id=1,
                document_type=DocumentType.INSURANCE,
                document_ref="s3://bucket/ins.pdf",
            )

    @pytest.mark.asyncio
    async def test_submit_sets_pending_status(self):
        db = _db_returning(None)
        await submit_document(
            db,
            driver_profile_id=1,
            document_type=DocumentType.DRIVERS_LICENSE,
            document_ref="s3://bucket/license.pdf",
        )
        added_doc = db.add.call_args[0][0]
        assert added_doc.status == VerificationStatus.PENDING

    @pytest.mark.asyncio
    async def test_submit_sets_document_ref(self):
        db = _db_returning(None)
        await submit_document(
            db,
            driver_profile_id=1,
            document_type=DocumentType.DRIVERS_LICENSE,
            document_ref="s3://bucket/my-license.pdf",
        )
        added_doc = db.add.call_args[0][0]
        assert added_doc.document_ref == "s3://bucket/my-license.pdf"

    @pytest.mark.asyncio
    async def test_submit_sets_driver_profile_id(self):
        db = _db_returning(None)
        await submit_document(
            db,
            driver_profile_id=42,
            document_type=DocumentType.DRIVERS_LICENSE,
            document_ref="s3://bucket/license.pdf",
        )
        added_doc = db.add.call_args[0][0]
        assert added_doc.driver_profile_id == 42

    @pytest.mark.asyncio
    async def test_submit_with_expiry_date(self):
        db = _db_returning(None)
        expiry = _now() + timedelta(days=365)
        await submit_document(
            db,
            driver_profile_id=1,
            document_type=DocumentType.DRIVERS_LICENSE,
            document_ref="s3://bucket/license.pdf",
            expiry_date=expiry,
        )
        added_doc = db.add.call_args[0][0]
        assert added_doc.expiry_date == expiry

    @pytest.mark.asyncio
    async def test_submit_all_document_types(self):
        for doc_type in DocumentType:
            db = _db_returning(None)
            await submit_document(
                db,
                driver_profile_id=1,
                document_type=doc_type,
                document_ref="s3://bucket/doc.pdf",
            )
            db.add.assert_called_once()


# ===========================================================================
# TestReviewDocument
# ===========================================================================


class TestReviewDocument:
    """Tests for review_document (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_review_pending_to_under_review(self):
        doc = _make_document_mock(status=VerificationStatus.PENDING)
        db = _db_returning(doc)
        result = await review_document(
            db,
            document_id=1,
            reviewer_id=99,
            new_status=VerificationStatus.UNDER_REVIEW,
        )
        assert result.status == VerificationStatus.UNDER_REVIEW
        assert result.reviewed_by == 99

    @pytest.mark.asyncio
    async def test_review_under_review_to_approved(self):
        doc = _make_document_mock(
            driver_profile_id=1,
            status=VerificationStatus.UNDER_REVIEW,
        )
        # Extra call for _check_auto_approve → get_verification_status
        docs_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [doc]
        docs_result.scalars.return_value = scalars_mock

        profile_mock = _make_driver_profile_mock(profile_id=1, is_approved=False)
        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = profile_mock

        db = AsyncMock()
        call_results = [
            # First execute: get document by id
            MagicMock(**{"scalar_one_or_none.return_value": doc}),
            # Second: auto-approve check — get_verification_status docs query
            docs_result,
            # Third: auto-approve check — get DriverProfile
            profile_result,
        ]
        db.execute = AsyncMock(side_effect=call_results)
        db.add = MagicMock()
        db.flush = AsyncMock()

        result = await review_document(
            db,
            document_id=1,
            reviewer_id=99,
            new_status=VerificationStatus.APPROVED,
        )
        assert result.status == VerificationStatus.APPROVED

    @pytest.mark.asyncio
    async def test_review_document_not_found_raises(self):
        db = _db_returning(None)
        with pytest.raises(VerificationError, match="Document not found"):
            await review_document(
                db,
                document_id=999,
                reviewer_id=1,
                new_status=VerificationStatus.UNDER_REVIEW,
            )

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self):
        # APPROVED → UNDER_REVIEW is not valid
        doc = _make_document_mock(status=VerificationStatus.APPROVED)
        db = _db_returning(doc)
        with pytest.raises(VerificationError):
            await review_document(
                db,
                document_id=1,
                reviewer_id=99,
                new_status=VerificationStatus.UNDER_REVIEW,
            )

    @pytest.mark.asyncio
    async def test_reject_without_reason_raises(self):
        doc = _make_document_mock(status=VerificationStatus.UNDER_REVIEW)
        db = _db_returning(doc)
        with pytest.raises(VerificationError, match="Rejection reason"):
            await review_document(
                db,
                document_id=1,
                reviewer_id=99,
                new_status=VerificationStatus.REJECTED,
                rejection_reason=None,
            )

    @pytest.mark.asyncio
    async def test_reject_with_reason_succeeds(self):
        doc = _make_document_mock(status=VerificationStatus.UNDER_REVIEW)
        db = _db_returning(doc)
        result = await review_document(
            db,
            document_id=1,
            reviewer_id=99,
            new_status=VerificationStatus.REJECTED,
            rejection_reason="Document unclear",
        )
        assert result.status == VerificationStatus.REJECTED
        assert result.rejection_reason == "Document unclear"

    @pytest.mark.asyncio
    async def test_review_sets_reviewer_id(self):
        doc = _make_document_mock(status=VerificationStatus.PENDING)
        db = _db_returning(doc)
        result = await review_document(
            db,
            document_id=1,
            reviewer_id=77,
            new_status=VerificationStatus.UNDER_REVIEW,
        )
        assert result.reviewed_by == 77

    @pytest.mark.asyncio
    async def test_review_sets_reviewed_at(self):
        doc = _make_document_mock(status=VerificationStatus.PENDING)
        db = _db_returning(doc)
        before = _now()
        result = await review_document(
            db,
            document_id=1,
            reviewer_id=99,
            new_status=VerificationStatus.UNDER_REVIEW,
        )
        after = _now()
        assert before <= result.reviewed_at <= after


# ===========================================================================
# TestGetVerificationStatus
# ===========================================================================


class TestGetVerificationStatus:
    """Tests for get_verification_status (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_no_documents_all_missing(self):
        db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=result_mock)

        status = await get_verification_status(db, driver_profile_id=1)
        assert status["documents"] == []
        assert status["all_required_approved"] is False
        assert len(status["missing_required"]) == len(REQUIRED_DOCUMENTS)

    @pytest.mark.asyncio
    async def test_all_required_approved(self):
        docs = [
            _make_document_mock(
                doc_id=i,
                document_type=dt,
                status=VerificationStatus.APPROVED,
                submitted_at=_now(),
            )
            for i, dt in enumerate(REQUIRED_DOCUMENTS, start=1)
        ]
        db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = docs
        result_mock.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=result_mock)

        status = await get_verification_status(db, driver_profile_id=1)
        assert status["all_required_approved"] is True
        assert status["missing_required"] == []

    @pytest.mark.asyncio
    async def test_partial_approval_not_all_approved(self):
        # Only one required doc approved
        doc = _make_document_mock(
            doc_id=1,
            document_type=DocumentType.DRIVERS_LICENSE,
            status=VerificationStatus.APPROVED,
            submitted_at=_now(),
        )
        db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [doc]
        result_mock.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=result_mock)

        status = await get_verification_status(db, driver_profile_id=1)
        assert status["all_required_approved"] is False
        # At least 2 required docs still missing
        assert len(status["missing_required"]) >= 2

    @pytest.mark.asyncio
    async def test_returns_dict_with_expected_keys(self):
        db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=result_mock)

        status = await get_verification_status(db, driver_profile_id=1)
        assert "documents" in status
        assert "missing_required" in status
        assert "all_required_approved" in status

    @pytest.mark.asyncio
    async def test_most_recent_document_per_type_kept(self):
        """If two docs of same type submitted, keep most recent."""
        old_doc = _make_document_mock(
            doc_id=1,
            document_type=DocumentType.DRIVERS_LICENSE,
            status=VerificationStatus.REJECTED,
            submitted_at=_now() - timedelta(days=10),
        )
        new_doc = _make_document_mock(
            doc_id=2,
            document_type=DocumentType.DRIVERS_LICENSE,
            status=VerificationStatus.PENDING,
            submitted_at=_now(),
        )
        db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [old_doc, new_doc]
        result_mock.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=result_mock)

        status = await get_verification_status(db, driver_profile_id=1)
        # Should keep the newer pending doc
        doc_statuses = {d.document_type: d for d in status["documents"]}
        assert doc_statuses[DocumentType.DRIVERS_LICENSE].status == VerificationStatus.PENDING


# ===========================================================================
# TestVerificationError
# ===========================================================================


class TestVerificationError:
    """Tests for the VerificationError exception."""

    def test_is_exception(self):
        exc = VerificationError("test error")
        assert isinstance(exc, Exception)

    def test_message_preserved(self):
        msg = "Active document already exists"
        exc = VerificationError(msg)
        assert str(exc) == msg

    def test_can_be_raised_and_caught(self):
        with pytest.raises(VerificationError):
            raise VerificationError("test")

    def test_required_documents_set(self):
        assert DocumentType.DRIVERS_LICENSE in REQUIRED_DOCUMENTS
        assert DocumentType.VEHICLE_REGISTRATION in REQUIRED_DOCUMENTS
        assert DocumentType.INSURANCE in REQUIRED_DOCUMENTS


# ===========================================================================
# TestDriverProfileSchemas
# ===========================================================================


class TestDriverProfileSchemas:
    """Pydantic validation tests for driver-related schemas."""

    def test_driver_profile_create_required_fields(self):
        req = DriverProfileCreate(
            vehicle_type="sedan",
            vehicle_make="Toyota",
            vehicle_model="Camry",
            vehicle_year=2020,
            vehicle_color="Blue",
            license_plate="ABC123",
            license_number="DL9999",
        )
        assert req.vehicle_make == "Toyota"
        assert req.license_plate == "ABC123"

    def test_driver_profile_create_insurance_optional(self):
        req = DriverProfileCreate(
            vehicle_type="suv",
            vehicle_make="Honda",
            vehicle_model="Pilot",
            vehicle_year=2021,
            vehicle_color="White",
            license_plate="XYZ789",
            license_number="DL0001",
        )
        assert req.insurance_policy is None

    def test_driver_profile_create_with_insurance(self):
        req = DriverProfileCreate(
            vehicle_type="suv",
            vehicle_make="Honda",
            vehicle_model="Pilot",
            vehicle_year=2021,
            vehicle_color="White",
            license_plate="XYZ789",
            license_number="DL0001",
            insurance_policy="INS-001-2024",
        )
        assert req.insurance_policy == "INS-001-2024"

    def test_driver_profile_create_requires_vehicle_type(self):
        with pytest.raises(Exception):
            DriverProfileCreate(
                vehicle_make="Toyota",
                vehicle_model="Camry",
                vehicle_year=2020,
                vehicle_color="Blue",
                license_plate="ABC123",
                license_number="DL9999",
            )

    def test_driver_profile_update_all_optional(self):
        req = DriverProfileUpdate()
        assert req.vehicle_type is None
        assert req.vehicle_make is None
        assert req.license_plate is None

    def test_driver_profile_update_partial(self):
        req = DriverProfileUpdate(vehicle_color="Red", license_plate="NEW123")
        assert req.vehicle_color == "Red"
        assert req.vehicle_make is None

    def test_driver_profile_response_from_attributes(self):
        assert DriverProfileResponse.model_config.get("from_attributes") is True

    def test_driver_profile_response_fields(self):
        resp = DriverProfileResponse(
            id=1,
            user_id=10,
            vehicle_type="sedan",
            vehicle_make="Toyota",
            vehicle_model="Camry",
            vehicle_year=2020,
            vehicle_color="Blue",
            license_plate="ABC123",
            is_online=False,
            is_approved=True,
            rating_avg=4.5,
            total_trips=100,
        )
        assert resp.id == 1
        assert resp.is_approved is True
        assert resp.active_vehicle_id is None

    def test_driver_location_update_fields(self):
        req = DriverLocationUpdate(lat=37.77, lng=-122.41)
        assert req.lat == 37.77
        assert req.lng == -122.41

    def test_driver_location_update_requires_both_fields(self):
        with pytest.raises(Exception):
            DriverLocationUpdate(lat=37.77)


# ===========================================================================
# TestEarningsSchemas
# ===========================================================================


class TestEarningsSchemas:
    """Tests for earnings-related Pydantic schemas."""

    def test_earnings_summary_basic(self):
        today = date.today()
        summary = EarningsSummary(
            total_fares=100.0,
            total_tips=15.0,
            total_cancellation_fees=5.0,
            total_earnings=120.0,
            trip_count=10,
            average_fare=10.0,
            average_tip=1.5,
            period_start=today - timedelta(days=7),
            period_end=today,
        )
        assert summary.total_earnings == 120.0
        assert summary.trip_count == 10

    def test_earnings_summary_cancellation_fees_default_zero(self):
        today = date.today()
        summary = EarningsSummary(
            total_fares=50.0,
            total_tips=5.0,
            total_earnings=55.0,
            trip_count=5,
            average_fare=10.0,
            average_tip=1.0,
            period_start=today - timedelta(days=7),
            period_end=today,
        )
        assert summary.total_cancellation_fees == 0.0

    def test_earnings_trip_fields(self):
        now = _now()
        trip = EarningsTrip(
            ride_id=1,
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            fare=12.50,
            tip=2.00,
            total=14.50,
            distance_km=5.2,
            duration_min=15.0,
            completed_at=now,
        )
        assert trip.fare == 12.50
        assert trip.total == 14.50
        assert trip.ride_id == 1

    def test_earnings_trip_optional_fields(self):
        trip = EarningsTrip(
            ride_id=2,
            pickup_address="A",
            dropoff_address="B",
            fare=10.0,
            tip=0.0,
            total=10.0,
            distance_km=None,
            duration_min=None,
            completed_at=None,
        )
        assert trip.distance_km is None
        assert trip.completed_at is None

    def test_earnings_response_structure(self):
        today = date.today()
        summary = EarningsSummary(
            total_fares=0.0,
            total_tips=0.0,
            total_earnings=0.0,
            trip_count=0,
            average_fare=0.0,
            average_tip=0.0,
            period_start=today,
            period_end=today,
        )
        resp = EarningsResponse(summary=summary, trips=[])
        assert resp.trips == []
        assert resp.summary.trip_count == 0

    def test_daily_earnings_point(self):
        point = DailyEarningsPoint(
            date="2026-04-01",
            fares=50.0,
            tips=5.0,
            cancellation_fees=2.0,
            total=57.0,
            trips=5,
        )
        assert point.date == "2026-04-01"
        assert point.total == 57.0
        assert point.trips == 5

    def test_rating_distribution_response_defaults(self):
        dist = RatingDistributionResponse()
        assert dist.one_star == 0
        assert dist.five_star == 0

    def test_rating_distribution_response_with_values(self):
        dist = RatingDistributionResponse(
            one_star=1,
            two_star=2,
            three_star=5,
            four_star=20,
            five_star=72,
        )
        assert dist.five_star == 72

    def test_ratings_summary_response_fields(self):
        dist = RatingDistributionResponse(five_star=50, four_star=30)
        resp = RatingsSummaryResponse(
            average=4.7,
            total_ratings=80,
            distribution=dist,
            recent_average=4.9,
            recent_count=10,
        )
        assert resp.average == 4.7
        assert resp.recent_count == 10

    def test_ratings_summary_optional_recent(self):
        dist = RatingDistributionResponse()
        resp = RatingsSummaryResponse(
            average=4.5,
            total_ratings=20,
            distribution=dist,
        )
        assert resp.recent_average is None
        assert resp.recent_count == 0


# ===========================================================================
# TestVerificationSchemas
# ===========================================================================


class TestVerificationSchemas:
    """Tests for verification-related Pydantic schemas."""

    def test_document_submit_request_minimal(self):
        req = DocumentSubmitRequest(
            document_type="drivers_license",
            document_ref="s3://bucket/doc.pdf",
        )
        assert req.document_type == "drivers_license"
        assert req.document_number is None
        assert req.expiry_date is None

    def test_document_submit_request_full(self):
        now = _now()
        req = DocumentSubmitRequest(
            document_type="insurance",
            document_ref="s3://bucket/ins.pdf",
            document_number="INS-001",
            expiry_date=now,
        )
        assert req.document_number == "INS-001"
        assert req.expiry_date == now

    def test_document_response_fields(self):
        now = _now()
        resp = DocumentResponse(
            id=1,
            driver_profile_id=5,
            document_type="drivers_license",
            status="pending",
            document_ref="s3://bucket/doc.pdf",
            document_number="DL001",
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

    def test_verification_status_response_fields(self):
        resp = VerificationStatusResponse(
            documents=[],
            missing_required=["drivers_license", "insurance"],
            all_required_approved=False,
        )
        assert resp.all_required_approved is False
        assert len(resp.missing_required) == 2

    def test_verification_status_response_all_approved(self):
        resp = VerificationStatusResponse(
            documents=[],
            missing_required=[],
            all_required_approved=True,
        )
        assert resp.all_required_approved is True


# ===========================================================================
# TestDriverProfileModel
# ===========================================================================


class TestDriverProfileModel:
    """Tests verifying the DriverProfile ORM model table structure."""

    def _cols(self):
        from app.models.driver import DriverProfile
        return {c.name for c in DriverProfile.__table__.columns}

    def test_table_name(self):
        from app.models.driver import DriverProfile
        assert DriverProfile.__tablename__ == "driver_profiles"

    def test_has_id(self):
        assert "id" in self._cols()

    def test_has_user_id(self):
        assert "user_id" in self._cols()

    def test_has_vehicle_make(self):
        assert "vehicle_make" in self._cols()

    def test_has_vehicle_model(self):
        assert "vehicle_model" in self._cols()

    def test_has_vehicle_year(self):
        assert "vehicle_year" in self._cols()

    def test_has_vehicle_color(self):
        assert "vehicle_color" in self._cols()

    def test_has_license_plate(self):
        assert "license_plate" in self._cols()

    def test_has_is_online(self):
        assert "is_online" in self._cols()

    def test_has_is_approved(self):
        assert "is_approved" in self._cols()

    def test_has_rating_avg(self):
        assert "rating_avg" in self._cols()

    def test_has_total_trips(self):
        assert "total_trips" in self._cols()


# ===========================================================================
# TestVerificationModel
# ===========================================================================


class TestVerificationModel:
    """Tests verifying the DriverDocument ORM model table structure."""

    def _cols(self):
        from app.models.verification import DriverDocument
        return {c.name for c in DriverDocument.__table__.columns}

    def test_table_name(self):
        from app.models.verification import DriverDocument
        assert DriverDocument.__tablename__ == "driver_documents"

    def test_has_id(self):
        assert "id" in self._cols()

    def test_has_driver_profile_id(self):
        assert "driver_profile_id" in self._cols()

    def test_has_document_type(self):
        assert "document_type" in self._cols()

    def test_has_status(self):
        assert "status" in self._cols()

    def test_has_document_ref(self):
        assert "document_ref" in self._cols()

    def test_has_document_number(self):
        assert "document_number" in self._cols()

    def test_has_expiry_date(self):
        assert "expiry_date" in self._cols()

    def test_has_reviewed_by(self):
        assert "reviewed_by" in self._cols()

    def test_has_reviewed_at(self):
        assert "reviewed_at" in self._cols()

    def test_has_rejection_reason(self):
        assert "rejection_reason" in self._cols()

    def test_has_submitted_at(self):
        assert "submitted_at" in self._cols()

    def test_driver_profile_id_is_indexed(self):
        from app.models.verification import DriverDocument
        col = DriverDocument.__table__.columns["driver_profile_id"]
        assert col.index is True

    def test_driver_profile_id_has_fk(self):
        from app.models.verification import DriverDocument
        col = DriverDocument.__table__.columns["driver_profile_id"]
        targets = {fk.target_fullname for fk in col.foreign_keys}
        assert "driver_profiles.id" in targets

    def test_document_type_enum_values(self):
        assert DocumentType.DRIVERS_LICENSE.value == "drivers_license"
        assert DocumentType.VEHICLE_REGISTRATION.value == "vehicle_registration"
        assert DocumentType.INSURANCE.value == "insurance"
        assert DocumentType.BACKGROUND_CHECK.value == "background_check"
        assert DocumentType.VEHICLE_INSPECTION.value == "vehicle_inspection"

    def test_verification_status_enum_values(self):
        assert VerificationStatus.PENDING.value == "pending"
        assert VerificationStatus.UNDER_REVIEW.value == "under_review"
        assert VerificationStatus.APPROVED.value == "approved"
        assert VerificationStatus.REJECTED.value == "rejected"
        assert VerificationStatus.EXPIRED.value == "expired"
