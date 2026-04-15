"""Tests for the Corporate Data Export feature.

Service layer (async, mocked DB):
  1.  export_corporate_rides_csv — empty result returns header-only CSV
  2.  export_corporate_rides_csv — header contains all required columns in order
  3.  export_corporate_rides_csv — correct data row for a completed ride
  4.  export_corporate_rides_csv — rider_name and driver_name resolved from users
  5.  export_corporate_rides_csv — driver columns empty when driver_id is None
  6.  export_corporate_rides_csv — cost_center columns populated when tagged
  7.  export_corporate_rides_csv — cost_center columns empty when untagged
  8.  export_corporate_rides_csv — trip_purpose columns populated when tagged
  9.  export_corporate_rides_csv — trip_purpose columns empty when untagged
  10. export_corporate_rides_csv — total_charged = actual_fare + tip_amount
  11. export_corporate_rides_csv — not admin → 403
  12. export_corporate_rides_csv — end_date before start_date → 400
  13. export_corporate_rides_csv — multiple rides produce multiple rows
  14. export_corporate_rides_csv — completed_at column is ISO format
  15. export_corporate_rides_csv — distance and duration empty when None
  16. export_invoice_csv — empty result returns header-only CSV
  17. export_invoice_csv — header contains all required columns in order
  18. export_invoice_csv — invoice metadata propagated to every row
  19. export_invoice_csv — rider_name resolved from users table
  20. export_invoice_csv — cost_center and trip_purpose columns populated
  21. export_invoice_csv — not a member → 403
  22. export_invoice_csv — invoice not found → 404
  23. export_invoice_csv — multiple rides produce multiple rows

Internal helpers:
  24. _date_to_utc_start — converts date to midnight UTC
  25. _date_to_utc_end — converts date to 23:59:59 UTC

API layer (service functions patched):
  26. GET /corporate/accounts/me/export/rides — 200, text/csv
  27. GET /corporate/accounts/me/export/rides — no account → 404
  28. GET /corporate/accounts/me/export/invoices/{id} — 200, text/csv
  29. GET /corporate/accounts/me/export/invoices/{id} — no account → 404
  30. GET /admin/corporate/accounts/{id}/export/rides — 200, admin path
  31. GET /admin/corporate/accounts/{id}/export/invoices/{inv_id} — 200, admin path
  32. GET /corporate/accounts/me/export/rides — Content-Disposition header present
  33. GET /corporate/accounts/me/export/invoices/{id} — Content-Disposition header present
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_cost_center import CorporateCostCenter
from app.models.corporate_invoice import CorporateInvoice, InvoiceStatus
from app.models.corporate_trip_purpose import CorporateTripPurpose
from app.models.ride import Ride, RideStatus
from app.models.user import User
from app.services.corporate_data_export import (
    _INVOICE_CSV_COLUMNS,
    _RIDES_CSV_COLUMNS,
    _date_to_utc_end,
    _date_to_utc_start,
    export_corporate_rides_csv,
    export_invoice_csv,
)


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 10
USER_ID = 1
ADMIN_ID = 2
INVOICE_ID = 5
_DT_COMPLETED = datetime(2026, 4, 10, 14, 30, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers: model mocks
# ---------------------------------------------------------------------------


def _make_admin(account_id: int = ACCOUNT_ID, user_id: int = ADMIN_ID) -> MagicMock:
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = account_id
    m.user_id = user_id
    m.role = MemberRole.ADMIN
    m.is_active = True
    return m


def _make_member(account_id: int = ACCOUNT_ID, user_id: int = USER_ID) -> MagicMock:
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = account_id
    m.user_id = user_id
    m.role = MemberRole.MEMBER
    m.is_active = True
    return m


def _make_ride(
    ride_id: int = 1,
    rider_id: int = 100,
    driver_id: int | None = 200,
    status: RideStatus = RideStatus.COMPLETED,
    completed_at: datetime | None = None,
    actual_fare: float | None = 18.50,
    tip_amount: float = 2.00,
    distance_km: float | None = 7.2,
    duration_min: float | None = 15.5,
    pickup_address: str = "1 Pickup St",
    dropoff_address: str = "9 Dropoff Ave",
    cost_center_id: int | None = None,
    trip_purpose_id: int | None = None,
    trip_notes: str | None = None,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.completed_at = completed_at or _DT_COMPLETED
    ride.actual_fare = actual_fare
    ride.tip_amount = tip_amount
    ride.distance_km = distance_km
    ride.duration_min = duration_min
    ride.pickup_address = pickup_address
    ride.dropoff_address = dropoff_address
    ride.cost_center_id = cost_center_id
    ride.trip_purpose_id = trip_purpose_id
    ride.trip_notes = trip_notes
    return ride


def _make_user(user_id: int, name: str = "Test User") -> MagicMock:
    u = MagicMock(spec=User)
    u.id = user_id
    u.name = name
    return u


def _make_cost_center(cc_id: int = 30, code: str = "ENG", name: str = "Engineering") -> MagicMock:
    cc = MagicMock(spec=CorporateCostCenter)
    cc.id = cc_id
    cc.code = code
    cc.name = name
    return cc


def _make_trip_purpose(tp_id: int = 40, code: str = "CLIENT_MEETING", label: str = "Client Meeting") -> MagicMock:
    tp = MagicMock(spec=CorporateTripPurpose)
    tp.id = tp_id
    tp.code = code
    tp.label = label
    return tp


def _make_invoice(
    invoice_id: int = INVOICE_ID,
    account_id: int = ACCOUNT_ID,
    invoice_number: str = "INV-0010-202604",
    status: InvoiceStatus = InvoiceStatus.FINALIZED,
    period_start: date = date(2026, 4, 1),
    period_end: date = date(2026, 4, 30),
) -> MagicMock:
    inv = MagicMock(spec=CorporateInvoice)
    inv.id = invoice_id
    inv.account_id = account_id
    inv.invoice_number = invoice_number
    inv.status = status
    inv.period_start = period_start
    inv.period_end = period_end
    return inv


# ---------------------------------------------------------------------------
# Helpers: DB mock builders
# ---------------------------------------------------------------------------


def _scalar_result(value) -> MagicMock:
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    return res


def _scalars_result(values: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = list(values)
    res = MagicMock()
    res.scalars.return_value = scalars
    return res


def _parse_csv(text: str) -> tuple[list[str], list[list[str]]]:
    """Return (headers, data_rows) parsed from a CSV string."""
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


# ---------------------------------------------------------------------------
# 1. export_corporate_rides_csv — empty result returns header-only CSV
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_rides_csv_empty_returns_header_only():
    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_admin()),   # _require_account_admin
        _scalars_result([]),              # rides query
    ]
    csv_text = await export_corporate_rides_csv(db, ACCOUNT_ID, ADMIN_ID)
    headers, data = _parse_csv(csv_text)
    assert headers == _RIDES_CSV_COLUMNS
    assert data == []


# ---------------------------------------------------------------------------
# 2. export_corporate_rides_csv — header contains all required columns
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_rides_csv_header_columns_correct():
    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_admin()),
        _scalars_result([]),
    ]
    csv_text = await export_corporate_rides_csv(db, ACCOUNT_ID, ADMIN_ID)
    headers, _ = _parse_csv(csv_text)
    for col in _RIDES_CSV_COLUMNS:
        assert col in headers


# ---------------------------------------------------------------------------
# 3. export_corporate_rides_csv — correct data row for a completed ride
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_rides_csv_data_row_values():
    ride = _make_ride(ride_id=7, actual_fare=20.00, tip_amount=3.00)
    rider = _make_user(100, "Alice")
    driver = _make_user(200, "Bob")

    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_admin()),         # auth
        _scalars_result([ride]),               # rides
        _scalars_result([rider, driver]),      # users
        _scalars_result([]),                   # cost centers
        _scalars_result([]),                   # trip purposes
    ]

    csv_text = await export_corporate_rides_csv(db, ACCOUNT_ID, ADMIN_ID)
    headers, rows = _parse_csv(csv_text)
    assert len(rows) == 1
    row = dict(zip(headers, rows[0]))

    assert row["ride_id"] == "7"
    assert row["actual_fare"] == "20.0"
    assert row["tip_amount"] == "3.0"
    assert row["total_charged"] == "23.0"
    assert row["status"] == RideStatus.COMPLETED.value


# ---------------------------------------------------------------------------
# 4. export_corporate_rides_csv — rider and driver names resolved
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_rides_csv_names_resolved():
    ride = _make_ride(rider_id=100, driver_id=200)
    rider = _make_user(100, "Alice Rider")
    driver = _make_user(200, "Bob Driver")

    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_admin()),
        _scalars_result([ride]),
        _scalars_result([rider, driver]),
        _scalars_result([]),
        _scalars_result([]),
    ]

    csv_text = await export_corporate_rides_csv(db, ACCOUNT_ID, ADMIN_ID)
    headers, rows = _parse_csv(csv_text)
    row = dict(zip(headers, rows[0]))
    assert row["rider_name"] == "Alice Rider"
    assert row["driver_name"] == "Bob Driver"


# ---------------------------------------------------------------------------
# 5. export_corporate_rides_csv — driver columns empty when driver_id None
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_rides_csv_no_driver_columns_empty():
    ride = _make_ride(driver_id=None)

    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_admin()),
        _scalars_result([ride]),
        _scalars_result([_make_user(100)]),
        _scalars_result([]),
        _scalars_result([]),
    ]

    csv_text = await export_corporate_rides_csv(db, ACCOUNT_ID, ADMIN_ID)
    headers, rows = _parse_csv(csv_text)
    row = dict(zip(headers, rows[0]))
    assert row["driver_id"] == ""
    assert row["driver_name"] == ""


# ---------------------------------------------------------------------------
# 6. export_corporate_rides_csv — cost_center columns populated when tagged
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_rides_csv_cost_center_populated():
    ride = _make_ride(cost_center_id=30)
    cc = _make_cost_center(cc_id=30, code="ENG", name="Engineering")

    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_admin()),
        _scalars_result([ride]),
        _scalars_result([_make_user(100)]),
        _scalars_result([cc]),
        _scalars_result([]),
    ]

    csv_text = await export_corporate_rides_csv(db, ACCOUNT_ID, ADMIN_ID)
    headers, rows = _parse_csv(csv_text)
    row = dict(zip(headers, rows[0]))
    assert row["cost_center_code"] == "ENG"
    assert row["cost_center_name"] == "Engineering"


# ---------------------------------------------------------------------------
# 7. export_corporate_rides_csv — cost_center columns empty when untagged
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_rides_csv_no_cost_center_empty():
    ride = _make_ride(cost_center_id=None)

    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_admin()),
        _scalars_result([ride]),
        _scalars_result([_make_user(100)]),
        _scalars_result([]),
    ]

    csv_text = await export_corporate_rides_csv(db, ACCOUNT_ID, ADMIN_ID)
    headers, rows = _parse_csv(csv_text)
    row = dict(zip(headers, rows[0]))
    assert row["cost_center_code"] == ""
    assert row["cost_center_name"] == ""


# ---------------------------------------------------------------------------
# 8. export_corporate_rides_csv — trip_purpose columns populated
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_rides_csv_trip_purpose_populated():
    # cost_center_id=None — no cost-center batch query is issued
    ride = _make_ride(cost_center_id=None, trip_purpose_id=40, trip_notes="Quarterly review")
    tp = _make_trip_purpose(tp_id=40, code="CLIENT_MEETING", label="Client Meeting")

    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_admin()),
        _scalars_result([ride]),
        _scalars_result([_make_user(100)]),
        # cc_ids is empty → no cost-center query
        _scalars_result([tp]),            # trip purposes
    ]

    csv_text = await export_corporate_rides_csv(db, ACCOUNT_ID, ADMIN_ID)
    headers, rows = _parse_csv(csv_text)
    row = dict(zip(headers, rows[0]))
    assert row["trip_purpose_code"] == "CLIENT_MEETING"
    assert row["trip_purpose_label"] == "Client Meeting"
    assert row["trip_notes"] == "Quarterly review"


# ---------------------------------------------------------------------------
# 9. export_corporate_rides_csv — trip_purpose columns empty when untagged
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_rides_csv_no_trip_purpose_empty():
    ride = _make_ride(trip_purpose_id=None, trip_notes=None)

    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_admin()),
        _scalars_result([ride]),
        _scalars_result([_make_user(100)]),
        _scalars_result([]),
    ]

    csv_text = await export_corporate_rides_csv(db, ACCOUNT_ID, ADMIN_ID)
    headers, rows = _parse_csv(csv_text)
    row = dict(zip(headers, rows[0]))
    assert row["trip_purpose_code"] == ""
    assert row["trip_purpose_label"] == ""
    assert row["trip_notes"] == ""


# ---------------------------------------------------------------------------
# 10. export_corporate_rides_csv — total_charged = actual_fare + tip
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_rides_csv_total_charged_is_sum():
    ride = _make_ride(actual_fare=25.75, tip_amount=4.25)

    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_admin()),
        _scalars_result([ride]),
        _scalars_result([_make_user(100)]),
        _scalars_result([]),
        _scalars_result([]),
    ]

    csv_text = await export_corporate_rides_csv(db, ACCOUNT_ID, ADMIN_ID)
    headers, rows = _parse_csv(csv_text)
    row = dict(zip(headers, rows[0]))
    assert float(row["total_charged"]) == pytest.approx(30.00)


# ---------------------------------------------------------------------------
# 11. export_corporate_rides_csv — not admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_rides_csv_not_admin_raises_403():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)   # no admin row found

    with pytest.raises(HTTPException) as exc_info:
        await export_corporate_rides_csv(db, ACCOUNT_ID, USER_ID)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 12. export_corporate_rides_csv — end_date before start_date → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_rides_csv_invalid_date_range_raises_400():
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await export_corporate_rides_csv(
            db, ACCOUNT_ID, ADMIN_ID,
            start_date=date(2026, 4, 30),
            end_date=date(2026, 4, 1),
        )
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 13. export_corporate_rides_csv — multiple rides produce multiple rows
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_rides_csv_multiple_rides():
    rides = [_make_ride(ride_id=i, rider_id=100) for i in range(1, 4)]

    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_admin()),
        _scalars_result(rides),
        _scalars_result([_make_user(100)]),
        _scalars_result([]),
        _scalars_result([]),
    ]

    csv_text = await export_corporate_rides_csv(db, ACCOUNT_ID, ADMIN_ID)
    _, rows = _parse_csv(csv_text)
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# 14. export_corporate_rides_csv — completed_at is ISO format
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_rides_csv_completed_at_iso():
    dt = datetime(2026, 4, 10, 14, 30, 0, tzinfo=timezone.utc)
    ride = _make_ride(completed_at=dt)

    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_admin()),
        _scalars_result([ride]),
        _scalars_result([_make_user(100)]),
        _scalars_result([]),
        _scalars_result([]),
    ]

    csv_text = await export_corporate_rides_csv(db, ACCOUNT_ID, ADMIN_ID)
    headers, rows = _parse_csv(csv_text)
    row = dict(zip(headers, rows[0]))
    parsed = datetime.fromisoformat(row["completed_at"])
    assert parsed.year == 2026
    assert parsed.month == 4
    assert parsed.day == 10


# ---------------------------------------------------------------------------
# 15. export_corporate_rides_csv — distance and duration empty when None
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_rides_csv_none_distance_duration_empty():
    ride = _make_ride(distance_km=None, duration_min=None)

    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_admin()),
        _scalars_result([ride]),
        _scalars_result([_make_user(100)]),
        _scalars_result([]),
        _scalars_result([]),
    ]

    csv_text = await export_corporate_rides_csv(db, ACCOUNT_ID, ADMIN_ID)
    headers, rows = _parse_csv(csv_text)
    row = dict(zip(headers, rows[0]))
    assert row["distance_km"] == ""
    assert row["duration_min"] == ""


# ---------------------------------------------------------------------------
# 16. export_invoice_csv — empty result returns header-only CSV
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_invoice_csv_empty_returns_header_only():
    invoice = _make_invoice()

    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_member()),   # _require_account_member
        _scalar_result(invoice),          # invoice lookup
        _scalars_result([]),              # rides
    ]

    csv_text = await export_invoice_csv(db, INVOICE_ID, ACCOUNT_ID, USER_ID)
    headers, data = _parse_csv(csv_text)
    assert headers == _INVOICE_CSV_COLUMNS
    assert data == []


# ---------------------------------------------------------------------------
# 17. export_invoice_csv — header contains all required columns
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_invoice_csv_header_columns_correct():
    invoice = _make_invoice()

    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_member()),
        _scalar_result(invoice),
        _scalars_result([]),
    ]

    csv_text = await export_invoice_csv(db, INVOICE_ID, ACCOUNT_ID, USER_ID)
    headers, _ = _parse_csv(csv_text)
    for col in _INVOICE_CSV_COLUMNS:
        assert col in headers


# ---------------------------------------------------------------------------
# 18. export_invoice_csv — invoice metadata propagated to every row
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_invoice_csv_metadata_in_every_row():
    invoice = _make_invoice(
        invoice_number="INV-0010-202604",
        status=InvoiceStatus.FINALIZED,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )
    rides = [_make_ride(ride_id=i) for i in range(1, 3)]

    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_member()),
        _scalar_result(invoice),
        _scalars_result(rides),
        _scalars_result([_make_user(100)]),
        _scalars_result([]),
        _scalars_result([]),
    ]

    csv_text = await export_invoice_csv(db, INVOICE_ID, ACCOUNT_ID, USER_ID)
    headers, rows = _parse_csv(csv_text)
    for row_vals in rows:
        row = dict(zip(headers, row_vals))
        assert row["invoice_number"] == "INV-0010-202604"
        assert row["invoice_status"] == InvoiceStatus.FINALIZED.value
        assert row["period_start"] == "2026-04-01"
        assert row["period_end"] == "2026-04-30"


# ---------------------------------------------------------------------------
# 19. export_invoice_csv — rider_name resolved from users table
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_invoice_csv_rider_name_resolved():
    invoice = _make_invoice()
    ride = _make_ride(rider_id=100)
    rider = _make_user(100, "Carol Rider")

    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_member()),
        _scalar_result(invoice),
        _scalars_result([ride]),
        _scalars_result([rider]),
        _scalars_result([]),
        _scalars_result([]),
    ]

    csv_text = await export_invoice_csv(db, INVOICE_ID, ACCOUNT_ID, USER_ID)
    headers, rows = _parse_csv(csv_text)
    row = dict(zip(headers, rows[0]))
    assert row["rider_name"] == "Carol Rider"


# ---------------------------------------------------------------------------
# 20. export_invoice_csv — cost_center and trip_purpose columns populated
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_invoice_csv_tags_populated():
    invoice = _make_invoice()
    ride = _make_ride(cost_center_id=30, trip_purpose_id=40, trip_notes="Note")
    cc = _make_cost_center(cc_id=30, code="SALES", name="Sales")
    tp = _make_trip_purpose(tp_id=40, code="CONFERENCE", label="Conference")

    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_member()),
        _scalar_result(invoice),
        _scalars_result([ride]),
        _scalars_result([_make_user(100)]),
        _scalars_result([cc]),
        _scalars_result([tp]),
    ]

    csv_text = await export_invoice_csv(db, INVOICE_ID, ACCOUNT_ID, USER_ID)
    headers, rows = _parse_csv(csv_text)
    row = dict(zip(headers, rows[0]))
    assert row["cost_center_code"] == "SALES"
    assert row["cost_center_name"] == "Sales"
    assert row["trip_purpose_code"] == "CONFERENCE"
    assert row["trip_purpose_label"] == "Conference"
    assert row["trip_notes"] == "Note"


# ---------------------------------------------------------------------------
# 21. export_invoice_csv — not a member → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_invoice_csv_not_member_raises_403():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await export_invoice_csv(db, INVOICE_ID, ACCOUNT_ID, 99)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 22. export_invoice_csv — invoice not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_invoice_csv_not_found_raises_404():
    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_member()),
        _scalar_result(None),             # invoice not found
    ]

    with pytest.raises(HTTPException) as exc_info:
        await export_invoice_csv(db, 999, ACCOUNT_ID, USER_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 23. export_invoice_csv — multiple rides produce multiple rows
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_invoice_csv_multiple_rides():
    invoice = _make_invoice()
    rides = [_make_ride(ride_id=i, rider_id=100) for i in range(1, 5)]

    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_make_member()),
        _scalar_result(invoice),
        _scalars_result(rides),
        _scalars_result([_make_user(100)]),
        _scalars_result([]),
        _scalars_result([]),
    ]

    csv_text = await export_invoice_csv(db, INVOICE_ID, ACCOUNT_ID, USER_ID)
    _, rows = _parse_csv(csv_text)
    assert len(rows) == 4


# ---------------------------------------------------------------------------
# 24. _date_to_utc_start — midnight UTC
# ---------------------------------------------------------------------------


def test_date_to_utc_start_is_midnight():
    d = date(2026, 4, 10)
    result = _date_to_utc_start(d)
    assert result == datetime(2026, 4, 10, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 25. _date_to_utc_end — 23:59:59 UTC
# ---------------------------------------------------------------------------


def test_date_to_utc_end_is_end_of_day():
    d = date(2026, 4, 10)
    result = _date_to_utc_end(d)
    assert result == datetime(2026, 4, 10, 23, 59, 59, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# API layer — service functions patched
# ---------------------------------------------------------------------------

_MEMBER_ENDPOINT_RIDES = "/api/v1/corporate/accounts/me/export/rides"
_MEMBER_ENDPOINT_INVOICE = "/api/v1/corporate/accounts/me/export/invoices/5"
_ADMIN_ENDPOINT_RIDES = "/api/v1/admin/corporate/accounts/10/export/rides"
_ADMIN_ENDPOINT_INVOICE = "/api/v1/admin/corporate/accounts/10/export/invoices/5"

_CSV_HEADER = "ride_id,completed_at\r\n"
_INVOICE_HEADER = "invoice_number,invoice_status\r\n"


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 26. GET /corporate/accounts/me/export/rides — 200, text/csv
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_export_rides_returns_200_csv(client, rider, rider_token):
    with (
        patch(
            "app.api.v1.corporate_data_export._resolve_account_id",
            return_value=ACCOUNT_ID,
        ),
        patch(
            "app.api.v1.corporate_data_export.export_corporate_rides_csv",
            return_value=_CSV_HEADER,
        ),
    ):
        resp = await client.get(
            _MEMBER_ENDPOINT_RIDES,
            headers=auth_header(rider_token),
        )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# 27. GET /corporate/accounts/me/export/rides — no account → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_export_rides_no_account_returns_404(client, rider, rider_token):
    with patch(
        "app.api.v1.corporate_data_export._resolve_account_id",
        side_effect=HTTPException(status_code=404, detail="no account"),
    ):
        resp = await client.get(
            _MEMBER_ENDPOINT_RIDES,
            headers=auth_header(rider_token),
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 28. GET /corporate/accounts/me/export/invoices/{id} — 200, text/csv
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_export_invoice_returns_200_csv(client, rider, rider_token):
    with (
        patch(
            "app.api.v1.corporate_data_export._resolve_account_id",
            return_value=ACCOUNT_ID,
        ),
        patch(
            "app.api.v1.corporate_data_export.export_invoice_csv",
            return_value=_INVOICE_HEADER,
        ),
    ):
        resp = await client.get(
            _MEMBER_ENDPOINT_INVOICE,
            headers=auth_header(rider_token),
        )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# 29. GET /corporate/accounts/me/export/invoices/{id} — no account → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_export_invoice_no_account_returns_404(client, rider, rider_token):
    with patch(
        "app.api.v1.corporate_data_export._resolve_account_id",
        side_effect=HTTPException(status_code=404, detail="no account"),
    ):
        resp = await client.get(
            _MEMBER_ENDPOINT_INVOICE,
            headers=auth_header(rider_token),
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 30. GET /admin/corporate/accounts/{id}/export/rides — 200, admin path
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_admin_export_rides_returns_200(client, admin_user, admin_token):
    with patch(
        "app.api.v1.corporate_data_export.export_corporate_rides_csv",
        return_value=_CSV_HEADER,
    ):
        resp = await client.get(
            _ADMIN_ENDPOINT_RIDES,
            headers=auth_header(admin_token),
        )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# 31. GET /admin/corporate/accounts/{id}/export/invoices/{inv_id} — 200
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_admin_export_invoice_returns_200(client, admin_user, admin_token):
    with patch(
        "app.api.v1.corporate_data_export.export_invoice_csv",
        return_value=_INVOICE_HEADER,
    ):
        resp = await client.get(
            _ADMIN_ENDPOINT_INVOICE,
            headers=auth_header(admin_token),
        )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# 32. Rides endpoint — Content-Disposition header present
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_export_rides_content_disposition_present(client, rider, rider_token):
    with (
        patch(
            "app.api.v1.corporate_data_export._resolve_account_id",
            return_value=ACCOUNT_ID,
        ),
        patch(
            "app.api.v1.corporate_data_export.export_corporate_rides_csv",
            return_value=_CSV_HEADER,
        ),
    ):
        resp = await client.get(
            _MEMBER_ENDPOINT_RIDES,
            headers=auth_header(rider_token),
        )
    assert "content-disposition" in resp.headers
    assert "attachment" in resp.headers["content-disposition"]


# ---------------------------------------------------------------------------
# 33. Invoice endpoint — Content-Disposition header present
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_export_invoice_content_disposition_present(client, rider, rider_token):
    with (
        patch(
            "app.api.v1.corporate_data_export._resolve_account_id",
            return_value=ACCOUNT_ID,
        ),
        patch(
            "app.api.v1.corporate_data_export.export_invoice_csv",
            return_value=_INVOICE_HEADER,
        ),
    ):
        resp = await client.get(
            _MEMBER_ENDPOINT_INVOICE,
            headers=auth_header(rider_token),
        )
    assert "content-disposition" in resp.headers
    assert "attachment" in resp.headers["content-disposition"]
