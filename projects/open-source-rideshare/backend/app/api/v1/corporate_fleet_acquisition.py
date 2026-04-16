"""Corporate Fleet Vehicle Acquisition and Disposal endpoints.

Fleet managers record how vehicles entered the fleet (purchased, leased,
financed, donated) and formally retire vehicles when they leave it.

Member endpoints (any authenticated account member):
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/acquisition         — active acquisition
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/acquisition/history — full history
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/disposal             — disposal record
  GET  /corporate/{account_id}/fleet-acquisition/summary                        — ownership summary

Admin endpoints (account admins only):
  POST /corporate/{account_id}/fleet-vehicles/{vehicle_id}/acquisition          — record acquisition
  PUT  /corporate/{account_id}/fleet-acquisition/{acquisition_id}               — update acquisition
  POST /corporate/{account_id}/fleet-vehicles/{vehicle_id}/dispose              — dispose vehicle
  GET  /corporate/{account_id}/fleet-acquisition/disposals                      — list all disposals
  GET  /corporate/{account_id}/fleet-acquisition/disposals/{disposal_id}        — get one disposal

Platform-admin endpoints:
  GET /platform/corporate/fleet-acquisition/     — all acquisitions across accounts
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_fleet_acquisition import DisposalReason
from app.models.user import User
from app.schemas.corporate_fleet_acquisition import (
    AcquisitionCreate,
    AcquisitionResponse,
    AcquisitionUpdate,
    DisposalCreate,
    DisposalResponse,
    FleetOwnershipSummary,
)
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin
from app.services.corporate_fleet_acquisition_service import (
    dispose_vehicle,
    get_acquisition,
    get_disposal,
    get_fleet_ownership_summary,
    get_vehicle_acquisition,
    get_vehicle_disposal,
    list_account_disposals,
    list_all_platform,
    list_vehicle_acquisitions,
    record_acquisition,
    update_acquisition,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Fleet Acquisition"])


# ---------------------------------------------------------------------------
# Member: fleet ownership summary  ← MUST be before param routes
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-acquisition/summary",
    response_model=FleetOwnershipSummary,
    summary="Get fleet ownership summary for the account",
)
async def get_fleet_ownership_summary_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate fleet ownership and financial statistics for the account.

    Includes vehicle counts by acquisition type, monthly payment totals for
    leased and financed vehicles, and a count of leases expiring within 90 days.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_fleet_ownership_summary(db, account_id)


# ---------------------------------------------------------------------------
# Admin: list all disposals  ← MUST be before /{disposal_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-acquisition/disposals",
    response_model=List[DisposalResponse],
    summary="List all vehicle disposals for the account (admin only)",
)
async def list_account_disposals_endpoint(
    account_id: int,
    disposal_reason: Optional[DisposalReason] = Query(
        None, description="Filter by disposal reason"
    ),
    from_date: Optional[str] = Query(
        None, description="Filter disposals on or after this date (YYYY-MM-DD)"
    ),
    to_date: Optional[str] = Query(
        None, description="Filter disposals on or before this date (YYYY-MM-DD)"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all disposal records for the account, ordered by disposal_date descending.

    Supports optional filtering by disposal_reason and date range.
    Only account admins may call this endpoint.
    """
    from datetime import date as _date

    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)

    parsed_from = _date.fromisoformat(from_date) if from_date else None
    parsed_to = _date.fromisoformat(to_date) if to_date else None

    return await list_account_disposals(
        db,
        account_id,
        disposal_reason=disposal_reason,
        from_date=parsed_from,
        to_date=parsed_to,
        skip=skip,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Admin: get single disposal
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-acquisition/disposals/{disposal_id}",
    response_model=DisposalResponse,
    summary="Get a specific disposal record (admin only)",
)
async def get_disposal_endpoint(
    account_id: int,
    disposal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single vehicle disposal record by ID.

    Returns 404 if the disposal does not exist or belongs to a different account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_disposal(db, account_id, disposal_id)


# ---------------------------------------------------------------------------
# Member: get active acquisition for a vehicle
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/acquisition",
    response_model=Optional[AcquisitionResponse],
    summary="Get the active acquisition record for a fleet vehicle",
)
async def get_vehicle_acquisition_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the active acquisition record for the specified fleet vehicle.

    Returns null if no active acquisition record exists.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_vehicle_acquisition(db, vehicle_id, account_id)


# ---------------------------------------------------------------------------
# Member: acquisition history for a vehicle
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/acquisition/history",
    response_model=List[AcquisitionResponse],
    summary="Get full acquisition history for a fleet vehicle",
)
async def list_vehicle_acquisitions_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all acquisition records for a fleet vehicle, newest first.

    Returns 404 if the vehicle does not exist in this account.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await list_vehicle_acquisitions(db, vehicle_id, account_id)


# ---------------------------------------------------------------------------
# Member: get disposal record for a vehicle
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/disposal",
    response_model=Optional[DisposalResponse],
    summary="Get the disposal record for a fleet vehicle",
)
async def get_vehicle_disposal_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the disposal record for the specified fleet vehicle.

    Returns null if the vehicle has not been disposed of.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_vehicle_disposal(db, vehicle_id, account_id)


# ---------------------------------------------------------------------------
# Admin: record acquisition for a vehicle
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/acquisition",
    response_model=AcquisitionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record how a fleet vehicle was acquired (admin only)",
)
async def record_acquisition_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    data: AcquisitionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or replace the active acquisition record for a fleet vehicle.

    If the vehicle already has an active acquisition, it is marked inactive
    and the new record becomes active.
    Returns 404 if the vehicle does not exist in this account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await record_acquisition(
        db, account_id, vehicle_id, data, created_by_id=user.id
    )


# ---------------------------------------------------------------------------
# Admin: update an acquisition record
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/fleet-acquisition/{acquisition_id}",
    response_model=AcquisitionResponse,
    summary="Update an acquisition record (admin only)",
)
async def update_acquisition_endpoint(
    account_id: int,
    acquisition_id: uuid.UUID,
    data: AcquisitionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update an acquisition record.

    Returns 404 if the acquisition does not exist or belongs to a different account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await update_acquisition(db, account_id, acquisition_id, data)


# ---------------------------------------------------------------------------
# Admin: dispose a vehicle
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/dispose",
    response_model=DisposalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Retire a fleet vehicle from the fleet (admin only)",
)
async def dispose_vehicle_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    data: DisposalCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retire a fleet vehicle by recording a disposal event.

    Marks the vehicle as inactive, deactivates its acquisition record (if any),
    and creates a disposal record.
    Returns 404 if the vehicle does not exist in this account.
    Returns 409 if the vehicle has already been disposed of.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await dispose_vehicle(
        db, account_id, vehicle_id, data, disposed_by_id=user.id
    )


# ---------------------------------------------------------------------------
# Platform-admin: list all acquisitions
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/fleet-acquisition/",
    response_model=List[AcquisitionResponse],
    summary="Admin: list all fleet acquisitions across all accounts",
)
async def admin_list_all_acquisitions(
    account_id: Optional[int] = Query(
        None, description="Filter by corporate account ID"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return fleet vehicle acquisition records across all corporate accounts.

    Platform admin only.  Optionally filter by account_id.
    """
    return await list_all_platform(db, account_id=account_id, skip=skip, limit=limit)
