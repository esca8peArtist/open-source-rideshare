"""Service layer for Corporate Webhooks.

Corporate admins configure HTTP POST endpoints to receive event notifications
for key corporate account events.  Each delivery is signed with HMAC-SHA256
using the webhook's secret.

Public surface
--------------
create_webhook(db, account_id, url, event_types, description, created_by_id)
get_webhook(db, account_id, webhook_id)
list_webhooks(db, account_id, active_only)
update_webhook(db, account_id, webhook_id, **fields)
deactivate_webhook(db, account_id, webhook_id)
delete_webhook(db, account_id, webhook_id)
deliver_event(db, webhook_id, event_type, payload)
list_deliveries(db, account_id, webhook_id, limit)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_webhook import CorporateWebhook, CorporateWebhookDelivery

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known event types
# ---------------------------------------------------------------------------

KNOWN_EVENT_TYPES: frozenset[str] = frozenset(
    [
        "ride.completed",
        "invoice.finalized",
        "invoice.paid",
        "expense_report.submitted",
        "expense_report.approved",
        "expense_report.rejected",
        "budget_alert.triggered",
        "ride_approval.approved",
        "ride_approval.rejected",
        "employee.joined",
    ]
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _generate_secret() -> str:
    """Generate a random 32-byte hex secret for HMAC signing."""
    return os.urandom(32).hex()


def _validate_event_types(event_types: list[str]) -> None:
    """Raise HTTP 422 if any event type is not in the known set."""
    unknown = set(event_types) - KNOWN_EVENT_TYPES
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown event type(s): {sorted(unknown)}. "
            f"Valid types are: {sorted(KNOWN_EVENT_TYPES)}",
        )


async def _get_webhook_by_id(
    db: AsyncSession,
    account_id: int,
    webhook_id: uuid.UUID,
) -> CorporateWebhook:
    """Return the webhook or raise HTTP 404 if not found in this account."""
    result = await db.execute(
        select(CorporateWebhook).where(
            CorporateWebhook.id == webhook_id,
            CorporateWebhook.account_id == account_id,
        )
    )
    webhook = result.scalar_one_or_none()
    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found in this account.",
        )
    return webhook


def _sign_payload(secret: str, body: bytes) -> str:
    """Return ``sha256=<hex>`` HMAC-SHA256 signature over *body*."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


async def create_webhook(
    db: AsyncSession,
    account_id: int,
    url: str,
    event_types: list[str],
    description: Optional[str] = None,
    created_by_id: Optional[int] = None,
) -> CorporateWebhook:
    """Create a new webhook for a corporate account.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        url: HTTPS endpoint to receive event POST requests.
        event_types: List of event type strings to subscribe to.
        description: Optional human-readable label.
        created_by_id: ID of the admin creating this webhook.

    Returns:
        The newly created CorporateWebhook instance.

    Raises:
        HTTP 422: When any event type is not in the known set.
    """
    _validate_event_types(event_types)

    webhook = CorporateWebhook(
        account_id=account_id,
        url=url,
        secret=_generate_secret(),
        event_types=event_types,
        description=description,
        is_active=True,
        created_by_id=created_by_id,
    )
    db.add(webhook)
    await db.flush()
    return webhook


async def get_webhook(
    db: AsyncSession,
    account_id: int,
    webhook_id: uuid.UUID,
) -> CorporateWebhook:
    """Return a single webhook by ID.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        webhook_id: Webhook UUID.

    Raises:
        HTTP 404: When the webhook is not found in this account.
    """
    return await _get_webhook_by_id(db, account_id, webhook_id)


