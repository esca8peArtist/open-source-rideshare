"""Service functions for corporate notification settings.

Enterprise accounts configure per-event notification routing here.  The
upsert-on-read pattern means callers never need to pre-create rows — a missing
row is transparently created with defaults when first accessed.

Public API
----------
get_notification_config         — get single config row; create with defaults if missing
get_all_notification_configs    — return all 12 configs; fill defaults for any missing
update_notification_config      — update one config; 404 if not found
bulk_update_notification_configs — update multiple configs in one call
reset_notification_configs      — reset all configs to defaults
get_recipients_for_event        — return routing targets (emails, webhook urls) for an event
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_billing_contact import CorporateBillingContact
from app.models.corporate_account_contact import CorporateAccountContact
from app.models.corporate_webhook import CorporateWebhook
from app.models.corporate_notification_settings import (
    CorporateNotificationConfig,
    NotificationEventType,
)

# All event types as a fixed ordered list
_ALL_EVENT_TYPES: list[NotificationEventType] = list(NotificationEventType)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _default_config(
    account_id: int, event_type: NotificationEventType
) -> CorporateNotificationConfig:
    """Build a new CorporateNotificationConfig with default values."""
    return CorporateNotificationConfig(
        account_id=account_id,
        event_type=event_type,
        enabled=True,
        notify_billing_contacts=False,
        notify_account_contacts=True,
        notify_via_webhooks=True,
        additional_emails=[],
    )


async def _get_config_or_404(
    db: AsyncSession, account_id: int, event_type: NotificationEventType
) -> CorporateNotificationConfig:
    """Return the config row; raise 404 if it does not exist."""
    result = await db.execute(
        select(CorporateNotificationConfig).where(
            CorporateNotificationConfig.account_id == account_id,
            CorporateNotificationConfig.event_type == event_type,
        )
    )
    cfg = result.scalar_one_or_none()
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Notification config for event '{event_type.value}' not found "
                "on this account."
            ),
        )
    return cfg


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


async def get_notification_config(
    db: AsyncSession,
    account_id: int,
    event_type: NotificationEventType,
) -> CorporateNotificationConfig:
    """Return the notification config for one event type.

    If the row does not yet exist it is created with defaults and flushed
    (upsert-on-read pattern).
    """
    result = await db.execute(
        select(CorporateNotificationConfig).where(
            CorporateNotificationConfig.account_id == account_id,
            CorporateNotificationConfig.event_type == event_type,
        )
    )
    cfg = result.scalar_one_or_none()
    if cfg is None:
        cfg = _default_config(account_id, event_type)
        db.add(cfg)
        await db.flush()
    return cfg


async def get_all_notification_configs(
    db: AsyncSession, account_id: int
) -> list[CorporateNotificationConfig]:
    """Return all 12 notification configs for *account_id*.

    Any missing event types are created with defaults so the caller always
    receives exactly 12 rows.
    """
    result = await db.execute(
        select(CorporateNotificationConfig).where(
            CorporateNotificationConfig.account_id == account_id
        )
    )
    existing = {cfg.event_type: cfg for cfg in result.scalars().all()}

    configs: list[CorporateNotificationConfig] = []
    for event_type in _ALL_EVENT_TYPES:
        if event_type in existing:
            configs.append(existing[event_type])
        else:
            cfg = _default_config(account_id, event_type)
            db.add(cfg)
            await db.flush()
            configs.append(cfg)

    return configs


async def update_notification_config(
    db: AsyncSession,
    account_id: int,
    event_type: NotificationEventType,
    **kwargs: Any,
) -> CorporateNotificationConfig:
    """Partially update the notification config for one event type.

    Only keys present in *kwargs* are applied.  Raises 404 if the row has
    never been created (i.e. the caller has not yet read it).
    """
    cfg = await _get_config_or_404(db, account_id, event_type)
    for field, value in kwargs.items():
        setattr(cfg, field, value)
    await db.flush()
    return cfg


async def bulk_update_notification_configs(
    db: AsyncSession,
    account_id: int,
    updates: list[dict[str, Any]],
) -> list[CorporateNotificationConfig]:
    """Update multiple notification configs in a single call.

    Each entry in *updates* must contain ``event_type`` plus at least one
    field to update.  Rows that do not exist are created with defaults before
    the update is applied.

    Returns the updated config objects in the same order as *updates*.
    """
    results: list[CorporateNotificationConfig] = []
    for entry in updates:
        entry = dict(entry)  # copy so we can mutate
        raw_event_type = entry.pop("event_type")
        try:
            event_type = NotificationEventType(raw_event_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown event_type: '{raw_event_type}'.",
            )
        # Upsert-on-read: create row if missing
        cfg = await get_notification_config(db, account_id, event_type)
        for field, value in entry.items():
            setattr(cfg, field, value)
        await db.flush()
        results.append(cfg)
    return results


async def reset_notification_configs(
    db: AsyncSession, account_id: int
) -> list[CorporateNotificationConfig]:
    """Reset all notification configs for *account_id* to default values.

    Existing rows are updated in-place; missing rows are created.  Returns all
    12 configs after the reset.
    """
    result = await db.execute(
        select(CorporateNotificationConfig).where(
            CorporateNotificationConfig.account_id == account_id
        )
    )
    existing = {cfg.event_type: cfg for cfg in result.scalars().all()}

    configs: list[CorporateNotificationConfig] = []
    for event_type in _ALL_EVENT_TYPES:
        if event_type in existing:
            cfg = existing[event_type]
            cfg.enabled = True
            cfg.notify_billing_contacts = False
            cfg.notify_account_contacts = True
            cfg.notify_via_webhooks = True
            cfg.additional_emails = []
        else:
            cfg = _default_config(account_id, event_type)
            db.add(cfg)
        await db.flush()
        configs.append(cfg)

    return configs


async def get_recipients_for_event(
    db: AsyncSession,
    account_id: int,
    event_type: NotificationEventType,
) -> dict[str, list[str]]:
    """Return notification routing targets for a given event.

    Queries billing contacts, account contacts, and webhooks according to the
    flags on the notification config row.  Used internally by notification
    dispatch and exposed via the preview-recipients endpoint.

    Returns a dict with keys:
        billing_contact_emails  — list[str]
        account_contact_emails  — list[str]
        webhook_urls            — list[str]
        additional_emails       — list[str]
    """
    cfg = await get_notification_config(db, account_id, event_type)

    billing_emails: list[str] = []
    if cfg.enabled and cfg.notify_billing_contacts:
        bc_result = await db.execute(
            select(CorporateBillingContact).where(
                CorporateBillingContact.account_id == account_id,
                CorporateBillingContact.is_active.is_(True),
            )
        )
        billing_emails = [bc.email for bc in bc_result.scalars().all()]

    account_emails: list[str] = []
    if cfg.enabled and cfg.notify_account_contacts:
        ac_result = await db.execute(
            select(CorporateAccountContact).where(
                CorporateAccountContact.account_id == account_id,
                CorporateAccountContact.is_active.is_(True),
            )
        )
        account_emails = [ac.email for ac in ac_result.scalars().all()]

    webhook_urls: list[str] = []
    if cfg.enabled and cfg.notify_via_webhooks:
        wh_result = await db.execute(
            select(CorporateWebhook).where(
                CorporateWebhook.account_id == account_id,
                CorporateWebhook.is_active.is_(True),
            )
        )
        webhook_urls = [wh.url for wh in wh_result.scalars().all()]

    additional = list(cfg.additional_emails) if cfg.enabled else []

    return {
        "billing_contact_emails": billing_emails,
        "account_contact_emails": account_emails,
        "webhook_urls": webhook_urls,
        "additional_emails": additional,
    }
