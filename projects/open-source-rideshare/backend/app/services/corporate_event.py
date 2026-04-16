"""Service layer for Corporate Event Management.

Enterprise coordinators organize company events (team offsites, conferences,
client dinners, holiday parties), invite employees, and link rides for
consolidated billing.

Public surface
--------------
create_event(db, account_id, data, member_id)
    -> EventResponse

get_event(db, account_id, event_id)
    -> EventResponse

list_events(db, account_id, status, limit, offset)
    -> EventListResponse

update_event(db, account_id, event_id, data, member_id)
    -> EventResponse

activate_event(db, account_id, event_id)
    -> EventResponse

cancel_event(db, account_id, event_id)
    -> EventResponse

complete_event(db, account_id, event_id)
    -> EventResponse

invite_attendees(db, account_id, event_id, member_ids, invited_by_id, notes)
    -> AttendeeListResponse

update_attendee_status(db, account_id, event_id, member_id, status)
    -> AttendeeResponse

get_event_summary(db, account_id, event_id)
    -> EventSummaryResponse

list_all_events_platform(db, limit, offset)
    -> EventListResponse
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_event import CorporateEvent, CorporateEventAttendee
from app.schemas.corporate_event import (
    AttendeeListResponse,
    AttendeeResponse,
    EventCreate,
    EventListResponse,
    EventResponse,
    EventSummaryResponse,
    EventUpdate,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_event_response(event: CorporateEvent) -> EventResponse:
    """Convert a model instance to EventResponse."""
    return EventResponse(
        id=event.id,
        account_id=event.account_id,
        organizer_id=event.organizer_id,
        created_by_id=event.created_by_id,
        title=event.title,
        description=event.description,
        event_location_name=event.event_location_name,
        event_address_line1=event.event_address_line1,
        event_city=event.event_city,
        event_state=event.event_state,
        event_country=event.event_country,
        event_latitude=event.event_latitude,
        event_longitude=event.event_longitude,
        corporate_address_id=event.corporate_address_id,
        event_datetime=event.event_datetime,
        status=event.status,
        budget_usd=event.budget_usd,
        max_attendees=event.max_attendees,
        auto_approve_rides=event.auto_approve_rides,
        notes=event.notes,
        is_active=event.is_active,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def _to_attendee_response(attendee: CorporateEventAttendee) -> AttendeeResponse:
    """Convert an attendee model instance to AttendeeResponse."""
    return AttendeeResponse(
        id=attendee.id,
        event_id=attendee.event_id,
        member_id=attendee.member_id,
        ride_id=attendee.ride_id,
        invited_by_id=attendee.invited_by_id,
        status=attendee.status,
        notes=attendee.notes,
        created_at=attendee.created_at,
        updated_at=attendee.updated_at,
    )


async def _fetch_event(
    db: AsyncSession, account_id: int, event_id: int
) -> Optional[CorporateEvent]:
    """Return the event row for an account, or None."""
    result = await db.execute(
        select(CorporateEvent).where(
            CorporateEvent.id == event_id,
            CorporateEvent.account_id == account_id,
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


async def create_event(
    db: AsyncSession,
    account_id: int,
    data: EventCreate,
    member_id: int,
) -> EventResponse:
    """Create a new corporate event.

    The event starts in ``draft`` status with ``is_active=True``.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.
        data:       Validated creation payload.
        member_id:  ID of the member creating the event (becomes organizer).

    Returns:
        EventResponse for the newly created event.
    """
    event = CorporateEvent(
        account_id=account_id,
        organizer_id=member_id,
        created_by_id=member_id,
        title=data.title,
        description=data.description,
        event_location_name=data.event_location_name,
        event_address_line1=data.event_address_line1,
        event_city=data.event_city,
        event_state=data.event_state,
        event_country=data.event_country,
        corporate_address_id=data.corporate_address_id,
        event_datetime=data.event_datetime,
        status="draft",
        budget_usd=data.budget_usd,
        max_attendees=data.max_attendees,
        auto_approve_rides=data.auto_approve_rides,
        notes=data.notes,
        is_active=True,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return _to_event_response(event)


async def get_event(
    db: AsyncSession,
    account_id: int,
    event_id: int,
) -> EventResponse:
    """Return a single event by ID.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.
        event_id:   ID of the event to fetch.

    Returns:
        EventResponse.

    Raises:
        HTTP 404: Event not found or does not belong to the account.
    """
    event = await _fetch_event(db, account_id, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate event not found.",
        )
    return _to_event_response(event)


async def list_events(
    db: AsyncSession,
    account_id: int,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> EventListResponse:
    """List events for a corporate account with optional status filter.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.
        status:     Optional status filter.
        limit:      Maximum number of records to return (default 50).
        offset:     Number of records to skip (default 0).

    Returns:
        EventListResponse with total count and paginated items.
    """
    base_query = select(CorporateEvent).where(
        CorporateEvent.account_id == account_id
    )
    if status is not None:
        base_query = base_query.where(CorporateEvent.status == status)

    count_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = count_result.scalar_one()

    result = await db.execute(
        base_query.order_by(CorporateEvent.event_datetime.desc())
        .limit(limit)
        .offset(offset)
    )
    events = list(result.scalars().all())

    return EventListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[_to_event_response(e) for e in events],
    )


async def update_event(
    db: AsyncSession,
    account_id: int,
    event_id: int,
    data: EventUpdate,
    member_id: int,
) -> EventResponse:
    """Partially update a corporate event.

    Only fields explicitly supplied in the request body are written; unset
    fields are left unchanged.  Raises 409 if the event is cancelled or
    completed — those events are immutable.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.
        event_id:   ID of the event to update.
        data:       Validated update payload.
        member_id:  ID of the member making the update.

    Returns:
        Updated EventResponse.

    Raises:
        HTTP 404: Event not found.
        HTTP 409: Event is cancelled or completed.
    """
    event = await _fetch_event(db, account_id, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate event not found.",
        )
    if event.status in ("cancelled", "completed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot update a cancelled or completed event.",
        )

    payload = data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        setattr(event, field, value)

    await db.commit()
    await db.refresh(event)
    return _to_event_response(event)


async def activate_event(
    db: AsyncSession,
    account_id: int,
    event_id: int,
) -> EventResponse:
    """Transition a corporate event from draft to active.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.
        event_id:   ID of the event to activate.

    Returns:
        Updated EventResponse with status="active".

    Raises:
        HTTP 404: Event not found.
        HTTP 409: Event is not in draft status.
    """
    event = await _fetch_event(db, account_id, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate event not found.",
        )
    if event.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft events can be activated.",
        )

    event.status = "active"
    await db.commit()
    await db.refresh(event)
    return _to_event_response(event)


async def cancel_event(
    db: AsyncSession,
    account_id: int,
    event_id: int,
) -> EventResponse:
    """Cancel a corporate event.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.
        event_id:   ID of the event to cancel.

    Returns:
        Updated EventResponse with status="cancelled".

    Raises:
        HTTP 404: Event not found.
        HTTP 409: Event is already cancelled or is completed.
    """
    event = await _fetch_event(db, account_id, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate event not found.",
        )
    if event.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot cancel a completed event.",
        )
    if event.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event is already cancelled.",
        )

    event.status = "cancelled"
    await db.commit()
    await db.refresh(event)
    return _to_event_response(event)


async def complete_event(
    db: AsyncSession,
    account_id: int,
    event_id: int,
) -> EventResponse:
    """Mark a corporate event as completed.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.
        event_id:   ID of the event to complete.

    Returns:
        Updated EventResponse with status="completed".

    Raises:
        HTTP 404: Event not found.
        HTTP 409: Event is not in active status.
    """
    event = await _fetch_event(db, account_id, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate event not found.",
        )
    if event.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only active events can be completed.",
        )

    event.status = "completed"
    await db.commit()
    await db.refresh(event)
    return _to_event_response(event)


async def invite_attendees(
    db: AsyncSession,
    account_id: int,
    event_id: int,
    member_ids: list[int],
    invited_by_id: int,
    notes: Optional[str] = None,
) -> AttendeeListResponse:
    """Invite one or more members to a corporate event.

    Duplicate member_ids (already invited) are silently skipped.  Returns
    the full attendee list for the event after processing.

    Args:
        db:             Async database session.
        account_id:     Corporate account identifier.
        event_id:       ID of the event.
        member_ids:     List of user IDs to invite.
        invited_by_id:  ID of the admin sending the invitations.
        notes:          Optional note for all new invitations.

    Returns:
        AttendeeListResponse with all attendees for the event.

    Raises:
        HTTP 404: Event not found.
        HTTP 409: Event is cancelled.
    """
    event = await _fetch_event(db, account_id, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate event not found.",
        )
    if event.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot invite attendees to a cancelled event.",
        )

    for mid in member_ids:
        existing_result = await db.execute(
            select(CorporateEventAttendee).where(
                CorporateEventAttendee.event_id == event_id,
                CorporateEventAttendee.member_id == mid,
            )
        )
        if existing_result.scalar_one_or_none() is not None:
            continue
        attendee = CorporateEventAttendee(
            event_id=event_id,
            member_id=mid,
            invited_by_id=invited_by_id,
            status="invited",
            notes=notes,
        )
        db.add(attendee)

    await db.commit()

    count_result = await db.execute(
        select(func.count()).where(
            CorporateEventAttendee.event_id == event_id
        )
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(CorporateEventAttendee)
        .where(CorporateEventAttendee.event_id == event_id)
        .order_by(CorporateEventAttendee.id)
    )
    attendees = list(result.scalars().all())

    return AttendeeListResponse(
        total=total,
        limit=total,
        offset=0,
        items=[_to_attendee_response(a) for a in attendees],
    )


async def update_attendee_status(
    db: AsyncSession,
    account_id: int,
    event_id: int,
    member_id: int,
    new_status: str,
) -> AttendeeResponse:
    """Update the status of an event attendee.

    Args:
        db:          Async database session.
        account_id:  Corporate account identifier.
        event_id:    ID of the event.
        member_id:   ID of the attending member.
        new_status:  New attendee status.

    Returns:
        Updated AttendeeResponse.

    Raises:
        HTTP 404: Event not found.
        HTTP 404: Attendee record not found.
    """
    event = await _fetch_event(db, account_id, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate event not found.",
        )

    result = await db.execute(
        select(CorporateEventAttendee).where(
            CorporateEventAttendee.event_id == event_id,
            CorporateEventAttendee.member_id == member_id,
        )
    )
    attendee = result.scalar_one_or_none()
    if attendee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attendee not found for this event.",
        )

    attendee.status = new_status
    await db.commit()
    await db.refresh(attendee)
    return _to_attendee_response(attendee)


async def get_event_summary(
    db: AsyncSession,
    account_id: int,
    event_id: int,
) -> EventSummaryResponse:
    """Return a lightweight summary of a corporate event.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.
        event_id:   ID of the event.

    Returns:
        EventSummaryResponse with attendee counts and ride link count.

    Raises:
        HTTP 404: Event not found.
    """
    event = await _fetch_event(db, account_id, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate event not found.",
        )

    result = await db.execute(
        select(CorporateEventAttendee).where(
            CorporateEventAttendee.event_id == event_id
        )
    )
    attendees = list(result.scalars().all())

    total_invited = sum(1 for a in attendees if a.status == "invited")
    total_confirmed = sum(1 for a in attendees if a.status == "confirmed")
    total_declined = sum(1 for a in attendees if a.status == "declined")
    total_cancelled = sum(1 for a in attendees if a.status == "cancelled")
    rides_linked = sum(1 for a in attendees if a.ride_id is not None)

    return EventSummaryResponse(
        event_id=event.id,
        total_invited=total_invited,
        total_confirmed=total_confirmed,
        total_declined=total_declined,
        total_cancelled=total_cancelled,
        rides_linked=rides_linked,
        budget_usd=event.budget_usd,
    )


async def list_all_events_platform(
    db: AsyncSession,
    limit: int = 50,
    offset: int = 0,
) -> EventListResponse:
    """List corporate events across all accounts.

    Platform-admin only.  Returns a paginated list ordered by created_at desc.

    Args:
        db:     Async database session.
        limit:  Maximum number of records to return (default 50).
        offset: Number of records to skip (default 0).

    Returns:
        EventListResponse with total count and paginated items.
    """
    count_result = await db.execute(
        select(func.count()).select_from(CorporateEvent)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(CorporateEvent)
        .order_by(CorporateEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    events = list(result.scalars().all())

    return EventListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[_to_event_response(e) for e in events],
    )
