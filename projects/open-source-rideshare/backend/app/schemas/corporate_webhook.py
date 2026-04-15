"""Pydantic schemas for Corporate Webhooks."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class WebhookCreate(BaseModel):
    """Payload for creating a new corporate webhook."""

    url: str = Field(..., description="HTTPS endpoint that will receive event POST requests.")
    event_types: list[str] = Field(
        ...,
        min_length=1,
        description="List of event type strings to subscribe to.",
    )
    description: Optional[str] = Field(None, description="Optional human-readable label.")


class WebhookUpdate(BaseModel):
    """Payload for updating a webhook.  All fields are optional."""

    url: Optional[str] = Field(None, description="New endpoint URL.")
    event_types: Optional[list[str]] = Field(None, description="New event type list.")
    description: Optional[str] = Field(None, description="New description.")
    is_active: Optional[bool] = Field(None, description="New active state.")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class WebhookResponse(BaseModel):
    """Full representation of a corporate webhook (secret is excluded)."""

    id: uuid.UUID
    account_id: int
    url: str
    event_types: list[str]
    is_active: bool
    description: Optional[str]
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    last_delivery_at: Optional[datetime]
    last_delivery_success: Optional[bool]

    model_config = {"from_attributes": True}


class WebhookListResponse(BaseModel):
    """List of webhooks for a corporate account."""

    account_id: int
    total: int
    webhooks: list[WebhookResponse]


class WebhookDeliveryResponse(BaseModel):
    """Representation of a single delivery attempt."""

    id: uuid.UUID
    webhook_id: uuid.UUID
    event_type: str
    payload: dict
    attempted_at: datetime
    status_code: Optional[int]
    response_body: Optional[str]
    success: bool
    attempt_number: int

    model_config = {"from_attributes": True}


class WebhookDeliveryListResponse(BaseModel):
    """List of delivery records for a webhook."""

    webhook_id: uuid.UUID
    total: int
    deliveries: list[WebhookDeliveryResponse]
