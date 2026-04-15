"""Corporate Notification Settings endpoints.

Enterprise accounts configure per-event notification routing here, controlling
which contact groups and webhooks receive each notification type.

Admin endpoints (require authenticated user):
  GET  /corporate/{account_id}/notification-settings
       — list all 12 notification configs
  GET  /corporate/{account_id}/notification-settings/{event_type}
       — get single config
  PUT  /corporate/{account_id}/notification-settings/{event_type}
       — update single config
  POST /corporate/{account_id}/notification-settings/bulk-update
       — update multiple configs
  POST /corporate/{account_id}/notification-settings/reset
       — reset all to defaults
  GET  /corporate/{account_id}/notification-settings/{event_type}/preview-recipients
       — show who would receive this notification

Platform-admin endpoints:
  GET /platform-admin/notification-settings/{account_id}
      — view any account's settings
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_notification_settings import NotificationEventType
from app.models.user import User
from app.schemas.corporate_notification_settings import (
    BulkNotificationConfigUpdate,
    CorporateNotificationConfigResponse,
    CorporateNotificationConfigUpdate,
    NotificationRecipientsResponse,
)
from app.services.corporate_notification_settings import (
    bulk_update_notification_configs,
    get_all_notification_configs,
    get_notification_config,
    get_recipients_for_event,
    reset_notification_configs,
    update_notification_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-notification-settings"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(cfg: object) -> CorporateNotificationConfigResponse:
    return CorporateNotificationConfigResponse.model_validate(cfg)


# ---------------------------------------------------------------------------
# Admin: list all notification configs
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/notification-settings",
    response_model=list[CorporateNotificationConfigResponse],
    summary="Admin: list all notification configs for a corporate account",
)
async def list_notification_configs_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all 12 notification configs for *account_id*.

    Missing configs are created with defaults on first access so the response
    always contains exactly 12 entries — one per event type.
    """
    configs = await get_all_notification_configs(db, account_id=account_id)
    await db.commit()
    return [_to_response(c) for c in configs]


# ---------------------------------------------------------------------------
# Admin: get single notification config
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/notification-settings/{event_type}",
    response_model=CorporateNotificationConfigResponse,
    summary="Admin: get notification config for a specific event type",
)
async def get_notification_config_endpoint(
    account_id: int,
    event_type: NotificationEventType,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the notification config for one event type.

    Creates the row with defaults if it does not yet exist.
    """
    cfg = await get_notification_config(db, account_id=account_id, event_type=event_type)
    await db.commit()
    return _to_response(cfg)


# ---------------------------------------------------------------------------
# Admin: update single notification config
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/notification-settings/{event_type}",
    response_model=CorporateNotificationConfigResponse,
    summary="Admin: update notification config for a specific event type",
)
async def update_notification_config_endpoint(
    account_id: int,
    event_type: NotificationEventType,
    data: CorporateNotificationConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the notification config for one event type.

    Only supplied fields are changed.  If the row does not exist yet it is
    first created with defaults, then the update is applied.
    """
    # Ensure the row exists (upsert-on-read)
    await get_notification_config(db, account_id=account_id, event_type=event_type)
    updates = data.model_dump(exclude_none=True)
    cfg = await update_notification_config(
        db, account_id=account_id, event_type=event_type, **updates
    )
    await db.commit()
    return _to_response(cfg)


# ---------------------------------------------------------------------------
# Admin: bulk update notification configs
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/notification-settings/bulk-update",
    response_model=list[CorporateNotificationConfigResponse],
    summary="Admin: bulk-update multiple notification configs",
)
async def bulk_update_notification_configs_endpoint(
    account_id: int,
    data: BulkNotificationConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update multiple notification configs in a single request.

    Each entry specifies an event_type and the fields to change.  Existing
    rows are updated; missing rows are created with defaults first.
    """
    updates_dicts = [entry.model_dump(exclude_none=False) for entry in data.updates]
    configs = await bulk_update_notification_configs(
        db, account_id=account_id, updates=updates_dicts
    )
    await db.commit()
    return [_to_response(c) for c in configs]


# ---------------------------------------------------------------------------
# Admin: reset all notification configs to defaults
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/notification-settings/reset",
    response_model=list[CorporateNotificationConfigResponse],
    summary="Admin: reset all notification configs to defaults",
)
async def reset_notification_configs_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reset all 12 notification configs for *account_id* to their default values.

    Returns the full set of 12 configs after the reset.
    """
    configs = await reset_notification_configs(db, account_id=account_id)
    await db.commit()
    return [_to_response(c) for c in configs]


# ---------------------------------------------------------------------------
# Admin: preview recipients
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/notification-settings/{event_type}/preview-recipients",
    response_model=NotificationRecipientsResponse,
    summary="Admin: preview who would receive a notification for a given event type",
)
async def preview_recipients_endpoint(
    account_id: int,
    event_type: NotificationEventType,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current routing targets for *event_type*.

    Shows which billing contacts, account contacts, webhooks, and additional
    email addresses would be notified if this event fired right now.
    """
    recipients = await get_recipients_for_event(
        db, account_id=account_id, event_type=event_type
    )
    await db.commit()
    return NotificationRecipientsResponse(
        event_type=event_type,
        **recipients,
    )


# ---------------------------------------------------------------------------
# Platform-admin: view any account's settings
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/notification-settings/{account_id}",
    response_model=list[CorporateNotificationConfigResponse],
    summary="Platform admin: view notification settings for any corporate account",
)
async def platform_admin_list_notification_configs(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all notification configs for any corporate account.

    Creates missing configs with defaults so the response always contains
    exactly 12 entries.
    """
    configs = await get_all_notification_configs(db, account_id=account_id)
    await db.commit()
    return [_to_response(c) for c in configs]
