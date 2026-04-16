"""Corporate Vehicle Maintenance Log endpoints.

Fleet managers track service history for company vehicles — oil changes,
inspections, tire rotations, brake services, and other maintenance events.

Member endpoints (any authenticated account member):
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/maintenance           — list vehicle history
  GET  /corporate/{account_id}/vehicle-maintenance/upcoming                       — upcoming alerts
  GET  /corporate/{account_id}/vehicle-maintenance/summary                        — summary stats

Admin endpoints (account admins only):
  POST /corporate/{account_id}/vehicle-maintenance/                               — create → 201
  GET  /corporate/{account_id}/vehicle-maintenance/                               — list all (filtered)
  GET  /corporate/{account_id}/vehicle-maintenance/{log_id}                       — get one
  PUT  /corporate/{account_id}/vehicle-maintenance/{log_id}                       — update
  POST /corporate/{account_id}/vehicle-maintenance/{log_id}/complete              — mark complete
  DELETE /corporate/{account_id}/vehicle-maintenance/{log_id}                    — delete (non-completed only)

Platform-admin endpoints:
  GET /platform/corporate/vehicle-maintenance/              — all records across accounts
  GET /platform/corporate/vehicle-maintenance/{account_id}  — records for one account
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_vehicle_maintenance_log import MaintenanceType
from app.models.user import User
from app.schemas.corporate_vehicle_maintenance_log import (
    MaintenanceLogComplete,
    MaintenanceLogCreate,
    MaintenanceLogResponse,
    MaintenanceSummaryResponse,
    MaintenanceUpcomingResponse,
    MaintenanceLogUpdate,
)
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin
from app.services.corporate_vehicle_maintenance_log_service import (
    complete_maintenance_record,
    create_maintenance_record,
    delete_maintenance_record,
    get_maintenance_record,
    get_maintenance_summary,
    get_upcoming_maintenance,
    list_all_platform,
    list_maintenance_records,
    list_vehicle_maintenance,
    update_maintenance_record,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Vehicle Maintenance"])


# ---------------------------------------------------------------------------
# Member: list maintenance history for a specific vehicle
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/maintenance",
    response_model=List[MaintenanceLogResponse],
    summary="List maintenance history for a fleet vehicle",
)
async def list_vehicle_maintenance_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all maintenance records for a specific fleet vehicle.

    Any authenticated account member may call this endpoint.
    Returns 404 if the vehicle does not exist in this account.
    """
    await get_account(db, account_id)
    return await list_vehicle_maintenance(
        db, account_id, vehicle_id, skip=skip, limit=limit
    )


