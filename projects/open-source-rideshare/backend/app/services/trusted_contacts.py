"""Service layer for trusted contacts and trip sharing.

Business rules:
  - A rider may have at most MAX_TRUSTED_CONTACTS (5) active contacts.
  - Each contact must have at least a phone or email.
  - Duplicate phone per user is blocked (DB unique constraint + service check).
  - share_trip creates TripShareRecord rows; idempotent — duplicate (ride, contact) is ignored.
  - notify_trip_started / notify_trip_completed stamp the relevant timestamp columns.
  - Contacts are validated to belong to the requesting rider before use.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus
from app.models.trusted_contact import MAX_TRUSTED_CONTACTS, TripShareRecord, TrustedContact
from app.schemas.trusted_contact import TrustedContactCreate, TrustedContactUpdate


class TrustedContactError(Exception):
    """Domain error for trusted contact operations."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Contact CRUD
# ---------------------------------------------------------------------------


async def add_contact(user_id: int, data: TrustedContactCreate, db: AsyncSession) -> TrustedContact:
    """Add a new trusted contact for the rider.

    Raises TrustedContactError if:
      - The rider already has MAX_TRUSTED_CONTACTS active contacts.
      - A contact with the same phone already exists for this user.
    """
    # Count current active contacts
    count_result = await db.execute(
        select(func.count(TrustedContact.id)).where(
            TrustedContact.user_id == user_id,
            TrustedContact.is_active.is_(True),
        )
    )
    current_count = count_result.scalar() or 0
    if current_count >= MAX_TRUSTED_CONTACTS:
        raise TrustedContactError(
            f"Maximum of {MAX_TRUSTED_CONTACTS} trusted contacts allowed. "
            "Deactivate an existing contact before adding a new one.",
            status_code=409,
        )

    # Duplicate phone check
    if data.phone:
        dup = await db.execute(
            select(TrustedContact).where(
                TrustedContact.user_id == user_id,
                TrustedContact.phone == data.phone,
                TrustedContact.is_active.is_(True),
            )
        )
        if dup.scalar_one_or_none():
            raise TrustedContactError(
                "A trusted contact with this phone number already exists.",
                status_code=409,
            )

    contact = TrustedContact(
        user_id=user_id,
        name=data.name,
        phone=data.phone,
        email=data.email,
        relationship_label=data.relationship_label,
        share_automatically=data.share_automatically,
        is_active=True,
    )
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
    return contact


async def list_contacts(user_id: int, db: AsyncSession) -> list[TrustedContact]:
    """Return all active trusted contacts for a rider, newest first."""
    result = await db.execute(
        select(TrustedContact)
        .where(TrustedContact.user_id == user_id, TrustedContact.is_active.is_(True))
        .order_by(TrustedContact.created_at.desc())
    )
    return list(result.scalars().all())


