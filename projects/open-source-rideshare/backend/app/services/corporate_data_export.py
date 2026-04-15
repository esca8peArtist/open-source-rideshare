"""Corporate Data Export service.

Provides CSV exports of corporate ride data and invoice line items for
accounting, expense reporting, and reconciliation.

All functions are read-only; no data is mutated here.

Public surface
--------------
export_corporate_rides_csv(db, account_id, requesting_user_id, ...)
    Admin-only.  Exports completed rides for the account, with cost-center
    and trip-purpose columns, optionally filtered by date range, cost center,
    or trip purpose.

export_invoice_csv(db, invoice_id, account_id, requesting_user_id)
    Any active member.  Exports the ride-level line items for a specific
    invoice, matching the billing period on the invoice record.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccount, BusinessAccountMember, MemberRole
from app.models.corporate_cost_center import CorporateCostCenter
from app.models.corporate_invoice import CorporateInvoice
from app.models.corporate_trip_purpose import CorporateTripPurpose
from app.models.ride import Ride, RideStatus
from app.models.user import User


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def _date_to_utc_start(d: date) -> datetime:
    """Convert a date to a UTC-aware datetime at midnight (inclusive start)."""
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)


def _date_to_utc_end(d: date) -> datetime:
    """Convert a date to a UTC-aware datetime at end of day (inclusive end)."""
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


async def _require_account_admin(
    db: AsyncSession, account_id: int, user_id: int
) -> BusinessAccountMember:
    """Raise HTTP 403 when the user is not an active admin of the account."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.role == MemberRole.ADMIN,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have admin access to this corporate account.",
        )
    return member


