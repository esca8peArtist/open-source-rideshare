"""Add corporate_admin_audit_logs table.

Enterprise accounts need an immutable record of all significant admin actions
for compliance (SOX, SOC2, internal audit).

Tables created:
  corporate_admin_audit_logs — append-only audit trail of admin events per account

Revision ID: e5f6g7h8i9j0
Revises:     d4e5f6g7h8i9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

revision = "e5f6g7h8i9j0"
down_revision = "d4e5f6g7h8i9"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "corporate_admin_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(200), nullable=False),
        sa.Column("details", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_corporate_admin_audit_logs_account_id",
        "corporate_admin_audit_logs",
        ["account_id"],
    )
    op.create_index(
        "ix_corporate_admin_audit_logs_actor_id",
        "corporate_admin_audit_logs",
        ["actor_id"],
    )
    op.create_index(
        "ix_corporate_admin_audit_logs_action",
        "corporate_admin_audit_logs",
        ["action"],
    )
    op.create_index(
        "ix_corporate_admin_audit_logs_resource_type",
        "corporate_admin_audit_logs",
        ["resource_type"],
    )
    op.create_index(
        "ix_corporate_admin_audit_logs_created_at",
        "corporate_admin_audit_logs",
        ["created_at"],
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    op.drop_index(
        "ix_corporate_admin_audit_logs_created_at",
        table_name="corporate_admin_audit_logs",
    )
    op.drop_index(
        "ix_corporate_admin_audit_logs_resource_type",
        table_name="corporate_admin_audit_logs",
    )
    op.drop_index(
        "ix_corporate_admin_audit_logs_action",
        table_name="corporate_admin_audit_logs",
    )
    op.drop_index(
        "ix_corporate_admin_audit_logs_actor_id",
        table_name="corporate_admin_audit_logs",
    )
    op.drop_index(
        "ix_corporate_admin_audit_logs_account_id",
        table_name="corporate_admin_audit_logs",
    )
    op.drop_table("corporate_admin_audit_logs")
