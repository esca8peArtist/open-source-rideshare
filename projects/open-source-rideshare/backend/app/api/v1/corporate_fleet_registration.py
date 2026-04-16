"""Corporate Fleet Vehicle Registration Tracking endpoints.

Fleet managers track state/jurisdiction registration records for company
vehicles with expiry date alerts.

Member endpoints (any authenticated account member):
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/registrations  — list vehicle registrations
  GET  /corporate/{account_id}/fleet-registrations/expiring               — expiry alerts
  GET  /corporate/{account_id}/fleet-registrations/summary                — summary stats
  GET  /corporate/{account_id}/fleet-registrations/{registration_id}      — get one registration

Admin endpoints (account admins only):
  POST /corporate/{account_id}/fleet-registrations/                       — create → 201
  GET  /corporate/{account_id}/fleet-registrations/                       — list all (filtered)
  PUT  /corporate/{account_id}/fleet-registrations/{registration_id}      — update
  POST /corporate/{account_id}/fleet-registrations/{registration_id}/deactivate  — deactivate
  POST /corporate/{account_id}/fleet-registrations/{registration_id}/reactivate  — reactivate

Platform-admin endpoints:
  GET /platform/corporate/fleet-registrations/              — all records across accounts
  GET /platform/corporate/fleet-registrations/{account_id}  — records for one account
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_fleet_registration import (
    RegistrationCreate,
    RegistrationExpiringResponse,
    RegistrationResponse,
    RegistrationSummaryResponse,
    RegistrationUpdate,
)
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin
from app.services.corporate_fleet_registration_service import (
    deactivate_registration,
    get_account_registration_summary,
    get_expiring_registrations,
    get_registration,
    list_account_registrations,
    list_all_platform,
    list_vehicle_registrations,
    reactivate_registration,
    register_vehicle,
    update_registration,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Fleet Registration"])


# ---------------------------------------------------------------------------
# Member: list registrations for a specific vehicle
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/registrations",
    response_model=List[RegistrationResponse],
    summary="List registration records for a fleet vehicle",
)
async def list_vehicle_registrations_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all registration records for a specific fleet vehicle.

    Any authenticated account member may call this endpoint.
    Returns 404 if the vehicle does not exist in this account.
    """
    await get_account(db, account_id)
    return await list_vehicle_registrations(
        db, account_id, vehicle_id, is_active=is_active, skip=skip, limit=limit
    )


# ---------------------------------------------------------------------------
# Member: expiring registrations alert  <- MUST be before /{registration_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-registrations/expiring",
    response_model=List[RegistrationExpiringResponse],
    summary="List vehicle registrations expiring soon for the account",
)
async def get_expiring_registrations_endpoint(
    account_id: int,
    days_ahead: int = Query(30, ge=1, le=365, description="Look-ahead window in days"),
    fleet_vehicle_id: Optional[uuid.UUID] = Query(
        None, description="Filter to a specific vehicle"
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return active registrations expiring within the next N days.

    Results are ordered by expiration_date ascending (most urgent first).
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_expiring_registrations(
        db, account_id, days_ahead=days_ahead, fleet_vehicle_id=fleet_vehicle_id
    )


# ---------------------------------------------------------------------------
# Member: registration summary  <- MUST be before /{registration_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-registrations/summary",
    response_model=RegistrationSummaryResponse,
    summary="Get registration statistics for the account",
)
async def get_registration_summary_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate registration counts and fee totals for the account.

    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_account_registration_summary(db, account_id)


# ---------------------------------------------------------------------------
# Admin: create registration  <- MUST be before /{registration_id}
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-registrations/",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a fleet vehicle registration record (admin only)",
)
async def register_vehicle_endpoint(
    account_id: int,
    data: RegistrationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new vehicle registration record for a fleet vehicle.

    Returns 404 if the vehicle does not exist in this account.
    Returns 409 if the registration number already exists for this account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await register_vehicle(db, account_id, data, created_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: list all registrations  <- MUST be before /{registration_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-registrations/",
    response_model=List[RegistrationResponse],
    summary="List registration records for the account (admin only)",
)
async def list_account_registrations_endpoint(
    account_id: int,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    registration_state: Optional[str] = Query(
        None, description="Filter by state or jurisdiction"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated, filtered list of registration records for the account.

    Ordered by expiration_date ascending (soonest expiry first).
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await list_account_registrations(
        db,
        account_id,
        is_active=is_active,
        registration_state=registration_state,
        skip=skip,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Member: get single registration record
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-registrations/{registration_id}",
    response_model=RegistrationResponse,
    summary="Get a single vehicle registration record",
)
async def get_registration_endpoint(
    account_id: int,
    registration_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single vehicle registration record by ID.

    Returns 404 if the record does not exist or belongs to a different account.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_registration(db, account_id, registration_id)


# ---------------------------------------------------------------------------
# Admin: update registration record
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/fleet-registrations/{registration_id}",
    response_model=RegistrationResponse,
    summary="Update a vehicle registration record (admin only)",
)
async def update_registration_endpoint(
    account_id: int,
    registration_id: uuid.UUID,
    data: RegistrationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a vehicle registration record.

    Returns 404 if the record does not exist or belongs to a different account.
    Returns 409 if the registration number is already in use by another record.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await update_registration(db, account_id, registration_id, data)


# ---------------------------------------------------------------------------
# Admin: deactivate registration record
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-registrations/{registration_id}/deactivate",
    response_model=RegistrationResponse,
    summary="Deactivate a vehicle registration record (admin only)",
)
async def deactivate_registration_endpoint(
    account_id: int,
    registration_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a vehicle registration record as inactive.

    Returns 404 if the record does not exist or belongs to a different account.
    Returns 409 if the record is already inactive.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await deactivate_registration(db, account_id, registration_id)


# ---------------------------------------------------------------------------
# Admin: reactivate registration record
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-registrations/{registration_id}/reactivate",
    response_model=RegistrationResponse,
    summary="Reactivate a vehicle registration record (admin only)",
)
async def reactivate_registration_endpoint(
    account_id: int,
    registration_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a vehicle registration record as active.

    Returns 404 if the record does not exist or belongs to a different account.
    Returns 409 if the record is already active.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await reactivate_registration(db, account_id, registration_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all registration records
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/fleet-registrations/",
    response_model=List[RegistrationResponse],
    summary="Admin: list all fleet registration records across all accounts",
)
async def admin_list_fleet_registrations(
    account_id: Optional[int] = Query(None, description="Filter by corporate account ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return fleet registration records across all corporate accounts.

    Platform admin only.  Optionally filter by account_id.
    """
    return await list_all_platform(db, account_id=account_id, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Platform-admin: list registration records for one account
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/fleet-registrations/{account_id}",
    response_model=List[RegistrationResponse],
    summary="Admin: list fleet registration records for a specific corporate account",
)
async def admin_list_account_fleet_registrations(
    account_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return fleet registration records for a specific corporate account.

    Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id, skip=skip, limit=limit)