async def _require_account_member(
    db: AsyncSession, account_id: int, user_id: int
) -> BusinessAccountMember:
    """Raise HTTP 403 when the user is not an active member of the account."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not an active member of this corporate account.",
        )
    return member


# ---------------------------------------------------------------------------
# Corporate rides CSV export
# ---------------------------------------------------------------------------

_RIDES_CSV_COLUMNS = [
    "ride_id",
    "completed_at",
    "status",
    "rider_id",
    "rider_name",
    "driver_id",
    "driver_name",
    "pickup_address",
    "dropoff_address",
    "distance_km",
    "duration_min",
    "actual_fare",
    "tip_amount",
    "total_charged",
    "cost_center_code",
    "cost_center_name",
    "trip_purpose_code",
    "trip_purpose_label",
    "trip_notes",
]


async def export_corporate_rides_csv(
    db: AsyncSession,
    account_id: int,
    requesting_user_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    cost_center_id: int | None = None,
    trip_purpose_id: int | None = None,
) -> str:
    """Return a CSV string of completed corporate rides for the account.

    Only account admins may call this function, as it includes rider names
    and full spend details across all employees.

    Args:
        db: Async database session.
        account_id: Corporate account identifier.
        requesting_user_id: ID of the authenticated user (must be admin).
        start_date: Inclusive start filter on ride.completed_at.
        end_date: Inclusive end filter on ride.completed_at.
        cost_center_id: Optional filter — only rides tagged to this cost center.
        trip_purpose_id: Optional filter — only rides tagged with this purpose.

    Columns (in order):
        ride_id, completed_at, status, rider_id, rider_name, driver_id,
        driver_name, pickup_address, dropoff_address, distance_km,
        duration_min, actual_fare, tip_amount, total_charged,
        cost_center_code, cost_center_name, trip_purpose_code,
        trip_purpose_label, trip_notes

    Returns:
        CSV string with header row.  Empty result returns header row only.

    Raises:
        HTTP 400: When end_date precedes start_date.
        HTTP 403: When the user is not an account admin.
    """
    if start_date is not None and end_date is not None and end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date must not be before start_date.",
        )

    await _require_account_admin(db, account_id, requesting_user_id)

    query = select(Ride).where(
        Ride.corporate_account_id == account_id,
        Ride.completed_at.is_not(None),
    )

    if start_date is not None:
        query = query.where(Ride.completed_at >= _date_to_utc_start(start_date))
    if end_date is not None:
        query = query.where(Ride.completed_at <= _date_to_utc_end(end_date))
    if cost_center_id is not None:
        query = query.where(Ride.cost_center_id == cost_center_id)
    if trip_purpose_id is not None:
        query = query.where(Ride.trip_purpose_id == trip_purpose_id)

    query = query.order_by(Ride.completed_at.asc())

    rides_result = await db.execute(query)
    rides: list[Ride] = list(rides_result.scalars().all())

    # Batch-resolve riders and drivers to avoid N+1
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

    # Batch-resolve cost centers
    cc_ids: set[int] = {r.cost_center_id for r in rides if r.cost_center_id is not None}
    cc_by_id: dict[int, CorporateCostCenter] = {}
    if cc_ids:
        cc_result = await db.execute(
            select(CorporateCostCenter).where(CorporateCostCenter.id.in_(cc_ids))
        )
        cc_by_id = {cc.id: cc for cc in cc_result.scalars().all()}

    # Batch-resolve trip purposes
    tp_ids: set[int] = {r.trip_purpose_id for r in rides if r.trip_purpose_id is not None}
    tp_by_id: dict[int, CorporateTripPurpose] = {}
    if tp_ids:
        tp_result = await db.execute(
            select(CorporateTripPurpose).where(CorporateTripPurpose.id.in_(tp_ids))
        )
        tp_by_id = {tp.id: tp for tp in tp_result.scalars().all()}

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(_RIDES_CSV_COLUMNS)

    for ride in rides:
        rider = users_by_id.get(ride.rider_id)
        driver = users_by_id.get(ride.driver_id) if ride.driver_id is not None else None
        cc = cc_by_id.get(ride.cost_center_id) if ride.cost_center_id is not None else None
        tp = tp_by_id.get(ride.trip_purpose_id) if ride.trip_purpose_id is not None else None

        actual_fare = ride.actual_fare if ride.actual_fare is not None else 0.0
        tip = ride.tip_amount if ride.tip_amount is not None else 0.0
        total_charged = round(actual_fare + tip, 2)

        writer.writerow([
            ride.id,
            ride.completed_at.isoformat() if ride.completed_at else "",
            ride.status.value,
            ride.rider_id,
            rider.name if rider else "",
            ride.driver_id if ride.driver_id is not None else "",
            driver.name if driver else "",
            ride.pickup_address,
            ride.dropoff_address,
            round(ride.distance_km, 4) if ride.distance_km is not None else "",
            round(ride.duration_min, 2) if ride.duration_min is not None else "",
            round(actual_fare, 2) if ride.actual_fare is not None else "",
            round(tip, 2),
            total_charged,
            cc.code if cc else "",
            cc.name if cc else "",
            tp.code if tp else "",
            tp.label if tp else "",
            ride.trip_notes if ride.trip_notes else "",
        ])

    return output.getvalue()


# ---------------------------------------------------------------------------
# Invoice line items CSV export
# ---------------------------------------------------------------------------

_INVOICE_CSV_COLUMNS = [
    "invoice_number",
    "invoice_status",
    "period_start",
    "period_end",
    "ride_id",
    "completed_at",
    "rider_id",
    "rider_name",
    "pickup_address",
    "dropoff_address",
    "actual_fare",
    "tip_amount",
    "total_charged",
    "cost_center_code",
    "cost_center_name",
    "trip_purpose_code",
    "trip_purpose_label",
    "trip_notes",
]


async def export_invoice_csv(
    db: AsyncSession,
    invoice_id: int,
    account_id: int,
    requesting_user_id: int,
) -> str:
    """Return a CSV string of ride-level line items for a specific invoice.

    Any active account member may call this function, consistent with the
    existing get_invoice_line_items service function.

    Args:
        db: Async database session.
        invoice_id: Invoice identifier (must belong to account_id).
        account_id: Corporate account identifier.
        requesting_user_id: ID of the authenticated user (must be member).

    Columns (in order):
        invoice_number, invoice_status, period_start, period_end,
        ride_id, completed_at, rider_id, rider_name, pickup_address,
        dropoff_address, actual_fare, tip_amount, total_charged,
        cost_center_code, cost_center_name, trip_purpose_code,
        trip_purpose_label, trip_notes

    Returns:
        CSV string with header row.  Empty result returns header row only.

    Raises:
        HTTP 403: When the user is not an active member.
        HTTP 404: When the invoice does not exist for this account.
    """
    await _require_account_member(db, account_id, requesting_user_id)

    # Fetch invoice — enforce account ownership
    inv_result = await db.execute(
        select(CorporateInvoice).where(
            CorporateInvoice.id == invoice_id,
            CorporateInvoice.account_id == account_id,
        )
    )
    invoice = inv_result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found.",
        )

    # Fetch rides for the billing period
    rides_result = await db.execute(
        select(Ride).where(
            Ride.corporate_account_id == account_id,
            Ride.actual_fare.is_not(None),
            Ride.completed_at.is_not(None),
            Ride.completed_at >= _date_to_utc_start(invoice.period_start),
            Ride.completed_at <= _date_to_utc_end(invoice.period_end),
        ).order_by(Ride.completed_at.asc())
    )
    rides: list[Ride] = list(rides_result.scalars().all())

    # Batch-resolve riders
    rider_ids: set[int] = {ride.rider_id for ride in rides}
    riders_by_id: dict[int, User] = {}
    if rider_ids:
        riders_result = await db.execute(
            select(User).where(User.id.in_(rider_ids))
        )
        riders_by_id = {u.id: u for u in riders_result.scalars().all()}

    # Batch-resolve cost centers
    cc_ids: set[int] = {r.cost_center_id for r in rides if r.cost_center_id is not None}
    cc_by_id: dict[int, CorporateCostCenter] = {}
    if cc_ids:
        cc_result = await db.execute(
            select(CorporateCostCenter).where(CorporateCostCenter.id.in_(cc_ids))
        )
        cc_by_id = {cc.id: cc for cc in cc_result.scalars().all()}

    # Batch-resolve trip purposes
    tp_ids: set[int] = {r.trip_purpose_id for r in rides if r.trip_purpose_id is not None}
    tp_by_id: dict[int, CorporateTripPurpose] = {}
    if tp_ids:
        tp_result = await db.execute(
            select(CorporateTripPurpose).where(CorporateTripPurpose.id.in_(tp_ids))
        )
        tp_by_id = {tp.id: tp for tp in tp_result.scalars().all()}

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(_INVOICE_CSV_COLUMNS)

    for ride in rides:
        rider = riders_by_id.get(ride.rider_id)
        cc = cc_by_id.get(ride.cost_center_id) if ride.cost_center_id is not None else None
        tp = tp_by_id.get(ride.trip_purpose_id) if ride.trip_purpose_id is not None else None

        actual_fare = ride.actual_fare if ride.actual_fare is not None else 0.0
        tip = ride.tip_amount if ride.tip_amount is not None else 0.0
        total_charged = round(actual_fare + tip, 2)

        writer.writerow([
            invoice.invoice_number,
            invoice.status.value,
            invoice.period_start.isoformat(),
            invoice.period_end.isoformat(),
            ride.id,
            ride.completed_at.isoformat() if ride.completed_at else "",
            ride.rider_id,
            rider.name if rider else "",
            ride.pickup_address,
            ride.dropoff_address,
            round(actual_fare, 2),
            round(tip, 2),
            total_charged,
            cc.code if cc else "",
            cc.name if cc else "",
            tp.code if tp else "",
            tp.label if tp else "",
            ride.trip_notes if ride.trip_notes else "",
        ])

    return output.getvalue()
