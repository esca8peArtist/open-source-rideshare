"""Corporate Event Management endpoints.

Enterprise coordinators organize company events, invite employees, and link
rides for consolidated billing.

Member endpoints (any active member):
  POST   /corporate/accounts/me/events                                  — create event
  GET    /corporate/accounts/me/events                                   — list events
  GET    /corporate/accounts/me/events/{event_id}                        — get event
  PUT    /corporate/accounts/me/events/{event_id}                        — update event
  GET    /corporate/accounts/me/events/{event_id}/summary                — get summary

Admin endpoints (account admins only):
  POST   /corporate/accounts/me/events/{event_id}/activate               — activate event
  POST   /corporate/accounts/me/events/{event_id}/cancel                 — cancel event
  POST   /corporate/accounts/me/events/{event_id}/complete               — complete event
  POST   /corporate/accounts/me/events/{event_id}/attendees/invite       — invite attendees
  PATCH  /corporate/accounts/me/events/{event_id}/attendees/{member_id}  — update attendee status

Platform-admin endpoints:
  GET    /platform/corporate/events                                       — list all events
  GET    /platform/corporate/accounts/{account_id}/events                — list for account
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_event import (
    AttendeeListResponse,
    AttendeeResponse,
    AttendeeStatusUpdate,
    EventCreate,
    EventListResponse,
    EventResponse,
    EventSummaryResponse,
    EventUpdate,
    InviteAttendeesRequest,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_event import (
    activate_event,
    cancel_event,
    complete_event,
    create_event,
    get_event,
    get_event_summary,
    invite_attendees,
    list_all_events_platform,
    list_events,
    update_attendee_status,
    update_event,
)
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-events"])


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
# Member: create event
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/events",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a corporate event for own account",
)
async def create_my_event(
    data: EventCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new corporate event.

    Any active member may create an event.  The event starts in ``draft``
    status.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await create_event(db, account_id, data, member_id=user.id)


# ---------------------------------------------------------------------------
# Member: list events
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/events",
    response_model=EventListResponse,
    summary="List corporate events for own account",
)
async def list_my_events(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of corporate events for the authenticated
    user's corporate account.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_events(db, account_id, status=status, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Member: get event
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/events/{event_id}",
    response_model=EventResponse,
    summary="Get a corporate event for own account",
)
async def get_my_event(
    event_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single corporate event by ID.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_event(db, account_id, event_id)


# ---------------------------------------------------------------------------
# Member: update event
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/events/{event_id}",
    response_model=EventResponse,
    summary="Update a corporate event (member — own or admin)",
)
async def update_my_event(
    event_id: int,
    data: EventUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update fields on a corporate event.

    Only supplied fields are written; unset fields are left unchanged.
    Returns 409 if the event is cancelled or completed.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await update_event(db, account_id, event_id, data, member_id=user.id)


# ---------------------------------------------------------------------------
# Member: get summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/events/{event_id}/summary",
    response_model=EventSummaryResponse,
    summary="Get a summary of a corporate event",
)
async def get_my_event_summary(
    event_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a lightweight summary of a corporate event including attendee counts.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_event_summary(db, account_id, event_id)


# ---------------------------------------------------------------------------
# Admin: activate event
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/events/{event_id}/activate",
    response_model=EventResponse,
    summary="Activate a corporate event (admin only)",
)
async def activate_my_event(
    event_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Transition a corporate event from draft to active.

    Returns 409 if the event is not in draft status.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await activate_event(db, account_id, event_id)


# ---------------------------------------------------------------------------
# Admin: cancel event
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/events/{event_id}/cancel",
    response_model=EventResponse,
    summary="Cancel a corporate event (admin only)",
)
async def cancel_my_event(
    event_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a corporate event.

    Returns 409 if the event is already cancelled or is completed.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await cancel_event(db, account_id, event_id)


# ---------------------------------------------------------------------------
# Admin: complete event
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/events/{event_id}/complete",
    response_model=EventResponse,
    summary="Complete a corporate event (admin only)",
)
async def complete_my_event(
    event_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a corporate event as completed.

    Returns 409 if the event is not in active status.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await complete_event(db, account_id, event_id)


# ---------------------------------------------------------------------------
# Admin: invite attendees
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/events/{event_id}/attendees/invite",
    response_model=AttendeeListResponse,
    summary="Invite members to a corporate event (admin only)",
)
async def invite_event_attendees(
    event_id: int,
    data: InviteAttendeesRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Invite one or more members to a corporate event.

    Duplicate invitations are silently skipped.  Returns 409 if the event is
    cancelled.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await invite_attendees(
        db,
        account_id,
        event_id,
        member_ids=data.member_ids,
        invited_by_id=user.id,
        notes=data.notes,
    )


# ---------------------------------------------------------------------------
# Admin: update attendee status
# ---------------------------------------------------------------------------


@router.patch(
    "/corporate/accounts/me/events/{event_id}/attendees/{member_id}",
    response_model=AttendeeResponse,
    summary="Update an attendee's status (admin only)",
)
async def update_event_attendee_status(
    event_id: int,
    member_id: int,
    data: AttendeeStatusUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the status of a member's attendance record.

    Returns 404 if the event or attendee is not found.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await update_attendee_status(
        db, account_id, event_id, member_id, new_status=data.status
    )


# ---------------------------------------------------------------------------
# Platform-admin: list all events
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/events",
    response_model=EventListResponse,
    summary="Admin: list corporate events for all accounts",
)
async def admin_list_all_events(
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of corporate events across all accounts.

    Ordered by created_at desc.  Platform admin only.
    """
    return await list_all_events_platform(db, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Platform-admin: list events for a specific account
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/accounts/{account_id}/events",
    response_model=EventListResponse,
    summary="Admin: list corporate events for a specific account",
)
async def admin_list_account_events(
    account_id: int,
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of corporate events for any account.

    Platform admin only.
    """
    return await list_events(db, account_id, status=status, limit=limit, offset=offset)
