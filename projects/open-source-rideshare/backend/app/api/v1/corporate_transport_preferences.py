"""Corporate Employee Transport Preference endpoints.

Each employee in a corporate account maintains a personal transport
preference profile — preferred vehicle type, accessibility needs, home
address defaults, default cost centre / trip purpose, driver pickup notes,
and an SMS notification number.  These preferences auto-populate booking
forms for corporate rides.

Member endpoints (own preferences):
  GET    /corporate/accounts/me/transport-preferences/me        — get own
  PUT    /corporate/accounts/me/transport-preferences/me        — update own
  DELETE /corporate/accounts/me/transport-preferences/me        — delete own
  GET    /corporate/accounts/me/transport-preferences/me/booking-defaults
                                                                — booking defaults view

Admin endpoints (account admins only):
  GET  /corporate/accounts/me/transport-preferences             — list all
  GET  /corporate/accounts/me/transport-preferences/accessibility
                                                                — accessibility list
  GET  /corporate/accounts/me/transport-preferences/wav-required
                                                                — WAV-needed list
  GET  /corporate/accounts/me/transport-preferences/{member_id} — get member
  PUT  /corporate/accounts/me/transport-preferences/{member_id} — update member

Platform-admin endpoints:
  GET /platform/corporate/transport-preferences                 — all
  GET /platform/corporate/accounts/{account_id}/transport-preferences
                                                                — by account
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_transport_preference import (
    BookingDefaultsResponse,
    TransportPreferenceListResponse,
    TransportPreferenceResponse,
    TransportPreferenceUpdate,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_transport_preference import (
    delete_preference,
    get_booking_defaults,
    get_members_needing_wav,
    get_members_with_accessibility_needs,
    get_or_create_preference,
    get_preference_for_member,
    list_all_platform,
    list_preferences_for_account,
    update_preference,
)
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Transport Preferences"])


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
# Member: get own preferences (upsert-on-read)
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/transport-preferences/me",
    response_model=TransportPreferenceResponse,
    summary="Get own transport preferences",
)
async def get_my_transport_preferences(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated employee's transport preference profile.

    Creates a blank preference row if none exists (upsert-on-read).
    Any active corporate account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_or_create_preference(db, account_id, user.id)


# ---------------------------------------------------------------------------
# Member: update own preferences
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/transport-preferences/me",
    response_model=TransportPreferenceResponse,
    summary="Update own transport preferences",
)
async def update_my_transport_preferences(
    data: TransportPreferenceUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the authenticated employee's transport preference profile.

    Only explicitly supplied fields are written; unset fields are left
    unchanged.  Creates the row if it does not exist.
    Any active corporate account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await update_preference(db, account_id, user.id, data)


# ---------------------------------------------------------------------------
# Member: delete own preferences
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/transport-preferences/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete own transport preferences",
)
async def delete_my_transport_preferences(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete the authenticated employee's transport preference profile.

    Returns 404 if no preference row exists.
    Any active corporate account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await delete_preference(db, account_id, user.id)


# ---------------------------------------------------------------------------
# Member: booking defaults view
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/transport-preferences/me/booking-defaults",
    response_model=BookingDefaultsResponse,
    summary="Get own transport preferences as booking defaults",
)
async def get_my_booking_defaults(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a booking-defaults view of the authenticated employee's preferences.

    Returns a structured object with only the fields relevant for pre-filling
    a new corporate booking form, including a ``has_wav_requirement`` flag.
    Returns safe defaults (all None / False) if no preference row exists.
    Any active corporate account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_booking_defaults(db, account_id, user.id)


# ---------------------------------------------------------------------------
# Admin: list all preferences for account
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/transport-preferences",
    response_model=TransportPreferenceListResponse,
    summary="List all employee transport preferences (admin only)",
)
async def list_account_transport_preferences(
    has_accessibility_needs: Optional[bool] = Query(
        None,
        description="Filter: True = only rows with accessibility needs; False = only without",
    ),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all employee transport preferences for the account.

    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_preferences_for_account(
        db, account_id, has_accessibility_needs=has_accessibility_needs, is_active=is_active
    )


# ---------------------------------------------------------------------------
# Admin: list members with accessibility needs (must precede /{member_id})
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/transport-preferences/accessibility",
    response_model=TransportPreferenceListResponse,
    summary="List employees with accessibility needs (admin only)",
)
async def list_accessibility_preferences(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return active transport preferences where any accessibility need is recorded.

    Useful for fleet ops to ensure appropriate vehicles are available.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await get_members_with_accessibility_needs(db, account_id)


# ---------------------------------------------------------------------------
# Admin: list members needing WAV (must precede /{member_id})
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/transport-preferences/wav-required",
    response_model=TransportPreferenceListResponse,
    summary="List employees requiring wheelchair-accessible vehicles (admin only)",
)
async def list_wav_required_preferences(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return active transport preferences where a WAV is required.

    A member requires a WAV when preferred_vehicle_type is 'wav' OR
    'wheelchair_accessible' is in accessibility_needs.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await get_members_needing_wav(db, account_id)


# ---------------------------------------------------------------------------
# Admin: get specific member preference
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/transport-preferences/{member_id}",
    response_model=TransportPreferenceResponse,
    summary="Get transport preferences for a specific employee (admin only)",
)
async def get_member_transport_preferences(
    member_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the transport preference profile for any employee in the account.

    Returns 404 if the member has no preference row.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await get_preference_for_member(db, account_id, member_id)


# ---------------------------------------------------------------------------
# Admin: update specific member preference
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/transport-preferences/{member_id}",
    response_model=TransportPreferenceResponse,
    summary="Update transport preferences for a specific employee (admin only)",
)
async def update_member_transport_preferences(
    member_id: int,
    data: TransportPreferenceUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the transport preference profile for any employee in the account.

    Creates the row if it does not yet exist.  Only supplied fields are
    written.  Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await update_preference(db, account_id, member_id, data)


# ---------------------------------------------------------------------------
# Platform-admin: list all preferences
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/transport-preferences",
    response_model=TransportPreferenceListResponse,
    summary="Platform admin: list all employee transport preferences",
)
async def admin_list_all_transport_preferences(
    account_id: Optional[int] = Query(None, description="Filter by account ID"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all employee transport preferences across all accounts.

    Optionally filter by account_id.  Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id)


# ---------------------------------------------------------------------------
# Platform-admin: list preferences for a specific account
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/accounts/{account_id}/transport-preferences",
    response_model=TransportPreferenceListResponse,
    summary="Platform admin: list transport preferences for a specific account",
)
async def admin_list_account_transport_preferences(
    account_id: int,
    has_accessibility_needs: Optional[bool] = Query(None),
    is_active: Optional[bool] = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all employee transport preferences for any corporate account.

    Platform admin only.
    """
    return await list_preferences_for_account(
        db, account_id, has_accessibility_needs=has_accessibility_needs, is_active=is_active
    )
