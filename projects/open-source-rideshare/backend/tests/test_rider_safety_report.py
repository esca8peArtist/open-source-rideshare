"""Tests for post-ride rider safety report feature.

POST   /riders/me/safety-reports
GET    /riders/me/safety-reports
GET    /riders/me/safety-reports/{report_id}
GET    /admin/safety-reports
POST   /admin/safety-reports/{report_id}/review

Coverage
--------
Schemas
  - SafetyReportCategory: all 6 values valid
  - SafetyReportStatus: all 4 values valid
  - SafetyReportCreate: valid with and without location; description too short
  - SafetyReportResponse: all fields present
  - AdminReviewReportRequest: valid; invalid status ('pending') rejected at service
  - SafetyReportListResponse: total and items fields

Service: create_report
  - creates report with PENDING status
  - stores ride_id, rider_id, driver_id, category, description correctly
  - stores optional lat/lng
  - assigns unique UUID ids
  - filed_at is populated
  - reviewed_at, reviewed_by, admin_notes are None on creation
  - raises ValueError on duplicate (same rider + ride)
  - second report on different ride by same rider succeeds
  - two different riders can each file a report for the same ride

Service: get_report
  - returns report for correct owner
  - returns None for wrong owner (404 guard)
  - returns None for nonexistent id

Service: list_rider_reports
  - returns empty for rider with no reports
  - returns all reports for rider, newest-first
  - pagination skip and limit
  - does not return reports belonging to other riders

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

Router: post_create_safety_report
  - 404 when ride not found / not completed / wrong rider
  - 409 when duplicate report

Router: get_list_rider_safety_reports
  - returns SafetyReportListResponse

Router: get_rider_safety_report
  - 404 when service returns None

Router: admin_get_safety_reports
  - returns SafetyReportListResponse

Router: admin_post_review_safety_report
  - 404 on KeyError
  - 400 on ValueError

End-to-end: file report -> admin lists -> admin reviews
  - report moves from PENDING to REVIEWED with notes
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from app.schemas.rider_safety_report import (
    AdminReviewReportRequest,
    SafetyReportCategory,
    SafetyReportCreate,
    SafetyReportListResponse,
    SafetyReportResponse,
    SafetyReportStatus,
)
from app.services.rider_safety_report import (
    _reset_store,
    admin_list_reports,
    admin_review_report,
    create_report,
    get_report,
    list_rider_reports,
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
    rider_id: int = 1,
    ride_id: int = 100,
    driver_id: int = 2,
    category: SafetyReportCategory = SafetyReportCategory.DANGEROUS_DRIVING,
    description: str = "Driver ran three red lights at high speed.",
    location_lat: Optional[float] = None,
    location_lng: Optional[float] = None,
) -> dict:
    return await create_report(
        db=mock_db,
        rider_id=rider_id,
        ride_id=ride_id,
        driver_id=driver_id,
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
        for cat in SafetyReportCategory:
            sc = SafetyReportCreate(
                ride_id=1,
                category=cat,
                description="Enough characters for validation.",
            )
            assert sc.category == cat

    def test_all_statuses_valid(self):
        for s in SafetyReportStatus:
            assert isinstance(s.value, str)

    def test_create_without_location(self):
        sc = SafetyReportCreate(
            ride_id=5,
            category=SafetyReportCategory.HARASSMENT,
            description="Driver made repeated inappropriate comments.",
        )
        assert sc.location_lat is None
        assert sc.location_lng is None

    def test_create_with_location(self):
        sc = SafetyReportCreate(
            ride_id=5,
            category=SafetyReportCategory.HARASSMENT,
            description="Driver made repeated inappropriate comments.",
            location_lat=37.7749,
            location_lng=-122.4194,
        )
        assert sc.location_lat == 37.7749
        assert sc.location_lng == -122.4194

    def test_description_too_short_raises(self):
        with pytest.raises(ValidationError):
            SafetyReportCreate(
                ride_id=1,
                category=SafetyReportCategory.OTHER,
                description="Short",
            )

    def test_response_model_config(self):
        assert SafetyReportResponse.model_config.get("from_attributes") is True

    def test_list_response_fields(self):
        resp = SafetyReportListResponse(total=0, items=[])
        assert resp.total == 0
        assert resp.items == []

    def test_admin_review_request_valid(self):
        req = AdminReviewReportRequest(review_status=SafetyReportStatus.REVIEWED)
        assert req.review_status == SafetyReportStatus.REVIEWED
        assert req.admin_notes is None

    def test_admin_review_request_with_notes(self):
        req = AdminReviewReportRequest(
            review_status=SafetyReportStatus.ESCALATED,
            admin_notes="Escalated to safety team for follow-up.",
        )
        assert req.admin_notes == "Escalated to safety team for follow-up."


# ---------------------------------------------------------------------------
# Service: create_report
# ---------------------------------------------------------------------------


class TestCreateReport:
    @pytest.mark.asyncio
    async def test_creates_with_pending_status(self, mock_db):
        report = await _make_report(mock_db)
        assert report["status"] == SafetyReportStatus.PENDING

    @pytest.mark.asyncio
    async def test_stores_fields_correctly(self, mock_db):
        report = await _make_report(
            mock_db,
            rider_id=7,
            ride_id=42,
            driver_id=3,
            category=SafetyReportCategory.VEHICLE_ISSUE,
            description="Brakes were grinding badly throughout the ride.",
        )
        assert report["rider_id"] == 7
        assert report["ride_id"] == 42
        assert report["driver_id"] == 3
        assert report["category"] == SafetyReportCategory.VEHICLE_ISSUE
        assert "grinding" in report["description"]

    @pytest.mark.asyncio
    async def test_stores_optional_location(self, mock_db):
        report = await _make_report(
            mock_db,
            location_lat=40.7128,
            location_lng=-74.0060,
        )
        assert report["location_lat"] == 40.7128
        assert report["location_lng"] == -74.0060

    @pytest.mark.asyncio
    async def test_location_defaults_to_none(self, mock_db):
        report = await _make_report(mock_db)
        assert report["location_lat"] is None
        assert report["location_lng"] is None

    @pytest.mark.asyncio
    async def test_assigns_uuid(self, mock_db):
        r1 = await _make_report(mock_db, ride_id=1)
        r2 = await _make_report(mock_db, ride_id=2)
        assert r1["id"] != r2["id"]
        assert len(r1["id"]) == 36  # UUID4 string

    @pytest.mark.asyncio
    async def test_filed_at_is_set(self, mock_db):
        report = await _make_report(mock_db)
        assert isinstance(report["filed_at"], datetime)

    @pytest.mark.asyncio
    async def test_reviewed_fields_are_none_on_creation(self, mock_db):
        report = await _make_report(mock_db)
        assert report["reviewed_at"] is None
        assert report["reviewed_by"] is None
        assert report["admin_notes"] is None

    @pytest.mark.asyncio
    async def test_duplicate_raises_value_error(self, mock_db):
        await _make_report(mock_db, rider_id=1, ride_id=100)
        with pytest.raises(ValueError, match="already been filed"):
            await _make_report(mock_db, rider_id=1, ride_id=100)

    @pytest.mark.asyncio
    async def test_different_ride_succeeds(self, mock_db):
        r1 = await _make_report(mock_db, rider_id=1, ride_id=100)
        r2 = await _make_report(mock_db, rider_id=1, ride_id=200)
        assert r1["ride_id"] == 100
        assert r2["ride_id"] == 200

    @pytest.mark.asyncio
    async def test_two_riders_same_ride(self, mock_db):
        r1 = await _make_report(mock_db, rider_id=1, ride_id=100)
        r2 = await _make_report(mock_db, rider_id=2, ride_id=100)
        assert r1["id"] != r2["id"]


# ---------------------------------------------------------------------------
# Service: get_report
# ---------------------------------------------------------------------------


class TestGetReport:
    @pytest.mark.asyncio
    async def test_returns_for_correct_owner(self, mock_db):
        report = await _make_report(mock_db, rider_id=5)
        result = await get_report(db=mock_db, rider_id=5, report_id=report["id"])
        assert result is not None
        assert result["id"] == report["id"]

    @pytest.mark.asyncio
    async def test_returns_none_for_wrong_owner(self, mock_db):
        report = await _make_report(mock_db, rider_id=5)
        result = await get_report(db=mock_db, rider_id=99, report_id=report["id"])
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_id(self, mock_db):
        result = await get_report(db=mock_db, rider_id=1, report_id="does-not-exist")
        assert result is None


# ---------------------------------------------------------------------------
# Service: list_rider_reports
# ---------------------------------------------------------------------------


class TestListRiderReports:
    @pytest.mark.asyncio
    async def test_empty_for_new_rider(self, mock_db):
        total, items = await list_rider_reports(db=mock_db, rider_id=99)
        assert total == 0
        assert items == []

    @pytest.mark.asyncio
    async def test_returns_newest_first(self, mock_db):
        import asyncio
        r1 = await _make_report(mock_db, rider_id=1, ride_id=1)
        await asyncio.sleep(0)
        r2 = await _make_report(mock_db, rider_id=1, ride_id=2)
        total, items = await list_rider_reports(db=mock_db, rider_id=1)
        assert total == 2
        assert items[0]["id"] == r2["id"]
        assert items[1]["id"] == r1["id"]

    @pytest.mark.asyncio
    async def test_pagination_skip_and_limit(self, mock_db):
        for i in range(5):
            await _make_report(mock_db, rider_id=1, ride_id=i + 1)
        _, page1 = await list_rider_reports(db=mock_db, rider_id=1, skip=0, limit=2)
        _, page2 = await list_rider_reports(db=mock_db, rider_id=1, skip=2, limit=2)
        ids_p1 = {r["id"] for r in page1}
        ids_p2 = {r["id"] for r in page2}
        assert len(page1) == 2
        assert len(page2) == 2
        assert ids_p1.isdisjoint(ids_p2)

    @pytest.mark.asyncio
    async def test_does_not_return_other_riders_reports(self, mock_db):
        await _make_report(mock_db, rider_id=1, ride_id=1)
        await _make_report(mock_db, rider_id=2, ride_id=2)
        total, items = await list_rider_reports(db=mock_db, rider_id=1)
        assert total == 1
        assert all(r["rider_id"] == 1 for r in items)


# ---------------------------------------------------------------------------
# Service: admin_list_reports
# ---------------------------------------------------------------------------


class TestAdminListReports:
    @pytest.mark.asyncio
    async def test_returns_all_when_no_filter(self, mock_db):
        await _make_report(mock_db, rider_id=1, ride_id=1)
        await _make_report(mock_db, rider_id=2, ride_id=2)
        total, items = await admin_list_reports(db=mock_db)
        assert total == 2

    @pytest.mark.asyncio
    async def test_filters_by_status(self, mock_db):
        r = await _make_report(mock_db, rider_id=1, ride_id=1)
        await _make_report(mock_db, rider_id=2, ride_id=2)
        # Review one report
        await admin_review_report(
            db=mock_db,
            report_id=r["id"],
            admin_id=99,
            review_status=SafetyReportStatus.REVIEWED,
        )
        total, items = await admin_list_reports(db=mock_db, status_filter="reviewed")
        assert total == 1
        assert items[0]["id"] == r["id"]

    @pytest.mark.asyncio
    async def test_filters_by_category(self, mock_db):
        await _make_report(
            mock_db, rider_id=1, ride_id=1,
            category=SafetyReportCategory.HARASSMENT,
        )
        await _make_report(
            mock_db, rider_id=2, ride_id=2,
            category=SafetyReportCategory.VEHICLE_ISSUE,
        )
        total, items = await admin_list_reports(db=mock_db, category_filter="harassment")
        assert total == 1
        assert items[0]["category"] == SafetyReportCategory.HARASSMENT

    @pytest.mark.asyncio
    async def test_filters_by_both_status_and_category(self, mock_db):
        r = await _make_report(
            mock_db, rider_id=1, ride_id=1,
            category=SafetyReportCategory.DANGEROUS_DRIVING,
        )
        await _make_report(
            mock_db, rider_id=2, ride_id=2,
            category=SafetyReportCategory.DANGEROUS_DRIVING,
        )
        await admin_review_report(
            db=mock_db,
            report_id=r["id"],
            admin_id=99,
            review_status=SafetyReportStatus.ESCALATED,
        )
        total, items = await admin_list_reports(
            db=mock_db,
            status_filter="escalated",
            category_filter="dangerous_driving",
        )
        assert total == 1
        assert items[0]["id"] == r["id"]

    @pytest.mark.asyncio
    async def test_pagination(self, mock_db):
        for i in range(6):
            await _make_report(mock_db, rider_id=i + 1, ride_id=i + 1)
        total, page1 = await admin_list_reports(db=mock_db, skip=0, limit=3)
        assert total == 6
        assert len(page1) == 3

    @pytest.mark.asyncio
    async def test_sorted_newest_first(self, mock_db):
        import asyncio
        r1 = await _make_report(mock_db, rider_id=1, ride_id=1)
        await asyncio.sleep(0)
        r2 = await _make_report(mock_db, rider_id=2, ride_id=2)
        _, items = await admin_list_reports(db=mock_db)
        assert items[0]["id"] == r2["id"]
        assert items[1]["id"] == r1["id"]


# ---------------------------------------------------------------------------
# Service: admin_review_report
# ---------------------------------------------------------------------------


class TestAdminReviewReport:
    @pytest.mark.asyncio
    async def test_sets_reviewed_status(self, mock_db):
        r = await _make_report(mock_db)
        updated = await admin_review_report(
            db=mock_db,
            report_id=r["id"],
            admin_id=50,
            review_status=SafetyReportStatus.REVIEWED,
        )
        assert updated["status"] == SafetyReportStatus.REVIEWED
        assert updated["reviewed_by"] == 50
        assert updated["reviewed_at"] is not None

    @pytest.mark.asyncio
    async def test_sets_escalated_status(self, mock_db):
        r = await _make_report(mock_db)
        updated = await admin_review_report(
            db=mock_db,
            report_id=r["id"],
            admin_id=50,
            review_status=SafetyReportStatus.ESCALATED,
        )
        assert updated["status"] == SafetyReportStatus.ESCALATED

    @pytest.mark.asyncio
    async def test_sets_closed_status(self, mock_db):
        r = await _make_report(mock_db)
        updated = await admin_review_report(
            db=mock_db,
            report_id=r["id"],
            admin_id=50,
            review_status=SafetyReportStatus.CLOSED,
        )
        assert updated["status"] == SafetyReportStatus.CLOSED

    @pytest.mark.asyncio
    async def test_stores_admin_notes(self, mock_db):
        r = await _make_report(mock_db)
        updated = await admin_review_report(
            db=mock_db,
            report_id=r["id"],
            admin_id=50,
            review_status=SafetyReportStatus.REVIEWED,
            admin_notes="Contacted driver, issued warning.",
        )
        assert updated["admin_notes"] == "Contacted driver, issued warning."

    @pytest.mark.asyncio
    async def test_raises_key_error_for_nonexistent(self, mock_db):
        with pytest.raises(KeyError, match="not found"):
            await admin_review_report(
                db=mock_db,
                report_id="ghost-id",
                admin_id=1,
                review_status=SafetyReportStatus.REVIEWED,
            )

    @pytest.mark.asyncio
    async def test_raises_value_error_for_pending_status(self, mock_db):
        r = await _make_report(mock_db)
        with pytest.raises(ValueError, match="Cannot set status back to 'pending'"):
            await admin_review_report(
                db=mock_db,
                report_id=r["id"],
                admin_id=1,
                review_status=SafetyReportStatus.PENDING,
            )

    @pytest.mark.asyncio
    async def test_raises_value_error_when_already_reviewed(self, mock_db):
        r = await _make_report(mock_db)
        await admin_review_report(
            db=mock_db,
            report_id=r["id"],
            admin_id=1,
            review_status=SafetyReportStatus.REVIEWED,
        )
        with pytest.raises(ValueError, match="Only PENDING reports"):
            await admin_review_report(
                db=mock_db,
                report_id=r["id"],
                admin_id=1,
                review_status=SafetyReportStatus.CLOSED,
            )


# ---------------------------------------------------------------------------
# Router tests — call handlers directly (same pattern as test_rider_safety.py)
# ---------------------------------------------------------------------------


class TestRouter:
    @pytest.mark.asyncio
    async def test_post_create_404_when_ride_not_found(self):
        """Handler raises 404 when DB finds no matching completed ride."""
        from fastapi import HTTPException
        from unittest.mock import AsyncMock as AM, MagicMock as MM
        from app.api.v1.rider_safety_report import post_create_safety_report

        mock_rider = MM()
        mock_rider.id = 1
        mock_result = MM()
        mock_result.scalar_one_or_none = MM(return_value=None)
        mock_db = AM()
        mock_db.execute = AM(return_value=mock_result)

        body = SafetyReportCreate(
            ride_id=999,
            category=SafetyReportCategory.DANGEROUS_DRIVING,
            description="Driver was on their phone the entire ride.",
        )
        with pytest.raises(HTTPException) as exc_info:
            await post_create_safety_report(body=body, rider=mock_rider, db=mock_db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_post_create_409_on_duplicate(self):
        """Handler raises 409 when service raises ValueError (duplicate)."""
        from fastapi import HTTPException
        from unittest.mock import AsyncMock as AM, MagicMock as MM
        from app.api.v1.rider_safety_report import post_create_safety_report

        mock_rider = MM()
        mock_rider.id = 1
        mock_ride = MM()
        mock_ride.id = 100
        mock_ride.driver_id = 2
        mock_result = MM()
        mock_result.scalar_one_or_none = MM(return_value=mock_ride)
        mock_db = AM()
        mock_db.execute = AM(return_value=mock_result)

        body = SafetyReportCreate(
            ride_id=100,
            category=SafetyReportCategory.DANGEROUS_DRIVING,
            description="Driver ran a stop sign at the end of the ride.",
        )
        # First call creates the report
        await post_create_safety_report(body=body, rider=mock_rider, db=mock_db)
        # Second call should 409
        with pytest.raises(HTTPException) as exc_info:
            await post_create_safety_report(body=body, rider=mock_rider, db=mock_db)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_get_list_returns_list_response(self):
        from unittest.mock import AsyncMock as AM, MagicMock as MM
        from app.api.v1.rider_safety_report import get_list_rider_safety_reports

        mock_rider = MM()
        mock_rider.id = 1
        mock_db = AM()

        result = await get_list_rider_safety_reports(skip=0, limit=20, rider=mock_rider, db=mock_db)
        assert isinstance(result, SafetyReportListResponse)
        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_get_report_404_when_not_found(self):
        from fastapi import HTTPException
        from unittest.mock import AsyncMock as AM, MagicMock as MM
        from app.api.v1.rider_safety_report import get_rider_safety_report

        mock_rider = MM()
        mock_rider.id = 1
        mock_db = AM()

        with pytest.raises(HTTPException) as exc_info:
            await get_rider_safety_report(
                report_id="nonexistent-id", rider=mock_rider, db=mock_db
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_get_safety_reports_returns_list(self):
        from unittest.mock import AsyncMock as AM, MagicMock as MM
        from app.api.v1.rider_safety_report import admin_get_safety_reports

        mock_admin = MM()
        mock_admin.id = 99
        mock_db = AM()

        result = await admin_get_safety_reports(
            report_status=None, category=None, skip=0, limit=50,
            admin=mock_admin, db=mock_db,
        )
        assert isinstance(result, SafetyReportListResponse)
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_admin_review_404_on_key_error(self):
        from fastapi import HTTPException
        from unittest.mock import AsyncMock as AM, MagicMock as MM
        from app.api.v1.rider_safety_report import admin_post_review_safety_report

        mock_admin = MM()
        mock_admin.id = 99
        mock_db = AM()
        body = AdminReviewReportRequest(review_status=SafetyReportStatus.REVIEWED)

        with pytest.raises(HTTPException) as exc_info:
            await admin_post_review_safety_report(
                report_id="nonexistent", body=body, admin=mock_admin, db=mock_db
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_review_400_on_value_error(self):
        """Handler raises 400 when a non-PENDING report is reviewed again."""
        from fastapi import HTTPException
        from unittest.mock import AsyncMock as AM, MagicMock as MM
        from app.api.v1.rider_safety_report import (
            post_create_safety_report,
            admin_post_review_safety_report,
        )

        mock_rider = MM()
        mock_rider.id = 1
        mock_ride = MM()
        mock_ride.id = 50
        mock_ride.driver_id = 2
        mock_result = MM()
        mock_result.scalar_one_or_none = MM(return_value=mock_ride)
        mock_db = AM()
        mock_db.execute = AM(return_value=mock_result)

        body = SafetyReportCreate(
            ride_id=50,
            category=SafetyReportCategory.WRONG_ROUTE,
            description="Driver took a significantly longer route deliberately.",
        )
        report_resp = await post_create_safety_report(body=body, rider=mock_rider, db=mock_db)
        report_id = report_resp.id

        mock_admin = MM()
        mock_admin.id = 99
        review_body = AdminReviewReportRequest(review_status=SafetyReportStatus.REVIEWED)
        # First review succeeds
        await admin_post_review_safety_report(
            report_id=report_id, body=review_body, admin=mock_admin, db=mock_db
        )
        # Second review raises 400
        with pytest.raises(HTTPException) as exc_info:
            await admin_post_review_safety_report(
                report_id=report_id,
                body=AdminReviewReportRequest(review_status=SafetyReportStatus.CLOSED),
                admin=mock_admin,
                db=mock_db,
            )
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_file_report_admin_lists_admin_reviews(self, mock_db):
        """Full lifecycle: file -> admin list -> admin review -> confirmed reviewed."""
        # Rider files a report
        report = await create_report(
            db=mock_db,
            rider_id=10,
            ride_id=500,
            driver_id=20,
            category=SafetyReportCategory.THREATENING_BEHAVIOR,
            description="Driver became verbally aggressive when asked to follow GPS route.",
        )
        assert report["status"] == SafetyReportStatus.PENDING

        # Admin sees it in the pending queue
        total, items = await admin_list_reports(db=mock_db, status_filter="pending")
        assert total == 1
        assert items[0]["id"] == report["id"]

        # Admin escalates with notes
        updated = await admin_review_report(
            db=mock_db,
            report_id=report["id"],
            admin_id=99,
            review_status=SafetyReportStatus.ESCALATED,
            admin_notes="Pattern of complaints against this driver. Forwarding to safety team.",
        )
        assert updated["status"] == SafetyReportStatus.ESCALATED
        assert updated["reviewed_by"] == 99
        assert "safety team" in updated["admin_notes"]

        # Pending queue now empty
        total_pending, _ = await admin_list_reports(db=mock_db, status_filter="pending")
        assert total_pending == 0

        # Rider can still retrieve their report and see the updated status
        rider_view = await get_report(db=mock_db, rider_id=10, report_id=report["id"])
        assert rider_view["status"] == SafetyReportStatus.ESCALATED
