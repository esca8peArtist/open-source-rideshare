"""Tests for background check expiry tracking.

Covers:
  - Pydantic schemas (ExpiringBackgroundCheckRow, ExpiringBackgroundChecksResponse,
    BackgroundCheckExpiryScanResponse)
  - Service: get_expiring_background_checks (mocked DB)
  - Service: run_expiry_scan (mocked DB)
  - API endpoints: GET /admin/background-checks/expiring
                   POST /admin/background-checks/expiry-scan

No live database is used.  All DB interactions are mocked with AsyncMock /
MagicMock following the same pattern as test_document_expiry_alerts.py.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.background_check import BackgroundCheckAlertType, BackgroundCheckStatus
from app.models.user import UserRole
from app.schemas.background_check_expiry import (
    BackgroundCheckExpiryScanResponse,
    ExpiringBackgroundCheckRow,
    ExpiringBackgroundChecksResponse,
)

TODAY = date(2026, 4, 17)
NOW = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------

def _make_check(
    check_id: int = 1,
    driver_profile_id: int = 10,
    expires_at: date | None = None,
    status: BackgroundCheckStatus = BackgroundCheckStatus.CLEAR,
) -> MagicMock:
    """Build a mock BackgroundCheck ORM object."""
    check = MagicMock()
    check.id = check_id
    check.driver_profile_id = driver_profile_id
    check.expires_at = expires_at
    check.status = status
    return check


def _make_alert(
    alert_id: int = 1,
    background_check_id: int = 1,
    alert_type: BackgroundCheckAlertType = BackgroundCheckAlertType.THIRTY_DAY,
) -> MagicMock:
    """Build a mock BackgroundCheckAlert ORM object."""
    alert = MagicMock()
    alert.id = alert_id
    alert.background_check_id = background_check_id
    alert.alert_type = alert_type
    return alert


def _make_user(user_id: int = 1, role: UserRole = UserRole.ADMIN) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    u.role = role
    return u


def _db_with_scalars(*lists_of_rows):
    """Build an AsyncSession mock for sequential select() calls.

    Each positional arg is a list of ORM objects returned by scalars() for
    that call in order.  Supports both .scalars().all() and iterating
    over .scalars() directly.
    """
    db = AsyncMock()
    results = []
    for row_list in lists_of_rows:
        result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = row_list
        # also support iteration directly
        scalars_mock.__iter__ = lambda self, rl=row_list: iter(rl)
        result.scalars.return_value = scalars_mock
        results.append(result)
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


# ===========================================================================
# Schema tests
# ===========================================================================


class TestExpiringBackgroundCheckRowSchema:
    """Pydantic validation for ExpiringBackgroundCheckRow."""

    def test_basic_construction(self):
        row = ExpiringBackgroundCheckRow(
            check_id=1,
            driver_profile_id=10,
            expires_at=TODAY + timedelta(days=30),
            days_until_expiry=30,
            status="clear",
        )
        assert row.check_id == 1
        assert row.driver_profile_id == 10
        assert row.days_until_expiry == 30
        assert row.status == "clear"

    def test_negative_days_until_expiry_allowed(self):
        row = ExpiringBackgroundCheckRow(
            check_id=2,
            driver_profile_id=5,
            expires_at=TODAY - timedelta(days=1),
            days_until_expiry=-1,
            status="clear",
        )
        assert row.days_until_expiry == -1

    def test_zero_days_until_expiry(self):
        row = ExpiringBackgroundCheckRow(
            check_id=3,
            driver_profile_id=7,
            expires_at=TODAY,
            days_until_expiry=0,
            status="clear",
        )
        assert row.days_until_expiry == 0

    def test_from_attributes_config(self):
        assert ExpiringBackgroundCheckRow.model_config.get("from_attributes") is True

    def test_expires_at_is_date_type(self):
        row = ExpiringBackgroundCheckRow(
            check_id=4,
            driver_profile_id=8,
            expires_at=TODAY + timedelta(days=7),
            days_until_expiry=7,
            status="clear",
        )
        assert isinstance(row.expires_at, date)

    def test_large_days_until_expiry(self):
        row = ExpiringBackgroundCheckRow(
            check_id=5,
            driver_profile_id=9,
            expires_at=TODAY + timedelta(days=365),
            days_until_expiry=365,
            status="clear",
        )
        assert row.days_until_expiry == 365


class TestExpiringBackgroundChecksResponseSchema:
    """Pydantic validation for ExpiringBackgroundChecksResponse."""

    def test_empty_response(self):
        resp = ExpiringBackgroundChecksResponse(items=[], total=0)
        assert resp.items == []
        assert resp.total == 0

    def test_response_with_items(self):
        row = ExpiringBackgroundCheckRow(
            check_id=1,
            driver_profile_id=10,
            expires_at=TODAY + timedelta(days=15),
            days_until_expiry=15,
            status="clear",
        )
        resp = ExpiringBackgroundChecksResponse(items=[row], total=1)
        assert resp.total == 1
        assert len(resp.items) == 1
        assert resp.items[0].check_id == 1

    def test_total_does_not_have_to_match_items_length(self):
        # total reflects the full count before pagination
        resp = ExpiringBackgroundChecksResponse(items=[], total=42)
        assert resp.total == 42

    def test_from_attributes_config(self):
        assert ExpiringBackgroundChecksResponse.model_config.get("from_attributes") is True


class TestBackgroundCheckExpiryScanResponseSchema:
    """Pydantic validation for BackgroundCheckExpiryScanResponse."""

    def test_basic_construction(self):
        resp = BackgroundCheckExpiryScanResponse(
            alerts_sent=3,
            by_type={"30_day": 2, "7_day": 1},
        )
        assert resp.alerts_sent == 3
        assert resp.by_type["30_day"] == 2

    def test_zero_alerts(self):
        resp = BackgroundCheckExpiryScanResponse(alerts_sent=0, by_type={})
        assert resp.alerts_sent == 0
        assert resp.by_type == {}

    def test_all_alert_types_in_by_type(self):
        resp = BackgroundCheckExpiryScanResponse(
            alerts_sent=10,
            by_type={"60_day": 4, "30_day": 3, "7_day": 2, "expired": 1},
        )
        assert sum(resp.by_type.values()) == resp.alerts_sent


# ===========================================================================
# Service: get_expiring_background_checks
# ===========================================================================


class TestGetExpiringBackgroundChecks:
    """Tests for get_expiring_background_checks with mocked DB."""

    @pytest.mark.asyncio
    async def test_no_checks_returns_empty_list(self):
        from app.services.background_check_expiry import get_expiring_background_checks

        db = _db_with_scalars([])
        with patch("app.services.background_check_expiry.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_expiring_background_checks(db, days_ahead=60)
        assert rows == []

    @pytest.mark.asyncio
    async def test_clear_check_within_window_returned(self):
        from app.services.background_check_expiry import get_expiring_background_checks

        check = _make_check(check_id=1, driver_profile_id=10, expires_at=TODAY + timedelta(days=30))
        db = _db_with_scalars([check])
        with patch("app.services.background_check_expiry.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_expiring_background_checks(db, days_ahead=60)
        assert len(rows) == 1
        assert rows[0].check_id == 1
        assert rows[0].driver_profile_id == 10
        assert rows[0].days_until_expiry == 30
        assert rows[0].status == "clear"

    @pytest.mark.asyncio
    async def test_recently_expired_check_included(self):
        from app.services.background_check_expiry import get_expiring_background_checks

        # Expired yesterday — within the lower bound of today - 1
        check = _make_check(check_id=2, driver_profile_id=11, expires_at=TODAY - timedelta(days=1))
        db = _db_with_scalars([check])
        with patch("app.services.background_check_expiry.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_expiring_background_checks(db, days_ahead=60)
        assert len(rows) == 1
        assert rows[0].days_until_expiry == -1

    @pytest.mark.asyncio
    async def test_days_until_expiry_computed_correctly(self):
        from app.services.background_check_expiry import get_expiring_background_checks

        check = _make_check(check_id=3, driver_profile_id=12, expires_at=TODAY + timedelta(days=7))
        db = _db_with_scalars([check])
        with patch("app.services.background_check_expiry.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_expiring_background_checks(db, days_ahead=60)
        assert rows[0].days_until_expiry == 7

    @pytest.mark.asyncio
    async def test_results_sorted_expired_first(self):
        from app.services.background_check_expiry import get_expiring_background_checks

        check_expiring = _make_check(check_id=1, driver_profile_id=10, expires_at=TODAY + timedelta(days=20))
        check_expired = _make_check(check_id=2, driver_profile_id=11, expires_at=TODAY - timedelta(days=1))
        # Return expiring before expired in DB result; service should re-sort
        db = _db_with_scalars([check_expiring, check_expired])
        with patch("app.services.background_check_expiry.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_expiring_background_checks(db, days_ahead=60)
        assert rows[0].days_until_expiry < 0  # expired one is first
        assert rows[1].days_until_expiry > 0

    @pytest.mark.asyncio
    async def test_multiple_checks_all_returned(self):
        from app.services.background_check_expiry import get_expiring_background_checks

        checks = [
            _make_check(check_id=i, driver_profile_id=i, expires_at=TODAY + timedelta(days=i))
            for i in range(1, 6)
        ]
        db = _db_with_scalars(checks)
        with patch("app.services.background_check_expiry.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_expiring_background_checks(db, days_ahead=60)
        assert len(rows) == 5

    @pytest.mark.asyncio
    async def test_status_value_is_string(self):
        from app.services.background_check_expiry import get_expiring_background_checks

        check = _make_check(check_id=1, driver_profile_id=10, expires_at=TODAY + timedelta(days=10))
        db = _db_with_scalars([check])
        with patch("app.services.background_check_expiry.date") as mock_date:
            mock_date.today.return_value = TODAY
            rows = await get_expiring_background_checks(db, days_ahead=60)
        assert rows[0].status == "clear"

    @pytest.mark.asyncio
    async def test_single_execute_call_made(self):
        from app.services.background_check_expiry import get_expiring_background_checks

        db = _db_with_scalars([])
        with patch("app.services.background_check_expiry.date") as mock_date:
            mock_date.today.return_value = TODAY
            await get_expiring_background_checks(db, days_ahead=60)
        assert db.execute.await_count == 1


# ===========================================================================
# Service: run_expiry_scan
# ===========================================================================


class TestRunExpiryScan:
    """Tests for run_expiry_scan with mocked DB."""

    @pytest.mark.asyncio
    async def test_no_checks_returns_zero_alerts(self):
        from app.services.background_check_expiry import run_expiry_scan

        db = _db_with_scalars([], [])
        with patch("app.services.background_check_expiry.date") as mock_date:
            mock_date.today.return_value = TODAY
            result = await run_expiry_scan(db)
        assert result["alerts_sent"] == 0
        assert result["by_type"] == {}

    @pytest.mark.asyncio
    async def test_check_at_30_days_generates_thirty_day_alert(self):
        from app.services.background_check_expiry import run_expiry_scan

        check = _make_check(check_id=1, driver_profile_id=10, expires_at=TODAY + timedelta(days=30))
        # First query returns checks, second returns existing alerts (none)
        db = _db_with_scalars([check], [])
        with patch("app.services.background_check_expiry.date") as mock_date, \
             patch("app.services.background_check_expiry.datetime") as mock_dt:
            mock_date.today.return_value = TODAY
            mock_dt.now.return_value = NOW
            result = await run_expiry_scan(db)
        assert result["alerts_sent"] == 1
        assert result["by_type"].get("30_day") == 1

    @pytest.mark.asyncio
    async def test_check_at_7_days_generates_seven_day_alert(self):
        from app.services.background_check_expiry import run_expiry_scan

        check = _make_check(check_id=1, driver_profile_id=10, expires_at=TODAY + timedelta(days=7))
        db = _db_with_scalars([check], [])
        with patch("app.services.background_check_expiry.date") as mock_date, \
             patch("app.services.background_check_expiry.datetime") as mock_dt:
            mock_date.today.return_value = TODAY
            mock_dt.now.return_value = NOW
            result = await run_expiry_scan(db)
        assert result["alerts_sent"] == 1
        assert result["by_type"].get("7_day") == 1

    @pytest.mark.asyncio
    async def test_expired_check_generates_expired_alert(self):
        from app.services.background_check_expiry import run_expiry_scan

        check = _make_check(check_id=1, driver_profile_id=10, expires_at=TODAY - timedelta(days=1))
        db = _db_with_scalars([check], [])
        with patch("app.services.background_check_expiry.date") as mock_date, \
             patch("app.services.background_check_expiry.datetime") as mock_dt:
            mock_date.today.return_value = TODAY
            mock_dt.now.return_value = NOW
            result = await run_expiry_scan(db)
        assert result["alerts_sent"] == 1
        assert result["by_type"].get("expired") == 1

    @pytest.mark.asyncio
    async def test_existing_alert_not_duplicated(self):
        from app.services.background_check_expiry import run_expiry_scan

        check = _make_check(check_id=1, driver_profile_id=10, expires_at=TODAY + timedelta(days=7))
        existing = _make_alert(
            alert_id=99,
            background_check_id=1,
            alert_type=BackgroundCheckAlertType.SEVEN_DAY,
        )
        db = _db_with_scalars([check], [existing])
        with patch("app.services.background_check_expiry.date") as mock_date, \
             patch("app.services.background_check_expiry.datetime") as mock_dt:
            mock_date.today.return_value = TODAY
            mock_dt.now.return_value = NOW
            result = await run_expiry_scan(db)
        assert result["alerts_sent"] == 0
        assert result["by_type"] == {}

    @pytest.mark.asyncio
    async def test_different_alert_type_not_blocked_by_existing(self):
        from app.services.background_check_expiry import run_expiry_scan

        # Check is at 7 days; a 30_day alert already exists but 7_day does not
        check = _make_check(check_id=1, driver_profile_id=10, expires_at=TODAY + timedelta(days=7))
        existing = _make_alert(
            alert_id=50,
            background_check_id=1,
            alert_type=BackgroundCheckAlertType.THIRTY_DAY,
        )
        db = _db_with_scalars([check], [existing])
        with patch("app.services.background_check_expiry.date") as mock_date, \
             patch("app.services.background_check_expiry.datetime") as mock_dt:
            mock_date.today.return_value = TODAY
            mock_dt.now.return_value = NOW
            result = await run_expiry_scan(db)
        assert result["alerts_sent"] == 1
        assert result["by_type"].get("7_day") == 1

    @pytest.mark.asyncio
    async def test_multiple_checks_multiple_alerts(self):
        from app.services.background_check_expiry import run_expiry_scan

        checks = [
            _make_check(check_id=1, driver_profile_id=10, expires_at=TODAY + timedelta(days=5)),
            _make_check(check_id=2, driver_profile_id=11, expires_at=TODAY + timedelta(days=25)),
            _make_check(check_id=3, driver_profile_id=12, expires_at=TODAY - timedelta(days=1)),
        ]
        db = _db_with_scalars(checks, [])
        with patch("app.services.background_check_expiry.date") as mock_date, \
             patch("app.services.background_check_expiry.datetime") as mock_dt:
            mock_date.today.return_value = TODAY
            mock_dt.now.return_value = NOW
            result = await run_expiry_scan(db)
        assert result["alerts_sent"] == 3
        assert result["by_type"].get("7_day") == 1
        assert result["by_type"].get("30_day") == 1
        assert result["by_type"].get("expired") == 1

    @pytest.mark.asyncio
    async def test_commit_called(self):
        from app.services.background_check_expiry import run_expiry_scan

        check = _make_check(check_id=1, driver_profile_id=10, expires_at=TODAY + timedelta(days=5))
        db = _db_with_scalars([check], [])
        with patch("app.services.background_check_expiry.date") as mock_date, \
             patch("app.services.background_check_expiry.datetime") as mock_dt:
            mock_date.today.return_value = TODAY
            mock_dt.now.return_value = NOW
            await run_expiry_scan(db)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_commit_called_even_with_no_alerts(self):
        from app.services.background_check_expiry import run_expiry_scan

        db = _db_with_scalars([], [])
        with patch("app.services.background_check_expiry.date") as mock_date:
            mock_date.today.return_value = TODAY
            await run_expiry_scan(db)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_check_at_60_days_generates_sixty_day_alert(self):
        from app.services.background_check_expiry import run_expiry_scan

        check = _make_check(check_id=1, driver_profile_id=10, expires_at=TODAY + timedelta(days=60))
        db = _db_with_scalars([check], [])
        with patch("app.services.background_check_expiry.date") as mock_date, \
             patch("app.services.background_check_expiry.datetime") as mock_dt:
            mock_date.today.return_value = TODAY
            mock_dt.now.return_value = NOW
            result = await run_expiry_scan(db)
        assert result["alerts_sent"] == 1
        assert result["by_type"].get("60_day") == 1

    @pytest.mark.asyncio
    async def test_db_add_called_for_each_new_alert(self):
        from app.services.background_check_expiry import run_expiry_scan

        checks = [
            _make_check(check_id=i, driver_profile_id=i, expires_at=TODAY + timedelta(days=5))
            for i in range(1, 4)
        ]
        db = _db_with_scalars(checks, [])
        with patch("app.services.background_check_expiry.date") as mock_date, \
             patch("app.services.background_check_expiry.datetime") as mock_dt:
            mock_date.today.return_value = TODAY
            mock_dt.now.return_value = NOW
            await run_expiry_scan(db)
        assert db.add.call_count == 3

    @pytest.mark.asyncio
    async def test_by_type_totals_match_alerts_sent(self):
        from app.services.background_check_expiry import run_expiry_scan

        checks = [
            _make_check(check_id=1, driver_profile_id=1, expires_at=TODAY + timedelta(days=55)),
            _make_check(check_id=2, driver_profile_id=2, expires_at=TODAY + timedelta(days=25)),
        ]
        db = _db_with_scalars(checks, [])
        with patch("app.services.background_check_expiry.date") as mock_date, \
             patch("app.services.background_check_expiry.datetime") as mock_dt:
            mock_date.today.return_value = TODAY
            mock_dt.now.return_value = NOW
            result = await run_expiry_scan(db)
        assert sum(result["by_type"].values()) == result["alerts_sent"]


# ===========================================================================
# Endpoint tests
# ===========================================================================


class TestAdminExpiringBackgroundChecksEndpoint:
    """Tests for GET /admin/background-checks/expiring."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_response(self):
        from app.api.v1.background_check_expiry import admin_expiring_background_checks

        admin = _make_user()
        db = AsyncMock()
        mock_rows = [
            ExpiringBackgroundCheckRow(
                check_id=1,
                driver_profile_id=10,
                expires_at=TODAY + timedelta(days=20),
                days_until_expiry=20,
                status="clear",
            )
        ]

        with patch(
            "app.api.v1.background_check_expiry.get_expiring_background_checks",
            new_callable=AsyncMock,
            return_value=mock_rows,
        ) as mock_svc:
            result = await admin_expiring_background_checks(
                days_ahead=60, limit=100, offset=0, _admin=admin, db=db
            )
            mock_svc.assert_awaited_once_with(db, days_ahead=60)

        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].check_id == 1

    @pytest.mark.asyncio
    async def test_empty_result(self):
        from app.api.v1.background_check_expiry import admin_expiring_background_checks

        admin = _make_user()
        db = AsyncMock()

        with patch(
            "app.api.v1.background_check_expiry.get_expiring_background_checks",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await admin_expiring_background_checks(
                days_ahead=60, limit=100, offset=0, _admin=admin, db=db
            )

        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_days_ahead_param_passed_to_service(self):
        from app.api.v1.background_check_expiry import admin_expiring_background_checks

        admin = _make_user()
        db = AsyncMock()

        with patch(
            "app.api.v1.background_check_expiry.get_expiring_background_checks",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_svc:
            await admin_expiring_background_checks(
                days_ahead=30, limit=100, offset=0, _admin=admin, db=db
            )
            mock_svc.assert_awaited_once_with(db, days_ahead=30)

    @pytest.mark.asyncio
    async def test_pagination_offset_applied(self):
        from app.api.v1.background_check_expiry import admin_expiring_background_checks

        admin = _make_user()
        db = AsyncMock()
        mock_rows = [
            ExpiringBackgroundCheckRow(
                check_id=i,
                driver_profile_id=i,
                expires_at=TODAY + timedelta(days=i),
                days_until_expiry=i,
                status="clear",
            )
            for i in range(1, 6)
        ]

        with patch(
            "app.api.v1.background_check_expiry.get_expiring_background_checks",
            new_callable=AsyncMock,
            return_value=mock_rows,
        ):
            result = await admin_expiring_background_checks(
                days_ahead=60, limit=10, offset=3, _admin=admin, db=db
            )

        assert len(result.items) == 2  # rows 4 and 5
        assert result.total == 5  # full count before pagination

    @pytest.mark.asyncio
    async def test_pagination_limit_applied(self):
        from app.api.v1.background_check_expiry import admin_expiring_background_checks

        admin = _make_user()
        db = AsyncMock()
        mock_rows = [
            ExpiringBackgroundCheckRow(
                check_id=i,
                driver_profile_id=i,
                expires_at=TODAY + timedelta(days=i),
                days_until_expiry=i,
                status="clear",
            )
            for i in range(1, 6)
        ]

        with patch(
            "app.api.v1.background_check_expiry.get_expiring_background_checks",
            new_callable=AsyncMock,
            return_value=mock_rows,
        ):
            result = await admin_expiring_background_checks(
                days_ahead=60, limit=2, offset=0, _admin=admin, db=db
            )

        assert len(result.items) == 2
        assert result.total == 5

    @pytest.mark.asyncio
    async def test_total_reflects_full_count_not_page_count(self):
        from app.api.v1.background_check_expiry import admin_expiring_background_checks

        admin = _make_user()
        db = AsyncMock()
        mock_rows = [
            ExpiringBackgroundCheckRow(
                check_id=i,
                driver_profile_id=i,
                expires_at=TODAY + timedelta(days=i),
                days_until_expiry=i,
                status="clear",
            )
            for i in range(1, 11)
        ]

        with patch(
            "app.api.v1.background_check_expiry.get_expiring_background_checks",
            new_callable=AsyncMock,
            return_value=mock_rows,
        ):
            result = await admin_expiring_background_checks(
                days_ahead=60, limit=3, offset=0, _admin=admin, db=db
            )

        assert result.total == 10
        assert len(result.items) == 3


class TestAdminBackgroundCheckExpiryScanEndpoint:
    """Tests for POST /admin/background-checks/expiry-scan."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_summary(self):
        from app.api.v1.background_check_expiry import admin_background_check_expiry_scan

        admin = _make_user()
        db = AsyncMock()
        mock_summary = {"alerts_sent": 5, "by_type": {"30_day": 3, "7_day": 2}}

        with patch(
            "app.api.v1.background_check_expiry.run_expiry_scan",
            new_callable=AsyncMock,
            return_value=mock_summary,
        ) as mock_svc:
            result = await admin_background_check_expiry_scan(_admin=admin, db=db)
            mock_svc.assert_awaited_once_with(db)

        assert result.alerts_sent == 5
        assert result.by_type["30_day"] == 3
        assert result.by_type["7_day"] == 2

    @pytest.mark.asyncio
    async def test_zero_alerts_returned(self):
        from app.api.v1.background_check_expiry import admin_background_check_expiry_scan

        admin = _make_user()
        db = AsyncMock()

        with patch(
            "app.api.v1.background_check_expiry.run_expiry_scan",
            new_callable=AsyncMock,
            return_value={"alerts_sent": 0, "by_type": {}},
        ):
            result = await admin_background_check_expiry_scan(_admin=admin, db=db)

        assert result.alerts_sent == 0
        assert result.by_type == {}

    @pytest.mark.asyncio
    async def test_service_called_with_db(self):
        from app.api.v1.background_check_expiry import admin_background_check_expiry_scan

        admin = _make_user()
        db = AsyncMock()

        with patch(
            "app.api.v1.background_check_expiry.run_expiry_scan",
            new_callable=AsyncMock,
            return_value={"alerts_sent": 0, "by_type": {}},
        ) as mock_svc:
            await admin_background_check_expiry_scan(_admin=admin, db=db)
        mock_svc.assert_awaited_once_with(db)

    @pytest.mark.asyncio
    async def test_all_alert_types_reflected(self):
        from app.api.v1.background_check_expiry import admin_background_check_expiry_scan

        admin = _make_user()
        db = AsyncMock()
        mock_summary = {
            "alerts_sent": 10,
            "by_type": {"60_day": 4, "30_day": 3, "7_day": 2, "expired": 1},
        }

        with patch(
            "app.api.v1.background_check_expiry.run_expiry_scan",
            new_callable=AsyncMock,
            return_value=mock_summary,
        ):
            result = await admin_background_check_expiry_scan(_admin=admin, db=db)

        assert result.alerts_sent == 10
        assert sum(result.by_type.values()) == 10
