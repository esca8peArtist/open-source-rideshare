"""Endpoints for per-user notification preferences.

Endpoints
---------
GET    /users/me/notification-preferences
    Returns the full preference map (all types x all channels) with defaults.

PUT    /users/me/notification-preferences/bulk
    Set multiple preferences in a single request.

PUT    /users/me/notification-preferences/{notification_type}/{channel}
    Set a single preference.

DELETE /users/me/notification-preferences/{notification_type}/{channel}
    Reset a preference to its default (opt-in / enabled).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.notification_preference import (
    BulkSetPreferenceRequest,
    NotificationPreferenceResponse,
    SetPreferenceRequest,
    UserPreferencesResponse,
)
from app.services.notification_preferences import (
    bulk_set_preferences,
    get_user_preferences,
    reset_preference,
    set_preference,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users/me/notification-preferences", tags=["notification-preferences"])

# Valid values used for path-parameter validation
_VALID_NOTIFICATION_TYPES: frozenset[str] = frozenset(
    {
        "ride_matched",
        "ride_cancelled",
        "ride_completed",
        "driver_en_route",
        "driver_arrived",
        "payment_received",
        "sos_alert",
        "rating_received",
        "account_verification",
        "payout_completed",
        "ride_reminder",
        "fare_split_request",
        "promo_applied",
        "background_check_approved",
        "background_check_action_required",
    }
)

_VALID_CHANNELS: frozenset[str] = frozenset({"push", "sms", "email"})


def _validate_type_and_channel(notification_type: str, channel: str) -> None:
    """Raise 422 if notification_type or channel is not valid."""
    if notification_type not in _VALID_NOTIFICATION_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Invalid notification_type '{notification_type}'. "
                f"Valid values: {sorted(_VALID_NOTIFICATION_TYPES)}"
            ),
        )
    if channel not in _VALID_CHANNELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid channel '{channel}'. Valid values: {sorted(_VALID_CHANNELS)}",
        )


@router.get("", response_model=UserPreferencesResponse)
async def get_preferences(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPreferencesResponse:
    """Get all notification preferences for the current user.

    Returns the complete matrix of (notification_type x channel) with the
    effective enabled value.  Combinations that have no explicit DB record
    are returned as enabled=True (the default opt-in state).
    """
    prefs = await get_user_preferences(db, user.id)
    return UserPreferencesResponse(preferences=prefs)


@router.put("/bulk", response_model=list[NotificationPreferenceResponse])
async def bulk_update_preferences(
    req: BulkSetPreferenceRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationPreferenceResponse]:
    """Set multiple notification preferences in one request.

    Each entry in ``updates`` must include ``notification_type``, ``channel``,
    and ``enabled``.  Validation of both fields is enforced by the schema.
    """
    updates = [u.model_dump() for u in req.updates]
    saved = await bulk_set_preferences(db, user.id, updates)
    return [NotificationPreferenceResponse.model_validate(p) for p in saved]


@router.put("/{notification_type}/{channel}", response_model=NotificationPreferenceResponse)
async def update_preference(
    notification_type: str,
    channel: str,
    req: SetPreferenceRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationPreferenceResponse:
    """Set a single notification preference for the current user.

    Path parameters are validated against the known notification_type and
    channel values.  The request body ``enabled`` field controls the preference.
    """
    _validate_type_and_channel(notification_type, channel)

    # Path params take precedence — they must match the body if body provides them
    pref = await set_preference(
        db,
        user_id=user.id,
        notification_type=notification_type,
        channel=channel,
        enabled=req.enabled,
    )
    return NotificationPreferenceResponse.model_validate(pref)


@router.delete("/{notification_type}/{channel}", status_code=status.HTTP_204_NO_CONTENT)
async def reset_single_preference(
    notification_type: str,
    channel: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Reset a single preference to the default (enabled).

    Deletes the explicit preference record so the combination reverts to the
    default opt-in state.  Returns 204 whether or not a record existed.
    """
    _validate_type_and_channel(notification_type, channel)
    await reset_preference(db, user.id, notification_type, channel)
