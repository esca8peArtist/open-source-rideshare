"""Tests for the admin financial reconciliation feature.

Covers:

Service unit tests (using AsyncMock for DB):
  1.  get_financial_summary — empty period returns zeroed summary
  2.  get_financial_summary — ride_count is correct
  3.  get_financial_summary — total_ride_fares sums actual_fare
  4.  get_financial_summary — falls back to estimated_fare when actual_fare is None
  5.  get_financial_summary — total_tips_collected sums completed tips
  6.  get_financial_summary — gross_platform_revenue sums platform fees
  7.  get_financial_summary — total_refunds_issued from refunded payments
  8.  get_financial_summary — net_platform_revenue = gross - refunds
  9.  get_financial_summary — total_promo_discounts_applied from redemptions
  10. get_financial_summary — active_drivers counts unique driver_ids
  11. get_financial_summary — active_riders counts unique rider_ids
  12. get_financial_summary — average_fare is mean of fares
  13. get_financial_summary — total_driver_payouts sums completed payouts
  14. get_financial_summary — daily_breakdown groups by date
  15. get_financial_summary — daily_breakdown is sorted ascending
  16. get_financial_summary — period contains start_date and end_date
  17. get_financial_summary — zero refunds gives net == gross
  18. export_reconciliation_csv — returns header row
  19. export_reconciliation_csv — empty period returns header only
  20. export_reconciliation_csv — correct number of data rows
  21. export_reconciliation_csv — row contains expected columns
  22. export_reconciliation_csv — net_platform = platform_fee - refund_amount
  23. export_reconciliation_csv — refund_amount is 0 when no refund
  24. export_reconciliation_csv — driver_id is empty string when None
  25. get_payout_status — empty result returns empty list
  26. get_payout_status — returns payout records with correct fields
  27. get_payout_status — driver_name resolved from users table
  28. get_payout_status — unknown driver shows "Unknown"
  29. get_payout_status — status filter passed through correctly
  30. get_payout_status — invalid status returns empty list

API integration tests (using real in-transaction test DB via conftest fixtures):
  31. GET /summary — 401 with no auth
  32. GET /summary — 403 with rider token
  33. GET /summary — 403 with driver token
  34. GET /summary — 200 with admin token, valid date range
  35. GET /summary — response contains required fields
  36. GET /summary — missing start_date returns 422
  37. GET /summary — missing end_date returns 422
  38. GET /summary — invalid date format returns 422
  39. GET /summary — end_date before start_date returns 422
  40. GET /summary — empty period returns zero ride_count
  41. GET /summary — daily_breakdown is a list
  42. GET /export — 401 with no auth
  43. GET /export — 403 with rider token
  44. GET /export — 200 with admin token, CSV content-type
  45. GET /export — CSV has correct header columns
  46. GET /export — missing start_date returns 422
  47. GET /export — end_date before start_date returns 422
  48. GET /payout-status — 401 with no auth
  49. GET /payout-status — 403 with rider token
  50. GET /payout-status — 200 with admin token
  51. GET /payout-status — returns a list
  52. GET /payout-status — invalid status returns 422
  53. GET /payout-status — valid status param accepted
  54. GET /summary — ride data aggregated correctly in integration test
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.payment import Payment, PaymentStatus
from app.models.payout import DriverPayout, PayoutStatus
from app.models.promo import PromoRedemption
from app.models.ride import Ride, RideStatus
from app.models.tip import TipRecord, TipStatus
from app.models.user import User, UserRole
from app.services.admin_financials import (
    export_reconciliation_csv,
    get_financial_summary,
    get_payout_status,
)

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

_START = date(2025, 3, 1)
_END = date(2025, 3, 31)
_DT = datetime(2025, 3, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_ride(
    ride_id: int = 1,
    rider_id: int = 10,
    driver_id: int | None = 20,
    actual_fare: float | None = 15.00,
    estimated_fare: float = 14.50,
    promo_discount: float = 0.0,
    completed_at: datetime | None = None,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = RideStatus.COMPLETED
    ride.actual_fare = actual_fare
    ride.estimated_fare = estimated_fare
    ride.promo_discount = promo_discount
    ride.completed_at = completed_at or _DT
    ride.pickup_address = "123 Main St"
    ride.dropoff_address = "456 Oak Ave"
    return ride


def _make_payment(
    pay_id: int = 1,
    ride_id: int = 1,
    amount: float = 15.00,
    platform_fee: float = 2.25,
    driver_payout: float = 12.75,
    status: PaymentStatus = PaymentStatus.COMPLETED,
) -> MagicMock:
    p = MagicMock(spec=Payment)
    p.id = pay_id
    p.ride_id = ride_id
    p.amount = amount
    p.platform_fee = platform_fee
    p.driver_payout = driver_payout
    p.status = status
    return p


def _make_tip(
    tip_id: int = 1,
    ride_id: int = 1,
    amount_cents: int = 200,
    status: TipStatus = TipStatus.COMPLETED,
) -> MagicMock:
    t = MagicMock(spec=TipRecord)
    t.id = tip_id
    t.ride_id = ride_id
    t.amount_cents = amount_cents
    t.status = status
    return t


def _make_promo_redemption(
    redemption_id: int = 1,
    ride_id: int = 1,
    discount_amount: float = 5.0,
) -> MagicMock:
    pr = MagicMock(spec=PromoRedemption)
    pr.id = redemption_id
    pr.ride_id = ride_id
    pr.discount_amount = discount_amount
    return pr


def _make_payout(
    payout_id: int = 1,
    driver_id: int = 20,
    total_amount: float = 150.0,
    status: PayoutStatus = PayoutStatus.COMPLETED,
    trip_count: int = 10,
    created_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> MagicMock:
    dp = MagicMock(spec=DriverPayout)
    dp.id = payout_id
    dp.driver_id = driver_id
    dp.total_amount = total_amount
    dp.status = status
    dp.trip_count = trip_count
    dp.created_at = created_at or _DT
    dp.completed_at = completed_at or _DT
    dp.processed_at = None
    return dp


def _make_user(user_id: int = 20, name: str = "Test Driver") -> MagicMock:
    u = MagicMock(spec=User)
    u.id = user_id
    u.name = name
    return u


def _make_db(*result_lists) -> AsyncMock:
    """DB mock where each execute() call returns the next list via scalars().all()."""
    db = AsyncMock()
    side_effects = []
    for items in result_lists:
        mock_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = items
        mock_result.scalars.return_value = scalars_mock
        side_effects.append(mock_result)
    db.execute = AsyncMock(side_effect=side_effects)
    return db


# ---------------------------------------------------------------------------
# Service unit tests — get_financial_summary
# ---------------------------------------------------------------------------


class TestGetFinancialSummary:
    # DB call order for empty rides: rides, payouts => 2 calls
    # DB call order for non-empty rides: rides, payments(completed), refunds, tips, promos, payouts => 6 calls

    @pytest.mark.asyncio
    async def test_empty_period_returns_zeroed_summary(self):
        # rides=[], payouts=[]
        db = _make_db([], [])
        result = await get_financial_summary(db, _START, _END)
        assert result["ride_count"] == 0
        assert result["gross_platform_revenue"] == 0.0
        assert result["total_ride_fares"] == 0.0
        assert result["total_tips_collected"] == 0.0
        assert result["total_promo_discounts_applied"] == 0.0
        assert result["total_refunds_issued"] == 0.0
        assert result["total_driver_payouts"] == 0.0
        assert result["net_platform_revenue"] == 0.0
        assert result["active_drivers"] == 0
        assert result["active_riders"] == 0
        assert result["average_fare"] == 0.0
        assert result["daily_breakdown"] == []

    @pytest.mark.asyncio
    async def test_period_contains_start_and_end_dates(self):
        db = _make_db([], [])
        result = await get_financial_summary(db, _START, _END)
        assert result["period"]["start_date"] == _START.isoformat()
        assert result["period"]["end_date"] == _END.isoformat()

    @pytest.mark.asyncio
    async def test_ride_count_is_correct(self):
        rides = [_make_ride(ride_id=i) for i in range(4)]
        # rides, payments, refunds, tips, promos, payouts
        db = _make_db(rides, [], [], [], [], [])
        result = await get_financial_summary(db, _START, _END)
        assert result["ride_count"] == 4

    @pytest.mark.asyncio
    async def test_total_ride_fares_sums_actual_fare(self):
        rides = [
            _make_ride(ride_id=1, actual_fare=10.0),
            _make_ride(ride_id=2, actual_fare=20.0),
        ]
        db = _make_db(rides, [], [], [], [], [])
        result = await get_financial_summary(db, _START, _END)
        assert result["total_ride_fares"] == 30.0

    @pytest.mark.asyncio
    async def test_falls_back_to_estimated_fare(self):
        rides = [_make_ride(ride_id=1, actual_fare=None, estimated_fare=12.5)]
        db = _make_db(rides, [], [], [], [], [])
        result = await get_financial_summary(db, _START, _END)
        assert result["total_ride_fares"] == 12.5

    @pytest.mark.asyncio
    async def test_total_tips_collected(self):
        rides = [_make_ride(ride_id=1)]
        tips = [_make_tip(ride_id=1, amount_cents=500)]  # $5.00
        db = _make_db(rides, [], [], tips, [], [])
        result = await get_financial_summary(db, _START, _END)
        assert result["total_tips_collected"] == 5.0

    @pytest.mark.asyncio
    async def test_gross_platform_revenue_sums_platform_fees(self):
        rides = [_make_ride(ride_id=1)]
        payments = [_make_payment(ride_id=1, platform_fee=3.00)]
        db = _make_db(rides, payments, [], [], [], [])
        result = await get_financial_summary(db, _START, _END)
        assert result["gross_platform_revenue"] == 3.0

    @pytest.mark.asyncio
    async def test_total_refunds_issued_from_refunded_payments(self):
        rides = [_make_ride(ride_id=1)]
        refunds = [_make_payment(ride_id=1, amount=15.0, status=PaymentStatus.REFUNDED)]
        db = _make_db(rides, [], refunds, [], [], [])
        result = await get_financial_summary(db, _START, _END)
        assert result["total_refunds_issued"] == 15.0

    @pytest.mark.asyncio
    async def test_net_platform_revenue_equals_gross_minus_refunds(self):
        rides = [_make_ride(ride_id=1)]
        payments = [_make_payment(ride_id=1, platform_fee=4.0)]
        refunds = [_make_payment(ride_id=1, amount=2.0, status=PaymentStatus.REFUNDED)]
        db = _make_db(rides, payments, refunds, [], [], [])
        result = await get_financial_summary(db, _START, _END)
        assert result["gross_platform_revenue"] == 4.0
        assert result["total_refunds_issued"] == 2.0
        assert result["net_platform_revenue"] == 2.0

    @pytest.mark.asyncio
    async def test_zero_refunds_net_equals_gross(self):
        rides = [_make_ride(ride_id=1)]
        payments = [_make_payment(ride_id=1, platform_fee=5.0)]
        db = _make_db(rides, payments, [], [], [], [])
        result = await get_financial_summary(db, _START, _END)
        assert result["net_platform_revenue"] == result["gross_platform_revenue"]

    @pytest.mark.asyncio
    async def test_total_promo_discounts_from_redemptions(self):
        rides = [_make_ride(ride_id=1)]
        promos = [_make_promo_redemption(ride_id=1, discount_amount=3.0)]
        db = _make_db(rides, [], [], [], promos, [])
        result = await get_financial_summary(db, _START, _END)
        assert result["total_promo_discounts_applied"] == 3.0

    @pytest.mark.asyncio
    async def test_active_drivers_counts_unique_driver_ids(self):
        # ride 1 & 2 have same driver; ride 3 has different driver
        rides = [
            _make_ride(ride_id=1, driver_id=20),
            _make_ride(ride_id=2, driver_id=20),
            _make_ride(ride_id=3, driver_id=21),
        ]
        db = _make_db(rides, [], [], [], [], [])
        result = await get_financial_summary(db, _START, _END)
        assert result["active_drivers"] == 2

    @pytest.mark.asyncio
    async def test_active_riders_counts_unique_rider_ids(self):
        rides = [
            _make_ride(ride_id=1, rider_id=10),
            _make_ride(ride_id=2, rider_id=11),
            _make_ride(ride_id=3, rider_id=10),
        ]
        db = _make_db(rides, [], [], [], [], [])
        result = await get_financial_summary(db, _START, _END)
        assert result["active_riders"] == 2

    @pytest.mark.asyncio
    async def test_average_fare_is_mean(self):
        rides = [
            _make_ride(ride_id=1, actual_fare=10.0),
            _make_ride(ride_id=2, actual_fare=30.0),
        ]
        db = _make_db(rides, [], [], [], [], [])
        result = await get_financial_summary(db, _START, _END)
        assert result["average_fare"] == 20.0

    @pytest.mark.asyncio
    async def test_total_driver_payouts_sums_completed_payouts(self):
        rides = [_make_ride(ride_id=1)]
        payouts = [
            _make_payout(payout_id=1, total_amount=100.0),
            _make_payout(payout_id=2, total_amount=50.0),
        ]
        db = _make_db(rides, [], [], [], [], payouts)
        result = await get_financial_summary(db, _START, _END)
        assert result["total_driver_payouts"] == 150.0

    @pytest.mark.asyncio
    async def test_daily_breakdown_groups_by_date(self):
        day1 = datetime(2025, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        day2 = datetime(2025, 3, 2, 12, 0, 0, tzinfo=timezone.utc)
        rides = [
            _make_ride(ride_id=1, completed_at=day1),
            _make_ride(ride_id=2, completed_at=day1),
            _make_ride(ride_id=3, completed_at=day2),
        ]
        db = _make_db(rides, [], [], [], [], [])
        result = await get_financial_summary(db, _START, _END)
        breakdown = result["daily_breakdown"]
        assert len(breakdown) == 2
        assert breakdown[0]["date"] == "2025-03-01"
        assert breakdown[0]["ride_count"] == 2
        assert breakdown[1]["date"] == "2025-03-02"
        assert breakdown[1]["ride_count"] == 1

    @pytest.mark.asyncio
    async def test_daily_breakdown_sorted_ascending(self):
        day1 = datetime(2025, 3, 5, tzinfo=timezone.utc)
        day2 = datetime(2025, 3, 1, tzinfo=timezone.utc)
        rides = [
            _make_ride(ride_id=1, completed_at=day1),
            _make_ride(ride_id=2, completed_at=day2),
        ]
        db = _make_db(rides, [], [], [], [], [])
        result = await get_financial_summary(db, _START, _END)
        dates = [d["date"] for d in result["daily_breakdown"]]
        assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# Service unit tests — export_reconciliation_csv
# ---------------------------------------------------------------------------


class TestExportReconciliationCsv:
    # DB call order for empty rides: rides => 1 call
    # DB call order for non-empty rides: rides, payments, tips, promos => 4 calls

    @pytest.mark.asyncio
    async def test_header_row_present(self):
        db = _make_db([])
        csv_text = await export_reconciliation_csv(db, _START, _END)
        first_line = csv_text.splitlines()[0]
        assert "date" in first_line
        assert "ride_id" in first_line
        assert "rider_id" in first_line
        assert "driver_id" in first_line
        assert "fare" in first_line
        assert "tip" in first_line
        assert "platform_fee" in first_line
        assert "driver_payout" in first_line
        assert "refund_amount" in first_line
        assert "net_platform" in first_line

    @pytest.mark.asyncio
    async def test_empty_period_returns_header_only(self):
        db = _make_db([])
        csv_text = await export_reconciliation_csv(db, _START, _END)
        lines = [line for line in csv_text.splitlines() if line.strip()]
        assert len(lines) == 1

    @pytest.mark.asyncio
    async def test_correct_number_of_data_rows(self):
        rides = [_make_ride(ride_id=i) for i in range(3)]
        db = _make_db(rides, [], [], [])
        csv_text = await export_reconciliation_csv(db, _START, _END)
        lines = [line for line in csv_text.splitlines() if line.strip()]
        assert len(lines) == 4  # 1 header + 3 data rows

    @pytest.mark.asyncio
    async def test_row_contains_ride_id(self):
        rides = [_make_ride(ride_id=99, actual_fare=20.0)]
        payments = [_make_payment(ride_id=99, platform_fee=3.0, driver_payout=17.0)]
        db = _make_db(rides, payments, [], [])
        csv_text = await export_reconciliation_csv(db, _START, _END)
        data_line = csv_text.splitlines()[1]
        assert "99" in data_line

    @pytest.mark.asyncio
    async def test_net_platform_equals_fee_minus_refund(self):
        rides = [_make_ride(ride_id=1, actual_fare=20.0)]
        payments = [_make_payment(ride_id=1, platform_fee=4.0)]
        refund_payments = [_make_payment(ride_id=1, amount=2.0, status=PaymentStatus.REFUNDED)]
        # All payments query returns both; service separates by status
        all_payments = [payments[0], refund_payments[0]]
        db = _make_db(rides, all_payments, [], [])
        csv_text = await export_reconciliation_csv(db, _START, _END)
        data_line = csv_text.splitlines()[1]
        parts = data_line.split(",")
        # net_platform is the last column
        net = float(parts[-1].strip())
        assert net == 2.0  # 4.0 - 2.0

    @pytest.mark.asyncio
    async def test_refund_amount_is_zero_when_no_refund(self):
        rides = [_make_ride(ride_id=1, actual_fare=15.0)]
        payments = [_make_payment(ride_id=1, platform_fee=2.25)]
        db = _make_db(rides, payments, [], [])
        csv_text = await export_reconciliation_csv(db, _START, _END)
        data_line = csv_text.splitlines()[1]
        parts = data_line.split(",")
        # refund_amount is second-to-last column
        refund = float(parts[-2].strip())
        assert refund == 0.0

    @pytest.mark.asyncio
    async def test_driver_id_empty_when_none(self):
        rides = [_make_ride(ride_id=1, driver_id=None)]
        db = _make_db(rides, [], [], [])
        csv_text = await export_reconciliation_csv(db, _START, _END)
        data_line = csv_text.splitlines()[1]
        parts = data_line.split(",")
        # driver_id is the 4th column (index 3)
        assert parts[3].strip() == ""


# ---------------------------------------------------------------------------
# Service unit tests — get_payout_status
# ---------------------------------------------------------------------------


class TestGetPayoutStatus:
    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self):
        db = _make_db([])
        result = await get_payout_status(db, _START, _END)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_payout_records_with_required_fields(self):
        payouts = [_make_payout(payout_id=1, driver_id=20, total_amount=100.0, trip_count=5)]
        users = [_make_user(user_id=20, name="Alice Driver")]
        db = _make_db(payouts, users)
        result = await get_payout_status(db, _START, _END)
        assert len(result) == 1
        record = result[0]
        assert record["driver_id"] == 20
        assert record["payout_amount"] == 100.0
        assert record["ride_count_in_period"] == 5
        assert "status" in record
        assert "payout_date" in record

    @pytest.mark.asyncio
    async def test_driver_name_resolved(self):
        payouts = [_make_payout(driver_id=20)]
        users = [_make_user(user_id=20, name="Bob Driver")]
        db = _make_db(payouts, users)
        result = await get_payout_status(db, _START, _END)
        assert result[0]["driver_name"] == "Bob Driver"

    @pytest.mark.asyncio
    async def test_unknown_driver_shows_unknown(self):
        payouts = [_make_payout(driver_id=999)]
        users: list = []  # no user returned for driver 999
        db = _make_db(payouts, users)
        result = await get_payout_status(db, _START, _END)
        assert result[0]["driver_name"] == "Unknown"

    @pytest.mark.asyncio
    async def test_status_field_is_string_value(self):
        payouts = [_make_payout(status=PayoutStatus.PENDING)]
        users = [_make_user()]
        db = _make_db(payouts, users)
        result = await get_payout_status(db, _START, _END)
        assert result[0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_invalid_status_returns_empty_list(self):
        db = _make_db([])
        result = await get_payout_status(db, _START, _END, status="invalid_status")
        assert result == []


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------

BASE = "/api/v1/admin/financial-reconciliation"
VALID_DATES = "?start_date=2025-01-01&end_date=2025-12-31"


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
class TestFinancialSummaryEndpoint:
    async def test_no_auth_returns_401(self, client):
        resp = await client.get(f"{BASE}/summary{VALID_DATES}")
        assert resp.status_code == 401

    async def test_rider_token_returns_403(self, client, rider, rider_token):
        resp = await client.get(
            f"{BASE}/summary{VALID_DATES}",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_driver_token_returns_403(self, client, driver_user, driver_token):
        resp = await client.get(
            f"{BASE}/summary{VALID_DATES}",
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 403

    async def test_admin_token_returns_200(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/summary{VALID_DATES}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_response_contains_required_fields(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/summary{VALID_DATES}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "period" in data
        assert "gross_platform_revenue" in data
        assert "total_ride_fares" in data
        assert "total_tips_collected" in data
        assert "total_promo_discounts_applied" in data
        assert "total_refunds_issued" in data
        assert "total_driver_payouts" in data
        assert "net_platform_revenue" in data
        assert "ride_count" in data
        assert "active_drivers" in data
        assert "active_riders" in data
        assert "average_fare" in data
        assert "daily_breakdown" in data

    async def test_missing_start_date_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/summary?end_date=2025-12-31",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_missing_end_date_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/summary?start_date=2025-01-01",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_invalid_date_format_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/summary?start_date=01-01-2025&end_date=12-31-2025",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_end_before_start_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/summary?start_date=2025-12-01&end_date=2025-01-01",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_empty_period_returns_zero_ride_count(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/summary?start_date=2099-01-01&end_date=2099-12-31",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["ride_count"] == 0

    async def test_daily_breakdown_is_a_list(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/summary{VALID_DATES}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert isinstance(resp.json()["daily_breakdown"], list)

    async def test_ride_data_aggregated_correctly(
        self, client, db, admin_user, admin_token, rider, driver_user
    ):
        from geoalchemy2.functions import ST_MakePoint

        ride = Ride(
            rider_id=rider.id,
            driver_id=driver_user.id,
            status=RideStatus.COMPLETED,
            pickup_location=ST_MakePoint(-122.4194, 37.7749),
            dropoff_location=ST_MakePoint(-122.4094, 37.7849),
            pickup_address="A",
            dropoff_address="B",
            estimated_fare=20.0,
            actual_fare=20.0,
            completed_at=datetime(2025, 6, 15, tzinfo=timezone.utc),
            requested_at=datetime(2025, 6, 15, tzinfo=timezone.utc),
        )
        db.add(ride)
        await db.flush()

        resp = await client.get(
            f"{BASE}/summary?start_date=2025-06-01&end_date=2025-06-30",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ride_count"] >= 1
        assert data["total_ride_fares"] >= 20.0


@pytest.mark.anyio
class TestExportEndpoint:
    async def test_no_auth_returns_401(self, client):
        resp = await client.get(f"{BASE}/export{VALID_DATES}")
        assert resp.status_code == 401

    async def test_rider_token_returns_403(self, client, rider, rider_token):
        resp = await client.get(
            f"{BASE}/export{VALID_DATES}",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_admin_token_returns_csv(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export{VALID_DATES}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    async def test_csv_has_correct_header_columns(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export{VALID_DATES}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        first_line = resp.text.splitlines()[0]
        assert "ride_id" in first_line
        assert "rider_id" in first_line
        assert "driver_id" in first_line
        assert "fare" in first_line
        assert "platform_fee" in first_line
        assert "net_platform" in first_line

    async def test_missing_start_date_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export?end_date=2025-12-31",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_end_before_start_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export?start_date=2025-12-01&end_date=2025-01-01",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422


@pytest.mark.anyio
class TestPayoutStatusEndpoint:
    async def test_no_auth_returns_401(self, client):
        resp = await client.get(f"{BASE}/payout-status{VALID_DATES}")
        assert resp.status_code == 401

    async def test_rider_token_returns_403(self, client, rider, rider_token):
        resp = await client.get(
            f"{BASE}/payout-status{VALID_DATES}",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_admin_token_returns_200(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/payout-status{VALID_DATES}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_response_is_a_list(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/payout-status{VALID_DATES}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_invalid_status_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/payout-status{VALID_DATES}&status=bogus",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_valid_status_param_accepted(self, client, admin_user, admin_token):
        for status_val in ("pending", "completed", "failed", "processing"):
            resp = await client.get(
                f"{BASE}/payout-status{VALID_DATES}&status={status_val}",
                headers=auth_header(admin_token),
            )
            assert resp.status_code == 200, f"status={status_val} should return 200"
