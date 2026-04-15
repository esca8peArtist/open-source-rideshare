"""Corporate Notification Settings model.

Enterprise accounts can configure which events trigger email notifications and
to which contact types those notifications are routed.  This ties together the
existing CorporateBillingContact, CorporateAccountContact, and CorporateWebhook
systems into a unified notification routing layer.

Models
------
CorporateNotificationConfig — one row per (account, event_type) pair.

Tables
------
corporate_notification_configs — per-event routing config with a UNIQUE
    constraint on (account_id, event_type).
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class NotificationEventType(str, enum.Enum):
    """Event types that can trigger corporate account notifications."""

    member_joined = "member_joined"
    member_removed = "member_removed"
    policy_violation = "policy_violation"
    budget_threshold_crossed = "budget_threshold_crossed"
    invoice_generated = "invoice_generated"
    invoice_paid = "invoice_paid"
    ride_approval_requested = "ride_approval_requested"
    ride_approval_denied = "ride_approval_denied"
    low_credit_balance = "low_credit_balance"
    sso_login_failed = "sso_login_failed"
    api_key_created = "api_key_created"
    data_export_ready = "data_export_ready"


class CorporateNotificationConfig(Base):
    """Per-event notification routing configuration for a corporate account.

    One row per (account_id, event_type) combination.  When a row does not
    exist for a given event type it is created on first read with sensible
    defaults (see the service layer upsert-on-read helper).

    Attributes:
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        event_type: The notification event type this row configures.
        enabled: When False no notifications are dispatched for this event.
            Defaults to True.
        notify_billing_contacts: Route the notification to all active
            CorporateBillingContact rows on the account.  Defaults to False.
        notify_account_contacts: Route the notification to all active
            CorporateAccountContact rows on the account.  Defaults to True.
        notify_via_webhooks: Fire matching CorporateWebhook events.
            Defaults to True.
        additional_emails: JSONB list of ad-hoc email address strings that
            should always receive this notification.  Defaults to [].
        created_at: Creation timestamp (UTC).
        updated_at: Last modification timestamp (UTC).
    """

    __tablename__ = "corporate_notification_configs"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "event_type",
            name="uq_corp_notif_account_event",
        ),
        Index("ix_corp_notif_account_id", "account_id"),
        Index("ix_corp_notif_account_event", "account_id", "event_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    event_type: Mapped[NotificationEventType] = mapped_column(
        Enum(NotificationEventType, name="notificationeventtype"),
        nullable=False,
    )

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    notify_billing_contacts: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    notify_account_contacts: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    notify_via_webhooks: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    additional_emails: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
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

    account = relationship("BusinessAccount", foreign_keys=[account_id])
