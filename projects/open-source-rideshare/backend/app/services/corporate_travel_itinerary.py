"""Service layer for Corporate Travel Itinerary.

Employees create named business trips that group multiple rides for
consolidated expense reporting.  All rides under an itinerary share a cost
center and trip purpose.

Public surface
--------------
create_itinerary(db, account_id, data, member_id)
    -> ItineraryResponse

get_itinerary(db, account_id, itinerary_id)
    -> ItineraryResponse

update_itinerary(db, account_id, itinerary_id, data, member_id)
    -> ItineraryResponse

cancel_itinerary(db, account_id, itinerary_id)
    -> ItineraryResponse

complete_itinerary(db, account_id, itinerary_id)
    -> ItineraryResponse

list_itineraries(db, account_id, status, created_by_id, limit, offset)
    -> ItineraryListResponse

add_ride_to_itinerary(db, account_id, itinerary_id, ride_id, member_id, notes)
    -> ItineraryRideResponse

remove_ride_from_itinerary(db, account_id, itinerary_id, ride_id)
    -> None

list_itinerary_rides(db, account_id, itinerary_id, limit, offset)
    -> ItineraryRideListResponse

get_itinerary_summary(db, account_id, itinerary_id)
    -> ItinerarySummaryResponse

list_all_itineraries_platform(db, limit, offset)
    -> ItineraryListResponse
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_travel_itinerary import (
    CorporateItineraryRide,
    CorporateTravelItinerary,
)
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(itinerary: CorporateTravelItinerary) -> ItineraryResponse:
    """Convert a model instance to ItineraryResponse."""
    return ItineraryResponse(
        id=itinerary.id,
        account_id=itinerary.account_id,
        created_by_id=itinerary.created_by_id,
        title=itinerary.title,
        description=itinerary.description,
        start_date=itinerary.start_date,
        end_date=itinerary.end_date,
        cost_center_id=itinerary.cost_center_id,
        trip_purpose_id=itinerary.trip_purpose_id,
        status=itinerary.status,
        is_active=itinerary.is_active,
        created_at=itinerary.created_at,
        updated_at=itinerary.updated_at,
    )


def _to_ride_response(assoc: CorporateItineraryRide) -> ItineraryRideResponse:
    """Convert a ride-association model instance to ItineraryRideResponse."""
    return ItineraryRideResponse(
        id=assoc.id,
        itinerary_id=assoc.itinerary_id,
        ride_id=assoc.ride_id,
        added_by_id=assoc.added_by_id,
        notes=assoc.notes,
        added_at=assoc.added_at,
    )


async def _fetch_itinerary(
    db: AsyncSession, account_id: int, itinerary_id: int
) -> Optional[CorporateTravelItinerary]:
    """Return the itinerary row for an account, or None."""
    result = await db.execute(
        select(CorporateTravelItinerary).where(
            CorporateTravelItinerary.id == itinerary_id,
            CorporateTravelItinerary.account_id == account_id,
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


async def create_itinerary(
    db: AsyncSession,
    account_id: int,
    data: ItineraryCreate,
    member_id: int,
) -> ItineraryResponse:
    """Create a new travel itinerary for a corporate account.

    The itinerary starts in ``draft`` status with ``is_active=True``.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.
        data:       Validated creation payload.
        member_id:  ID of the member creating the itinerary.

    Returns:
        ItineraryResponse for the newly created itinerary.
    """
    itinerary = CorporateTravelItinerary(
        account_id=account_id,
        created_by_id=member_id,
        title=data.title,
        description=data.description,
        start_date=data.start_date,
        end_date=data.end_date,
        cost_center_id=data.cost_center_id,
        trip_purpose_id=data.trip_purpose_id,
        status="draft",
        is_active=True,
    )
    db.add(itinerary)
    await db.commit()
    await db.refresh(itinerary)
    return _to_response(itinerary)


async def get_itinerary(
    db: AsyncSession,
    account_id: int,
    itinerary_id: int,
) -> ItineraryResponse:
    """Return a single itinerary by ID.

    Args:
        db:            Async database session.
        account_id:    Corporate account identifier.
        itinerary_id:  ID of the itinerary to fetch.

    Returns:
        ItineraryResponse.

    Raises:
        HTTP 404: Itinerary not found or does not belong to the account.
    """
    itinerary = await _fetch_itinerary(db, account_id, itinerary_id)
    if itinerary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Travel itinerary not found.",
        )
    return _to_response(itinerary)


async def update_itinerary(
    db: AsyncSession,
    account_id: int,
    itinerary_id: int,
    data: ItineraryUpdate,
    member_id: int,
) -> ItineraryResponse:
    """Partially update a travel itinerary.

    Only fields explicitly supplied in the request body are written; unset
    fields are left unchanged.  Raises 409 if the itinerary is cancelled —
    cancelled itineraries are immutable.

    Args:
        db:            Async database session.
        account_id:    Corporate account identifier.
        itinerary_id:  ID of the itinerary to update.
        data:          Validated update payload.
        member_id:     ID of the member making the update.

    Returns:
        Updated ItineraryResponse.

    Raises:
        HTTP 404: Itinerary not found.
        HTTP 409: Itinerary is cancelled.
    """
    itinerary = await _fetch_itinerary(db, account_id, itinerary_id)
    if itinerary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Travel itinerary not found.",
        )
    if itinerary.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot update a cancelled itinerary.",
        )

    payload = data.model_dump(exclude_unset=True)
    # Convert ItineraryStatus enum to its string value if present
    if "status" in payload and payload["status"] is not None:
        payload["status"] = str(payload["status"].value) if hasattr(payload["status"], "value") else payload["status"]
    for field, value in payload.items():
        setattr(itinerary, field, value)

    await db.commit()
    await db.refresh(itinerary)
    return _to_response(itinerary)


async def cancel_itinerary(
    db: AsyncSession,
    account_id: int,
    itinerary_id: int,
) -> ItineraryResponse:
    """Cancel a travel itinerary.

    Args:
        db:            Async database session.
        account_id:    Corporate account identifier.
        itinerary_id:  ID of the itinerary to cancel.

    Returns:
        Updated ItineraryResponse with status="cancelled".

    Raises:
        HTTP 404: Itinerary not found.
        HTTP 409: Itinerary is already cancelled.
    """
    itinerary = await _fetch_itinerary(db, account_id, itinerary_id)
    if itinerary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Travel itinerary not found.",
        )
    if itinerary.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Itinerary is already cancelled.",
        )

    itinerary.status = "cancelled"
    await db.commit()
    await db.refresh(itinerary)
    return _to_response(itinerary)


async def complete_itinerary(
    db: AsyncSession,
    account_id: int,
    itinerary_id: int,
) -> ItineraryResponse:
    """Mark a travel itinerary as completed.

    Args:
        db:            Async database session.
        account_id:    Corporate account identifier.
        itinerary_id:  ID of the itinerary to complete.

    Returns:
        Updated ItineraryResponse with status="completed".

    Raises:
        HTTP 404: Itinerary not found.
        HTTP 409: Itinerary is cancelled.
    """
    itinerary = await _fetch_itinerary(db, account_id, itinerary_id)
    if itinerary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Travel itinerary not found.",
        )
    if itinerary.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot complete a cancelled itinerary.",
        )

    itinerary.status = "completed"
    await db.commit()
    await db.refresh(itinerary)
    return _to_response(itinerary)


async def list_itineraries(
    db: AsyncSession,
    account_id: int,
    status: Optional[str] = None,
    created_by_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> ItineraryListResponse:
    """List itineraries for a corporate account with optional filters.

    Args:
        db:             Async database session.
        account_id:     Corporate account identifier.
        status:         Optional status filter.
        created_by_id:  Optional filter by creator.
        limit:          Maximum number of records to return (default 50).
        offset:         Number of records to skip (default 0).

    Returns:
        ItineraryListResponse with total count and paginated items.
    """
    base_query = select(CorporateTravelItinerary).where(
        CorporateTravelItinerary.account_id == account_id
    )
    if status is not None:
        base_query = base_query.where(CorporateTravelItinerary.status == status)
    if created_by_id is not None:
        base_query = base_query.where(
            CorporateTravelItinerary.created_by_id == created_by_id
        )

    count_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = count_result.scalar_one()

    result = await db.execute(
        base_query.order_by(CorporateTravelItinerary.id.desc())
        .limit(limit)
        .offset(offset)
    )
    itineraries = list(result.scalars().all())

    return ItineraryListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[_to_response(i) for i in itineraries],
    )


async def add_ride_to_itinerary(
    db: AsyncSession,
    account_id: int,
    itinerary_id: int,
    ride_id: int,
    member_id: int,
    notes: Optional[str] = None,
) -> ItineraryRideResponse:
    """Add a ride to a travel itinerary.

    Args:
        db:            Async database session.
        account_id:    Corporate account identifier.
        itinerary_id:  ID of the itinerary.
        ride_id:       ID of the ride to add.
        member_id:     ID of the member adding the ride.
        notes:         Optional note about this ride.

    Returns:
        ItineraryRideResponse for the new association.

    Raises:
        HTTP 404: Itinerary not found or does not belong to the account.
        HTTP 409: Itinerary is cancelled.
        HTTP 409: Ride is already in this itinerary.
    """
    itinerary = await _fetch_itinerary(db, account_id, itinerary_id)
    if itinerary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Travel itinerary not found.",
        )
    if itinerary.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot add rides to a cancelled itinerary.",
        )

    # Check for duplicate
    existing = await db.execute(
        select(CorporateItineraryRide).where(
            CorporateItineraryRide.itinerary_id == itinerary_id,
            CorporateItineraryRide.ride_id == ride_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ride is already in this itinerary.",
        )

    assoc = CorporateItineraryRide(
        itinerary_id=itinerary_id,
        ride_id=ride_id,
        added_by_id=member_id,
        notes=notes,
    )
    db.add(assoc)
    await db.commit()
    await db.refresh(assoc)
    return _to_ride_response(assoc)


async def remove_ride_from_itinerary(
    db: AsyncSession,
    account_id: int,
    itinerary_id: int,
    ride_id: int,
) -> None:
    """Remove a ride association from a travel itinerary.

    Args:
        db:            Async database session.
        account_id:    Corporate account identifier.
        itinerary_id:  ID of the itinerary.
        ride_id:       ID of the ride to remove.

    Raises:
        HTTP 404: Itinerary not found.
        HTTP 404: Ride association not found in this itinerary.
    """
    itinerary = await _fetch_itinerary(db, account_id, itinerary_id)
    if itinerary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Travel itinerary not found.",
        )

    result = await db.execute(
        select(CorporateItineraryRide).where(
            CorporateItineraryRide.itinerary_id == itinerary_id,
            CorporateItineraryRide.ride_id == ride_id,
        )
    )
    assoc = result.scalar_one_or_none()
    if assoc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride association not found in this itinerary.",
        )

    await db.delete(assoc)
    await db.commit()


async def list_itinerary_rides(
    db: AsyncSession,
    account_id: int,
    itinerary_id: int,
    limit: int = 50,
    offset: int = 0,
) -> ItineraryRideListResponse:
    """List rides associated with a travel itinerary.

    Args:
        db:            Async database session.
        account_id:    Corporate account identifier.
        itinerary_id:  ID of the itinerary.
        limit:         Maximum number of records to return (default 50).
        offset:        Number of records to skip (default 0).

    Returns:
        ItineraryRideListResponse with total count and paginated items.

    Raises:
        HTTP 404: Itinerary not found.
    """
    itinerary = await _fetch_itinerary(db, account_id, itinerary_id)
    if itinerary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Travel itinerary not found.",
        )

    count_result = await db.execute(
        select(func.count()).where(
            CorporateItineraryRide.itinerary_id == itinerary_id
        )
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(CorporateItineraryRide)
        .where(CorporateItineraryRide.itinerary_id == itinerary_id)
        .order_by(CorporateItineraryRide.id)
        .limit(limit)
        .offset(offset)
    )
    rides = list(result.scalars().all())

    return ItineraryRideListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[_to_ride_response(r) for r in rides],
    )


async def get_itinerary_summary(
    db: AsyncSession,
    account_id: int,
    itinerary_id: int,
) -> ItinerarySummaryResponse:
    """Return a lightweight summary of a travel itinerary.

    Args:
        db:            Async database session.
        account_id:    Corporate account identifier.
        itinerary_id:  ID of the itinerary.

    Returns:
        ItinerarySummaryResponse with ride count and ride IDs.

    Raises:
        HTTP 404: Itinerary not found.
    """
    itinerary = await _fetch_itinerary(db, account_id, itinerary_id)
    if itinerary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Travel itinerary not found.",
        )

    result = await db.execute(
        select(CorporateItineraryRide).where(
            CorporateItineraryRide.itinerary_id == itinerary_id
        )
    )
    assocs = list(result.scalars().all())
    ride_ids = [a.ride_id for a in assocs if a.ride_id is not None]

    return ItinerarySummaryResponse(
        itinerary_id=itinerary.id,
        title=itinerary.title,
        status=itinerary.status,
        total_rides=len(assocs),
        ride_ids=ride_ids,
    )


async def list_all_itineraries_platform(
    db: AsyncSession,
    limit: int = 50,
    offset: int = 0,
) -> ItineraryListResponse:
    """List travel itineraries across all corporate accounts.

    Platform-admin only.  Returns a paginated list ordered by id desc.

    Args:
        db:     Async database session.
        limit:  Maximum number of records to return (default 50).
        offset: Number of records to skip (default 0).

    Returns:
        ItineraryListResponse with total count and paginated items.
    """
    count_result = await db.execute(
        select(func.count()).select_from(CorporateTravelItinerary)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(CorporateTravelItinerary)
        .order_by(CorporateTravelItinerary.id.desc())
        .limit(limit)
        .offset(offset)
    )
    itineraries = list(result.scalars().all())

    return ItineraryListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[_to_response(i) for i in itineraries],
    )
