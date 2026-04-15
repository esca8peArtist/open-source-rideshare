"""Corporate Webhook models.

Corporate admins configure HTTP POST endpoints to receive event notifications
for key corporate account events (ride completions, invoices, expense reports,
budget alerts, etc.).  Each webhook has an HMAC-SHA256 secret for request
verification.

Models
------
CorporateWebhook         — a configured endpoint with subscribed event types.
CorporateWebhookDelivery — one delivery attempt for a single event.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateWebhook(Base):
    """An HTTP POST endpoint configured to receive corporate account events.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        url: The HTTPS endpoint to POST events to.
        secret: Random 32-byte hex string used for HMAC-SHA256 signatures.
        event_types: JSONB list of subscribed event type strings.
        is_active: When False the webhook will not receive deliveries.
        description: Optional human-readable label.
        created_by_id: FK to users — the admin who created the webhook.
        created_at: Creation timestamp.
        updated_at: Last modification timestamp.
        last_delivery_at: Timestamp of the most recent delivery attempt.
        last_delivery_success: Whether the most recent delivery succeeded.
    """

    __tablename__ = "corporate_webhooks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    url: Mapped[str] = mapped_column(Text, nullable=False)

    # Random 32-byte hex — never exposed in list responses
    secret: Mapped[str] = mapped_column(Text, nullable=False)

    # List of subscribed event type strings, e.g. ["ride.completed", "invoice.paid"]
    event_types: Mapped[list] = mapped_column(JSONB, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    last_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_delivery_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    account = relationship("BusinessAccount", foreign_keys=[account_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    deliveries: Mapped[list["CorporateWebhookDelivery"]] = relationship(
        "CorporateWebhookDelivery",
        back_populates="webhook",
        cascade="all, delete-orphan",
    )


class CorporateWebhookDelivery(Base):
    """One delivery attempt for a single event to a configured webhook.

    Attributes:
        id: UUID primary key.
        webhook_id: FK to corporate_webhooks (CASCADE delete).
        event_type: The event type string (e.g. ``ride.completed``).
        payload: The full JSON payload that was sent.
        attempted_at: When the delivery was attempted.
        status_code: HTTP response status code; null if request failed entirely.
        response_body: First 1000 chars of the response body.
        success: True when the HTTP response code was 200–299.
        attempt_number: Delivery attempt count (1 for first try).
    """

    __tablename__ = "corporate_webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    webhook_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("corporate_webhooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(Text, nullable=False)

    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)

    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    webhook: Mapped["CorporateWebhook"] = relationship(
        "CorporateWebhook", back_populates="deliveries"
    )
