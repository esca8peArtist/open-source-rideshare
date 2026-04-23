"""GDPR-compliant user data export.

Gathers all personal data stored for a user and returns it as a structured
dict suitable for JSON serialisation. Geometry columns are omitted — addresses
are included instead.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationLog
from app.models.ride import Ride
from app.models.ride_preference import RidePreference
from app.models.saved_location import SavedLocation
from app.models.user import User


def _dt(val) -> str | None:
    return val.isoformat() if val is not None else None


async def export_user_data(user_id: int, db: AsyncSession) -> dict:
    # Profile
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return {}

    profile = {
        "id": user.id,
        "name": user.name,
        "phone": user.phone,
        "email": user.email,
        "role": user.role.value,
        "is_active": user.is_active,
        "phone_verified": user.phone_verified,
        "referral_code": user.referral_code,
        "referred_by": user.referred_by,
        "created_at": _dt(user.created_at),
        "updated_at": _dt(user.updated_at),
    }

    # Rides as rider (100 most recent)
    rider_result = await db.execute(
        select(Ride)
        .where(Ride.rider_id == user_id)
        .order_by(Ride.requested_at.desc())
        .limit(100)
    )
    rides_as_rider = [
        {
            "id": r.id,
            "status": r.status.value,
            "pickup_address": r.pickup_address,
            "dropoff_address": r.dropoff_address,
            "estimated_fare": r.estimated_fare,
            "actual_fare": r.actual_fare,
            "distance_km": r.distance_km,
            "duration_min": r.duration_min,
            "tip_amount": r.tip_amount,
            "promo_discount": r.promo_discount,
            "is_pool": r.is_pool,
            "requested_at": _dt(r.requested_at),
            "completed_at": _dt(r.completed_at),
            "cancelled_at": _dt(r.cancelled_at),
            "rider_rating": r.rider_rating,
            "driver_rating": r.driver_rating,
        }
        for r in rider_result.scalars().all()
    ]

    # Rides as driver (100 most recent)
    driver_result = await db.execute(
        select(Ride)
        .where(Ride.driver_id == user_id)
        .order_by(Ride.requested_at.desc())
        .limit(100)
    )
    rides_as_driver = [
        {
            "id": r.id,
            "status": r.status.value,
            "pickup_address": r.pickup_address,
            "dropoff_address": r.dropoff_address,
            "estimated_fare": r.estimated_fare,
            "actual_fare": r.actual_fare,
            "distance_km": r.distance_km,
            "duration_min": r.duration_min,
            "tip_amount": r.tip_amount,
            "requested_at": _dt(r.requested_at),
            "completed_at": _dt(r.completed_at),
            "cancelled_at": _dt(r.cancelled_at),
            "rider_rating": r.rider_rating,
            "driver_rating": r.driver_rating,
        }
        for r in driver_result.scalars().all()
    ]

    # Saved locations
    loc_result = await db.execute(
        select(SavedLocation).where(SavedLocation.user_id == user_id)
    )
    saved_locations = [
        {
            "id": loc.id,
            "label": loc.label.value,
            "name": loc.name,
            "address": loc.address,
            "lat": loc.lat,
            "lng": loc.lng,
            "created_at": _dt(loc.created_at),
        }
        for loc in loc_result.scalars().all()
    ]

    # Ride preferences (one row per rider, may not exist)
    pref_result = await db.execute(
        select(RidePreference).where(RidePreference.user_id == user_id)
    )
    pref = pref_result.scalar_one_or_none()
    ride_preferences = (
        {
            "quiet_ride": pref.quiet_ride,
            "music_off": pref.music_off,
            "temperature_preference": pref.temperature_preference.value,
            "pet_friendly": pref.pet_friendly,
            "extra_luggage": pref.extra_luggage,
            "accessibility_vehicle_needed": pref.accessibility_vehicle_needed,
            "hearing_impairment": pref.hearing_impairment,
            "has_service_animal": pref.has_service_animal,
            "visual_impairment": pref.visual_impairment,
            "pool_opt_out": pref.pool_opt_out,
            "communication_preference": pref.communication_preference.value,
            "notes": pref.notes,
        }
        if pref is not None
        else None
    )

    # Notification log (50 most recent, non-deleted)
    notif_result = await db.execute(
        select(NotificationLog)
        .where(
            NotificationLog.user_id == user_id,
            NotificationLog.deleted_at.is_(None),
        )
        .order_by(NotificationLog.created_at.desc())
        .limit(50)
    )
    notifications = [
        {
            "id": n.id,
            "type": n.notification_type,
            "channel": n.channel,
            "title": n.title,
            "body": n.body,
            "status": n.status.value,
            "is_read": n.is_read,
            "created_at": _dt(n.created_at),
            "read_at": _dt(n.read_at),
        }
        for n in notif_result.scalars().all()
    ]

    return {
        "profile": profile,
        "rides_as_rider": rides_as_rider,
        "rides_as_driver": rides_as_driver,
        "saved_locations": saved_locations,
        "ride_preferences": ride_preferences,
        "notifications": notifications,
    }
