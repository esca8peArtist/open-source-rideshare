"""Corporate Fleet Fuel Log endpoints.

Fleet managers and drivers record fuel fill-ups and EV charging events for
company vehicles.

Member endpoints (any active account member):
  POST /api/v1/corporate/fleet/vehicles/{vehicle_id}/fuel-logs
      — Create a fuel log entry for a vehicle.
  GET  /api/v1/corporate/fleet/vehicles/{vehicle_id}/fuel-logs
      — List fuel logs for a vehicle.
  GET  /api/v1/corporate/fleet/vehicles/{vehicle_id}/fuel-logs/summary
      — Fuel analytics summary for a vehicle.

Member (owner) or admin endpoints:
  PUT    /api/v1/corporate/fleet/fuel-logs/{log_id}   — Update a log entry.
  DELETE /api/v1/corporate/fleet/fuel-logs/{log_id}   — Delete a log entry.

Admin-only endpoints:
  GET /api/v1/corporate/fleet/accounts/{account_id}/fuel-logs
      — Fleet-wide fuel log list for an account.
"""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.corporate_fleet_fuel_log import (
    FuelLogCreate,
    FuelLogResponse,
    FuelLogUpdate,
    VehicleFuelSummaryAnalytics,
)
from app.services.corporate_fleet_fuel_log_service import (
    create_fuel_log,
    delete_fuel_log,
    get_vehicle_fuel_summary,
    list_fuel_logs_for_account,
    list_fuel_logs_for_vehicle,
    update_fuel_log,
)

router = APIRouter(tags=["Corporate Fleet Fuel Logs"])


# ---------------------------------------------------------------------------
# Member: create a fuel log for a vehicle
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/fleet/vehicles/{vehicle_id}/fuel-logs",
    response_model=FuelLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a fuel log entry for a fleet vehicle (member)",
)
async def create_fuel_log_endpoint(
    vehicle_id: uuid.UUID,
    account_id: int = Query(..., description="Corporate account ID that owns the vehicle"),
    data: FuelLogCreate = ...,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a fuel fill-up or EV charge event for a fleet vehicle.

    The authenticated user must be an active member of the corporate account
    that owns the vehicle.  Returns 404 if the vehicle does not exist in
    that account.  The actor is automatically recorded as ``logged_by_id``.
    """
    return await create_fuel_log(
        db,
        account_id=account_id,
        vehicle_id=vehicle_id,
        data=data,
        actor_id=user.id,
    )


# ---------------------------------------------------------------------------
# Member: list fuel logs for a vehicle (summary must be before bare list)
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/fleet/vehicles/{vehicle_id}/fuel-logs/summary",
    response_model=VehicleFuelSummaryAnalytics,
    summary="Get fuel analytics summary for a fleet vehicle (member)",
)
async def get_vehicle_fuel_summary_endpoint(
    vehicle_id: uuid.UUID,
    account_id: int = Query(..., description="Corporate account ID that owns the vehicle"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return fuel cost and volume analytics for a specific fleet vehicle.

    Includes total fill-ups, total gallons, total kWh, total cost, and
    average cost per gallon / kWh.  The authenticated user must be an
    active member of the corporate account.
    """
    return await get_vehicle_fuel_summary(db, account_id, vehicle_id, user.id)


@router.get(
    "/corporate/fleet/vehicles/{vehicle_id}/fuel-logs",
    response_model=List[FuelLogResponse],
    summary="List fuel logs for a fleet vehicle (member)",
)
async def list_fuel_logs_for_vehicle_endpoint(
    vehicle_id: uuid.UUID,
    account_id: int = Query(..., description="Corporate account ID that owns the vehicle"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return fuel log entries for a specific fleet vehicle.

    Ordered by fill_date descending.  The authenticated user must be an
    active member of the corporate account.  Returns 404 if the vehicle
    does not exist in the account.
    """
    return await list_fuel_logs_for_vehicle(
        db, account_id, vehicle_id, user.id, skip=skip, limit=limit
    )


# ---------------------------------------------------------------------------
# Member (owner) or admin: update / delete a log entry
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/fleet/fuel-logs/{log_id}",
    response_model=FuelLogResponse,
    summary="Update a fuel log entry (owner or admin)",
)
async def update_fuel_log_endpoint(
    log_id: uuid.UUID,
    data: FuelLogUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a fuel log entry.

    The actor must either be the user who originally created the log
    (``logged_by_id == actor``) or be an active admin of the account.
    Returns 403 otherwise.  Returns 404 if the log does not exist.
    """
    return await update_fuel_log(db, log_id, data, user.id)


@router.delete(
    "/corporate/fleet/fuel-logs/{log_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a fuel log entry (owner or admin)",
)
async def delete_fuel_log_endpoint(
    log_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a fuel log entry.

    The actor must either own the log or be an active admin of the account.
    Returns 403 otherwise.  Returns 404 if the log does not exist.
    """
    await delete_fuel_log(db, log_id, user.id)


# ---------------------------------------------------------------------------
# Admin: fleet-wide fuel log list for an account
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/fleet/accounts/{account_id}/fuel-logs",
    response_model=List[FuelLogResponse],
    summary="List all fuel logs for a corporate account (admin only)",
)
async def list_fuel_logs_for_account_endpoint(
    account_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all fuel log entries across the fleet for a corporate account.

    Ordered by fill_date descending.  Only active account admins may call
    this endpoint.  Returns 403 for non-admins.
    """
    return await list_fuel_logs_for_account(db, account_id, user.id, skip=skip, limit=limit)
