import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus
from app.models.safety import EmergencyContact, SOSAlert, SOSStatus, TripShareToken

SHARE_TOKEN_BYTES = 32
SHARE_TOKEN_TTL_HOURS = 24


async def trigger_sos(
    user_id: int,
    db: AsyncSession,
    ride_id: int | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    message: str | None = None,
) -> SOSAlert:
    """Create an SOS alert and return it. Caller handles notifications."""
    if ride_id is not None:
        result = await db.execute(select(Ride).where(Ride.id == ride_id))
        ride = result.scalar_one_or_none()
        if not ride:
            raise ValueError("Ride not found")
        if ride.rider_id != user_id and ride.driver_id != user_id:
            raise PermissionError("Not a participant in this ride")

    alert = SOSAlert(
        user_id=user_id,
        ride_id=ride_id,
        status=SOSStatus.ACTIVE,
        latitude=latitude,
        longitude=longitude,
        message=message,
    )
    db.add(alert)
    await db.flush()

    # Send SOS notification via SMS/email
    try:
        from app.services.notification_events import notify_sos_alert
        await notify_sos_alert(db, user_id=user_id, ride_id=ride_id)
    except Exception:
        pass  # SOS creation must not fail due to notification issues

    return alert


async def resolve_sos(
    alert_id: int,
    user_id: int,
    db: AsyncSession,
    resolution: str = "false_alarm",
) -> SOSAlert:
    """Resolve an SOS alert. Only the user who triggered it can resolve."""
    result = await db.execute(select(SOSAlert).where(SOSAlert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise ValueError("Alert not found")
    if alert.user_id != user_id:
        raise PermissionError("Not authorized to resolve this alert")
    if alert.status != SOSStatus.ACTIVE:
        raise ValueError("Alert is not active")

    alert.status = SOSStatus.FALSE_ALARM if resolution == "false_alarm" else SOSStatus.RESOLVED
    alert.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return alert


async def get_active_alerts(user_id: int, db: AsyncSession) -> list[SOSAlert]:
    """Get all active SOS alerts for a user."""
    result = await db.execute(
        select(SOSAlert).where(
            SOSAlert.user_id == user_id,
            SOSAlert.status == SOSStatus.ACTIVE,
        )
    )
    return list(result.scalars().all())


async def create_trip_share_token(
    ride_id: int,
    user_id: int,
    db: AsyncSession,
) -> TripShareToken:
    """Generate a shareable token for a ride. Only ride participants can share."""
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        raise ValueError("Ride not found")
    if ride.rider_id != user_id and ride.driver_id != user_id:
        raise PermissionError("Not a participant in this ride")
    if ride.status in (RideStatus.COMPLETED, RideStatus.CANCELLED):
        raise ValueError("Cannot share a finished ride")

    token = secrets.token_urlsafe(SHARE_TOKEN_BYTES)
    share = TripShareToken(
        ride_id=ride_id,
        token=token,
        created_by=user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=SHARE_TOKEN_TTL_HOURS),
    )
    db.add(share)
    await db.flush()
    return share


async def get_shared_trip(token: str, db: AsyncSession) -> Ride | None:
    """Look up a ride by share token. Returns None if token invalid/expired."""
    result = await db.execute(
        select(TripShareToken).where(TripShareToken.token == token)
    )
    share = result.scalar_one_or_none()
    if not share:
        return None
    if share.expires_at < datetime.now(timezone.utc):
        return None

    result = await db.execute(select(Ride).where(Ride.id == share.ride_id))
    return result.scalar_one_or_none()


async def get_shared_trip_detail(
    token: str,
    db: AsyncSession,
) -> dict | None:
    """Return ride + live driver location for a share token.

    Returns None if the token is invalid or expired.  Driver lat/lng are None
    when the driver hasn't submitted a location yet.

    Keys returned:
        ride                       — Ride ORM object
        driver_lat                 — float | None
        driver_lng                 — float | None
        driver_location_updated_at — datetime | None
    """
    result = await db.execute(
        select(TripShareToken).where(TripShareToken.token == token)
    )
    share = result.scalar_one_or_none()
    if not share:
        return None
    if share.expires_at < datetime.now(timezone.utc):
        return None

    result = await db.execute(select(Ride).where(Ride.id == share.ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        return None

    driver_lat: float | None = None
    driver_lng: float | None = None
    driver_location_updated_at = None

    if ride.driver_id is not None:
        from geoalchemy2.functions import ST_X, ST_Y

        from app.models.driver import DriverProfile

        loc_result = await db.execute(
            select(
                ST_Y(DriverProfile.current_location).label("lat"),
                ST_X(DriverProfile.current_location).label("lng"),
                DriverProfile.updated_at,
            ).where(DriverProfile.user_id == ride.driver_id)
        )
        row = loc_result.one_or_none()
        if row is not None and row.lat is not None:
            driver_lat = float(row.lat)
            driver_lng = float(row.lng)
            driver_location_updated_at = row.updated_at

    return {
        "ride": ride,
        "driver_lat": driver_lat,
        "driver_lng": driver_lng,
        "driver_location_updated_at": driver_location_updated_at,
    }


async def revoke_trip_share_token(
    token: str,
    user_id: int,
    db: AsyncSession,
) -> bool:
    """Delete a trip share token.  Only the creator may revoke.

    Returns True if deleted, False if the token was not found.
    Raises PermissionError if the token exists but belongs to a different user.
    """
    result = await db.execute(
        select(TripShareToken).where(TripShareToken.token == token)
    )
    share = result.scalar_one_or_none()
    if not share:
        return False
    if share.created_by != user_id:
        raise PermissionError("Not authorized to revoke this token")
    await db.delete(share)
    await db.flush()
    return True


async def list_trip_share_tokens(
    user_id: int,
    db: AsyncSession,
) -> list[TripShareToken]:
    """Return all non-expired share tokens created by *user_id*."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(TripShareToken).where(
            TripShareToken.created_by == user_id,
            TripShareToken.expires_at > now,
        )
    )
    return list(result.scalars().all())


async def add_emergency_contact(
    user_id: int,
    name: str,
    phone: str,
    db: AsyncSession,
    relationship_label: str | None = None,
) -> EmergencyContact:
    """Add an emergency contact for a user."""
    contact = EmergencyContact(
        user_id=user_id,
        name=name,
        phone=phone,
        relationship_label=relationship_label,
    )
    db.add(contact)
    await db.flush()
    return contact


async def list_emergency_contacts(user_id: int, db: AsyncSession) -> list[EmergencyContact]:
    """List all emergency contacts for a user."""
    result = await db.execute(
        select(EmergencyContact).where(EmergencyContact.user_id == user_id)
    )
    return list(result.scalars().all())


async def update_emergency_contact(
    contact_id: int,
    user_id: int,
    db: AsyncSession,
    name: str | None = None,
    phone: str | None = None,
    relationship_label: str | None = None,
) -> EmergencyContact:
    """Update an emergency contact.

    Only the owning user's contacts may be updated.  Raises ValueError if the
    contact does not exist or belongs to a different user.  Only non-None
    arguments are applied so callers can do a true partial update.
    """
    result = await db.execute(
        select(EmergencyContact).where(
            EmergencyContact.id == contact_id,
            EmergencyContact.user_id == user_id,
        )
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise ValueError("Contact not found")

    if name is not None:
        contact.name = name
    if phone is not None:
        contact.phone = phone
    if relationship_label is not None:
        contact.relationship_label = relationship_label

    await db.flush()
    return contact


async def delete_emergency_contact(contact_id: int, user_id: int, db: AsyncSession) -> bool:
    """Delete an emergency contact. Returns True if deleted, False if not found."""
    result = await db.execute(
        select(EmergencyContact).where(
            EmergencyContact.id == contact_id,
            EmergencyContact.user_id == user_id,
        )
    )
    contact = result.scalar_one_or_none()
    if not contact:
        return False
    await db.delete(contact)
    await db.flush()
    return True
