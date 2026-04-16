"""Add corporate member policy overrides table.

Adds a table for per-member exceptions to account-level ride policies.
Admins can grant individual members relaxed or tighter rules than the
account default (e.g. executives allowed premium vehicles; contractors
capped at a lower per-ride cost).

Override fields are nullable: NULL means "inherit from account policy".

Table created:
  corporate_member_policy_overrides

Revision ID: e6f7a8b9c0d1
Revises:     d4e5f6a7b8c9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "e6f7a8b9c0d1"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "corporate_member_policy_overrides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("overridden_by_id", sa.Integer(), nullable=True),
        # Override fields — NULL = inherit from account policy
        sa.Column(
            "allowed_vehicle_categories",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("max_per_ride_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("require_purpose", sa.Boolean(), nullable=True),
        sa.Column(
            "approved_purposes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("business_hours_only", sa.Boolean(), nullable=True),
        sa.Column("custom_notes", sa.String(length=500), nullable=True),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
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
            ["member_id"],
            ["corporate_account_members.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["overridden_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "member_id",
            name="uq_corp_member_policy_override",
        ),
    )

    op.create_index(
        "ix_corp_member_policy_override_account_id",
        "corporate_member_policy_overrides",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_member_policy_override_member_id",
        "corporate_member_policy_overrides",
        ["member_id"],
    )
    op.create_index(
        "ix_corp_member_policy_override_account_active",
        "corporate_member_policy_overrides",
        ["account_id", "is_active"],
    )
    op.create_index(
        "ix_corp_member_policy_override_valid_until",
        "corporate_member_policy_overrides",
        ["valid_until"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_member_policy_override_valid_until",
        table_name="corporate_member_policy_overrides",
    )
    op.drop_index(
        "ix_corp_member_policy_override_account_active",
        table_name="corporate_member_policy_overrides",
    )
    op.drop_index(
        "ix_corp_member_policy_override_member_id",
        table_name="corporate_member_policy_overrides",
    )
    op.drop_index(
        "ix_corp_member_policy_override_account_id",
        table_name="corporate_member_policy_overrides",
    )
    op.drop_table("corporate_member_policy_overrides")
