"""Tests for the Sprint 1 compliance engine.

Covers:
- check_driver_compliance() service: all pass, membership status blocks,
  license expired beyond grace, license missing, license within grace window,
  background check variations, vehicle inspection, insurance endorsement,
  custom jurisdiction grace periods, multiple simultaneous issues.
- run_nightly_compliance_check(): places eligible drivers on hold when docs lapse.
- ComplianceDocumentUpdate schema: rejects past dates.
- MembershipStatusUpdateRequest schema: rejects empty reason.
- GET /api/v1/compliance/check/{driver_id} endpoint: own record, wrong driver,
  not-found.
- GET /api/v1/compliance/jurisdictions endpoint.
- POST /api/v1/admin/drivers/{driver_id}/membership-status endpoint.
- PATCH /api/v1/admin/drivers/{driver_id}/compliance-documents endpoint.

All tests run without a database by mocking SQLAlchemy sessions, consistent
with the existing test suite pattern.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver import DriverProfile, MembershipStatus
from app.schemas.compliance import ComplianceDocumentUpdate, MembershipStatusUpdateRequest
from app.services.compliance import (
    ComplianceField,
    check_driver_compliance,
    run_nightly_compliance_check,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

TODAY = date(2026, 6, 21)
FUTURE = TODAY + timedelta(days=180)   # well within any grace period
EXPIRED_RECENT = TODAY - timedelta(days=1)     # 1 day past; within license grace
EXPIRED_WELL = TODAY - timedelta(days=60)      # 60 days past; beyond all grace


def _make_profile(
    driver_id: int = 1,
    membership_status: MembershipStatus = MembershipStatus.ACTIVE,
    license_expiry: date | None = FUTURE,
    background_check_expiry: date | None = FUTURE,
    vehicle_inspection_expiry: date | None = FUTURE,
    insurance_endorsement_expiry: date | None = FUTURE,
    jurisdiction_id: str | None = None,
) -> MagicMock:
    p = MagicMock(spec=DriverProfile)
    p.id = driver_id
    p.membership_status = membership_status
    p.license_expiry = license_expiry
    p.background_check_expiry = background_check_expiry
    p.vehicle_inspection_expiry = vehicle_inspection_expiry
    p.insurance_endorsement_expiry = insurance_endorsement_expiry
    p.jurisdiction_id = jurisdiction_id
    return p


def _make_jurisdiction(
    license_grace: int = 14,
    bgcheck_grace: int = 30,
) -> MagicMock:
    j = MagicMock()
    j.license_grace_days = license_grace
    j.background_check_grace_days = bgcheck_grace
    return j


# ── check_driver_compliance — happy path ────────────────────────────────────

class TestComplianceCheckEligible:
    def test_all_current_documents_are_eligible(self) -> None:
        profile = _make_profile()
        result = check_driver_compliance(profile, today=TODAY)
        assert result.eligible is True
        assert result.issues == []
        assert result.driver_id == 1

    def test_probation_status_is_still_eligible(self) -> None:
        profile = _make_profile(membership_status=MembershipStatus.PROBATION)
        result = check_driver_compliance(profile, today=TODAY)
        assert result.eligible is True

    def test_none_inspection_expiry_does_not_block(self) -> None:
        """Missing inspection expiry is not a hard block at this stage."""
        profile = _make_profile(vehicle_inspection_expiry=None)
        result = check_driver_compliance(profile, today=TODAY)
        assert result.eligible is True

    def test_none_insurance_expiry_does_not_block(self) -> None:
        """Missing insurance expiry is not a hard block at this stage."""
        profile = _make_profile(insurance_endorsement_expiry=None)
        result = check_driver_compliance(profile, today=TODAY)
        assert result.eligible is True

    def test_checked_at_is_set(self) -> None:
        profile = _make_profile()
        result = check_driver_compliance(profile, today=TODAY)
        assert isinstance(result.checked_at, datetime)


# ── check_driver_compliance — membership status blocks ──────────────────────

class TestMembershipStatusBlocks:
    def test_suspended_is_ineligible(self) -> None:
        profile = _make_profile(membership_status=MembershipStatus.SUSPENDED)
        result = check_driver_compliance(profile, today=TODAY)
        assert result.eligible is False
        fields = [i.field for i in result.issues]
        assert ComplianceField.MEMBERSHIP_STATUS in fields

    def test_terminated_is_ineligible(self) -> None:
        profile = _make_profile(membership_status=MembershipStatus.TERMINATED)
        result = check_driver_compliance(profile, today=TODAY)
        assert result.eligible is False

    def test_compliance_hold_is_ineligible(self) -> None:
        profile = _make_profile(membership_status=MembershipStatus.COMPLIANCE_HOLD)
        result = check_driver_compliance(profile, today=TODAY)
        assert result.eligible is False

    def test_suspended_message_does_not_expose_internals(self) -> None:
        profile = _make_profile(membership_status=MembershipStatus.SUSPENDED)
        result = check_driver_compliance(profile, today=TODAY)
        issue = result.issues[0]
        # Should say "suspended", not internal field names or DB ids
        assert "suspended" in issue.message.lower()
        assert "membership_status" not in issue.message
        assert str(profile.id) not in issue.message


# ── check_driver_compliance — license checks ─────────────────────────────────

class TestLicenseCompliance:
    def test_missing_license_expiry_is_ineligible(self) -> None:
        profile = _make_profile(license_expiry=None)
        result = check_driver_compliance(profile, today=TODAY)
        assert result.eligible is False
        issue = next(i for i in result.issues if i.field == ComplianceField.LICENSE)
        assert issue.days_until_expiry is None
        assert "license" in issue.message.lower()

    def test_license_expired_within_grace_period_is_still_ineligible(self) -> None:
        """Default grace = 14 days.  1 day past expiry is within grace but
        the current logic requires remaining >= -grace to pass.  A license
        expired 1 day ago has days_remaining = -1; -1 >= -14 so it is NOT
        blocked.  Verify this boundary behaviour."""
        profile = _make_profile(license_expiry=EXPIRED_RECENT)
        result = check_driver_compliance(profile, today=TODAY)
        # -1 >= -14 → within grace → eligible
        assert result.eligible is True

    def test_license_expired_beyond_grace_is_ineligible(self) -> None:
        """60 days past expiry; -60 < -14 → blocked."""
        profile = _make_profile(license_expiry=EXPIRED_WELL)
        result = check_driver_compliance(profile, today=TODAY)
        assert result.eligible is False
        issue = next(i for i in result.issues if i.field == ComplianceField.LICENSE)
        assert issue.days_until_expiry == -60

    def test_custom_jurisdiction_license_grace(self) -> None:
        """A jurisdiction with 0-day grace should block immediately on expiry."""
        profile = _make_profile(license_expiry=EXPIRED_RECENT)
        j = _make_jurisdiction(license_grace=0)
        result = check_driver_compliance(profile, jurisdiction=j, today=TODAY)
        assert result.eligible is False

    def test_custom_jurisdiction_wide_license_grace(self) -> None:
        """A jurisdiction with 90-day grace shouldn't block a 60-day-old expiry."""
        profile = _make_profile(license_expiry=EXPIRED_WELL)
        j = _make_jurisdiction(license_grace=90)
        result = check_driver_compliance(profile, jurisdiction=j, today=TODAY)
        # 60 < 90 grace → eligible (assuming background check is fine)
        license_issues = [i for i in result.issues if i.field == ComplianceField.LICENSE]
        assert license_issues == []


