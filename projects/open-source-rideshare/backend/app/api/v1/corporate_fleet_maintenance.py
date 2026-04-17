"""Corporate Fleet Maintenance Scheduling endpoints.

Fleet managers schedule preventive maintenance and log completed service
records for company vehicles.

Member endpoints (any authenticated account member):
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/scheduled-maintenance            — list vehicle maintenance
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/scheduled-maintenance/{record_id} — get one record
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/maintenance-summary              — vehicle summary

Admin endpoints (account admins only):
  POST   /corporate/{account_id}/fleet-vehicles/{vehicle_id}/scheduled-maintenance          — schedule → 201
  PUT    /corporate/{account_id}/fleet-maintenance/{record_id}                    — update
  POST   /corporate/{account_id}/fleet-maintenance/{record_id}/complete           — mark complete
  POST   /corporate/{account_id}/fleet-maintenance/{record_id}/cancel             — cancel
  DELETE /corporate/{account_id}/fleet-maintenance/{record_id}                    — delete → 204
  GET    /corporate/{account_id}/fleet-maintenance/                               — list all for account
  GET    /corporate/{account_id}/fleet-maintenance/overdue                        — overdue records
  GET    /corporate/{account_id}/fleet-maintenance-summary                        — account summary

Platform-admin endpoints:
  GET /platform/corporate/fleet-maintenance/              — all records
  GET /platform/corporate/fleet-maintenance/{account_id} — records for one account
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_fleet_maintenance import (
    FleetMaintenanceStatus,
    FleetMaintenanceType,
)
from app.models.user import User
from app.schemas.corporate_fleet_maintenance import (
    AccountMaintenanceSummaryResponse,
    MaintenanceRecordCreate,
    MaintenanceRecordResponse,
    MaintenanceRecordUpdate,
    VehicleMaintenanceSummaryResponse,
)
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin
from app.services.corporate_fleet_maintenance_service import (
    cancel_maintenance,
    complete_maintenance,
    delete_maintenance_record,
    get_account_maintenance_summary,
    get_maintenance_record,
    get_overdue_maintenance,
    get_vehicle_maintenance_summary,
    list_account_maintenance,
    list_all_platform,
    list_vehicle_maintenance,
    schedule_maintenance,
    update_maintenance_record,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Fleet Maintenance"])


# ---------------------------------------------------------------------------
# Member: list maintenance records for a specific vehicle
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/scheduled-maintenance",
    response_model=List[MaintenanceRecordResponse],
    summary="List scheduled maintenance records for a fleet vehicle",
)
async def list_vehicle_maintenance_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    status: Optional[FleetMaintenanceStatus] = Query(
        None, description="Filter by status"
    ),
    maintenance_type: Optional[FleetMaintenanceType] = Query(
        None, description="Filter by maintenance type"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return maintenance records for a specific fleet vehicle.

    Any authenticated account member may call this endpoint.
    Returns 404 if the vehicle does not exist in this account.
    """
    await get_account(db, account_id)
    return await list_vehicle_maintenance(
        db,
        account_id,
        vehicle_id,
        status=status,
        maintenance_type=maintenance_type,
        skip=skip,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Member: vehicle maintenance summary  <- MUST be before /{record_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/maintenance-summary",
    response_model=VehicleMaintenanceSummaryResponse,
    summary="Get maintenance summary for a fleet vehicle",
)
async def get_vehicle_maintenance_summary_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate maintenance statistics for a specific fleet vehicle.

    Any authenticated account member may call this endpoint.
    Returns 404 if the vehicle does not exist in this account.
    """
    await get_account(db, account_id)
    return await get_vehicle_maintenance_summary(db, account_id, vehicle_id)


# ---------------------------------------------------------------------------
# Member: get single maintenance record
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/scheduled-maintenance/{record_id}",
    response_model=MaintenanceRecordResponse,
    summary="Get a single fleet scheduled maintenance record",
)
async def get_maintenance_record_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    record_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single maintenance record by ID.

    Returns 404 if the record does not exist or belongs to a different account.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_maintenance_record(db, account_id, record_id)


# ---------------------------------------------------------------------------
# Admin: schedule maintenance  <- vehicle-scoped POST
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/scheduled-maintenance",
    response_model=MaintenanceRecordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Schedule a maintenance record for a fleet vehicle (admin only)",
)
async def schedule_maintenance_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    data: MaintenanceRecordCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Schedule a new maintenance record for a fleet vehicle.

    Returns 404 if the vehicle does not exist in this account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await schedule_maintenance(
        db, account_id, vehicle_id, data, created_by_id=user.id
    )


# ---------------------------------------------------------------------------
# Admin: list all maintenance for account  <- MUST be before /{record_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-maintenance/",
    response_model=List[MaintenanceRecordResponse],
    summary="List all fleet maintenance records for an account (admin only)",
)
async def list_account_maintenance_endpoint(
    account_id: int,
    vehicle_id: Optional[uuid.UUID] = Query(
        None, description="Filter to a specific vehicle"
    ),
    status: Optional[FleetMaintenanceStatus] = Query(
        None, description="Filter by status"
    ),
    maintenance_type: Optional[FleetMaintenanceType] = Query(
        None, description="Filter by maintenance type"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated, filtered list of maintenance records for the account.

    Ordered by scheduled_date ascending.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await list_account_maintenance(
        db,
        account_id,
        vehicle_id=vehicle_id,
        status=status,
        maintenance_type=maintenance_type,
        skip=skip,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Admin: get overdue records  <- MUST be before /{record_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-maintenance/overdue",
    response_model=List[MaintenanceRecordResponse],
    summary="Get overdue maintenance records for the account (admin only)",
)
async def get_overdue_maintenance_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return records that are past their scheduled date and mark them overdue.

    Records with status=scheduled or in_progress whose scheduled_date or
    next_service_date is in the past are automatically updated to
    status=overdue.  Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_overdue_maintenance(db, account_id)


# ---------------------------------------------------------------------------
# Admin: update maintenance record
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/fleet-maintenance/{record_id}",
    response_model=MaintenanceRecordResponse,
    summary="Update a fleet maintenance record (admin only)",
)
async def update_maintenance_record_endpoint(
    account_id: int,
    record_id: uuid.UUID,
    data: MaintenanceRecordUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a fleet maintenance record.

    Returns 404 if the record does not exist or belongs to a different account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await update_maintenance_record(db, account_id, record_id, data)


# ---------------------------------------------------------------------------
# Admin: complete maintenance record
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-maintenance/{record_id}/complete",
    response_model=MaintenanceRecordResponse,
    summary="Mark a fleet maintenance record as completed (admin only)",
)
async def complete_maintenance_endpoint(
    account_id: int,
    record_id: uuid.UUID,
    completed_date: Optional[date] = Query(None, description="Date the service was completed"),
    cost_usd: Optional[float] = Query(None, ge=0, description="Total service cost in USD"),
    odometer: Optional[int] = Query(None, ge=0, description="Odometer reading at service"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a maintenance record as completed.

    Sets status to completed.  Optionally records the completed_date,
    cost_usd, and odometer_at_service.  Returns 404 if the record does not
    exist or belongs to a different account.  Only account admins may call
    this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await complete_maintenance(
        db, account_id, record_id,
        completed_date=completed_date,
        cost_usd=cost_usd,
        odometer=odometer,
    )


# ---------------------------------------------------------------------------
# Admin: cancel maintenance record
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-maintenance/{record_id}/cancel",
    response_model=MaintenanceRecordResponse,
    summary="Cancel a fleet maintenance record (admin only)",
)
async def cancel_maintenance_endpoint(
    account_id: int,
    record_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a scheduled maintenance record.

    Returns 404 if the record does not exist or belongs to a different account.
    Returns 409 if the record is already completed or cancelled.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await cancel_maintenance(db, account_id, record_id)


# ---------------------------------------------------------------------------
# Admin: delete maintenance record
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/{account_id}/fleet-maintenance/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a fleet maintenance record (admin only)",
)
async def delete_maintenance_record_endpoint(
    account_id: int,
    record_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a fleet maintenance record.

    Returns 404 if the record does not exist or belongs to a different account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    await delete_maintenance_record(db, account_id, record_id)


# ---------------------------------------------------------------------------
# Admin: account-level maintenance summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-maintenance-summary",
    response_model=AccountMaintenanceSummaryResponse,
    summary="Get account-level fleet maintenance summary (admin only)",
)
async def get_account_maintenance_summary_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return account-wide aggregate maintenance statistics.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_account_maintenance_summary(db, account_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all maintenance records
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/fleet-maintenance/",
    response_model=List[MaintenanceRecordResponse],
    summary="Admin: list all fleet maintenance records across all accounts",
)
async def admin_list_fleet_maintenance(
    account_id: Optional[int] = Query(
        None, description="Filter by corporate account ID"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return fleet maintenance records across all corporate accounts.

    Platform admin only.  Optionally filter by account_id.
    """
    return await list_all_platform(db, account_id=account_id, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Platform-admin: list maintenance records for one account
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/fleet-maintenance/{account_id}",
    response_model=List[MaintenanceRecordResponse],
    summary="Admin: list fleet maintenance records for a specific corporate account",
)
async def admin_list_account_fleet_maintenance(
    account_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return fleet maintenance records for a specific corporate account.

    Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id, skip=skip, limit=limit)
