"""Service layer for Corporate Fleet Vehicle Registration Tracking.

Fleet managers track state/jurisdiction registration records for company
vehicles — registration numbers, expiration dates, and annual fees —
with expiry date alerts.

Public functions
----------------
register_vehicle            — create a new registration record (404 vehicle; 409 duplicate).
get_registration            — fetch one registration (404 if missing or wrong account).
list_vehicle_registrations  — all registrations for a specific fleet vehicle.
list_account_registrations  — filtered, paginated list for an account.
update_registration         — partial update (404; 409 number collision).
deactivate_registration     — mark as inactive (409 if already inactive).
reactivate_registration     — mark as active (409 if already active).
get_expiring_registrations  — active registrations expiring within N days.
get_account_registration_summary — aggregate stats for an account.
list_all_platform           — platform-admin cross-account listing.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
from app.models.corporate_fleet_registration import CorporateFleetVehicleRegistration
from app.schemas.corporate_fleet_registration import (
    RegistrationCreate,
    RegistrationExpiringResponse,
    RegistrationResponse,
    RegistrationSummaryResponse,
    RegistrationUpdate,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(row: CorporateFleetVehicleRegistration) -> RegistrationResponse:
    return RegistrationResponse.model_validate(row)


async def _fetch_vehicle(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: uuid.UUID,
) -> CorporateFleetVehicle:
    """Return a fleet vehicle verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        fleet_vehicle_id: UUID of the fleet vehicle.

    Returns:
        ``CorporateFleetVehicle`` ORM instance.

    Raises:
        HTTPException 404: Vehicle not found or does not belong to this account.
    """
    stmt = select(CorporateFleetVehicle).where(
        CorporateFleetVehicle.id == fleet_vehicle_id,
        CorporateFleetVehicle.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fleet vehicle not found for this account.",
        )
    return row


async def _fetch_registration(
    db: AsyncSession,
    account_id: int,
    registration_id: uuid.UUID,
) -> CorporateFleetVehicleRegistration:
    """Return a registration record verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        registration_id: UUID of the registration record.

    Returns:
        ``CorporateFleetVehicleRegistration`` ORM instance.

    Raises:
        HTTPException 404: Registration not found or wrong account.
    """
    stmt = select(CorporateFleetVehicleRegistration).where(
        CorporateFleetVehicleRegistration.id == registration_id,
        CorporateFleetVehicleRegistration.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration record not found.",
        )
    return row


async def _check_registration_number_unique(
    db: AsyncSession,
    account_id: int,
    registration_number: str,
    exclude_id: Optional[uuid.UUID] = None,
) -> None:
    """Raise 409 if registration_number already exists in this account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        registration_number: Registration number to check.
        exclude_id: UUID to exclude from the check (used on updates).

    Raises:
        HTTPException 409: Registration number already in use for this account.
    """
    conditions = [
        CorporateFleetVehicleRegistration.account_id == account_id,
        CorporateFleetVehicleRegistration.registration_number == registration_number,
    ]
    if exclude_id is not None:
        conditions.append(CorporateFleetVehicleRegistration.id != exclude_id)

    stmt = select(CorporateFleetVehicleRegistration).where(and_(*conditions)).limit(1)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A registration with this number already exists for this account.",
        )


# ---------------------------------------------------------------------------
# register_vehicle
# ---------------------------------------------------------------------------


async def register_vehicle(
    db: AsyncSession,
    account_id: int,
    data: RegistrationCreate,
    created_by_id: Optional[int] = None,
) -> RegistrationResponse:
    """Create a new vehicle registration record for a corporate fleet vehicle.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        data: Registration creation payload.
        created_by_id: ID of the user creating the record.

    Returns:
        ``RegistrationResponse`` for the new registration.

    Raises:
        HTTPException 404: Fleet vehicle not found for this account.
        HTTPException 409: Registration number already in use for this account.
    """
    await _fetch_vehicle(db, account_id, data.fleet_vehicle_id)

    await _check_registration_number_unique(db, account_id, data.registration_number)

    registration = CorporateFleetVehicleRegistration(
        id=uuid.uuid4(),
        account_id=account_id,
        fleet_vehicle_id=data.fleet_vehicle_id,
        registration_number=data.registration_number,
        registration_state=data.registration_state,
        registration_date=data.registration_date,
        expiration_date=data.expiration_date,
        annual_fee_usd=float(data.annual_fee_usd)
        if data.annual_fee_usd is not None
        else None,
        registered_owner_name=data.registered_owner_name,
        is_active=True,
        notes=data.notes,
        created_by_id=created_by_id,
    )
    db.add(registration)
    await db.commit()
    await db.refresh(registration)
    return _to_response(registration)


# ---------------------------------------------------------------------------
# get_registration
# ---------------------------------------------------------------------------


async def get_registration(
    db: AsyncSession,
    account_id: int,
    registration_id: uuid.UUID,
) -> RegistrationResponse:
    """Return a single registration record.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        registration_id: UUID of the registration record.

    Returns:
        ``RegistrationResponse``.

    Raises:
        HTTPException 404: Registration not found or wrong account.
    """
    row = await _fetch_registration(db, account_id, registration_id)
    return _to_response(row)


# ---------------------------------------------------------------------------
# list_vehicle_registrations
# ---------------------------------------------------------------------------


async def list_vehicle_registrations(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: uuid.UUID,
    *,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[RegistrationResponse]:
    """Return all registration records for a specific fleet vehicle.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        fleet_vehicle_id: UUID of the vehicle.
        is_active: Optional filter by active status.
        skip: Records to skip (default 0).
        limit: Max records to return (default 50).

    Returns:
        List of ``RegistrationResponse``.

    Raises:
        HTTPException 404: Vehicle not found for this account.
    """
    await _fetch_vehicle(db, account_id, fleet_vehicle_id)

    conditions = [
        CorporateFleetVehicleRegistration.account_id == account_id,
        CorporateFleetVehicleRegistration.fleet_vehicle_id == fleet_vehicle_id,
    ]
    if is_active is not None:
        conditions.append(CorporateFleetVehicleRegistration.is_active == is_active)

    stmt = (
        select(CorporateFleetVehicleRegistration)
        .where(and_(*conditions))
        .order_by(CorporateFleetVehicleRegistration.expiration_date.asc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# list_account_registrations
# ---------------------------------------------------------------------------


async def list_account_registrations(
    db: AsyncSession,
    account_id: int,
    *,
    is_active: Optional[bool] = None,
    registration_state: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[RegistrationResponse]:
    """Return a filtered, paginated list of registration records for an account.

    Results are ordered by expiration_date ascending (soonest expiry first).

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        is_active: Optional filter by active status.
        registration_state: Optional filter by state/jurisdiction name.
        skip: Records to skip (default 0).
        limit: Max records to return (default 50).

    Returns:
        List of ``RegistrationResponse``.
    """
    conditions = [CorporateFleetVehicleRegistration.account_id == account_id]
    if is_active is not None:
        conditions.append(CorporateFleetVehicleRegistration.is_active == is_active)
    if registration_state is not None:
        conditions.append(
            CorporateFleetVehicleRegistration.registration_state == registration_state
        )

    stmt = (
        select(CorporateFleetVehicleRegistration)
        .where(and_(*conditions))
        .order_by(CorporateFleetVehicleRegistration.expiration_date.asc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# update_registration
# ---------------------------------------------------------------------------


async def update_registration(
    db: AsyncSession,
    account_id: int,
    registration_id: uuid.UUID,
    data: RegistrationUpdate,
) -> RegistrationResponse:
    """Partially update a vehicle registration record.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        registration_id: UUID of the registration record.
        data: Fields to update (None values are ignored).

    Returns:
        Updated ``RegistrationResponse``.

    Raises:
        HTTPException 404: Registration not found or wrong account.
        HTTPException 409: Registration number already in use by another record.
    """
    row = await _fetch_registration(db, account_id, registration_id)

    update_data = data.model_dump(exclude_none=True)

    if "registration_number" in update_data:
        await _check_registration_number_unique(
            db, account_id, update_data["registration_number"], exclude_id=registration_id
        )

    for field, value in update_data.items():
        if field == "annual_fee_usd":
            value = float(value) if value is not None else None
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# deactivate_registration
# ---------------------------------------------------------------------------


async def deactivate_registration(
    db: AsyncSession,
    account_id: int,
    registration_id: uuid.UUID,
) -> RegistrationResponse:
    """Mark a registration record as inactive.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        registration_id: UUID of the registration record.

    Returns:
        Updated ``RegistrationResponse``.

    Raises:
        HTTPException 404: Registration not found or wrong account.
        HTTPException 409: Registration is already inactive.
    """
    row = await _fetch_registration(db, account_id, registration_id)

    if not row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration record is already inactive.",
        )

    row.is_active = False
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# reactivate_registration
# ---------------------------------------------------------------------------


async def reactivate_registration(
    db: AsyncSession,
    account_id: int,
    registration_id: uuid.UUID,
) -> RegistrationResponse:
    """Mark a registration record as active.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        registration_id: UUID of the registration record.

    Returns:
        Updated ``RegistrationResponse``.

    Raises:
        HTTPException 404: Registration not found or wrong account.
        HTTPException 409: Registration is already active.
    """
    row = await _fetch_registration(db, account_id, registration_id)

    if row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration record is already active.",
        )

    row.is_active = True
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# get_expiring_registrations
# ---------------------------------------------------------------------------


async def get_expiring_registrations(
    db: AsyncSession,
    account_id: int,
    *,
    days_ahead: int = 30,
    fleet_vehicle_id: Optional[uuid.UUID] = None,
) -> list[RegistrationExpiringResponse]:
    """Return active registrations expiring within the next N days.

    Only active registrations with expiration_date between today and
    today+days_ahead are included.  Results are ordered by expiration_date
    ascending.  days_until_expiry is computed in Python from date.today().

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        days_ahead: Look-ahead window in days (default 30).
        fleet_vehicle_id: Optional filter to a specific vehicle.

    Returns:
        List of ``RegistrationExpiringResponse``.
    """
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)

    conditions = [
        CorporateFleetVehicleRegistration.account_id == account_id,
        CorporateFleetVehicleRegistration.is_active == True,  # noqa: E712
        CorporateFleetVehicleRegistration.expiration_date >= today,
        CorporateFleetVehicleRegistration.expiration_date <= cutoff,
    ]
    if fleet_vehicle_id is not None:
        conditions.append(
            CorporateFleetVehicleRegistration.fleet_vehicle_id == fleet_vehicle_id
        )

    stmt = (
        select(CorporateFleetVehicleRegistration)
        .where(and_(*conditions))
        .order_by(CorporateFleetVehicleRegistration.expiration_date.asc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    alerts = []
    for row in rows:
        days_until = (row.expiration_date - today).days
        alerts.append(
            RegistrationExpiringResponse(
                id=row.id,
                account_id=row.account_id,
                fleet_vehicle_id=row.fleet_vehicle_id,
                registration_number=row.registration_number,
                registration_state=row.registration_state,
                registration_date=row.registration_date,
                expiration_date=row.expiration_date,
                annual_fee_usd=float(row.annual_fee_usd)
                if row.annual_fee_usd is not None
                else None,
                registered_owner_name=row.registered_owner_name,
                is_active=row.is_active,
                notes=row.notes,
                created_by_id=row.created_by_id,
                created_at=row.created_at,
                updated_at=row.updated_at,
                days_until_expiry=days_until,
            )
        )
    return alerts


# ---------------------------------------------------------------------------
# get_account_registration_summary
# ---------------------------------------------------------------------------


async def get_account_registration_summary(
    db: AsyncSession,
    account_id: int,
) -> RegistrationSummaryResponse:
    """Return aggregate registration statistics for a corporate account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.

    Returns:
        ``RegistrationSummaryResponse`` with counts, fee total, and per-state breakdown.
    """
    today = date.today()
    cutoff_30 = today + timedelta(days=30)

    stmt = select(CorporateFleetVehicleRegistration).where(
        CorporateFleetVehicleRegistration.account_id == account_id
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    active = sum(1 for r in rows if r.is_active)
    inactive = len(rows) - active

    expiring_30 = sum(
        1
        for r in rows
        if r.is_active
        and r.expiration_date >= today
        and r.expiration_date <= cutoff_30
    )

    total_fee = sum(
        float(r.annual_fee_usd)
        for r in rows
        if r.is_active and r.annual_fee_usd is not None
    )

    per_state: dict[str, int] = {}
    for row in rows:
        state = row.registration_state
        per_state[state] = per_state.get(state, 0) + 1

    return RegistrationSummaryResponse(
        active_count=active,
        inactive_count=inactive,
        expiring_within_30_days=expiring_30,
        total_annual_fee_usd=round(total_fee, 2),
        per_state_breakdown=per_state,
    )


# ---------------------------------------------------------------------------
# list_all_platform
# ---------------------------------------------------------------------------


async def list_all_platform(
    db: AsyncSession,
    *,
    account_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
) -> list[RegistrationResponse]:
    """Return registration records across all corporate accounts (platform admin).

    Args:
        db: Async SQLAlchemy session.
        account_id: Optional filter to a specific account.
        skip: Records to skip (default 0).
        limit: Max records to return (default 100).

    Returns:
        List of ``RegistrationResponse``.
    """
    conditions = []
    if account_id is not None:
        conditions.append(CorporateFleetVehicleRegistration.account_id == account_id)

    base = select(CorporateFleetVehicleRegistration)
    if conditions:
        base = base.where(and_(*conditions))

    stmt = (
        base.order_by(
            CorporateFleetVehicleRegistration.account_id,
            CorporateFleetVehicleRegistration.expiration_date.asc(),
        )
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]
