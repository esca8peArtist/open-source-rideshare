"""Unit tests for the driver document expiry alert feature.

Tests cover:
  - Service: get_driver_expiry_status
  - Service: get_all_expiring_documents
  - Service: run_expiry_scan
  - Endpoint: GET /drivers/me/documents/expiry-status
  - Endpoint: GET /admin/documents/expiring
  - Endpoint: POST /admin/documents/expiry/scan
  - Schema: DriverExpiryStatusResponse, AdminExpiringDocumentsResponse
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.driver_documents import DocumentStatus, DriverLicense, VehicleRegistration
from app.models.driver_insurance import DriverInsuranceDocument, InsuranceDocumentStatus
from app.models.vehicle_inspection import InspectionStatus, VehicleInspection
from app.models.user import User, UserRole
from app.services.document_expiry_alerts import (
    ExpiringDocument,
    ExpiryScaResult,
    ExpiryStatusResult,
    DriverExpiryRow,
    _classify,
    _days_until,
)


TODAY = date(2026, 4, 15)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _license(
    lic_id: int = 1,
    driver_id: int = 10,
    expiry_date: date = TODAY + timedelta(days=20),
    status: DocumentStatus = DocumentStatus.APPROVED,
) -> DriverLicense:
    obj = MagicMock(spec=DriverLicense)
    obj.id = lic_id
    obj.driver_id = driver_id
    obj.expiry_date = expiry_date
    obj.status = status
    return obj


def _registration(
    reg_id: int = 2,
    driver_id: int = 10,
    expiry_date: date = TODAY + timedelta(days=5),
    status: DocumentStatus = DocumentStatus.APPROVED,
) -> VehicleRegistration:
    obj = MagicMock(spec=VehicleRegistration)
    obj.id = reg_id
    obj.driver_id = driver_id
    obj.expiry_date = expiry_date
    obj.status = status
    return obj


def _insurance(
    ins_id: int = 3,
    driver_id: int = 10,
    policy_end_date: date = TODAY - timedelta(days=3),
    status: InsuranceDocumentStatus = InsuranceDocumentStatus.APPROVED,
) -> DriverInsuranceDocument:
    obj = MagicMock(spec=DriverInsuranceDocument)
    obj.id = ins_id
    obj.driver_id = driver_id
    obj.policy_end_date = policy_end_date
    obj.status = status
    return obj


def _inspection(
    insp_id: int = 4,
    driver_id: int = 10,
    expiry_date: date | None = TODAY + timedelta(days=10),
    status: InspectionStatus = InspectionStatus.APPROVED,
) -> VehicleInspection:
    obj = MagicMock(spec=VehicleInspection)
    obj.id = insp_id
    obj.driver_id = driver_id
    obj.expiry_date = expiry_date
    obj.status = status
    return obj


def _user(user_id: int = 10, role: UserRole = UserRole.DRIVER) -> User:
    u = MagicMock(spec=User)
    u.id = user_id
    u.role = role
    return u


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_days_until_future(self):
        assert _days_until(TODAY + timedelta(days=5), TODAY) == 5

    def test_days_until_past(self):
        assert _days_until(TODAY - timedelta(days=2), TODAY) == -2

    def test_days_until_today(self):
        assert _days_until(TODAY, TODAY) == 0

    def test_days_until_none(self):
        assert _days_until(None, TODAY) is None

    def test_classify_expiring(self):
        assert _classify(TODAY + timedelta(days=15), TODAY, 30) == "expiring"

    def test_classify_expired(self):
        assert _classify(TODAY - timedelta(days=1), TODAY, 30) == "expired"

    def test_classify_none_not_in_window(self):
        assert _classify(TODAY + timedelta(days=60), TODAY, 30) is None

    def test_classify_exactly_at_boundary(self):
        assert _classify(TODAY + timedelta(days=30), TODAY, 30) == "expiring"

    def test_classify_none_expiry(self):
        assert _classify(None, TODAY, 30) is None


# ---------------------------------------------------------------------------
# ExpiryStatusResult dataclass
# ---------------------------------------------------------------------------

class TestExpiryStatusResult:
    def test_has_issues_false_when_empty(self):
        result = ExpiryStatusResult(driver_id=1)
        assert not result.has_issues

    def test_has_issues_true_with_expiring(self):
        result = ExpiryStatusResult(
            driver_id=1,
            expiring=[ExpiringDocument("license", 1, TODAY, 5, "approved")],
        )
        assert result.has_issues

    def test_has_issues_true_with_expired(self):
        result = ExpiryStatusResult(
            driver_id=1,
            expired=[ExpiringDocument("insurance", 3, TODAY - timedelta(3), -3, "approved")],
        )
        assert result.has_issues


# ---------------------------------------------------------------------------
# Service: get_driver_expiry_status
# ---------------------------------------------------------------------------

class TestGetDriverExpiryStatus:

    def _make_db(self, *doc_sets):
        """Build an AsyncMock db that returns doc_sets in order of execute() calls."""
        call_count = 0

        async def mock_execute(query, *a, **kw):
            nonlocal call_count
            idx = call_count
            call_count += 1
            docs = doc_sets[idx] if idx < len(doc_sets) else []
            result = MagicMock()
            result.scalars.return_value = iter(docs)
            return result

        db = AsyncMock()
        db.execute = mock_execute
        return db

    @pytest.mark.asyncio
    async def test_empty_driver_no_documents(self):
        from app.services.document_expiry_alerts import get_driver_expiry_status
        db = self._make_db([], [], [], [])
        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            status = await get_driver_expiry_status(10, db, days_ahead=30)
        assert status.driver_id == 10
        assert not status.expiring
        assert not status.expired
        assert not status.has_issues

    @pytest.mark.asyncio
    async def test_license_expiring_soon(self):
        from app.services.document_expiry_alerts import get_driver_expiry_status
        lic = _license(expiry_date=TODAY + timedelta(days=10))
        db = self._make_db([lic], [], [], [])
        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            status = await get_driver_expiry_status(10, db, days_ahead=30)
        assert len(status.expiring) == 1
        assert status.expiring[0].doc_type == "license"
        assert status.expiring[0].days_until_expiry == 10
        assert not status.expired

    @pytest.mark.asyncio
    async def test_insurance_expired(self):
        from app.services.document_expiry_alerts import get_driver_expiry_status
        ins = _insurance(policy_end_date=TODAY - timedelta(days=5))
        db = self._make_db([], [], [ins], [])
        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            status = await get_driver_expiry_status(10, db, days_ahead=30)
        assert len(status.expired) == 1
        assert status.expired[0].doc_type == "insurance"
        assert status.expired[0].days_until_expiry == -5

    @pytest.mark.asyncio
    async def test_inspection_no_expiry_date_ignored(self):
        from app.services.document_expiry_alerts import get_driver_expiry_status
        insp = _inspection(expiry_date=None)
        db = self._make_db([], [], [], [insp])
        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            status = await get_driver_expiry_status(10, db, days_ahead=30)
        assert not status.expiring
        assert not status.expired

    @pytest.mark.asyncio
    async def test_multiple_doc_types_mixed(self):
        from app.services.document_expiry_alerts import get_driver_expiry_status
        lic = _license(expiry_date=TODAY + timedelta(days=7))
        ins = _insurance(policy_end_date=TODAY - timedelta(days=1))
        db = self._make_db([lic], [], [ins], [])
        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            status = await get_driver_expiry_status(10, db, days_ahead=30)
        assert len(status.expiring) == 1
        assert status.expiring[0].doc_type == "license"
        assert len(status.expired) == 1
        assert status.expired[0].doc_type == "insurance"
        assert status.has_issues

    @pytest.mark.asyncio
    async def test_document_outside_window_not_included(self):
        from app.services.document_expiry_alerts import get_driver_expiry_status
        lic = _license(expiry_date=TODAY + timedelta(days=60))
        db = self._make_db([lic], [], [], [])
        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            status = await get_driver_expiry_status(10, db, days_ahead=30)
        assert not status.expiring
        assert not status.expired

    @pytest.mark.asyncio
    async def test_registration_expiring(self):
        from app.services.document_expiry_alerts import get_driver_expiry_status
        reg = _registration(expiry_date=TODAY + timedelta(days=3))
        db = self._make_db([], [reg], [], [])
        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            status = await get_driver_expiry_status(10, db, days_ahead=30)
        assert len(status.expiring) == 1
        assert status.expiring[0].doc_type == "registration"

    @pytest.mark.asyncio
    async def test_inspection_expiring(self):
        from app.services.document_expiry_alerts import get_driver_expiry_status
        insp = _inspection(expiry_date=TODAY + timedelta(days=14))
        db = self._make_db([], [], [], [insp])
        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            status = await get_driver_expiry_status(10, db, days_ahead=30)
        assert len(status.expiring) == 1
        assert status.expiring[0].doc_type == "inspection"


# ---------------------------------------------------------------------------
# Service: get_all_expiring_documents
# ---------------------------------------------------------------------------

class TestGetAllExpiringDocuments:

    def _make_db(self, *doc_sets):
        call_count = 0

        async def mock_execute(query, *a, **kw):
            nonlocal call_count
            idx = call_count
            call_count += 1
            docs = doc_sets[idx] if idx < len(doc_sets) else []
            result = MagicMock()
            result.scalars.return_value = iter(docs)
            return result

        db = AsyncMock()
        db.execute = mock_execute
        return db

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_expiring(self):
        from app.services.document_expiry_alerts import get_all_expiring_documents
        db = self._make_db([], [], [], [])
        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_all_expiring_documents(db, days_ahead=30)
        assert rows == []

    @pytest.mark.asyncio
    async def test_returns_expiring_license(self):
        from app.services.document_expiry_alerts import get_all_expiring_documents
        lic = _license(driver_id=5, expiry_date=TODAY + timedelta(days=10))
        db = self._make_db([lic], [], [], [])
        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_all_expiring_documents(db, days_ahead=30)
        assert len(rows) == 1
        assert rows[0].doc_type == "license"
        assert rows[0].driver_id == 5
        assert rows[0].days_until_expiry == 10

    @pytest.mark.asyncio
    async def test_doc_type_filter_license_only(self):
        from app.services.document_expiry_alerts import get_all_expiring_documents
        lic = _license(driver_id=5, expiry_date=TODAY + timedelta(days=10))
        db = self._make_db([lic])
        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_all_expiring_documents(db, days_ahead=30, doc_type="license")
        assert len(rows) == 1
        assert rows[0].doc_type == "license"

    @pytest.mark.asyncio
    async def test_doc_type_filter_insurance_only(self):
        from app.services.document_expiry_alerts import get_all_expiring_documents
        ins = _insurance(driver_id=7, policy_end_date=TODAY - timedelta(days=2))
        db = self._make_db([ins])
        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_all_expiring_documents(db, days_ahead=30, doc_type="insurance")
        assert len(rows) == 1
        assert rows[0].doc_type == "insurance"
        assert rows[0].days_until_expiry == -2

    @pytest.mark.asyncio
    async def test_sorted_expired_before_expiring(self):
        from app.services.document_expiry_alerts import get_all_expiring_documents
        lic_expiring = _license(lic_id=1, driver_id=5, expiry_date=TODAY + timedelta(days=10))
        lic_expired = _license(lic_id=2, driver_id=6, expiry_date=TODAY - timedelta(days=5))
        db = self._make_db([lic_expiring, lic_expired], [], [], [])
        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_all_expiring_documents(db, days_ahead=30)
        assert rows[0].days_until_expiry == -5
        assert rows[1].days_until_expiry == 10

    @pytest.mark.asyncio
    async def test_pagination_skip_limit(self):
        from app.services.document_expiry_alerts import get_all_expiring_documents
        lics = [_license(lic_id=i, driver_id=i, expiry_date=TODAY + timedelta(days=i))
                for i in range(1, 6)]
        db = self._make_db(lics, [], [], [])
        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_all_expiring_documents(db, days_ahead=30, skip=2, limit=2)
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_registration_expiry_included(self):
        from app.services.document_expiry_alerts import get_all_expiring_documents
        reg = _registration(reg_id=10, driver_id=20, expiry_date=TODAY + timedelta(days=15))
        db = self._make_db([], [reg], [], [])
        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_all_expiring_documents(db, days_ahead=30)
        assert len(rows) == 1
        assert rows[0].doc_type == "registration"

    @pytest.mark.asyncio
    async def test_inspection_expiry_included(self):
        from app.services.document_expiry_alerts import get_all_expiring_documents
        insp = _inspection(insp_id=5, driver_id=30, expiry_date=TODAY + timedelta(days=5))
        db = self._make_db([], [], [], [insp])
        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_all_expiring_documents(db, days_ahead=30)
        assert len(rows) == 1
        assert rows[0].doc_type == "inspection"


# ---------------------------------------------------------------------------
# Service: run_expiry_scan
# ---------------------------------------------------------------------------

class TestRunExpiryScan:

    @pytest.mark.asyncio
    async def test_scan_returns_counts(self):
        from app.services.document_expiry_alerts import run_expiry_scan

        db = AsyncMock()

        async def mock_execute(query, *a, **kw):
            result = MagicMock()
            result.rowcount = 3
            return result

        db.execute = mock_execute

        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            result = await run_expiry_scan(db)

        assert result.licenses_marked_expired == 3
        assert result.registrations_marked_expired == 3
        assert result.insurance_marked_expired == 3
        assert result.inspections_marked_expired == 3
        assert result.total_marked_expired == 12
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scan_zero_counts(self):
        from app.services.document_expiry_alerts import run_expiry_scan

        db = AsyncMock()

        async def mock_execute(query, *a, **kw):
            result = MagicMock()
            result.rowcount = 0
            return result

        db.execute = mock_execute

        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            result = await run_expiry_scan(db)

        assert result.total_marked_expired == 0

    @pytest.mark.asyncio
    async def test_scan_commits(self):
        from app.services.document_expiry_alerts import run_expiry_scan

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(rowcount=0))
        with patch("app.services.document_expiry_alerts.date") as mock_date:
            mock_date.today.return_value = TODAY
            await run_expiry_scan(db)
        db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------

class TestDriverExpiryStatusEndpoint:

    @pytest.mark.asyncio
    async def test_returns_clean_status(self):
        from app.api.v1.document_expiry import driver_expiry_status

        user = _user(user_id=10)
        db = AsyncMock()
        mock_status = ExpiryStatusResult(driver_id=10)

        with patch(
            "app.api.v1.document_expiry.get_driver_expiry_status",
            new_callable=AsyncMock,
            return_value=mock_status,
        ) as mock_svc:
            result = await driver_expiry_status(days=30, user=user, db=db)
            mock_svc.assert_awaited_once_with(10, db, days_ahead=30)

        assert result.driver_id == 10
        assert result.expiring == []
        assert result.expired == []
        assert not result.has_issues

    @pytest.mark.asyncio
    async def test_returns_expiring_documents(self):
        from app.api.v1.document_expiry import driver_expiry_status

        user = _user(user_id=5)
        db = AsyncMock()
        mock_status = ExpiryStatusResult(
            driver_id=5,
            expiring=[
                ExpiringDocument("license", 1, TODAY + timedelta(days=10), 10, "approved"),
                ExpiringDocument("registration", 2, TODAY + timedelta(days=3), 3, "approved"),
            ],
        )

        with patch(
            "app.api.v1.document_expiry.get_driver_expiry_status",
            new_callable=AsyncMock,
            return_value=mock_status,
        ):
            result = await driver_expiry_status(days=30, user=user, db=db)

        assert len(result.expiring) == 2
        assert result.has_issues

    @pytest.mark.asyncio
    async def test_expired_documents_in_response(self):
        from app.api.v1.document_expiry import driver_expiry_status

        user = _user(user_id=7)
        db = AsyncMock()
        mock_status = ExpiryStatusResult(
            driver_id=7,
            expired=[
                ExpiringDocument("insurance", 3, TODAY - timedelta(days=5), -5, "approved"),
            ],
        )

        with patch(
            "app.api.v1.document_expiry.get_driver_expiry_status",
            new_callable=AsyncMock,
            return_value=mock_status,
        ):
            result = await driver_expiry_status(days=30, user=user, db=db)

        assert len(result.expired) == 1
        assert result.expired[0].doc_type == "insurance"
        assert result.expired[0].days_until_expiry == -5


class TestAdminExpiringDocumentsEndpoint:

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        from app.api.v1.document_expiry import admin_expiring_documents

        admin = _user(role=UserRole.ADMIN)
        db = AsyncMock()

        with patch(
            "app.api.v1.document_expiry.get_all_expiring_documents",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await admin_expiring_documents(
                days=30, doc_type=None, skip=0, limit=100,
                _admin=admin, db=db,
            )

        assert result.items == []
        assert result.total == 0
        assert result.days_ahead == 30
        assert result.doc_type_filter is None

    @pytest.mark.asyncio
    async def test_returns_driver_rows(self):
        from app.api.v1.document_expiry import admin_expiring_documents

        admin = _user(role=UserRole.ADMIN)
        db = AsyncMock()
        mock_rows = [
            DriverExpiryRow(
                driver_id=10, doc_type="license", doc_id=1,
                expiry_date=TODAY + timedelta(days=5), days_until_expiry=5, status="approved",
            ),
            DriverExpiryRow(
                driver_id=20, doc_type="insurance", doc_id=3,
                expiry_date=TODAY - timedelta(days=2), days_until_expiry=-2, status="approved",
            ),
        ]

        with patch(
            "app.api.v1.document_expiry.get_all_expiring_documents",
            new_callable=AsyncMock,
            return_value=mock_rows,
        ):
            result = await admin_expiring_documents(
                days=30, doc_type=None, skip=0, limit=100,
                _admin=admin, db=db,
            )

        assert result.total == 2
        assert result.items[0].driver_id == 10
        assert result.items[1].doc_type == "insurance"

    @pytest.mark.asyncio
    async def test_doc_type_filter_passed_to_service(self):
        from app.api.v1.document_expiry import admin_expiring_documents

        admin = _user(role=UserRole.ADMIN)
        db = AsyncMock()

        with patch(
            "app.api.v1.document_expiry.get_all_expiring_documents",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_svc:
            await admin_expiring_documents(
                days=14, doc_type="license", skip=0, limit=50,
                _admin=admin, db=db,
            )
            mock_svc.assert_awaited_once_with(db, days_ahead=14, doc_type="license", skip=0, limit=50)

    @pytest.mark.asyncio
    async def test_days_ahead_filter_in_response(self):
        from app.api.v1.document_expiry import admin_expiring_documents

        admin = _user(role=UserRole.ADMIN)
        db = AsyncMock()

        with patch(
            "app.api.v1.document_expiry.get_all_expiring_documents",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await admin_expiring_documents(
                days=7, doc_type=None, skip=0, limit=100,
                _admin=admin, db=db,
            )

        assert result.days_ahead == 7


class TestAdminExpiryScaEndpoint:

    @pytest.mark.asyncio
    async def test_returns_scan_result(self):
        from app.api.v1.document_expiry import admin_run_expiry_scan

        admin = _user(role=UserRole.ADMIN)
        db = AsyncMock()
        mock_result = ExpiryScaResult(
            licenses_marked_expired=2,
            registrations_marked_expired=1,
            insurance_marked_expired=3,
            inspections_marked_expired=0,
        )

        with patch(
            "app.api.v1.document_expiry.run_expiry_scan",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_svc:
            result = await admin_run_expiry_scan(_admin=admin, db=db)
            mock_svc.assert_awaited_once_with(db)

        assert result.licenses_marked_expired == 2
        assert result.registrations_marked_expired == 1
        assert result.insurance_marked_expired == 3
        assert result.inspections_marked_expired == 0
        assert result.total_marked_expired == 6

    @pytest.mark.asyncio
    async def test_zero_result_on_no_expired_docs(self):
        from app.api.v1.document_expiry import admin_run_expiry_scan

        admin = _user(role=UserRole.ADMIN)
        db = AsyncMock()
        mock_result = ExpiryScaResult()

        with patch(
            "app.api.v1.document_expiry.run_expiry_scan",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await admin_run_expiry_scan(_admin=admin, db=db)

        assert result.total_marked_expired == 0


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchemas:

    def test_driver_expiry_status_response_minimal(self):
        from app.schemas.document_expiry import DriverExpiryStatusResponse

        obj = DriverExpiryStatusResponse(
            driver_id=1,
            expiring=[],
            expired=[],
            has_issues=False,
        )
        assert obj.driver_id == 1
        assert not obj.has_issues

    def test_expiring_document_item(self):
        from app.schemas.document_expiry import ExpiringDocumentItem

        item = ExpiringDocumentItem(
            doc_type="license",
            doc_id=42,
            expiry_date=date(2026, 5, 1),
            days_until_expiry=16,
            status="approved",
        )
        assert item.doc_type == "license"
        assert item.days_until_expiry == 16

    def test_expiring_document_item_no_expiry(self):
        from app.schemas.document_expiry import ExpiringDocumentItem

        item = ExpiringDocumentItem(
            doc_type="inspection",
            doc_id=7,
            expiry_date=None,
            days_until_expiry=None,
            status="approved",
        )
        assert item.expiry_date is None
        assert item.days_until_expiry is None

    def test_expiry_scan_response(self):
        from app.schemas.document_expiry import ExpiryScaResponse

        obj = ExpiryScaResponse(
            licenses_marked_expired=1,
            registrations_marked_expired=2,
            insurance_marked_expired=0,
            inspections_marked_expired=3,
            total_marked_expired=6,
        )
        assert obj.total_marked_expired == 6

    def test_admin_expiring_documents_response(self):
        from app.schemas.document_expiry import AdminExpiringDocumentsResponse, AdminExpiringDocumentRow

        obj = AdminExpiringDocumentsResponse(
            items=[
                AdminExpiringDocumentRow(
                    driver_id=10,
                    doc_type="registration",
                    doc_id=5,
                    expiry_date=date(2026, 4, 20),
                    days_until_expiry=5,
                    status="approved",
                )
            ],
            total=1,
            days_ahead=30,
            doc_type_filter=None,
        )
        assert obj.total == 1
        assert obj.items[0].doc_type == "registration"
        assert obj.doc_type_filter is None

    def test_admin_expiring_documents_with_doc_type_filter(self):
        from app.schemas.document_expiry import AdminExpiringDocumentsResponse

        obj = AdminExpiringDocumentsResponse(
            items=[],
            total=0,
            days_ahead=7,
            doc_type_filter="insurance",
        )
        assert obj.doc_type_filter == "insurance"
        assert obj.days_ahead == 7

    def test_negative_days_until_expiry_is_valid(self):
        from app.schemas.document_expiry import AdminExpiringDocumentRow

        row = AdminExpiringDocumentRow(
            driver_id=1,
            doc_type="license",
            doc_id=1,
            expiry_date=date(2026, 4, 10),
            days_until_expiry=-5,
            status="approved",
        )
        assert row.days_until_expiry == -5
