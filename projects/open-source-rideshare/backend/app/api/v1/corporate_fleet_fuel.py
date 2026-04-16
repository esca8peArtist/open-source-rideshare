"""Corporate Fleet Fuel & Mileage Tracking endpoints.

Fleet managers and drivers log fuel fill-ups for company vehicles to track
fuel costs and efficiency over time.

Member endpoints (any authenticated account member):
  POST /corporate/{account_id}/fleet-fuel/                                    — log a fill-up → 201
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/fuel               — list vehicle logs
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/fuel/summary       — vehicle analytics
  GET  /corporate/{account_id}/fleet-fuel/{log_id}                            — get one log

Admin endpoints (account admins only):
  PUT    /corporate/{account_id}/fleet-fuel/{log_id}                          — update log
  DELETE /corporate/{account_id}/fleet-fuel/{log_id}                          — delete log (204)
  GET    /corporate/{account_id}/fleet-fuel/                                  — list all (filtered)
  GET    /corporate/{account_id}/fleet-fuel/fleet-summary                     — fleet analytics

Platform-admin endpoints:
  GET /platform/corporate/fleet-fuel/        — all logs across accounts
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_fleet_fuel_log import FleetFuelType
from app.models.user import User
from app.schemas.corporate_fleet_fuel_log import (
    FleetFuelSummary,
    FuelLogCreate,
    FuelLogResponse,
    FuelLogUpdate,
    VehicleFuelSummary,
)
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin
from app.services.corporate_fleet_fuel_service import (
    delete_fuel_log,
    get_fleet_fuel_summary,
    get_fuel_log,
    get_vehicle_fuel_summary,
    list_account_fuel_logs,
    list_all_platform,
    list_vehicle_fuel_logs,
    log_fuel_fill,
    update_fuel_log,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Fleet Fuel"])


# ---------------------------------------------------------------------------
# Member: log a fuel fill-up  ← MUST be before /{log_id}
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-fuel/",
    response_model=FuelLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log a fleet vehicle fuel fill-up",
)
async def log_fuel_fill_endpoint(
    account_id: int,
    data: FuelLogCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new fuel fill-up or energy charge log entry.

    Returns 404 if the fleet vehicle does not exist in this account.
    Any authenticated account member may log a fill-up.
    """
    await get_account(db, account_id)
    return await log_fuel_fill(db, account_id, data, logged_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: list all fuel logs for account  ← MUST be before /{log_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-fuel/",
    response_model=List[FuelLogResponse],
    summary="List fuel logs for the account (admin only)",
)
async def list_account_fuel_logs_endpoint(
    account_id: int,
    fleet_vehicle_id: Optional[uuid.UUID] = Query(
        None, description="Filter to a specific vehicle"
    ),
    fuel_type: Optional[FleetFuelType] = Query(None, description="Filter by fuel type"),
    from_date: Optional[date] = Query(None, description="Inclusive start date (YYYY-MM-DD)"),
    to_date: Optional[date] = Query(None, description="Inclusive end date (YYYY-MM-DD)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a filtered, paginated list of fuel logs for the account.

    Ordered by fill_date descending.  Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await list_account_fuel_logs(
        db,
        account_id,
        fleet_vehicle_id=fleet_vehicle_id,
        fuel_type=fuel_type,
        from_date=from_date,
        to_date=to_date,
        skip=skip,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Admin: fleet-wide fuel summary  ← MUST be before /{log_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-fuel/fleet-summary",
    response_model=FleetFuelSummary,
    summary="Get fleet-wide fuel analytics (admin only)",
)
async def get_fleet_fuel_summary_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return fleet-wide fuel cost and volume analytics for the account.

    Includes totals and per-fuel-type breakdowns.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_fleet_fuel_summary(db, account_id)


# ---------------------------------------------------------------------------
# Member: list fuel logs for a vehicle
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/fuel",
    response_model=List[FuelLogResponse],
    summary="List fuel logs for a fleet vehicle",
)
async def list_vehicle_fuel_logs_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    fuel_type: Optional[FleetFuelType] = Query(None, description="Filter by fuel type"),
    from_date: Optional[date] = Query(None, description="Inclusive start date (YYYY-MM-DD)"),
    to_date: Optional[date] = Query(None, description="Inclusive end date (YYYY-MM-DD)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all fuel logs for a specific fleet vehicle.

    Returns 404 if the vehicle does not exist in this account.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await list_vehicle_fuel_logs(
        db,
        account_id,
        vehicle_id,
        fuel_type=fuel_type,
        from_date=from_date,
        to_date=to_date,
        skip=skip,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Member: per-vehicle fuel summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/fuel/summary",
    response_model=VehicleFuelSummary,
    summary="Get fuel analytics for a fleet vehicle",
)
async def get_vehicle_fuel_summary_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return fuel cost and efficiency analytics for a specific fleet vehicle.

    Returns 404 if the vehicle does not exist in this account.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_vehicle_fuel_summary(db, account_id, vehicle_id)


# ---------------------------------------------------------------------------
# Member: get single fuel log
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-fuel/{log_id}",
    response_model=FuelLogResponse,
    summary="Get a single fuel log entry",
)
async def get_fuel_log_endpoint(
    account_id: int,
    log_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single fuel log by ID.

    Returns 404 if the log does not exist or belongs to a different account.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_fuel_log(db, account_id, log_id)


# ---------------------------------------------------------------------------
# Admin: update fuel log
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/fleet-fuel/{log_id}",
    response_model=FuelLogResponse,
    summary="Update a fuel log entry (admin only)",
)
async def update_fuel_log_endpoint(
    account_id: int,
    log_id: uuid.UUID,
    data: FuelLogUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a fuel log record.

    Returns 404 if the log does not exist or belongs to a different account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await update_fuel_log(db, account_id, log_id, data)


# ---------------------------------------------------------------------------
# Admin: delete fuel log
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/{account_id}/fleet-fuel/{log_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a fuel log entry (admin only)",
)
async def delete_fuel_log_endpoint(
    account_id: int,
    log_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete a fuel log record.

    Returns 404 if the log does not exist or belongs to a different account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    await delete_fuel_log(db, account_id, log_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all fuel logs
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/fleet-fuel/",
    response_model=List[FuelLogResponse],
    summary="Admin: list all fleet fuel logs across all accounts",
)
async def admin_list_fuel_logs(
    account_id: Optional[int] = Query(None, description="Filter by corporate account ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return fleet fuel logs across all corporate accounts.

    Platform admin only.  Optionally filter by account_id.
    """
    return await list_all_platform(db, account_id=account_id, skip=skip, limit=limit)
