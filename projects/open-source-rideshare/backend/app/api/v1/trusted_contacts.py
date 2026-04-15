"""Trusted contact and trip-sharing endpoints.

Rider endpoints:
  POST   /riders/me/trusted-contacts                        — add a trusted contact (max 5)
  GET    /riders/me/trusted-contacts                        — list own contacts
  PUT    /riders/me/trusted-contacts/{contact_id}           — update a contact
  DELETE /riders/me/trusted-contacts/{contact_id}           — soft-delete a contact
  POST   /riders/me/rides/{ride_id}/share-trip              — share trip with contacts
  GET    /riders/me/rides/{ride_id}/share-status            — who was notified and when

Admin endpoints:
  GET    /admin/trusted-contacts/summary                    — platform-wide stats
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.trusted_contact import TripShareRecord, TrustedContact
from app.models.user import User
from app.schemas.trusted_contact import (
    AdminTripShareSummary,
    ShareTripRequest,
    TripShareContactStatus,
    TripShareStatusResponse,
    TrustedContactCreate,
    TrustedContactResponse,
    TrustedContactUpdate,
)
from app.services.trusted_contacts import (
    TrustedContactError,
    add_contact,
    delete_contact,
    get_share_status,
    list_contacts,
    notify_trip_started,
    share_trip,
    update_contact,
)

router = APIRouter(tags=["trusted-contacts"])


# ---------------------------------------------------------------------------
# Rider — contact management
# ---------------------------------------------------------------------------


@router.post(
    "/riders/me/trusted-contacts",
    response_model=TrustedContactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_trusted_contact(
    req: TrustedContactCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a trusted contact. Max 5 active contacts per rider."""
    try:
        contact = await add_contact(user.id, req, db)
    except TrustedContactError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return contact


@router.get(
    "/riders/me/trusted-contacts",
    response_model=list[TrustedContactResponse],
)
async def list_trusted_contacts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the rider's active trusted contacts."""
    return await list_contacts(user.id, db)


@router.put(
    "/riders/me/trusted-contacts/{contact_id}",
    response_model=TrustedContactResponse,
)
async def update_trusted_contact(
    contact_id: int,
    req: TrustedContactUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a trusted contact."""
    try:
        contact = await update_contact(contact_id, user.id, req, db)
    except TrustedContactError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return contact


@router.delete(
    "/riders/me/trusted-contacts/{contact_id}",
    status_code=status.HTTP_200_OK,
)
async def delete_trusted_contact(
    contact_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete (deactivate) a trusted contact."""
    try:
        await delete_contact(contact_id, user.id, db)
    except TrustedContactError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return {"status": "deleted", "contact_id": contact_id}


# ---------------------------------------------------------------------------
# Rider — trip sharing
# ---------------------------------------------------------------------------


@router.post(
    "/riders/me/rides/{ride_id}/share-trip",
    status_code=status.HTTP_200_OK,
)
async def share_trip_endpoint(
    ride_id: int,
    req: ShareTripRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Share a trip with trusted contacts.

    If contact_ids is omitted: auto-share contacts are used.
    If contact_ids is provided: those contacts are notified (must belong to rider).

    Also stamps start_notified_at on new share records so contacts are
    considered notified immediately (notification delivery is handled async).
    """
    try:
        records = await share_trip(ride_id, user.id, req.contact_ids, db)
    except TrustedContactError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    # Stamp start notifications on newly created records
    if records:
        await notify_trip_started(ride_id, db)

    return {
        "ride_id": ride_id,
        "contacts_notified": len(records),
        "message": (
            f"Trip shared with {len(records)} contact(s)."
            if records
            else "All requested contacts were already notified."
        ),
    }


@router.get(
    "/riders/me/rides/{ride_id}/share-status",
    response_model=TripShareStatusResponse,
)
async def get_trip_share_status(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get trip sharing status: which contacts were notified and when."""
    try:
        records = await get_share_status(ride_id, user.id, db)
    except TrustedContactError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    contact_statuses: list[TripShareContactStatus] = []
    for rec in records:
        # Load the contact to get the name
        contact_result = await db.execute(
            select(TrustedContact).where(TrustedContact.id == rec.contact_id)
        )
        contact = contact_result.scalar_one_or_none()
        contact_name = contact.name if contact else f"Contact #{rec.contact_id}"

        contact_statuses.append(
            TripShareContactStatus(
                contact_id=rec.contact_id,
                contact_name=contact_name,
                shared_at=rec.shared_at,
                start_notified_at=rec.start_notified_at,
                complete_notified_at=rec.complete_notified_at,
            )
        )

    return TripShareStatusResponse(
        ride_id=ride_id,
        total_contacts_notified=len(records),
        contacts=contact_statuses,
    )


# ---------------------------------------------------------------------------
# Admin — platform overview
# ---------------------------------------------------------------------------


@router.get(
    "/admin/trusted-contacts/summary",
    response_model=AdminTripShareSummary,
    dependencies=[Depends(require_admin)],
)
async def admin_trusted_contacts_summary(
    db: AsyncSession = Depends(get_db),
):
    """Admin: platform-wide trusted contact and trip sharing statistics."""
    total_contacts = (
        await db.execute(select(func.count(TrustedContact.id)))
    ).scalar() or 0

    auto_share_contacts = (
        await db.execute(
            select(func.count(TrustedContact.id)).where(
                TrustedContact.share_automatically.is_(True),
                TrustedContact.is_active.is_(True),
            )
        )
    ).scalar() or 0

    total_shares = (
        await db.execute(select(func.count(TripShareRecord.id)))
    ).scalar() or 0

    total_rides_shared = (
        await db.execute(
            select(func.count(func.distinct(TripShareRecord.ride_id)))
        )
    ).scalar() or 0

    return AdminTripShareSummary(
        total_shares=int(total_shares),
        total_rides_shared=int(total_rides_shared),
        total_contacts=int(total_contacts),
        auto_share_contacts=int(auto_share_contacts),
    )
