"""Corporate Fleet Toll & Transponder Management endpoints.

Fleet managers track toll transponders (E-ZPass, FasTrak, SunPass, etc.)
assigned to company vehicles and log individual toll charges for cost
analytics and expense reporting.

Member endpoints (any authenticated account member):
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/transponders         — list vehicle transponders
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/toll-charges         — list vehicle charges
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/toll-summary         — vehicle toll summary
  GET  /corporate/{account_id}/fleet-transponders/{transponder_id}              — get one transponder
  GET  /corporate/{account_id}/fleet-toll-charges/{charge_id}                  — get one charge

Admin endpoints (account admins only):
  POST   /corporate/{account_id}/fleet-transponders/                            — assign transponder → 201
  GET    /corporate/{account_id}/fleet-transponders/                            — list account transponders
  POST   /corporate/{account_id}/fleet-transponders/{transponder_id}/deactivate — deactivate
  POST   /corporate/{account_id}/fleet-transponders/{transponder_id}/reactivate — reactivate
  POST   /corporate/{account_id}/fleet-toll-charges/                            — log charge → 201
  PUT    /corporate/{account_id}/fleet-toll-charges/{charge_id}                — update charge
  DELETE /corporate/{account_id}/fleet-toll-charges/{charge_id}                — delete charge
  GET    /corporate/{account_id}/fleet-toll-charges/                            — list account charges
  GET    /corporate/{account_id}/fleet-toll-summary                             — fleet-wide summary

Platform-admin endpoints:
  GET /platform/corporate/fleet-transponders/              — all transponders across accounts
  GET /platform/corporate/fleet-transponders/{account_id} — transponders for one account
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_fleet_toll import TransponderProvider
from app.models.user import User
from app.schemas.corporate_fleet_toll import (
    FleetTollSummaryResponse,
    TollChargeCreate,
    TollChargeResponse,
    TollChargeUpdate,
    TransponderCreate,
    TransponderResponse,
    VehicleTollSummaryResponse,
)
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin
from app.services.corporate_fleet_toll_service import (
    assign_transponder,
    deactivate_transponder,
    delete_toll_charge,
    get_fleet_toll_summary,
    get_toll_charge,
    get_transponder,
    get_vehicle_toll_summary,
    list_account_toll_charges,
    list_account_transponders,
    list_all_platform,
    list_vehicle_toll_charges,
    list_vehicle_transponders,
    log_toll_charge,
    reactivate_transponder,
    update_toll_charge,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Fleet Toll"])


# ---------------------------------------------------------------------------
# Member: list transponders for a specific vehicle
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/transponders",
    response_model=List[TransponderResponse],
    summary="List toll transponders for a fleet vehicle",
)
async def list_vehicle_transponders_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all transponders assigned to a specific fleet vehicle.

    Any authenticated account member may call this endpoint.
    Returns 404 if the vehicle does not exist in this account.
    """
    await get_account(db, account_id)
    return await list_vehicle_transponders(
        db, account_id, vehicle_id, is_active=is_active, skip=skip, limit=limit
    )


# ---------------------------------------------------------------------------
# Member: list toll charges for a specific vehicle
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/toll-charges",
    response_model=List[TollChargeResponse],
    summary="List toll charges for a fleet vehicle",
)
async def list_vehicle_toll_charges_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    date_from: Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return toll charges for a specific fleet vehicle.

    Optionally filter by date range.  Results are ordered by charge_date
    descending (most recent first).
    Any authenticated account member may call this endpoint.
    """
    from datetime import date as date_type
    df = date_type.fromisoformat(date_from) if date_from else None
    dt = date_type.fromisoformat(date_to) if date_to else None
    await get_account(db, account_id)
    return await list_vehicle_toll_charges(
        db, account_id, vehicle_id, date_from=df, date_to=dt, skip=skip, limit=limit
    )


# ---------------------------------------------------------------------------
# Member: vehicle toll summary  <- MUST be before /{charge_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/toll-summary",
    response_model=VehicleTollSummaryResponse,
    summary="Get aggregate toll statistics for a fleet vehicle",
)
async def get_vehicle_toll_summary_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    date_from: Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate toll charge statistics for a fleet vehicle.

    Any authenticated account member may call this endpoint.
    """
    from datetime import date as date_type
    df = date_type.fromisoformat(date_from) if date_from else None
    dt = date_type.fromisoformat(date_to) if date_to else None
    await get_account(db, account_id)
    return await get_vehicle_toll_summary(db, account_id, vehicle_id, date_from=df, date_to=dt)


