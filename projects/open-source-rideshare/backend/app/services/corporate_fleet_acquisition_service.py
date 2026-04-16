"""Service layer for Corporate Fleet Vehicle Acquisition and Disposal Tracking.

Fleet managers record how vehicles entered the fleet (purchased, leased,
financed, donated) and formally retire vehicles when they leave it.

Public functions
----------------
record_acquisition          — create or replace the active acquisition for a vehicle.
get_acquisition             — fetch one acquisition by ID (404 if missing or wrong account).
get_vehicle_acquisition     — active acquisition for a vehicle, or None.
list_vehicle_acquisitions   — full acquisition history for a vehicle.
update_acquisition          — partial update on an active acquisition record.
dispose_vehicle             — retire a vehicle: create disposal, deactivate vehicle + acquisition.
get_disposal                — fetch one disposal record by ID.
get_vehicle_disposal        — disposal record for a vehicle, or None.
list_account_disposals      — all disposals for an account, with optional filters.
get_fleet_ownership_summary — aggregate ownership stats for an account.
list_all_platform           — platform-admin: all acquisitions, optional account filter.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_fleet_acquisition import (
    AcquisitionType,
    CorporateFleetVehicleAcquisition,
    CorporateFleetVehicleDisposal,
    DisposalReason,
)
from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
from app.schemas.corporate_fleet_acquisition import (
    AcquisitionCreate,
    AcquisitionResponse,
    AcquisitionUpdate,
    DisposalCreate,
    DisposalResponse,
    FleetOwnershipSummary,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _acq_to_response(row: CorporateFleetVehicleAcquisition) -> AcquisitionResponse:
    return AcquisitionResponse.model_validate(row)


def _disposal_to_response(row: CorporateFleetVehicleDisposal) -> DisposalResponse:
    return DisposalResponse.model_validate(row)


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


async def _fetch_acquisition(
    db: AsyncSession,
    account_id: int,
    acquisition_id: uuid.UUID,
) -> CorporateFleetVehicleAcquisition:
    """Return an acquisition record verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        acquisition_id: UUID of the acquisition record.

    Returns:
        ``CorporateFleetVehicleAcquisition`` ORM instance.

    Raises:
        HTTPException 404: Acquisition not found or wrong account.
    """
    stmt = select(CorporateFleetVehicleAcquisition).where(
        CorporateFleetVehicleAcquisition.id == acquisition_id,
        CorporateFleetVehicleAcquisition.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Acquisition record not found.",
        )
    return row


async def _fetch_disposal(
    db: AsyncSession,
    account_id: int,
    disposal_id: uuid.UUID,
) -> CorporateFleetVehicleDisposal:
    """Return a disposal record verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        disposal_id: UUID of the disposal record.

    Returns:
        ``CorporateFleetVehicleDisposal`` ORM instance.

    Raises:
        HTTPException 404: Disposal not found or wrong account.
    """
    stmt = select(CorporateFleetVehicleDisposal).where(
        CorporateFleetVehicleDisposal.id == disposal_id,
        CorporateFleetVehicleDisposal.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disposal record not found.",
        )
    return row


def _numeric(value: Optional[float]) -> Optional[float]:
    return float(value) if value is not None else None


# ---------------------------------------------------------------------------
# record_acquisition
# ---------------------------------------------------------------------------


async def record_acquisition(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: uuid.UUID,
    data: AcquisitionCreate,
    created_by_id: Optional[int] = None,
) -> AcquisitionResponse:
    """Create or replace the active acquisition record for a fleet vehicle.

    If the vehicle already has an active acquisition record, it is marked
    inactive before the new record is created.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        fleet_vehicle_id: UUID of the fleet vehicle.
        data: Acquisition creation payload.
        created_by_id: ID of the user creating the record.

    Returns:
        ``AcquisitionResponse`` for the new active acquisition.

    Raises:
        HTTPException 404: Fleet vehicle not found for this account.
    """
    await _fetch_vehicle(db, account_id, fleet_vehicle_id)

    # Deactivate any existing active acquisition for this vehicle.
    stmt = select(CorporateFleetVehicleAcquisition).where(
        CorporateFleetVehicleAcquisition.fleet_vehicle_id == fleet_vehicle_id,
        CorporateFleetVehicleAcquisition.account_id == account_id,
        CorporateFleetVehicleAcquisition.is_active == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.is_active = False

    acquisition = CorporateFleetVehicleAcquisition(
        id=uuid.uuid4(),
        fleet_vehicle_id=fleet_vehicle_id,
        account_id=account_id,
        acquisition_type=data.acquisition_type,
        vendor_name=data.vendor_name,
        acquisition_date=data.acquisition_date,
        acquisition_cost_usd=_numeric(data.acquisition_cost_usd),
        lease_start_date=data.lease_start_date,
        lease_end_date=data.lease_end_date,
        monthly_lease_payment_usd=_numeric(data.monthly_lease_payment_usd),
        lease_mileage_allowance_annual=data.lease_mileage_allowance_annual,
        financed_amount_usd=_numeric(data.financed_amount_usd),
        loan_term_months=data.loan_term_months,
        monthly_loan_payment_usd=_numeric(data.monthly_loan_payment_usd),
        notes=data.notes,
        is_active=True,
        created_by_id=created_by_id,
    )
    db.add(acquisition)
    await db.commit()
    await db.refresh(acquisition)
    return _acq_to_response(acquisition)


# ---------------------------------------------------------------------------
# get_acquisition
# ---------------------------------------------------------------------------


async def get_acquisition(
    db: AsyncSession,
    account_id: int,
    acquisition_id: uuid.UUID,
) -> AcquisitionResponse:
    """Return a single acquisition record.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        acquisition_id: UUID of the acquisition record.

    Returns:
        ``AcquisitionResponse``.

    Raises:
        HTTPException 404: Acquisition not found or wrong account.
    """
    row = await _fetch_acquisition(db, account_id, acquisition_id)
    return _acq_to_response(row)


# ---------------------------------------------------------------------------
# get_vehicle_acquisition
# ---------------------------------------------------------------------------


async def get_vehicle_acquisition(
    db: AsyncSession,
    fleet_vehicle_id: uuid.UUID,
    account_id: int,
) -> Optional[AcquisitionResponse]:
    """Return the active acquisition for a vehicle, or None if none exists.

    Args:
        db: Async SQLAlchemy session.
        fleet_vehicle_id: UUID of the fleet vehicle.
        account_id: Corporate account ID.

    Returns:
        ``AcquisitionResponse`` or None.
    """
    stmt = select(CorporateFleetVehicleAcquisition).where(
        CorporateFleetVehicleAcquisition.fleet_vehicle_id == fleet_vehicle_id,
        CorporateFleetVehicleAcquisition.account_id == account_id,
        CorporateFleetVehicleAcquisition.is_active == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return _acq_to_response(row) if row is not None else None


# ---------------------------------------------------------------------------
# list_vehicle_acquisitions
# ---------------------------------------------------------------------------


async def list_vehicle_acquisitions(
    db: AsyncSession,
    fleet_vehicle_id: uuid.UUID,
    account_id: int,
) -> list[AcquisitionResponse]:
    """Return all acquisition records for a fleet vehicle (full history).

    Results are ordered by acquisition_date descending (most recent first).

    Args:
        db: Async SQLAlchemy session.
        fleet_vehicle_id: UUID of the fleet vehicle.
        account_id: Corporate account ID.

    Returns:
        List of ``AcquisitionResponse``.
    """
    await _fetch_vehicle(db, account_id, fleet_vehicle_id)

    stmt = (
        select(CorporateFleetVehicleAcquisition)
        .where(
            CorporateFleetVehicleAcquisition.fleet_vehicle_id == fleet_vehicle_id,
            CorporateFleetVehicleAcquisition.account_id == account_id,
        )
        .order_by(CorporateFleetVehicleAcquisition.acquisition_date.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_acq_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# update_acquisition
# ---------------------------------------------------------------------------


async def update_acquisition(
    db: AsyncSession,
    account_id: int,
    acquisition_id: uuid.UUID,
    data: AcquisitionUpdate,
) -> AcquisitionResponse:
    """Partially update an acquisition record.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        acquisition_id: UUID of the acquisition record.
        data: Fields to update (None values are ignored).

    Returns:
        Updated ``AcquisitionResponse``.

    Raises:
        HTTPException 404: Acquisition not found or wrong account.
    """
    row = await _fetch_acquisition(db, account_id, acquisition_id)

    update_data = data.model_dump(exclude_none=True)

    numeric_fields = {
        "acquisition_cost_usd",
        "monthly_lease_payment_usd",
        "financed_amount_usd",
        "monthly_loan_payment_usd",
    }

    for field, value in update_data.items():
        if field in numeric_fields:
            value = float(value) if value is not None else None
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    return _acq_to_response(row)


# ---------------------------------------------------------------------------
# dispose_vehicle
# ---------------------------------------------------------------------------


async def dispose_vehicle(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: uuid.UUID,
    data: DisposalCreate,
    disposed_by_id: Optional[int] = None,
) -> DisposalResponse:
    """Retire a fleet vehicle by creating a disposal record.

    This function:
    1. Verifies the vehicle belongs to the account (404 if not found).
    2. Raises 409 if a disposal record already exists (vehicle already retired).
    3. Marks the vehicle's ``is_active`` flag to ``False``.
    4. Marks the vehicle's active acquisition (if any) as inactive.
    5. Creates and returns the disposal record.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        fleet_vehicle_id: UUID of the fleet vehicle to retire.
        data: Disposal creation payload.
        disposed_by_id: ID of the user creating the disposal record.

    Returns:
        ``DisposalResponse`` for the new disposal record.

    Raises:
        HTTPException 404: Fleet vehicle not found for this account.
        HTTPException 409: Vehicle already has a disposal record.
    """
    vehicle = await _fetch_vehicle(db, account_id, fleet_vehicle_id)

    # 409 if already disposed.
    existing_stmt = select(CorporateFleetVehicleDisposal).where(
        CorporateFleetVehicleDisposal.fleet_vehicle_id == fleet_vehicle_id,
        CorporateFleetVehicleDisposal.account_id == account_id,
    )
    existing_result = await db.execute(existing_stmt)
    existing_disposal = existing_result.scalar_one_or_none()
    if existing_disposal is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This vehicle has already been disposed of.",
        )

    # Deactivate the vehicle.
    vehicle.is_active = False

    # Deactivate any active acquisition.
    acq_stmt = select(CorporateFleetVehicleAcquisition).where(
        CorporateFleetVehicleAcquisition.fleet_vehicle_id == fleet_vehicle_id,
        CorporateFleetVehicleAcquisition.account_id == account_id,
        CorporateFleetVehicleAcquisition.is_active == True,  # noqa: E712
    )
    acq_result = await db.execute(acq_stmt)
    active_acq = acq_result.scalar_one_or_none()
    if active_acq is not None:
        active_acq.is_active = False

    disposal = CorporateFleetVehicleDisposal(
        id=uuid.uuid4(),
        fleet_vehicle_id=fleet_vehicle_id,
        account_id=account_id,
        disposal_reason=data.disposal_reason,
        disposal_date=data.disposal_date,
        sale_price_usd=_numeric(data.sale_price_usd),
        buyer_name=data.buyer_name,
        notes=data.notes,
        disposed_by_id=disposed_by_id,
    )
    db.add(disposal)
    await db.commit()
    await db.refresh(disposal)
    return _disposal_to_response(disposal)


# ---------------------------------------------------------------------------
# get_disposal
# ---------------------------------------------------------------------------


async def get_disposal(
    db: AsyncSession,
    account_id: int,
    disposal_id: uuid.UUID,
) -> DisposalResponse:
    """Return a single disposal record.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        disposal_id: UUID of the disposal record.

    Returns:
        ``DisposalResponse``.

    Raises:
        HTTPException 404: Disposal not found or wrong account.
    """
    row = await _fetch_disposal(db, account_id, disposal_id)
    return _disposal_to_response(row)


# ---------------------------------------------------------------------------
# get_vehicle_disposal
# ---------------------------------------------------------------------------


async def get_vehicle_disposal(
    db: AsyncSession,
    fleet_vehicle_id: uuid.UUID,
    account_id: int,
) -> Optional[DisposalResponse]:
    """Return the disposal record for a vehicle, or None if the vehicle is still active.

    Args:
        db: Async SQLAlchemy session.
        fleet_vehicle_id: UUID of the fleet vehicle.
        account_id: Corporate account ID.

    Returns:
        ``DisposalResponse`` or None.
    """
    stmt = select(CorporateFleetVehicleDisposal).where(
        CorporateFleetVehicleDisposal.fleet_vehicle_id == fleet_vehicle_id,
        CorporateFleetVehicleDisposal.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return _disposal_to_response(row) if row is not None else None


# ---------------------------------------------------------------------------
# list_account_disposals
# ---------------------------------------------------------------------------


async def list_account_disposals(
    db: AsyncSession,
    account_id: int,
    *,
    disposal_reason: Optional[DisposalReason] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[DisposalResponse]:
    """Return all disposal records for an account, with optional filters.

    Results are ordered by disposal_date descending.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        disposal_reason: Optional filter by reason.
        from_date: Optional inclusive start date filter on disposal_date.
        to_date: Optional inclusive end date filter on disposal_date.
        skip: Records to skip (default 0).
        limit: Max records to return (default 50).

    Returns:
        List of ``DisposalResponse``.
    """
    conditions = [CorporateFleetVehicleDisposal.account_id == account_id]
    if disposal_reason is not None:
        conditions.append(
            CorporateFleetVehicleDisposal.disposal_reason == disposal_reason
        )
    if from_date is not None:
        conditions.append(CorporateFleetVehicleDisposal.disposal_date >= from_date)
    if to_date is not None:
        conditions.append(CorporateFleetVehicleDisposal.disposal_date <= to_date)

    stmt = (
        select(CorporateFleetVehicleDisposal)
        .where(and_(*conditions))
        .order_by(CorporateFleetVehicleDisposal.disposal_date.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_disposal_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# get_fleet_ownership_summary
# ---------------------------------------------------------------------------


async def get_fleet_ownership_summary(
    db: AsyncSession,
    account_id: int,
) -> FleetOwnershipSummary:
    """Return aggregate fleet ownership and financial statistics for an account.

    Computes:
    - total_vehicles: all vehicles ever recorded (active and retired).
    - active_vehicles: vehicles with is_active=True.
    - retired_vehicles: vehicles that have a disposal record.
    - by_acquisition_type: active-vehicle count per AcquisitionType.
    - total_monthly_lease_payments_usd: sum of lease payments for active leased vehicles.
    - total_monthly_loan_payments_usd: sum of loan payments for active financed vehicles.
    - leases_expiring_within_90_days: active leased vehicles with lease_end_date within 90 days.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.

    Returns:
        ``FleetOwnershipSummary``.
    """
    today = date.today()
    cutoff_90 = today + timedelta(days=90)

    # All fleet vehicles for this account.
    vehicle_stmt = select(CorporateFleetVehicle).where(
        CorporateFleetVehicle.account_id == account_id
    )
    vehicle_result = await db.execute(vehicle_stmt)
    all_vehicles = list(vehicle_result.scalars().all())

    total_vehicles = len(all_vehicles)
    active_vehicles = sum(1 for v in all_vehicles if v.is_active)

    # Disposal count (vehicles with a disposal record).
    disposal_stmt = select(CorporateFleetVehicleDisposal).where(
        CorporateFleetVehicleDisposal.account_id == account_id
    )
    disposal_result = await db.execute(disposal_stmt)
    disposals = list(disposal_result.scalars().all())
    retired_vehicles = len(disposals)

    # Active acquisitions for per-type counts and financial aggregates.
    acq_stmt = select(CorporateFleetVehicleAcquisition).where(
        CorporateFleetVehicleAcquisition.account_id == account_id,
        CorporateFleetVehicleAcquisition.is_active == True,  # noqa: E712
    )
    acq_result = await db.execute(acq_stmt)
    active_acquisitions = list(acq_result.scalars().all())

    by_type: dict[str, int] = {t.value: 0 for t in AcquisitionType}
    total_lease_payments = 0.0
    total_loan_payments = 0.0
    leases_expiring = 0

    for acq in active_acquisitions:
        key = (
            acq.acquisition_type.value
            if hasattr(acq.acquisition_type, "value")
            else str(acq.acquisition_type)
        )
        by_type[key] = by_type.get(key, 0) + 1

        if acq.acquisition_type == AcquisitionType.leased:
            if acq.monthly_lease_payment_usd is not None:
                total_lease_payments += float(acq.monthly_lease_payment_usd)
            if (
                acq.lease_end_date is not None
                and today <= acq.lease_end_date <= cutoff_90
            ):
                leases_expiring += 1

        if acq.acquisition_type == AcquisitionType.financed:
            if acq.monthly_loan_payment_usd is not None:
                total_loan_payments += float(acq.monthly_loan_payment_usd)

    return FleetOwnershipSummary(
        total_vehicles=total_vehicles,
        active_vehicles=active_vehicles,
        retired_vehicles=retired_vehicles,
        by_acquisition_type=by_type,
        total_monthly_lease_payments_usd=round(total_lease_payments, 2),
        total_monthly_loan_payments_usd=round(total_loan_payments, 2),
        leases_expiring_within_90_days=leases_expiring,
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
) -> list[AcquisitionResponse]:
    """Return acquisition records across all corporate accounts (platform admin).

    Args:
        db: Async SQLAlchemy session.
        account_id: Optional filter to a specific account.
        skip: Records to skip (default 0).
        limit: Max records to return (default 100).

    Returns:
        List of ``AcquisitionResponse``.
    """
    conditions = []
    if account_id is not None:
        conditions.append(
            CorporateFleetVehicleAcquisition.account_id == account_id
        )

    base = select(CorporateFleetVehicleAcquisition)
    if conditions:
        base = base.where(and_(*conditions))

    stmt = (
        base.order_by(
            CorporateFleetVehicleAcquisition.account_id,
            CorporateFleetVehicleAcquisition.acquisition_date.desc(),
        )
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_acq_to_response(r) for r in rows]