async def list_webhooks(
    db: AsyncSession,
    account_id: int,
    active_only: bool = True,
) -> list[CorporateWebhook]:
    """Return webhooks for a corporate account.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        active_only: When True, only return active webhooks.

    Returns:
        List of CorporateWebhook instances.
    """
    q = select(CorporateWebhook).where(CorporateWebhook.account_id == account_id)
    if active_only:
        q = q.where(CorporateWebhook.is_active.is_(True))
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_webhook(
    db: AsyncSession,
    account_id: int,
    webhook_id: uuid.UUID,
    url: Optional[str] = None,
    event_types: Optional[list[str]] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> CorporateWebhook:
    """Update an existing webhook.

    Updatable fields: url, event_types, description, is_active.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        webhook_id: Webhook UUID.
        url: New endpoint URL, if changing.
        event_types: New event type list, if changing.
        description: New description, if changing.
        is_active: New active state, if changing.

    Returns:
        The updated CorporateWebhook instance.

    Raises:
        HTTP 404: When the webhook is not found in this account.
        HTTP 422: When any supplied event type is unknown.
    """
    webhook = await _get_webhook_by_id(db, account_id, webhook_id)

    if url is not None:
        webhook.url = url
    if event_types is not None:
        _validate_event_types(event_types)
        webhook.event_types = event_types
    if description is not None:
        webhook.description = description
    if is_active is not None:
        webhook.is_active = is_active

    await db.flush()
    return webhook


async def deactivate_webhook(
    db: AsyncSession,
    account_id: int,
    webhook_id: uuid.UUID,
) -> CorporateWebhook:
    """Soft-delete a webhook by setting is_active=False.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        webhook_id: Webhook UUID.

    Returns:
        The updated CorporateWebhook instance.

    Raises:
        HTTP 404: When the webhook is not found in this account.
        HTTP 409: When the webhook is already inactive.
    """
    webhook = await _get_webhook_by_id(db, account_id, webhook_id)
    if not webhook.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Webhook is already inactive.",
        )
    webhook.is_active = False
    await db.flush()
    return webhook


async def delete_webhook(
    db: AsyncSession,
    account_id: int,
    webhook_id: uuid.UUID,
) -> None:
    """Hard-delete a webhook and all its delivery records.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        webhook_id: Webhook UUID.

    Raises:
        HTTP 404: When the webhook is not found in this account.
    """
    webhook = await _get_webhook_by_id(db, account_id, webhook_id)
    await db.delete(webhook)
    await db.flush()


async def deliver_event(
    db: AsyncSession,
    webhook_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
) -> CorporateWebhookDelivery:
    """POST a JSON payload to a webhook endpoint and record the delivery.

    The request body is the JSON-serialised *payload*.  The
    ``X-Rideshare-Signature`` header carries the HMAC-SHA256 signature.

    Does not raise on HTTP error status codes — delivery failures are logged
    and recorded in the delivery table.  Network errors are also swallowed.

    Args:
        db: Database session.
        webhook_id: Webhook UUID — must exist in the database.
        event_type: Event type string (e.g. ``ride.completed``).
        payload: Arbitrary event-specific data to include in the body.

    Returns:
        The created CorporateWebhookDelivery record.
    """
    result = await db.execute(
        select(CorporateWebhook).where(CorporateWebhook.id == webhook_id)
    )
    webhook = result.scalar_one_or_none()
    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found.",
        )

    body = json.dumps(payload, default=str).encode("utf-8")
    signature = _sign_payload(webhook.secret, body)

    status_code: Optional[int] = None
    response_body: Optional[str] = None
    success = False

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                webhook.url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Rideshare-Signature": signature,
                },
            )
        status_code = resp.status_code
        response_body = resp.text[:1000] if resp.text else None
        success = 200 <= status_code < 300
        if not success:
            logger.warning(
                "Webhook delivery to %s returned status %d", webhook.url, status_code
            )
    except Exception as exc:
        logger.error("Webhook delivery to %s failed: %s", webhook.url, exc)

    now = datetime.now(timezone.utc)
    delivery = CorporateWebhookDelivery(
        webhook_id=webhook_id,
        event_type=event_type,
        payload=payload,
        attempted_at=now,
        status_code=status_code,
        response_body=response_body,
        success=success,
    )
    db.add(delivery)

    webhook.last_delivery_at = now
    webhook.last_delivery_success = success

    await db.flush()
    return delivery


async def list_deliveries(
    db: AsyncSession,
    account_id: int,
    webhook_id: uuid.UUID,
    limit: int = 50,
) -> list[CorporateWebhookDelivery]:
    """Return delivery records for a webhook, most recent first.

    Args:
        db: Database session.
        account_id: Corporate account identifier (used to verify ownership).
        webhook_id: Webhook UUID.
        limit: Maximum number of records to return.

    Returns:
        List of CorporateWebhookDelivery instances.

    Raises:
        HTTP 404: When the webhook is not found in this account.
    """
    # Verify the webhook belongs to this account
    await _get_webhook_by_id(db, account_id, webhook_id)

    result = await db.execute(
        select(CorporateWebhookDelivery)
        .where(CorporateWebhookDelivery.webhook_id == webhook_id)
        .order_by(CorporateWebhookDelivery.attempted_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
