"""Tests for driver incident reporting system.

Service layer (unit tests with mocked DB):
  1.  create_incident — creates report with correct fields
  2.  create_incident — encodes evidence_urls as comma-separated string
  3.  create_incident — handles empty evidence_urls
  4.  get_driver_incident — returns report when found
  5.  get_driver_incident — raises 404 when not found
  6.  list_driver_incidents — returns paginated results
  7.  update_driver_incident — updates description while submitted
  8.  update_driver_incident — raises 409 when status != submitted
  9.  update_driver_incident — raises 404 when not found
  10. admin_start_review — moves submitted → under_review
  11. admin_start_review — raises 409 when not submitted
  12. admin_resolve_incident — moves submitted → resolved
  13. admin_resolve_incident — moves under_review → resolved
  14. admin_resolve_incident — raises 409 when already resolved
  15. admin_dismiss_incident — moves submitted → dismissed
  16. admin_dismiss_incident — raises 409 when already dismissed
  17. admin_incident_summary — returns correct counts
  18. admin_get_incident — returns any incident by id
  19. admin_get_incident — raises 404 when not found
  20. admin_list_incidents — returns all when no filter

Schema:
  21. DriverIncidentCreate — validates description min length
  22. DriverIncidentCreate — validates evidence_urls max per-url length
  23. DriverIncidentResponse.from_orm_model — splits comma-separated urls

API layer (integration-style, skipped without live DB):
  24. POST /drivers/me/incidents — 201 creates report
  25. POST /drivers/me/incidents — 401 unauthenticated
  26. POST /drivers/me/incidents — 422 description too short
  27. GET  /drivers/me/incidents — 200 returns list
  28. GET  /drivers/me/incidents — 401 unauthenticated
  29. GET  /drivers/me/incidents/{id} — 200 returns report
  30. GET  /drivers/me/incidents/{id} — 404 wrong driver
  31. PUT  /drivers/me/incidents/{id} — 200 updates while submitted
  32. PUT  /drivers/me/incidents/{id} — 409 when under_review
  33. GET  /admin/driver-incidents — 200 returns all
  34. GET  /admin/driver-incidents — 403 non-admin
  35. GET  /admin/driver-incidents?status=submitted — filtered
  36. GET  /admin/driver-incidents/{id} — 200 returns report
  37. GET  /admin/driver-incidents/summary — 200 returns stats
  38. GET  /admin/driver-incidents/summary — 403 non-admin
  39. PUT  /admin/driver-incidents/{id}/review — 200 transitions to under_review
  40. PUT  /admin/driver-incidents/{id}/review — 403 non-admin
  41. PUT  /admin/driver-incidents/{id}/resolve — 200 transitions to resolved
  42. PUT  /admin/driver-incidents/{id}/resolve — 403 non-admin
  43. PUT  /admin/driver-incidents/{id}/dismiss — 200 transitions to dismissed
  44. PUT  /admin/driver-incidents/{id}/dismiss — 403 non-admin
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_incident import (
    DriverIncidentReport,
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
)
from app.models.user import User, UserRole
from app.schemas.driver_incident import (
    DriverIncidentCreate,
    DriverIncidentResponse,
)
from app.services.auth import create_access_token, hash_password
from app.services.driver_incident import (
    admin_dismiss_incident,
    admin_get_incident,
    admin_incident_summary,
    admin_list_incidents,
    admin_resolve_incident,
    admin_start_review,
    create_incident,
    get_driver_incident,
    list_driver_incidents,
    update_driver_incident,
)


# ===========================================================================
# Helpers / factories
# ===========================================================================

_BASE_TS = datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc)


def _make_report(
    *,
    report_id: int = 1,
    driver_id: int = 42,
    ride_id: int | None = None,
    incident_type: str = IncidentType.passenger_harassment.value,
    severity: str = IncidentSeverity.medium.value,
    status: str = IncidentStatus.submitted.value,
    description: str = "Passenger became verbally abusive during the ride.",
    evidence_urls: str | None = None,
    admin_note: str | None = None,
    reviewed_by_id: int | None = None,
    reviewed_at: datetime | None = None,
) -> MagicMock:
    r = MagicMock(spec=DriverIncidentReport)
    r.id = report_id
    r.driver_id = driver_id
    r.ride_id = ride_id
    r.incident_type = incident_type
    r.severity = severity
    r.status = status
    r.description = description
    r.evidence_urls = evidence_urls
    r.admin_note = admin_note
    r.reviewed_by_id = reviewed_by_id
    r.reviewed_at = reviewed_at
    r.created_at = _BASE_TS
    r.updated_at = _BASE_TS
    return r


def _scalar_result(value):
    m = MagicMock()
    m.scalar_one.return_value = value
    m.scalar_one_or_none.return_value = value
    inner = MagicMock()
    inner.first.return_value = value
    inner.all.return_value = [value] if value is not None else []
    m.scalars.return_value = inner
    return m


def _scalar_result_list(values: list):
    m = MagicMock()
    m.scalar_one.return_value = len(values)
    m.scalar_one_or_none.return_value = values[0] if values else None
    inner = MagicMock()
    inner.all.return_value = values
    m.scalars.return_value = inner
    return m


# ===========================================================================
# PART 1 — Service unit tests (mocked DB)
# ===========================================================================


class TestCreateIncident:
    @pytest.mark.anyio
    async def test_creates_report_with_correct_fields(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await create_incident(
            db,
            driver_id=42,
            incident_type=IncidentType.passenger_harassment,
            severity=IncidentSeverity.high,
            description="Passenger threatened me during pickup.",
            ride_id=99,
            evidence_urls=[],
        )

        db.add.assert_called_once()
        db.commit.assert_called_once()
        added = db.add.call_args[0][0]
        assert isinstance(added, DriverIncidentReport)
        assert added.driver_id == 42
        assert added.ride_id == 99
        assert added.incident_type == IncidentType.passenger_harassment.value
        assert added.severity == IncidentSeverity.high.value
        assert added.status == IncidentStatus.submitted.value

    @pytest.mark.anyio
    async def test_encodes_evidence_urls(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await create_incident(
            db,
            driver_id=1,
            incident_type=IncidentType.property_damage,
            severity=IncidentSeverity.medium,
            description="Passenger scratched the door panel.",
            ride_id=None,
            evidence_urls=["https://cdn.example.com/img1.jpg", "https://cdn.example.com/img2.jpg"],
        )

        added = db.add.call_args[0][0]
        assert "https://cdn.example.com/img1.jpg" in added.evidence_urls
        assert "https://cdn.example.com/img2.jpg" in added.evidence_urls
        assert "," in added.evidence_urls

    @pytest.mark.anyio
    async def test_handles_empty_evidence_urls(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await create_incident(
            db,
            driver_id=1,
            incident_type=IncidentType.theft,
            severity=IncidentSeverity.high,
            description="Passenger walked off with my phone charger.",
            ride_id=None,
            evidence_urls=[],
        )

        added = db.add.call_args[0][0]
        assert added.evidence_urls is None


class TestGetDriverIncident:
    @pytest.mark.anyio
    async def test_returns_report_when_found(self):
        report = _make_report()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(report))

        result = await get_driver_incident(db, incident_id=1, driver_id=42)
        assert result.id == 1
        assert result.driver_id == 42

    @pytest.mark.anyio
    async def test_raises_404_when_not_found(self):
        from fastapi import HTTPException

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(HTTPException) as exc:
            await get_driver_incident(db, incident_id=999, driver_id=42)
        assert exc.value.status_code == 404


class TestListDriverIncidents:
    @pytest.mark.anyio
    async def test_returns_paginated_results(self):
        reports = [_make_report(report_id=i) for i in range(1, 4)]

        db = AsyncMock()
        # First execute is the count query, second is the data query
        db.execute = AsyncMock(
            side_effect=[_scalar_result(3), _scalar_result_list(reports)]
        )

        results, total = await list_driver_incidents(db, driver_id=42, limit=10, offset=0)
        assert total == 3
        assert len(results) == 3


class TestUpdateDriverIncident:
    @pytest.mark.anyio
    async def test_updates_description_while_submitted(self):
        report = _make_report(status=IncidentStatus.submitted.value)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(report))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await update_driver_incident(
            db,
            incident_id=1,
            driver_id=42,
            description="Updated: passenger was also intoxicated.",
            evidence_urls=None,
        )

        assert result.description == "Updated: passenger was also intoxicated."
        db.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_raises_409_when_not_submitted(self):
        from fastapi import HTTPException

        report = _make_report(status=IncidentStatus.under_review.value)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(report))

        with pytest.raises(HTTPException) as exc:
            await update_driver_incident(
                db, incident_id=1, driver_id=42, description="New text.", evidence_urls=None
            )
        assert exc.value.status_code == 409

    @pytest.mark.anyio
    async def test_raises_404_when_not_found(self):
        from fastapi import HTTPException

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(HTTPException) as exc:
            await update_driver_incident(
                db, incident_id=999, driver_id=42, description="New text.", evidence_urls=None
            )
        assert exc.value.status_code == 404


class TestAdminStartReview:
    @pytest.mark.anyio
    async def test_moves_submitted_to_under_review(self):
        report = _make_report(status=IncidentStatus.submitted.value)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(report))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await admin_start_review(db, incident_id=1, admin_id=7, admin_note="Reviewing now.")
        assert result.status == IncidentStatus.under_review.value
        assert result.reviewed_by_id == 7
        assert result.admin_note == "Reviewing now."

    @pytest.mark.anyio
    async def test_raises_409_when_already_under_review(self):
        from fastapi import HTTPException

        report = _make_report(status=IncidentStatus.under_review.value)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(report))

        with pytest.raises(HTTPException) as exc:
            await admin_start_review(db, incident_id=1, admin_id=7, admin_note=None)
        assert exc.value.status_code == 409


class TestAdminResolveIncident:
    @pytest.mark.anyio
    async def test_resolves_submitted_report(self):
        report = _make_report(status=IncidentStatus.submitted.value)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(report))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await admin_resolve_incident(
            db, incident_id=1, admin_id=7, admin_note="Action taken against passenger."
        )
        assert result.status == IncidentStatus.resolved.value
        assert result.reviewed_by_id == 7

    @pytest.mark.anyio
    async def test_resolves_under_review_report(self):
        report = _make_report(status=IncidentStatus.under_review.value)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(report))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await admin_resolve_incident(db, incident_id=1, admin_id=7, admin_note=None)
        assert result.status == IncidentStatus.resolved.value

    @pytest.mark.anyio
    async def test_raises_409_when_already_resolved(self):
        from fastapi import HTTPException

        report = _make_report(status=IncidentStatus.resolved.value)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(report))

        with pytest.raises(HTTPException) as exc:
            await admin_resolve_incident(db, incident_id=1, admin_id=7, admin_note=None)
        assert exc.value.status_code == 409


class TestAdminDismissIncident:
    @pytest.mark.anyio
    async def test_dismisses_submitted_report(self):
        report = _make_report(status=IncidentStatus.submitted.value)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(report))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await admin_dismiss_incident(
            db, incident_id=1, admin_id=7, admin_note="Duplicate of report #5."
        )
        assert result.status == IncidentStatus.dismissed.value

    @pytest.mark.anyio
    async def test_raises_409_when_already_dismissed(self):
        from fastapi import HTTPException

        report = _make_report(status=IncidentStatus.dismissed.value)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(report))

        with pytest.raises(HTTPException) as exc:
            await admin_dismiss_incident(db, incident_id=1, admin_id=7, admin_note=None)
        assert exc.value.status_code == 409


class TestAdminIncidentSummary:
    @pytest.mark.anyio
    async def test_returns_correct_counts(self):
        reports = [
            _make_report(
                report_id=1,
                status=IncidentStatus.submitted.value,
                severity=IncidentSeverity.critical.value,
            ),
            _make_report(
                report_id=2,
                status=IncidentStatus.under_review.value,
                severity=IncidentSeverity.high.value,
            ),
            _make_report(
                report_id=3,
                status=IncidentStatus.resolved.value,
                severity=IncidentSeverity.medium.value,
            ),
        ]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result_list(reports))

        data = await admin_incident_summary(db)
        assert data["total"] == 3
        assert data["open_count"] == 2  # submitted + under_review
        assert data["critical_open"] == 1  # 1 critical + submitted
        assert data["by_status"][IncidentStatus.submitted.value] == 1
        assert data["by_status"][IncidentStatus.under_review.value] == 1
        assert data["by_status"][IncidentStatus.resolved.value] == 1


class TestAdminGetIncident:
    @pytest.mark.anyio
    async def test_returns_any_incident_by_id(self):
        report = _make_report(driver_id=99)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(report))

        result = await admin_get_incident(db, incident_id=1)
        assert result.driver_id == 99

    @pytest.mark.anyio
    async def test_raises_404_when_not_found(self):
        from fastapi import HTTPException

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(HTTPException) as exc:
            await admin_get_incident(db, incident_id=999)
        assert exc.value.status_code == 404


class TestAdminListIncidents:
    @pytest.mark.anyio
    async def test_returns_all_when_no_filter(self):
        reports = [_make_report(report_id=i) for i in range(1, 6)]
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_scalar_result(5), _scalar_result_list(reports)]
        )

        results, total = await admin_list_incidents(db, limit=50, offset=0)
        assert total == 5
        assert len(results) == 5


# ===========================================================================
# PART 2 — Schema validation tests
# ===========================================================================


class TestDriverIncidentCreate:
    def test_validates_description_min_length(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DriverIncidentCreate(
                incident_type=IncidentType.other,
                severity=IncidentSeverity.low,
                description="Short",  # < 10 chars
            )

    def test_validates_evidence_url_length(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DriverIncidentCreate(
                incident_type=IncidentType.other,
                severity=IncidentSeverity.low,
                description="A valid description that is long enough.",
                evidence_urls=["x" * 501],  # > 500 chars
            )

    def test_accepts_valid_payload(self):
        obj = DriverIncidentCreate(
            incident_type=IncidentType.passenger_harassment,
            description="Passenger was verbally abusive throughout the ride.",
        )
        assert obj.severity == IncidentSeverity.medium  # default


class TestDriverIncidentResponseFromOrm:
    def test_splits_comma_separated_urls(self):
        report = _make_report(
            evidence_urls="https://cdn.example.com/a.jpg,https://cdn.example.com/b.jpg"
        )
        resp = DriverIncidentResponse.from_orm_model(report)
        assert resp.evidence_urls == [
            "https://cdn.example.com/a.jpg",
            "https://cdn.example.com/b.jpg",
        ]

    def test_handles_empty_evidence_urls(self):
        report = _make_report(evidence_urls=None)
        resp = DriverIncidentResponse.from_orm_model(report)
        assert resp.evidence_urls == []

    def test_handles_single_url(self):
        report = _make_report(evidence_urls="https://cdn.example.com/only.jpg")
        resp = DriverIncidentResponse.from_orm_model(report)
        assert resp.evidence_urls == ["https://cdn.example.com/only.jpg"]


# ===========================================================================
# PART 3 — API integration tests (skipped without live DB)
# ===========================================================================

try:
    from tests.conftest import client, db, admin_token, driver_token  # type: ignore  # noqa: F401

    HAS_TEST_DB = True
except Exception:
    HAS_TEST_DB = False


def _make_user(
    *,
    user_id: int = 1,
    role: UserRole = UserRole.DRIVER,
    email: str = "driver@example.com",
) -> User:
    u = User()
    u.id = user_id
    u.email = email
    u.hashed_password = hash_password("password123")
    u.role = role
    u.is_active = True
    u.full_name = "Test Driver"
    return u


def _make_admin(*, user_id: int = 99) -> User:
    return _make_user(user_id=user_id, role=UserRole.ADMIN, email="admin@example.com")


def _driver_token(user_id: int = 1) -> str:
    return create_access_token({"sub": str(user_id), "role": "driver"})


def _admin_token(user_id: int = 99) -> str:
    return create_access_token({"sub": str(user_id), "role": "admin"})


@pytest.fixture
def driver():
    return _make_user()


@pytest.fixture
def admin_user():
    return _make_admin()


VALID_PAYLOAD = {
    "incident_type": "passenger_harassment",
    "severity": "medium",
    "description": "Passenger was verbally abusive during pickup and throughout the ride.",
    "evidence_urls": [],
}


# --- Driver: report incident ---


@pytest.mark.skipif(not HAS_TEST_DB, reason="Live DB not available")
class TestPostDriverIncident:
    def test_201_creates_report(self, client, driver):
        from app.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: driver
        try:
            resp = client.post("/api/v1/drivers/me/incidents", json=VALID_PAYLOAD)
            assert resp.status_code == 201
            data = resp.json()
            assert data["incident_type"] == "passenger_harassment"
            assert data["status"] == "submitted"
        finally:
            app.dependency_overrides.clear()

    def test_401_unauthenticated(self, client):
        resp = client.post("/api/v1/drivers/me/incidents", json=VALID_PAYLOAD)
        assert resp.status_code == 401

    def test_422_description_too_short(self, client, driver):
        from app.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: driver
        payload = {**VALID_PAYLOAD, "description": "Short"}
        try:
            resp = client.post("/api/v1/drivers/me/incidents", json=payload)
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()


# --- Driver: list incidents ---


@pytest.mark.skipif(not HAS_TEST_DB, reason="Live DB not available")
class TestGetDriverIncidents:
    def test_200_returns_list(self, client, driver):
        from app.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: driver
        try:
            resp = client.get("/api/v1/drivers/me/incidents")
            assert resp.status_code == 200
            assert "incidents" in resp.json()
            assert "total" in resp.json()
        finally:
            app.dependency_overrides.clear()

    def test_401_unauthenticated(self, client):
        resp = client.get("/api/v1/drivers/me/incidents")
        assert resp.status_code == 401


# --- Driver: get specific incident ---


@pytest.mark.skipif(not HAS_TEST_DB, reason="Live DB not available")
class TestGetSingleDriverIncident:
    def test_404_wrong_driver(self, client, driver):
        from app.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: driver
        try:
            resp = client.get("/api/v1/drivers/me/incidents/9999999")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()


# --- Driver: update incident ---


@pytest.mark.skipif(not HAS_TEST_DB, reason="Live DB not available")
class TestPutDriverIncident:
    def test_404_non_existent(self, client, driver):
        from app.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: driver
        try:
            resp = client.put(
                "/api/v1/drivers/me/incidents/9999999",
                json={"description": "Updated description for this incident."},
            )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()


# --- Admin: list incidents ---


@pytest.mark.skipif(not HAS_TEST_DB, reason="Live DB not available")
class TestAdminListIncidentsApi:
    def test_200_returns_all(self, client, admin_user):
        from app.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            resp = client.get("/api/v1/admin/driver-incidents")
            assert resp.status_code == 200
            assert "incidents" in resp.json()
        finally:
            app.dependency_overrides.clear()

    def test_403_non_admin(self, client, driver):
        from app.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: driver
        try:
            resp = client.get("/api/v1/admin/driver-incidents")
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_200_filtered_by_status(self, client, admin_user):
        from app.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            resp = client.get("/api/v1/admin/driver-incidents?status=submitted")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()


# --- Admin: get single incident ---


@pytest.mark.skipif(not HAS_TEST_DB, reason="Live DB not available")
class TestAdminGetSingleIncident:
    def test_404_not_found(self, client, admin_user):
        from app.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            resp = client.get("/api/v1/admin/driver-incidents/9999999")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()


# --- Admin: summary ---


@pytest.mark.skipif(not HAS_TEST_DB, reason="Live DB not available")
class TestAdminIncidentSummaryApi:
    def test_200_returns_stats(self, client, admin_user):
        from app.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            resp = client.get("/api/v1/admin/driver-incidents/summary")
            assert resp.status_code == 200
            data = resp.json()
            assert "total" in data
            assert "open_count" in data
            assert "critical_open" in data
        finally:
            app.dependency_overrides.clear()

    def test_403_non_admin(self, client, driver):
        from app.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: driver
        try:
            resp = client.get("/api/v1/admin/driver-incidents/summary")
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()


# --- Admin: review/resolve/dismiss ---


@pytest.mark.skipif(not HAS_TEST_DB, reason="Live DB not available")
class TestAdminIncidentActions:
    def test_404_review_nonexistent(self, client, admin_user):
        from app.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            resp = client.put(
                "/api/v1/admin/driver-incidents/9999999/review",
                json={"admin_note": "Reviewing."},
            )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_403_review_non_admin(self, client, driver):
        from app.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: driver
        try:
            resp = client.put(
                "/api/v1/admin/driver-incidents/1/review",
                json={"admin_note": "Reviewing."},
            )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_403_resolve_non_admin(self, client, driver):
        from app.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: driver
        try:
            resp = client.put(
                "/api/v1/admin/driver-incidents/1/resolve",
                json={"admin_note": "Resolved."},
            )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_403_dismiss_non_admin(self, client, driver):
        from app.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: driver
        try:
            resp = client.put(
                "/api/v1/admin/driver-incidents/1/dismiss",
                json={"admin_note": "Duplicate."},
            )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()
