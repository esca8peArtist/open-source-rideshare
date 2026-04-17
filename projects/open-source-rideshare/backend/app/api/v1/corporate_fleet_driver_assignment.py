"""Corporate Fleet Driver Assignment endpoints.

Fleet admins assign corporate account members to fleet vehicles, tracking
who is the primary, secondary, pool, or temporary driver of each vehicle.

Member endpoints (any authenticated account member):
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/driver-assignments              — list assignments for vehicle
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/driver-assignments/primary      — active primary driver
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/driver-assignments/{assignment_id} — get one assignment

Admin endpoints (account admins only):
  POST   /corporate/{account_id}/fleet-vehicles/{vehicle_id}/driver-assignments                         — create → 201
  PUT    /corporate/{account_id}/fleet-driver-assignments/{assignment_id}                               — update
  POST   /corporate/{account_id}/fleet-driver-assignments/{assignment_id}/activate                      — activate pending
  POST   /corporate/{account_id}/fleet-driver-assignments/{assignment_id}/suspend                       — suspend active
  POST   /corporate/{account_id}/fleet-driver-assignments/{assignment_id}/end                           — end assignment
  DELETE /corporate/{account_id}/fleet-driver-assignments/{assignment_id}                               — delete inactive → 204
  GET    /corporate/{account_id}/fleet-driver-assignments/                                              — all for account
  GET    /corporate/{account_id}/fleet-driver-assignments/active                                        — active only

Platform-admin endpoints:
  GET /admin/fleet-driver-assignments  — list all assignments across all accounts
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_fleet_driver_assignment import FleetDriverAssignmentStatus
from app.models.user import User
from app.schemas.corporate_fleet_driver_assignment import (
    DriverAssignmentCreate,
    DriverAssignmentResponse,
    DriverAssignmentUpdate,
    EndAssignmentRequest,
)
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin
from app.services.corporate_fleet_driver_assignment_service import (
    activate_assignment,
    create_assignment,
    delete_assignment,
    end_assignment,
    get_account_assignments,
    get_active_primary_driver,
    get_assignment,
    get_vehicle_assignments,
    list_all_assignments,
    suspend_assignment,
    update_assignment,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Fleet Driver Assignments"])


# ---------------------------------------------------------------------------
# Member: list assignments for a vehicle
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/driver-assignments",
    response_model=List[DriverAssignmentResponse],
    summary="List driver assignments for a fleet vehicle",
)
async def list_vehicle_driver_assignments(
    account_id: int,
    vehicle_id: uuid.UUID,
    status: Optional[FleetDriverAssignmentStatus] = Query(
        None, description="Filter by assignment status"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all driver assignments for a specific fleet vehicle.

    Any authenticated account member may call this endpoint.
    Returns 404 if the vehicle does not exist in this account.
    """
    await get_account(db, account_id)
    return await get_vehicle_assignments(
        db, account_id, vehicle_id, status=status, skip=skip, limit=limit
    )


