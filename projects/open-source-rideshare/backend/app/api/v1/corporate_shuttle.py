"""Corporate Shuttle Routes & Seat Booking endpoints.

Enterprise accounts define fixed shuttle routes between named locations, attach
recurring schedules to each route, and employees book seats on specific run dates.

Member endpoints (any authenticated account member):
  GET  /api/v1/corporate/{account_id}/shuttle/routes                          — list active routes
  GET  /api/v1/corporate/{account_id}/shuttle/routes/{route_id}               — get route + schedules
  GET  /api/v1/corporate/{account_id}/shuttle/schedules/{schedule_id}         — get schedule detail
  POST /api/v1/corporate/{account_id}/shuttle/schedules/{schedule_id}/book    — book a seat
  GET  /api/v1/corporate/{account_id}/shuttle/my-bookings                     — member's own bookings
  POST /api/v1/corporate/{account_id}/shuttle/bookings/{booking_id}/cancel    — cancel own booking

Admin endpoints (account admins only):
  POST /api/v1/corporate/{account_id}/shuttle/routes                          — create route → 201
  PUT  /api/v1/corporate/{account_id}/shuttle/routes/{route_id}               — update route
  POST /api/v1/corporate/{account_id}/shuttle/routes/{route_id}/deactivate    — deactivate route
  GET  /api/v1/corporate/{account_id}/shuttle/routes/{route_id}/summary       — route summary
  POST /api/v1/corporate/{account_id}/shuttle/routes/{route_id}/schedules     — add schedule → 201
  GET  /api/v1/corporate/{account_id}/shuttle/schedules/{schedule_id}/roster  — roster for a date

Platform-admin endpoints:
  GET /api/v1/platform/corporate/shuttle/all  — all routes across platform
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_shuttle import (
    BookingCancelRequest,
    BookingCreate,
    BookingResponse,
    RouteSummaryResponse,
    RouteCreate,
    RouteResponse,
    RouteUpdate,
    ScheduleCreate,
    ScheduleResponse,
)
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin
from app.services.corporate_shuttle_service import (
    add_schedule,
    book_seat,
    cancel_booking,
    create_route,
    deactivate_route,
    get_route,
    get_route_summary,
    get_schedule,
    get_schedule_roster,
    list_all_platform,
    list_member_bookings,
    list_routes,
    list_schedules,
    update_route,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Shuttle Routes & Seat Booking"])


# ---------------------------------------------------------------------------
# Member: list active routes  ← MUST be before /{route_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/shuttle/routes",
    response_model=List[RouteResponse],
    summary="List active shuttle routes for the account",
)
async def list_active_routes_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all active shuttle routes for the account.

    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await list_routes(db, account_id, is_active=True)


# ---------------------------------------------------------------------------
# Admin: create route  ← POST before GET /{route_id}
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/shuttle/routes",
    response_model=RouteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a shuttle route (admin only)",
)
async def create_route_endpoint(
    account_id: int,
    data: RouteCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new fixed shuttle route for the account.

    Returns 409 if an active route with the same name already exists.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await create_route(db, account_id, data, created_by_id=user.id)


# ---------------------------------------------------------------------------
# Member: get route detail (includes schedules listed via list_schedules)
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/shuttle/routes/{route_id}",
    response_model=RouteResponse,
    summary="Get a shuttle route",
)
async def get_route_endpoint(
    account_id: int,
    route_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single shuttle route by ID.

    Returns 404 if not found or belongs to a different account.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_route(db, route_id, account_id)


# ---------------------------------------------------------------------------
# Admin: update route
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/shuttle/routes/{route_id}",
    response_model=RouteResponse,
    summary="Update a shuttle route (admin only)",
)
async def update_route_endpoint(
    account_id: int,
    route_id: uuid.UUID,
    data: RouteUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a shuttle route.

    Returns 404 if not found. Returns 409 on name collision.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await update_route(db, route_id, account_id, data)


# ---------------------------------------------------------------------------
# Admin: deactivate route  ← MUST be before /{route_id}/summary
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/shuttle/routes/{route_id}/deactivate",
    response_model=RouteResponse,
    summary="Deactivate a shuttle route (admin only)",
)
async def deactivate_route_endpoint(
    account_id: int,
    route_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a shuttle route and cascade to its active schedules.

    Returns 404 if not found. Returns 409 if already inactive.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await deactivate_route(db, route_id, account_id, deactivated_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: route summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/shuttle/routes/{route_id}/summary",
    response_model=RouteSummaryResponse,
    summary="Get aggregate statistics for a shuttle route (admin only)",
)
async def get_route_summary_endpoint(
    account_id: int,
    route_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return schedule counts, monthly bookings, and upcoming run dates.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_route_summary(db, route_id, account_id)


# ---------------------------------------------------------------------------
# Admin: add schedule to route
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/shuttle/routes/{route_id}/schedules",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a schedule to a shuttle route (admin only)",
)
async def add_schedule_endpoint(
    account_id: int,
    route_id: uuid.UUID,
    data: ScheduleCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a recurring schedule to a shuttle route.

    Returns 404 if the route is not found.
    Returns 409 if the route is inactive.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await add_schedule(db, route_id, account_id, data, created_by_id=user.id)


# ---------------------------------------------------------------------------
# Member: get schedule detail
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/shuttle/schedules/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Get a shuttle schedule",
)
async def get_schedule_endpoint(
    account_id: int,
    schedule_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single shuttle schedule by ID.

    Returns 404 if not found or belongs to a different account.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_schedule(db, schedule_id, account_id)


# ---------------------------------------------------------------------------
# Member: book a seat
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/shuttle/schedules/{schedule_id}/book",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Book a seat on a shuttle schedule",
)
async def book_seat_endpoint(
    account_id: int,
    schedule_id: uuid.UUID,
    data: BookingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Book a seat for the calling user on the given schedule and date.

    Returns 404 if the schedule is not found.
    Returns 409 if the schedule is inactive, the member already has a booking,
    or capacity is exceeded.
    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await book_seat(
        db,
        schedule_id=schedule_id,
        account_id=account_id,
        member_id=user.id,
        booking_date=data.booking_date,
        notes=data.notes,
    )


# ---------------------------------------------------------------------------
# Admin: get schedule roster
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/shuttle/schedules/{schedule_id}/roster",
    response_model=List[BookingResponse],
    summary="Get the roster of bookings for a schedule date (admin only)",
)
async def get_roster_endpoint(
    account_id: int,
    schedule_id: uuid.UUID,
    booking_date: date = Query(..., description="Run date (YYYY-MM-DD)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all non-cancelled bookings for the given schedule and date.

    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await get_schedule_roster(db, schedule_id, account_id, booking_date)


# ---------------------------------------------------------------------------
# Member: list own bookings  ← MUST be before /bookings/{booking_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/shuttle/my-bookings",
    response_model=List[BookingResponse],
    summary="List the current user's shuttle bookings",
)
async def list_my_bookings_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the calling user's shuttle bookings for the account.

    Any authenticated account member may call this endpoint.
    """
    await get_account(db, account_id)
    return await list_member_bookings(db, account_id, user.id)


# ---------------------------------------------------------------------------
# Member: cancel own booking
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/shuttle/bookings/{booking_id}/cancel",
    response_model=BookingResponse,
    summary="Cancel a shuttle booking",
)
async def cancel_booking_endpoint(
    account_id: int,
    booking_id: uuid.UUID,
    data: BookingCancelRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a shuttle booking.

    Returns 404 if not found. Returns 409 if already completed or no_show.
    Any authenticated account member may cancel their own booking.
    """
    await get_account(db, account_id)
    return await cancel_booking(
        db,
        booking_id=booking_id,
        account_id=account_id,
        cancelled_by_id=user.id,
        reason=data.reason,
    )


# ---------------------------------------------------------------------------
# Platform-admin: cross-account listing
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/shuttle/all",
    response_model=List[RouteResponse],
    summary="Admin: list all shuttle routes across all accounts",
)
async def platform_list_all_endpoint(
    account_id: Optional[int] = Query(None, description="Filter by corporate account ID"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return shuttle routes across all corporate accounts.

    Platform admin only. Optionally filter by account_id.
    """
    return await list_all_platform(db, account_id=account_id)
