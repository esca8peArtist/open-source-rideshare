"""Corporate Webhook endpoints.

Corporate admins configure HTTP POST endpoints to receive event notifications
for key corporate account events.

Admin endpoints (require account membership; service enforces admin role):
  GET    /corporate/accounts/me/webhooks                          — list webhooks
  POST   /corporate/accounts/me/webhooks                         — create webhook
  GET    /corporate/accounts/me/webhooks/{webhook_id}            — get webhook
  PUT    /corporate/accounts/me/webhooks/{webhook_id}            — update webhook
  DELETE /corporate/accounts/me/webhooks/{webhook_id}/deactivate — soft-delete
  DELETE /corporate/accounts/me/webhooks/{webhook_id}            — hard-delete
  GET    /corporate/accounts/me/webhooks/{webhook_id}/deliveries — delivery log
  POST   /corporate/accounts/me/webhooks/{webhook_id}/test       — send test ping

Platform-admin endpoints:
  GET /admin/corporate/accounts/{account_id}/webhooks — list all for account
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_webhook import (
    WebhookCreate,
    WebhookDeliveryListResponse,
    WebhookDeliveryResponse,
    WebhookListResponse,
    WebhookResponse,
    WebhookUpdate,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_webhook import (
    KNOWN_EVENT_TYPES,
    create_webhook,
    deactivate_webhook,
    delete_webhook,
    deliver_event,
    get_webhook,
    list_deliveries,
    list_webhooks,
    update_webhook,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-webhooks"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


def _webhook_to_response(webhook) -> WebhookResponse:
    return WebhookResponse.model_validate(webhook)


def _delivery_to_response(delivery) -> WebhookDeliveryResponse:
    return WebhookDeliveryResponse.model_validate(delivery)


# ---------------------------------------------------------------------------
# Admin: list webhooks
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/webhooks",
    response_model=WebhookListResponse,
    summary="Admin: list webhooks for my corporate account",
)
async def list_account_webhooks(
    active_only: bool = Query(True, description="When True, only return active webhooks."),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all webhooks configured for the caller's corporate account.

    Requires account membership.
    """
    account_id = await _resolve_account_id(db, user.id)
    webhooks = await list_webhooks(db, account_id, active_only=active_only)
    return WebhookListResponse(
        account_id=account_id,
        total=len(webhooks),
        webhooks=[_webhook_to_response(w) for w in webhooks],
    )


# ---------------------------------------------------------------------------
# Admin: create webhook
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/webhooks",
    response_model=WebhookResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a webhook for my corporate account",
)
async def create_account_webhook(
    data: WebhookCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new webhook endpoint for the caller's corporate account.

    Requires ADMIN role within the account (enforced by the service layer).
    """
    account_id = await _resolve_account_id(db, user.id)
    webhook = await create_webhook(
        db,
        account_id=account_id,
        url=data.url,
        event_types=data.event_types,
        description=data.description,
        created_by_id=user.id,
    )
    await db.commit()
    return _webhook_to_response(webhook)


# ---------------------------------------------------------------------------
# Admin: get webhook
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/webhooks/{webhook_id}",
    response_model=WebhookResponse,
    summary="Admin: get a webhook by ID",
)
async def get_account_webhook(
    webhook_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return details of a specific webhook.

    Requires account membership.
    """
    account_id = await _resolve_account_id(db, user.id)
    webhook = await get_webhook(db, account_id, webhook_id)
    return _webhook_to_response(webhook)


# ---------------------------------------------------------------------------
# Admin: update webhook
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/webhooks/{webhook_id}",
    response_model=WebhookResponse,
    summary="Admin: update a webhook",
)
async def update_account_webhook(
    webhook_id: uuid.UUID,
    data: WebhookUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing webhook.

    Updatable fields: url, event_types, description, is_active.
    Requires account membership.
    """
    account_id = await _resolve_account_id(db, user.id)
    webhook = await update_webhook(
        db,
        account_id=account_id,
        webhook_id=webhook_id,
        url=data.url,
        event_types=data.event_types,
        description=data.description,
        is_active=data.is_active,
    )
    await db.commit()
    return _webhook_to_response(webhook)


# ---------------------------------------------------------------------------
# Admin: deactivate webhook (soft-delete)
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/webhooks/{webhook_id}/deactivate",
    response_model=WebhookResponse,
    summary="Admin: deactivate a webhook (soft-delete)",
)
async def deactivate_account_webhook(
    webhook_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a webhook by setting is_active=False.

    The webhook record is preserved for audit purposes.
    Requires account membership.
    """
    account_id = await _resolve_account_id(db, user.id)
    webhook = await deactivate_webhook(db, account_id, webhook_id)
    await db.commit()
    return _webhook_to_response(webhook)


# ---------------------------------------------------------------------------
# Admin: hard-delete webhook
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/webhooks/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: hard-delete a webhook",
)
async def delete_account_webhook(
    webhook_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a webhook and all its delivery records.

    Requires account membership.
    """
    account_id = await _resolve_account_id(db, user.id)
    await delete_webhook(db, account_id, webhook_id)
    await db.commit()


# ---------------------------------------------------------------------------
# Admin: delivery log
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/webhooks/{webhook_id}/deliveries",
    response_model=WebhookDeliveryListResponse,
    summary="Admin: view delivery log for a webhook",
)
async def get_webhook_deliveries(
    webhook_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return delivery history for a webhook, most recent first.

    Requires account membership.
    """
    account_id = await _resolve_account_id(db, user.id)
    deliveries = await list_deliveries(db, account_id, webhook_id, limit=limit)
    return WebhookDeliveryListResponse(
        webhook_id=webhook_id,
        total=len(deliveries),
        deliveries=[_delivery_to_response(d) for d in deliveries],
    )


# ---------------------------------------------------------------------------
# Admin: test ping
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/webhooks/{webhook_id}/test",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Admin: send a test ping event to a webhook",
)
async def test_webhook(
    webhook_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a test ``ping`` event to the webhook endpoint.

    Returns 202 Accepted.  The delivery record is created regardless of
    whether the remote endpoint responds successfully.
    """
    account_id = await _resolve_account_id(db, user.id)
    webhook = await get_webhook(db, account_id, webhook_id)

    payload = {
        "event": "ping",
        "account_id": str(account_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {"message": "This is a test event from the rideshare platform."},
    }

    delivery = await deliver_event(db, webhook_id, "ping", payload)
    await db.commit()
    return {
        "delivery_id": str(delivery.id),
        "success": delivery.success,
        "status_code": delivery.status_code,
    }


# ---------------------------------------------------------------------------
# Platform-admin: list all webhooks for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/webhooks",
    response_model=WebhookListResponse,
    summary="Platform admin: list all webhooks for a corporate account",
)
async def platform_admin_list_webhooks(
    account_id: int,
    active_only: bool = Query(False),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all webhooks for any corporate account.

    Requires platform-level admin role.
    """
    webhooks = await list_webhooks(db, account_id, active_only=active_only)
    return WebhookListResponse(
        account_id=account_id,
        total=len(webhooks),
        webhooks=[_webhook_to_response(w) for w in webhooks],
    )
