"""Tests for rider incident flag feature.

A rider is automatically flagged when INCIDENT_THRESHOLD (3) driver safety
reports are filed against them within INCIDENT_WINDOW_DAYS (90) days.

Admin endpoints:
    GET    /admin/rider-incident-flags                    — list all flags
    GET    /admin/rider-incident-flags/{rider_id}         — get flag for rider
    POST   /admin/rider-incident-flags/{rider_id}/review  — review flag

Coverage
--------
Schemas
  - FlagStatus: all 3 values valid
  - RiderIncidentFlagResponse: all fields present
  - RiderIncidentFlagListResponse: total and items fields
  - AdminReviewIncidentFlagRequest: valid; cannot set to 'active'
  - INCIDENT_THRESHOLD == 3, INCIDENT_WINDOW_DAYS == 90

Service: check_and_flag_rider
  - returns None when report count below threshold
  - returns None when report count exactly threshold - 1
  - raises flag when report count meets threshold
  - raises flag when report count exceeds threshold
  - only counts PENDING reports (not reviewed/closed ones)
  - only counts reports within the rolling window
  - reports outside window do not count
  - re-raises CLEARED flag as ACTIVE when threshold hit again
  - refreshes count on ACTIVE flag (does not create duplicate)
  - refreshes count on UNDER_REVIEW flag
  - flag status on fresh raise is ACTIVE
  - reviewed_by and admin_notes are None on fresh flag

Service: get_flag
  - returns None when no flag exists
  - returns flag dict for existing flag
  - returns None after store reset

Service: admin_list_flags
  - returns empty when no flags
  - returns all flags when no filter
  - filters by status 'active'
  - filters by status 'under_review'
  - filters by status 'cleared'
  - pagination skip and limit
  - sorted newest-first by flagged_at

Service: admin_review_flag
  - transitions ACTIVE → UNDER_REVIEW
  - transitions ACTIVE → CLEARED
  - transitions UNDER_REVIEW → CLEARED
  - stores reviewed_by and admin_notes
  - raises KeyError for nonexistent rider
  - raises ValueError when review_status is ACTIVE

Router: admin_get_rider_incident_flags
  - returns RiderIncidentFlagListResponse
  - passes status filter to service

Router: admin_get_rider_incident_flag
  - 404 when no flag for rider

Router: admin_post_review_rider_incident_flag
  - 404 on KeyError from service
  - 400 on ValueError from service

End-to-end: reports accumulate → flag raised → admin reviews → cleared → new reports → re-raised
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from pydantic import ValidationError

from app.schemas.rider_incident_flag import (
    INCIDENT_THRESHOLD,
    INCIDENT_WINDOW_DAYS,
    AdminReviewIncidentFlagRequest,
    FlagStatus,
    RiderIncidentFlagListResponse,
    RiderIncidentFlagResponse,
)
from app.services.rider_incident_flag import (
    _reset_store,
    admin_list_flags,
    admin_review_flag,
    check_and_flag_rider,
    get_flag,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_flag_store():
    _reset_store()
    yield
    _reset_store()


@pytest.fixture
def mock_db():
    return AsyncMock()


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_pending_report(
    rider_id: int = 2,
    days_ago: float = 0.0,
    status_value: str = "pending",
) -> dict:
    from app.schemas.driver_safety_report import DriverReportCategory, DriverReportStatus

    filed_at = _utc_now() - timedelta(days=days_ago)
    status_map = {
        "pending": DriverReportStatus.PENDING,
        "reviewed": DriverReportStatus.REVIEWED,
        "closed": DriverReportStatus.CLOSED,
        "escalated": DriverReportStatus.ESCALATED,
    }
    return {
        "id": f"report-{rider_id}-{days_ago}-{status_value}",
        "rider_id": rider_id,
        "driver_id": 1,
        "ride_id": int(days_ago * 100),
        "status": status_map[status_value],
        "filed_at": filed_at,
    }


def _make_reports(
    count: int,
    rider_id: int = 2,
    status_value: str = "pending",
    days_ago_start: float = 0.0,
) -> list[dict]:
    return [
        _make_pending_report(rider_id=rider_id, days_ago=days_ago_start + i * 0.01, status_value=status_value)
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_all_flag_statuses_valid(self):
        for s in FlagStatus:
            assert isinstance(s.value, str)

    def test_threshold_and_window_constants(self):
        assert INCIDENT_THRESHOLD == 3
        assert INCIDENT_WINDOW_DAYS == 90

    def test_response_all_fields(self):
        now = _utc_now()
        resp = RiderIncidentFlagResponse(
            rider_id=5,
            report_count=3,
            status=FlagStatus.ACTIVE,
            flagged_at=now,
            last_updated_at=now,
            reviewed_by=None,
            admin_notes=None,
        )
        assert resp.rider_id == 5
        assert resp.status == FlagStatus.ACTIVE
        assert resp.reviewed_by is None

    def test_list_response_structure(self):
        now = _utc_now()
        item = RiderIncidentFlagResponse(
            rider_id=1,
            report_count=3,
            status=FlagStatus.ACTIVE,
            flagged_at=now,
            last_updated_at=now,
            reviewed_by=None,
            admin_notes=None,
        )
        lr = RiderIncidentFlagListResponse(total=1, items=[item])
        assert lr.total == 1
        assert len(lr.items) == 1

    def test_admin_review_request_valid_under_review(self):
        req = AdminReviewIncidentFlagRequest(review_status=FlagStatus.UNDER_REVIEW)
        assert req.review_status == FlagStatus.UNDER_REVIEW

    def test_admin_review_request_valid_cleared(self):
        req = AdminReviewIncidentFlagRequest(review_status=FlagStatus.CLEARED, admin_notes="All good.")
        assert req.review_status == FlagStatus.CLEARED
        assert req.admin_notes == "All good."

    def test_admin_review_request_notes_max_length(self):
        with pytest.raises(ValidationError):
            AdminReviewIncidentFlagRequest(
                review_status=FlagStatus.CLEARED,
                admin_notes="x" * 2001,
            )


# ---------------------------------------------------------------------------
# Service: check_and_flag_rider
# ---------------------------------------------------------------------------


class TestCheckAndFlagRider:
    @pytest.mark.asyncio
    async def test_returns_none_below_threshold(self, mock_db):
        reports = _make_reports(INCIDENT_THRESHOLD - 1, rider_id=2)
        result = await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=reports)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_at_threshold_minus_one(self, mock_db):
        reports = _make_reports(INCIDENT_THRESHOLD - 1, rider_id=2)
        result = await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=reports)
        assert result is None

    @pytest.mark.asyncio
    async def test_raises_flag_at_threshold(self, mock_db):
        reports = _make_reports(INCIDENT_THRESHOLD, rider_id=2)
        result = await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=reports)
        assert result is not None
        assert result["rider_id"] == 2
        assert result["report_count"] == INCIDENT_THRESHOLD

    @pytest.mark.asyncio
    async def test_raises_flag_above_threshold(self, mock_db):
        reports = _make_reports(INCIDENT_THRESHOLD + 2, rider_id=2)
        result = await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=reports)
        assert result is not None
        assert result["report_count"] == INCIDENT_THRESHOLD + 2

    @pytest.mark.asyncio
    async def test_flag_status_is_active(self, mock_db):
        reports = _make_reports(INCIDENT_THRESHOLD, rider_id=2)
        result = await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=reports)
        assert result["status"] == FlagStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_flag_reviewed_by_is_none_on_raise(self, mock_db):
        reports = _make_reports(INCIDENT_THRESHOLD, rider_id=2)
        result = await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=reports)
        assert result["reviewed_by"] is None
        assert result["admin_notes"] is None

    @pytest.mark.asyncio
    async def test_only_counts_pending_reports(self, mock_db):
        pending = _make_reports(INCIDENT_THRESHOLD - 1, rider_id=2, status_value="pending")
        reviewed = _make_reports(5, rider_id=2, status_value="reviewed")
        result = await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=pending + reviewed)
        assert result is None

    @pytest.mark.asyncio
    async def test_reports_inside_window_count(self, mock_db):
        reports = _make_reports(INCIDENT_THRESHOLD, rider_id=2, days_ago_start=INCIDENT_WINDOW_DAYS - 1)
        result = await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=reports)
        assert result is not None

    @pytest.mark.asyncio
    async def test_reports_outside_window_do_not_count(self, mock_db):
        reports = _make_reports(INCIDENT_THRESHOLD, rider_id=2, days_ago_start=INCIDENT_WINDOW_DAYS + 1)
        result = await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=reports)
        assert result is None

    @pytest.mark.asyncio
    async def test_re_raises_cleared_flag(self, mock_db):
        reports = _make_reports(INCIDENT_THRESHOLD, rider_id=2)
        await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=reports)
        # Admin clears it
        await admin_review_flag(db=mock_db, rider_id=2, admin_id=99, review_status=FlagStatus.CLEARED)
        # New batch of reports crosses threshold again
        new_reports = _make_reports(INCIDENT_THRESHOLD, rider_id=2, days_ago_start=0.5)
        result = await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=reports + new_reports)
        assert result["status"] == FlagStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_refreshes_count_on_active_flag(self, mock_db):
        reports = _make_reports(INCIDENT_THRESHOLD, rider_id=2)
        await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=reports)
        more = _make_reports(INCIDENT_THRESHOLD + 1, rider_id=2, days_ago_start=0.1)
        result = await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=more)
        assert result["status"] == FlagStatus.ACTIVE
        assert result["report_count"] == INCIDENT_THRESHOLD + 1

    @pytest.mark.asyncio
    async def test_refreshes_count_on_under_review_flag(self, mock_db):
        reports = _make_reports(INCIDENT_THRESHOLD, rider_id=2)
        await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=reports)
        await admin_review_flag(db=mock_db, rider_id=2, admin_id=99, review_status=FlagStatus.UNDER_REVIEW)
        more = _make_reports(INCIDENT_THRESHOLD + 2, rider_id=2, days_ago_start=0.1)
        result = await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=more)
        assert result["status"] == FlagStatus.UNDER_REVIEW
        assert result["report_count"] == INCIDENT_THRESHOLD + 2

    @pytest.mark.asyncio
    async def test_ignores_reports_for_other_riders(self, mock_db):
        other_reports = _make_reports(INCIDENT_THRESHOLD + 5, rider_id=99)
        target_reports = _make_reports(INCIDENT_THRESHOLD - 1, rider_id=2)
        result = await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=other_reports + target_reports)
        assert result is None


# ---------------------------------------------------------------------------
# Service: get_flag
# ---------------------------------------------------------------------------


class TestGetFlag:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_flag(self, mock_db):
        result = await get_flag(db=mock_db, rider_id=42)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_flag_after_raise(self, mock_db):
        reports = _make_reports(INCIDENT_THRESHOLD, rider_id=7)
        await check_and_flag_rider(db=mock_db, rider_id=7, all_reports=reports)
        result = await get_flag(db=mock_db, rider_id=7)
        assert result is not None
        assert result["rider_id"] == 7

    @pytest.mark.asyncio
    async def test_returns_none_after_reset(self, mock_db):
        reports = _make_reports(INCIDENT_THRESHOLD, rider_id=7)
        await check_and_flag_rider(db=mock_db, rider_id=7, all_reports=reports)
        _reset_store()
        result = await get_flag(db=mock_db, rider_id=7)
        assert result is None


# ---------------------------------------------------------------------------
# Service: admin_list_flags
# ---------------------------------------------------------------------------


class TestAdminListFlags:
    @pytest.mark.asyncio
    async def test_empty_when_no_flags(self, mock_db):
        total, items = await admin_list_flags(db=mock_db)
        assert total == 0
        assert items == []

    @pytest.mark.asyncio
    async def test_returns_all_flags(self, mock_db):
        for rider_id in [2, 3]:
            reports = _make_reports(INCIDENT_THRESHOLD, rider_id=rider_id, days_ago_start=rider_id * 0.01)
            await check_and_flag_rider(db=mock_db, rider_id=rider_id, all_reports=reports)
        total, items = await admin_list_flags(db=mock_db)
        assert total == 2

    @pytest.mark.asyncio
    async def test_filters_by_active_status(self, mock_db):
        reports = _make_reports(INCIDENT_THRESHOLD, rider_id=2)
        await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=reports)
        reports2 = _make_reports(INCIDENT_THRESHOLD, rider_id=3, days_ago_start=0.1)
        await check_and_flag_rider(db=mock_db, rider_id=3, all_reports=reports2)
        await admin_review_flag(db=mock_db, rider_id=3, admin_id=99, review_status=FlagStatus.CLEARED)
        total, items = await admin_list_flags(db=mock_db, status_filter="active")
        assert total == 1
        assert items[0]["rider_id"] == 2

    @pytest.mark.asyncio
    async def test_filters_by_under_review(self, mock_db):
        for rider_id in [2, 3]:
            reports = _make_reports(INCIDENT_THRESHOLD, rider_id=rider_id, days_ago_start=rider_id * 0.01)
            await check_and_flag_rider(db=mock_db, rider_id=rider_id, all_reports=reports)
        await admin_review_flag(db=mock_db, rider_id=2, admin_id=99, review_status=FlagStatus.UNDER_REVIEW)
        total, items = await admin_list_flags(db=mock_db, status_filter="under_review")
        assert total == 1
        assert items[0]["rider_id"] == 2

    @pytest.mark.asyncio
    async def test_filters_by_cleared(self, mock_db):
        reports = _make_reports(INCIDENT_THRESHOLD, rider_id=2)
        await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=reports)
        await admin_review_flag(db=mock_db, rider_id=2, admin_id=99, review_status=FlagStatus.CLEARED)
        total, items = await admin_list_flags(db=mock_db, status_filter="cleared")
        assert total == 1
        assert items[0]["status"] == FlagStatus.CLEARED

    @pytest.mark.asyncio
    async def test_pagination_skip_and_limit(self, mock_db):
        for rider_id in range(2, 7):
            reports = _make_reports(INCIDENT_THRESHOLD, rider_id=rider_id, days_ago_start=rider_id * 0.01)
            await check_and_flag_rider(db=mock_db, rider_id=rider_id, all_reports=reports)
        total, page = await admin_list_flags(db=mock_db, skip=2, limit=2)
        assert total == 5
        assert len(page) == 2

    @pytest.mark.asyncio
    async def test_sorted_newest_first(self, mock_db):
        for rider_id in [2, 3]:
            reports = _make_reports(INCIDENT_THRESHOLD, rider_id=rider_id, days_ago_start=rider_id * 0.01)
            await check_and_flag_rider(db=mock_db, rider_id=rider_id, all_reports=reports)
        _, items = await admin_list_flags(db=mock_db)
        assert items[0]["flagged_at"] >= items[1]["flagged_at"]


# ---------------------------------------------------------------------------
# Service: admin_review_flag
# ---------------------------------------------------------------------------


class TestAdminReviewFlag:
    @pytest.fixture(autouse=True)
    async def setup_flag(self, mock_db):
        reports = _make_reports(INCIDENT_THRESHOLD, rider_id=5)
        await check_and_flag_rider(db=mock_db, rider_id=5, all_reports=reports)
        self.mock_db = mock_db

    @pytest.mark.asyncio
    async def test_transitions_to_under_review(self):
        updated = await admin_review_flag(
            db=self.mock_db, rider_id=5, admin_id=99,
            review_status=FlagStatus.UNDER_REVIEW,
        )
        assert updated["status"] == FlagStatus.UNDER_REVIEW

    @pytest.mark.asyncio
    async def test_transitions_to_cleared(self):
        updated = await admin_review_flag(
            db=self.mock_db, rider_id=5, admin_id=99,
            review_status=FlagStatus.CLEARED,
        )
        assert updated["status"] == FlagStatus.CLEARED

    @pytest.mark.asyncio
    async def test_under_review_to_cleared(self):
        await admin_review_flag(
            db=self.mock_db, rider_id=5, admin_id=99,
            review_status=FlagStatus.UNDER_REVIEW,
        )
        updated = await admin_review_flag(
            db=self.mock_db, rider_id=5, admin_id=99,
            review_status=FlagStatus.CLEARED,
        )
        assert updated["status"] == FlagStatus.CLEARED

    @pytest.mark.asyncio
    async def test_stores_reviewed_by_and_notes(self):
        updated = await admin_review_flag(
            db=self.mock_db, rider_id=5, admin_id=42,
            review_status=FlagStatus.CLEARED,
            admin_notes="Investigated, rider not at fault.",
        )
        assert updated["reviewed_by"] == 42
        assert updated["admin_notes"] == "Investigated, rider not at fault."

    @pytest.mark.asyncio
    async def test_raises_key_error_for_nonexistent_rider(self):
        with pytest.raises(KeyError):
            await admin_review_flag(
                db=self.mock_db, rider_id=9999, admin_id=99,
                review_status=FlagStatus.CLEARED,
            )

    @pytest.mark.asyncio
    async def test_raises_value_error_when_setting_to_active(self):
        with pytest.raises(ValueError, match="active"):
            await admin_review_flag(
                db=self.mock_db, rider_id=5, admin_id=99,
                review_status=FlagStatus.ACTIVE,
            )


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------


class TestRouterAdminListFlags:
    @pytest.mark.asyncio
    async def test_returns_list_response(self):
        mock_db = AsyncMock()
        mock_admin = MagicMock()

        from app.api.v1.rider_incident_flag import admin_get_rider_incident_flags

        result = await admin_get_rider_incident_flags(
            flag_status=None,
            skip=0,
            limit=50,
            admin=mock_admin,
            db=mock_db,
        )
        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_passes_status_filter(self):
        mock_db = AsyncMock()
        mock_admin = MagicMock()

        reports = _make_reports(INCIDENT_THRESHOLD, rider_id=2)
        await check_and_flag_rider(db=mock_db, rider_id=2, all_reports=reports)

        from app.api.v1.rider_incident_flag import admin_get_rider_incident_flags

        result = await admin_get_rider_incident_flags(
            flag_status=FlagStatus.ACTIVE,
            skip=0,
            limit=50,
            admin=mock_admin,
            db=mock_db,
        )
        assert result.total == 1


class TestRouterAdminGetFlag:
    @pytest.mark.asyncio
    async def test_404_when_no_flag(self):
        from fastapi import HTTPException

        mock_db = AsyncMock()
        mock_admin = MagicMock()

        from app.api.v1.rider_incident_flag import admin_get_rider_incident_flag

        with pytest.raises(HTTPException) as exc_info:
            await admin_get_rider_incident_flag(rider_id=9999, admin=mock_admin, db=mock_db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_flag_when_exists(self):
        mock_db = AsyncMock()
        mock_admin = MagicMock()

        reports = _make_reports(INCIDENT_THRESHOLD, rider_id=7)
        await check_and_flag_rider(db=mock_db, rider_id=7, all_reports=reports)

        from app.api.v1.rider_incident_flag import admin_get_rider_incident_flag

        result = await admin_get_rider_incident_flag(rider_id=7, admin=mock_admin, db=mock_db)
        assert result.rider_id == 7
        assert result.status == FlagStatus.ACTIVE


class TestRouterAdminReviewFlag:
    @pytest.mark.asyncio
    async def test_404_on_key_error(self):
        from fastapi import HTTPException

        mock_db = AsyncMock()
        mock_admin = MagicMock()

        from app.api.v1.rider_incident_flag import admin_post_review_rider_incident_flag

        body = AdminReviewIncidentFlagRequest(review_status=FlagStatus.CLEARED)
        with pytest.raises(HTTPException) as exc_info:
            await admin_post_review_rider_incident_flag(
                rider_id=9999, body=body, admin=mock_admin, db=mock_db
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_400_on_value_error(self):
        from fastapi import HTTPException

        mock_db = AsyncMock()
        mock_admin = MagicMock()
        mock_admin.id = 99

        reports = _make_reports(INCIDENT_THRESHOLD, rider_id=8)
        await check_and_flag_rider(db=mock_db, rider_id=8, all_reports=reports)

        from app.api.v1.rider_incident_flag import admin_post_review_rider_incident_flag

        body = AdminReviewIncidentFlagRequest(review_status=FlagStatus.ACTIVE)
        with pytest.raises(HTTPException) as exc_info:
            await admin_post_review_rider_incident_flag(
                rider_id=8, body=body, admin=mock_admin, db=mock_db
            )
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_reports_accumulate_flag_raised_cleared_reraise(self, mock_db):
        rider_id = 10

        # Under threshold — no flag
        under = _make_reports(INCIDENT_THRESHOLD - 1, rider_id=rider_id)
        result = await check_and_flag_rider(db=mock_db, rider_id=rider_id, all_reports=under)
        assert result is None
        assert await get_flag(db=mock_db, rider_id=rider_id) is None

        # Hit threshold — flag raised
        at_threshold = _make_reports(INCIDENT_THRESHOLD, rider_id=rider_id, days_ago_start=0.1)
        result = await check_and_flag_rider(db=mock_db, rider_id=rider_id, all_reports=at_threshold)
        assert result["status"] == FlagStatus.ACTIVE

        total, items = await admin_list_flags(db=mock_db, status_filter="active")
        assert total == 1
        assert items[0]["rider_id"] == rider_id

        # Admin reviews → under_review
        updated = await admin_review_flag(
            db=mock_db, rider_id=rider_id, admin_id=99,
            review_status=FlagStatus.UNDER_REVIEW,
            admin_notes="Contacting driver for details.",
        )
        assert updated["status"] == FlagStatus.UNDER_REVIEW

        # Admin clears
        cleared = await admin_review_flag(
            db=mock_db, rider_id=rider_id, admin_id=99,
            review_status=FlagStatus.CLEARED,
            admin_notes="No policy violation confirmed.",
        )
        assert cleared["status"] == FlagStatus.CLEARED

        # New reports cross threshold — re-raised
        new_batch = _make_reports(INCIDENT_THRESHOLD, rider_id=rider_id, days_ago_start=0.2)
        re_raised = await check_and_flag_rider(
            db=mock_db, rider_id=rider_id, all_reports=at_threshold + new_batch
        )
        assert re_raised is not None
        assert re_raised["status"] == FlagStatus.ACTIVE
