"""Create corporate_webhooks and corporate_webhook_deliveries tables.

Corporate admins configure HTTP POST endpoints to receive event notifications
for key corporate account events.  Each webhook is signed with HMAC-SHA256.

Tables created:
  corporate_webhooks           — configured endpoints with subscribed event types.
  corporate_webhook_deliveries — individual delivery attempts per event.

Revision ID: i9j0k1l2m3n4
Revises:     z2a3b4c5d6e7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "i9j0k1l2m3n4"
down_revision: str = "z2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corporate_webhooks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("event_types", postgresql.JSONB(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
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
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_success", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corporate_webhooks_account_id",
        "corporate_webhooks",
        ["account_id"],
    )
    op.create_index(
        "ix_corporate_webhooks_is_active",
        "corporate_webhooks",
        ["is_active"],
    )

    op.create_table(
        "corporate_webhook_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("webhook_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column(
            "success",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["webhook_id"],
            ["corporate_webhooks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corp_webhook_deliveries_webhook_id",
        "corporate_webhook_deliveries",
        ["webhook_id"],
    )
    op.create_index(
        "ix_corp_webhook_deliveries_attempted_at",
        "corporate_webhook_deliveries",
        ["attempted_at"],
    )
    op.create_index(
        "ix_corp_webhook_deliveries_webhook_attempted",
        "corporate_webhook_deliveries",
        ["webhook_id", "attempted_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_webhook_deliveries_webhook_attempted",
        table_name="corporate_webhook_deliveries",
    )
    op.drop_index(
        "ix_corp_webhook_deliveries_attempted_at",
        table_name="corporate_webhook_deliveries",
    )
    op.drop_index(
        "ix_corp_webhook_deliveries_webhook_id",
        table_name="corporate_webhook_deliveries",
    )
    op.drop_table("corporate_webhook_deliveries")

    op.drop_index(
        "ix_corporate_webhooks_is_active",
        table_name="corporate_webhooks",
    )
    op.drop_index(
        "ix_corporate_webhooks_account_id",
        table_name="corporate_webhooks",
    )
    op.drop_table("corporate_webhooks")
