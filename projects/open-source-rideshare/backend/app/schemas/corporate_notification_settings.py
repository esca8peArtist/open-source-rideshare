"""Pydantic schemas for corporate notification settings."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field

from app.models.corporate_notification_settings import NotificationEventType


class CorporateNotificationConfigUpdate(BaseModel):
    """Request body for updating a single notification config.

    All fields are optional — only supplied fields are applied.
    """

    enabled: Optional[bool] = None
    notify_billing_contacts: Optional[bool] = None
    notify_account_contacts: Optional[bool] = None
    notify_via_webhooks: Optional[bool] = None
    additional_emails: Optional[list[str]] = None


class BulkNotificationConfigEntry(BaseModel):
    """Single entry in a bulk-update request."""

    event_type: NotificationEventType
    enabled: Optional[bool] = None
    notify_billing_contacts: Optional[bool] = None
    notify_account_contacts: Optional[bool] = None
    notify_via_webhooks: Optional[bool] = None
    additional_emails: Optional[list[str]] = None


class BulkNotificationConfigUpdate(BaseModel):
    """Request body for updating multiple notification configs at once."""

    updates: list[BulkNotificationConfigEntry] = Field(
        ..., min_length=1, description="List of per-event config updates."
    )


class CorporateNotificationConfigResponse(BaseModel):
    """Notification config returned to callers."""

    id: int
    account_id: int
    event_type: NotificationEventType
    enabled: bool
    notify_billing_contacts: bool
    notify_account_contacts: bool
    notify_via_webhooks: bool
    additional_emails: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NotificationRecipientsResponse(BaseModel):
    """Preview of who would receive a notification for a given event type."""

    event_type: NotificationEventType
    billing_contact_emails: list[str]
    account_contact_emails: list[str]
    webhook_urls: list[str]
    additional_emails: list[str]