# ---------------------------------------------------------------------------
# Member: get active primary driver  <- MUST be before /{assignment_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/driver-assignments/primary",
    response_model=Optional[DriverAssignmentResponse],
    summary="Get the active primary driver assignment for a fleet vehicle",
)
async def get_primary_driver_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the active primary driver assignment for a vehicle, or null.

    Any authenticated account member may call this endpoint.
    Returns 404 if the vehicle does not exist in this account.
    """
    await get_account(db, account_id)
    return await get_active_primary_driver(db, account_id, vehicle_id)


# ---------------------------------------------------------------------------
# Member: get single assignment
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/driver-assignments/{assignment_id}",
    response_model=DriverAssignmentResponse,
    summary="Get a single fleet driver assignment",
)
async def get_driver_assignment_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    assignment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single driver assignment by ID.

    Returns 404 if the assignment does not exist or belongs to a different account.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_assignment(db, account_id, assignment_id)


# ---------------------------------------------------------------------------
# Admin: create assignment  <- vehicle-scoped POST
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/driver-assignments",
    response_model=DriverAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a driver assignment for a fleet vehicle (admin only)",
)
async def create_driver_assignment_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    data: DriverAssignmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new driver assignment for a fleet vehicle.

    Enforces primary driver uniqueness — creating a new primary assignment
    automatically ends any existing active primary for that vehicle.
    At most 2 active secondary drivers are permitted per vehicle.

    Returns 404 if the vehicle does not exist in this account.
    Returns 409 if the secondary driver limit would be exceeded.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await create_assignment(
        db,
        account_id=account_id,
        vehicle_id=vehicle_id,
        user_id=data.user_id,
        assignment_type=data.assignment_type,
        start_date=data.start_date,
        authorized_by_user_id=data.authorized_by_user_id,
        end_date=data.end_date,
        notes=data.notes,
    )


# ---------------------------------------------------------------------------
# Admin: list all assignments for account  <- MUST be before /{assignment_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-driver-assignments/",
    response_model=List[DriverAssignmentResponse],
    summary="List all fleet driver assignments for an account (admin only)",
)
async def list_account_driver_assignments(
    account_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all driver assignments for the corporate account.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_account_assignments(
        db, account_id, active_only=False, skip=skip, limit=limit
    )


# ---------------------------------------------------------------------------
# Admin: list active assignments for account  <- MUST be before /{assignment_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-driver-assignments/active",
    response_model=List[DriverAssignmentResponse],
    summary="List active fleet driver assignments for an account (admin only)",
)
async def list_active_account_driver_assignments(
    account_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return only active driver assignments for the corporate account.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_account_assignments(
        db, account_id, active_only=True, skip=skip, limit=limit
    )


# ---------------------------------------------------------------------------
# Admin: update assignment
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/fleet-driver-assignments/{assignment_id}",
    response_model=DriverAssignmentResponse,
    summary="Update a fleet driver assignment (admin only)",
)
async def update_driver_assignment_endpoint(
    account_id: int,
    assignment_id: uuid.UUID,
    data: DriverAssignmentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a driver assignment (end_date, notes, status).

    Returns 404 if the assignment does not exist or belongs to a different account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await update_assignment(db, account_id, assignment_id, data)


# ---------------------------------------------------------------------------
# Admin: activate pending assignment
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-driver-assignments/{assignment_id}/activate",
    response_model=DriverAssignmentResponse,
    summary="Activate a pending fleet driver assignment (admin only)",
)
async def activate_driver_assignment_endpoint(
    account_id: int,
    assignment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Transition a pending driver assignment to active.

    Returns 404 if the assignment does not exist or belongs to a different account.
    Returns 409 if the assignment is not in pending status.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await activate_assignment(db, account_id, assignment_id)


# ---------------------------------------------------------------------------
# Admin: suspend active assignment
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-driver-assignments/{assignment_id}/suspend",
    response_model=DriverAssignmentResponse,
    summary="Suspend an active fleet driver assignment (admin only)",
)
async def suspend_driver_assignment_endpoint(
    account_id: int,
    assignment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Transition an active driver assignment to suspended.

    Returns 404 if the assignment does not exist or belongs to a different account.
    Returns 409 if the assignment is not in active status.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await suspend_assignment(db, account_id, assignment_id)


# ---------------------------------------------------------------------------
# Admin: end assignment
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-driver-assignments/{assignment_id}/end",
    response_model=DriverAssignmentResponse,
    summary="End an active or suspended fleet driver assignment (admin only)",
)
async def end_driver_assignment_endpoint(
    account_id: int,
    assignment_id: uuid.UUID,
    body: Optional[EndAssignmentRequest] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Transition an active or suspended assignment to inactive.

    Sets end_date to today if not specified in the request body.
    Returns 404 if the assignment does not exist or belongs to a different account.
    Returns 409 if the assignment is not in active or suspended status.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    end_date_value = body.end_date if body is not None else None
    return await end_assignment(db, account_id, assignment_id, end_date=end_date_value)


# ---------------------------------------------------------------------------
# Admin: delete inactive assignment
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/{account_id}/fleet-driver-assignments/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an inactive fleet driver assignment (admin only)",
)
async def delete_driver_assignment_endpoint(
    account_id: int,
    assignment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a fleet driver assignment record.

    Only inactive assignments may be deleted.
    Returns 404 if the assignment does not exist or belongs to a different account.
    Returns 409 if the assignment is not inactive.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    await delete_assignment(db, account_id, assignment_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all driver assignments
# ---------------------------------------------------------------------------


@router.get(
    "/admin/fleet-driver-assignments",
    response_model=List[DriverAssignmentResponse],
    summary="Admin: list all fleet driver assignments across all accounts",
)
async def admin_list_fleet_driver_assignments(
    account_id: Optional[int] = Query(
        None, description="Filter by corporate account ID"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return fleet driver assignments across all corporate accounts.

    Platform admin only.  Optionally filter by account_id.
    """
    return await list_all_assignments(db, account_id=account_id, skip=skip, limit=limit)