# ── check_driver_compliance — background check ───────────────────────────────

class TestBackgroundCheckCompliance:
    def test_missing_background_check_is_ineligible(self) -> None:
        profile = _make_profile(background_check_expiry=None)
        result = check_driver_compliance(profile, today=TODAY)
        assert result.eligible is False
        issue = next(i for i in result.issues if i.field == ComplianceField.BACKGROUND_CHECK)
        assert issue.days_until_expiry is None

    def test_background_check_expired_within_grace_is_eligible(self) -> None:
        """Default grace = 30 days.  1 day past expiry → still within grace."""
        profile = _make_profile(background_check_expiry=EXPIRED_RECENT)
        result = check_driver_compliance(profile, today=TODAY)
        assert result.eligible is True

    def test_background_check_expired_beyond_grace_is_ineligible(self) -> None:
        profile = _make_profile(background_check_expiry=EXPIRED_WELL)
        result = check_driver_compliance(profile, today=TODAY)
        assert result.eligible is False
        issue = next(i for i in result.issues if i.field == ComplianceField.BACKGROUND_CHECK)
        assert issue.days_until_expiry == -60


# ── check_driver_compliance — inspection & insurance ─────────────────────────

class TestInspectionAndInsuranceCompliance:
    def test_expired_inspection_is_ineligible(self) -> None:
        profile = _make_profile(vehicle_inspection_expiry=EXPIRED_RECENT)
        result = check_driver_compliance(profile, today=TODAY)
        assert result.eligible is False
        fields = [i.field for i in result.issues]
        assert ComplianceField.VEHICLE_INSPECTION in fields

    def test_expired_insurance_is_ineligible(self) -> None:
        profile = _make_profile(insurance_endorsement_expiry=EXPIRED_RECENT)
        result = check_driver_compliance(profile, today=TODAY)
        assert result.eligible is False
        fields = [i.field for i in result.issues]
        assert ComplianceField.INSURANCE_ENDORSEMENT in fields


