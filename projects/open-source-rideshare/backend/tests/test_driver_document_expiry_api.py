"""Tests for driver document expiry API endpoints and the new service function.

Covers:
- get_expiring_documents_for_driver: empty result, per-doc-type results, multi-doc, sorting
- GET /api/v1/drivers/me/document-expiry: 200 empty, 200 with items, has_expired flag,
  has_warning flag, urgency labels, 403 for rider/admin callers
- GET /api/v1/admin/document-expiry: 200 all docs, expired_only filter,
  days_ahead parameter, 403 for driver/rider callers
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _make_scalars_all(objects: list):
    """Return a MagicMock that mimics scalars().all() returning *objects*."""
    scalars = MagicMock()
    scalars.all.return_value = objects
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _build_db_for_driver_query(license_objs, reg_objs, ins_objs):
    """AsyncMock DB whose three execute() calls return separate lists for each doc type."""
    db = AsyncMock()
    db.execute.side_effect = [
        _make_scalars_all(license_objs),
        _make_scalars_all(reg_objs),
        _make_scalars_all(ins_objs),
    ]
    return db


def _mock_license(days_offset: int, driver_id: int = 10):
    lic = MagicMock()
    lic.id = 1
    lic.driver_id = driver_id
    lic.expiry_date = date.today() + timedelta(days=days_offset)
    return lic


def _mock_registration(days_offset: int, driver_id: int = 10):
    reg = MagicMock()
    reg.id = 2
    reg.driver_id = driver_id
    reg.expiry_date = date.today() + timedelta(days=days_offset)
    return reg


def _mock_insurance(days_offset: int, driver_id: int = 10):
    ins = MagicMock()
    ins.id = 3
    ins.driver_id = driver_id
    ins.policy_end_date = date.today() + timedelta(days=days_offset)
    return ins


def _make_mock_user(role_value: str, user_id: int = 42):
    user = MagicMock()
    user.id = user_id
    user.role = MagicMock()
    user.role.value = role_value
    return user


# ---------------------------------------------------------------------------
# Unit tests: get_expiring_documents_for_driver
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetExpiringDocumentsForDriver:
    async def test_returns_empty_list_when_no_docs(self):
        """No documents in any category returns an empty list."""
        from app.services.driver_document_expiry import get_expiring_documents_for_driver

        db = _build_db_for_driver_query([], [], [])
        result = await get_expiring_documents_for_driver(db, driver_id=10, days_ahead=30)
        assert result == []

    async def test_returns_expiring_license(self):
        """An expiring license is included with correct fields."""
        from app.services.driver_document_expiry import get_expiring_documents_for_driver

        lic = _mock_license(15)
        db = _build_db_for_driver_query([lic], [], [])
        result = await get_expiring_documents_for_driver(db, driver_id=10, days_ahead=30)
        assert len(result) == 1
        assert result[0].document_type == "license"
        assert result[0].driver_id == 10
        assert result[0].days_remaining == 15

    async def test_returns_expiring_registration(self):
        """An expiring registration is included with correct fields."""
        from app.services.driver_document_expiry import get_expiring_documents_for_driver

        reg = _mock_registration(7)
        db = _build_db_for_driver_query([], [reg], [])
        result = await get_expiring_documents_for_driver(db, driver_id=10, days_ahead=30)
        assert len(result) == 1
        assert result[0].document_type == "vehicle_registration"
        assert result[0].days_remaining == 7

    async def test_returns_expired_insurance(self):
        """An already-expired insurance document has negative days_remaining."""
        from app.services.driver_document_expiry import get_expiring_documents_for_driver

        ins = _mock_insurance(-5)
        db = _build_db_for_driver_query([], [], [ins])
        result = await get_expiring_documents_for_driver(db, driver_id=10, days_ahead=30)
        assert len(result) == 1
        assert result[0].document_type == "vehicle_insurance"
        assert result[0].days_remaining == -5

    async def test_returns_multiple_docs_sorted_by_days_remaining(self):
        """Multiple expiring docs are sorted ascending (most urgent first)."""
        from app.services.driver_document_expiry import get_expiring_documents_for_driver

        lic = _mock_license(25)
        reg = _mock_registration(10)
        ins = _mock_insurance(-2)
        db = _build_db_for_driver_query([lic], [reg], [ins])
        result = await get_expiring_documents_for_driver(db, driver_id=10, days_ahead=30)
        assert len(result) == 3
        days = [r.days_remaining for r in result]
        assert days == sorted(days)  # ascending order

    async def test_performs_exactly_three_queries(self):
        """One query per document type."""
        from app.services.driver_document_expiry import get_expiring_documents_for_driver

        db = _build_db_for_driver_query([], [], [])
        await get_expiring_documents_for_driver(db, driver_id=10, days_ahead=30)
        assert db.execute.call_count == 3


# ---------------------------------------------------------------------------
# API tests: GET /drivers/me/document-expiry
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_driver_user():
    return _make_mock_user("driver", user_id=42)


@pytest.fixture
def mock_rider_user():
    return _make_mock_user("rider", user_id=55)


@pytest.fixture
def mock_admin_user():
    return _make_mock_user("admin", user_id=1)


@pytest.mark.asyncio
class TestDriverDocumentExpirySelf:
    async def _client(self, mock_user):
        from httpx import AsyncClient, ASGITransport
        from app.main import app as fastapi_app
        from app.db.database import get_db
        from app.api.deps import require_driver

        db = AsyncMock()

        async def override_get_db():
            yield db

        async def override_require_driver():
            return mock_user

        fastapi_app.dependency_overrides[get_db] = override_get_db
        fastapi_app.dependency_overrides[require_driver] = override_require_driver
        return AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test"), fastapi_app

    async def test_returns_200_with_empty_list_when_no_expiring_docs(self, mock_driver_user):
        """No expiring documents → 200 with empty documents list."""
        client, app = await self._client(mock_driver_user)
        try:
            with patch(
                "app.api.v1.driver_document_expiry.get_expiring_documents_for_driver",
                new=AsyncMock(return_value=[]),
            ):
                async with client as c:
                    resp = await c.get("/api/v1/drivers/me/document-expiry")
            assert resp.status_code == 200
            body = resp.json()
            assert body["documents"] == []
            assert body["has_expired"] is False
            assert body["has_warning"] is False
            assert body["driver_user_id"] == mock_driver_user.id
        finally:
            app.dependency_overrides.clear()

    async def test_returns_expiring_doc_with_correct_fields(self, mock_driver_user):
        """A warning-level doc appears with correct urgency, is_expired=False."""
        from app.services.driver_document_expiry import ExpiringDocument

        expiring_doc = ExpiringDocument(
            driver_id=mock_driver_user.id,
            document_type="license",
            expiry_date=date.today() + timedelta(days=20),
            document_id=1,
            days_remaining=20,
        )
        client, app = await self._client(mock_driver_user)
        try:
            with patch(
                "app.api.v1.driver_document_expiry.get_expiring_documents_for_driver",
                new=AsyncMock(return_value=[expiring_doc]),
            ):
                async with client as c:
                    resp = await c.get("/api/v1/drivers/me/document-expiry")
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["documents"]) == 1
            doc = body["documents"][0]
            assert doc["document_type"] == "license"
            assert doc["days_remaining"] == 20
            assert doc["is_expired"] is False
            assert doc["urgency"] == "warning"
            assert body["has_warning"] is True
            assert body["has_expired"] is False
        finally:
            app.dependency_overrides.clear()

    async def test_has_expired_true_when_doc_already_expired(self, mock_driver_user):
        """has_expired=True and urgency='expired' for a past-due document."""
        from app.services.driver_document_expiry import ExpiringDocument

        expired_doc = ExpiringDocument(
            driver_id=mock_driver_user.id,
            document_type="vehicle_insurance",
            expiry_date=date.today() - timedelta(days=3),
            document_id=3,
            days_remaining=-3,
        )
        client, app = await self._client(mock_driver_user)
        try:
            with patch(
                "app.api.v1.driver_document_expiry.get_expiring_documents_for_driver",
                new=AsyncMock(return_value=[expired_doc]),
            ):
                async with client as c:
                    resp = await c.get("/api/v1/drivers/me/document-expiry")
            assert resp.status_code == 200
            body = resp.json()
            assert body["has_expired"] is True
            assert body["documents"][0]["urgency"] == "expired"
        finally:
            app.dependency_overrides.clear()

    async def test_urgency_critical_for_doc_expiring_in_5_days(self, mock_driver_user):
        """A document expiring in 5 days gets urgency='critical'."""
        from app.services.driver_document_expiry import ExpiringDocument

        critical_doc = ExpiringDocument(
            driver_id=mock_driver_user.id,
            document_type="vehicle_registration",
            expiry_date=date.today() + timedelta(days=5),
            document_id=2,
            days_remaining=5,
        )
        client, app = await self._client(mock_driver_user)
        try:
            with patch(
                "app.api.v1.driver_document_expiry.get_expiring_documents_for_driver",
                new=AsyncMock(return_value=[critical_doc]),
            ):
                async with client as c:
                    resp = await c.get("/api/v1/drivers/me/document-expiry")
            body = resp.json()
            assert body["documents"][0]["urgency"] == "critical"
        finally:
            app.dependency_overrides.clear()

    async def test_urgency_ok_for_doc_expiring_in_45_days(self, mock_driver_user):
        """A document expiring in 45 days gets urgency='ok'."""
        from app.services.driver_document_expiry import ExpiringDocument

        ok_doc = ExpiringDocument(
            driver_id=mock_driver_user.id,
            document_type="license",
            expiry_date=date.today() + timedelta(days=45),
            document_id=1,
            days_remaining=45,
        )
        client, app = await self._client(mock_driver_user)
        try:
            with patch(
                "app.api.v1.driver_document_expiry.get_expiring_documents_for_driver",
                new=AsyncMock(return_value=[ok_doc]),
            ):
                async with client as c:
                    resp = await c.get("/api/v1/drivers/me/document-expiry?days_ahead=60")
            body = resp.json()
            assert body["documents"][0]["urgency"] == "ok"
        finally:
            app.dependency_overrides.clear()

    async def test_returns_403_when_called_by_rider(self):
        """Riders are not permitted to call the driver self-view endpoint."""
        from httpx import AsyncClient, ASGITransport
        from app.main import app as fastapi_app
        from app.db.database import get_db
        from app.api.deps import require_driver

        db = AsyncMock()

        async def override_get_db():
            yield db

        async def override_require_driver():
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Driver access required")

        fastapi_app.dependency_overrides[get_db] = override_get_db
        fastapi_app.dependency_overrides[require_driver] = override_require_driver
        try:
            async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as c:
                resp = await c.get("/api/v1/drivers/me/document-expiry")
            assert resp.status_code == 403
        finally:
            fastapi_app.dependency_overrides.clear()

    async def test_days_ahead_query_param_is_forwarded(self, mock_driver_user):
        """The days_ahead query param is forwarded to the service call."""
        from app.services.driver_document_expiry import ExpiringDocument

        mock_service = AsyncMock(return_value=[])
        client, app = await self._client(mock_driver_user)
        try:
            with patch(
                "app.api.v1.driver_document_expiry.get_expiring_documents_for_driver",
                new=mock_service,
            ):
                async with client as c:
                    await c.get("/api/v1/drivers/me/document-expiry?days_ahead=14")
            _, kwargs = mock_service.call_args
            assert kwargs.get("days_ahead") == 14 or mock_service.call_args[0][2] == 14
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# API tests: GET /admin/document-expiry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAdminDocumentExpiry:
    async def _admin_client(self, mock_user=None):
        from httpx import AsyncClient, ASGITransport
        from app.main import app as fastapi_app
        from app.db.database import get_db
        from app.api.deps import require_admin

        db = AsyncMock()
        if mock_user is None:
            mock_user = _make_mock_user("admin", user_id=1)

        async def override_get_db():
            yield db

        async def override_require_admin():
            return mock_user

        fastapi_app.dependency_overrides[get_db] = override_get_db
        fastapi_app.dependency_overrides[require_admin] = override_require_admin
        return AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test"), fastapi_app

    async def test_returns_200_with_empty_list(self):
        """No expiring docs → 200 with empty items list."""
        client, app = await self._admin_client()
        try:
            with patch(
                "app.api.v1.driver_document_expiry.get_expiring_documents",
                new=AsyncMock(return_value=[]),
            ):
                async with client as c:
                    resp = await c.get("/api/v1/admin/document-expiry")
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 0
            assert body["items"] == []
            assert body["days_ahead"] == 30
        finally:
            app.dependency_overrides.clear()

    async def test_returns_all_expiring_docs(self):
        """Returns all docs from get_expiring_documents regardless of driver."""
        from app.services.driver_document_expiry import ExpiringDocument

        docs = [
            ExpiringDocument(driver_id=10, document_type="license",
                             expiry_date=date.today() + timedelta(days=20),
                             document_id=1, days_remaining=20),
            ExpiringDocument(driver_id=11, document_type="vehicle_insurance",
                             expiry_date=date.today() - timedelta(days=2),
                             document_id=5, days_remaining=-2),
        ]
        client, app = await self._admin_client()
        try:
            with patch(
                "app.api.v1.driver_document_expiry.get_expiring_documents",
                new=AsyncMock(return_value=docs),
            ):
                async with client as c:
                    resp = await c.get("/api/v1/admin/document-expiry")
            body = resp.json()
            assert body["total"] == 2
            driver_ids = {i["driver_user_id"] for i in body["items"]}
            assert driver_ids == {10, 11}
        finally:
            app.dependency_overrides.clear()

    async def test_expired_only_filter(self):
        """expired_only=true retains only items with days_remaining < 0."""
        from app.services.driver_document_expiry import ExpiringDocument

        docs = [
            ExpiringDocument(driver_id=10, document_type="license",
                             expiry_date=date.today() + timedelta(days=15),
                             document_id=1, days_remaining=15),
            ExpiringDocument(driver_id=11, document_type="vehicle_insurance",
                             expiry_date=date.today() - timedelta(days=4),
                             document_id=5, days_remaining=-4),
        ]
        client, app = await self._admin_client()
        try:
            with patch(
                "app.api.v1.driver_document_expiry.get_expiring_documents",
                new=AsyncMock(return_value=docs),
            ):
                async with client as c:
                    resp = await c.get("/api/v1/admin/document-expiry?expired_only=true")
            body = resp.json()
            assert body["total"] == 1
            assert body["items"][0]["days_remaining"] == -4
        finally:
            app.dependency_overrides.clear()

    async def test_days_ahead_reflected_in_response(self):
        """Response days_ahead matches the query param."""
        client, app = await self._admin_client()
        try:
            with patch(
                "app.api.v1.driver_document_expiry.get_expiring_documents",
                new=AsyncMock(return_value=[]),
            ):
                async with client as c:
                    resp = await c.get("/api/v1/admin/document-expiry?days_ahead=7")
            body = resp.json()
            assert body["days_ahead"] == 7
        finally:
            app.dependency_overrides.clear()

    async def test_returns_403_when_called_by_driver(self):
        """Drivers cannot access the admin document-expiry endpoint."""
        from httpx import AsyncClient, ASGITransport
        from app.main import app as fastapi_app
        from app.db.database import get_db
        from app.api.deps import require_admin

        db = AsyncMock()

        async def override_get_db():
            yield db

        async def override_require_admin():
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Admin access required")

        fastapi_app.dependency_overrides[get_db] = override_get_db
        fastapi_app.dependency_overrides[require_admin] = override_require_admin
        try:
            async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as c:
                resp = await c.get("/api/v1/admin/document-expiry")
            assert resp.status_code == 403
        finally:
            fastapi_app.dependency_overrides.clear()

    async def test_returns_403_when_called_by_rider(self):
        """Riders cannot access the admin document-expiry endpoint."""
        from httpx import AsyncClient, ASGITransport
        from app.main import app as fastapi_app
        from app.db.database import get_db
        from app.api.deps import require_admin

        db = AsyncMock()

        async def override_get_db():
            yield db

        async def override_require_admin():
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Admin access required")

        fastapi_app.dependency_overrides[get_db] = override_get_db
        fastapi_app.dependency_overrides[require_admin] = override_require_admin
        try:
            async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as c:
                resp = await c.get("/api/v1/admin/document-expiry")
            assert resp.status_code == 403
        finally:
            fastapi_app.dependency_overrides.clear()

    async def test_items_include_all_doc_fields(self):
        """Each item in the admin response includes all required fields."""
        from app.services.driver_document_expiry import ExpiringDocument

        doc = ExpiringDocument(
            driver_id=77,
            document_type="vehicle_registration",
            expiry_date=date.today() + timedelta(days=10),
            document_id=9,
            days_remaining=10,
        )
        client, app = await self._admin_client()
        try:
            with patch(
                "app.api.v1.driver_document_expiry.get_expiring_documents",
                new=AsyncMock(return_value=[doc]),
            ):
                async with client as c:
                    resp = await c.get("/api/v1/admin/document-expiry")
            item = resp.json()["items"][0]
            assert set(item.keys()) == {
                "driver_user_id", "document_type", "expiry_date", "days_remaining"
            }
            assert item["driver_user_id"] == 77
            assert item["document_type"] == "vehicle_registration"
            assert item["days_remaining"] == 10
        finally:
            app.dependency_overrides.clear()
