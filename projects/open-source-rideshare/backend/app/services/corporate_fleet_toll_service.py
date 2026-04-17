"""Service layer for Corporate Fleet Toll & Transponder Management.

Fleet managers track toll transponders assigned to fleet vehicles and log
individual toll charges for cost analytics and expense reporting.

Public functions
----------------
assign_transponder          — create a new transponder record (404 vehicle; 409 duplicate number).
get_transponder             — fetch one transponder (404 if missing or wrong account).
list_vehicle_transponders   — all transponders for a specific fleet vehicle.
list_account_transponders   — filtered, paginated list for an account.
deactivate_transponder      — mark as inactive, set removed_date (409 if already inactive).
reactivate_transponder      — mark as active, clear removed_date (409 if already active).
log_toll_charge             — create a toll charge record (404 vehicle; optional 404 transponder).
get_toll_charge             — fetch one toll charge (404 if missing or wrong account).
update_toll_charge          — partial update (404 if missing).
delete_toll_charge          — delete a toll charge record (404 if missing).
list_vehicle_toll_charges   — charges for a specific vehicle, date-range filter.
get_vehicle_toll_summary    — aggregate stats for one vehicle.
list_account_toll_charges   — filtered, paginated charges for an account.
get_fleet_toll_summary      — fleet-wide aggregate with per-vehicle and per-provider breakdown.
list_all_platform           — platform-admin cross-account listing.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_fleet_toll import (
    CorporateFleetTollCharge,
    CorporateFleetTollTransponder,
    TransponderProvider,
)
from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
from app.schemas.corporate_fleet_toll import (
    FleetTollSummaryResponse,
    FleetTollVehicleBreakdown,
    TollChargeCreate,
    TollChargeResponse,
    TollChargeUpdate,
    TransponderCreate,
    TransponderResponse,
    VehicleTollSummaryResponse,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_transponder_response(row: CorporateFleetTollTransponder) -> TransponderResponse:
    return TransponderResponse.model_validate(row)


def _to_charge_response(row: CorporateFleetTollCharge) -> TollChargeResponse:
    return TollChargeResponse.model_validate(row)


async def _fetch_vehicle(
    db: AsyncSession, account_id: int, vehicle_id: uuid.UUID
) -> CorporateFleetVehicle:
    """Return the fleet vehicle or raise 404."""
    result = await db.execute(
        select(CorporateFleetVehicle).where(
            CorporateFleetVehicle.id == vehicle_id,
            CorporateFleetVehicle.account_id == account_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fleet vehicle {vehicle_id} not found in account {account_id}.",
        )
    return row


async def _fetch_transponder(
    db: AsyncSession, account_id: int, transponder_id: uuid.UUID
) -> CorporateFleetTollTransponder:
    """Return the transponder or raise 404."""
    result = await db.execute(
        select(CorporateFleetTollTransponder).where(
            CorporateFleetTollTransponder.id == transponder_id,
            CorporateFleetTollTransponder.account_id == account_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transponder {transponder_id} not found in account {account_id}.",
        )
    return row


async def _fetch_charge(
    db: AsyncSession, account_id: int, charge_id: uuid.UUID
) -> CorporateFleetTollCharge:
    """Return the toll charge or raise 404."""
    result = await db.execute(
        select(CorporateFleetTollCharge).where(
            CorporateFleetTollCharge.id == charge_id,
            CorporateFleetTollCharge.account_id == account_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Toll charge {charge_id} not found in account {account_id}.",
        )
    return row


async def _check_transponder_number_unique(
    db: AsyncSession,
    account_id: int,
    transponder_number: str,
    exclude_id: Optional[uuid.UUID] = None,
) -> None:
    """Raise 409 if transponder_number already exists for this account."""
    q = select(CorporateFleetTollTransponder.id).where(
        CorporateFleetTollTransponder.account_id == account_id,
        CorporateFleetTollTransponder.transponder_number == transponder_number,
    )
    if exclude_id is not None:
        q = q.where(CorporateFleetTollTransponder.id != exclude_id)
    result = await db.execute(q)
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transponder number '{transponder_number}' already exists for this account.",
        )


# ---------------------------------------------------------------------------
# Transponder CRUD
# ---------------------------------------------------------------------------


async def assign_transponder(
    db: AsyncSession,
    account_id: int,
    data: TransponderCreate,
    assigned_by_id: Optional[int] = None,
) -> TransponderResponse:
    """Assign a new toll transponder to a fleet vehicle.

    Raises:
        404: Vehicle not found in account.
        409: Transponder number already exists for this account.
    """
    await _fetch_vehicle(db, account_id, data.fleet_vehicle_id)
    await _check_transponder_number_unique(db, account_id, data.transponder_number)

    row = CorporateFleetTollTransponder(
        account_id=account_id,
        fleet_vehicle_id=data.fleet_vehicle_id,
        transponder_number=data.transponder_number,
        provider=data.provider,
        assigned_date=data.assigned_date,
        removed_date=None,
        monthly_plan_cost_usd=data.monthly_plan_cost_usd,
        toll_account_number=data.toll_account_number,
        is_active=True,
        notes=data.notes,
        assigned_by_id=assigned_by_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_transponder_response(row)


async def get_transponder(
    db: AsyncSession, account_id: int, transponder_id: uuid.UUID
) -> TransponderResponse:
    """Return a single transponder record.

    Raises:
        404: Not found or belongs to a different account.
    """
    row = await _fetch_transponder(db, account_id, transponder_id)
    return _to_transponder_response(row)


async def list_vehicle_transponders(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[TransponderResponse]:
    """Return all transponders for a specific fleet vehicle."""
    await _fetch_vehicle(db, account_id, vehicle_id)
    q = select(CorporateFleetTollTransponder).where(
        CorporateFleetTollTransponder.account_id == account_id,
        CorporateFleetTollTransponder.fleet_vehicle_id == vehicle_id,
    )
    if is_active is not None:
        q = q.where(CorporateFleetTollTransponder.is_active == is_active)
    q = q.order_by(CorporateFleetTollTransponder.assigned_date.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return [_to_transponder_response(r) for r in result.scalars().all()]


async def list_account_transponders(
    db: AsyncSession,
    account_id: int,
    is_active: Optional[bool] = None,
    provider: Optional[TransponderProvider] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[TransponderResponse]:
    """Return all transponders for a corporate account, with optional filters."""
    q = select(CorporateFleetTollTransponder).where(
        CorporateFleetTollTransponder.account_id == account_id,
    )
    if is_active is not None:
        q = q.where(CorporateFleetTollTransponder.is_active == is_active)
    if provider is not None:
        q = q.where(CorporateFleetTollTransponder.provider == provider)
    q = q.order_by(CorporateFleetTollTransponder.assigned_date.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return [_to_transponder_response(r) for r in result.scalars().all()]


async def deactivate_transponder(
    db: AsyncSession, account_id: int, transponder_id: uuid.UUID
) -> TransponderResponse:
    """Mark a transponder as inactive and record the removal date.

    Raises:
        404: Not found or belongs to a different account.
        409: Already inactive.
    """
    row = await _fetch_transponder(db, account_id, transponder_id)
    if not row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transponder is already inactive.",
        )
    row.is_active = False
    row.removed_date = datetime.now(tz=timezone.utc).date()
    await db.commit()
    await db.refresh(row)
    return _to_transponder_response(row)


async def reactivate_transponder(
    db: AsyncSession, account_id: int, transponder_id: uuid.UUID
) -> TransponderResponse:
    """Mark a transponder as active and clear the removal date.

    Raises:
        404: Not found or belongs to a different account.
        409: Already active.
    """
    row = await _fetch_transponder(db, account_id, transponder_id)
    if row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transponder is already active.",
        )
    row.is_active = True
    row.removed_date = None
    await db.commit()
    await db.refresh(row)
    return _to_transponder_response(row)


# ---------------------------------------------------------------------------
# Toll charge CRUD
# ---------------------------------------------------------------------------


async def log_toll_charge(
    db: AsyncSession,
    account_id: int,
    data: TollChargeCreate,
    logged_by_id: Optional[int] = None,
) -> TollChargeResponse:
    """Log an individual toll charge for a fleet vehicle.

    Raises:
        404: Vehicle not found in account.
        404: Transponder not found in account (if transponder_id provided).
    """
    await _fetch_vehicle(db, account_id, data.fleet_vehicle_id)
    if data.transponder_id is not None:
        await _fetch_transponder(db, account_id, data.transponder_id)

    row = CorporateFleetTollCharge(
        account_id=account_id,
        fleet_vehicle_id=data.fleet_vehicle_id,
        transponder_id=data.transponder_id,
        charge_date=data.charge_date,
        plaza_name=data.plaza_name,
        amount_usd=data.amount_usd,
        entry_location=data.entry_location,
        exit_location=data.exit_location,
        trip_purpose=data.trip_purpose,
        notes=data.notes,
        logged_by_id=logged_by_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_charge_response(row)


async def get_toll_charge(
    db: AsyncSession, account_id: int, charge_id: uuid.UUID
) -> TollChargeResponse:
    """Return a single toll charge record.

    Raises:
        404: Not found or belongs to a different account.
    """
    row = await _fetch_charge(db, account_id, charge_id)
    return _to_charge_response(row)


async def update_toll_charge(
    db: AsyncSession,
    account_id: int,
    charge_id: uuid.UUID,
    data: TollChargeUpdate,
) -> TollChargeResponse:
    """Partially update a toll charge record.

    Raises:
        404: Not found or belongs to a different account.
    """
    row = await _fetch_charge(db, account_id, charge_id)

    if data.transponder_id is not None:
        row.transponder_id = data.transponder_id
    if data.charge_date is not None:
        row.charge_date = data.charge_date
    if data.plaza_name is not None:
        row.plaza_name = data.plaza_name
    if data.amount_usd is not None:
        row.amount_usd = data.amount_usd
    if data.entry_location is not None:
        row.entry_location = data.entry_location
    if data.exit_location is not None:
        row.exit_location = data.exit_location
    if data.trip_purpose is not None:
        row.trip_purpose = data.trip_purpose
    if data.notes is not None:
        row.notes = data.notes

    await db.commit()
    await db.refresh(row)
    return _to_charge_response(row)


async def delete_toll_charge(
    db: AsyncSession, account_id: int, charge_id: uuid.UUID
) -> None:
    """Delete a toll charge record.

    Raises:
        404: Not found or belongs to a different account.
    """
    row = await _fetch_charge(db, account_id, charge_id)
    await db.delete(row)
    await db.commit()


async def list_vehicle_toll_charges(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[TollChargeResponse]:
    """Return toll charges for a specific fleet vehicle, with date range filter."""
    await _fetch_vehicle(db, account_id, vehicle_id)
    q = select(CorporateFleetTollCharge).where(
        CorporateFleetTollCharge.account_id == account_id,
        CorporateFleetTollCharge.fleet_vehicle_id == vehicle_id,
    )
    if date_from is not None:
        q = q.where(CorporateFleetTollCharge.charge_date >= date_from)
    if date_to is not None:
        q = q.where(CorporateFleetTollCharge.charge_date <= date_to)
    q = q.order_by(CorporateFleetTollCharge.charge_date.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return [_to_charge_response(r) for r in result.scalars().all()]


async def get_vehicle_toll_summary(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> VehicleTollSummaryResponse:
    """Return aggregate toll statistics for a single fleet vehicle."""
    await _fetch_vehicle(db, account_id, vehicle_id)

    # Aggregate charge totals
    charge_q = select(
        func.count(CorporateFleetTollCharge.id).label("charge_count"),
        func.coalesce(func.sum(CorporateFleetTollCharge.amount_usd), 0).label("total_cost"),
        func.min(CorporateFleetTollCharge.charge_date).label("date_from"),
        func.max(CorporateFleetTollCharge.charge_date).label("date_to"),
    ).where(
        CorporateFleetTollCharge.account_id == account_id,
        CorporateFleetTollCharge.fleet_vehicle_id == vehicle_id,
    )
    if date_from is not None:
        charge_q = charge_q.where(CorporateFleetTollCharge.charge_date >= date_from)
    if date_to is not None:
        charge_q = charge_q.where(CorporateFleetTollCharge.charge_date <= date_to)
    charge_result = await db.execute(charge_q)
    row = charge_result.one()

    # Count active transponders
    transponder_q = select(
        func.count(CorporateFleetTollTransponder.id)
    ).where(
        CorporateFleetTollTransponder.account_id == account_id,
        CorporateFleetTollTransponder.fleet_vehicle_id == vehicle_id,
        CorporateFleetTollTransponder.is_active == True,  # noqa: E712
    )
    transponder_result = await db.execute(transponder_q)
    active_count = transponder_result.scalar_one()

    return VehicleTollSummaryResponse(
        fleet_vehicle_id=vehicle_id,
        charge_count=row.charge_count or 0,
        total_cost_usd=float(row.total_cost or 0),
        active_transponder_count=active_count or 0,
        date_from=row.date_from,
        date_to=row.date_to,
    )


async def list_account_toll_charges(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: Optional[uuid.UUID] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[TollChargeResponse]:
    """Return toll charges for an account, with optional filters."""
    q = select(CorporateFleetTollCharge).where(
        CorporateFleetTollCharge.account_id == account_id,
    )
    if fleet_vehicle_id is not None:
        q = q.where(CorporateFleetTollCharge.fleet_vehicle_id == fleet_vehicle_id)
    if date_from is not None:
        q = q.where(CorporateFleetTollCharge.charge_date >= date_from)
    if date_to is not None:
        q = q.where(CorporateFleetTollCharge.charge_date <= date_to)
    q = q.order_by(CorporateFleetTollCharge.charge_date.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return [_to_charge_response(r) for r in result.scalars().all()]


async def get_fleet_toll_summary(
    db: AsyncSession,
    account_id: int,
) -> FleetTollSummaryResponse:
    """Return fleet-wide aggregate toll statistics for a corporate account."""
    # Fleet-wide charge totals
    totals_q = select(
        func.count(CorporateFleetTollCharge.id).label("charge_count"),
        func.coalesce(func.sum(CorporateFleetTollCharge.amount_usd), 0).label("total_cost"),
        func.count(
            CorporateFleetTollCharge.fleet_vehicle_id.distinct()
        ).label("vehicle_count"),
    ).where(CorporateFleetTollCharge.account_id == account_id)
    totals_result = await db.execute(totals_q)
    totals = totals_result.one()

    # Active transponder count
    active_q = select(func.count(CorporateFleetTollTransponder.id)).where(
        CorporateFleetTollTransponder.account_id == account_id,
        CorporateFleetTollTransponder.is_active == True,  # noqa: E712
    )
    active_result = await db.execute(active_q)
    active_transponder_count = active_result.scalar_one() or 0

    # Per-provider cost breakdown — join charges through transponder
    # We use the transponder linked to the charge; charges without transponder go to "unlinked"
    provider_q = select(
        CorporateFleetTollTransponder.provider,
        func.coalesce(func.sum(CorporateFleetTollCharge.amount_usd), 0).label("provider_cost"),
    ).join(
        CorporateFleetTollTransponder,
        CorporateFleetTollCharge.transponder_id == CorporateFleetTollTransponder.id,
        isouter=True,
    ).where(
        CorporateFleetTollCharge.account_id == account_id,
    ).group_by(CorporateFleetTollTransponder.provider)
    provider_result = await db.execute(provider_q)
    per_provider: dict[str, float] = {}
    for p_row in provider_result.all():
        key = p_row.provider.value if p_row.provider is not None else "unlinked"
        per_provider[key] = float(p_row.provider_cost or 0)

    # Top vehicles by cost
    vehicle_q = select(
        CorporateFleetTollCharge.fleet_vehicle_id,
        func.count(CorporateFleetTollCharge.id).label("charge_count"),
        func.coalesce(func.sum(CorporateFleetTollCharge.amount_usd), 0).label("vehicle_cost"),
    ).where(
        CorporateFleetTollCharge.account_id == account_id,
    ).group_by(
        CorporateFleetTollCharge.fleet_vehicle_id,
    ).order_by(
        func.sum(CorporateFleetTollCharge.amount_usd).desc()
    ).limit(10)
    vehicle_result = await db.execute(vehicle_q)
    top_vehicles = [
        FleetTollVehicleBreakdown(
            fleet_vehicle_id=v.fleet_vehicle_id,
            charge_count=v.charge_count,
            total_cost_usd=float(v.vehicle_cost or 0),
        )
        for v in vehicle_result.all()
    ]

    return FleetTollSummaryResponse(
        total_charge_count=totals.charge_count or 0,
        total_cost_usd=float(totals.total_cost or 0),
        active_transponder_count=active_transponder_count,
        vehicle_count=totals.vehicle_count or 0,
        per_provider_cost_usd=per_provider,
        top_vehicles=top_vehicles,
    )


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
) -> list[TransponderResponse]:
    """Return transponder records across all accounts (platform admin).

    Optionally filter by account_id.
    """
    q = select(CorporateFleetTollTransponder)
    if account_id is not None:
        q = q.where(CorporateFleetTollTransponder.account_id == account_id)
    q = q.order_by(
        CorporateFleetTollTransponder.account_id,
        CorporateFleetTollTransponder.assigned_date.desc(),
    ).offset(skip).limit(limit)
    result = await db.execute(q)
    return [_to_transponder_response(r) for r in result.scalars().all()]
