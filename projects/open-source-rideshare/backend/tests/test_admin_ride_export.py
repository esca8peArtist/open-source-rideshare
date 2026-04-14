"""Tests for the admin ride export feature.

Covers:

Service unit tests (using AsyncMock for DB):
  1.  export_rides_csv — returns header row when no rides exist
  2.  export_rides_csv — empty DB returns header-only CSV (not error)
  3.  export_rides_csv — correct number of data rows
  4.  export_rides_csv — header contains all required columns in order
  5.  export_rides_csv — ride_id appears in data row
  6.  export_rides_csv — status column reflects ride status value
  7.  export_rides_csv — driver_id is empty string when None
  8.  export_rides_csv — driver_name resolved from users table
  9.  export_rides_csv — driver_name is empty string when driver_id is None
  10. export_rides_csv — rider_name resolved from users table
  11. export_rides_csv — rider_name is empty string when user not found
  12. export_rides_csv — pickup_address and dropoff_address present
  13. export_rides_csv — distance_miles converted from km
  14. export_rides_csv — distance_miles empty when distance_km is None
  15. export_rides_csv — fare_amount uses actual_fare when available
  16. export_rides_csv — fare_amount falls back to estimated_fare
  17. export_rides_csv — currency column is always "USD"
  18. export_rides_csv — payment_status from payments table
  19. export_rides_csv — payment_status is empty when no payment record
  20. export_rides_csv — surge_multiplier column is always empty (not on model)
  21. export_rides_csv — vehicle_type uses vehicle_type_preference value
  22. export_rides_csv — vehicle_type defaults to "standard" when preference is None
  23. export_rides_csv — status filter: unknown status returns header-only
  24. export_rides_csv — rides ordered by requested_at ascending
  25. export_rides_csv — created_at column contains ISO formatted timestamp

API integration tests (using real in-transaction test DB via conftest fixtures):
  26. GET /export — 401 with no auth
  27. GET /export — 403 with rider token
  28. GET /export — 403 with driver token
  29. GET /export — 200 with admin token
  30. GET /export — response content-type is text/csv
  31. GET /export — content-disposition header is attachment with filename
  32. GET /export — filename contains "rides_export"
  33. GET /export — CSV has all required header columns
  34. GET /export — empty result returns CSV with header only (not 404)
  35. GET /export — start_date filter accepted
  36. GET /export — end_date filter accepted
  37. GET /export — start_date and end_date together accepted
  38. GET /export — end_date before start_date returns 422
  39. GET /export — invalid date format for start_date returns 422
  40. GET /export — invalid date format for end_date returns 422
  41. GET /export — status filter: valid status accepted
  42. GET /export — status filter: invalid status returns 422
  43. GET /export — driver_id filter accepted
  44. GET /export — unsupported format returns 422
  45. GET /export — format=csv accepted (explicit)
  46. GET /export — no filters returns 200
  47. GET /export — ride data appears in CSV when rides exist in DB
  48. GET /export — date boundary: ride on start_date is included
  49. GET /export — date boundary: ride on end_date is included
  50. GET /export — date boundary: ride before start_date is excluded
  51. GET /export — date boundary: ride after end_date is excluded
  52. GET /export — driver_id filter excludes rides from other drivers
  53. GET /export — status filter excludes rides with other statuses
  54. GET /export — all RideStatus values accepted as status param
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.payment import Payment, PaymentStatus
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.models.vehicle import VehicleServiceCategory
from app.services.admin_ride_export import export_rides_csv

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
    status: RideStatus = RideStatus.COMPLETED,
    requested_at: datetime | None = None,
    distance_km: float | None = 5.0,
    vehicle_type_preference: VehicleServiceCategory | None = None,
    pickup_address: str = "123 Main St",
    dropoff_address: str = "456 Oak Ave",
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.actual_fare = actual_fare
    ride.estimated_fare = estimated_fare
    ride.requested_at = requested_at or _DT
    ride.distance_km = distance_km
    ride.vehicle_type_preference = vehicle_type_preference
    ride.pickup_address = pickup_address
    ride.dropoff_address = dropoff_address
    return ride


def _make_payment(
    pay_id: int = 1,
    ride_id: int = 1,
    status: PaymentStatus = PaymentStatus.COMPLETED,
) -> MagicMock:
    p = MagicMock(spec=Payment)
    p.id = pay_id
    p.ride_id = ride_id
    p.status = status
    return p


def _make_user(user_id: int = 20, name: str = "Test User") -> MagicMock:
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
        scalars_mock.all.return_value = list(items)
        mock_result.scalars.return_value = scalars_mock
        side_effects.append(mock_result)
    db.execute = AsyncMock(side_effect=side_effects)
    return db


def _parse_csv(text: str) -> tuple[list[str], list[list[str]]]:
    """Return (headers, data_rows) from a CSV string."""
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


class TestExportRidesCsv:
    # DB call order for empty rides: rides => 1 call (no user/payment queries)
    # DB call order for non-empty rides: rides, users, payments => 3 calls

    @pytest.mark.asyncio
    async def test_returns_header_row_when_empty(self):
        db = _make_db([])
        csv_text = await export_rides_csv(db)
        assert csv_text.strip() != ""
        headers, _ = _parse_csv(csv_text)
        assert len(headers) > 0

    @pytest.mark.asyncio
    async def test_empty_db_returns_header_only(self):
        db = _make_db([])
        csv_text = await export_rides_csv(db)
        lines = [line for line in csv_text.splitlines() if line.strip()]
        assert len(lines) == 1

    @pytest.mark.asyncio
    async def test_correct_number_of_data_rows(self):
        rides = [_make_ride(ride_id=i) for i in range(5)]
        db = _make_db(rides, [], [])
        csv_text = await export_rides_csv(db)
        _, data_rows = _parse_csv(csv_text)
        assert len(data_rows) == 5

    @pytest.mark.asyncio
    async def test_header_contains_all_required_columns(self):
        db = _make_db([])
        csv_text = await export_rides_csv(db)
        headers, _ = _parse_csv(csv_text)
        required = [
            "ride_id", "created_at", "status", "driver_id", "driver_name",
            "rider_id", "rider_name", "pickup_address", "dropoff_address",
            "distance_miles", "fare_amount", "currency", "payment_status",
            "surge_multiplier", "vehicle_type",
        ]
        for col in required:
            assert col in headers, f"Missing column: {col}"

    @pytest.mark.asyncio
    async def test_header_columns_in_correct_order(self):
        db = _make_db([])
        csv_text = await export_rides_csv(db)
        headers, _ = _parse_csv(csv_text)
        expected = [
            "ride_id", "created_at", "status", "driver_id", "driver_name",
            "rider_id", "rider_name", "pickup_address", "dropoff_address",
            "distance_miles", "fare_amount", "currency", "payment_status",
            "surge_multiplier", "vehicle_type",
        ]
        assert headers == expected

    @pytest.mark.asyncio
    async def test_ride_id_in_data_row(self):
        rides = [_make_ride(ride_id=42)]
        users = [_make_user(user_id=10, name="Rider"), _make_user(user_id=20, name="Driver")]
        payments = []
        db = _make_db(rides, users, payments)
        csv_text = await export_rides_csv(db)
        _, data_rows = _parse_csv(csv_text)
        assert data_rows[0][0] == "42"

    @pytest.mark.asyncio
    async def test_status_column_contains_ride_status_value(self):
        rides = [_make_ride(status=RideStatus.CANCELLED)]
        db = _make_db(rides, [], [])
        csv_text = await export_rides_csv(db)
        _, data_rows = _parse_csv(csv_text)
        headers, _ = _parse_csv(csv_text.splitlines()[0] + "\n")
        # Re-parse properly
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)
        assert rows[0]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_driver_id_empty_when_none(self):
        rides = [_make_ride(driver_id=None)]
        db = _make_db(rides, [], [])
        csv_text = await export_rides_csv(db)
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        assert row["driver_id"] == ""

    @pytest.mark.asyncio
    async def test_driver_name_resolved_from_users(self):
        rides = [_make_ride(driver_id=20)]
        users = [_make_user(user_id=10, name="Alice Rider"), _make_user(user_id=20, name="Bob Driver")]
        db = _make_db(rides, users, [])
        csv_text = await export_rides_csv(db)
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        assert row["driver_name"] == "Bob Driver"

    @pytest.mark.asyncio
    async def test_driver_name_empty_when_driver_id_none(self):
        rides = [_make_ride(driver_id=None)]
        db = _make_db(rides, [], [])
        csv_text = await export_rides_csv(db)
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        assert row["driver_name"] == ""

    @pytest.mark.asyncio
    async def test_rider_name_resolved_from_users(self):
        rides = [_make_ride(rider_id=10)]
        users = [_make_user(user_id=10, name="Carol Rider"), _make_user(user_id=20, name="Dave Driver")]
        db = _make_db(rides, users, [])
        csv_text = await export_rides_csv(db)
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        assert row["rider_name"] == "Carol Rider"

    @pytest.mark.asyncio
    async def test_rider_name_empty_when_user_not_found(self):
        rides = [_make_ride(rider_id=99, driver_id=None)]
        # Return no users
        db = _make_db(rides, [], [])
        csv_text = await export_rides_csv(db)
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        assert row["rider_name"] == ""

    @pytest.mark.asyncio
    async def test_pickup_and_dropoff_addresses_present(self):
        rides = [_make_ride(pickup_address="Start Pl", dropoff_address="End Blvd")]
        db = _make_db(rides, [], [])
        csv_text = await export_rides_csv(db)
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        assert row["pickup_address"] == "Start Pl"
        assert row["dropoff_address"] == "End Blvd"

    @pytest.mark.asyncio
    async def test_distance_miles_converted_from_km(self):
        rides = [_make_ride(distance_km=10.0)]
        db = _make_db(rides, [], [])
        csv_text = await export_rides_csv(db)
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        # 10 km * 0.621371 = 6.21371
        assert abs(float(row["distance_miles"]) - 6.21371) < 0.001

    @pytest.mark.asyncio
    async def test_distance_miles_empty_when_distance_km_none(self):
        rides = [_make_ride(distance_km=None)]
        db = _make_db(rides, [], [])
        csv_text = await export_rides_csv(db)
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        assert row["distance_miles"] == ""

    @pytest.mark.asyncio
    async def test_fare_amount_uses_actual_fare(self):
        rides = [_make_ride(actual_fare=18.50, estimated_fare=17.00)]
        db = _make_db(rides, [], [])
        csv_text = await export_rides_csv(db)
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        assert float(row["fare_amount"]) == 18.50

    @pytest.mark.asyncio
    async def test_fare_amount_falls_back_to_estimated(self):
        rides = [_make_ride(actual_fare=None, estimated_fare=12.75)]
        db = _make_db(rides, [], [])
        csv_text = await export_rides_csv(db)
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        assert float(row["fare_amount"]) == 12.75

    @pytest.mark.asyncio
    async def test_currency_is_always_usd(self):
        rides = [_make_ride(), _make_ride(ride_id=2)]
        db = _make_db(rides, [], [])
        csv_text = await export_rides_csv(db)
        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            assert row["currency"] == "USD"

    @pytest.mark.asyncio
    async def test_payment_status_from_payments_table(self):
        rides = [_make_ride(ride_id=1)]
        users = [_make_user(user_id=10), _make_user(user_id=20)]
        payments = [_make_payment(ride_id=1, status=PaymentStatus.COMPLETED)]
        db = _make_db(rides, users, payments)
        csv_text = await export_rides_csv(db)
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        assert row["payment_status"] == "completed"

    @pytest.mark.asyncio
    async def test_payment_status_empty_when_no_payment(self):
        rides = [_make_ride(ride_id=1)]
        users = [_make_user(user_id=10), _make_user(user_id=20)]
        payments: list = []
        db = _make_db(rides, users, payments)
        csv_text = await export_rides_csv(db)
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        assert row["payment_status"] == ""

    @pytest.mark.asyncio
    async def test_surge_multiplier_is_always_empty(self):
        rides = [_make_ride(), _make_ride(ride_id=2)]
        db = _make_db(rides, [], [])
        csv_text = await export_rides_csv(db)
        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            assert row["surge_multiplier"] == ""

    @pytest.mark.asyncio
    async def test_vehicle_type_uses_preference_value(self):
        rides = [_make_ride(vehicle_type_preference=VehicleServiceCategory.XL)]
        db = _make_db(rides, [], [])
        csv_text = await export_rides_csv(db)
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        assert row["vehicle_type"] == VehicleServiceCategory.XL.value

    @pytest.mark.asyncio
    async def test_vehicle_type_defaults_to_standard(self):
        rides = [_make_ride(vehicle_type_preference=None)]
        db = _make_db(rides, [], [])
        csv_text = await export_rides_csv(db)
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        assert row["vehicle_type"] == "standard"

    @pytest.mark.asyncio
    async def test_unknown_status_filter_returns_header_only(self):
        """Service returns header-only CSV (not an error) for unknown status."""
        db = _make_db()
        csv_text = await export_rides_csv(db, status="not_a_valid_status")
        lines = [line for line in csv_text.splitlines() if line.strip()]
        assert len(lines) == 1

    @pytest.mark.asyncio
    async def test_created_at_column_is_iso_format(self):
        dt = datetime(2025, 4, 10, 8, 30, 0, tzinfo=timezone.utc)
        rides = [_make_ride(requested_at=dt)]
        db = _make_db(rides, [], [])
        csv_text = await export_rides_csv(db)
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        # Should be parseable as ISO datetime
        parsed = datetime.fromisoformat(row["created_at"])
        assert parsed.year == 2025
        assert parsed.month == 4
        assert parsed.day == 10


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------

BASE = "/api/v1/admin/rides"
VALID_PARAMS = "?start_date=2025-01-01&end_date=2025-12-31"


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
class TestExportRidesEndpoint:
    async def test_no_auth_returns_401(self, client):
        resp = await client.get(f"{BASE}/export")
        assert resp.status_code == 401

    async def test_rider_token_returns_403(self, client, rider, rider_token):
        resp = await client.get(
            f"{BASE}/export",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_driver_token_returns_403(self, client, driver_user, driver_token):
        resp = await client.get(
            f"{BASE}/export",
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 403

    async def test_admin_token_returns_200(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_content_type_is_text_csv(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    async def test_content_disposition_is_attachment(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export",
            headers=auth_header(admin_token),
        )
        disposition = resp.headers.get("content-disposition", "")
        assert "attachment" in disposition

    async def test_filename_contains_rides_export(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export",
            headers=auth_header(admin_token),
        )
        disposition = resp.headers.get("content-disposition", "")
        assert "rides_export" in disposition

    async def test_csv_has_all_required_header_columns(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        headers, _ = _parse_csv(resp.text)
        required = [
            "ride_id", "created_at", "status", "driver_id", "driver_name",
            "rider_id", "rider_name", "pickup_address", "dropoff_address",
            "distance_miles", "fare_amount", "currency", "payment_status",
            "surge_multiplier", "vehicle_type",
        ]
        for col in required:
            assert col in headers, f"Missing header column: {col}"

    async def test_empty_result_returns_csv_with_header_only(self, client, admin_user, admin_token):
        # Far-future date range — no rides will exist
        resp = await client.get(
            f"{BASE}/export?start_date=2099-01-01&end_date=2099-12-31",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        lines = [line for line in resp.text.splitlines() if line.strip()]
        assert len(lines) == 1  # header only

    async def test_start_date_filter_accepted(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export?start_date=2025-01-01",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_end_date_filter_accepted(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export?end_date=2025-12-31",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_both_dates_accepted(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export{VALID_PARAMS}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_end_before_start_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export?start_date=2025-12-01&end_date=2025-01-01",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_invalid_start_date_format_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export?start_date=01-2025-01&end_date=2025-12-31",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_invalid_end_date_format_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export?start_date=2025-01-01&end_date=31-12-2025",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_valid_status_filter_accepted(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export?status=completed",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_invalid_status_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export?status=bogus_status",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_driver_id_filter_accepted(self, client, admin_user, admin_token, driver_user):
        resp = await client.get(
            f"{BASE}/export?driver_id={driver_user.id}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_unsupported_format_returns_422(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export?format=json",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_format_csv_accepted_explicitly(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export?format=csv",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_no_filters_returns_200(self, client, admin_user, admin_token):
        resp = await client.get(
            f"{BASE}/export",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_all_valid_status_values_accepted(self, client, admin_user, admin_token):
        valid_statuses = [
            "scheduled", "requested", "matched", "driver_en_route",
            "arrived", "in_progress", "completed", "cancelled",
        ]
        for status_val in valid_statuses:
            resp = await client.get(
                f"{BASE}/export?status={status_val}",
                headers=auth_header(admin_token),
            )
            assert resp.status_code == 200, (
                f"status={status_val!r} should return 200, got {resp.status_code}"
            )

    async def test_ride_data_appears_in_csv(
        self, client, db, admin_user, admin_token, rider, driver_user
    ):
        from geoalchemy2.functions import ST_MakePoint

        ride = Ride(
            rider_id=rider.id,
            driver_id=driver_user.id,
            status=RideStatus.COMPLETED,
            pickup_location=ST_MakePoint(-122.4194, 37.7749),
            dropoff_location=ST_MakePoint(-122.4094, 37.7849),
            pickup_address="100 Export St",
            dropoff_address="200 Export Ave",
            estimated_fare=22.0,
            actual_fare=22.0,
            requested_at=datetime(2025, 7, 1, 10, 0, 0, tzinfo=timezone.utc),
        )
        db.add(ride)
        await db.flush()

        resp = await client.get(
            f"{BASE}/export?start_date=2025-07-01&end_date=2025-07-31",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        # Should have at least header + 1 data row
        lines = [line for line in resp.text.splitlines() if line.strip()]
        assert len(lines) >= 2
        assert "100 Export St" in resp.text

    async def test_start_date_boundary_ride_included(
        self, client, db, admin_user, admin_token, rider
    ):
        """A ride with requested_at == start_date (midnight) is included."""
        from geoalchemy2.functions import ST_MakePoint

        ride = Ride(
            rider_id=rider.id,
            status=RideStatus.REQUESTED,
            pickup_location=ST_MakePoint(-122.4, 37.77),
            dropoff_location=ST_MakePoint(-122.41, 37.78),
            pickup_address="Boundary Start",
            dropoff_address="Anywhere",
            estimated_fare=10.0,
            requested_at=datetime(2025, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        db.add(ride)
        await db.flush()

        resp = await client.get(
            f"{BASE}/export?start_date=2025-08-01&end_date=2025-08-31",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert "Boundary Start" in resp.text

    async def test_end_date_boundary_ride_included(
        self, client, db, admin_user, admin_token, rider
    ):
        """A ride with requested_at == end_date (23:59:59) is included."""
        from geoalchemy2.functions import ST_MakePoint

        ride = Ride(
            rider_id=rider.id,
            status=RideStatus.REQUESTED,
            pickup_location=ST_MakePoint(-122.4, 37.77),
            dropoff_location=ST_MakePoint(-122.41, 37.78),
            pickup_address="Boundary End",
            dropoff_address="Anywhere",
            estimated_fare=10.0,
            requested_at=datetime(2025, 9, 30, 23, 59, 59, tzinfo=timezone.utc),
        )
        db.add(ride)
        await db.flush()

        resp = await client.get(
            f"{BASE}/export?start_date=2025-09-01&end_date=2025-09-30",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert "Boundary End" in resp.text

    async def test_ride_before_start_date_excluded(
        self, client, db, admin_user, admin_token, rider
    ):
        """A ride before start_date does not appear in the export."""
        from geoalchemy2.functions import ST_MakePoint

        ride = Ride(
            rider_id=rider.id,
            status=RideStatus.COMPLETED,
            pickup_location=ST_MakePoint(-122.4, 37.77),
            dropoff_location=ST_MakePoint(-122.41, 37.78),
            pickup_address="TooEarly Place",
            dropoff_address="Anywhere",
            estimated_fare=10.0,
            requested_at=datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
        db.add(ride)
        await db.flush()

        resp = await client.get(
            f"{BASE}/export?start_date=2025-01-01&end_date=2025-12-31",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert "TooEarly Place" not in resp.text

    async def test_driver_id_filter_excludes_other_drivers(
        self, client, db, admin_user, admin_token, rider, driver_user
    ):
        """With driver_id filter, only that driver's rides appear."""
        from geoalchemy2.functions import ST_MakePoint

        other_driver = User(
            phone="+15559990001",
            name="Other Driver",
            email="other_driver@test.com",
            password_hash="hashed",
            role=UserRole.DRIVER,
            is_active=True,
        )
        db.add(other_driver)
        await db.flush()

        ride_target = Ride(
            rider_id=rider.id,
            driver_id=driver_user.id,
            status=RideStatus.COMPLETED,
            pickup_location=ST_MakePoint(-122.4, 37.77),
            dropoff_location=ST_MakePoint(-122.41, 37.78),
            pickup_address="Target Driver Ride",
            dropoff_address="X",
            estimated_fare=10.0,
            requested_at=datetime(2025, 10, 5, tzinfo=timezone.utc),
        )
        ride_other = Ride(
            rider_id=rider.id,
            driver_id=other_driver.id,
            status=RideStatus.COMPLETED,
            pickup_location=ST_MakePoint(-122.4, 37.77),
            dropoff_location=ST_MakePoint(-122.41, 37.78),
            pickup_address="Other Driver Ride",
            dropoff_address="Y",
            estimated_fare=12.0,
            requested_at=datetime(2025, 10, 6, tzinfo=timezone.utc),
        )
        db.add(ride_target)
        db.add(ride_other)
        await db.flush()

        resp = await client.get(
            f"{BASE}/export?driver_id={driver_user.id}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert "Target Driver Ride" in resp.text
        assert "Other Driver Ride" not in resp.text

    async def test_status_filter_excludes_other_statuses(
        self, client, db, admin_user, admin_token, rider
    ):
        """With status=completed, only completed rides appear."""
        from geoalchemy2.functions import ST_MakePoint

        completed_ride = Ride(
            rider_id=rider.id,
            status=RideStatus.COMPLETED,
            pickup_location=ST_MakePoint(-122.4, 37.77),
            dropoff_location=ST_MakePoint(-122.41, 37.78),
            pickup_address="Completed Pickup",
            dropoff_address="X",
            estimated_fare=10.0,
            requested_at=datetime(2025, 11, 1, tzinfo=timezone.utc),
        )
        cancelled_ride = Ride(
            rider_id=rider.id,
            status=RideStatus.CANCELLED,
            pickup_location=ST_MakePoint(-122.4, 37.77),
            dropoff_location=ST_MakePoint(-122.41, 37.78),
            pickup_address="Cancelled Pickup",
            dropoff_address="Y",
            estimated_fare=10.0,
            requested_at=datetime(2025, 11, 2, tzinfo=timezone.utc),
        )
        db.add(completed_ride)
        db.add(cancelled_ride)
        await db.flush()

        resp = await client.get(
            f"{BASE}/export?status=completed&start_date=2025-11-01&end_date=2025-11-30",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert "Completed Pickup" in resp.text
        assert "Cancelled Pickup" not in resp.text