# ---------------------------------------------------------------------------
# Member: upcoming maintenance alerts  ← MUST be before /{log_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/vehicle-maintenance/upcoming",
    response_model=List[MaintenanceUpcomingResponse],
    summary="List upcoming maintenance alerts for the account",
)
async def get_upcoming_maintenance_endpoint(
    account_id: int,
    days_ahead: int = Query(30, ge=1, le=365, description="Look-ahead window in days"),
    fleet_vehicle_id: Optional[uuid.UUID] = Query(
        None, description="Filter to a specific vehicle"
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return non-completed records with next_due_date within the next N days.

    Results are ordered by next_due_date ascending (most urgent first).
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_upcoming_maintenance(
        db, account_id, days_ahead=days_ahead, fleet_vehicle_id=fleet_vehicle_id
    )


# ---------------------------------------------------------------------------
# Member: maintenance summary  ← MUST be before /{log_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/vehicle-maintenance/summary",
    response_model=MaintenanceSummaryResponse,
    summary="Get maintenance statistics for the account",
)
async def get_maintenance_summary_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate maintenance counts and cost totals for the account.

    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_maintenance_summary(db, account_id)


# ---------------------------------------------------------------------------
# Admin: create maintenance record
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/vehicle-maintenance/",
    response_model=MaintenanceLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a vehicle maintenance record (admin only)",
)
async def create_maintenance_record_endpoint(
    account_id: int,
    data: MaintenanceLogCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new maintenance record for a fleet vehicle.

    Returns 404 if the vehicle does not exist in this account.
    Returns 409 if the vehicle is inactive.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await create_maintenance_record(db, account_id, data, created_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: list all maintenance records  ← MUST be before /{log_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/vehicle-maintenance/",
    response_model=List[MaintenanceLogResponse],
    summary="List maintenance records for the account (admin only)",
)
async def list_maintenance_records_endpoint(
    account_id: int,
    fleet_vehicle_id: Optional[uuid.UUID] = Query(None, description="Filter by vehicle UUID"),
    maintenance_type: Optional[MaintenanceType] = Query(
        None, description="Filter by maintenance category"
    ),
    is_completed: Optional[bool] = Query(None, description="Filter by completion status"),
    from_date: Optional[datetime] = Query(
        None, description="Filter: scheduled_date >= from_date"
    ),
    to_date: Optional[datetime] = Query(
        None, description="Filter: scheduled_date <= to_date"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated, filtered list of maintenance records for the account.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await list_maintenance_records(
        db,
        account_id,
        fleet_vehicle_id=fleet_vehicle_id,
        maintenance_type=maintenance_type,
        is_completed=is_completed,
        from_date=from_date,
        to_date=to_date,
        skip=skip,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Admin: get single maintenance record
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/vehicle-maintenance/{log_id}",
    response_model=MaintenanceLogResponse,
    summary="Get a single maintenance record (admin only)",
)
async def get_maintenance_record_endpoint(
    account_id: int,
    log_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single maintenance record by ID.

    Returns 404 if the record does not exist or belongs to a different account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_maintenance_record(db, account_id, log_id)


# ---------------------------------------------------------------------------
# Admin: update maintenance record
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/vehicle-maintenance/{log_id}",
    response_model=MaintenanceLogResponse,
    summary="Update a maintenance record (admin only)",
)
async def update_maintenance_record_endpoint(
    account_id: int,
    log_id: uuid.UUID,
    data: MaintenanceLogUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a maintenance record.

    Returns 404 if the record does not exist or belongs to a different account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await update_maintenance_record(db, account_id, log_id, data)


# ---------------------------------------------------------------------------
# Admin: mark maintenance record as completed
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/vehicle-maintenance/{log_id}/complete",
    response_model=MaintenanceLogResponse,
    summary="Mark a maintenance record as completed (admin only)",
)
async def complete_maintenance_record_endpoint(
    account_id: int,
    log_id: uuid.UUID,
    data: MaintenanceLogComplete = MaintenanceLogComplete(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a maintenance record as completed.

    Returns 404 if the record does not exist or belongs to a different account.
    Returns 409 if the record is already completed.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await complete_maintenance_record(
        db, account_id, log_id, data, completed_by_id=user.id
    )


# ---------------------------------------------------------------------------
# Admin: delete maintenance record
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/{account_id}/vehicle-maintenance/{log_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a maintenance record (admin only)",
)
async def delete_maintenance_record_endpoint(
    account_id: int,
    log_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a non-completed maintenance record.

    Returns 404 if the record does not exist or belongs to a different account.
    Returns 409 if the record is already completed.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    await delete_maintenance_record(db, account_id, log_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all maintenance records
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/vehicle-maintenance/",
    response_model=List[MaintenanceLogResponse],
    summary="Admin: list all vehicle maintenance records across all accounts",
)
async def admin_list_maintenance_records(
    account_id: Optional[int] = Query(None, description="Filter by corporate account ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return vehicle maintenance records across all corporate accounts.

    Platform admin only.  Optionally filter by account_id.
    """
    return await list_all_platform(db, account_id=account_id, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Platform-admin: list maintenance records for one account
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/vehicle-maintenance/{account_id}",
    response_model=List[MaintenanceLogResponse],
    summary="Admin: list vehicle maintenance records for a specific corporate account",
)
async def admin_list_account_maintenance_records(
    account_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return vehicle maintenance records for a specific corporate account.

    Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id, skip=skip, limit=limit)