# ---------------------------------------------------------------------------
# Member: get a single transponder
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-transponders/{transponder_id}",
    response_model=TransponderResponse,
    summary="Get a single toll transponder",
)
async def get_transponder_endpoint(
    account_id: int,
    transponder_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single toll transponder record.

    Returns 404 if not found or belongs to a different account.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_transponder(db, account_id, transponder_id)


# ---------------------------------------------------------------------------
# Member: get a single toll charge
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-toll-charges/{charge_id}",
    response_model=TollChargeResponse,
    summary="Get a single toll charge record",
)
async def get_toll_charge_endpoint(
    account_id: int,
    charge_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single toll charge record.

    Returns 404 if not found or belongs to a different account.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_toll_charge(db, account_id, charge_id)


# ---------------------------------------------------------------------------
# Admin: assign a transponder  <- MUST be before /{transponder_id}
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-transponders/",
    response_model=TransponderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a toll transponder to a fleet vehicle (admin only)",
)
async def assign_transponder_endpoint(
    account_id: int,
    data: TransponderCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign a new toll transponder to a fleet vehicle.

    Returns 404 if the vehicle does not exist in this account.
    Returns 409 if the transponder number already exists for this account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await assign_transponder(db, account_id, data, assigned_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: list all transponders for account  <- MUST be before /{transponder_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-transponders/",
    response_model=List[TransponderResponse],
    summary="List all toll transponders for the account (admin only)",
)
async def list_account_transponders_endpoint(
    account_id: int,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    provider: Optional[TransponderProvider] = Query(None, description="Filter by provider"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated, filtered list of transponders for the account.

    Ordered by assigned_date descending (most recent first).
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await list_account_transponders(
        db, account_id, is_active=is_active, provider=provider, skip=skip, limit=limit
    )


# ---------------------------------------------------------------------------
# Admin: deactivate transponder
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-transponders/{transponder_id}/deactivate",
    response_model=TransponderResponse,
    summary="Deactivate a toll transponder (admin only)",
)
async def deactivate_transponder_endpoint(
    account_id: int,
    transponder_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a toll transponder as inactive and record the removal date.

    Returns 404 if not found or belongs to a different account.
    Returns 409 if already inactive.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await deactivate_transponder(db, account_id, transponder_id)


# ---------------------------------------------------------------------------
# Admin: reactivate transponder
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-transponders/{transponder_id}/reactivate",
    response_model=TransponderResponse,
    summary="Reactivate a toll transponder (admin only)",
)
async def reactivate_transponder_endpoint(
    account_id: int,
    transponder_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a toll transponder as active and clear the removal date.

    Returns 404 if not found or belongs to a different account.
    Returns 409 if already active.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await reactivate_transponder(db, account_id, transponder_id)


# ---------------------------------------------------------------------------
# Admin: log a toll charge  <- MUST be before /{charge_id}
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/fleet-toll-charges/",
    response_model=TollChargeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log a toll charge for a fleet vehicle (admin only)",
)
async def log_toll_charge_endpoint(
    account_id: int,
    data: TollChargeCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Log an individual toll charge for a fleet vehicle.

    Returns 404 if the vehicle does not exist in this account.
    Returns 404 if the transponder is provided but not found in this account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await log_toll_charge(db, account_id, data, logged_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: list account toll charges  <- MUST be before /{charge_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-toll-charges/",
    response_model=List[TollChargeResponse],
    summary="List toll charges for the account (admin only)",
)
async def list_account_toll_charges_endpoint(
    account_id: int,
    fleet_vehicle_id: Optional[uuid.UUID] = Query(None, description="Filter by vehicle"),
    date_from: Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated, filtered list of toll charges for the account.

    Ordered by charge_date descending (most recent first).
    Only account admins may call this endpoint.
    """
    from datetime import date as date_type
    df = date_type.fromisoformat(date_from) if date_from else None
    dt = date_type.fromisoformat(date_to) if date_to else None
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await list_account_toll_charges(
        db, account_id, fleet_vehicle_id=fleet_vehicle_id, date_from=df, date_to=dt,
        skip=skip, limit=limit,
    )


# ---------------------------------------------------------------------------
# Admin: fleet-wide toll summary  <- MUST be before /{charge_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-toll-summary",
    response_model=FleetTollSummaryResponse,
    summary="Get fleet-wide toll statistics for the account (admin only)",
)
async def get_fleet_toll_summary_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return fleet-wide aggregate toll cost statistics.

    Includes per-provider cost breakdown and top vehicles by toll spend.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_fleet_toll_summary(db, account_id)


# ---------------------------------------------------------------------------
# Admin: update a toll charge
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/fleet-toll-charges/{charge_id}",
    response_model=TollChargeResponse,
    summary="Update a toll charge record (admin only)",
)
async def update_toll_charge_endpoint(
    account_id: int,
    charge_id: uuid.UUID,
    data: TollChargeUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a toll charge record.

    Returns 404 if not found or belongs to a different account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await update_toll_charge(db, account_id, charge_id, data)


# ---------------------------------------------------------------------------
# Admin: delete a toll charge
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/{account_id}/fleet-toll-charges/{charge_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a toll charge record (admin only)",
)
async def delete_toll_charge_endpoint(
    account_id: int,
    charge_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a toll charge record.

    Returns 404 if not found or belongs to a different account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    await delete_toll_charge(db, account_id, charge_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all transponders
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/fleet-transponders/",
    response_model=List[TransponderResponse],
    summary="Admin: list all fleet transponders across all accounts",
)
async def admin_list_fleet_transponders(
    account_id: Optional[int] = Query(None, description="Filter by corporate account ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return toll transponders across all corporate accounts.

    Platform admin only.  Optionally filter by account_id.
    """
    return await list_all_platform(db, account_id=account_id, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Platform-admin: list transponders for one account
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/fleet-transponders/{account_id}",
    response_model=List[TransponderResponse],
    summary="Admin: list fleet transponders for a specific corporate account",
)
async def admin_list_account_fleet_transponders(
    account_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return toll transponders for a specific corporate account.

    Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id, skip=skip, limit=limit)
