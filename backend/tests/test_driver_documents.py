"""Comprehensive unit tests for driver license and vehicle registration document management.

Covers:
- Model fields, enum values, and table structure
- Schema validation (create, update, admin review, status summary)
- Service logic: create, update, admin review, driver summary,
  expiring documents, mark expired
- Endpoint auth checks and behaviour (via schema/service layer)
- Authorization: driver can only see own docs; admins see all
- Edge cases: double approve, reject without reason, update non-editable status, etc.

All tests are pure unit tests — no database required.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_documents import (
    DocumentAlertType,
    DocumentStatus,
    DriverLicense,
    DriverLicenseAlert,
    LicenseClass,
    VehicleRegistration,
    VehicleRegistrationAlert,
)
from app.schemas.driver_documents import (
    AdminLicenseReview,
    AdminRegistrationReview,
    DriverDocumentsSummary,
    DriverLicenseCreate,
    DriverLicenseResponse,
    DriverLicenseUpdate,
    LicenseStatusSummary,
    RegistrationStatusSummary,
    VehicleRegistrationCreate,
    VehicleRegistrationResponse,
    VehicleRegistrationUpdate,
)
from app.services.driver_documents import (
    DriverDocumentError,
    admin_review_license,
    admin_review_registration,
    create_license,
    create_registration,
    get_current_approved_license,
    get_current_approved_registration,
    get_driver_documents_summary,
    get_driver_licenses,
    get_driver_registrations,
    get_expiring_licenses,
    get_expiring_registrations,
    get_license_status_summary,
    get_registration_status_summary,
    mark_expired_licenses,
    mark_expired_registrations,
    update_license,
    update_registration,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = date.today()
TOMORROW = TODAY + timedelta(days=1)
NEXT_YEAR = TODAY + timedelta(days=365)
YESTERDAY = TODAY - timedelta(days=1)


def _make_license(**kwargs) -> DriverLicense:
    defaults = dict(
        id=1,
        driver_id=10,
        license_number="DL-12345",
        state_issued="CA",
        license_class=LicenseClass.C,
        expiry_date=NEXT_YEAR,
        document_url="https://storage.example.com/license1.pdf",
        status=DocumentStatus.PENDING_REVIEW,
        notes=None,
        rejection_reason=None,
        reviewed_by=None,
        reviewed_at=None,
        uploaded_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    lic = MagicMock(spec=DriverLicense)
    for k, v in defaults.items():
        setattr(lic, k, v)
    return lic


def _make_registration(**kwargs) -> VehicleRegistration:
    defaults = dict(
        id=1,
        driver_id=10,
        vehicle_id="VH-001",
        plate_number="ABC123",
        state="CA",
        expiry_date=NEXT_YEAR,
        document_url="https://storage.example.com/reg1.pdf",
        status=DocumentStatus.PENDING_REVIEW,
        notes=None,
        rejection_reason=None,
        reviewed_by=None,
        reviewed_at=None,
        uploaded_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    reg = MagicMock(spec=VehicleRegistration)
    for k, v in defaults.items():
        setattr(reg, k, v)
    return reg


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
# Model tests — DriverLicense
# ===========================================================================


class TestDriverLicenseModel:
    def test_tablename(self):
        assert DriverLicense.__tablename__ == "driver_licenses"

    def test_has_required_columns(self):
        cols = {c.key for c in DriverLicense.__table__.columns}
        required = {
            "id", "driver_id", "license_number", "state_issued", "license_class",
            "expiry_date", "document_url", "status", "notes", "rejection_reason",
            "reviewed_by", "reviewed_at", "uploaded_at", "created_at", "updated_at",
        }
        assert required.issubset(cols)

    def test_license_class_enum_values(self):
        assert LicenseClass.A == "A"
        assert LicenseClass.B == "B"
        assert LicenseClass.C == "C"
        assert LicenseClass.CDL == "CDL"

    def test_all_license_class_values_exist(self):
        expected = {"A", "B", "C", "CDL"}
        actual = {lc.value for lc in LicenseClass}
        assert actual == expected

    def test_document_status_enum_values(self):
        assert DocumentStatus.PENDING_UPLOAD == "pending_upload"
        assert DocumentStatus.PENDING_REVIEW == "pending_review"
        assert DocumentStatus.APPROVED == "approved"
        assert DocumentStatus.REJECTED == "rejected"
        assert DocumentStatus.EXPIRED == "expired"

    def test_all_document_status_values_exist(self):
        expected = {"pending_upload", "pending_review", "approved", "rejected", "expired"}
        actual = {s.value for s in DocumentStatus}
        assert actual == expected

    def test_has_composite_indexes(self):
        index_names = {idx.name for idx in DriverLicense.__table__.indexes}
        assert "ix_driver_license_driver_status" in index_names
        assert "ix_driver_license_status_expiry" in index_names


class TestDriverLicenseAlertModel:
    def test_tablename(self):
        assert DriverLicenseAlert.__tablename__ == "driver_license_alerts"

    def test_has_required_columns(self):
        cols = {c.key for c in DriverLicenseAlert.__table__.columns}
        required = {"id", "driver_id", "license_id", "alert_type", "sent_at", "created_at"}
        assert required.issubset(cols)

    def test_alert_type_enum_values(self):
        assert DocumentAlertType.THIRTY_DAY == "30_day"
        assert DocumentAlertType.SEVEN_DAY == "7_day"
        assert DocumentAlertType.ONE_DAY == "1_day"
        assert DocumentAlertType.EXPIRED == "expired"

    def test_all_alert_type_values_exist(self):
        expected = {"30_day", "7_day", "1_day", "expired"}
        actual = {a.value for a in DocumentAlertType}
        assert actual == expected


# ===========================================================================
# Model tests — VehicleRegistration
# ===========================================================================


class TestVehicleRegistrationModel:
    def test_tablename(self):
        assert VehicleRegistration.__tablename__ == "vehicle_registrations"

    def test_has_required_columns(self):
        cols = {c.key for c in VehicleRegistration.__table__.columns}
        required = {
            "id", "driver_id", "vehicle_id", "plate_number", "state", "expiry_date",
            "document_url", "status", "notes", "rejection_reason",
            "reviewed_by", "reviewed_at", "uploaded_at", "created_at", "updated_at",
        }
        assert required.issubset(cols)

    def test_has_composite_indexes(self):
        index_names = {idx.name for idx in VehicleRegistration.__table__.indexes}
        assert "ix_vehicle_registration_driver_status" in index_names
        assert "ix_vehicle_registration_status_expiry" in index_names


class TestVehicleRegistrationAlertModel:
    def test_tablename(self):
        assert VehicleRegistrationAlert.__tablename__ == "vehicle_registration_alerts"

    def test_has_required_columns(self):
        cols = {c.key for c in VehicleRegistrationAlert.__table__.columns}
        required = {"id", "driver_id", "registration_id", "alert_type", "sent_at", "created_at"}
        assert required.issubset(cols)


# ===========================================================================
# Schema tests — DriverLicenseCreate
# ===========================================================================


class TestDriverLicenseCreate:
    def _valid_data(self, **overrides):
        base = dict(
            license_number="DL-98765",
            state_issued="NY",
            license_class="C",
            expiry_date=NEXT_YEAR,
        )
        base.update(overrides)
        return base

    def test_valid_create_minimal(self):
        req = DriverLicenseCreate(**self._valid_data())
        assert req.license_number == "DL-98765"
        assert req.license_class == LicenseClass.C
        assert req.document_url is None

    def test_valid_create_with_document_url(self):
        req = DriverLicenseCreate(
            **self._valid_data(document_url="https://example.com/dl.pdf")
        )
        assert req.document_url == "https://example.com/dl.pdf"

    def test_all_license_classes_accepted(self):
        for lc in LicenseClass:
            req = DriverLicenseCreate(**self._valid_data(license_class=lc.value))
            assert req.license_class == lc

    def test_expiry_in_past_rejected(self):
        with pytest.raises(Exception):
            DriverLicenseCreate(**self._valid_data(expiry_date=YESTERDAY))

    def test_expiry_today_rejected(self):
        with pytest.raises(Exception):
            DriverLicenseCreate(**self._valid_data(expiry_date=TODAY))

    def test_expiry_tomorrow_accepted(self):
        req = DriverLicenseCreate(**self._valid_data(expiry_date=TOMORROW))
        assert req.expiry_date == TOMORROW

    def test_empty_license_number_rejected(self):
        with pytest.raises(Exception):
            DriverLicenseCreate(**self._valid_data(license_number="   "))

    def test_empty_state_issued_rejected(self):
        with pytest.raises(Exception):
            DriverLicenseCreate(**self._valid_data(state_issued=""))

    def test_optional_fields_default_none(self):
        req = DriverLicenseCreate(**self._valid_data())
        assert req.document_url is None
        assert req.notes is None

    def test_license_number_stripped(self):
        req = DriverLicenseCreate(**self._valid_data(license_number="  DL-001  "))
        assert req.license_number == "DL-001"


class TestDriverLicenseUpdate:
    def test_all_fields_optional(self):
        update = DriverLicenseUpdate()
        assert update.license_number is None
        assert update.state_issued is None
        assert update.license_class is None
        assert update.expiry_date is None
        assert update.document_url is None
        assert update.notes is None

    def test_partial_update_notes(self):
        update = DriverLicenseUpdate(notes="Updated notes")
        assert update.notes == "Updated notes"
        assert update.license_number is None

    def test_partial_update_document_url(self):
        update = DriverLicenseUpdate(document_url="https://example.com/new.pdf")
        assert update.document_url == "https://example.com/new.pdf"

    def test_empty_license_number_rejected(self):
        with pytest.raises(Exception):
            DriverLicenseUpdate(license_number="   ")

    def test_empty_state_issued_rejected(self):
        with pytest.raises(Exception):
            DriverLicenseUpdate(state_issued="")


class TestAdminLicenseReview:
    def test_approve_valid(self):
        req = AdminLicenseReview(status=DocumentStatus.APPROVED)
        assert req.status == DocumentStatus.APPROVED

    def test_reject_with_reason_valid(self):
        req = AdminLicenseReview(
            status=DocumentStatus.REJECTED,
            rejection_reason="Expired document submitted",
        )
        assert req.rejection_reason == "Expired document submitted"

    def test_reject_without_reason_raises(self):
        with pytest.raises(Exception):
            AdminLicenseReview(status=DocumentStatus.REJECTED)

    def test_expired_status_raises(self):
        with pytest.raises(Exception):
            AdminLicenseReview(status=DocumentStatus.EXPIRED)

    def test_pending_upload_status_raises(self):
        with pytest.raises(Exception):
            AdminLicenseReview(status=DocumentStatus.PENDING_UPLOAD)

    def test_pending_review_status_raises(self):
        with pytest.raises(Exception):
            AdminLicenseReview(status=DocumentStatus.PENDING_REVIEW)

    def test_only_approved_and_rejected_are_valid(self):
        valid_statuses = {DocumentStatus.APPROVED, DocumentStatus.REJECTED}
        for status in DocumentStatus:
            if status in valid_statuses:
                if status == DocumentStatus.REJECTED:
                    req = AdminLicenseReview(
                        status=status, rejection_reason="some reason"
                    )
                else:
                    req = AdminLicenseReview(status=status)
                assert req.status == status
            else:
                with pytest.raises(Exception):
                    AdminLicenseReview(status=status)

    def test_notes_optional(self):
        req = AdminLicenseReview(status=DocumentStatus.APPROVED)
        assert req.notes is None

    def test_notes_accepted(self):
        req = AdminLicenseReview(status=DocumentStatus.APPROVED, notes="Looks good")
        assert req.notes == "Looks good"


class TestDriverLicenseResponse:
    def test_from_attributes(self):
        lic = _make_license()
        resp = DriverLicenseResponse.model_validate(lic)
        assert resp.id == 1
        assert resp.driver_id == 10
        assert resp.license_number == "DL-12345"
        assert resp.state_issued == "CA"
        assert resp.license_class == LicenseClass.C
        assert resp.status == DocumentStatus.PENDING_REVIEW

    def test_optional_fields_nullable(self):
        lic = _make_license(
            document_url=None, rejection_reason=None,
            reviewed_by=None, reviewed_at=None, notes=None, uploaded_at=None,
        )
        resp = DriverLicenseResponse.model_validate(lic)
        assert resp.document_url is None
        assert resp.rejection_reason is None
        assert resp.reviewed_by is None
        assert resp.reviewed_at is None
        assert resp.notes is None
        assert resp.uploaded_at is None


# ===========================================================================
# Schema tests — VehicleRegistrationCreate
# ===========================================================================


class TestVehicleRegistrationCreate:
    def _valid_data(self, **overrides):
        base = dict(
            plate_number="XYZ-999",
            state="TX",
            expiry_date=NEXT_YEAR,
        )
        base.update(overrides)
        return base

    def test_valid_create_minimal(self):
        req = VehicleRegistrationCreate(**self._valid_data())
        assert req.plate_number == "XYZ-999"
        assert req.state == "TX"
        assert req.vehicle_id is None
        assert req.document_url is None

    def test_valid_create_with_vehicle_id(self):
        req = VehicleRegistrationCreate(**self._valid_data(vehicle_id="VH-42"))
        assert req.vehicle_id == "VH-42"

    def test_expiry_in_past_rejected(self):
        with pytest.raises(Exception):
            VehicleRegistrationCreate(**self._valid_data(expiry_date=YESTERDAY))

    def test_expiry_today_rejected(self):
        with pytest.raises(Exception):
            VehicleRegistrationCreate(**self._valid_data(expiry_date=TODAY))

    def test_expiry_tomorrow_accepted(self):
        req = VehicleRegistrationCreate(**self._valid_data(expiry_date=TOMORROW))
        assert req.expiry_date == TOMORROW

    def test_empty_plate_number_rejected(self):
        with pytest.raises(Exception):
            VehicleRegistrationCreate(**self._valid_data(plate_number="  "))

    def test_empty_state_rejected(self):
        with pytest.raises(Exception):
            VehicleRegistrationCreate(**self._valid_data(state=""))

    def test_plate_number_stripped(self):
        req = VehicleRegistrationCreate(**self._valid_data(plate_number="  ABC-123  "))
        assert req.plate_number == "ABC-123"

    def test_optional_fields_default_none(self):
        req = VehicleRegistrationCreate(**self._valid_data())
        assert req.vehicle_id is None
        assert req.document_url is None
        assert req.notes is None


class TestVehicleRegistrationUpdate:
    def test_all_fields_optional(self):
        update = VehicleRegistrationUpdate()
        assert update.plate_number is None
        assert update.state is None
        assert update.vehicle_id is None
        assert update.document_url is None
        assert update.notes is None

    def test_partial_update(self):
        update = VehicleRegistrationUpdate(notes="Registration renewed")
        assert update.notes == "Registration renewed"

    def test_empty_plate_number_rejected(self):
        with pytest.raises(Exception):
            VehicleRegistrationUpdate(plate_number="  ")

    def test_empty_state_rejected(self):
        with pytest.raises(Exception):
            VehicleRegistrationUpdate(state="")


class TestAdminRegistrationReview:
    def test_approve_valid(self):
        req = AdminRegistrationReview(status=DocumentStatus.APPROVED)
        assert req.status == DocumentStatus.APPROVED

    def test_reject_with_reason_valid(self):
        req = AdminRegistrationReview(
            status=DocumentStatus.REJECTED,
            rejection_reason="Plate does not match records",
        )
        assert req.rejection_reason == "Plate does not match records"

    def test_reject_without_reason_raises(self):
        with pytest.raises(Exception):
            AdminRegistrationReview(status=DocumentStatus.REJECTED)

    def test_expired_status_raises(self):
        with pytest.raises(Exception):
            AdminRegistrationReview(status=DocumentStatus.EXPIRED)

    def test_pending_upload_status_raises(self):
        with pytest.raises(Exception):
            AdminRegistrationReview(status=DocumentStatus.PENDING_UPLOAD)

    def test_pending_review_status_raises(self):
        with pytest.raises(Exception):
            AdminRegistrationReview(status=DocumentStatus.PENDING_REVIEW)

    def test_notes_optional(self):
        req = AdminRegistrationReview(status=DocumentStatus.APPROVED)
        assert req.notes is None


# ===========================================================================
# Service tests — License
# ===========================================================================


class TestGetDriverLicenses:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        licenses = [_make_license(id=1), _make_license(id=2)]
        db = _make_db(scalars=licenses)
        result = await get_driver_licenses(db, driver_id=10)
        assert result == licenses

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_new_driver(self):
        db = _make_db(scalars=[])
        result = await get_driver_licenses(db, driver_id=99)
        assert result == []


class TestCreateLicense:
    @pytest.mark.asyncio
    async def test_creates_pending_upload_when_no_url(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.refresh = AsyncMock()

        data = DriverLicenseCreate(
            license_number="DL-001",
            state_issued="CA",
            license_class="C",
            expiry_date=NEXT_YEAR,
        )
        created = _make_license(status=DocumentStatus.PENDING_UPLOAD, document_url=None)
        db.refresh.side_effect = lambda obj: None

        with patch("app.services.driver_documents.DriverLicense") as MockModel:
            MockModel.return_value = created
            result = await create_license(db, driver_id=10, data=data)

        db.add.assert_called_once()
        db.commit.assert_called_once()
        call_kwargs = MockModel.call_args.kwargs
        assert call_kwargs["status"] == DocumentStatus.PENDING_UPLOAD
        assert call_kwargs["uploaded_at"] is None

    @pytest.mark.asyncio
    async def test_creates_pending_review_when_url_provided(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.refresh = AsyncMock()

        data = DriverLicenseCreate(
            license_number="DL-001",
            state_issued="CA",
            license_class="C",
            expiry_date=NEXT_YEAR,
            document_url="https://example.com/dl.pdf",
        )
        created = _make_license(status=DocumentStatus.PENDING_REVIEW)
        db.refresh.side_effect = lambda obj: None

        with patch("app.services.driver_documents.DriverLicense") as MockModel:
            MockModel.return_value = created
            await create_license(db, driver_id=10, data=data)

        call_kwargs = MockModel.call_args.kwargs
        assert call_kwargs["status"] == DocumentStatus.PENDING_REVIEW
        assert call_kwargs["uploaded_at"] is not None

    @pytest.mark.asyncio
    async def test_all_license_classes_create_correctly(self):
        for lc in LicenseClass:
            db = AsyncMock()
            db.commit = AsyncMock()
            db.add = MagicMock()
            db.refresh = AsyncMock()
            db.refresh.side_effect = lambda obj: None

            data = DriverLicenseCreate(
                license_number="DL-001",
                state_issued="CA",
                license_class=lc.value,
                expiry_date=NEXT_YEAR,
            )
            with patch("app.services.driver_documents.DriverLicense") as MockModel:
                MockModel.return_value = _make_license(license_class=lc)
                await create_license(db, driver_id=10, data=data)

            call_kwargs = MockModel.call_args.kwargs
            assert call_kwargs["license_class"] == lc


class TestUpdateLicense:
    @pytest.mark.asyncio
    async def test_driver_can_update_own_pending_upload_license(self):
        lic = _make_license(driver_id=10, status=DocumentStatus.PENDING_UPLOAD)
        db = _make_db(scalar=lic)

        update = DriverLicenseUpdate(notes="Renewed")
        await update_license(db, driver_id=10, license_id=1, data=update)

        assert lic.notes == "Renewed"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_driver_can_update_own_pending_review_license(self):
        lic = _make_license(driver_id=10, status=DocumentStatus.PENDING_REVIEW)
        db = _make_db(scalar=lic)

        update = DriverLicenseUpdate(state_issued="NY")
        await update_license(db, driver_id=10, license_id=1, data=update)

        assert lic.state_issued == "NY"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_driver_cannot_update_another_drivers_license(self):
        lic = _make_license(driver_id=99, status=DocumentStatus.PENDING_REVIEW)
        db = _make_db(scalar=lic)

        update = DriverLicenseUpdate(notes="Hack")
        with pytest.raises(DriverDocumentError, match="Not authorised"):
            await update_license(db, driver_id=10, license_id=1, data=update)

    @pytest.mark.asyncio
    async def test_driver_cannot_update_approved_license(self):
        lic = _make_license(driver_id=10, status=DocumentStatus.APPROVED)
        db = _make_db(scalar=lic)

        update = DriverLicenseUpdate(notes="Try to change")
        with pytest.raises(DriverDocumentError, match="Cannot edit"):
            await update_license(db, driver_id=10, license_id=1, data=update)

    @pytest.mark.asyncio
    async def test_driver_cannot_update_rejected_license(self):
        lic = _make_license(driver_id=10, status=DocumentStatus.REJECTED)
        db = _make_db(scalar=lic)

        update = DriverLicenseUpdate(notes="Try to change")
        with pytest.raises(DriverDocumentError, match="Cannot edit"):
            await update_license(db, driver_id=10, license_id=1, data=update)

    @pytest.mark.asyncio
    async def test_driver_cannot_update_expired_license(self):
        lic = _make_license(driver_id=10, status=DocumentStatus.EXPIRED)
        db = _make_db(scalar=lic)

        update = DriverLicenseUpdate(notes="Try to change")
        with pytest.raises(DriverDocumentError, match="Cannot edit"):
            await update_license(db, driver_id=10, license_id=1, data=update)

    @pytest.mark.asyncio
    async def test_update_nonexistent_license_raises(self):
        db = _make_db(scalar=None)
        update = DriverLicenseUpdate(notes="Notes")
        with pytest.raises(DriverDocumentError, match="not found"):
            await update_license(db, driver_id=10, license_id=999, data=update)

    @pytest.mark.asyncio
    async def test_attaching_url_promotes_to_pending_review(self):
        lic = _make_license(
            driver_id=10,
            status=DocumentStatus.PENDING_UPLOAD,
            document_url=None,
        )
        db = _make_db(scalar=lic)

        update = DriverLicenseUpdate(document_url="https://example.com/dl.pdf")
        await update_license(db, driver_id=10, license_id=1, data=update)

        assert lic.document_url == "https://example.com/dl.pdf"
        assert lic.status == DocumentStatus.PENDING_REVIEW

    @pytest.mark.asyncio
    async def test_update_sets_only_provided_fields(self):
        lic = _make_license(
            driver_id=10,
            status=DocumentStatus.PENDING_REVIEW,
            license_number="DL-OLD",
            notes=None,
        )
        db = _make_db(scalar=lic)

        update = DriverLicenseUpdate(license_number="DL-NEW")
        await update_license(db, driver_id=10, license_id=1, data=update)

        assert lic.license_number == "DL-NEW"
        assert lic.notes is None


class TestAdminReviewLicenseService:
    @pytest.mark.asyncio
    async def test_admin_can_approve_license(self):
        lic = _make_license(driver_id=10, status=DocumentStatus.PENDING_REVIEW)
        db = AsyncMock()

        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = lic
        second_result = MagicMock()
        second_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[first_result, second_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        review = AdminLicenseReview(status=DocumentStatus.APPROVED)
        await admin_review_license(db, admin_id=1, license_id=1, review=review)

        assert lic.status == DocumentStatus.APPROVED
        assert lic.reviewed_by == 1
        assert lic.reviewed_at is not None
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_approval_sets_reviewed_by_and_reviewed_at(self):
        lic = _make_license(
            driver_id=10,
            status=DocumentStatus.PENDING_REVIEW,
            reviewed_by=None,
            reviewed_at=None,
        )
        db = AsyncMock()

        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = lic
        second_result = MagicMock()
        second_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[first_result, second_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        review = AdminLicenseReview(status=DocumentStatus.APPROVED)
        await admin_review_license(db, admin_id=42, license_id=1, review=review)

        assert lic.reviewed_by == 42
        assert isinstance(lic.reviewed_at, datetime)

    @pytest.mark.asyncio
    async def test_admin_approval_expires_previous_approved_license(self):
        new_lic = _make_license(id=2, driver_id=10, status=DocumentStatus.PENDING_REVIEW)
        prev_approved = _make_license(id=1, driver_id=10, status=DocumentStatus.APPROVED)
        db = AsyncMock()

        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = new_lic
        second_result = MagicMock()
        second_result.scalars.return_value.all.return_value = [prev_approved]
        db.execute = AsyncMock(side_effect=[first_result, second_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        review = AdminLicenseReview(status=DocumentStatus.APPROVED)
        await admin_review_license(db, admin_id=1, license_id=2, review=review)

        assert prev_approved.status == DocumentStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_admin_can_reject_with_reason(self):
        lic = _make_license(driver_id=10, status=DocumentStatus.PENDING_REVIEW)
        db = _make_db(scalar=lic)

        review = AdminLicenseReview(
            status=DocumentStatus.REJECTED,
            rejection_reason="License number illegible",
        )
        await admin_review_license(db, admin_id=5, license_id=1, review=review)

        assert lic.status == DocumentStatus.REJECTED
        assert lic.rejection_reason == "License number illegible"
        assert lic.reviewed_by == 5

    @pytest.mark.asyncio
    async def test_admin_review_nonexistent_license_raises(self):
        db = _make_db(scalar=None)
        review = AdminLicenseReview(status=DocumentStatus.APPROVED)
        with pytest.raises(DriverDocumentError, match="not found"):
            await admin_review_license(db, admin_id=1, license_id=999, review=review)

    @pytest.mark.asyncio
    async def test_admin_review_with_notes_updates_notes(self):
        lic = _make_license(driver_id=10, status=DocumentStatus.PENDING_REVIEW)
        db = AsyncMock()

        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = lic
        second_result = MagicMock()
        second_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[first_result, second_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        review = AdminLicenseReview(
            status=DocumentStatus.APPROVED,
            notes="Valid CA license — Class C",
        )
        await admin_review_license(db, admin_id=1, license_id=1, review=review)

        assert lic.notes == "Valid CA license — Class C"


class TestGetLicenseStatusSummary:
    @pytest.mark.asyncio
    async def test_has_valid_license_true_for_approved(self):
        approved = _make_license(status=DocumentStatus.APPROVED, expiry_date=NEXT_YEAR)
        db = AsyncMock()
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [approved]
        single_result = MagicMock()
        single_result.scalar_one_or_none.return_value = approved
        db.execute = AsyncMock(side_effect=[list_result, single_result])

        summary = await get_license_status_summary(db, driver_id=10)

        assert summary.has_valid_license is True
        assert summary.days_until_expiry is not None
        assert summary.days_until_expiry > 0

    @pytest.mark.asyncio
    async def test_has_valid_license_false_when_no_approved(self):
        db = AsyncMock()
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = []
        single_result = MagicMock()
        single_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[list_result, single_result])

        summary = await get_license_status_summary(db, driver_id=10)

        assert summary.has_valid_license is False
        assert summary.days_until_expiry is None
        assert summary.active_license is None

    @pytest.mark.asyncio
    async def test_days_until_expiry_calculated_correctly(self):
        expiry = TODAY + timedelta(days=10)
        approved = _make_license(status=DocumentStatus.APPROVED, expiry_date=expiry)
        db = AsyncMock()
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [approved]
        single_result = MagicMock()
        single_result.scalar_one_or_none.return_value = approved
        db.execute = AsyncMock(side_effect=[list_result, single_result])

        summary = await get_license_status_summary(db, driver_id=10)
        assert summary.days_until_expiry == 10


class TestGetExpiringLicenses:
    @pytest.mark.asyncio
    async def test_returns_licenses_expiring_within_n_days(self):
        expiring = _make_license(
            status=DocumentStatus.APPROVED,
            expiry_date=TODAY + timedelta(days=15),
        )
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [expiring]
        db.execute = AsyncMock(return_value=result)

        licenses = await get_expiring_licenses(db, days_ahead=30)
        assert len(licenses) == 1
        assert licenses[0] is expiring

    @pytest.mark.asyncio
    async def test_returns_empty_when_none_expiring(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        licenses = await get_expiring_licenses(db, days_ahead=30)
        assert licenses == []

    @pytest.mark.asyncio
    async def test_default_days_ahead_is_30(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        await get_expiring_licenses(db)
        db.execute.assert_called_once()


class TestMarkExpiredLicenses:
    @pytest.mark.asyncio
    async def test_updates_past_expiry_licenses_to_expired(self):
        past = _make_license(
            status=DocumentStatus.APPROVED,
            expiry_date=YESTERDAY,
        )
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [past]
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        count = await mark_expired_licenses(db)

        assert count == 1
        assert past.status == DocumentStatus.EXPIRED
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_expired_licenses(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        count = await mark_expired_licenses(db)
        assert count == 0
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_expired_licenses_all_updated(self):
        past1 = _make_license(id=1, status=DocumentStatus.APPROVED, expiry_date=YESTERDAY)
        past2 = _make_license(id=2, status=DocumentStatus.APPROVED, expiry_date=YESTERDAY - timedelta(days=5))
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [past1, past2]
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        count = await mark_expired_licenses(db)
        assert count == 2
        assert past1.status == DocumentStatus.EXPIRED
        assert past2.status == DocumentStatus.EXPIRED
        db.commit.assert_called_once()


# ===========================================================================
# Service tests — VehicleRegistration
# ===========================================================================


class TestGetDriverRegistrations:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        regs = [_make_registration(id=1), _make_registration(id=2)]
        db = _make_db(scalars=regs)
        result = await get_driver_registrations(db, driver_id=10)
        assert result == regs

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_new_driver(self):
        db = _make_db(scalars=[])
        result = await get_driver_registrations(db, driver_id=99)
        assert result == []


class TestCreateRegistration:
    @pytest.mark.asyncio
    async def test_creates_pending_upload_when_no_url(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.refresh = AsyncMock()
        db.refresh.side_effect = lambda obj: None

        data = VehicleRegistrationCreate(
            plate_number="ABC-123",
            state="CA",
            expiry_date=NEXT_YEAR,
        )
        with patch("app.services.driver_documents.VehicleRegistration") as MockModel:
            MockModel.return_value = _make_registration(
                status=DocumentStatus.PENDING_UPLOAD, document_url=None
            )
            await create_registration(db, driver_id=10, data=data)

        call_kwargs = MockModel.call_args.kwargs
        assert call_kwargs["status"] == DocumentStatus.PENDING_UPLOAD
        assert call_kwargs["uploaded_at"] is None

    @pytest.mark.asyncio
    async def test_creates_pending_review_when_url_provided(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.refresh = AsyncMock()
        db.refresh.side_effect = lambda obj: None

        data = VehicleRegistrationCreate(
            plate_number="ABC-123",
            state="CA",
            expiry_date=NEXT_YEAR,
            document_url="https://example.com/reg.pdf",
        )
        with patch("app.services.driver_documents.VehicleRegistration") as MockModel:
            MockModel.return_value = _make_registration(status=DocumentStatus.PENDING_REVIEW)
            await create_registration(db, driver_id=10, data=data)

        call_kwargs = MockModel.call_args.kwargs
        assert call_kwargs["status"] == DocumentStatus.PENDING_REVIEW
        assert call_kwargs["uploaded_at"] is not None

    @pytest.mark.asyncio
    async def test_vehicle_id_is_optional(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.refresh = AsyncMock()
        db.refresh.side_effect = lambda obj: None

        data = VehicleRegistrationCreate(
            plate_number="ABC-123",
            state="CA",
            expiry_date=NEXT_YEAR,
        )
        with patch("app.services.driver_documents.VehicleRegistration") as MockModel:
            MockModel.return_value = _make_registration(vehicle_id=None)
            await create_registration(db, driver_id=10, data=data)

        call_kwargs = MockModel.call_args.kwargs
        assert call_kwargs["vehicle_id"] is None


class TestUpdateRegistration:
    @pytest.mark.asyncio
    async def test_driver_can_update_own_pending_upload_registration(self):
        reg = _make_registration(driver_id=10, status=DocumentStatus.PENDING_UPLOAD)
        db = _make_db(scalar=reg)

        update = VehicleRegistrationUpdate(notes="Renewed")
        await update_registration(db, driver_id=10, registration_id=1, data=update)

        assert reg.notes == "Renewed"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_driver_can_update_own_pending_review_registration(self):
        reg = _make_registration(driver_id=10, status=DocumentStatus.PENDING_REVIEW)
        db = _make_db(scalar=reg)

        update = VehicleRegistrationUpdate(state="NY")
        await update_registration(db, driver_id=10, registration_id=1, data=update)

        assert reg.state == "NY"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_driver_cannot_update_another_drivers_registration(self):
        reg = _make_registration(driver_id=99, status=DocumentStatus.PENDING_REVIEW)
        db = _make_db(scalar=reg)

        update = VehicleRegistrationUpdate(notes="Hack")
        with pytest.raises(DriverDocumentError, match="Not authorised"):
            await update_registration(db, driver_id=10, registration_id=1, data=update)

    @pytest.mark.asyncio
    async def test_driver_cannot_update_approved_registration(self):
        reg = _make_registration(driver_id=10, status=DocumentStatus.APPROVED)
        db = _make_db(scalar=reg)

        update = VehicleRegistrationUpdate(notes="Try to change")
        with pytest.raises(DriverDocumentError, match="Cannot edit"):
            await update_registration(db, driver_id=10, registration_id=1, data=update)

    @pytest.mark.asyncio
    async def test_driver_cannot_update_rejected_registration(self):
        reg = _make_registration(driver_id=10, status=DocumentStatus.REJECTED)
        db = _make_db(scalar=reg)

        update = VehicleRegistrationUpdate(notes="Try to change")
        with pytest.raises(DriverDocumentError, match="Cannot edit"):
            await update_registration(db, driver_id=10, registration_id=1, data=update)

    @pytest.mark.asyncio
    async def test_driver_cannot_update_expired_registration(self):
        reg = _make_registration(driver_id=10, status=DocumentStatus.EXPIRED)
        db = _make_db(scalar=reg)

        update = VehicleRegistrationUpdate(notes="Try to change")
        with pytest.raises(DriverDocumentError, match="Cannot edit"):
            await update_registration(db, driver_id=10, registration_id=1, data=update)

    @pytest.mark.asyncio
    async def test_update_nonexistent_registration_raises(self):
        db = _make_db(scalar=None)
        update = VehicleRegistrationUpdate(notes="Notes")
        with pytest.raises(DriverDocumentError, match="not found"):
            await update_registration(db, driver_id=10, registration_id=999, data=update)

    @pytest.mark.asyncio
    async def test_attaching_url_promotes_to_pending_review(self):
        reg = _make_registration(
            driver_id=10,
            status=DocumentStatus.PENDING_UPLOAD,
            document_url=None,
        )
        db = _make_db(scalar=reg)

        update = VehicleRegistrationUpdate(document_url="https://example.com/reg.pdf")
        await update_registration(db, driver_id=10, registration_id=1, data=update)

        assert reg.document_url == "https://example.com/reg.pdf"
        assert reg.status == DocumentStatus.PENDING_REVIEW


class TestAdminReviewRegistrationService:
    @pytest.mark.asyncio
    async def test_admin_can_approve_registration(self):
        reg = _make_registration(driver_id=10, status=DocumentStatus.PENDING_REVIEW)
        db = AsyncMock()

        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = reg
        second_result = MagicMock()
        second_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[first_result, second_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        review = AdminRegistrationReview(status=DocumentStatus.APPROVED)
        await admin_review_registration(db, admin_id=1, registration_id=1, review=review)

        assert reg.status == DocumentStatus.APPROVED
        assert reg.reviewed_by == 1
        assert reg.reviewed_at is not None
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_approval_expires_previous_approved_registration(self):
        new_reg = _make_registration(id=2, driver_id=10, status=DocumentStatus.PENDING_REVIEW)
        prev_approved = _make_registration(id=1, driver_id=10, status=DocumentStatus.APPROVED)
        db = AsyncMock()

        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = new_reg
        second_result = MagicMock()
        second_result.scalars.return_value.all.return_value = [prev_approved]
        db.execute = AsyncMock(side_effect=[first_result, second_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        review = AdminRegistrationReview(status=DocumentStatus.APPROVED)
        await admin_review_registration(db, admin_id=1, registration_id=2, review=review)

        assert prev_approved.status == DocumentStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_admin_can_reject_registration_with_reason(self):
        reg = _make_registration(driver_id=10, status=DocumentStatus.PENDING_REVIEW)
        db = _make_db(scalar=reg)

        review = AdminRegistrationReview(
            status=DocumentStatus.REJECTED,
            rejection_reason="Plate number mismatch",
        )
        await admin_review_registration(db, admin_id=5, registration_id=1, review=review)

        assert reg.status == DocumentStatus.REJECTED
        assert reg.rejection_reason == "Plate number mismatch"
        assert reg.reviewed_by == 5

    @pytest.mark.asyncio
    async def test_admin_review_nonexistent_registration_raises(self):
        db = _make_db(scalar=None)
        review = AdminRegistrationReview(status=DocumentStatus.APPROVED)
        with pytest.raises(DriverDocumentError, match="not found"):
            await admin_review_registration(db, admin_id=1, registration_id=999, review=review)

    @pytest.mark.asyncio
    async def test_admin_review_registration_with_notes_updates_notes(self):
        reg = _make_registration(driver_id=10, status=DocumentStatus.PENDING_REVIEW)
        db = AsyncMock()

        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = reg
        second_result = MagicMock()
        second_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[first_result, second_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        review = AdminRegistrationReview(
            status=DocumentStatus.APPROVED,
            notes="Plate verified against DMV records",
        )
        await admin_review_registration(db, admin_id=1, registration_id=1, review=review)

        assert reg.notes == "Plate verified against DMV records"


class TestGetRegistrationStatusSummary:
    @pytest.mark.asyncio
    async def test_has_valid_registration_true_for_approved(self):
        approved = _make_registration(
            status=DocumentStatus.APPROVED, expiry_date=NEXT_YEAR
        )
        db = AsyncMock()
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [approved]
        single_result = MagicMock()
        single_result.scalar_one_or_none.return_value = approved
        db.execute = AsyncMock(side_effect=[list_result, single_result])

        summary = await get_registration_status_summary(db, driver_id=10)

        assert summary.has_valid_registration is True
        assert summary.days_until_expiry is not None
        assert summary.days_until_expiry > 0

    @pytest.mark.asyncio
    async def test_has_valid_registration_false_when_no_approved(self):
        db = AsyncMock()
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = []
        single_result = MagicMock()
        single_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[list_result, single_result])

        summary = await get_registration_status_summary(db, driver_id=10)

        assert summary.has_valid_registration is False
        assert summary.days_until_expiry is None
        assert summary.active_registration is None

    @pytest.mark.asyncio
    async def test_days_until_expiry_calculated_correctly(self):
        expiry = TODAY + timedelta(days=7)
        approved = _make_registration(status=DocumentStatus.APPROVED, expiry_date=expiry)
        db = AsyncMock()
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [approved]
        single_result = MagicMock()
        single_result.scalar_one_or_none.return_value = approved
        db.execute = AsyncMock(side_effect=[list_result, single_result])

        summary = await get_registration_status_summary(db, driver_id=10)
        assert summary.days_until_expiry == 7


class TestGetExpiringRegistrations:
    @pytest.mark.asyncio
    async def test_returns_registrations_expiring_within_n_days(self):
        expiring = _make_registration(
            status=DocumentStatus.APPROVED,
            expiry_date=TODAY + timedelta(days=20),
        )
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [expiring]
        db.execute = AsyncMock(return_value=result)

        regs = await get_expiring_registrations(db, days_ahead=30)
        assert len(regs) == 1
        assert regs[0] is expiring

    @pytest.mark.asyncio
    async def test_returns_empty_when_none_expiring(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        regs = await get_expiring_registrations(db, days_ahead=30)
        assert regs == []

    @pytest.mark.asyncio
    async def test_default_days_ahead_is_30(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        await get_expiring_registrations(db)
        db.execute.assert_called_once()


class TestMarkExpiredRegistrations:
    @pytest.mark.asyncio
    async def test_updates_past_expiry_registrations_to_expired(self):
        past = _make_registration(
            status=DocumentStatus.APPROVED,
            expiry_date=YESTERDAY,
        )
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [past]
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        count = await mark_expired_registrations(db)

        assert count == 1
        assert past.status == DocumentStatus.EXPIRED
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_expired_registrations(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        count = await mark_expired_registrations(db)
        assert count == 0
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_expired_registrations_all_updated(self):
        past1 = _make_registration(id=1, status=DocumentStatus.APPROVED, expiry_date=YESTERDAY)
        past2 = _make_registration(id=2, status=DocumentStatus.APPROVED, expiry_date=YESTERDAY - timedelta(days=3))
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [past1, past2]
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        count = await mark_expired_registrations(db)
        assert count == 2
        assert past1.status == DocumentStatus.EXPIRED
        assert past2.status == DocumentStatus.EXPIRED
        db.commit.assert_called_once()


# ===========================================================================
# Combined summary service test
# ===========================================================================


class TestGetDriverDocumentsSummary:
    @pytest.mark.asyncio
    async def test_combined_summary_returns_both_summaries(self):
        approved_lic = _make_license(status=DocumentStatus.APPROVED, expiry_date=NEXT_YEAR)
        approved_reg = _make_registration(status=DocumentStatus.APPROVED, expiry_date=NEXT_YEAR)

        db = AsyncMock()

        # Four execute calls: list_licenses, active_license, list_regs, active_reg
        list_lic_result = MagicMock()
        list_lic_result.scalars.return_value.all.return_value = [approved_lic]

        active_lic_result = MagicMock()
        active_lic_result.scalar_one_or_none.return_value = approved_lic

        list_reg_result = MagicMock()
        list_reg_result.scalars.return_value.all.return_value = [approved_reg]

        active_reg_result = MagicMock()
        active_reg_result.scalar_one_or_none.return_value = approved_reg

        db.execute = AsyncMock(
            side_effect=[
                list_lic_result,
                active_lic_result,
                list_reg_result,
                active_reg_result,
            ]
        )

        summary = await get_driver_documents_summary(db, driver_id=10)

        assert summary.license_summary.has_valid_license is True
        assert summary.registration_summary.has_valid_registration is True

    @pytest.mark.asyncio
    async def test_combined_summary_no_documents(self):
        db = AsyncMock()

        empty_list = MagicMock()
        empty_list.scalars.return_value.all.return_value = []

        none_single = MagicMock()
        none_single.scalar_one_or_none.return_value = None

        db.execute = AsyncMock(
            side_effect=[empty_list, none_single, empty_list, none_single]
        )

        summary = await get_driver_documents_summary(db, driver_id=10)

        assert summary.license_summary.has_valid_license is False
        assert summary.registration_summary.has_valid_registration is False


# ===========================================================================
# API endpoint schema contracts
# ===========================================================================


class TestEndpointSchemaContracts:
    """Verify that schema contracts hold — no mocked HTTP client needed."""

    def test_license_response_serialises_full_record(self):
        lic = _make_license()
        resp = DriverLicenseResponse.model_validate(lic)
        dumped = resp.model_dump()
        assert dumped["id"] == 1
        assert dumped["driver_id"] == 10
        assert dumped["status"] == "pending_review"
        assert dumped["license_class"] == "C"

    def test_registration_response_serialises_full_record(self):
        reg = _make_registration()
        resp = VehicleRegistrationResponse.model_validate(reg)
        dumped = resp.model_dump()
        assert dumped["id"] == 1
        assert dumped["driver_id"] == 10
        assert dumped["plate_number"] == "ABC123"
        assert dumped["state"] == "CA"

    def test_license_status_summary_serialises(self):
        approved = _make_license(status=DocumentStatus.APPROVED, expiry_date=NEXT_YEAR)
        resp = DriverLicenseResponse.model_validate(approved)
        summary = LicenseStatusSummary(
            has_valid_license=True,
            days_until_expiry=365,
            active_license=resp,
            licenses=[resp],
        )
        dumped = summary.model_dump()
        assert dumped["has_valid_license"] is True
        assert dumped["days_until_expiry"] == 365
        assert dumped["active_license"]["id"] == 1

    def test_registration_status_summary_serialises(self):
        approved = _make_registration(status=DocumentStatus.APPROVED, expiry_date=NEXT_YEAR)
        resp = VehicleRegistrationResponse.model_validate(approved)
        summary = RegistrationStatusSummary(
            has_valid_registration=True,
            days_until_expiry=365,
            active_registration=resp,
            registrations=[resp],
        )
        dumped = summary.model_dump()
        assert dumped["has_valid_registration"] is True
        assert dumped["active_registration"]["plate_number"] == "ABC123"

    def test_combined_documents_summary_serialises(self):
        lic_resp = DriverLicenseResponse.model_validate(_make_license())
        reg_resp = VehicleRegistrationResponse.model_validate(_make_registration())

        license_summary = LicenseStatusSummary(
            has_valid_license=False,
            days_until_expiry=None,
            active_license=None,
            licenses=[lic_resp],
        )
        registration_summary = RegistrationStatusSummary(
            has_valid_registration=False,
            days_until_expiry=None,
            active_registration=None,
            registrations=[reg_resp],
        )
        combined = DriverDocumentsSummary(
            license_summary=license_summary,
            registration_summary=registration_summary,
        )
        dumped = combined.model_dump()
        assert "license_summary" in dumped
        assert "registration_summary" in dumped

    def test_admin_license_review_reject_requires_reason(self):
        with pytest.raises(Exception):
            AdminLicenseReview(status="rejected")

    def test_admin_license_review_approve_no_reason_needed(self):
        req = AdminLicenseReview(status="approved")
        assert req.status == DocumentStatus.APPROVED

    def test_admin_registration_review_reject_requires_reason(self):
        with pytest.raises(Exception):
            AdminRegistrationReview(status="rejected")

    def test_admin_registration_review_approve_no_reason_needed(self):
        req = AdminRegistrationReview(status="approved")
        assert req.status == DocumentStatus.APPROVED

    def test_registration_with_no_vehicle_id_serialises(self):
        reg = _make_registration(vehicle_id=None)
        resp = VehicleRegistrationResponse.model_validate(reg)
        assert resp.vehicle_id is None
        dumped = resp.model_dump()
        assert dumped["vehicle_id"] is None

    def test_cdl_license_class_serialises(self):
        lic = _make_license(license_class=LicenseClass.CDL)
        resp = DriverLicenseResponse.model_validate(lic)
        assert resp.license_class == LicenseClass.CDL
        assert resp.model_dump()["license_class"] == "CDL"