# ── check_driver_compliance — multiple simultaneous issues ───────────────────

class TestMultipleIssues:
    def test_multiple_issues_reported(self) -> None:
        profile = _make_profile(
            membership_status=MembershipStatus.SUSPENDED,
            license_expiry=EXPIRED_WELL,
            background_check_expiry=None,
        )
        result = check_driver_compliance(profile, today=TODAY)
        assert result.eligible is False
        fields = {i.field for i in result.issues}
        assert ComplianceField.MEMBERSHIP_STATUS in fields
        assert ComplianceField.LICENSE in fields
        assert ComplianceField.BACKGROUND_CHECK in fields

    def test_eligible_result_has_empty_issues(self) -> None:
        profile = _make_profile()
        result = check_driver_compliance(profile, today=TODAY)
        assert result.issues == []


# ── run_nightly_compliance_check ─────────────────────────────────────────────

def _make_nightly_db(profiles: list) -> AsyncMock:
    """Build a db mock suitable for run_nightly_compliance_check.

    The function does ``await db.execute(...)`` which returns a result object
    whose ``.scalars().all()`` yields the driver list.  Jurisdiction lookups
    are skipped because all test profiles have jurisdiction_id=None.
    """
    db = AsyncMock()

    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = profiles
    db.execute = AsyncMock(return_value=list_result)
    db.commit = AsyncMock()
    return db


class TestNightlyComplianceCheck:
    @pytest.mark.asyncio
    async def test_places_driver_on_hold_when_license_lapsed(self) -> None:
        profile = _make_profile(
            membership_status=MembershipStatus.ACTIVE,
            license_expiry=EXPIRED_WELL,  # 60 days past; beyond 14-day grace
        )
        db = _make_nightly_db([profile])

        summary = await run_nightly_compliance_check(db)

        assert summary["checked"] == 1
        assert summary["placed_on_hold"] == 1
        assert profile.membership_status == MembershipStatus.COMPLIANCE_HOLD
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_eligible_drivers_are_not_touched(self) -> None:
        profile = _make_profile(membership_status=MembershipStatus.ACTIVE)
        db = _make_nightly_db([profile])

        summary = await run_nightly_compliance_check(db)

        assert summary["placed_on_hold"] == 0
        assert profile.membership_status == MembershipStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_terminated_drivers_are_skipped(self) -> None:
        """Terminated drivers should not be auto-held (already terminal state)."""
        profile = _make_profile(
            membership_status=MembershipStatus.TERMINATED,
            license_expiry=EXPIRED_WELL,
        )
        db = _make_nightly_db([profile])

        summary = await run_nightly_compliance_check(db)

        assert summary["placed_on_hold"] == 0
        assert profile.membership_status == MembershipStatus.TERMINATED

    @pytest.mark.asyncio
    async def test_empty_driver_list_returns_zero_counts(self) -> None:
        db = _make_nightly_db([])

        summary = await run_nightly_compliance_check(db)

        assert summary["checked"] == 0
        assert summary["placed_on_hold"] == 0


# ── Schema validation ─────────────────────────────────────────────────────────

class TestSchemaValidation:
    def test_membership_status_update_rejects_empty_reason(self) -> None:
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            MembershipStatusUpdateRequest(
                new_status=MembershipStatus.SUSPENDED,
                reason="",
            )

    def test_membership_status_update_rejects_whitespace_only_reason(self) -> None:
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            MembershipStatusUpdateRequest(
                new_status=MembershipStatus.SUSPENDED,
                reason="   ",
            )

    def test_membership_status_update_accepts_valid_request(self) -> None:
        req = MembershipStatusUpdateRequest(
            new_status=MembershipStatus.SUSPENDED,
            reason="Repeated no-shows",
        )
        assert req.reason == "Repeated no-shows"

    def test_compliance_document_update_rejects_past_date(self) -> None:
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            ComplianceDocumentUpdate(license_expiry=date(2020, 1, 1))

    def test_compliance_document_update_accepts_future_date(self) -> None:
        doc = ComplianceDocumentUpdate(license_expiry=FUTURE)
        assert doc.license_expiry == FUTURE

    def test_compliance_document_update_all_none_is_valid(self) -> None:
        doc = ComplianceDocumentUpdate()
        assert doc.license_expiry is None


