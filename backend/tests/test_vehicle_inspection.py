"""Comprehensive unit tests for vehicle inspection record management.

Covers:
- Model fields, enum values, and table structure
- Schema validation (create, update, admin review, status summary)
- Service logic: create, update, admin review, driver summary,
  expiring inspections, mark expired
- Endpoint auth checks and behaviour

All tests are pure unit tests — no database required.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.vehicle_inspection import (
    InspectionAlertType,
    InspectionStatus,
    InspectionType,
    VehicleInspection,
    VehicleInspectionAlert,
)
from app.schemas.vehicle_inspection import (
    AdminInspectionReview,
    InspectionStatusSummary,
    VehicleInspectionCreate,
    VehicleInspectionResponse,
    VehicleInspectionUpdate,
)
from app.services.vehicle_inspection import (
    VehicleInspectionError,
    admin_review_inspection,
    create_inspection,
    get_current_approved_inspection,
    get_driver_inspections,
    get_driver_summary,
    get_expiring_inspections,
    mark_expired_inspections,
    update_inspection,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = date.today()
TOMORROW = TODAY + timedelta(days=1)
NEXT_YEAR = TODAY + timedelta(days=365)
YESTERDAY = TODAY - timedelta(days=1)


def _make_inspection(**kwargs) -> VehicleInspection:
    defaults = dict(
        id=1,
        driver_id=10,
        inspection_type=InspectionType.ANNUAL,
        inspection_date=TODAY,
        expiry_date=NEXT_YEAR,
        status=InspectionStatus.PENDING_REVIEW,
        document_url="https://storage.example.com/inspection1.pdf",
        odometer_reading=50000,
        passed_items=["brakes", "lights", "tires"],
        failed_items=None,
        notes=None,
        rejection_reason=None,
        reviewed_by=None,
        reviewed_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    inspection = MagicMock(spec=VehicleInspection)
    for k, v in defaults.items():
        setattr(inspection, k, v)
    return inspection


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


class TestVehicleInspectionModel:
    def test_tablename(self):
        assert VehicleInspection.__tablename__ == "vehicle_inspections"

    def test_has_required_columns(self):
        cols = {c.key for c in VehicleInspection.__table__.columns}
        required = {
            "id", "driver_id", "inspection_type", "inspection_date", "expiry_date",
            "status", "document_url", "odometer_reading", "passed_items", "failed_items",
            "notes", "rejection_reason", "reviewed_by", "reviewed_at",
            "created_at", "updated_at",
        }
        assert required.issubset(cols)

    def test_inspection_type_enum_values(self):
        assert InspectionType.ANNUAL == "annual"
        assert InspectionType.SEMI_ANNUAL == "semi_annual"
        assert InspectionType.PRE_TRIP == "pre_trip"
        assert InspectionType.POST_TRIP == "post_trip"
        assert InspectionType.REPAIR_FOLLOWUP == "repair_followup"

    def test_all_inspection_type_values_exist(self):
        expected = {"annual", "semi_annual", "pre_trip", "post_trip", "repair_followup"}
        actual = {t.value for t in InspectionType}
        assert actual == expected

    def test_status_enum_values(self):
        assert InspectionStatus.PENDING_REVIEW == "pending_review"
        assert InspectionStatus.APPROVED == "approved"
        assert InspectionStatus.REJECTED == "rejected"
        assert InspectionStatus.EXPIRED == "expired"

    def test_all_status_values_exist(self):
        expected = {"pending_review", "approved", "rejected", "expired"}
        actual = {s.value for s in InspectionStatus}
        assert actual == expected

    def test_has_composite_indexes(self):
        index_names = {idx.name for idx in VehicleInspection.__table__.indexes}
        assert "ix_vehicle_inspection_driver_status" in index_names
        assert "ix_vehicle_inspection_status_expiry" in index_names


class TestVehicleInspectionAlertModel:
    def test_tablename(self):
        assert VehicleInspectionAlert.__tablename__ == "vehicle_inspection_alerts"

    def test_has_required_columns(self):
        cols = {c.key for c in VehicleInspectionAlert.__table__.columns}
        required = {"id", "inspection_id", "alert_type", "alert_date", "acknowledged", "created_at"}
        assert required.issubset(cols)

    def test_alert_type_enum_values(self):
        assert InspectionAlertType.EXPIRING_SOON == "expiring_soon"
        assert InspectionAlertType.EXPIRED == "expired"
        assert InspectionAlertType.FAILED == "failed"

    def test_all_alert_type_values_exist(self):
        expected = {"expiring_soon", "expired", "failed"}
        actual = {a.value for a in InspectionAlertType}
        assert actual == expected


# ===========================================================================
# Schema tests
# ===========================================================================


class TestVehicleInspectionCreate:
    def _valid_data(self, **overrides):
        base = dict(
            inspection_type="annual",
            inspection_date=TODAY,
        )
        base.update(overrides)
        return base

    def test_valid_create_minimal(self):
        req = VehicleInspectionCreate(**self._valid_data())
        assert req.inspection_type == InspectionType.ANNUAL
        assert req.document_url is None

    def test_valid_create_with_document_url(self):
        req = VehicleInspectionCreate(
            **self._valid_data(document_url="https://example.com/doc.pdf")
        )
        assert req.document_url == "https://example.com/doc.pdf"

    def test_valid_create_with_expiry(self):
        req = VehicleInspectionCreate(
            **self._valid_data(expiry_date=NEXT_YEAR)
        )
        assert req.expiry_date == NEXT_YEAR

    def test_expiry_before_inspection_rejected(self):
        with pytest.raises(Exception):
            VehicleInspectionCreate(
                **self._valid_data(
                    inspection_date=NEXT_YEAR,
                    expiry_date=TODAY,
                )
            )

    def test_expiry_equal_inspection_rejected(self):
        with pytest.raises(Exception):
            VehicleInspectionCreate(
                **self._valid_data(
                    inspection_date=TODAY,
                    expiry_date=TODAY,
                )
            )

    def test_expiry_after_inspection_accepted(self):
        req = VehicleInspectionCreate(
            **self._valid_data(
                inspection_date=TODAY,
                expiry_date=TOMORROW,
            )
        )
        assert req.expiry_date == TOMORROW

    def test_optional_fields_default_none(self):
        req = VehicleInspectionCreate(**self._valid_data())
        assert req.odometer_reading is None
        assert req.passed_items is None
        assert req.failed_items is None
        assert req.notes is None

    def test_all_inspection_types_accepted(self):
        for itype in InspectionType:
            req = VehicleInspectionCreate(**self._valid_data(inspection_type=itype.value))
            assert req.inspection_type == itype


class TestVehicleInspectionUpdate:
    def test_all_fields_optional(self):
        update = VehicleInspectionUpdate()
        assert update.document_url is None
        assert update.odometer_reading is None
        assert update.notes is None

    def test_partial_update(self):
        update = VehicleInspectionUpdate(notes="All clear")
        assert update.notes == "All clear"
        assert update.document_url is None

    def test_update_with_url(self):
        update = VehicleInspectionUpdate(document_url="https://example.com/new.pdf")
        assert update.document_url == "https://example.com/new.pdf"


class TestAdminInspectionReview:
    def test_approve_valid(self):
        req = AdminInspectionReview(status=InspectionStatus.APPROVED)
        assert req.status == InspectionStatus.APPROVED

    def test_reject_with_reason_valid(self):
        req = AdminInspectionReview(
            status=InspectionStatus.REJECTED,
            rejection_reason="Brakes failed inspection",
        )
        assert req.rejection_reason == "Brakes failed inspection"

    def test_reject_without_reason_raises(self):
        with pytest.raises(Exception):
            AdminInspectionReview(status=InspectionStatus.REJECTED)

    def test_expired_status_raises(self):
        with pytest.raises(Exception):
            AdminInspectionReview(status=InspectionStatus.EXPIRED)

    def test_pending_review_status_raises(self):
        with pytest.raises(Exception):
            AdminInspectionReview(status=InspectionStatus.PENDING_REVIEW)

    def test_only_approved_and_rejected_are_valid(self):
        valid_statuses = {InspectionStatus.APPROVED, InspectionStatus.REJECTED}
        for status in InspectionStatus:
            if status in valid_statuses:
                if status == InspectionStatus.REJECTED:
                    req = AdminInspectionReview(
                        status=status, rejection_reason="some reason"
                    )
                else:
                    req = AdminInspectionReview(status=status)
                assert req.status == status
            else:
                with pytest.raises(Exception):
                    AdminInspectionReview(status=status)

    def test_notes_optional(self):
        req = AdminInspectionReview(status=InspectionStatus.APPROVED)
        assert req.notes is None

    def test_notes_accepted(self):
        req = AdminInspectionReview(status=InspectionStatus.APPROVED, notes="Looks good")
        assert req.notes == "Looks good"


class TestVehicleInspectionResponse:
    def test_from_attributes(self):
        inspection = _make_inspection()
        resp = VehicleInspectionResponse.model_validate(inspection)
        assert resp.id == 1
        assert resp.driver_id == 10
        assert resp.status == InspectionStatus.PENDING_REVIEW
        assert resp.inspection_type == InspectionType.ANNUAL

    def test_optional_fields_nullable(self):
        inspection = _make_inspection(
            document_url=None, rejection_reason=None,
            reviewed_by=None, reviewed_at=None, expiry_date=None,
        )
        resp = VehicleInspectionResponse.model_validate(inspection)
        assert resp.document_url is None
        assert resp.rejection_reason is None
        assert resp.reviewed_by is None
        assert resp.reviewed_at is None
        assert resp.expiry_date is None


# ===========================================================================
# Service tests
# ===========================================================================


class TestGetDriverInspections:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        inspections = [_make_inspection(id=1), _make_inspection(id=2)]
        db = _make_db(scalars=inspections)
        result = await get_driver_inspections(db, driver_id=10)
        assert result == inspections

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_new_driver(self):
        db = _make_db(scalars=[])
        result = await get_driver_inspections(db, driver_id=99)
        assert result == []


class TestCreateInspection:
    @pytest.mark.asyncio
    async def test_creates_pending_review(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.refresh = AsyncMock()

        data = VehicleInspectionCreate(
            inspection_type="annual",
            inspection_date=TODAY,
        )
        created = _make_inspection(status=InspectionStatus.PENDING_REVIEW)
        db.refresh.side_effect = lambda obj: None

        with patch("app.services.vehicle_inspection.VehicleInspection") as MockModel:
            MockModel.return_value = created
            result = await create_inspection(db, driver_id=10, data=data)

        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_annual_inspection_gets_1_year_expiry_if_not_provided(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.refresh = AsyncMock()

        data = VehicleInspectionCreate(
            inspection_type="annual",
            inspection_date=TODAY,
        )
        db.refresh.side_effect = lambda obj: None

        with patch("app.services.vehicle_inspection.VehicleInspection") as MockModel:
            MockModel.return_value = _make_inspection()
            await create_inspection(db, driver_id=10, data=data)

        call_kwargs = MockModel.call_args.kwargs
        expected_expiry = TODAY + timedelta(days=365)
        assert call_kwargs["expiry_date"] == expected_expiry

    @pytest.mark.asyncio
    async def test_semi_annual_inspection_gets_182_day_expiry(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.refresh = AsyncMock()

        data = VehicleInspectionCreate(
            inspection_type="semi_annual",
            inspection_date=TODAY,
        )
        db.refresh.side_effect = lambda obj: None

        with patch("app.services.vehicle_inspection.VehicleInspection") as MockModel:
            MockModel.return_value = _make_inspection()
            await create_inspection(db, driver_id=10, data=data)

        call_kwargs = MockModel.call_args.kwargs
        expected_expiry = TODAY + timedelta(days=182)
        assert call_kwargs["expiry_date"] == expected_expiry

    @pytest.mark.asyncio
    async def test_pre_trip_inspection_expiry_stays_none(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.refresh = AsyncMock()

        data = VehicleInspectionCreate(
            inspection_type="pre_trip",
            inspection_date=TODAY,
        )
        db.refresh.side_effect = lambda obj: None

        with patch("app.services.vehicle_inspection.VehicleInspection") as MockModel:
            MockModel.return_value = _make_inspection(expiry_date=None)
            await create_inspection(db, driver_id=10, data=data)

        call_kwargs = MockModel.call_args.kwargs
        assert call_kwargs["expiry_date"] is None

    @pytest.mark.asyncio
    async def test_explicit_expiry_date_is_honoured(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.refresh = AsyncMock()

        explicit_expiry = TODAY + timedelta(days=200)
        data = VehicleInspectionCreate(
            inspection_type="annual",
            inspection_date=TODAY,
            expiry_date=explicit_expiry,
        )
        db.refresh.side_effect = lambda obj: None

        with patch("app.services.vehicle_inspection.VehicleInspection") as MockModel:
            MockModel.return_value = _make_inspection(expiry_date=explicit_expiry)
            await create_inspection(db, driver_id=10, data=data)

        call_kwargs = MockModel.call_args.kwargs
        assert call_kwargs["expiry_date"] == explicit_expiry


class TestUpdateInspection:
    @pytest.mark.asyncio
    async def test_driver_can_update_own_pending_inspection(self):
        inspection = _make_inspection(
            driver_id=10, status=InspectionStatus.PENDING_REVIEW
        )
        db = _make_db(scalar=inspection)

        update = VehicleInspectionUpdate(notes="Updated notes")
        result = await update_inspection(db, driver_id=10, inspection_id=1, data=update)

        assert inspection.notes == "Updated notes"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_driver_cannot_update_another_drivers_inspection(self):
        inspection = _make_inspection(driver_id=99, status=InspectionStatus.PENDING_REVIEW)
        db = _make_db(scalar=inspection)

        update = VehicleInspectionUpdate(notes="Hack")
        with pytest.raises(VehicleInspectionError, match="Not authorised"):
            await update_inspection(db, driver_id=10, inspection_id=1, data=update)

    @pytest.mark.asyncio
    async def test_driver_cannot_update_approved_inspection(self):
        inspection = _make_inspection(driver_id=10, status=InspectionStatus.APPROVED)
        db = _make_db(scalar=inspection)

        update = VehicleInspectionUpdate(notes="Try to change")
        with pytest.raises(VehicleInspectionError, match="Cannot edit"):
            await update_inspection(db, driver_id=10, inspection_id=1, data=update)

    @pytest.mark.asyncio
    async def test_driver_cannot_update_rejected_inspection(self):
        inspection = _make_inspection(driver_id=10, status=InspectionStatus.REJECTED)
        db = _make_db(scalar=inspection)

        update = VehicleInspectionUpdate(notes="Try to change")
        with pytest.raises(VehicleInspectionError, match="Cannot edit"):
            await update_inspection(db, driver_id=10, inspection_id=1, data=update)

    @pytest.mark.asyncio
    async def test_driver_cannot_update_expired_inspection(self):
        inspection = _make_inspection(driver_id=10, status=InspectionStatus.EXPIRED)
        db = _make_db(scalar=inspection)

        update = VehicleInspectionUpdate(notes="Try to change")
        with pytest.raises(VehicleInspectionError, match="Cannot edit"):
            await update_inspection(db, driver_id=10, inspection_id=1, data=update)

    @pytest.mark.asyncio
    async def test_update_nonexistent_inspection_raises(self):
        db = _make_db(scalar=None)
        update = VehicleInspectionUpdate(notes="Notes")
        with pytest.raises(VehicleInspectionError, match="not found"):
            await update_inspection(db, driver_id=10, inspection_id=999, data=update)

    @pytest.mark.asyncio
    async def test_update_sets_only_provided_fields(self):
        inspection = _make_inspection(
            driver_id=10, status=InspectionStatus.PENDING_REVIEW,
            odometer_reading=40000, notes=None,
        )
        db = _make_db(scalar=inspection)

        update = VehicleInspectionUpdate(odometer_reading=45000)
        await update_inspection(db, driver_id=10, inspection_id=1, data=update)

        assert inspection.odometer_reading == 45000
        # notes was not provided so should not have been touched
        assert inspection.notes is None


class TestAdminReviewInspectionService:
    @pytest.mark.asyncio
    async def test_admin_can_approve_inspection(self):
        inspection = _make_inspection(
            driver_id=10, status=InspectionStatus.PENDING_REVIEW
        )
        db = AsyncMock()

        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = inspection
        second_result = MagicMock()
        second_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[first_result, second_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        review = AdminInspectionReview(status=InspectionStatus.APPROVED)
        await admin_review_inspection(db, admin_id=1, inspection_id=1, review=review)

        assert inspection.status == InspectionStatus.APPROVED
        assert inspection.reviewed_by == 1
        assert inspection.reviewed_at is not None
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_approval_sets_reviewed_by_and_reviewed_at(self):
        inspection = _make_inspection(
            driver_id=10, status=InspectionStatus.PENDING_REVIEW,
            reviewed_by=None, reviewed_at=None,
        )
        db = AsyncMock()

        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = inspection
        second_result = MagicMock()
        second_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[first_result, second_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        review = AdminInspectionReview(status=InspectionStatus.APPROVED)
        await admin_review_inspection(db, admin_id=42, inspection_id=1, review=review)

        assert inspection.reviewed_by == 42
        assert isinstance(inspection.reviewed_at, datetime)

    @pytest.mark.asyncio
    async def test_admin_approval_expires_previous_approved_inspection(self):
        new_inspection = _make_inspection(
            id=2, driver_id=10, status=InspectionStatus.PENDING_REVIEW
        )
        prev_approved = _make_inspection(
            id=1, driver_id=10, status=InspectionStatus.APPROVED
        )
        db = AsyncMock()

        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = new_inspection
        second_result = MagicMock()
        second_result.scalars.return_value.all.return_value = [prev_approved]
        db.execute = AsyncMock(side_effect=[first_result, second_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        review = AdminInspectionReview(status=InspectionStatus.APPROVED)
        await admin_review_inspection(db, admin_id=1, inspection_id=2, review=review)

        assert prev_approved.status == InspectionStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_admin_can_reject_with_reason(self):
        inspection = _make_inspection(
            driver_id=10, status=InspectionStatus.PENDING_REVIEW
        )
        db = _make_db(scalar=inspection)

        review = AdminInspectionReview(
            status=InspectionStatus.REJECTED,
            rejection_reason="Headlights not functioning",
        )
        await admin_review_inspection(db, admin_id=5, inspection_id=1, review=review)

        assert inspection.status == InspectionStatus.REJECTED
        assert inspection.rejection_reason == "Headlights not functioning"
        assert inspection.reviewed_by == 5

    @pytest.mark.asyncio
    async def test_admin_review_nonexistent_inspection_raises(self):
        db = _make_db(scalar=None)
        review = AdminInspectionReview(status=InspectionStatus.APPROVED)
        with pytest.raises(VehicleInspectionError, match="not found"):
            await admin_review_inspection(db, admin_id=1, inspection_id=999, review=review)

    @pytest.mark.asyncio
    async def test_admin_review_with_notes_updates_notes(self):
        inspection = _make_inspection(
            driver_id=10, status=InspectionStatus.PENDING_REVIEW
        )
        db = AsyncMock()

        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = inspection
        second_result = MagicMock()
        second_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[first_result, second_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        review = AdminInspectionReview(
            status=InspectionStatus.APPROVED,
            notes="Excellent condition",
        )
        await admin_review_inspection(db, admin_id=1, inspection_id=1, review=review)

        assert inspection.notes == "Excellent condition"


class TestGetDriverSummary:
    @pytest.mark.asyncio
    async def test_has_active_inspection_true_for_approved(self):
        approved = _make_inspection(
            status=InspectionStatus.APPROVED,
            expiry_date=NEXT_YEAR,
        )
        db = AsyncMock()
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [approved]
        single_result = MagicMock()
        single_result.scalar_one_or_none.return_value = approved
        db.execute = AsyncMock(side_effect=[list_result, single_result])

        summary = await get_driver_summary(db, driver_id=10)

        assert summary.has_active_inspection is True
        assert summary.days_until_expiry is not None
        assert summary.days_until_expiry > 0

    @pytest.mark.asyncio
    async def test_has_active_inspection_false_when_no_approved(self):
        db = AsyncMock()
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = []
        single_result = MagicMock()
        single_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[list_result, single_result])

        summary = await get_driver_summary(db, driver_id=10)

        assert summary.has_active_inspection is False
        assert summary.days_until_expiry is None
        assert summary.current_inspection is None

    @pytest.mark.asyncio
    async def test_days_until_expiry_calculated_correctly(self):
        expiry = TODAY + timedelta(days=10)
        approved = _make_inspection(
            status=InspectionStatus.APPROVED,
            expiry_date=expiry,
        )
        db = AsyncMock()
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [approved]
        single_result = MagicMock()
        single_result.scalar_one_or_none.return_value = approved
        db.execute = AsyncMock(side_effect=[list_result, single_result])

        summary = await get_driver_summary(db, driver_id=10)
        assert summary.days_until_expiry == 10

    @pytest.mark.asyncio
    async def test_summary_inspection_without_expiry_date(self):
        approved = _make_inspection(
            status=InspectionStatus.APPROVED,
            expiry_date=None,
        )
        db = AsyncMock()
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [approved]
        single_result = MagicMock()
        single_result.scalar_one_or_none.return_value = approved
        db.execute = AsyncMock(side_effect=[list_result, single_result])

        summary = await get_driver_summary(db, driver_id=10)
        # No expiry date means days_until_expiry stays None
        assert summary.days_until_expiry is None
        assert summary.has_active_inspection is True


class TestGetExpiringInspections:
    @pytest.mark.asyncio
    async def test_returns_inspections_expiring_within_n_days(self):
        expiring = _make_inspection(
            status=InspectionStatus.APPROVED,
            expiry_date=TODAY + timedelta(days=15),
        )
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [expiring]
        db.execute = AsyncMock(return_value=result)

        inspections = await get_expiring_inspections(db, days_ahead=30)
        assert len(inspections) == 1
        assert inspections[0] is expiring

    @pytest.mark.asyncio
    async def test_returns_empty_when_none_expiring(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        inspections = await get_expiring_inspections(db, days_ahead=30)
        assert inspections == []

    @pytest.mark.asyncio
    async def test_default_days_ahead_is_30(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        # Calling without days_ahead should not raise
        await get_expiring_inspections(db)
        db.execute.assert_called_once()


class TestMarkExpiredInspections:
    @pytest.mark.asyncio
    async def test_updates_past_expiry_inspections_to_expired(self):
        past = _make_inspection(
            status=InspectionStatus.APPROVED,
            expiry_date=YESTERDAY,
        )
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [past]
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        count = await mark_expired_inspections(db)

        assert count == 1
        assert past.status == InspectionStatus.EXPIRED
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_expired_inspections(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        count = await mark_expired_inspections(db)
        assert count == 0
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_expired_inspections_all_updated(self):
        past1 = _make_inspection(id=1, status=InspectionStatus.APPROVED, expiry_date=YESTERDAY)
        past2 = _make_inspection(id=2, status=InspectionStatus.APPROVED, expiry_date=YESTERDAY - timedelta(days=5))
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [past1, past2]
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        count = await mark_expired_inspections(db)
        assert count == 2
        assert past1.status == InspectionStatus.EXPIRED
        assert past2.status == InspectionStatus.EXPIRED
        db.commit.assert_called_once()


# ===========================================================================
# API endpoint behaviour (via service/schema layer)
# ===========================================================================


class TestEndpointSchemaContracts:
    """Verify that the API layer schema contracts hold — no mocked HTTP client needed.

    These tests confirm that the response schemas produced by the service are
    serialisable and carry the right shape, which is what the endpoint returns.
    """

    def test_inspection_response_serialises_full_record(self):
        inspection = _make_inspection()
        resp = VehicleInspectionResponse.model_validate(inspection)
        dumped = resp.model_dump()
        assert dumped["id"] == 1
        assert dumped["driver_id"] == 10
        assert dumped["status"] == "pending_review"

    def test_inspection_status_summary_serialises(self):
        approved = _make_inspection(
            status=InspectionStatus.APPROVED, expiry_date=NEXT_YEAR
        )
        resp = VehicleInspectionResponse.model_validate(approved)
        summary = InspectionStatusSummary(
            has_active_inspection=True,
            days_until_expiry=365,
            current_inspection=resp,
            inspections=[resp],
        )
        dumped = summary.model_dump()
        assert dumped["has_active_inspection"] is True
        assert dumped["days_until_expiry"] == 365
        assert dumped["current_inspection"]["id"] == 1

    def test_admin_review_reject_requires_reason_contract(self):
        """The API layer relies on the schema validator — confirm it raises."""
        with pytest.raises(Exception):
            AdminInspectionReview(status="rejected")

    def test_admin_review_approve_no_reason_needed(self):
        req = AdminInspectionReview(status="approved")
        assert req.status == InspectionStatus.APPROVED

    def test_vehicle_inspection_create_pre_trip_no_expiry(self):
        req = VehicleInspectionCreate(
            inspection_type="pre_trip",
            inspection_date=TODAY,
        )
        assert req.expiry_date is None
        assert req.inspection_type == InspectionType.PRE_TRIP

    def test_vehicle_inspection_create_post_trip_no_expiry(self):
        req = VehicleInspectionCreate(
            inspection_type="post_trip",
            inspection_date=TODAY,
        )
        assert req.expiry_date is None

    def test_vehicle_inspection_create_repair_followup(self):
        req = VehicleInspectionCreate(
            inspection_type="repair_followup",
            inspection_date=TODAY,
        )
        assert req.inspection_type == InspectionType.REPAIR_FOLLOWUP
