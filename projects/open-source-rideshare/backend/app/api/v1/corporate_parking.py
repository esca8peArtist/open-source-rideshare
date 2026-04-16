"""Corporate Parking Management endpoints.

Enterprise accounts manage physical parking facilities, individual spots, and
spot assignments for employees.

Member endpoints (any authenticated account member):
  GET  /corporate/{account_id}/parking/facilities                  — list active facilities
  GET  /corporate/{account_id}/parking/my-spots                    — get own parking assignments

Admin endpoints (account admins only):
  POST /corporate/{account_id}/parking/facilities                  — create facility → 201
  GET  /corporate/{account_id}/parking/facilities/all              — list all facilities (with filters)
  GET  /corporate/{account_id}/parking/facilities/{facility_id}    — get facility
  PUT  /corporate/{account_id}/parking/facilities/{facility_id}    — update facility
  POST /corporate/{account_id}/parking/facilities/{facility_id}/deactivate — deactivate
  GET  /corporate/{account_id}/parking/facilities/{facility_id}/summary    — facility summary
  POST /corporate/{account_id}/parking/spots                       — add spot → 201
  GET  /corporate/{account_id}/parking/spots                       — list spots (with filters)
  GET  /corporate/{account_id}/parking/spots/{spot_id}             — get spot
  POST /corporate/{account_id}/parking/spots/{spot_id}/assign      — assign spot to member → 201
  POST /corporate/{account_id}/parking/spots/{spot_id}/end-assignment — end active assignment

Platform-admin endpoints:
  GET /platform/corporate/parking/all   — cross-account facility listing
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_parking import SpotType
from app.models.user import User
from app.schemas.corporate_parking import (
    AssignmentCreate,
    AssignmentResponse,
    FacilityCreate,
    FacilityResponse,
    FacilitySummaryResponse,
    FacilityUpdate,
    SpotCreate,
    SpotResponse,
)
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin
from app.services.corporate_parking_service import (
    add_spot,
    assign_spot_to_member,
    create_facility,
    deactivate_facility,
    end_assignment,
    get_facility,
    get_facility_summary,
    get_member_parking,
    get_spot,
    list_all_platform,
    list_facilities,
    list_spots,
    update_facility,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Parking Management"])


# ---------------------------------------------------------------------------
# Member: list active facilities  ← MUST be before /{facility_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/parking/facilities",
    response_model=List[FacilityResponse],
    summary="List active parking facilities for the account",
)
async def list_active_facilities_endpoint(
    account_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all active parking facilities for the account.

    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await list_facilities(db, account_id, is_active=True, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Member: get own parking assignments
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/parking/my-spots",
    response_model=List[AssignmentResponse],
    summary="Get the current user's parking assignments",
)
async def get_my_parking_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the calling user's active parking assignments for the account.

    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_member_parking(db, account_id, user.id)


# ---------------------------------------------------------------------------
# Admin: create facility
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/parking/facilities",
    response_model=FacilityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a parking facility (admin only)",
)
async def create_facility_endpoint(
    account_id: int,
    data: FacilityCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new parking facility for the account.

    Returns 409 if a facility with the same name already exists.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await create_facility(db, account_id, data, created_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: list all facilities  ← MUST be before /{facility_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/parking/facilities/all",
    response_model=List[FacilityResponse],
    summary="List all parking facilities for the account (admin only)",
)
async def list_all_facilities_endpoint(
    account_id: int,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all parking facilities including inactive ones.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await list_facilities(db, account_id, is_active=is_active, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Admin: get facility
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/parking/facilities/{facility_id}",
    response_model=FacilityResponse,
    summary="Get a specific parking facility (admin only)",
)
async def get_facility_endpoint(
    account_id: int,
    facility_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single parking facility by ID.

    Returns 404 if not found or belongs to a different account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_facility(db, facility_id, account_id)


# ---------------------------------------------------------------------------
# Admin: update facility
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/parking/facilities/{facility_id}",
    response_model=FacilityResponse,
    summary="Update a parking facility (admin only)",
)
async def update_facility_endpoint(
    account_id: int,
    facility_id: uuid.UUID,
    data: FacilityUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a parking facility.

    Returns 404 if not found. Returns 409 on name collision.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await update_facility(db, facility_id, account_id, data)


# ---------------------------------------------------------------------------
# Admin: deactivate facility  ← MUST be before /{facility_id}/summary
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/parking/facilities/{facility_id}/deactivate",
    response_model=FacilityResponse,
    summary="Deactivate a parking facility (admin only)",
)
async def deactivate_facility_endpoint(
    account_id: int,
    facility_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a parking facility.

    Returns 404 if not found. Returns 409 if already inactive.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await deactivate_facility(db, facility_id, account_id)


# ---------------------------------------------------------------------------
# Admin: facility summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/parking/facilities/{facility_id}/summary",
    response_model=FacilitySummaryResponse,
    summary="Get aggregate statistics for a parking facility (admin only)",
)
async def get_facility_summary_endpoint(
    account_id: int,
    facility_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return total/active/assigned/available spot counts and breakdown by type.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_facility_summary(db, account_id, facility_id)


# ---------------------------------------------------------------------------
# Admin: add spot
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/parking/spots",
    response_model=SpotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a parking spot to a facility (admin only)",
)
async def add_spot_endpoint(
    account_id: int,
    data: SpotCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a new parking spot to a facility.

    Returns 404 if the facility is not found.
    Returns 409 if a spot with the same identifier already exists in the facility.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await add_spot(db, account_id, data, created_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: list spots
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/parking/spots",
    response_model=List[SpotResponse],
    summary="List parking spots for the account (admin only)",
)
async def list_spots_endpoint(
    account_id: int,
    facility_id: Optional[uuid.UUID] = Query(None, description="Filter by facility ID"),
    spot_type: Optional[SpotType] = Query(None, description="Filter by spot type"),
    is_assigned: Optional[bool] = Query(None, description="Filter by assignment status"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a filtered list of parking spots.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await list_spots(
        db,
        account_id,
        facility_id=facility_id,
        spot_type=spot_type,
        is_assigned=is_assigned,
        is_active=is_active,
        skip=skip,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Admin: get spot
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/parking/spots/{spot_id}",
    response_model=SpotResponse,
    summary="Get a specific parking spot (admin only)",
)
async def get_spot_endpoint(
    account_id: int,
    spot_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single parking spot by ID.

    Returns 404 if not found or belongs to a different account.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_spot(db, spot_id, account_id)


# ---------------------------------------------------------------------------
# Admin: assign spot to member  ← MUST be before /spots/{spot_id}/end-assignment
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/parking/spots/{spot_id}/assign",
    response_model=AssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a parking spot to an employee (admin only)",
)
async def assign_spot_endpoint(
    account_id: int,
    spot_id: uuid.UUID,
    data: AssignmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign a parking spot to a corporate member.

    Returns 404 if the spot is not found.
    Returns 409 if the spot already has an active assignment.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await assign_spot_to_member(db, account_id, spot_id, data, assigned_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: end assignment
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/parking/spots/{spot_id}/end-assignment",
    response_model=AssignmentResponse,
    summary="End the active assignment for a parking spot (admin only)",
)
async def end_assignment_endpoint(
    account_id: int,
    spot_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """End the active assignment for a parking spot.

    Returns 404 if no active assignment exists for this spot.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await end_assignment(db, account_id, spot_id, ended_by_id=user.id)


# ---------------------------------------------------------------------------
# Platform-admin: cross-account listing
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/parking/all",
    response_model=List[FacilityResponse],
    summary="Admin: list all parking facilities across all accounts",
)
async def platform_list_all_endpoint(
    account_id: Optional[int] = Query(None, description="Filter by corporate account ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return parking facilities across all corporate accounts.

    Platform admin only. Optionally filter by account_id.
    """
    return await list_all_platform(db, account_id=account_id, skip=skip, limit=limit)
