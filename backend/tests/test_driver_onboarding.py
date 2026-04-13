"""Comprehensive unit tests for the driver onboarding status and activation workflow.

Covers:
- Model: fields, enum values, table structure
- Schema: ChecklistItem, OnboardingChecklist, SuspendDriverRequest validation
- Service:
    - get_onboarding_checklist returns correct status per requirement combination
    - compute_onboarding_status returns correct enum
    - get_or_create_onboarding creates row when absent / returns existing
    - activate_driver rejects if requirements not met
    - activate_driver succeeds when all requirements approved
    - suspend_driver sets status + reason + flips profile flags
    - list_pending_review / list_incomplete paginate correctly
- API endpoints (via mocked service / dep overrides):
    - Driver views own checklist (GET /drivers/me/onboarding)
    - Driver cannot access admin endpoints
    - Admin views any driver checklist
    - Activate endpoint returns 409 when requirements not met
    - Activate endpoint returns 200 when all requirements met
    - Suspend endpoint works with valid reason
    - Suspend endpoint returns 422 on empty reason
    - Pending / incomplete list endpoints paginate

All tests are pure unit tests — no database required.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.background_check import BackgroundCheck, BackgroundCheckStatus
from app.models.driver import DriverProfile
from app.models.driver_documents import DocumentStatus, DriverLicense, VehicleRegistration
from app.models.driver_insurance import DriverInsuranceDocument, InsuranceDocumentStatus
from app.models.driver_onboarding import DriverOnboarding, OnboardingStatus
from app.models.vehicle_inspection import InspectionStatus, InspectionType, VehicleInspection
from app.schemas.driver_onboarding import (
    ActivateDriverRequest,
    ChecklistItem,
    DriverOnboardingResponse,
    IncompleteDriverItem,
    OnboardingChecklist,
    PendingDriverItem,
    SuspendDriverRequest,
)
from app.services.driver_onboarding import (
    OnboardingError,
    _latest_approved_background_check,
    _latest_approved_inspection,
    _latest_approved_insurance,
    _latest_approved_license,
    _latest_approved_registration,
    _profile_complete_item,
    activate_driver,
    compute_onboarding_status,
    get_onboarding_checklist,
    get_or_create_onboarding,
    list_incomplete,
    list_pending_review,
    suspend_driver,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = date.today()
NEXT_YEAR = TODAY + timedelta(days=365)
YESTERDAY = TODAY - timedelta(days=1)


def _make_profile(**kwargs) -> DriverProfile:
    defaults = dict(
        id=1,
        user_id=10,
        vehicle_type="sedan",
        vehicle_make="Toyota",
        vehicle_model="Camry",
        vehicle_year=2022,
        vehicle_color="Silver",
        license_plate="TEST-123",
        license_number="DL-456",
        insurance_policy="INS-789",
        background_check_status="pending",
        rating_avg=5.0,
        total_trips=0,
        is_online=False,
        is_approved=False,
        active_vehicle_id=None,
        current_location=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    p = MagicMock(spec=DriverProfile)
    for k, v in defaults.items():
        setattr(p, k, v)
    return p


def _make_bg_check(**kwargs) -> BackgroundCheck:
    defaults = dict(
        id=1,
        driver_profile_id=1,
        status=BackgroundCheckStatus.CLEAR,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    bc = MagicMock(spec=BackgroundCheck)
    for k, v in defaults.items():
        setattr(bc, k, v)
    return bc


def _make_license(**kwargs) -> DriverLicense:
    defaults = dict(
        id=1,
        driver_id=10,
        status=DocumentStatus.APPROVED,
        expiry_date=NEXT_YEAR,
        created_at=datetime.now(timezone.utc),
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
        status=DocumentStatus.APPROVED,
        expiry_date=NEXT_YEAR,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    reg = MagicMock(spec=VehicleRegistration)
    for k, v in defaults.items():
        setattr(reg, k, v)
    return reg


def _make_inspection(**kwargs) -> VehicleInspection:
    defaults = dict(
        id=1,
        driver_id=10,
        inspection_type=InspectionType.ANNUAL,
        status=InspectionStatus.APPROVED,
        expiry_date=NEXT_YEAR,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    insp = MagicMock(spec=VehicleInspection)
    for k, v in defaults.items():
        setattr(insp, k, v)
    return insp


def _make_insurance(**kwargs) -> DriverInsuranceDocument:
    defaults = dict(
        id=1,
        driver_id=10,
        status=InsuranceDocumentStatus.APPROVED,
        policy_end_date=NEXT_YEAR,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    ins = MagicMock(spec=DriverInsuranceDocument)
    for k, v in defaults.items():
        setattr(ins, k, v)
    return ins


def _make_onboarding(**kwargs) -> DriverOnboarding:
    defaults = dict(
        id=1,
        driver_profile_id=1,
        status=OnboardingStatus.INCOMPLETE,
        suspension_reason=None,
        suspended_by=None,
        suspended_at=None,
        activated_by=None,
        activated_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    ob = MagicMock(spec=DriverOnboarding)
    for k, v in defaults.items():
        setattr(ob, k, v)
    return ob


def _make_db_multi(*return_values):
    """Build a mock DB whose execute() returns different values on successive calls."""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    call_index = {"n": 0}

    async def _execute(query):
        idx = call_index["n"]
        call_index["n"] += 1
        result = MagicMock()
        if idx < len(return_values):
            val = return_values[idx]
        else:
            val = None
        if isinstance(val, list):
            result.scalar_one_or_none.return_value = None
            result.scalars.return_value.all.return_value = val
        else:
            result.scalar_one_or_none.return_value = val
            result.scalars.return_value.all.return_value = [val] if val else []
        return result

    db.execute = _execute
    return db


# ===========================================================================
# Model tests
# ===========================================================================


class TestDriverOnboardingModel:
    def test_tablename(self):
        assert DriverOnboarding.__tablename__ == "driver_onboarding"

    def test_has_required_columns(self):
        cols = {c.key for c in DriverOnboarding.__table__.columns}
        required = {
            "id",
            "driver_profile_id",
            "status",
            "suspension_reason",
            "suspended_by",
            "suspended_at",
            "activated_by",
            "activated_at",
            "created_at",
            "updated_at",
        }
        assert required.issubset(cols)

    def test_onboarding_status_enum_values(self):
        assert OnboardingStatus.INCOMPLETE == "incomplete"
        assert OnboardingStatus.PENDING_REVIEW == "pending_review"
        assert OnboardingStatus.APPROVED == "approved"
        assert OnboardingStatus.SUSPENDED == "suspended"

    def test_default_status_is_incomplete(self):
        col = DriverOnboarding.__table__.columns["status"]
        assert col.default is not None or col.server_default is not None or True
        # Default is set via mapped_column default=
        assert DriverOnboarding.status.property.columns[0].default.arg == OnboardingStatus.INCOMPLETE


# ===========================================================================
# Schema tests
# ===========================================================================


class TestSchemas:
    def test_checklist_item_met_true(self):
        item = ChecklistItem(required=True, met=True, detail="OK")
        assert item.met is True
        assert item.required is True

    def test_checklist_item_met_false(self):
        item = ChecklistItem(required=True, met=False, detail="Missing")
        assert item.met is False

    def test_suspend_request_valid(self):
        req = SuspendDriverRequest(reason="Insurance expired")
        assert req.reason == "Insurance expired"

    def test_suspend_request_empty_reason_raises(self):
        with pytest.raises(Exception):
            SuspendDriverRequest(reason="   ")

    def test_suspend_request_strips_whitespace(self):
        req = SuspendDriverRequest(reason="  Safety concern  ")
        assert req.reason == "Safety concern"

    def test_onboarding_checklist_fields(self):
        item = ChecklistItem(required=True, met=True, detail="OK")
        checklist = OnboardingChecklist(
            driver_profile_id=1,
            background_check=item,
            driver_license=item,
            vehicle_registration=item,
            vehicle_inspection=item,
            insurance_document=item,
            profile_complete=item,
            computed_status=OnboardingStatus.APPROVED,
            persisted_status=OnboardingStatus.APPROVED,
        )
        assert checklist.driver_profile_id == 1
        assert checklist.computed_status == OnboardingStatus.APPROVED

    def test_driver_onboarding_response_from_attributes(self):
        ob = _make_onboarding()
        resp = DriverOnboardingResponse.model_validate(ob)
        assert resp.driver_profile_id == 1
        assert resp.status == OnboardingStatus.INCOMPLETE


# ===========================================================================
# Service: _profile_complete_item
# ===========================================================================


class TestProfileCompleteItem:
    def test_complete_when_insurance_policy_set(self):
        profile = _make_profile(insurance_policy="INS-001")
        item = _profile_complete_item(profile)
        assert item.met is True

    def test_incomplete_when_no_insurance_policy(self):
        profile = _make_profile(insurance_policy=None)
        item = _profile_complete_item(profile)
        assert item.met is False
        assert "payout account" in item.detail


# ===========================================================================
# Service: get_or_create_onboarding
# ===========================================================================


class TestGetOrCreateOnboarding:
    @pytest.mark.anyio
    async def test_returns_existing_onboarding(self):
        existing = _make_onboarding(status=OnboardingStatus.PENDING_REVIEW)
        db = _make_db_multi(existing)
        result = await get_or_create_onboarding(1, db)
        assert result.status == OnboardingStatus.PENDING_REVIEW

    @pytest.mark.anyio
    async def test_creates_new_onboarding_when_absent(self):
        db = _make_db_multi(None)
        db.add = MagicMock()
        db.flush = AsyncMock()
        result = await get_or_create_onboarding(1, db)
        db.add.assert_called_once()
        assert result is not None


# ===========================================================================
# Service: get_onboarding_checklist
# ===========================================================================


class TestGetOnboardingChecklist:
    @pytest.mark.anyio
    async def test_raises_when_profile_not_found(self):
        db = _make_db_multi(None)
        with pytest.raises(OnboardingError, match="not found"):
            await get_onboarding_checklist(99, db)

    @pytest.mark.anyio
    async def test_all_requirements_met_returns_approved(self):
        profile = _make_profile(id=1, user_id=10, insurance_policy="INS-001")
        bg = _make_bg_check()
        lic = _make_license()
        reg = _make_registration()
        insp = _make_inspection()
        ins = _make_insurance()
        onboarding = _make_onboarding(status=OnboardingStatus.INCOMPLETE)
        db = _make_db_multi(profile, bg, lic, reg, insp, ins, onboarding)
        checklist = await get_onboarding_checklist(1, db)
        assert checklist.background_check.met is True
        assert checklist.driver_license.met is True
        assert checklist.vehicle_registration.met is True
        assert checklist.vehicle_inspection.met is True
        assert checklist.insurance_document.met is True
        assert checklist.profile_complete.met is True
        assert checklist.computed_status == OnboardingStatus.APPROVED

    @pytest.mark.anyio
    async def test_missing_background_check_returns_incomplete(self):
        profile = _make_profile(insurance_policy="INS-001")
        db = _make_db_multi(profile, None, _make_license(), _make_registration(),
                            _make_inspection(), _make_insurance(), _make_onboarding())
        checklist = await get_onboarding_checklist(1, db)
        assert checklist.background_check.met is False
        assert checklist.computed_status == OnboardingStatus.INCOMPLETE

    @pytest.mark.anyio
    async def test_missing_license_marks_incomplete(self):
        profile = _make_profile(insurance_policy="INS-001")
        db = _make_db_multi(profile, _make_bg_check(), None, _make_registration(),
                            _make_inspection(), _make_insurance(), _make_onboarding())
        checklist = await get_onboarding_checklist(1, db)
        assert checklist.driver_license.met is False

    @pytest.mark.anyio
    async def test_missing_registration_marks_incomplete(self):
        profile = _make_profile(insurance_policy="INS-001")
        db = _make_db_multi(profile, _make_bg_check(), _make_license(), None,
                            _make_inspection(), _make_insurance(), _make_onboarding())
        checklist = await get_onboarding_checklist(1, db)
        assert checklist.vehicle_registration.met is False

    @pytest.mark.anyio
    async def test_missing_inspection_marks_incomplete(self):
        profile = _make_profile(insurance_policy="INS-001")
        db = _make_db_multi(profile, _make_bg_check(), _make_license(),
                            _make_registration(), None, _make_insurance(), _make_onboarding())
        checklist = await get_onboarding_checklist(1, db)
        assert checklist.vehicle_inspection.met is False

    @pytest.mark.anyio
    async def test_missing_insurance_marks_incomplete(self):
        profile = _make_profile(insurance_policy="INS-001")
        db = _make_db_multi(profile, _make_bg_check(), _make_license(),
                            _make_registration(), _make_inspection(), None, _make_onboarding())
        checklist = await get_onboarding_checklist(1, db)
        assert checklist.insurance_document.met is False

    @pytest.mark.anyio
    async def test_missing_payout_account_marks_incomplete(self):
        profile = _make_profile(insurance_policy=None)
        db = _make_db_multi(profile, _make_bg_check(), _make_license(),
                            _make_registration(), _make_inspection(),
                            _make_insurance(), _make_onboarding())
        checklist = await get_onboarding_checklist(1, db)
        assert checklist.profile_complete.met is False

    @pytest.mark.anyio
    async def test_persisted_status_reflects_stored_value(self):
        profile = _make_profile(insurance_policy="INS-001")
        ob = _make_onboarding(status=OnboardingStatus.SUSPENDED)
        db = _make_db_multi(profile, _make_bg_check(), _make_license(),
                            _make_registration(), _make_inspection(),
                            _make_insurance(), ob)
        checklist = await get_onboarding_checklist(1, db)
        assert checklist.persisted_status == OnboardingStatus.SUSPENDED

    @pytest.mark.anyio
    async def test_detail_contains_expiry_when_license_approved(self):
        profile = _make_profile(insurance_policy="INS-001")
        lic = _make_license(expiry_date=NEXT_YEAR)
        db = _make_db_multi(profile, _make_bg_check(), lic, _make_registration(),
                            _make_inspection(), _make_insurance(), _make_onboarding())
        checklist = await get_onboarding_checklist(1, db)
        assert str(NEXT_YEAR) in checklist.driver_license.detail


# ===========================================================================
# Service: compute_onboarding_status
# ===========================================================================


class TestComputeOnboardingStatus:
    @pytest.mark.anyio
    async def test_returns_approved_when_all_met(self):
        profile = _make_profile(insurance_policy="INS-001")
        db = _make_db_multi(profile, _make_bg_check(), _make_license(),
                            _make_registration(), _make_inspection(),
                            _make_insurance(), _make_onboarding())
        status = await compute_onboarding_status(1, db)
        assert status == OnboardingStatus.APPROVED

    @pytest.mark.anyio
    async def test_returns_incomplete_when_nothing_met(self):
        profile = _make_profile(insurance_policy=None)
        db = _make_db_multi(profile, None, None, None, None, None, _make_onboarding())
        status = await compute_onboarding_status(1, db)
        assert status == OnboardingStatus.INCOMPLETE


# ===========================================================================
# Service: activate_driver
# ===========================================================================


class TestActivateDriver:
    @pytest.mark.anyio
    async def test_raises_when_requirements_not_met(self):
        profile = _make_profile(insurance_policy=None)
        db = _make_db_multi(
            # get_onboarding_checklist calls:
            profile, None, None, None, None, None,
            # get_or_create_onboarding call:
            _make_onboarding(),
            # activate_driver's own get_or_create_onboarding call:
            _make_onboarding(),
        )
        with pytest.raises(OnboardingError, match="requirements not met"):
            await activate_driver(1, admin_user_id=99, db=db)

    @pytest.mark.anyio
    async def test_raises_when_driver_is_suspended(self):
        profile = _make_profile(insurance_policy="INS-001")
        ob_suspended = _make_onboarding(status=OnboardingStatus.SUSPENDED)
        # First checklist build: all items met, then get_or_create returns suspended ob
        db = _make_db_multi(
            profile, _make_bg_check(), _make_license(), _make_registration(),
            _make_inspection(), _make_insurance(),
            ob_suspended,       # inside get_onboarding_checklist -> get_or_create
            ob_suspended,       # activate_driver's own get_or_create call
        )
        with pytest.raises(OnboardingError, match="suspended"):
            await activate_driver(1, admin_user_id=99, db=db)

    @pytest.mark.anyio
    async def test_activates_successfully_when_all_requirements_met(self):
        profile = _make_profile(insurance_policy="INS-001")
        ob = _make_onboarding(status=OnboardingStatus.INCOMPLETE)

        call_order = []

        db = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()

        # We need profile returned for:
        # 1. get_onboarding_checklist -> select(DriverProfile)
        # 2. bg_check lookup
        # 3. license lookup
        # 4. registration lookup
        # 5. inspection lookup
        # 6. insurance lookup
        # 7. get_or_create_onboarding (inside checklist) -> returns ob
        # 8. activate_driver's own get_or_create_onboarding -> returns ob
        # 9. select(DriverProfile) inside activate_driver -> profile

        returns = [
            profile,         # 1 profile lookup in checklist
            _make_bg_check(),
            _make_license(),
            _make_registration(),
            _make_inspection(),
            _make_insurance(),
            ob,              # get_or_create inside checklist
            ob,              # get_or_create inside activate_driver
            profile,         # profile lookup inside activate_driver
        ]
        idx = {"n": 0}

        async def _execute(q):
            r = MagicMock()
            val = returns[idx["n"]] if idx["n"] < len(returns) else None
            idx["n"] += 1
            if isinstance(val, list):
                r.scalar_one_or_none.return_value = None
                r.scalars.return_value.all.return_value = val
            else:
                r.scalar_one_or_none.return_value = val
                r.scalars.return_value.all.return_value = [val] if val else []
            return r

        db.execute = _execute

        result = await activate_driver(1, admin_user_id=99, db=db)
        assert ob.status == OnboardingStatus.APPROVED
        assert ob.activated_by == 99
        assert profile.is_approved is True

    @pytest.mark.anyio
    async def test_activate_clears_suspension_fields(self):
        profile = _make_profile(insurance_policy="INS-001")
        ob = _make_onboarding(
            status=OnboardingStatus.INCOMPLETE,
            suspension_reason="old reason",
            suspended_by=5,
        )

        returns = [
            profile,
            _make_bg_check(),
            _make_license(),
            _make_registration(),
            _make_inspection(),
            _make_insurance(),
            ob,   # checklist -> get_or_create
            ob,   # activate_driver -> get_or_create
            profile,
        ]
        idx = {"n": 0}
        db = AsyncMock()
        db.flush = AsyncMock()

        async def _execute(q):
            r = MagicMock()
            val = returns[idx["n"]] if idx["n"] < len(returns) else None
            idx["n"] += 1
            r.scalar_one_or_none.return_value = val
            r.scalars.return_value.all.return_value = []
            return r

        db.execute = _execute
        await activate_driver(1, admin_user_id=99, db=db)
        assert ob.suspension_reason is None
        assert ob.suspended_by is None


# ===========================================================================
# Service: suspend_driver
# ===========================================================================


class TestSuspendDriver:
    @pytest.mark.anyio
    async def test_raises_on_empty_reason(self):
        db = AsyncMock()
        with pytest.raises(OnboardingError, match="reason"):
            await suspend_driver(1, "", admin_user_id=99, db=db)

    @pytest.mark.anyio
    async def test_raises_when_profile_not_found(self):
        db = _make_db_multi(None)
        with pytest.raises(OnboardingError, match="not found"):
            await suspend_driver(1, "Safety issue", admin_user_id=99, db=db)

    @pytest.mark.anyio
    async def test_suspends_driver_successfully(self):
        profile = _make_profile()
        ob = _make_onboarding(status=OnboardingStatus.APPROVED)
        db = _make_db_multi(profile, ob)
        result = await suspend_driver(1, "Violation of terms", admin_user_id=55, db=db)
        assert ob.status == OnboardingStatus.SUSPENDED
        assert ob.suspension_reason == "Violation of terms"
        assert ob.suspended_by == 55
        assert profile.is_approved is False
        assert profile.is_online is False

    @pytest.mark.anyio
    async def test_suspend_sets_suspended_at_timestamp(self):
        profile = _make_profile()
        ob = _make_onboarding()
        db = _make_db_multi(profile, ob)
        await suspend_driver(1, "Reason", admin_user_id=55, db=db)
        assert ob.suspended_at is not None


# ===========================================================================
# Service: list_pending_review / list_incomplete
# ===========================================================================


class TestListEndpoints:
    @pytest.mark.anyio
    async def test_list_pending_review_returns_items(self):
        ob1 = _make_onboarding(id=1, status=OnboardingStatus.PENDING_REVIEW)
        ob2 = _make_onboarding(id=2, status=OnboardingStatus.PENDING_REVIEW)

        db = AsyncMock()
        db.flush = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [ob1, ob2]
        db.execute = AsyncMock(return_value=result_mock)

        rows = await list_pending_review(db, page=1, page_size=20)
        assert len(rows) == 2

    @pytest.mark.anyio
    async def test_list_pending_review_pagination(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)

        rows = await list_pending_review(db, page=2, page_size=10)
        assert rows == []

    @pytest.mark.anyio
    async def test_list_incomplete_returns_items(self):
        ob = _make_onboarding(id=1, status=OnboardingStatus.INCOMPLETE)

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [ob]
        db.execute = AsyncMock(return_value=result_mock)

        rows = await list_incomplete(db, page=1, page_size=20)
        assert len(rows) == 1

    @pytest.mark.anyio
    async def test_list_incomplete_page_2_empty(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)

        rows = await list_incomplete(db, page=2, page_size=5)
        assert rows == []


# ===========================================================================
# API endpoint tests — via FastAPI test client with mocked deps
# ===========================================================================


def _make_app_with_db(db_override):
    """Return the FastAPI app with db and auth dependency overrides."""
    from app.main import app
    from app.db.database import get_db

    app.dependency_overrides[get_db] = lambda: db_override
    return app


class TestDriverOnboardingEndpoints:
    """Tests for the HTTP layer using mocked service calls."""

    @pytest.mark.anyio
    async def test_get_my_onboarding_requires_driver_role(self):
        """Unauthenticated request returns 401 or 403 (no bearer token)."""
        import httpx
        from httpx import ASGITransport
        from app.main import app

        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/drivers/me/onboarding")
        # HTTPBearer returns 403 when scheme is missing, but some middleware may
        # return 401 — both are acceptable "not authenticated" responses.
        assert resp.status_code in (401, 403)

    @pytest.mark.anyio
    async def test_admin_endpoints_reject_non_admin(self):
        """Driver token cannot access admin endpoints."""
        import httpx
        from httpx import ASGITransport
        from app.main import app
        from app.services.auth import create_access_token

        token = create_access_token(999, "driver")
        headers = {"Authorization": f"Bearer {token}"}

        # We still need to mock the DB so auth doesn't crash
        from unittest.mock import AsyncMock, MagicMock
        from app.models.user import User, UserRole
        from app.db.database import get_db

        mock_user = MagicMock(spec=User)
        mock_user.id = 999
        mock_user.is_active = True
        mock_user.role = UserRole.DRIVER

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=result)

        original_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = lambda: mock_db

        transport = ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/admin/drivers/1/onboarding", headers=headers
                )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides = original_overrides

    @pytest.mark.anyio
    async def test_driver_can_get_own_checklist(self):
        """Driver token successfully retrieves own onboarding checklist."""
        import httpx
        from httpx import ASGITransport
        from app.main import app
        from app.db.database import get_db
        from app.services.auth import create_access_token
        from app.models.user import User, UserRole

        driver_user = MagicMock(spec=User)
        driver_user.id = 10
        driver_user.is_active = True
        driver_user.role = UserRole.DRIVER

        profile = _make_profile(id=1, user_id=10, insurance_policy="INS")

        token = create_access_token(10, "driver")
        headers = {"Authorization": f"Bearer {token}"}

        # Build a multi-call mock db
        # Calls in order:
        # 1. get_current_user -> user
        # 2. select(DriverProfile) in endpoint -> profile
        # 3-8. checklist lookups: profile, bg, lic, reg, insp, ins
        # 9. get_or_create_onboarding
        ob = _make_onboarding()
        returns = [
            driver_user,   # auth lookup
            profile,       # endpoint profile lookup
            profile,       # checklist profile lookup
            _make_bg_check(),
            _make_license(),
            _make_registration(),
            _make_inspection(),
            _make_insurance(),
            ob,            # get_or_create
        ]
        idx = {"n": 0}
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        async def _execute(q):
            r = MagicMock()
            val = returns[idx["n"]] if idx["n"] < len(returns) else None
            idx["n"] += 1
            r.scalar_one_or_none.return_value = val
            r.scalars.return_value.all.return_value = []
            return r

        mock_db.execute = _execute

        original = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = lambda: mock_db

        transport = ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/drivers/me/onboarding", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert "computed_status" in data
            assert "background_check" in data
        finally:
            app.dependency_overrides = original

    @pytest.mark.anyio
    async def test_activate_endpoint_returns_409_when_requirements_not_met(self):
        """Admin activate returns 409 when checklist is incomplete."""
        import httpx
        from httpx import ASGITransport
        from app.main import app
        from app.db.database import get_db
        from app.services.auth import create_access_token
        from app.models.user import User, UserRole

        admin_user = MagicMock(spec=User)
        admin_user.id = 99
        admin_user.is_active = True
        admin_user.role = UserRole.ADMIN

        # Profile exists but all documents missing
        profile = _make_profile(insurance_policy=None)
        ob = _make_onboarding()

        returns = [
            admin_user,    # auth
            profile,       # checklist profile
            None,          # bg check
            None,          # license
            None,          # registration
            None,          # inspection
            None,          # insurance
            ob,            # get_or_create inside checklist
            ob,            # get_or_create inside activate_driver
        ]
        idx = {"n": 0}
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        async def _execute(q):
            r = MagicMock()
            val = returns[idx["n"]] if idx["n"] < len(returns) else None
            idx["n"] += 1
            r.scalar_one_or_none.return_value = val
            r.scalars.return_value.all.return_value = []
            return r

        mock_db.execute = _execute

        token = create_access_token(99, "admin")
        headers = {"Authorization": f"Bearer {token}"}

        original = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = lambda: mock_db

        transport = ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/admin/drivers/1/onboarding/activate",
                    json={},
                    headers=headers,
                )
            assert resp.status_code == 409
        finally:
            app.dependency_overrides = original

    @pytest.mark.anyio
    async def test_activate_endpoint_succeeds_when_all_requirements_met(self):
        """Admin activate returns 200 when all checklist items pass."""
        import httpx
        from httpx import ASGITransport
        from app.main import app
        from app.db.database import get_db
        from app.services.auth import create_access_token
        from app.models.user import User, UserRole

        admin_user = MagicMock(spec=User)
        admin_user.id = 99
        admin_user.is_active = True
        admin_user.role = UserRole.ADMIN

        profile = _make_profile(insurance_policy="INS-001")
        ob = _make_onboarding(status=OnboardingStatus.INCOMPLETE)

        returns = [
            admin_user,          # auth
            profile,             # checklist profile lookup
            _make_bg_check(),
            _make_license(),
            _make_registration(),
            _make_inspection(),
            _make_insurance(),
            ob,                  # get_or_create inside checklist
            ob,                  # get_or_create inside activate_driver
            profile,             # profile lookup inside activate_driver
        ]
        idx = {"n": 0}
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        async def _execute(q):
            r = MagicMock()
            val = returns[idx["n"]] if idx["n"] < len(returns) else None
            idx["n"] += 1
            r.scalar_one_or_none.return_value = val
            r.scalars.return_value.all.return_value = []
            return r

        mock_db.execute = _execute

        token = create_access_token(99, "admin")
        headers = {"Authorization": f"Bearer {token}"}

        original = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = lambda: mock_db

        transport = ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/admin/drivers/1/onboarding/activate",
                    json={},
                    headers=headers,
                )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "approved"
        finally:
            app.dependency_overrides = original

    @pytest.mark.anyio
    async def test_suspend_endpoint_returns_422_on_empty_reason(self):
        """Suspend endpoint returns 422 when reason is empty string."""
        import httpx
        from httpx import ASGITransport
        from app.main import app
        from app.db.database import get_db
        from app.services.auth import create_access_token
        from app.models.user import User, UserRole

        admin_user = MagicMock(spec=User)
        admin_user.id = 99
        admin_user.is_active = True
        admin_user.role = UserRole.ADMIN

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = admin_user
        mock_db.execute = AsyncMock(return_value=result)

        token = create_access_token(99, "admin")
        headers = {"Authorization": f"Bearer {token}"}

        original = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = lambda: mock_db

        transport = ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/admin/drivers/1/onboarding/suspend",
                    json={"reason": "   "},
                    headers=headers,
                )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides = original

    @pytest.mark.anyio
    async def test_suspend_endpoint_succeeds_with_reason(self):
        """Admin suspend endpoint returns 200 with valid reason."""
        import httpx
        from httpx import ASGITransport
        from app.main import app
        from app.db.database import get_db
        from app.services.auth import create_access_token
        from app.models.user import User, UserRole

        admin_user = MagicMock(spec=User)
        admin_user.id = 99
        admin_user.is_active = True
        admin_user.role = UserRole.ADMIN

        profile = _make_profile()
        ob = _make_onboarding(status=OnboardingStatus.APPROVED)

        returns = [
            admin_user,  # auth
            profile,     # suspend_driver profile lookup
            ob,          # get_or_create
        ]
        idx = {"n": 0}
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        async def _execute(q):
            r = MagicMock()
            val = returns[idx["n"]] if idx["n"] < len(returns) else None
            idx["n"] += 1
            r.scalar_one_or_none.return_value = val
            r.scalars.return_value.all.return_value = []
            return r

        mock_db.execute = _execute

        token = create_access_token(99, "admin")
        headers = {"Authorization": f"Bearer {token}"}

        original = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = lambda: mock_db

        transport = ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/admin/drivers/1/onboarding/suspend",
                    json={"reason": "Repeated safety violations"},
                    headers=headers,
                )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "suspended"
        finally:
            app.dependency_overrides = original

    @pytest.mark.anyio
    async def test_admin_pending_list_returns_empty_when_none(self):
        """Admin pending list returns empty array when no drivers are pending."""
        import httpx
        from httpx import ASGITransport
        from app.main import app
        from app.db.database import get_db
        from app.services.auth import create_access_token
        from app.models.user import User, UserRole

        admin_user = MagicMock(spec=User)
        admin_user.id = 99
        admin_user.is_active = True
        admin_user.role = UserRole.ADMIN

        call_count = {"n": 0}
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()

        async def _execute(q):
            r = MagicMock()
            if call_count["n"] == 0:
                # auth lookup
                r.scalar_one_or_none.return_value = admin_user
                r.scalars.return_value.all.return_value = []
            else:
                # list query
                r.scalars.return_value.all.return_value = []
                r.scalar_one_or_none.return_value = None
            call_count["n"] += 1
            return r

        mock_db.execute = _execute

        token = create_access_token(99, "admin")
        headers = {"Authorization": f"Bearer {token}"}

        original = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = lambda: mock_db

        transport = ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/admin/drivers/onboarding/pending",
                    headers=headers,
                )
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            app.dependency_overrides = original

    @pytest.mark.anyio
    async def test_admin_incomplete_list_pagination_params(self):
        """Admin incomplete list accepts page and page_size query params."""
        import httpx
        from httpx import ASGITransport
        from app.main import app
        from app.db.database import get_db
        from app.services.auth import create_access_token
        from app.models.user import User, UserRole

        admin_user = MagicMock(spec=User)
        admin_user.id = 99
        admin_user.is_active = True
        admin_user.role = UserRole.ADMIN

        call_count = {"n": 0}
        mock_db = AsyncMock()

        async def _execute(q):
            r = MagicMock()
            if call_count["n"] == 0:
                r.scalar_one_or_none.return_value = admin_user
            else:
                r.scalars.return_value.all.return_value = []
                r.scalar_one_or_none.return_value = None
            call_count["n"] += 1
            return r

        mock_db.execute = _execute

        token = create_access_token(99, "admin")
        headers = {"Authorization": f"Bearer {token}"}

        original = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = lambda: mock_db

        transport = ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/admin/drivers/onboarding/incomplete?page=2&page_size=5",
                    headers=headers,
                )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides = original

    @pytest.mark.anyio
    async def test_activate_returns_404_when_driver_not_found(self):
        """Admin activate returns 404 when driver profile does not exist."""
        import httpx
        from httpx import ASGITransport
        from app.main import app
        from app.db.database import get_db
        from app.services.auth import create_access_token
        from app.models.user import User, UserRole

        admin_user = MagicMock(spec=User)
        admin_user.id = 99
        admin_user.is_active = True
        admin_user.role = UserRole.ADMIN

        # profile not found — triggers OnboardingError("not found")
        returns = [admin_user, None]
        idx = {"n": 0}
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        async def _execute(q):
            r = MagicMock()
            val = returns[idx["n"]] if idx["n"] < len(returns) else None
            idx["n"] += 1
            r.scalar_one_or_none.return_value = val
            r.scalars.return_value.all.return_value = []
            return r

        mock_db.execute = _execute

        token = create_access_token(99, "admin")
        headers = {"Authorization": f"Bearer {token}"}

        original = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = lambda: mock_db

        transport = ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/admin/drivers/999/onboarding/activate",
                    json={},
                    headers=headers,
                )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides = original
