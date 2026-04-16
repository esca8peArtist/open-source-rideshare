"""Service layer for Corporate Employee Transport Preferences.

Each employee in a corporate account may maintain a personal preference
profile covering vehicle type, accessibility needs, home address, default
cost centre / trip purpose, pickup notes, and SMS notifications.

The profile is created on first access (upsert-on-read); subsequent writes
are partial updates.

Public surface
--------------
get_or_create_preference(db, account_id, member_id) -> TransportPreferenceResponse
update_preference(db, account_id, member_id, data) -> TransportPreferenceResponse
get_preference_for_member(db, account_id, member_id) -> TransportPreferenceResponse
list_preferences_for_account(db, account_id, has_accessibility_needs, is_active)
    -> TransportPreferenceListResponse
delete_preference(db, account_id, member_id) -> None
get_members_with_accessibility_needs(db, account_id) -> TransportPreferenceListResponse
get_members_needing_wav(db, account_id) -> TransportPreferenceListResponse
get_booking_defaults(db, account_id, member_id) -> BookingDefaultsResponse
list_all_platform(db, account_id) -> TransportPreferenceListResponse
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_transport_preference import (
    CorporateEmployeeTransportPreference,
)
from app.schemas.corporate_transport_preference import (
    BookingDefaultsResponse,
    TransportPreferenceListResponse,
    TransportPreferenceResponse,
    TransportPreferenceUpdate,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(
    pref: CorporateEmployeeTransportPreference,
) -> TransportPreferenceResponse:
    """Convert an ORM instance to a TransportPreferenceResponse."""
    return TransportPreferenceResponse(
        id=pref.id,
        account_id=pref.account_id,
        member_id=pref.member_id,
        preferred_vehicle_type=pref.preferred_vehicle_type,
        accessibility_needs=pref.accessibility_needs,
        home_address=pref.home_address,
        home_latitude=(
            float(pref.home_latitude) if pref.home_latitude is not None else None
        ),
        home_longitude=(
            float(pref.home_longitude) if pref.home_longitude is not None else None
        ),
        default_cost_center_id=pref.default_cost_center_id,
        default_trip_purpose_id=pref.default_trip_purpose_id,
        preferred_pickup_note=pref.preferred_pickup_note,
        notify_sms_number=pref.notify_sms_number,
        is_active=pref.is_active,
        created_at=pref.created_at,
        updated_at=pref.updated_at,
    )


async def _get_pref(
    db: AsyncSession,
    account_id: int,
    member_id: int,
) -> CorporateEmployeeTransportPreference | None:
    """Return the preference row for (account, member) or None."""
    result = await db.execute(
        select(CorporateEmployeeTransportPreference).where(
            CorporateEmployeeTransportPreference.account_id == account_id,
            CorporateEmployeeTransportPreference.member_id == member_id,
        )
    )
    return result.scalar_one_or_none()


async def _get_pref_or_404(
    db: AsyncSession,
    account_id: int,
    member_id: int,
) -> CorporateEmployeeTransportPreference:
    """Return preference row or raise HTTP 404."""
    pref = await _get_pref(db, account_id, member_id)
    if pref is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transport preference not found for this member.",
        )
    return pref


def _has_wav_requirement(
    pref: CorporateEmployeeTransportPreference,
) -> bool:
    """Return True if the preference indicates a WAV or wheelchair need."""
    if pref.preferred_vehicle_type == "wav":
        return True
    if pref.accessibility_needs and "wheelchair_accessible" in pref.accessibility_needs:
        return True
    return False


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def get_or_create_preference(
    db: AsyncSession,
    account_id: int,
    member_id: int,
) -> TransportPreferenceResponse:
    """Return the transport preference for the member, creating a blank row if none exists.

    This upsert-on-read pattern ensures callers always receive a valid
    response without the need for an explicit create step.
    """
    pref = await _get_pref(db, account_id, member_id)
    if pref is None:
        pref = CorporateEmployeeTransportPreference(
            account_id=account_id,
            member_id=member_id,
            is_active=True,
        )
        db.add(pref)
        await db.commit()
        await db.refresh(pref)
    return _to_response(pref)


async def update_preference(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    data: TransportPreferenceUpdate,
) -> TransportPreferenceResponse:
    """Partially update the transport preference for a member.

    Creates the row if it does not yet exist.  Only explicitly supplied
    fields are written; unset fields are left unchanged.
    """
    pref = await _get_pref(db, account_id, member_id)
    if pref is None:
        pref = CorporateEmployeeTransportPreference(
            account_id=account_id,
            member_id=member_id,
            is_active=True,
        )
        db.add(pref)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(pref, field, value)

    await db.commit()
    await db.refresh(pref)
    return _to_response(pref)


async def get_preference_for_member(
    db: AsyncSession,
    account_id: int,
    member_id: int,
) -> TransportPreferenceResponse:
    """Return the transport preference for a specific member.

    Raises HTTP 404 if no preference row exists.
    """
    pref = await _get_pref_or_404(db, account_id, member_id)
    return _to_response(pref)


async def list_preferences_for_account(
    db: AsyncSession,
    account_id: int,
    has_accessibility_needs: Optional[bool] = None,
    is_active: Optional[bool] = None,
) -> TransportPreferenceListResponse:
    """Return all transport preferences for an account.

    Optional filters:
      - ``has_accessibility_needs``: True → only rows with a non-empty
        accessibility_needs list; False → only rows where the list is NULL
        or empty.
      - ``is_active``: filter by active status.
    """
    stmt = select(CorporateEmployeeTransportPreference).where(
        CorporateEmployeeTransportPreference.account_id == account_id
    )
    if is_active is not None:
        stmt = stmt.where(
            CorporateEmployeeTransportPreference.is_active == is_active
        )
    stmt = stmt.order_by(CorporateEmployeeTransportPreference.member_id)

    result = await db.execute(stmt)
    prefs = result.scalars().all()

    if has_accessibility_needs is True:
        prefs = [
            p
            for p in prefs
            if p.accessibility_needs and len(p.accessibility_needs) > 0
        ]
    elif has_accessibility_needs is False:
        prefs = [
            p
            for p in prefs
            if not p.accessibility_needs or len(p.accessibility_needs) == 0
        ]

    return TransportPreferenceListResponse(
        items=[_to_response(p) for p in prefs],
        total=len(prefs),
    )


async def delete_preference(
    db: AsyncSession,
    account_id: int,
    member_id: int,
) -> None:
    """Hard-delete the transport preference for a member.

    Raises HTTP 404 if no preference row exists.
    """
    pref = await _get_pref_or_404(db, account_id, member_id)
    await db.delete(pref)
    await db.commit()


async def get_members_with_accessibility_needs(
    db: AsyncSession,
    account_id: int,
) -> TransportPreferenceListResponse:
    """Return active preference rows that have at least one accessibility need tag."""
    result = await db.execute(
        select(CorporateEmployeeTransportPreference).where(
            CorporateEmployeeTransportPreference.account_id == account_id,
            CorporateEmployeeTransportPreference.is_active == True,  # noqa: E712
            CorporateEmployeeTransportPreference.accessibility_needs.isnot(None),
        )
    )
    prefs = [
        p
        for p in result.scalars().all()
        if p.accessibility_needs and len(p.accessibility_needs) > 0
    ]
    return TransportPreferenceListResponse(
        items=[_to_response(p) for p in prefs],
        total=len(prefs),
    )


async def get_members_needing_wav(
    db: AsyncSession,
    account_id: int,
) -> TransportPreferenceListResponse:
    """Return active preference rows where a WAV (wheelchair-accessible vehicle) is required.

    A member requires a WAV when:
      - ``preferred_vehicle_type == 'wav'``, OR
      - ``'wheelchair_accessible' in accessibility_needs``
    """
    result = await db.execute(
        select(CorporateEmployeeTransportPreference).where(
            CorporateEmployeeTransportPreference.account_id == account_id,
            CorporateEmployeeTransportPreference.is_active == True,  # noqa: E712
        )
    )
    prefs = [p for p in result.scalars().all() if _has_wav_requirement(p)]
    return TransportPreferenceListResponse(
        items=[_to_response(p) for p in prefs],
        total=len(prefs),
    )


async def get_booking_defaults(
    db: AsyncSession,
    account_id: int,
    member_id: int,
) -> BookingDefaultsResponse:
    """Return the booking-defaults view of a member's transport preference.

    If no preference row exists, returns a defaults-only response with
    all fields None / False.
    """
    pref = await _get_pref(db, account_id, member_id)
    if pref is None or not pref.is_active:
        return BookingDefaultsResponse(
            member_id=member_id,
            preferred_vehicle_type=None,
            accessibility_needs=None,
            preferred_pickup_note=None,
            default_cost_center_id=None,
            default_trip_purpose_id=None,
            home_address=None,
            home_latitude=None,
            home_longitude=None,
            has_wav_requirement=False,
        )

    return BookingDefaultsResponse(
        member_id=member_id,
        preferred_vehicle_type=pref.preferred_vehicle_type,
        accessibility_needs=pref.accessibility_needs,
        preferred_pickup_note=pref.preferred_pickup_note,
        default_cost_center_id=pref.default_cost_center_id,
        default_trip_purpose_id=pref.default_trip_purpose_id,
        home_address=pref.home_address,
        home_latitude=(
            float(pref.home_latitude) if pref.home_latitude is not None else None
        ),
        home_longitude=(
            float(pref.home_longitude) if pref.home_longitude is not None else None
        ),
        has_wav_requirement=_has_wav_requirement(pref),
    )


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
) -> TransportPreferenceListResponse:
    """Platform-admin: list all transport preferences, optionally filtered by account."""
    stmt = select(CorporateEmployeeTransportPreference)
    if account_id is not None:
        stmt = stmt.where(
            CorporateEmployeeTransportPreference.account_id == account_id
        )
    stmt = stmt.order_by(
        CorporateEmployeeTransportPreference.account_id,
        CorporateEmployeeTransportPreference.member_id,
    )
    result = await db.execute(stmt)
    prefs = result.scalars().all()
    return TransportPreferenceListResponse(
        items=[_to_response(p) for p in prefs],
        total=len(prefs),
    )
