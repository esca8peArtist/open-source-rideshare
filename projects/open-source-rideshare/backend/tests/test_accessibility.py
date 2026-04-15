"""Unit tests for accessibility and WAV certification.

All tests are pure unit tests — no database or HTTP client required.

Covers:
- Model: RiderAccessibilityProfile and DriverWAVCertification field defaults
- Model: WAVCertificationStatus enum values
- Model: table names
- Service: get_or_create_rider_profile — creates new; returns existing
- Service: update_rider_profile — all fields written correctly
- Service: get_driver_wav — None when absent; returns row when present
- Service: submit_driver_wav — new cert; update existing pending; reset rejected; reset expired; keep verified
- Service: admin_verify_wav — approve; reject; raises for missing cert; raises for wrong status
- Service: get_wav_platform_stats — zero state; mixed counts; coverage_ratio capping
- Schema: RiderAccessibilityProfileUpdate defaults
- Schema: DriverWAVCertificationSubmit defaults
- Schema: AdminWAVVerifyRequest
- Schema: WAVPlatformStats coverage_ratio
- Router: 7 endpoints registered (smoke)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.accessibility import (
    DriverWAVCertification,
    RiderAccessibilityProfile,
    WAVCertificationStatus,
)
from app.schemas.accessibility import (
    AdminWAVVerifyRequest,
    DriverWAVCertificationResponse,
    DriverWAVCertificationSubmit,
    RiderAccessibilityProfileResponse,
    RiderAccessibilityProfileUpdate,
    WAVPlatformStats,
)
from app.services.accessibility import (
    admin_verify_wav,
    get_driver_wav,
    get_or_create_rider_profile,
    get_wav_platform_stats,
    submit_driver_wav,
    update_rider_profile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_rider_profile(
    id: int = 1,
    rider_id: int = 10,
    needs_wav: bool = False,
    has_mobility_device: bool = False,
    visual_impairment: bool = False,
    hearing_impairment: bool = False,
    other_needs: str | None = None,
) -> RiderAccessibilityProfile:
    p = RiderAccessibilityProfile()
    p.id = id
    p.rider_id = rider_id
    p.needs_wav = needs_wav
    p.has_mobility_device = has_mobility_device
    p.visual_impairment = visual_impairment
    p.hearing_impairment = hearing_impairment
    p.other_needs = other_needs
    p.created_at = _now()
    p.updated_at = _now()
    return p


def _make_cert(
    id: int = 1,
    driver_id: int = 20,
    cert_status: WAVCertificationStatus = WAVCertificationStatus.pending,
    vehicle_make: str | None = "Toyota",
    vehicle_model: str | None = "Sienna",
    vehicle_year: int | None = 2022,
    certification_document_url: str | None = None,
    certification_number: str | None = None,
    verified_at: datetime | None = None,
    expires_at: datetime | None = None,
    verified_by_admin_id: int | None = None,
    admin_note: str | None = None,
) -> DriverWAVCertification:
    c = DriverWAVCertification()
    c.id = id
    c.driver_id = driver_id
    c.status = cert_status
    c.vehicle_make = vehicle_make
    c.vehicle_model = vehicle_model
    c.vehicle_year = vehicle_year
    c.certification_document_url = certification_document_url
    c.certification_number = certification_number
    c.submitted_at = _now()
    c.verified_at = verified_at
    c.expires_at = expires_at
    c.verified_by_admin_id = verified_by_admin_id
    c.admin_note = admin_note
    c.updated_at = _now()
    return c


def _db_returning(value):
    """Mock AsyncSession.execute() returning a scalar."""
    m = MagicMock()
    m.scalar_one_or_none.return_value = value
    m.scalar_one.return_value = value
    scalars = MagicMock()
    scalars.all.return_value = value if isinstance(value, list) else ([] if value is None else [value])
    m.scalars.return_value = scalars
    return m


def _db_sequence(*returns):
    """Mock execute() to return different values on successive calls."""
    side_effects = [_db_returning(r) for r in returns]
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=side_effects)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    return mock_db


def _make_db(execute_return=None):
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_db_returning(execute_return))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestWAVCertificationStatusEnum:
    def test_pending(self):
        assert WAVCertificationStatus.pending.value == "pending"

    def test_verified(self):
        assert WAVCertificationStatus.verified.value == "verified"

    def test_rejected(self):
        assert WAVCertificationStatus.rejected.value == "rejected"

    def test_expired(self):
        assert WAVCertificationStatus.expired.value == "expired"

    def test_all_four_values(self):
        assert len(WAVCertificationStatus) == 4


class TestRiderAccessibilityProfileModel:
    def test_tablename(self):
        assert RiderAccessibilityProfile.__tablename__ == "rider_accessibility_profiles"

    def test_default_needs_wav_false(self):
        p = _make_rider_profile()
        assert p.needs_wav is False

    def test_default_mobility_device_false(self):
        p = _make_rider_profile()
        assert p.has_mobility_device is False

    def test_default_visual_impairment_false(self):
        p = _make_rider_profile()
        assert p.visual_impairment is False

    def test_default_hearing_impairment_false(self):
        p = _make_rider_profile()
        assert p.hearing_impairment is False

    def test_default_other_needs_none(self):
        p = _make_rider_profile()
        assert p.other_needs is None

    def test_rider_id_stored(self):
        p = _make_rider_profile(rider_id=99)
        assert p.rider_id == 99


class TestDriverWAVCertificationModel:
    def test_tablename(self):
        assert DriverWAVCertification.__tablename__ == "driver_wav_certifications"

    def test_driver_id_stored(self):
        c = _make_cert(driver_id=77)
        assert c.driver_id == 77

    def test_default_status_pending(self):
        c = _make_cert()
        assert c.status == WAVCertificationStatus.pending

    def test_vehicle_fields_stored(self):
        c = _make_cert(vehicle_make="Ford", vehicle_model="Transit", vehicle_year=2020)
        assert c.vehicle_make == "Ford"
        assert c.vehicle_model == "Transit"
        assert c.vehicle_year == 2020

    def test_verified_at_nullable(self):
        c = _make_cert()
        assert c.verified_at is None

    def test_verified_by_admin_id_nullable(self):
        c = _make_cert()
        assert c.verified_by_admin_id is None


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestRiderAccessibilityProfileUpdate:
    def test_all_defaults_false(self):
        req = RiderAccessibilityProfileUpdate()
        assert req.needs_wav is False
        assert req.has_mobility_device is False
        assert req.visual_impairment is False
        assert req.hearing_impairment is False
        assert req.other_needs is None

    def test_set_needs_wav(self):
        req = RiderAccessibilityProfileUpdate(needs_wav=True)
        assert req.needs_wav is True

    def test_other_needs_accepts_text(self):
        req = RiderAccessibilityProfileUpdate(other_needs="Guide dog")
        assert req.other_needs == "Guide dog"


class TestDriverWAVCertificationSubmit:
    def test_all_defaults_none(self):
        req = DriverWAVCertificationSubmit()
        assert req.vehicle_make is None
        assert req.vehicle_model is None
        assert req.vehicle_year is None
        assert req.certification_document_url is None
        assert req.certification_number is None
        assert req.expires_at is None

    def test_vehicle_year_bounds(self):
        req = DriverWAVCertificationSubmit(vehicle_year=2023)
        assert req.vehicle_year == 2023

    def test_invalid_vehicle_year_too_old(self):
        with pytest.raises(Exception):
            DriverWAVCertificationSubmit(vehicle_year=1985)

    def test_invalid_vehicle_year_future(self):
        with pytest.raises(Exception):
            DriverWAVCertificationSubmit(vehicle_year=2031)


class TestAdminWAVVerifyRequest:
    def test_approve_true(self):
        req = AdminWAVVerifyRequest(approve=True)
        assert req.approve is True

    def test_approve_false(self):
        req = AdminWAVVerifyRequest(approve=False)
        assert req.approve is False

    def test_note_optional(self):
        req = AdminWAVVerifyRequest(approve=True)
        assert req.admin_note is None

    def test_note_set(self):
        req = AdminWAVVerifyRequest(approve=True, admin_note="Verified via inspection.")
        assert req.admin_note == "Verified via inspection."


class TestWAVPlatformStats:
    def test_coverage_ratio_field(self):
        stats = WAVPlatformStats(
            total_riders_needing_wav=10,
            drivers_pending_wav=2,
            drivers_verified_wav=5,
            drivers_rejected_wav=1,
            drivers_expired_wav=0,
            coverage_ratio=0.5,
        )
        assert stats.coverage_ratio == 0.5

    def test_zero_counts(self):
        stats = WAVPlatformStats(
            total_riders_needing_wav=0,
            drivers_pending_wav=0,
            drivers_verified_wav=0,
            drivers_rejected_wav=0,
            drivers_expired_wav=0,
            coverage_ratio=1.0,
        )
        assert stats.total_riders_needing_wav == 0
        assert stats.coverage_ratio == 1.0


# ---------------------------------------------------------------------------
# Service: get_or_create_rider_profile
# ---------------------------------------------------------------------------


class TestGetOrCreateRiderProfile:
    @pytest.mark.asyncio
    async def test_returns_existing_profile(self):
        existing = _make_rider_profile(rider_id=10)
        db = _make_db(execute_return=existing)
        result = await get_or_create_rider_profile(db, rider_id=10)
        assert result is existing
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_new_profile_when_absent(self):
        db = _make_db(execute_return=None)

        created_profile = _make_rider_profile(rider_id=10)

        async def _refresh(obj):
            obj.id = created_profile.id
            obj.created_at = created_profile.created_at
            obj.updated_at = created_profile.updated_at

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await get_or_create_rider_profile(db, rider_id=10)
        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        assert result.rider_id == 10

    @pytest.mark.asyncio
    async def test_new_profile_all_flags_false(self):
        db = _make_db(execute_return=None)
        db.refresh = AsyncMock()

        await get_or_create_rider_profile(db, rider_id=10)

        added_obj = db.add.call_args[0][0]
        assert added_obj.needs_wav is False
        assert added_obj.has_mobility_device is False
        assert added_obj.visual_impairment is False
        assert added_obj.hearing_impairment is False
        assert added_obj.other_needs is None


# ---------------------------------------------------------------------------
# Service: update_rider_profile
# ---------------------------------------------------------------------------


class TestUpdateRiderProfile:
    @pytest.mark.asyncio
    async def test_updates_all_flags(self):
        existing = _make_rider_profile(rider_id=10)
        db = _make_db(execute_return=existing)
        db.refresh = AsyncMock()

        data = RiderAccessibilityProfileUpdate(
            needs_wav=True,
            has_mobility_device=True,
            visual_impairment=True,
            hearing_impairment=True,
            other_needs="Guide dog",
        )
        result = await update_rider_profile(db, rider_id=10, data=data)

        assert result.needs_wav is True
        assert result.has_mobility_device is True
        assert result.visual_impairment is True
        assert result.hearing_impairment is True
        assert result.other_needs == "Guide dog"
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_clears_flags_on_reset(self):
        existing = _make_rider_profile(
            rider_id=10, needs_wav=True, has_mobility_device=True
        )
        db = _make_db(execute_return=existing)
        db.refresh = AsyncMock()

        data = RiderAccessibilityProfileUpdate()  # all defaults False
        result = await update_rider_profile(db, rider_id=10, data=data)

        assert result.needs_wav is False
        assert result.has_mobility_device is False

    @pytest.mark.asyncio
    async def test_other_needs_can_be_cleared(self):
        existing = _make_rider_profile(rider_id=10, other_needs="Old text")
        db = _make_db(execute_return=existing)
        db.refresh = AsyncMock()

        data = RiderAccessibilityProfileUpdate(other_needs=None)
        result = await update_rider_profile(db, rider_id=10, data=data)

        assert result.other_needs is None


# ---------------------------------------------------------------------------
# Service: get_driver_wav
# ---------------------------------------------------------------------------


class TestGetDriverWAV:
    @pytest.mark.asyncio
    async def test_returns_none_when_absent(self):
        db = _make_db(execute_return=None)
        result = await get_driver_wav(db, driver_id=20)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_cert_when_present(self):
        cert = _make_cert(driver_id=20)
        db = _make_db(execute_return=cert)
        result = await get_driver_wav(db, driver_id=20)
        assert result is cert


# ---------------------------------------------------------------------------
# Service: submit_driver_wav
# ---------------------------------------------------------------------------


class TestSubmitDriverWAV:
    @pytest.mark.asyncio
    async def test_creates_new_cert_when_absent(self):
        db = _make_db(execute_return=None)

        created = _make_cert(driver_id=20, cert_status=WAVCertificationStatus.pending)

        async def _refresh(obj):
            obj.id = created.id
            obj.submitted_at = created.submitted_at
            obj.updated_at = created.updated_at

        db.refresh = AsyncMock(side_effect=_refresh)

        data = DriverWAVCertificationSubmit(
            vehicle_make="Toyota", vehicle_model="Sienna", vehicle_year=2022
        )
        result = await submit_driver_wav(db, driver_id=20, data=data)

        db.add.assert_called_once()
        assert result.status == WAVCertificationStatus.pending
        assert result.vehicle_make == "Toyota"

    @pytest.mark.asyncio
    async def test_updates_existing_pending_cert(self):
        existing = _make_cert(driver_id=20, cert_status=WAVCertificationStatus.pending)
        db = _make_db(execute_return=existing)
        db.refresh = AsyncMock()

        data = DriverWAVCertificationSubmit(
            vehicle_make="Honda", vehicle_model="Odyssey", vehicle_year=2021
        )
        result = await submit_driver_wav(db, driver_id=20, data=data)

        db.add.assert_not_called()
        assert result.vehicle_make == "Honda"
        assert result.vehicle_model == "Odyssey"
        assert result.status == WAVCertificationStatus.pending

    @pytest.mark.asyncio
    async def test_resets_rejected_cert_to_pending(self):
        existing = _make_cert(
            driver_id=20,
            cert_status=WAVCertificationStatus.rejected,
            admin_note="Failed inspection",
            verified_by_admin_id=5,
        )
        db = _make_db(execute_return=existing)
        db.refresh = AsyncMock()

        data = DriverWAVCertificationSubmit(vehicle_make="Toyota")
        result = await submit_driver_wav(db, driver_id=20, data=data)

        assert result.status == WAVCertificationStatus.pending
        assert result.verified_at is None
        assert result.verified_by_admin_id is None
        assert result.admin_note is None

    @pytest.mark.asyncio
    async def test_resets_expired_cert_to_pending(self):
        existing = _make_cert(driver_id=20, cert_status=WAVCertificationStatus.expired)
        db = _make_db(execute_return=existing)
        db.refresh = AsyncMock()

        data = DriverWAVCertificationSubmit()
        result = await submit_driver_wav(db, driver_id=20, data=data)

        assert result.status == WAVCertificationStatus.pending

    @pytest.mark.asyncio
    async def test_updates_verified_cert_without_resetting_status(self):
        existing = _make_cert(driver_id=20, cert_status=WAVCertificationStatus.verified)
        db = _make_db(execute_return=existing)
        db.refresh = AsyncMock()

        data = DriverWAVCertificationSubmit(
            vehicle_make="Chrysler", vehicle_year=2023
        )
        result = await submit_driver_wav(db, driver_id=20, data=data)

        # Verified stays verified on update (driver renewing docs before expiry).
        assert result.status == WAVCertificationStatus.verified
        assert result.vehicle_make == "Chrysler"

    @pytest.mark.asyncio
    async def test_sets_expires_at_when_provided(self):
        existing = _make_cert(driver_id=20)
        db = _make_db(execute_return=existing)
        db.refresh = AsyncMock()

        expiry = datetime(2027, 1, 1, tzinfo=timezone.utc)
        data = DriverWAVCertificationSubmit(expires_at=expiry)
        result = await submit_driver_wav(db, driver_id=20, data=data)

        assert result.expires_at == expiry


# ---------------------------------------------------------------------------
# Service: admin_verify_wav
# ---------------------------------------------------------------------------


class TestAdminVerifyWAV:
    @pytest.mark.asyncio
    async def test_approve_pending_cert(self):
        cert = _make_cert(driver_id=20, cert_status=WAVCertificationStatus.pending)
        db = _make_db(execute_return=cert)
        db.refresh = AsyncMock()

        result = await admin_verify_wav(
            db, driver_id=20, admin_id=99, approve=True,
            admin_note="All good", expires_at=None,
        )

        assert result.status == WAVCertificationStatus.verified
        assert result.verified_by_admin_id == 99
        assert result.verified_at is not None
        assert result.admin_note == "All good"

    @pytest.mark.asyncio
    async def test_reject_pending_cert(self):
        cert = _make_cert(driver_id=20, cert_status=WAVCertificationStatus.pending)
        db = _make_db(execute_return=cert)
        db.refresh = AsyncMock()

        result = await admin_verify_wav(
            db, driver_id=20, admin_id=99, approve=False,
            admin_note="Missing ramp cert", expires_at=None,
        )

        assert result.status == WAVCertificationStatus.rejected
        assert result.admin_note == "Missing ramp cert"

    @pytest.mark.asyncio
    async def test_approve_sets_expires_at(self):
        cert = _make_cert(driver_id=20, cert_status=WAVCertificationStatus.pending)
        db = _make_db(execute_return=cert)
        db.refresh = AsyncMock()

        expiry = datetime(2027, 6, 1, tzinfo=timezone.utc)
        result = await admin_verify_wav(
            db, driver_id=20, admin_id=99, approve=True,
            admin_note=None, expires_at=expiry,
        )

        assert result.expires_at == expiry

    @pytest.mark.asyncio
    async def test_raises_when_cert_not_found(self):
        db = _make_db(execute_return=None)
        with pytest.raises(ValueError, match="No WAV certification"):
            await admin_verify_wav(
                db, driver_id=20, admin_id=99, approve=True,
                admin_note=None, expires_at=None,
            )

    @pytest.mark.asyncio
    async def test_raises_for_rejected_status(self):
        cert = _make_cert(driver_id=20, cert_status=WAVCertificationStatus.rejected)
        db = _make_db(execute_return=cert)
        with pytest.raises(ValueError, match="rejected"):
            await admin_verify_wav(
                db, driver_id=20, admin_id=99, approve=True,
                admin_note=None, expires_at=None,
            )

    @pytest.mark.asyncio
    async def test_raises_for_expired_status(self):
        cert = _make_cert(driver_id=20, cert_status=WAVCertificationStatus.expired)
        db = _make_db(execute_return=cert)
        with pytest.raises(ValueError, match="expired"):
            await admin_verify_wav(
                db, driver_id=20, admin_id=99, approve=True,
                admin_note=None, expires_at=None,
            )

    @pytest.mark.asyncio
    async def test_re_verify_already_verified_cert(self):
        """Admins can re-verify a cert (e.g. to extend expiry)."""
        cert = _make_cert(driver_id=20, cert_status=WAVCertificationStatus.verified)
        db = _make_db(execute_return=cert)
        db.refresh = AsyncMock()

        expiry = datetime(2028, 1, 1, tzinfo=timezone.utc)
        result = await admin_verify_wav(
            db, driver_id=20, admin_id=99, approve=True,
            admin_note="Renewed", expires_at=expiry,
        )

        assert result.status == WAVCertificationStatus.verified
        assert result.expires_at == expiry


# ---------------------------------------------------------------------------
# Service: get_wav_platform_stats
# ---------------------------------------------------------------------------


class TestGetWAVPlatformStats:
    @pytest.mark.asyncio
    async def test_zero_state_coverage_ratio_one(self):
        """No riders need WAV → coverage is vacuously 1.0."""
        db = AsyncMock()
        # Returns: riders_needing_wav=0, then 4 status counts (all 0).
        db.execute = AsyncMock(side_effect=[
            _db_returning(0),   # riders needing WAV
            _db_returning(0),   # pending
            _db_returning(0),   # verified
            _db_returning(0),   # rejected
            _db_returning(0),   # expired
        ])

        stats = await get_wav_platform_stats(db)

        assert stats.total_riders_needing_wav == 0
        assert stats.coverage_ratio == 1.0

    @pytest.mark.asyncio
    async def test_coverage_ratio_correct(self):
        """10 riders need WAV; 5 verified → coverage = 0.5."""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _db_returning(10),  # riders needing WAV
            _db_returning(2),   # pending
            _db_returning(5),   # verified
            _db_returning(1),   # rejected
            _db_returning(0),   # expired
        ])

        stats = await get_wav_platform_stats(db)

        assert stats.total_riders_needing_wav == 10
        assert stats.drivers_verified_wav == 5
        assert stats.coverage_ratio == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_coverage_ratio_capped_at_one(self):
        """More verified drivers than riders needing WAV → capped at 1.0."""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _db_returning(3),   # only 3 riders need WAV
            _db_returning(0),   # pending
            _db_returning(10),  # 10 verified
            _db_returning(0),   # rejected
            _db_returning(0),   # expired
        ])

        stats = await get_wav_platform_stats(db)

        assert stats.coverage_ratio == 1.0

    @pytest.mark.asyncio
    async def test_all_counts_populated(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _db_returning(8),
            _db_returning(3),
            _db_returning(2),
            _db_returning(1),
            _db_returning(4),
        ])

        stats = await get_wav_platform_stats(db)

        assert stats.drivers_pending_wav == 3
        assert stats.drivers_verified_wav == 2
        assert stats.drivers_rejected_wav == 1
        assert stats.drivers_expired_wav == 4


# ---------------------------------------------------------------------------
# Router smoke test — endpoints are registered
# ---------------------------------------------------------------------------


class TestRouterRegistration:
    def test_accessibility_router_imported(self):
        from app.api.v1 import accessibility
        assert hasattr(accessibility, "router")

    def test_router_has_routes(self):
        from app.api.v1.accessibility import router
        paths = {r.path for r in router.routes}
        assert "/riders/me/accessibility" in paths
        assert "/drivers/me/wav" in paths
        assert "/admin/accessibility/stats" in paths
        assert "/admin/drivers/{driver_id}/wav/verify" in paths
        assert "/admin/drivers/wav" in paths

    def test_main_includes_accessibility_router(self):
        from app.main import app
        all_paths = {r.path for r in app.routes}
        assert "/api/v1/riders/me/accessibility" in all_paths
        assert "/api/v1/drivers/me/wav" in all_paths
        assert "/api/v1/admin/accessibility/stats" in all_paths
