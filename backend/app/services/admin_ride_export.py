"""Admin ride export service.

Provides a filterable CSV export of ride data for compliance reporting,
auditing, and operational analysis.

All functions are read-only; no data is mutated here.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment, PaymentStatus
from app.models.ride import Ride, RideStatus
from app.models.user import User


# ---------------------------------------------------------------------------
# Date helpers (shared pattern with admin_financials)
# ---------------------------------------------------------------------------


def _date_to_utc_start(d: date) -> datetime:
    """Convert a date to a UTC-aware datetime at midnight (inclusive start)."""
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)


def _date_to_utc_end(d: date) -> datetime:
    """Convert a date to a UTC-aware datetime at end of day (inclusive end)."""
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

_CSV_COLUMNS = [
    "ride_id",
    "created_at",
    "status",
    "driver_id",
    "driver_name",
    "rider_id",
    "rider_name",
    "pickup_address",
    "dropoff_address",
    "distance_miles",
    "fare_amount",
    "currency",
    "payment_status",
    "surge_multiplier",
    "vehicle_type",
]

_KM_TO_MILES = 0.621371


def _km_to_miles(km: float | None) -> str:
    """Convert km to miles; return empty string if value is absent."""
    if km is None:
        return ""
    return str(round(km * _KM_TO_MILES, 4))


async def export_rides_csv(
    db: AsyncSession,
    start_date: date | None = None,
    end_date: date | None = None,
    status: str | None = None,
    driver_id: int | None = None,
) -> str:
    """Return a CSV string of ride data, optionally filtered.

    Args:
        db: async database session
        start_date: inclusive start date — filters on ride.requested_at
        end_date: inclusive end date — filters on ride.requested_at
        status: optional RideStatus string value filter (e.g. "completed")
        driver_id: optional filter by driver user ID

    Columns (in order):
        ride_id, created_at, status, driver_id, driver_name, rider_id,
        rider_name, pickup_address, dropoff_address, distance_miles,
        fare_amount, currency, payment_status, surge_multiplier, vehicle_type

    Returns:
        CSV string with header row; empty result returns header row only.
    """
    query = select(Ride)

    if start_date is not None:
        query = query.where(Ride.requested_at >= _date_to_utc_start(start_date))

    if end_date is not None:
        query = query.where(Ride.requested_at <= _date_to_utc_end(end_date))

    if status is not None:
        try:
            status_enum = RideStatus(status)
        except ValueError:
            # Unknown status — return header-only CSV (no matching rows)
            output = io.StringIO()
            csv.writer(output).writerow(_CSV_COLUMNS)
            return output.getvalue()
        query = query.where(Ride.status == status_enum)

    if driver_id is not None:
        query = query.where(Ride.driver_id == driver_id)

    query = query.order_by(Ride.requested_at.asc())

    rides_result = await db.execute(query)
    rides: list[Ride] = list(rides_result.scalars().all())

    # Resolve user names for riders and drivers
    user_ids: set[int] = set()
    for ride in rides:
        user_ids.add(ride.rider_id)
        if ride.driver_id is not None:
            user_ids.add(ride.driver_id)

    users_by_id: dict[int, User] = {}
    if user_ids:
        users_result = await db.execute(
            select(User).where(User.id.in_(user_ids))
        )
        users_by_id = {u.id: u for u in users_result.scalars().all()}

    # Resolve payment status for each ride
    payment_status_by_ride: dict[int, str] = {}
    if rides:
        ride_ids = [r.id for r in rides]
        payments_result = await db.execute(
            select(Payment).where(Payment.ride_id.in_(ride_ids))
        )
        for payment in payments_result.scalars().all():
            # Use the most recent payment record (later ones overwrite earlier)
            payment_status_by_ride[payment.ride_id] = payment.status.value

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(_CSV_COLUMNS)

    for ride in rides:
        rider = users_by_id.get(ride.rider_id)
        driver = users_by_id.get(ride.driver_id) if ride.driver_id is not None else None

        fare_amount = ride.actual_fare if ride.actual_fare is not None else ride.estimated_fare

        vehicle_type = (
            ride.vehicle_type_preference.value
            if ride.vehicle_type_preference is not None
            else "standard"
        )

        writer.writerow([
            ride.id,
            ride.requested_at.isoformat() if ride.requested_at else "",
            ride.status.value,
            ride.driver_id if ride.driver_id is not None else "",
            driver.name if driver else "",
            ride.rider_id,
            rider.name if rider else "",
            ride.pickup_address,
            ride.dropoff_address,
            _km_to_miles(ride.distance_km),
            round(fare_amount, 2) if fare_amount is not None else "",
            "USD",
            payment_status_by_ride.get(ride.id, ""),
            "",  # surge_multiplier — not stored on Ride model
            vehicle_type,
        ])

    return output.getvalue()
