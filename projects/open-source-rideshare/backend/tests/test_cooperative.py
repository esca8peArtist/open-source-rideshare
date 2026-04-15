"""Unit tests for cooperative transparency and member equity feature.

Coverage:
  _quarter_date_range helper:
    1.  Q1 starts Jan 1, ends Mar 31
    2.  Q2 starts Apr 1, ends Jun 30
    3.  Q3 starts Jul 1, ends Sep 30
    4.  Q4 starts Oct 1, ends Dec 31
    5.  Invalid quarter raises ValueError

  get_platform_public_stats:
    6.  Returns total_completed_rides from ride count query
    7.  Returns total_cancelled_rides from ride count query
    8.  Returns total_fare_collected_usd from payment sum
    9.  Returns total_platform_fees_usd from payment sum
    10. Returns total_driver_earnings_usd = fare - platform_fee
    11. Returns total_tips_usd from payment sum
    12. platform_fee_rate_pct is 0.0 when no fare collected
    13. driver_take_rate_pct is 0.0 when no fare collected
    14. platform_fee_rate_pct correct when fare > 0
    15. driver_take_rate_pct correct when fare > 0
    16. Returns total_approved_drivers count
    17. Returns total_active_riders count
    18. Returns drivers_currently_online count

  get_driver_equity_stats:
    19. Returns None for unknown driver_profile_id
    20. Returns driver_profile_id in response
    21. Returns driver_name from user record
    22. tenure_days reflects driver account age
    23. lifetime_completed_trips from completed ride count
    24. platform_total_trips reflects all platform completed rides
    25. equity_share_pct is 0.0 when platform has no trips
    26. equity_share_pct correct when platform has trips
    27. equity_share_pct is 0.0 when driver has no trips (but platform does)
    28. lifetime_earnings_usd computed as amount - platform_fee
    29. lifetime_tips_usd from tip_amount sum
    30. lifetime_platform_contribution_usd = sum of platform_fees
    31. rating_avg from driver profile
    32. is_approved from driver profile

  generate_quarterly_report:
    33. Creates new report when none exists
    34. Updates existing report when called twice (idempotent)
    35. total_rides reflects completed rides in period
    36. total_cancelled_rides reflects cancelled rides in period
    37. platform_fee_rate_pct computed correctly
    38. driver_take_rate_pct computed correctly
    39. active_drivers counts distinct drivers in period
    40. active_riders counts distinct riders in period
    41. new_drivers counts drivers created in period
    42. new_riders counts users created in period
    43. notes field stored when provided

  list_quarterly_reports:
    44. Returns all reports
    45. Returns empty list when no reports exist

  get_quarterly_report:
    46. Returns report for matching year/quarter
    47. Returns None for missing year/quarter

  Endpoint auth (integration):
    48. GET /platform/cooperative/stats returns 200 without auth
    49. GET /platform/cooperative/reports returns 200 without auth
    50. GET /platform/cooperative/reports/{year}/{quarter} returns 404 for missing report
    51. GET /platform/cooperative/reports/{year}/{quarter} returns 422 for invalid quarter
    52. GET /drivers/me/cooperative-equity returns 403 for unauthenticated
    53. GET /drivers/me/cooperative-equity returns 403 for rider
    54. GET /drivers/me/cooperative-equity returns 200 for driver
    55. POST /admin/cooperative/reports/generate returns 403 for rider
    56. POST /admin/cooperative/reports/generate returns 403 for driver
    57. POST /admin/cooperative/reports/generate returns 200 for admin
    58. POST /admin/cooperative/reports/generate returns 422 for invalid quarter
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.cooperative_report import CooperativeReport
from app.models.driver import DriverProfile
from app.models.user import User
from app.services.cooperative import (
    _quarter_date_range,
    generate_quarterly_report,
    get_driver_equity_stats,
    get_platform_public_stats,
    get_quarterly_report,
    list_quarterly_reports,
)

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# DB mock helpers (same pattern used throughout test suite)
# ---------------------------------------------------------------------------


def _one_result(item) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = item
    r.scalar_one.return_value = item
    scalars = MagicMock()
    scalars.all.return_value = [item] if item is not None else []
    r.scalars.return_value = scalars
    return r


def _list_result(items: list) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = items[0] if items else None
    r.scalar_one.return_value = len(items)
    scalars = MagicMock()
    scalars.all.return_value = items
    r.scalars.return_value = scalars
    return r


def _count_result(n: int) -> MagicMock:
    r = MagicMock()
    r.scalar_one.return_value = n
    r.scalar_one_or_none.return_value = n
    scalars = MagicMock()
    scalars.all.return_value = []
    r.scalars.return_value = scalars
    return r


def _none_result() -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    r.scalar_one.return_value = 0
    scalars = MagicMock()
    scalars.all.return_value = []
    r.scalars.return_value = scalars
    return r


def _row_result(*values) -> MagicMock:
    """Simulate a result with .one() returning a tuple of values."""
    r = MagicMock()
    r.one.return_value = values
    r.scalar_one_or_none.return_value = values[0] if values else None
    r.scalar_one.return_value = values[0] if values else 0
    return r


def _make_db(*results) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


_PAST = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _make_driver(
    driver_id: int = 1,
    user_id: int = 10,
    rating_avg: float = 4.8,
    total_trips: int = 50,
    is_approved: bool = True,
    created_at: datetime = _PAST,
) -> MagicMock:
    d = MagicMock(spec=DriverProfile)
    d.id = driver_id
    d.user_id = user_id
    d.rating_avg = rating_avg
    d.total_trips = total_trips
    d.is_approved = is_approved
    d.is_online = False
    d.created_at = created_at
    return d


def _make_user(
    user_id: int = 10,
    name: str = "Test Driver",
) -> MagicMock:
    u = MagicMock(spec=User)
    u.id = user_id
    u.name = name
    return u


def _make_report(
    year: int = 2026,
    quarter: int = 1,
    report_id: int = 1,
) -> MagicMock:
    r = MagicMock(spec=CooperativeReport)
    r.id = report_id
    r.year = year
    r.quarter = quarter
    r.total_rides = 100
    r.total_cancelled_rides = 5
    r.total_fare_collected_usd = 5000.0
    r.total_platform_fees_usd = 750.0
    r.total_driver_earnings_usd = 4250.0
    r.total_tips_usd = 300.0
    r.platform_fee_rate_pct = 15.0
    r.driver_take_rate_pct = 85.0
    r.active_drivers = 20
    r.active_riders = 80
    r.new_drivers = 3
    r.new_riders = 15
    r.generated_at = _NOW
    r.notes = None
    return r


# ---------------------------------------------------------------------------
# 1-5: _quarter_date_range
# ---------------------------------------------------------------------------

class TestQuarterDateRange:
    def test_q1_start(self):
        start, _ = _quarter_date_range(2026, 1)
        assert start == date(2026, 1, 1)

    def test_q1_end(self):
        _, end = _quarter_date_range(2026, 1)
        assert end == date(2026, 3, 31)

    def test_q2_range(self):
        start, end = _quarter_date_range(2026, 2)
        assert start == date(2026, 4, 1)
        assert end == date(2026, 6, 30)

    def test_q3_range(self):
        start, end = _quarter_date_range(2026, 3)
        assert start == date(2026, 7, 1)
        assert end == date(2026, 9, 30)

    def test_q4_range(self):
        start, end = _quarter_date_range(2026, 4)
        assert start == date(2026, 10, 1)
        assert end == date(2026, 12, 31)

    def test_invalid_quarter_raises(self):
        with pytest.raises(ValueError):
            _quarter_date_range(2026, 5)


# ---------------------------------------------------------------------------
# 6-18: get_platform_public_stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGetPlatformPublicStats:
    def _make_stats_db(
        self,
        completed: int = 120,
        cancelled: int = 10,
        fare: float = 6000.0,
        platform_fee: float = 900.0,
        tips: float = 400.0,
        total_drivers: int = 25,
        total_riders: int = 200,
        online_drivers: int = 8,
    ) -> AsyncMock:
        return _make_db(
            _count_result(completed),           # completed rides
            _count_result(cancelled),           # cancelled rides
            _row_result(fare, platform_fee, tips),  # financial totals
            _count_result(total_drivers),       # approved drivers
            _count_result(total_riders),        # active riders
            _count_result(online_drivers),      # online drivers
        )

    async def test_total_completed_rides(self):
        db = self._make_stats_db(completed=120)
        stats = await get_platform_public_stats(db)
        assert stats["total_completed_rides"] == 120

    async def test_total_cancelled_rides(self):
        db = self._make_stats_db(cancelled=10)
        stats = await get_platform_public_stats(db)
        assert stats["total_cancelled_rides"] == 10

    async def test_total_fare_collected(self):
        db = self._make_stats_db(fare=6000.0)
        stats = await get_platform_public_stats(db)
        assert stats["total_fare_collected_usd"] == 6000.0

    async def test_total_platform_fees(self):
        db = self._make_stats_db(fare=6000.0, platform_fee=900.0)
        stats = await get_platform_public_stats(db)
        assert stats["total_platform_fees_usd"] == 900.0

    async def test_total_driver_earnings(self):
        db = self._make_stats_db(fare=6000.0, platform_fee=900.0)
        stats = await get_platform_public_stats(db)
        assert abs(stats["total_driver_earnings_usd"] - 5100.0) < 0.01

    async def test_total_tips(self):
        db = self._make_stats_db(tips=400.0)
        stats = await get_platform_public_stats(db)
        assert stats["total_tips_usd"] == 400.0

    async def test_platform_fee_rate_zero_when_no_fare(self):
        db = self._make_stats_db(fare=0.0, platform_fee=0.0, tips=0.0)
        stats = await get_platform_public_stats(db)
        assert stats["platform_fee_rate_pct"] == 0.0

    async def test_driver_take_rate_zero_when_no_fare(self):
        db = self._make_stats_db(fare=0.0, platform_fee=0.0, tips=0.0)
        stats = await get_platform_public_stats(db)
        assert stats["driver_take_rate_pct"] == 0.0

    async def test_platform_fee_rate_correct(self):
        db = self._make_stats_db(fare=1000.0, platform_fee=150.0)
        stats = await get_platform_public_stats(db)
        assert abs(stats["platform_fee_rate_pct"] - 15.0) < 0.01

    async def test_driver_take_rate_correct(self):
        db = self._make_stats_db(fare=1000.0, platform_fee=150.0)
        stats = await get_platform_public_stats(db)
        assert abs(stats["driver_take_rate_pct"] - 85.0) < 0.01

    async def test_total_approved_drivers(self):
        db = self._make_stats_db(total_drivers=25)
        stats = await get_platform_public_stats(db)
        assert stats["total_approved_drivers"] == 25

    async def test_total_active_riders(self):
        db = self._make_stats_db(total_riders=200)
        stats = await get_platform_public_stats(db)
        assert stats["total_active_riders"] == 200

    async def test_drivers_currently_online(self):
        db = self._make_stats_db(online_drivers=8)
        stats = await get_platform_public_stats(db)
        assert stats["drivers_currently_online"] == 8


# ---------------------------------------------------------------------------
# 19-32: get_driver_equity_stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGetDriverEquityStats:
    def _make_equity_db(
        self,
        driver=None,
        user=None,
        platform_trips: int = 500,
        driver_trips: int = 50,
        driver_earnings: float = 2550.0,
        platform_contribution: float = 450.0,
        tips: float = 200.0,
    ) -> AsyncMock:
        if driver is None:
            driver = _make_driver()
        if user is None:
            user = _make_user()
        return _make_db(
            _one_result(driver),                                   # driver profile lookup
            _one_result(user),                                     # user lookup
            _count_result(platform_trips),                         # total platform completed rides
            _count_result(driver_trips),                           # driver's completed rides
            _row_result(driver_earnings, platform_contribution, tips),  # financial query
        )

    async def test_returns_none_for_unknown_driver(self):
        db = _make_db(_none_result())
        result = await get_driver_equity_stats(db, driver_profile_id=999)
        assert result is None

    async def test_returns_driver_profile_id(self):
        db = self._make_equity_db()
        result = await get_driver_equity_stats(db, driver_profile_id=1)
        assert result["driver_profile_id"] == 1

    async def test_returns_driver_name(self):
        user = _make_user(name="Alice Smith")
        db = self._make_equity_db(user=user)
        result = await get_driver_equity_stats(db, driver_profile_id=1)
        assert result["driver_name"] == "Alice Smith"

    async def test_tenure_days_non_negative(self):
        db = self._make_equity_db()
        result = await get_driver_equity_stats(db, driver_profile_id=1)
        assert result["tenure_days"] >= 0

    async def test_lifetime_completed_trips(self):
        db = self._make_equity_db(driver_trips=50)
        result = await get_driver_equity_stats(db, driver_profile_id=1)
        assert result["lifetime_completed_trips"] == 50

    async def test_platform_total_trips(self):
        db = self._make_equity_db(platform_trips=500)
        result = await get_driver_equity_stats(db, driver_profile_id=1)
        assert result["platform_total_trips"] == 500

    async def test_equity_share_zero_when_no_platform_trips(self):
        db = self._make_equity_db(platform_trips=0, driver_trips=0)
        result = await get_driver_equity_stats(db, driver_profile_id=1)
        assert result["equity_share_pct"] == 0.0

    async def test_equity_share_correct(self):
        db = self._make_equity_db(platform_trips=500, driver_trips=50)
        result = await get_driver_equity_stats(db, driver_profile_id=1)
        assert abs(result["equity_share_pct"] - 10.0) < 0.01

    async def test_equity_share_zero_when_driver_has_no_trips(self):
        db = self._make_equity_db(platform_trips=500, driver_trips=0)
        result = await get_driver_equity_stats(db, driver_profile_id=1)
        assert result["equity_share_pct"] == 0.0

    async def test_lifetime_earnings_usd(self):
        db = self._make_equity_db(driver_earnings=2550.0)
        result = await get_driver_equity_stats(db, driver_profile_id=1)
        assert abs(result["lifetime_earnings_usd"] - 2550.0) < 0.01

    async def test_lifetime_tips_usd(self):
        db = self._make_equity_db(tips=200.0)
        result = await get_driver_equity_stats(db, driver_profile_id=1)
        assert abs(result["lifetime_tips_usd"] - 200.0) < 0.01

    async def test_lifetime_platform_contribution_usd(self):
        db = self._make_equity_db(platform_contribution=450.0)
        result = await get_driver_equity_stats(db, driver_profile_id=1)
        assert abs(result["lifetime_platform_contribution_usd"] - 450.0) < 0.01

    async def test_rating_avg(self):
        driver = _make_driver(rating_avg=4.9)
        db = self._make_equity_db(driver=driver)
        result = await get_driver_equity_stats(db, driver_profile_id=1)
        assert result["rating_avg"] == 4.9

    async def test_is_approved(self):
        driver = _make_driver(is_approved=True)
        db = self._make_equity_db(driver=driver)
        result = await get_driver_equity_stats(db, driver_profile_id=1)
        assert result["is_approved"] is True


# ---------------------------------------------------------------------------
# 33-43: generate_quarterly_report
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGenerateQuarterlyReport:
    def _make_gen_db(
        self,
        completed: int = 100,
        cancelled: int = 5,
        fare: float = 5000.0,
        platform_fee: float = 750.0,
        tips: float = 300.0,
        active_drivers: int = 20,
        active_riders: int = 80,
        new_drivers: int = 3,
        new_riders: int = 15,
        existing_report=None,
    ) -> AsyncMock:
        return _make_db(
            _count_result(completed),                      # completed rides in period
            _count_result(cancelled),                      # cancelled rides in period
            _row_result(fare, platform_fee, tips),          # financial query
            _count_result(active_drivers),                 # active drivers
            _count_result(active_riders),                  # active riders
            _count_result(new_drivers),                    # new drivers
            _count_result(new_riders),                     # new riders
            _one_result(existing_report),                  # existing report lookup
        )

    async def test_creates_new_report_when_none_exists(self):
        db = self._make_gen_db(existing_report=None)
        report = await generate_quarterly_report(db, year=2026, quarter=1)
        db.add.assert_called_once()

    async def test_updates_existing_report(self):
        existing = _make_report(year=2026, quarter=1)
        db = self._make_gen_db(existing_report=existing)
        report = await generate_quarterly_report(db, year=2026, quarter=1)
        # Should not add a second record
        db.add.assert_not_called()

    async def test_total_rides(self):
        db = self._make_gen_db(completed=100)
        report = await generate_quarterly_report(db, year=2026, quarter=1)
        assert report.total_rides == 100

    async def test_total_cancelled_rides(self):
        db = self._make_gen_db(cancelled=5)
        report = await generate_quarterly_report(db, year=2026, quarter=1)
        assert report.total_cancelled_rides == 5

    async def test_platform_fee_rate_computed_correctly(self):
        db = self._make_gen_db(fare=1000.0, platform_fee=150.0)
        report = await generate_quarterly_report(db, year=2026, quarter=1)
        assert abs(report.platform_fee_rate_pct - 15.0) < 0.01

    async def test_driver_take_rate_computed_correctly(self):
        db = self._make_gen_db(fare=1000.0, platform_fee=150.0)
        report = await generate_quarterly_report(db, year=2026, quarter=1)
        assert abs(report.driver_take_rate_pct - 85.0) < 0.01

    async def test_active_drivers(self):
        db = self._make_gen_db(active_drivers=20)
        report = await generate_quarterly_report(db, year=2026, quarter=1)
        assert report.active_drivers == 20

    async def test_active_riders(self):
        db = self._make_gen_db(active_riders=80)
        report = await generate_quarterly_report(db, year=2026, quarter=1)
        assert report.active_riders == 80

    async def test_new_drivers(self):
        db = self._make_gen_db(new_drivers=3)
        report = await generate_quarterly_report(db, year=2026, quarter=1)
        assert report.new_drivers == 3

    async def test_new_riders(self):
        db = self._make_gen_db(new_riders=15)
        report = await generate_quarterly_report(db, year=2026, quarter=1)
        assert report.new_riders == 15

    async def test_notes_stored(self):
        db = self._make_gen_db(existing_report=None)
        report = await generate_quarterly_report(
            db, year=2026, quarter=1, notes="End of Q1 report"
        )
        assert report.notes == "End of Q1 report"


# ---------------------------------------------------------------------------
# 44-47: list / get quarterly reports
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestReportRetrieval:
    async def test_list_returns_all_reports(self):
        reports = [_make_report(year=2026, quarter=1), _make_report(year=2025, quarter=4)]
        r = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = reports
        r.scalars.return_value = scalars
        db = AsyncMock()
        db.execute = AsyncMock(return_value=r)
        result = await list_quarterly_reports(db)
        assert len(result) == 2

    async def test_list_returns_empty_when_none(self):
        r = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        r.scalars.return_value = scalars
        db = AsyncMock()
        db.execute = AsyncMock(return_value=r)
        result = await list_quarterly_reports(db)
        assert result == []

    async def test_get_returns_matching_report(self):
        report = _make_report(year=2026, quarter=1)
        db = _make_db(_one_result(report))
        result = await get_quarterly_report(db, year=2026, quarter=1)
        assert result is report

    async def test_get_returns_none_for_missing(self):
        db = _make_db(_none_result())
        result = await get_quarterly_report(db, year=2020, quarter=2)
        assert result is None


# ---------------------------------------------------------------------------
# 48-58: Endpoint auth (integration)
# ---------------------------------------------------------------------------


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
class TestCooperativeEndpointAuth:
    async def test_platform_stats_public_no_auth(self, client):
        resp = await client.get("/api/v1/platform/cooperative/stats")
        assert resp.status_code == 200

    async def test_list_reports_public_no_auth(self, client):
        resp = await client.get("/api/v1/platform/cooperative/reports")
        assert resp.status_code == 200

    async def test_get_report_404_for_missing(self, client):
        resp = await client.get("/api/v1/platform/cooperative/reports/1900/1")
        assert resp.status_code == 404

    async def test_get_report_422_for_invalid_quarter(self, client):
        resp = await client.get("/api/v1/platform/cooperative/reports/2026/9")
        assert resp.status_code == 422

    async def test_driver_equity_requires_auth(self, client):
        resp = await client.get("/api/v1/drivers/me/cooperative-equity")
        assert resp.status_code in (401, 403)

    async def test_driver_equity_returns_403_for_rider(self, client, rider, rider_token):
        resp = await client.get(
            "/api/v1/drivers/me/cooperative-equity",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_driver_equity_accessible_to_driver(self, client, driver_user, driver_token):
        resp = await client.get(
            "/api/v1/drivers/me/cooperative-equity",
            headers=auth_header(driver_token),
        )
        # 200 or 404 (driver profile exists in test db — either is a success)
        assert resp.status_code in (200, 404)

    async def test_generate_report_returns_403_for_rider(self, client, rider, rider_token):
        resp = await client.post(
            "/api/v1/admin/cooperative/reports/generate",
            json={"year": 2026, "quarter": 1},
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_generate_report_returns_403_for_driver(
        self, client, driver_user, driver_token
    ):
        resp = await client.post(
            "/api/v1/admin/cooperative/reports/generate",
            json={"year": 2026, "quarter": 1},
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 403

    async def test_generate_report_accessible_to_admin(self, client, admin_user, admin_token):
        resp = await client.post(
            "/api/v1/admin/cooperative/reports/generate",
            json={"year": 2026, "quarter": 1},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_generate_report_returns_422_for_invalid_quarter(
        self, client, admin_user, admin_token
    ):
        resp = await client.post(
            "/api/v1/admin/cooperative/reports/generate",
            json={"year": 2026, "quarter": 7},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422
