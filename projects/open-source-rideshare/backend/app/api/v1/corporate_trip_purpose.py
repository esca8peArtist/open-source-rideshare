"""Corporate Trip Purpose Code endpoints.

Member endpoints (any active member):
  GET  /corporate/accounts/me/trip-purposes                   — list active purposes
  GET  /corporate/accounts/me/trip-purposes/{purpose_id}      — get purpose
  POST /corporate/accounts/me/trip-purposes/analytics         — spend by purpose

Admin endpoints (account admins only):
  POST   /corporate/accounts/me/trip-purposes                          — create purpose
  PATCH  /corporate/accounts/me/trip-purposes/{purpose_id}             — update purpose
  DELETE /corporate/accounts/me/trip-purposes/{purpose_id}             — deactivate purpose

Rider endpoints (authenticated riders):
  PUT  /rides/{ride_id}/trip-purpose                          — tag or clear ride purpose

Platform-admin endpoints:
  GET  /admin/corporate/accounts/{account_id}/trip-purposes            — list all purposes
  GET  /admin/corporate/accounts/{account_id}/trip-purposes/analytics  — spend analytics
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_trip_purpose import (
    CorporateTripPurposeCreate,
    CorporateTripPurposeResponse,
    CorporateTripPurposeUpdate,
    SetRideTripPurposeRequest,
    TripPurposeAnalyticsRequest,
    TripPurposeSpendResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_trip_purpose import (
    _require_account_admin,
    create_purpose,
    deactivate_purpose,
    get_purpose,
    get_purpose_spend_analytics,
    list_purposes,
    set_ride_purpose,
    update_purpose,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-trip-purpose"])


# ---------------------------------------------------------------------------
# Internal helper: resolve the calling user's account_id
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the account_id for the authenticated user.

    Raises HTTP 404 if the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Member: list purposes
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/trip-purposes",
    response_model=list[CorporateTripPurposeResponse],
    summary="List trip purpose codes for own corporate account",
)
async def list_my_purposes(
    include_inactive: bool = Query(False, description="Include inactive purposes (admin use)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all trip purpose codes for the authenticated user's corporate account.

    Active purposes are always returned.  Pass ``include_inactive=true`` to also
    include deactivated purposes (useful for historical analytics).
    """
    account_id = await _resolve_account_id(db, user.id)
    purposes = await list_purposes(db, account_id, include_inactive=include_inactive)
    return [CorporateTripPurposeResponse.model_validate(p) for p in purposes]


# ---------------------------------------------------------------------------
# Member: get purpose
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/trip-purposes/{purpose_id}",
    response_model=CorporateTripPurposeResponse,
    summary="Get a trip purpose code for own corporate account",
)
async def get_my_purpose(
    purpose_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single trip purpose code by ID.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    purpose = await get_purpose(db, account_id, purpose_id)
    if purpose is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip purpose not found.",
        )
    return CorporateTripPurposeResponse.model_validate(purpose)


# ---------------------------------------------------------------------------
# Member: spend analytics by purpose
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/trip-purposes/analytics",
    response_model=TripPurposeSpendResponse,
    summary="Get spend breakdown by trip purpose for own corporate account",
)
async def get_my_purpose_analytics(
    body: TripPurposeAnalyticsRequest = TripPurposeAnalyticsRequest(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return completed-ride spend broken down by trip purpose code.

    An optional date range may be provided in the request body.  Rides without
    a purpose tag are counted in the ``untagged`` bucket.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_purpose_spend_analytics(
        db,
        account_id,
        start_date=body.start_date,
        end_date=body.end_date,
    )


# ---------------------------------------------------------------------------
# Admin: create purpose
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/trip-purposes",
    response_model=CorporateTripPurposeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a trip purpose code (admin only)",
)
async def create_my_purpose(
    data: CorporateTripPurposeCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new trip purpose code for the authenticated user's account.

    The code is normalised to uppercase.  Duplicate codes within the account
    result in a 409 Conflict.  Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)

    purpose, err = await create_purpose(db, account_id, data)
    if err is not None:
        raise err
    return CorporateTripPurposeResponse.model_validate(purpose)


# ---------------------------------------------------------------------------
# Admin: update purpose
# ---------------------------------------------------------------------------


@router.patch(
    "/corporate/accounts/me/trip-purposes/{purpose_id}",
    response_model=CorporateTripPurposeResponse,
    summary="Update a trip purpose code (admin only)",
)
async def update_my_purpose(
    purpose_id: int,
    data: CorporateTripPurposeUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the label, active status, or notes requirement of a purpose code.

    Only non-None fields in the request body are applied.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)

    purpose, err = await update_purpose(db, account_id, purpose_id, data)
    if err is not None:
        raise err
    return CorporateTripPurposeResponse.model_validate(purpose)


# ---------------------------------------------------------------------------
# Admin: deactivate purpose
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/trip-purposes/{purpose_id}",
    response_model=CorporateTripPurposeResponse,
    summary="Deactivate a trip purpose code (admin only)",
)
async def deactivate_my_purpose(
    purpose_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set is_active=False on a purpose code.

    The purpose is not deleted — rides that reference it retain the tag.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)

    purpose, err = await deactivate_purpose(db, account_id, purpose_id)
    if err is not None:
        raise err
    return CorporateTripPurposeResponse.model_validate(purpose)


# ---------------------------------------------------------------------------
# Rider: set or clear trip purpose on a ride
# ---------------------------------------------------------------------------


@router.put(
    "/rides/{ride_id}/trip-purpose",
    response_model=dict,
    summary="Tag or clear the trip purpose on a ride",
)
async def set_ride_trip_purpose(
    ride_id: int,
    body: SetRideTripPurposeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign (or clear) a trip purpose on the authenticated rider's ride.

    Pass ``trip_purpose_id: null`` to remove an existing tag.  When the
    purpose's ``requires_notes`` flag is True, ``trip_notes`` must be non-empty.
    """
    ride, err = await set_ride_purpose(
        db,
        ride_id=ride_id,
        user_id=user.id,
        purpose_id=body.trip_purpose_id,
        notes=body.trip_notes,
    )
    if err is not None:
        raise err
    return {
        "ride_id": ride.id,
        "trip_purpose_id": ride.trip_purpose_id,
        "trip_notes": ride.trip_notes,
    }


# ---------------------------------------------------------------------------
# Platform admin: list purposes for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/trip-purposes",
    response_model=list[CorporateTripPurposeResponse],
    summary="Admin: list all trip purpose codes for any corporate account",
)
async def admin_list_purposes(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all purpose codes (active and inactive) for any account."""
    purposes = await list_purposes(db, account_id, include_inactive=True)
    return [CorporateTripPurposeResponse.model_validate(p) for p in purposes]


# ---------------------------------------------------------------------------
# Platform admin: spend analytics for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/trip-purposes/analytics",
    response_model=TripPurposeSpendResponse,
    summary="Admin: get trip purpose spend analytics for any corporate account",
)
async def admin_get_purpose_analytics(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return spend-by-purpose analytics for any corporate account."""
    return await get_purpose_spend_analytics(db, account_id)