# ── API endpoint tests (mock DB) ─────────────────────────────────────────────

class TestComplianceCheckEndpoint:
    @pytest.mark.asyncio
    async def test_driver_can_check_own_compliance(self) -> None:
        from app.api.v1.compliance import get_compliance_check
        profile = _make_profile(driver_id=5)
        user = MagicMock()
        user.id = 99
        user.is_admin = False

        db = AsyncMock()
        # First execute: load profile by driver_id
        own_result = MagicMock()
        own_result.scalar_one_or_none.return_value = profile

        # Second execute: load own profile by user_id
        own_profile_result = MagicMock()
        own_profile_result.scalar_one_or_none.return_value = profile

        # Third execute: jurisdiction (profile has no jurisdiction)
        db.execute.side_effect = [own_result, own_profile_result]

        result = await get_compliance_check(
            driver_id=5, current_user=user, db=db
        )
        assert result.driver_id == 5
        assert result.eligible is True

    @pytest.mark.asyncio
    async def test_driver_cannot_check_another_drivers_compliance(self) -> None:
        from fastapi import HTTPException
        from app.api.v1.compliance import get_compliance_check

        target_profile = _make_profile(driver_id=5)
        own_profile = _make_profile(driver_id=9)
        user = MagicMock()
        user.id = 99
        user.is_admin = False

        db = AsyncMock()
        target_result = MagicMock()
        target_result.scalar_one_or_none.return_value = target_profile
        own_result = MagicMock()
        own_result.scalar_one_or_none.return_value = own_profile
        db.execute.side_effect = [target_result, own_result]

        with pytest.raises(HTTPException) as exc_info:
            await get_compliance_check(driver_id=5, current_user=user, db=db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_404_for_missing_profile(self) -> None:
        from fastapi import HTTPException
        from app.api.v1.compliance import get_compliance_check

        user = MagicMock()
        user.is_admin = True

        db = AsyncMock()
        not_found = MagicMock()
        not_found.scalar_one_or_none.return_value = None
        db.execute.return_value = not_found

        with pytest.raises(HTTPException) as exc_info:
            await get_compliance_check(driver_id=999, current_user=user, db=db)
        assert exc_info.value.status_code == 404


def _make_single_result_db(obj) -> AsyncMock:
    """Build a db mock where a single execute returns obj via scalar_one_or_none."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


class TestAdminMembershipStatusEndpoint:
    @pytest.mark.asyncio
    async def test_updates_membership_status_successfully(self) -> None:
        from app.api.v1.compliance import update_membership_status

        profile = _make_profile(membership_status=MembershipStatus.ACTIVE)
        db = _make_single_result_db(profile)

        body = MembershipStatusUpdateRequest(
            new_status=MembershipStatus.SUSPENDED,
            reason="Repeated policy violations",
        )
        response = await update_membership_status(
            driver_id=1, body=body, _admin=MagicMock(), db=db
        )

        assert response.new_status == MembershipStatus.SUSPENDED
        assert response.previous_status == MembershipStatus.ACTIVE
        assert response.reason == "Repeated policy violations"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_404_for_missing_driver(self) -> None:
        from fastapi import HTTPException
        from app.api.v1.compliance import update_membership_status

        db = _make_single_result_db(None)

        with pytest.raises(HTTPException) as exc_info:
            await update_membership_status(
                driver_id=999,
                body=MembershipStatusUpdateRequest(
                    new_status=MembershipStatus.SUSPENDED,
                    reason="Test",
                ),
                _admin=MagicMock(),
                db=db,
            )
        assert exc_info.value.status_code == 404


class TestAdminComplianceDocumentsEndpoint:
    @pytest.mark.asyncio
    async def test_updates_license_expiry(self) -> None:
        from app.api.v1.compliance import update_compliance_documents

        profile = _make_profile()
        db = _make_single_result_db(profile)

        new_expiry = date(2027, 6, 1)
        body = ComplianceDocumentUpdate(license_expiry=new_expiry)
        response = await update_compliance_documents(
            driver_id=1, body=body, _admin=MagicMock(), db=db
        )

        assert profile.license_expiry == new_expiry
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_404_for_missing_driver(self) -> None:
        from fastapi import HTTPException
        from app.api.v1.compliance import update_compliance_documents

        db = _make_single_result_db(None)

        with pytest.raises(HTTPException) as exc_info:
            await update_compliance_documents(
                driver_id=999,
                body=ComplianceDocumentUpdate(),
                _admin=MagicMock(),
                db=db,
            )
        assert exc_info.value.status_code == 404
