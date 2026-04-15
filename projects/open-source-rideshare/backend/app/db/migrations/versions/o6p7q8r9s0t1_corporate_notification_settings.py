"""Corporate notification settings.

Enterprise accounts configure per-event notification routing, controlling
which contact groups and webhooks receive each notification type.

Tables created:
  corporate_notification_configs — one row per (account_id, event_type).

Enums created:
  notificationeventtype — the 12 supported notification event types.

Revision ID: o6p7q8r9s0t1
Revises:     n5o6p7q8r9s0
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "o6p7q8r9s0t1"
down_revision: str = "n5o6p7q8r9s0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum
    notificationeventtype = postgresql.ENUM(
        "member_joined",
        "member_removed",
        "policy_violation",
        "budget_threshold_crossed",
        "invoice_generated",
        "invoice_paid",
        "ride_approval_requested",
        "ride_approval_denied",
        "low_credit_balance",
        "sso_login_failed",
        "api_key_created",
        "data_export_ready",
        name="notificationeventtype",
    )
    notificationeventtype.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "corporate_notification_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "member_joined",
                "member_removed",
                "policy_violation",
                "budget_threshold_crossed",
                "invoice_generated",
                "invoice_paid",
                "ride_approval_requested",
                "ride_approval_denied",
                "low_credit_balance",
                "sso_login_failed",
                "api_key_created",
                "data_export_ready",
                name="notificationeventtype",
            ),
            nullable=False,
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "notify_billing_contacts",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "notify_account_contacts",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "notify_via_webhooks",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "additional_emails",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "account_id",
            "event_type",
            name="uq_corp_notif_account_event",
        ),
    )

    op.create_index(
        "ix_corp_notif_account_id",
        "corporate_notification_configs",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_notif_account_event",
        "corporate_notification_configs",
        ["account_id", "event_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_notif_account_event",
        table_name="corporate_notification_configs",
    )
    op.drop_index(
        "ix_corp_notif_account_id",
        table_name="corporate_notification_configs",
    )
    op.drop_table("corporate_notification_configs")
    sa.Enum(name="notificationeventtype").drop(op.get_bind(), checkfirst=True)
