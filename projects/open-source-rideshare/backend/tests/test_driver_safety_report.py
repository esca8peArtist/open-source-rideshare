"""Tests for post-ride driver safety report feature.

POST   /drivers/me/safety-reports
GET    /drivers/me/safety-reports
GET    /drivers/me/safety-reports/{report_id}
GET    /admin/driver-safety-reports
GET    /admin/driver-safety-reports/stats
POST   /admin/driver-safety-reports/{report_id}/review

Coverage
--------
Schemas
  - DriverReportCategory: all 7 values valid
  - DriverReportStatus: all 4 values valid
  - DriverSafetyReportCreate: valid with and without location; description too short
  - DriverSafetyReportResponse: all fields present
  - AdminReviewDriverReportRequest: valid; invalid status ('pending') rejected at service
  - DriverSafetyReportListResponse: total and items fields

Service: create_report
  - creates report with PENDING status
  - stores ride_id, driver_id, rider_id, category, description correctly
  - stores optional lat/lng
  - assigns unique UUID ids
  - filed_at is populated
  - reviewed_at, reviewed_by, admin_notes are None on creation
  - raises ValueError on duplicate (same driver + ride)
  - second report on different ride by same driver succeeds
  - two different drivers can each file a report for the same ride

Service: get_report
  - returns report for correct owner
  - returns None for wrong owner (404 guard)
  - returns None for nonexistent id

Service: list_driver_reports
  - returns empty for driver with no reports
  - returns all reports for driver, newest-first
  - pagination skip and limit
  - does not return reports belonging to other drivers

Service: admin_list_reports
  - returns all reports when no filter
  - filters by status
  - filters by category
  - filters by both status and category
  - pagination skip and limit
  - sorted newest-first

Service: admin_review_report
  - sets REVIEWED status with reviewed_at and reviewed_by
  - sets ESCALATED status
  - sets CLOSED status
  - stores admin_notes
  - raises KeyError for nonexistent report
  - raises ValueError when review_status is PENDING
  - raises ValueError when report is already reviewed (not PENDING)

Service: get_driver_safety_report_stats
  - empty store returns zeros and None avg
  - counts by_status correctly
  - counts by_category correctly
  - escalation_rate computation
  - avg_resolution_hours computed from resolved reports
  - rolling window counts

Router: post_create_driver_safety_report
  - 404 when ride not found / not completed / wrong driver
  - 409 when duplicate report

Router: get_list_driver_safety_reports
  - returns DriverSafetyReportListResponse

Router: get_driver_safety_report
  - 404 when service returns None

Router: admin_get_driver_safety_reports
  - returns DriverSafetyReportListResponse

Router: admin_get_driver_safety_report_stats
  - returns DriverSafetyReportStats

Router: admin_post_review_driver_safety_report
  - 404 on KeyError
  - 400 on ValueError

End-to-end: file report -> admin lists -> admin reviews
  - report moves from PENDING to ESCALATED with notes
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from app.schemas.driver_safety_report import (
    AdminReviewDriverReportRequest,
    DriverReportCategory,
    DriverReportStatus,
    DriverSafetyReportCreate,
    DriverSafetyReportListResponse,
    DriverSafetyReportResponse,
    DriverSafetyReportStats,
)
from app.services.driver_safety_report import (
    _reset_store,
    admin_list_reports,
    admin_review_report,
    create_report,
    get_driver_safety_report_stats,
    get_report,
    list_driver_reports,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_report_store():
    _reset_store()
    yield
    _reset_store()


@pytest.fixture
def mock_db():
    return AsyncMock()


async def _make_report(
    mock_db,
    driver_id: int = 1,
    ride_id: int = 100,
    rider_id: int = 2,
    category: DriverReportCategory = DriverReportCategory.THREATENING_BEHAVIOR,
    description: str = "Rider threatened me with physical harm during the ride.",
    location_lat: Optional[float] = None,
    location_lng: Optional[float] = None,
) -> dict:
    return await create_report(
        db=mock_db,
        driver_id=driver_id,
        ride_id=ride_id,
        rider_id=rider_id,
        category=category,
        description=description,
        location_lat=location_lat,
        location_lng=location_lng,
    )


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_all_categories_valid(self):
        for cat in DriverReportCategory:
            sc = DriverSafetyReportCreate(
                ride_id=1,
                category=cat,
                description="Enough characters for validation.",
            )
            assert sc.category == cat

    def test_all_statuses_valid(self):
        for s in DriverReportStatus:
            assert isinstance(s.value, str)

    def test_create_valid_without_location(self):
        sc = DriverSafetyReportCreate(
            ride_id=5,
            category=DriverReportCategory.PROPERTY_DAMAGE,
            description="Rider scratched the door panel.",
        )
        assert sc.ride_id == 5
        assert sc.location_lat is None
        assert sc.location_lng is None

    def test_create_valid_with_location(self):
        sc = DriverSafetyReportCreate(
            ride_id=5,
            category=DriverReportCategory.PHYSICAL_ASSAULT,
            description="Rider struck me at the destination.",
            location_lat=40.7128,
            location_lng=-74.0060,
        )
        assert sc.location_lat == pytest.approx(40.7128)

    def test_create_description_too_short(self):
        with pytest.raises(ValidationError):
            DriverSafetyReportCreate(
                ride_id=1,
                category=DriverReportCategory.HARASSMENT,
                description="short",
            )

    def test_response_all_fields(self):
        now = datetime.now(tz=timezone.utc)
        resp = DriverSafetyReportResponse(
            id="abc-123",
            ride_id=10,
            driver_id=1,
            rider_id=2,
            category=DriverReportCategory.FRAUD,
            description="Rider attempted to dispute valid charge.",
            status=DriverReportStatus.PENDING,
            location_lat=None,
            location_lng=None,
            filed_at=now,
            reviewed_at=None,
            reviewed_by=None,
            admin_notes=None,
        )
        assert resp.id == "abc-123"
        assert resp.driver_id == 1
        assert resp.rider_id == 2

    def test_list_response_structure(self):
        now = datetime.now(tz=timezone.utc)
        item = DriverSafetyReportResponse(
            id="x",
            ride_id=1,
            driver_id=1,
            rider_id=2,
            category=DriverReportCategory.OTHER,
            description="Incident description goes here.",
            status=DriverReportStatus.PENDING,
            location_lat=None,
            location_lng=None,
            filed_at=now,
            reviewed_at=None,
            reviewed_by=None,
            admin_notes=None,
        )
        lr = DriverSafetyReportListResponse(total=1, items=[item])
        assert lr.total == 1
        assert len(lr.items) == 1

    def test_admin_review_request_valid(self):
        req = AdminReviewDriverReportRequest(
            review_status=DriverReportStatus.REVIEWED,
            admin_notes="Confirmed via ride recording.",
        )
        assert req.review_status == DriverReportStatus.REVIEWED

    def test_stats_schema_fields(self):
        stats = DriverSafetyReportStats(
            total_reports=0,
            by_status={s.value: 0 for s in DriverReportStatus},
            by_category={c.value: 0 for c in DriverReportCategory},
            escalation_rate=0.0,
            reports_last_7_days=0,
            reports_last_30_days=0,
            avg_resolution_hours=None,
        )
        assert stats.total_reports == 0
        assert stats.avg_resolution_hours is None


# ---------------------------------------------------------------------------
# Service: create_report
# ---------------------------------------------------------------------------


class TestServiceCreateReport:
    @pytest.mark.asyncio
    async def test_creates_with_pending_status(self, mock_db):
        report = await _make_report(mock_db)
        assert report["status"] == DriverReportStatus.PENDING

    @pytest.mark.asyncio
    async def test_stores_ids_correctly(self, mock_db):
        report = await _make_report(mock_db, driver_id=10, ride_id=200, rider_id=20)
        assert report["driver_id"] == 10
        assert report["ride_id"] == 200
        assert report["rider_id"] == 20

    @pytest.mark.asyncio
    async def test_stores_category_and_description(self, mock_db):
        report = await _make_report(
            mock_db,
            category=DriverReportCategory.PROPERTY_DAMAGE,
            description="Rider spilled drinks on the seat.",
        )
        assert report["category"] == DriverReportCategory.PROPERTY_DAMAGE
        assert report["description"] == "Rider spilled drinks on the seat."

    @pytest.mark.asyncio
    async def test_stores_optional_location(self, mock_db):
        report = await _make_report(mock_db, location_lat=34.0522, location_lng=-118.2437)
        assert report["location_lat"] == pytest.approx(34.0522)
        assert report["location_lng"] == pytest.approx(-118.2437)

    @pytest.mark.asyncio
    async def test_location_none_by_default(self, mock_db):
        report = await _make_report(mock_db)
        assert report["location_lat"] is None
        assert report["location_lng"] is None

    @pytest.mark.asyncio
    async def test_assigns_unique_ids(self, mock_db):
        r1 = await _make_report(mock_db, ride_id=101)
        r2 = await _make_report(mock_db, ride_id=102)
        assert r1["id"] != r2["id"]

    @pytest.mark.asyncio
    async def test_filed_at_populated(self, mock_db):
        report = await _make_report(mock_db)
        assert isinstance(report["filed_at"], datetime)

    @pytest.mark.asyncio
    async def test_audit_fields_none_on_creation(self, mock_db):
        report = await _make_report(mock_db)
        assert report["reviewed_at"] is None
        assert report["reviewed_by"] is None
        assert report["admin_notes"] is None

    @pytest.mark.asyncio
    async def test_raises_on_duplicate_same_driver_same_ride(self, mock_db):
        await _make_report(mock_db, driver_id=1, ride_id=100)
        with pytest.raises(ValueError, match="already been filed"):
            await _make_report(mock_db, driver_id=1, ride_id=100)

    @pytest.mark.asyncio
    async def test_second_report_different_ride_succeeds(self, mock_db):
        r1 = await _make_report(mock_db, driver_id=1, ride_id=100)
        r2 = await _make_report(mock_db, driver_id=1, ride_id=101)
        assert r1["id"] != r2["id"]

    @pytest.mark.asyncio
    async def test_two_drivers_can_report_same_ride(self, mock_db):
        r1 = await _make_report(mock_db, driver_id=1, ride_id=100)
        r2 = await _make_report(mock_db, driver_id=2, ride_id=100)
        assert r1["id"] != r2["id"]


# ---------------------------------------------------------------------------
# Service: get_report
# ---------------------------------------------------------------------------


class TestServiceGetReport:
    @pytest.mark.asyncio
    async def test_returns_report_for_correct_owner(self, mock_db):
        report = await _make_report(mock_db, driver_id=1)
        result = await get_report(db=mock_db, driver_id=1, report_id=report["id"])
        assert result is not None
        assert result["id"] == report["id"]

    @pytest.mark.asyncio
    async def test_returns_none_for_wrong_owner(self, mock_db):
        report = await _make_report(mock_db, driver_id=1)
        result = await get_report(db=mock_db, driver_id=99, report_id=report["id"])
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_id(self, mock_db):
        result = await get_report(db=mock_db, driver_id=1, report_id="does-not-exist")
        assert result is None


# ---------------------------------------------------------------------------
# Service: list_driver_reports
# ---------------------------------------------------------------------------


class TestServiceListDriverReports:
    @pytest.mark.asyncio
    async def test_empty_for_no_reports(self, mock_db):
        total, items = await list_driver_reports(db=mock_db, driver_id=1)
        assert total == 0
        assert items == []

    @pytest.mark.asyncio
    async def test_returns_all_reports_newest_first(self, mock_db):
        await _make_report(mock_db, driver_id=1, ride_id=100)
        await _make_report(mock_db, driver_id=1, ride_id=101)
        total, items = await list_driver_reports(db=mock_db, driver_id=1)
        assert total == 2
        assert items[0]["ride_id"] == 101

    @pytest.mark.asyncio
    async def test_pagination_skip_and_limit(self, mock_db):
        for ride_id in range(110, 115):
            await _make_report(mock_db, driver_id=1, ride_id=ride_id)
        total, page = await list_driver_reports(db=mock_db, driver_id=1, skip=2, limit=2)
        assert total == 5
        assert len(page) == 2

    @pytest.mark.asyncio
    async def test_does_not_return_other_drivers_reports(self, mock_db):
        await _make_report(mock_db, driver_id=1, ride_id=100)
        await _make_report(mock_db, driver_id=2, ride_id=200)
        total, items = await list_driver_reports(db=mock_db, driver_id=1)
        assert total == 1
        assert all(r["driver_id"] == 1 for r in items)


# ---------------------------------------------------------------------------
# Service: admin_list_reports
# ---------------------------------------------------------------------------


class TestServiceAdminListReports:
    @pytest.mark.asyncio
    async def test_returns_all_when_no_filter(self, mock_db):
        await _make_report(mock_db, driver_id=1, ride_id=100)
        await _make_report(mock_db, driver_id=2, ride_id=200)
        total, items = await admin_list_reports(db=mock_db)
        assert total == 2

    @pytest.mark.asyncio
    async def test_filters_by_status(self, mock_db):
        r = await _make_report(mock_db, driver_id=1, ride_id=100)
        await _make_report(mock_db, driver_id=2, ride_id=200)
        await admin_review_report(
            db=mock_db, report_id=r["id"], admin_id=99,
            review_status=DriverReportStatus.REVIEWED,
        )
        total, items = await admin_list_reports(db=mock_db, status_filter="reviewed")
        assert total == 1
        assert items[0]["status"] == DriverReportStatus.REVIEWED

    @pytest.mark.asyncio
    async def test_filters_by_category(self, mock_db):
        await _make_report(mock_db, driver_id=1, ride_id=100, category=DriverReportCategory.FRAUD)
        await _make_report(mock_db, driver_id=2, ride_id=200, category=DriverReportCategory.HARASSMENT)
        total, items = await admin_list_reports(db=mock_db, category_filter="fraud")
        assert total == 1
        assert items[0]["category"] == DriverReportCategory.FRAUD

    @pytest.mark.asyncio
    async def test_filters_by_both_status_and_category(self, mock_db):
        r = await _make_report(mock_db, driver_id=1, ride_id=100, category=DriverReportCategory.FRAUD)
        await _make_report(mock_db, driver_id=2, ride_id=200, category=DriverReportCategory.FRAUD)
        await admin_review_report(
            db=mock_db, report_id=r["id"], admin_id=99,
            review_status=DriverReportStatus.CLOSED,
        )
        total, items = await admin_list_reports(
            db=mock_db, status_filter="closed", category_filter="fraud"
        )
        assert total == 1

    @pytest.mark.asyncio
    async def test_pagination(self, mock_db):
        for i in range(5):
            await _make_report(mock_db, driver_id=i + 1, ride_id=100 + i)
        total, page = await admin_list_reports(db=mock_db, skip=2, limit=2)
        assert total == 5
        assert len(page) == 2

    @pytest.mark.asyncio
    async def test_sorted_newest_first(self, mock_db):
        await _make_report(mock_db, driver_id=1, ride_id=100)
        await _make_report(mock_db, driver_id=2, ride_id=200)
        _, items = await admin_list_reports(db=mock_db)
        assert items[0]["filed_at"] >= items[1]["filed_at"]


# ---------------------------------------------------------------------------
# Service: admin_review_report
# ---------------------------------------------------------------------------


class TestServiceAdminReviewReport:
    @pytest.mark.asyncio
    async def test_sets_reviewed_status(self, mock_db):
        r = await _make_report(mock_db)
        updated = await admin_review_report(
            db=mock_db, report_id=r["id"], admin_id=99,
            review_status=DriverReportStatus.REVIEWED,
        )
        assert updated["status"] == DriverReportStatus.REVIEWED
        assert updated["reviewed_at"] is not None
        assert updated["reviewed_by"] == 99

    @pytest.mark.asyncio
    async def test_sets_escalated_status(self, mock_db):
        r = await _make_report(mock_db)
        updated = await admin_review_report(
            db=mock_db, report_id=r["id"], admin_id=99,
            review_status=DriverReportStatus.ESCALATED,
        )
        assert updated["status"] == DriverReportStatus.ESCALATED

    @pytest.mark.asyncio
    async def test_sets_closed_status(self, mock_db):
        r = await _make_report(mock_db)
        updated = await admin_review_report(
            db=mock_db, report_id=r["id"], admin_id=99,
            review_status=DriverReportStatus.CLOSED,
        )
        assert updated["status"] == DriverReportStatus.CLOSED

    @pytest.mark.asyncio
    async def test_stores_admin_notes(self, mock_db):
        r = await _make_report(mock_db)
        updated = await admin_review_report(
            db=mock_db, report_id=r["id"], admin_id=99,
            review_status=DriverReportStatus.REVIEWED,
            admin_notes="Verified via dash cam footage.",
        )
        assert updated["admin_notes"] == "Verified via dash cam footage."

    @pytest.mark.asyncio
    async def test_raises_key_error_for_nonexistent(self, mock_db):
        with pytest.raises(KeyError):
            await admin_review_report(
                db=mock_db, report_id="does-not-exist", admin_id=99,
                review_status=DriverReportStatus.REVIEWED,
            )

    @pytest.mark.asyncio
    async def test_raises_value_error_on_pending_status(self, mock_db):
        r = await _make_report(mock_db)
        with pytest.raises(ValueError, match="pending"):
            await admin_review_report(
                db=mock_db, report_id=r["id"], admin_id=99,
                review_status=DriverReportStatus.PENDING,
            )

    @pytest.mark.asyncio
    async def test_raises_value_error_when_already_reviewed(self, mock_db):
        r = await _make_report(mock_db)
        await admin_review_report(
            db=mock_db, report_id=r["id"], admin_id=99,
            review_status=DriverReportStatus.REVIEWED,
        )
        with pytest.raises(ValueError, match="already"):
            await admin_review_report(
                db=mock_db, report_id=r["id"], admin_id=99,
                review_status=DriverReportStatus.CLOSED,
            )


# ---------------------------------------------------------------------------
# Service: get_driver_safety_report_stats
# ---------------------------------------------------------------------------


class TestServiceStats:
    @pytest.mark.asyncio
    async def test_empty_store(self, mock_db):
        stats = await get_driver_safety_report_stats(db=mock_db)
        assert stats["total_reports"] == 0
        assert stats["escalation_rate"] == 0.0
        assert stats["avg_resolution_hours"] is None
        assert stats["reports_last_7_days"] == 0

    @pytest.mark.asyncio
    async def test_counts_by_status(self, mock_db):
        r1 = await _make_report(mock_db, driver_id=1, ride_id=100)
        await _make_report(mock_db, driver_id=2, ride_id=200)
        await admin_review_report(
            db=mock_db, report_id=r1["id"], admin_id=99,
            review_status=DriverReportStatus.REVIEWED,
        )
        stats = await get_driver_safety_report_stats(db=mock_db)
        assert stats["by_status"]["reviewed"] == 1
        assert stats["by_status"]["pending"] == 1

    @pytest.mark.asyncio
    async def test_counts_by_category(self, mock_db):
        await _make_report(mock_db, driver_id=1, ride_id=100, category=DriverReportCategory.FRAUD)
        await _make_report(mock_db, driver_id=2, ride_id=200, category=DriverReportCategory.FRAUD)
        stats = await get_driver_safety_report_stats(db=mock_db)
        assert stats["by_category"]["fraud"] == 2
        assert stats["by_category"]["harassment"] == 0

    @pytest.mark.asyncio
    async def test_escalation_rate(self, mock_db):
        r1 = await _make_report(mock_db, driver_id=1, ride_id=100)
        await _make_report(mock_db, driver_id=2, ride_id=200)
        await admin_review_report(
            db=mock_db, report_id=r1["id"], admin_id=99,
            review_status=DriverReportStatus.ESCALATED,
        )
        stats = await get_driver_safety_report_stats(db=mock_db)
        assert stats["escalation_rate"] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_avg_resolution_hours(self, mock_db):
        r = await _make_report(mock_db)
        await admin_review_report(
            db=mock_db, report_id=r["id"], admin_id=99,
            review_status=DriverReportStatus.REVIEWED,
        )
        stats = await get_driver_safety_report_stats(db=mock_db)
        assert stats["avg_resolution_hours"] is not None
        assert stats["avg_resolution_hours"] >= 0.0

    @pytest.mark.asyncio
    async def test_rolling_window_counts(self, mock_db):
        await _make_report(mock_db, driver_id=1, ride_id=100)
        stats = await get_driver_safety_report_stats(db=mock_db)
        assert stats["reports_last_7_days"] == 1
        assert stats["reports_last_30_days"] == 1


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------


class TestRouterPostCreateReport:
    @pytest.mark.asyncio
    async def test_404_when_ride_not_found(self):
        from fastapi import HTTPException
        from unittest.mock import AsyncMock, MagicMock

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        mock_driver = MagicMock()
        mock_driver.id = 1

        from app.api.v1.driver_safety_report import post_create_driver_safety_report
        from app.schemas.driver_safety_report import DriverSafetyReportCreate, DriverReportCategory

        body = DriverSafetyReportCreate(
            ride_id=999,
            category=DriverReportCategory.THREATENING_BEHAVIOR,
            description="Rider made explicit threats during the ride.",
        )

        with pytest.raises(HTTPException) as exc_info:
            await post_create_driver_safety_report(body=body, driver=mock_driver, db=mock_db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_409_when_duplicate_report(self):
        from fastapi import HTTPException
        from unittest.mock import AsyncMock, MagicMock

        mock_db = AsyncMock()
        mock_ride = MagicMock()
        mock_ride.id = 100
        mock_ride.rider_id = 2
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_ride
        mock_db.execute.return_value = mock_result

        mock_driver = MagicMock()
        mock_driver.id = 1

        from app.api.v1.driver_safety_report import post_create_driver_safety_report
        from app.schemas.driver_safety_report import DriverSafetyReportCreate, DriverReportCategory

        body = DriverSafetyReportCreate(
            ride_id=100,
            category=DriverReportCategory.PROPERTY_DAMAGE,
            description="Rider damaged the back seat upholstery.",
        )

        # First call succeeds
        await post_create_driver_safety_report(body=body, driver=mock_driver, db=mock_db)

        # Second call on same ride raises 409
        with pytest.raises(HTTPException) as exc_info:
            await post_create_driver_safety_report(body=body, driver=mock_driver, db=mock_db)
        assert exc_info.value.status_code == 409


class TestRouterGetListReports:
    @pytest.mark.asyncio
    async def test_returns_list_response(self):
        from unittest.mock import AsyncMock, MagicMock

        mock_db = AsyncMock()
        mock_driver = MagicMock()
        mock_driver.id = 1

        from app.api.v1.driver_safety_report import get_list_driver_safety_reports

        result = await get_list_driver_safety_reports(
            skip=0, limit=20, driver=mock_driver, db=mock_db
        )
        assert result.total == 0
        assert result.items == []


class TestRouterGetReport:
    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        from fastapi import HTTPException
        from unittest.mock import AsyncMock, MagicMock

        mock_db = AsyncMock()
        mock_driver = MagicMock()
        mock_driver.id = 1

        from app.api.v1.driver_safety_report import get_driver_safety_report

        with pytest.raises(HTTPException) as exc_info:
            await get_driver_safety_report(
                report_id="nonexistent", driver=mock_driver, db=mock_db
            )
        assert exc_info.value.status_code == 404


class TestRouterAdminListReports:
    @pytest.mark.asyncio
    async def test_returns_list_response(self):
        from unittest.mock import AsyncMock, MagicMock

        mock_db = AsyncMock()
        mock_admin = MagicMock()
        mock_admin.id = 99

        from app.api.v1.driver_safety_report import admin_get_driver_safety_reports

        result = await admin_get_driver_safety_reports(
            report_status=None,
            category=None,
            skip=0,
            limit=50,
            admin=mock_admin,
            db=mock_db,
        )
        assert result.total == 0


class TestRouterAdminStats:
    @pytest.mark.asyncio
    async def test_returns_stats(self):
        from unittest.mock import AsyncMock, MagicMock

        mock_db = AsyncMock()
        mock_admin = MagicMock()

        from app.api.v1.driver_safety_report import admin_get_driver_safety_report_stats

        result = await admin_get_driver_safety_report_stats(admin=mock_admin, db=mock_db)
        assert result.total_reports == 0
        assert result.escalation_rate == 0.0


class TestRouterAdminReview:
    @pytest.mark.asyncio
    async def test_404_on_key_error(self):
        from fastapi import HTTPException
        from unittest.mock import AsyncMock, MagicMock

        mock_db = AsyncMock()
        mock_admin = MagicMock()

        from app.api.v1.driver_safety_report import admin_post_review_driver_safety_report

        body = AdminReviewDriverReportRequest(review_status=DriverReportStatus.REVIEWED)

        with pytest.raises(HTTPException) as exc_info:
            await admin_post_review_driver_safety_report(
                report_id="nonexistent", body=body, admin=mock_admin, db=mock_db
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_400_on_value_error(self):
        from fastapi import HTTPException
        from unittest.mock import AsyncMock, MagicMock

        mock_db = AsyncMock()
        mock_driver = MagicMock()
        mock_driver.id = 1
        mock_admin = MagicMock()

        # Create a report first (via service directly)
        report = await create_report(
            db=mock_db,
            driver_id=1,
            ride_id=300,
            rider_id=2,
            category=DriverReportCategory.HARASSMENT,
            description="Persistent harassment throughout the ride.",
        )

        # Review it once
        await admin_review_report(
            db=mock_db, report_id=report["id"], admin_id=99,
            review_status=DriverReportStatus.REVIEWED,
        )

        from app.api.v1.driver_safety_report import admin_post_review_driver_safety_report

        body = AdminReviewDriverReportRequest(review_status=DriverReportStatus.CLOSED)

        with pytest.raises(HTTPException) as exc_info:
            await admin_post_review_driver_safety_report(
                report_id=report["id"], body=body, admin=mock_admin, db=mock_db
            )
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_file_then_admin_lists_then_escalates(self, mock_db):
        report = await create_report(
            db=mock_db,
            driver_id=1,
            ride_id=500,
            rider_id=3,
            category=DriverReportCategory.PHYSICAL_ASSAULT,
            description="Rider struck me when I refused to deviate from the route.",
        )
        assert report["status"] == DriverReportStatus.PENDING

        total, items = await admin_list_reports(db=mock_db)
        assert total == 1
        assert items[0]["id"] == report["id"]

        updated = await admin_review_report(
            db=mock_db,
            report_id=report["id"],
            admin_id=99,
            review_status=DriverReportStatus.ESCALATED,
            admin_notes="Referred to law enforcement per policy 7.3.",
        )
        assert updated["status"] == DriverReportStatus.ESCALATED
        assert updated["admin_notes"] == "Referred to law enforcement per policy 7.3."

        total, items = await admin_list_reports(db=mock_db, status_filter="pending")
        assert total == 0
