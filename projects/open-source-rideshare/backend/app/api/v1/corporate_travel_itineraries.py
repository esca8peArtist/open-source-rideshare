"""Corporate Travel Itinerary endpoints.

Employees create named business trips that group multiple rides for
consolidated expense reporting.

Member endpoints (any active member):
  POST /corporate/accounts/me/travel-itineraries              — create itinerary
  GET  /corporate/accounts/me/travel-itineraries              — list itineraries
  GET  /corporate/accounts/me/travel-itineraries/{id}         — get itinerary
  PUT  /corporate/accounts/me/travel-itineraries/{id}         — update itinerary
  GET  /corporate/accounts/me/travel-itineraries/{id}/rides   — list rides
  POST /corporate/accounts/me/travel-itineraries/{id}/rides   — add ride
  GET  /corporate/accounts/me/travel-itineraries/{id}/summary — get summary

Admin endpoints (account admins only):
  POST   /corporate/accounts/me/travel-itineraries/{id}/cancel   — cancel
  POST   /corporate/accounts/me/travel-itineraries/{id}/complete  — complete
  DELETE /corporate/accounts/me/travel-itineraries/{id}/rides/{ride_id} — remove ride

Platform-admin endpoints:
  GET /platform/corporate/travel-itineraries                             — list all
  GET /platform/corporate/accounts/{account_id}/travel-itineraries      — list for account
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_travel_itinerary import (
    ItineraryCreate,
    ItineraryListResponse,
    ItineraryResponse,
    ItineraryRideCreate,
    ItineraryRideListResponse,
    ItineraryRideResponse,
    ItinerarySummaryResponse,
    ItineraryUpdate,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_travel_itinerary import (
    add_ride_to_itinerary,
    cancel_itinerary,
    complete_itinerary,
    create_itinerary,
    get_itinerary,
    get_itinerary_summary,
    list_all_itineraries_platform,
    list_itineraries,
    list_itinerary_rides,
    remove_ride_from_itinerary,
    update_itinerary,
)
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-travel-itinerary"])


# ---------------------------------------------------------------------------
# Internal helper
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
# Member: create itinerary
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/travel-itineraries",
    response_model=ItineraryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a travel itinerary for own corporate account",
)
async def create_my_itinerary(
    data: ItineraryCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new named business trip itinerary.

    Any active member may create an itinerary.  The itinerary starts in
    ``draft`` status.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await create_itinerary(db, account_id, data, member_id=user.id)


# ---------------------------------------------------------------------------
# Member: list itineraries
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/travel-itineraries",
    response_model=ItineraryListResponse,
    summary="List travel itineraries for own corporate account",
)
async def list_my_itineraries(
    status: Optional[str] = Query(None, description="Filter by status"),
    created_by_id: Optional[int] = Query(None, description="Filter by creator"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of travel itineraries for the authenticated
    user's corporate account.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_itineraries(
        db, account_id, status=status, created_by_id=created_by_id,
        limit=limit, offset=offset,
    )


# ---------------------------------------------------------------------------
# Member: get itinerary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/travel-itineraries/{itinerary_id}",
    response_model=ItineraryResponse,
    summary="Get a travel itinerary for own corporate account",
)
async def get_my_itinerary(
    itinerary_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single travel itinerary by ID.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_itinerary(db, account_id, itinerary_id)


# ---------------------------------------------------------------------------
# Member: update itinerary
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/travel-itineraries/{itinerary_id}",
    response_model=ItineraryResponse,
    summary="Update a travel itinerary (member — own or admin)",
)
async def update_my_itinerary(
    itinerary_id: int,
    data: ItineraryUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update fields on a travel itinerary.

    Only supplied fields are written; unset fields are left unchanged.
    Returns 409 if the itinerary is cancelled.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await update_itinerary(db, account_id, itinerary_id, data, member_id=user.id)


# ---------------------------------------------------------------------------
# Admin: cancel itinerary
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/travel-itineraries/{itinerary_id}/cancel",
    response_model=ItineraryResponse,
    summary="Cancel a travel itinerary (admin only)",
)
async def cancel_my_itinerary(
    itinerary_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a travel itinerary.

    Returns 409 if the itinerary is already cancelled.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await cancel_itinerary(db, account_id, itinerary_id)


# ---------------------------------------------------------------------------
# Admin: complete itinerary
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/travel-itineraries/{itinerary_id}/complete",
    response_model=ItineraryResponse,
    summary="Complete a travel itinerary (admin only)",
)
async def complete_my_itinerary(
    itinerary_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a travel itinerary as completed.

    Returns 409 if the itinerary is cancelled.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await complete_itinerary(db, account_id, itinerary_id)


# ---------------------------------------------------------------------------
# Member: list rides
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/travel-itineraries/{itinerary_id}/rides",
    response_model=ItineraryRideListResponse,
    summary="List rides in a travel itinerary",
)
async def list_my_itinerary_rides(
    itinerary_id: int,
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of rides associated with a travel itinerary.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_itinerary_rides(db, account_id, itinerary_id, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Member: add ride
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/travel-itineraries/{itinerary_id}/rides",
    response_model=ItineraryRideResponse,
    status_code=status.HTTP_200_OK,
    summary="Add a ride to a travel itinerary",
)
async def add_ride_to_my_itinerary(
    itinerary_id: int,
    data: ItineraryRideCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a ride to the specified travel itinerary.

    Returns 409 if the itinerary is cancelled or the ride is already present.
    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await add_ride_to_itinerary(
        db, account_id, itinerary_id,
        ride_id=data.ride_id,
        member_id=user.id,
        notes=data.notes,
    )


# ---------------------------------------------------------------------------
# Admin: remove ride
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/travel-itineraries/{itinerary_id}/rides/{ride_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a ride from a travel itinerary (admin only)",
)
async def remove_ride_from_my_itinerary(
    itinerary_id: int,
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a ride from the specified travel itinerary.

    Returns 404 if the itinerary or ride association is not found.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    await remove_ride_from_itinerary(db, account_id, itinerary_id, ride_id)


# ---------------------------------------------------------------------------
# Member: get summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/travel-itineraries/{itinerary_id}/summary",
    response_model=ItinerarySummaryResponse,
    summary="Get a summary of a travel itinerary",
)
async def get_my_itinerary_summary(
    itinerary_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a lightweight summary of a travel itinerary including ride count.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_itinerary_summary(db, account_id, itinerary_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all itineraries
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/travel-itineraries",
    response_model=ItineraryListResponse,
    summary="Admin: list travel itineraries for all corporate accounts",
)
async def admin_list_all_itineraries(
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of travel itineraries across all corporate accounts.

    Ordered by id desc.  Platform admin only.
    """
    return await list_all_itineraries_platform(db, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Platform-admin: list itineraries for a specific account
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/accounts/{account_id}/travel-itineraries",
    response_model=ItineraryListResponse,
    summary="Admin: list travel itineraries for a specific corporate account",
)
async def admin_list_account_itineraries(
    account_id: int,
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of travel itineraries for any corporate account.

    Platform admin only.
    """
    return await list_itineraries(
        db, account_id, status=status, limit=limit, offset=offset
    )
