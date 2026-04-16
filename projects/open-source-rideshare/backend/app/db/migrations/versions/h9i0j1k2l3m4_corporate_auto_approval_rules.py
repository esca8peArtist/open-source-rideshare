"""Add corporate_auto_approval_rules table.

Corporate account admins define rules that, when all specified conditions
match a ride request, automatically approve that ride without a manual step
in the approval chain.

Tables created:
  corporate_auto_approval_rules

Revision ID: h9i0j1k2l3m4
Revises:     g8h9i0j1k2l3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "h9i0j1k2l3m4"
down_revision = "g8h9i0j1k2l3"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "corporate_auto_approval_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("max_cost_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "trip_purpose_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "cost_center_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "employee_group_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "allowed_days_of_week",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("start_hour", sa.Integer(), nullable=True),
        sa.Column("end_hour", sa.Integer(), nullable=True),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
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
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corp_auto_approval_account_id",
        "corporate_auto_approval_rules",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_auto_approval_is_active",
        "corporate_auto_approval_rules",
        ["is_active"],
    )
    op.create_index(
        "ix_corp_auto_approval_account_active_priority",
        "corporate_auto_approval_rules",
        ["account_id", "is_active", "priority"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_auto_approval_account_active_priority",
        table_name="corporate_auto_approval_rules",
    )
    op.drop_index(
        "ix_corp_auto_approval_is_active",
        table_name="corporate_auto_approval_rules",
    )
    op.drop_index(
        "ix_corp_auto_approval_account_id",
        table_name="corporate_auto_approval_rules",
    )
    op.drop_table("corporate_auto_approval_rules")
