"""Corporate Fleet Vehicle Management endpoints.

Enterprise corporate accounts can define a pool of company-owned or leased
vehicles and assign drivers to them.

Member endpoints (any authenticated user — account membership implicit):
  GET  /corporate/{account_id}/fleet-vehicles/          — list vehicles
  GET  /corporate/{account_id}/fleet-vehicles/summary   — fleet summary
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id} — get one vehicle

Admin endpoints (account admins only):
  POST   /corporate/{account_id}/fleet-vehicles/                        — create → 201
  PUT    /corporate/{account_id}/fleet-vehicles/{vehicle_id}            — update
  POST   /corporate/{account_id}/fleet-vehicles/{vehicle_id}/deactivate
  POST   /corporate/{account_id}/fleet-vehicles/{vehicle_id}/reactivate
  DELETE /corporate/{account_id}/fleet-vehicles/{vehicle_id}            — 204
  POST   /corporate/{account_id}/fleet-vehicles/{vehicle_id}/assign-driver → 201
  DELETE /corporate/{account_id}/fleet-vehicles/{vehicle_id}/assignment — end assignment
  GET    /corporate/{account_id}/fleet-vehicles/{vehicle_id}/assignments — history

Platform-admin endpoints:
  GET /platform/corporate/fleet-vehicles/           — all accounts (optional filter)
  GET /platform/corporate/fleet-vehicles/{account_id} — one account
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_fleet_vehicle import (
    FleetAssignmentCreate,
    FleetAssignmentResponse,
    FleetSummaryResponse,
    FleetVehicleCreate,
    FleetVehicleResponse,
    FleetVehicleUpdate,
)
from app.services.corporate_fleet_vehicle_service import (
    assign_driver,
    create_fleet_vehicle,
    deactivate_fleet_vehicle,
    delete_fleet_vehicle,
    end_assignment,
    get_active_assignment,
    get_fleet_summary,
    get_fleet_vehicle,
    list_all_platform,
    list_fleet_vehicles,
    list_vehicle_assignments,
    reactivate_fleet_vehicle,
    update_fleet_vehicle,
)
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Fleet Vehicles"])


# ---------------------------------------------------------------------------
# Member: list fleet vehicles
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/",
    response_model=List[FleetVehicleResponse],
    summary="List fleet vehicles for a corporate account",
)
async def list_fleet_vehicles_endpoint(
    account_id: int,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    is_wav: Optional[bool] = Query(None, description="Filter by WAV status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return fleet vehicles for a corporate account.

    Any authenticated user may call this endpoint.
    """
    await get_account(db, account_id)
    return await list_fleet_vehicles(
        db, account_id, is_active=is_active, is_wav=is_wav, limit=limit, offset=offset
    )


# ---------------------------------------------------------------------------
# Member: fleet summary  ← MUST be before /{vehicle_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/summary",
    response_model=FleetSummaryResponse,
    summary="Get fleet summary statistics for a corporate account",
)
async def get_fleet_summary_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate fleet statistics.

    Any authenticated user may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_fleet_summary(db, account_id)


# ---------------------------------------------------------------------------
# Member: get one vehicle
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}",
    response_model=FleetVehicleResponse,
    summary="Get a single fleet vehicle",
)
async def get_fleet_vehicle_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return details for a single fleet vehicle.

    Any authenticated user may call this endpoint.
    Returns 404 if the vehicle does not exist or does not belong to this account.
    """
    await get_account(db, account_id)
    return await get_fleet_vehicle(db, account_id, vehicle_id)


# ---------------------------------------------------------------------------
# Admin: create vehicle
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-vehicles/",
    response_model=FleetVehicleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a fleet vehicle (admin only)",
)
async def create_fleet_vehicle_endpoint(
    account_id: int,
    data: FleetVehicleCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new vehicle in the corporate fleet.

    Returns 409 if a vehicle with the same name already exists for this account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await create_fleet_vehicle(db, account_id, data, created_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: update vehicle
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}",
    response_model=FleetVehicleResponse,
    summary="Update a fleet vehicle (admin only)",
)
async def update_fleet_vehicle_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    data: FleetVehicleUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a fleet vehicle.

    Returns 409 if the new name collides with another vehicle.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await update_fleet_vehicle(db, account_id, vehicle_id, data)


# ---------------------------------------------------------------------------
# Admin: deactivate vehicle
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/deactivate",
    response_model=FleetVehicleResponse,
    summary="Deactivate a fleet vehicle (admin only)",
)
async def deactivate_fleet_vehicle_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a fleet vehicle.

    Returns 409 if the vehicle is already inactive.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await deactivate_fleet_vehicle(db, account_id, vehicle_id)


# ---------------------------------------------------------------------------
# Admin: reactivate vehicle
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/reactivate",
    response_model=FleetVehicleResponse,
    summary="Reactivate a fleet vehicle (admin only)",
)
async def reactivate_fleet_vehicle_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reactivate a deactivated fleet vehicle.

    Returns 409 if the vehicle is already active.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await reactivate_fleet_vehicle(db, account_id, vehicle_id)


# ---------------------------------------------------------------------------
# Admin: delete vehicle
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a fleet vehicle (admin only)",
)
async def delete_fleet_vehicle_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete a fleet vehicle.

    The vehicle must be deactivated first.  Returns 409 if still active.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    await delete_fleet_vehicle(db, account_id, vehicle_id)


# ---------------------------------------------------------------------------
# Admin: assign driver
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/assign-driver",
    response_model=FleetAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a driver to a fleet vehicle (admin only)",
)
async def assign_driver_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    data: FleetAssignmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign a driver to a fleet vehicle.

    Any previous active assignment is ended automatically.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await assign_driver(db, account_id, vehicle_id, data, assigned_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: end active assignment
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/assignment",
    response_model=FleetAssignmentResponse,
    summary="End the active driver assignment for a vehicle (admin only)",
)
async def end_assignment_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """End the current active driver assignment for a fleet vehicle.

    Returns 404 if no active assignment exists.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await end_assignment(db, account_id, vehicle_id)


# ---------------------------------------------------------------------------
# Admin: list assignment history
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/assignments",
    response_model=List[FleetAssignmentResponse],
    summary="List assignment history for a vehicle (admin only)",
)
async def list_vehicle_assignments_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the full assignment history for a fleet vehicle, newest-first.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await list_vehicle_assignments(
        db, account_id, vehicle_id, limit=limit, offset=offset
    )


# ---------------------------------------------------------------------------
# Platform-admin: list all fleet vehicles
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/fleet-vehicles/",
    response_model=List[FleetVehicleResponse],
    summary="Admin: list all corporate fleet vehicles across all accounts",
)
async def admin_list_fleet_vehicles(
    account_id: Optional[int] = Query(None, description="Filter by corporate account ID"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return fleet vehicles across all corporate accounts.

    Platform admin only.  Optionally filter by account_id.
    """
    return await list_all_platform(db, account_id=account_id, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Platform-admin: list vehicles for one account
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/fleet-vehicles/{account_id}",
    response_model=List[FleetVehicleResponse],
    summary="Admin: list fleet vehicles for a specific corporate account",
)
async def admin_list_account_fleet_vehicles(
    account_id: int,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return fleet vehicles for a specific corporate account.

    Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id, limit=limit, offset=offset)