async def get_contact(contact_id: int, user_id: int, db: AsyncSession) -> TrustedContact:
    """Fetch a contact, verifying ownership. Raises TrustedContactError(404) if not found."""
    result = await db.execute(
        select(TrustedContact).where(
            TrustedContact.id == contact_id,
            TrustedContact.user_id == user_id,
        )
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise TrustedContactError("Trusted contact not found.", status_code=404)
    return contact


async def update_contact(
    contact_id: int, user_id: int, data: TrustedContactUpdate, db: AsyncSession
) -> TrustedContact:
    """Update a trusted contact. Only the owning rider may update."""
    contact = await get_contact(contact_id, user_id, db)

    if data.name is not None:
        contact.name = data.name
    if data.phone is not None:
        contact.phone = data.phone
    if data.email is not None:
        contact.email = data.email
    if data.relationship_label is not None:
        contact.relationship_label = data.relationship_label
    if data.share_automatically is not None:
        contact.share_automatically = data.share_automatically
    if data.is_active is not None:
        contact.is_active = data.is_active

    await db.commit()
    await db.refresh(contact)
    return contact


async def delete_contact(contact_id: int, user_id: int, db: AsyncSession) -> None:
    """Soft-delete a trusted contact (sets is_active=False)."""
    contact = await get_contact(contact_id, user_id, db)
    contact.is_active = False
    await db.commit()


# ---------------------------------------------------------------------------
# Trip sharing
# ---------------------------------------------------------------------------


async def share_trip(
    ride_id: int,
    user_id: int,
    contact_ids: list[int] | None,
    db: AsyncSession,
) -> list[TripShareRecord]:
    """Create TripShareRecord entries for a ride.

    If contact_ids is None/empty: use all active auto-share contacts.
    If contact_ids is provided: use only those contacts (must belong to rider).

    Idempotent — existing (ride_id, contact_id) pairs are silently skipped.

    Raises TrustedContactError if:
      - The ride does not exist or does not belong to this rider.
      - Any requested contact_id does not belong to this rider.
      - No contacts resolved (nothing to share with).
    """
    # Validate ride ownership
    ride_result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = ride_result.scalar_one_or_none()
    if not ride:
        raise TrustedContactError("Ride not found.", status_code=404)
    if ride.rider_id != user_id:
        raise TrustedContactError("You can only share your own rides.", status_code=403)

    # Resolve contacts
    if contact_ids:
        contacts_result = await db.execute(
            select(TrustedContact).where(
                TrustedContact.id.in_(contact_ids),
                TrustedContact.user_id == user_id,
                TrustedContact.is_active.is_(True),
            )
        )
        contacts = list(contacts_result.scalars().all())
        if len(contacts) != len(set(contact_ids)):
            raise TrustedContactError(
                "One or more contact IDs are invalid or do not belong to you.",
                status_code=400,
            )
    else:
        # Auto-share contacts
        contacts_result = await db.execute(
            select(TrustedContact).where(
                TrustedContact.user_id == user_id,
                TrustedContact.share_automatically.is_(True),
                TrustedContact.is_active.is_(True),
            )
        )
        contacts = list(contacts_result.scalars().all())

    if not contacts:
        raise TrustedContactError(
            "No contacts to share with. Add a trusted contact with share_automatically=true "
            "or specify contact_ids.",
            status_code=400,
        )

    # Fetch existing share records to avoid duplicates
    existing_result = await db.execute(
        select(TripShareRecord.contact_id).where(TripShareRecord.ride_id == ride_id)
    )
    already_shared = set(existing_result.scalars().all())

    new_records: list[TripShareRecord] = []
    for contact in contacts:
        if contact.id in already_shared:
            continue
        record = TripShareRecord(ride_id=ride_id, contact_id=contact.id)
        db.add(record)
        new_records.append(record)

    await db.commit()
    for r in new_records:
        await db.refresh(r)

    return new_records


async def notify_trip_started(ride_id: int, db: AsyncSession) -> int:
    """Stamp start_notified_at for all share records for this ride that haven't been stamped yet.

    In a real deployment this would also trigger SMS/email notifications via notification
    providers. Here we record the timestamp and rely on the notification layer to pick it up.

    Returns the number of records updated.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(TripShareRecord).where(
            TripShareRecord.ride_id == ride_id,
            TripShareRecord.start_notified_at.is_(None),
        )
    )
    records = list(result.scalars().all())
    for rec in records:
        rec.start_notified_at = now
    await db.commit()
    return len(records)


async def notify_trip_completed(ride_id: int, db: AsyncSession) -> int:
    """Stamp complete_notified_at for all share records for this ride.

    Returns the number of records updated.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(TripShareRecord).where(
            TripShareRecord.ride_id == ride_id,
            TripShareRecord.complete_notified_at.is_(None),
        )
    )
    records = list(result.scalars().all())
    for rec in records:
        rec.complete_notified_at = now
    await db.commit()
    return len(records)


async def get_share_status(
    ride_id: int, user_id: int, db: AsyncSession
) -> list[TripShareRecord]:
    """Return trip share records for a ride, validating the rider owns it."""
    ride_result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = ride_result.scalar_one_or_none()
    if not ride:
        raise TrustedContactError("Ride not found.", status_code=404)
    if ride.rider_id != user_id:
        raise TrustedContactError("You can only view sharing status for your own rides.", status_code=403)

    result = await db.execute(
        select(TripShareRecord).where(TripShareRecord.ride_id == ride_id)
    )
    return list(result.scalars().all())
