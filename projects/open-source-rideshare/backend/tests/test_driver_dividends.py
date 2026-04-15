"""Unit tests for cooperative member dividend / profit-sharing feature.

Coverage:
  _quarter_date_range:
    1.  Q1 returns Jan 1 – Mar 31
    2.  Q4 returns Oct 1 – Dec 31
    3.  Invalid quarter raises ValueError

  calculate_dividend:
    4.  Returns year and quarter
    5.  Returns total_platform_surplus_usd
    6.  Returns total_qualifying_rides = sum of all driver rides
    7.  per_ride_payout_usd = surplus / total_rides
    8.  per_ride_payout_usd is 0.0 when no qualifying rides
    9.  Returns participating_drivers count
    10. Driver shares contain driver_id, profile_id, ride_count
    11. Driver share_pct = rides / total * 100
    12. Driver amount_usd = rides * per_ride_payout
    13. Shares sorted descending by qualifying_rides
    14. driver_share_id is 0 (preview, not persisted)
    15. Driver name populated from user record

  declare_dividend:
    16. Creates CooperativeDividend record (db.add called)
    17. Status is pending after declaration
    18. total_qualifying_rides set from ride data
    19. per_ride_payout_usd computed correctly
    20. DriverDividendShare records created (one per driver)
    21. Share amount_usd = rides * per_ride_payout
    22. Share share_pct = driver_rides / total_rides * 100
    23. Raises ValueError when dividend already exists for period
    24. Notes stored when provided
    25. Raises ValueError for invalid quarter

  admin_approve_dividend:
    26. Returns None for unknown dividend_id
    27. Status transitions from pending to approved
    28. approved_by_user_id set to admin's user_id
    29. approved_at set to current time
    30. Raises ValueError if not in pending status (approved → error)
    31. Raises ValueError if cancelled → error

  admin_distribute_dividend:
    32. Returns None for unknown dividend_id
    33. Status transitions from approved to distributed
    34. distributed_at set
    35. All pending shares transitioned to paid
    36. paid_at set on each share
    37. Raises ValueError if not in approved status (pending → error)
    38. Raises ValueError if already distributed

  admin_cancel_dividend:
    39. Returns None for unknown dividend_id
    40. Status transitions from pending to cancelled
    41. Status transitions from approved to cancelled
    42. Cancellation reason stored
    43. Pending shares transitioned to cancelled
    44. Raises ValueError if already distributed
    45. Raises ValueError if already cancelled

  list_dividends:
    46. Returns all dividends newest first
    47. Returns empty list when no dividends exist

  get_dividend:
    48. Returns dividend for known id
    49. Returns None for unknown id

  get_driver_dividend_history:
    50. Returns correct number of history items
    51. History item contains year, quarter, amount_usd
    52. History item contains share_pct
    53. History item contains dividend_status and share_status
    54. Returns empty list when driver has no shares

  build_dividend_detail:
    55. Returns id, year, quarter fields
    56. Includes shares list with driver items
    57. Driver names populated in share items
    58. Shares sorted descending by qualifying_rides

  Schema validation:
    59. DividendCalculationRequest rejects surplus_usd <= 0
    60. DividendCalculationRequest rejects invalid quarter
    61. DividendDeclarationRequest rejects surplus_usd <= 0

  Endpoint auth (integration):
    62. GET /platform/cooperative/dividends returns 200 without auth
    63. GET /drivers/me/dividends returns 403 without auth
    64. GET /drivers/me/dividends returns 403 for rider
    65. GET /drivers/me/dividends returns 200 for driver
    66. POST /admin/cooperative/dividends/calculate returns 403 for rider
    67. POST /admin/cooperative/dividends/calculate returns 403 for driver
    68. POST /admin/cooperative/dividends/calculate returns 200 for admin
    69. POST /admin/cooperative/dividends returns 403 for rider
    70. POST /admin/cooperative/dividends returns 403 for driver
    71. POST /admin/cooperative/dividends returns 201 for admin
    72. GET /admin/cooperative/dividends returns 403 for rider
    73. GET /admin/cooperative/dividends returns 200 for admin
    74. POST /admin/cooperative/dividends/{id}/approve returns 403 for rider
    75. POST /admin/cooperative/dividends/{id}/distribute returns 403 for driver
    76. POST /admin/cooperative/dividends/{id}/cancel returns 403 for rider
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.models  # noqa: F401 — ensure all models are registered
from app.models.driver_dividend import (
    CooperativeDividend,
    DividendShareStatus,
    DividendStatus,
    DriverDividendShare,
)
from app.schemas.driver_dividend import (
    DividendCalculationRequest,
    DividendDeclarationRequest,
)
from app.services.driver_dividend import (
    _quarter_date_range,
    admin_approve_dividend,
    admin_cancel_dividend,
    admin_distribute_dividend,
    build_dividend_detail,
    calculate_dividend,
    declare_dividend,
    get_dividend,
    get_driver_dividend_history,
    list_dividends,
)

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dividend(
    id: int = 1,
    year: int = 2026,
    quarter: int = 1,
    surplus: float = 5000.0,
    total_rides: int = 200,
    per_ride_payout: float = 25.0,
    status: DividendStatus = DividendStatus.pending,
    approved_by_user_id: int | None = None,
    notes: str | None = None,
    cancellation_reason: str | None = None,
) -> MagicMock:
    d = MagicMock(spec=CooperativeDividend)
    d.id = id
    d.year = year
    d.quarter = quarter
    d.total_platform_surplus_usd = surplus
    d.total_qualifying_rides = total_rides
    d.per_ride_payout_usd = per_ride_payout
    d.status = status
    d.approved_by_user_id = approved_by_user_id
    d.notes = notes
    d.cancellation_reason = cancellation_reason
    d.declared_at = _NOW
    d.approved_at = None
    d.distributed_at = None
    d.shares = []
    return d


def _make_share(
    id: int = 1,
    dividend_id: int = 1,
    driver_id: int = 10,
    driver_profile_id: int = 5,
    qualifying_rides: int = 50,
    share_pct: float = 25.0,
    amount_usd: float = 1250.0,
    status: DividendShareStatus = DividendShareStatus.pending,
) -> MagicMock:
    s = MagicMock(spec=DriverDividendShare)
    s.id = id
    s.dividend_id = dividend_id
    s.driver_id = driver_id
    s.driver_profile_id = driver_profile_id
    s.qualifying_rides = qualifying_rides
    s.share_pct = share_pct
    s.amount_usd = amount_usd
    s.status = status
    s.paid_at = None
    return s


def _scalar_one(item) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = item
    r.scalar_one.return_value = item
    scalars = MagicMock()
    scalars.all.return_value = [item] if item is not None else []
    r.scalars.return_value = scalars
    r.all.return_value = []
    return r


def _none_result() -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    r.scalar_one.return_value = 0
    scalars = MagicMock()
    scalars.all.return_value = []
    r.scalars.return_value = scalars
    r.all.return_value = []
    return r


def _scalars_list(items: list) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = items[0] if items else None
    scalars = MagicMock()
    scalars.all.return_value = items
    r.scalars.return_value = scalars
    r.all.return_value = [(item, None) for item in items]
    return r


def _make_db(*results) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _rows_result(rows: list) -> MagicMock:
    """Mock result where .all() returns list of tuples (for GROUP BY queries)."""
    r = MagicMock()
    r.all.return_value = rows
    scalars = MagicMock()
    scalars.all.return_value = [row[0] for row in rows] if rows else []
    r.scalars.return_value = scalars
    r.scalar_one_or_none.return_value = rows[0][0] if rows else None
    return r


# ---------------------------------------------------------------------------
# 1-3: _quarter_date_range
# ---------------------------------------------------------------------------

class TestQuarterDateRange:
    from datetime import date

    def test_q1_range(self):
        from datetime import date
        start, end = _quarter_date_range(2026, 1)
        assert start == date(2026, 1, 1)
        assert end == date(2026, 3, 31)

    def test_q4_range(self):
        from datetime import date
        start, end = _quarter_date_range(2026, 4)
        assert start == date(2026, 10, 1)
        assert end == date(2026, 12, 31)

    def test_invalid_quarter_raises(self):
        with pytest.raises(ValueError):
            _quarter_date_range(2026, 0)


# ---------------------------------------------------------------------------
# 4-15: calculate_dividend
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCalculateDividend:
    def _make_calc_db(
        self,
        driver_rows: list,
        profile_map: list | None = None,
        user_names: list | None = None,
    ) -> AsyncMock:
        """
        calculate_dividend calls:
          1. db.execute(GROUP BY query) → driver ride counts
          2. db.execute(profile lookup) → profile_id mapping
          3. db.execute(user names) → name mapping
        """
        ride_result = _rows_result(driver_rows)

        if profile_map is None:
            profile_map = [(uid, uid) for uid, _ in driver_rows]
        profile_result = _rows_result(profile_map)

        if user_names is None:
            user_names = [(uid, f"Driver {uid}") for uid, _ in driver_rows]
        name_result = _rows_result(user_names)

        return _make_db(ride_result, profile_result, name_result)

    async def test_returns_year(self):
        db = self._make_calc_db([(10, 50), (11, 30)])
        result = await calculate_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)
        assert result["year"] == 2026

    async def test_returns_quarter(self):
        db = self._make_calc_db([(10, 50)])
        result = await calculate_dividend(db, year=2026, quarter=2, surplus_usd=500.0)
        assert result["quarter"] == 2

    async def test_returns_surplus(self):
        db = self._make_calc_db([(10, 100)])
        result = await calculate_dividend(db, year=2026, quarter=1, surplus_usd=2500.0)
        assert result["total_platform_surplus_usd"] == 2500.0

    async def test_total_qualifying_rides(self):
        db = self._make_calc_db([(10, 50), (11, 30), (12, 20)])
        result = await calculate_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)
        assert result["total_qualifying_rides"] == 100

    async def test_per_ride_payout_computed(self):
        db = self._make_calc_db([(10, 100)])
        result = await calculate_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)
        assert abs(result["per_ride_payout_usd"] - 10.0) < 0.01

    async def test_per_ride_payout_zero_when_no_rides(self):
        db = self._make_calc_db([])
        result = await calculate_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)
        assert result["per_ride_payout_usd"] == 0.0

    async def test_participating_drivers_count(self):
        db = self._make_calc_db([(10, 50), (11, 30)])
        result = await calculate_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)
        assert result["participating_drivers"] == 2

    async def test_driver_shares_contain_driver_id(self):
        db = self._make_calc_db([(10, 50)])
        result = await calculate_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)
        assert result["driver_shares"][0]["driver_id"] == 10

    async def test_driver_share_pct(self):
        # Driver 10 has 50 rides, driver 11 has 50 rides → 50% each
        db = self._make_calc_db([(10, 50), (11, 50)])
        result = await calculate_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)
        for share in result["driver_shares"]:
            assert abs(share["share_pct"] - 50.0) < 0.01

    async def test_driver_amount_usd(self):
        # 100 rides total, $1000 surplus → $10/ride; driver with 60 rides → $600
        db = self._make_calc_db([(10, 60), (11, 40)])
        result = await calculate_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)
        shares = {s["driver_id"]: s for s in result["driver_shares"]}
        assert abs(shares[10]["amount_usd"] - 600.0) < 0.01
        assert abs(shares[11]["amount_usd"] - 400.0) < 0.01

    async def test_shares_sorted_descending_by_rides(self):
        db = self._make_calc_db([(10, 20), (11, 80)])
        result = await calculate_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)
        rides = [s["qualifying_rides"] for s in result["driver_shares"]]
        assert rides == sorted(rides, reverse=True)

    async def test_preview_share_id_is_zero(self):
        db = self._make_calc_db([(10, 100)])
        result = await calculate_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)
        assert result["driver_shares"][0]["driver_share_id"] == 0

    async def test_driver_name_populated(self):
        user_names = [(10, "Alice Driver")]
        db = self._make_calc_db([(10, 50)], user_names=user_names)
        result = await calculate_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)
        assert result["driver_shares"][0]["driver_name"] == "Alice Driver"


# ---------------------------------------------------------------------------
# 16-25: declare_dividend
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestDeclareDividend:
    def _make_declare_db(
        self,
        driver_rows: list,
        profile_map: list | None = None,
        user_names: list | None = None,
        existing_dividend=None,
    ) -> AsyncMock:
        """
        declare_dividend calls:
          1. existing check → scalar_one_or_none
          2. _driver_rides_in_period → ride count GROUP BY
          3. profile id lookup
          4. Optionally user name lookup (via build_dividend_detail / names)
        """
        ride_result = _rows_result(driver_rows)

        if profile_map is None:
            profile_map = [(uid, uid + 100) for uid, _ in driver_rows]
        profile_result = _rows_result(profile_map)

        existing_result = _scalar_one(existing_dividend)

        return _make_db(existing_result, ride_result, profile_result)

    async def test_db_add_called(self):
        db = self._make_declare_db([(10, 100)])
        await declare_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)
        db.add.assert_called()

    async def test_dividend_status_is_pending(self):
        db = self._make_declare_db([(10, 100)])
        dividend = await declare_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)
        assert dividend.status == DividendStatus.pending

    async def test_total_qualifying_rides_set(self):
        db = self._make_declare_db([(10, 60), (11, 40)])
        dividend = await declare_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)
        assert dividend.total_qualifying_rides == 100

    async def test_per_ride_payout_computed(self):
        db = self._make_declare_db([(10, 100)])
        dividend = await declare_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)
        assert abs(float(dividend.per_ride_payout_usd) - 10.0) < 0.01

    async def test_shares_created_for_each_driver(self):
        db = self._make_declare_db([(10, 50), (11, 50)])
        await declare_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)
        # add called once for dividend + once per driver share = 3 total
        assert db.add.call_count == 3

    async def test_share_amount_computed(self):
        """Each add call for a share gets amount_usd set."""
        db = self._make_declare_db([(10, 100)])
        await declare_dividend(db, year=2026, quarter=1, surplus_usd=500.0)
        # Check last add call (share) has amount_usd
        share_call = db.add.call_args_list[-1]
        share_obj = share_call[0][0]
        assert abs(float(share_obj.amount_usd) - 500.0) < 0.01

    async def test_share_pct_computed(self):
        db = self._make_declare_db([(10, 100)])
        await declare_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)
        share_obj = db.add.call_args_list[-1][0][0]
        assert abs(float(share_obj.share_pct) - 100.0) < 0.01

    async def test_raises_if_already_exists(self):
        existing = _make_dividend()
        db = self._make_declare_db([], existing_dividend=existing)
        with pytest.raises(ValueError, match="already exists"):
            await declare_dividend(db, year=2026, quarter=1, surplus_usd=1000.0)

    async def test_notes_stored(self):
        db = self._make_declare_db([(10, 100)])
        dividend = await declare_dividend(
            db, year=2026, quarter=1, surplus_usd=1000.0, notes="Q1 2026 surplus"
        )
        assert dividend.notes == "Q1 2026 surplus"

    async def test_raises_for_invalid_quarter(self):
        db = AsyncMock()
        with pytest.raises(ValueError):
            await declare_dividend(db, year=2026, quarter=5, surplus_usd=1000.0)


# ---------------------------------------------------------------------------
# 26-31: admin_approve_dividend
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAdminApproveDividend:
    async def test_returns_none_for_unknown_id(self):
        db = _make_db(_none_result())
        result = await admin_approve_dividend(db, dividend_id=999, admin_user_id=1)
        assert result is None

    async def test_status_transitions_to_approved(self):
        dividend = _make_dividend(status=DividendStatus.pending)
        db = _make_db(_scalar_one(dividend))
        await admin_approve_dividend(db, dividend_id=1, admin_user_id=7)
        assert dividend.status == DividendStatus.approved

    async def test_approved_by_user_id_set(self):
        dividend = _make_dividend(status=DividendStatus.pending)
        db = _make_db(_scalar_one(dividend))
        await admin_approve_dividend(db, dividend_id=1, admin_user_id=7)
        assert dividend.approved_by_user_id == 7

    async def test_approved_at_set(self):
        dividend = _make_dividend(status=DividendStatus.pending)
        db = _make_db(_scalar_one(dividend))
        await admin_approve_dividend(db, dividend_id=1, admin_user_id=1)
        assert dividend.approved_at is not None

    async def test_raises_if_already_approved(self):
        dividend = _make_dividend(status=DividendStatus.approved)
        db = _make_db(_scalar_one(dividend))
        with pytest.raises(ValueError, match="pending"):
            await admin_approve_dividend(db, dividend_id=1, admin_user_id=1)

    async def test_raises_if_cancelled(self):
        dividend = _make_dividend(status=DividendStatus.cancelled)
        db = _make_db(_scalar_one(dividend))
        with pytest.raises(ValueError):
            await admin_approve_dividend(db, dividend_id=1, admin_user_id=1)


# ---------------------------------------------------------------------------
# 32-38: admin_distribute_dividend
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAdminDistributeDividend:
    async def test_returns_none_for_unknown_id(self):
        db = _make_db(_none_result())
        result = await admin_distribute_dividend(db, dividend_id=999)
        assert result is None

    async def test_status_transitions_to_distributed(self):
        dividend = _make_dividend(status=DividendStatus.approved)
        share1 = _make_share(status=DividendShareStatus.pending)
        shares_result = _scalars_list([share1])
        db = _make_db(_scalar_one(dividend), shares_result)
        await admin_distribute_dividend(db, dividend_id=1)
        assert dividend.status == DividendStatus.distributed

    async def test_distributed_at_set(self):
        dividend = _make_dividend(status=DividendStatus.approved)
        share1 = _make_share(status=DividendShareStatus.pending)
        shares_result = _scalars_list([share1])
        db = _make_db(_scalar_one(dividend), shares_result)
        await admin_distribute_dividend(db, dividend_id=1)
        assert dividend.distributed_at is not None

    async def test_shares_set_to_paid(self):
        dividend = _make_dividend(status=DividendStatus.approved)
        share1 = _make_share(status=DividendShareStatus.pending)
        share2 = _make_share(id=2, driver_id=11, status=DividendShareStatus.pending)
        shares_result = _scalars_list([share1, share2])
        db = _make_db(_scalar_one(dividend), shares_result)
        await admin_distribute_dividend(db, dividend_id=1)
        assert share1.status == DividendShareStatus.paid
        assert share2.status == DividendShareStatus.paid

    async def test_paid_at_set_on_shares(self):
        dividend = _make_dividend(status=DividendStatus.approved)
        share1 = _make_share(status=DividendShareStatus.pending)
        shares_result = _scalars_list([share1])
        db = _make_db(_scalar_one(dividend), shares_result)
        await admin_distribute_dividend(db, dividend_id=1)
        assert share1.paid_at is not None

    async def test_raises_if_pending_not_approved(self):
        dividend = _make_dividend(status=DividendStatus.pending)
        db = _make_db(_scalar_one(dividend))
        with pytest.raises(ValueError, match="approved"):
            await admin_distribute_dividend(db, dividend_id=1)

    async def test_raises_if_already_distributed(self):
        dividend = _make_dividend(status=DividendStatus.distributed)
        db = _make_db(_scalar_one(dividend))
        with pytest.raises(ValueError):
            await admin_distribute_dividend(db, dividend_id=1)


# ---------------------------------------------------------------------------
# 39-45: admin_cancel_dividend
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAdminCancelDividend:
    async def test_returns_none_for_unknown_id(self):
        db = _make_db(_none_result())
        result = await admin_cancel_dividend(db, dividend_id=999)
        assert result is None

    async def test_cancels_pending_dividend(self):
        dividend = _make_dividend(status=DividendStatus.pending)
        share1 = _make_share(status=DividendShareStatus.pending)
        shares_result = _scalars_list([share1])
        db = _make_db(_scalar_one(dividend), shares_result)
        await admin_cancel_dividend(db, dividend_id=1)
        assert dividend.status == DividendStatus.cancelled

    async def test_cancels_approved_dividend(self):
        dividend = _make_dividend(status=DividendStatus.approved)
        shares_result = _scalars_list([])
        db = _make_db(_scalar_one(dividend), shares_result)
        await admin_cancel_dividend(db, dividend_id=1)
        assert dividend.status == DividendStatus.cancelled

    async def test_cancellation_reason_stored(self):
        dividend = _make_dividend(status=DividendStatus.pending)
        shares_result = _scalars_list([])
        db = _make_db(_scalar_one(dividend), shares_result)
        await admin_cancel_dividend(db, dividend_id=1, reason="Insufficient surplus")
        assert dividend.cancellation_reason == "Insufficient surplus"

    async def test_pending_shares_cancelled(self):
        dividend = _make_dividend(status=DividendStatus.pending)
        share1 = _make_share(status=DividendShareStatus.pending)
        shares_result = _scalars_list([share1])
        db = _make_db(_scalar_one(dividend), shares_result)
        await admin_cancel_dividend(db, dividend_id=1)
        assert share1.status == DividendShareStatus.cancelled

    async def test_raises_if_already_distributed(self):
        dividend = _make_dividend(status=DividendStatus.distributed)
        db = _make_db(_scalar_one(dividend))
        with pytest.raises(ValueError):
            await admin_cancel_dividend(db, dividend_id=1)

    async def test_raises_if_already_cancelled(self):
        dividend = _make_dividend(status=DividendStatus.cancelled)
        db = _make_db(_scalar_one(dividend))
        with pytest.raises(ValueError):
            await admin_cancel_dividend(db, dividend_id=1)


# ---------------------------------------------------------------------------
# 46-49: list_dividends / get_dividend
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestDividendRetrieval:
    async def test_list_returns_all(self):
        d1 = _make_dividend(id=1, year=2026, quarter=1)
        d2 = _make_dividend(id=2, year=2025, quarter=4)
        result_mock = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = [d1, d2]
        result_mock.scalars.return_value = scalars
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await list_dividends(db)
        assert len(result) == 2

    async def test_list_empty_when_none(self):
        result_mock = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        result_mock.scalars.return_value = scalars
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await list_dividends(db)
        assert result == []

    async def test_get_returns_matching(self):
        dividend = _make_dividend(id=5)
        # get_dividend uses selectinload — returns scalar_one_or_none
        db = _make_db(_scalar_one(dividend))
        result = await get_dividend(db, dividend_id=5)
        assert result is dividend

    async def test_get_returns_none_for_missing(self):
        db = _make_db(_none_result())
        result = await get_dividend(db, dividend_id=99)
        assert result is None


# ---------------------------------------------------------------------------
# 50-54: get_driver_dividend_history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGetDriverDividendHistory:
    async def test_returns_history_items(self):
        share = _make_share(qualifying_rides=40, share_pct=20.0, amount_usd=800.0)
        dividend = _make_dividend(year=2026, quarter=1, status=DividendStatus.distributed)
        rows_mock = MagicMock()
        rows_mock.all.return_value = [(share, dividend)]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=rows_mock)
        result = await get_driver_dividend_history(db, driver_profile_id=5)
        assert len(result) == 1

    async def test_history_item_has_year_quarter_amount(self):
        share = _make_share(qualifying_rides=40, share_pct=20.0, amount_usd=800.0)
        dividend = _make_dividend(year=2026, quarter=1)
        rows_mock = MagicMock()
        rows_mock.all.return_value = [(share, dividend)]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=rows_mock)
        result = await get_driver_dividend_history(db, driver_profile_id=5)
        item = result[0]
        assert item["year"] == 2026
        assert item["quarter"] == 1
        assert abs(item["amount_usd"] - 800.0) < 0.01

    async def test_history_item_has_share_pct(self):
        share = _make_share(share_pct=20.0, amount_usd=800.0)
        dividend = _make_dividend()
        rows_mock = MagicMock()
        rows_mock.all.return_value = [(share, dividend)]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=rows_mock)
        result = await get_driver_dividend_history(db, driver_profile_id=5)
        assert abs(result[0]["share_pct"] - 20.0) < 0.01

    async def test_history_item_has_statuses(self):
        share = _make_share(status=DividendShareStatus.paid)
        dividend = _make_dividend(status=DividendStatus.distributed)
        rows_mock = MagicMock()
        rows_mock.all.return_value = [(share, dividend)]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=rows_mock)
        result = await get_driver_dividend_history(db, driver_profile_id=5)
        assert result[0]["dividend_status"] == DividendStatus.distributed
        assert result[0]["share_status"] == DividendShareStatus.paid

    async def test_returns_empty_when_no_shares(self):
        rows_mock = MagicMock()
        rows_mock.all.return_value = []
        db = AsyncMock()
        db.execute = AsyncMock(return_value=rows_mock)
        result = await get_driver_dividend_history(db, driver_profile_id=99)
        assert result == []


# ---------------------------------------------------------------------------
# 55-58: build_dividend_detail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestBuildDividendDetail:
    async def test_returns_id_year_quarter(self):
        dividend = _make_dividend(id=3, year=2026, quarter=2)
        dividend.shares = []
        # build_dividend_detail calls _get_driver_names → user query
        name_result = _rows_result([])
        shares_result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        shares_result.scalars.return_value = scalars
        db = _make_db(shares_result, name_result)
        detail = await build_dividend_detail(db, dividend)
        assert detail["id"] == 3
        assert detail["year"] == 2026
        assert detail["quarter"] == 2

    async def test_includes_shares_list(self):
        share = _make_share(driver_id=10, qualifying_rides=50, share_pct=100.0, amount_usd=500.0)
        dividend = _make_dividend()
        dividend.shares = [share]
        name_result = _rows_result([(10, "Bob Driver")])
        db = _make_db(name_result)
        detail = await build_dividend_detail(db, dividend)
        assert len(detail["shares"]) == 1

    async def test_driver_names_populated(self):
        share = _make_share(driver_id=10, qualifying_rides=50, share_pct=100.0, amount_usd=500.0)
        dividend = _make_dividend()
        dividend.shares = [share]
        name_result = _rows_result([(10, "Carol Driver")])
        db = _make_db(name_result)
        detail = await build_dividend_detail(db, dividend)
        assert detail["shares"][0]["driver_name"] == "Carol Driver"

    async def test_shares_sorted_descending(self):
        share_a = _make_share(id=1, driver_id=10, qualifying_rides=20)
        share_b = _make_share(id=2, driver_id=11, qualifying_rides=80)
        dividend = _make_dividend()
        dividend.shares = [share_a, share_b]
        name_result = _rows_result([(10, "D1"), (11, "D2")])
        db = _make_db(name_result)
        detail = await build_dividend_detail(db, dividend)
        rides = [s["qualifying_rides"] for s in detail["shares"]]
        assert rides == sorted(rides, reverse=True)


# ---------------------------------------------------------------------------
# 59-61: Schema validation
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    def test_calculation_request_rejects_zero_surplus(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            DividendCalculationRequest(year=2026, quarter=1, surplus_usd=0.0)

    def test_calculation_request_rejects_negative_surplus(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            DividendCalculationRequest(year=2026, quarter=1, surplus_usd=-100.0)

    def test_calculation_request_rejects_invalid_quarter(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            DividendCalculationRequest(year=2026, quarter=5, surplus_usd=1000.0)

    def test_declaration_request_rejects_zero_surplus(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            DividendDeclarationRequest(year=2026, quarter=1, surplus_usd=0.0)


# ---------------------------------------------------------------------------
# 62-76: Endpoint auth (integration)
# ---------------------------------------------------------------------------

def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
class TestDividendEndpointAuth:
    async def test_public_list_no_auth(self, client):
        resp = await client.get("/api/v1/platform/cooperative/dividends")
        assert resp.status_code == 200

    async def test_driver_history_requires_auth(self, client):
        resp = await client.get("/api/v1/drivers/me/dividends")
        assert resp.status_code in (401, 403)

    async def test_driver_history_returns_403_for_rider(self, client, rider, rider_token):
        resp = await client.get(
            "/api/v1/drivers/me/dividends",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_driver_history_accessible_to_driver(self, client, driver_user, driver_token):
        resp = await client.get(
            "/api/v1/drivers/me/dividends",
            headers=auth_header(driver_token),
        )
        assert resp.status_code in (200, 404)

    async def test_calculate_returns_403_for_rider(self, client, rider, rider_token):
        resp = await client.post(
            "/api/v1/admin/cooperative/dividends/calculate",
            json={"year": 2026, "quarter": 1, "surplus_usd": 1000.0},
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_calculate_returns_403_for_driver(self, client, driver_user, driver_token):
        resp = await client.post(
            "/api/v1/admin/cooperative/dividends/calculate",
            json={"year": 2026, "quarter": 1, "surplus_usd": 1000.0},
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 403

    async def test_calculate_accessible_to_admin(self, client, admin_user, admin_token):
        resp = await client.post(
            "/api/v1/admin/cooperative/dividends/calculate",
            json={"year": 2026, "quarter": 1, "surplus_usd": 1000.0},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_declare_returns_403_for_rider(self, client, rider, rider_token):
        resp = await client.post(
            "/api/v1/admin/cooperative/dividends",
            json={"year": 2026, "quarter": 1, "surplus_usd": 1000.0},
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_declare_returns_403_for_driver(self, client, driver_user, driver_token):
        resp = await client.post(
            "/api/v1/admin/cooperative/dividends",
            json={"year": 2026, "quarter": 1, "surplus_usd": 1000.0},
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 403

    async def test_declare_accessible_to_admin(self, client, admin_user, admin_token):
        resp = await client.post(
            "/api/v1/admin/cooperative/dividends",
            json={"year": 2026, "quarter": 1, "surplus_usd": 1000.0},
            headers=auth_header(admin_token),
        )
        assert resp.status_code in (201, 422)  # 422 = already exists (idempotent test run)

    async def test_list_returns_403_for_rider(self, client, rider, rider_token):
        resp = await client.get(
            "/api/v1/admin/cooperative/dividends",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_list_accessible_to_admin(self, client, admin_user, admin_token):
        resp = await client.get(
            "/api/v1/admin/cooperative/dividends",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_approve_returns_403_for_rider(self, client, rider, rider_token):
        resp = await client.post(
            "/api/v1/admin/cooperative/dividends/999/approve",
            json={},
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_distribute_returns_403_for_driver(self, client, driver_user, driver_token):
        resp = await client.post(
            "/api/v1/admin/cooperative/dividends/999/distribute",
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 403

    async def test_cancel_returns_403_for_rider(self, client, rider, rider_token):
        resp = await client.post(
            "/api/v1/admin/cooperative/dividends/999/cancel",
            json={},
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403
