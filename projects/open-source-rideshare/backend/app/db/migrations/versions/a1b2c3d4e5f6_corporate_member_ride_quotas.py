"""Add corporate_member_ride_quotas table.

Corporate account admins set per-member ride count limits scoped to a time
period (daily, weekly, monthly).  This table stores one row per
(account, member, period) combination, tracking the maximum number of
corporate rides an employee may take in a given period.

Tables created:
  corporate_member_ride_quotas — quota row with unique (account, member, period).

Revision ID: a1b2c3d4e5f6
Revises:     z5a6b7c8d9e0
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "a1b2c3d4e5f6"
down_revision = "z5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. corporate_member_ride_quotas table
    # ------------------------------------------------------------------
    op.create_table(
        "corporate_member_ride_quotas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("period", sa.String(10), nullable=False),
        sa.Column("max_rides", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------
    # 2. Unique constraint + indexes
    # ------------------------------------------------------------------
    op.create_unique_constraint(
        "uq_corp_quota_account_member_period",
        "corporate_member_ride_quotas",
        ["account_id", "member_id", "period"],
    )
    op.create_index(
        "ix_corp_quota_account_id",
        "corporate_member_ride_quotas",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_quota_member_id",
        "corporate_member_ride_quotas",
        ["member_id"],
    )
    op.create_index(
        "ix_corp_quota_account_period",
        "corporate_member_ride_quotas",
        ["account_id", "period"],
    )


def downgrade() -> None:
    op.drop_index("ix_corp_quota_account_period", table_name="corporate_member_ride_quotas")
    op.drop_index("ix_corp_quota_member_id", table_name="corporate_member_ride_quotas")
    op.drop_index("ix_corp_quota_account_id", table_name="corporate_member_ride_quotas")
    op.drop_constraint(
        "uq_corp_quota_account_member_period",
        "corporate_member_ride_quotas",
        type_="unique",
    )
    op.drop_table("corporate_member_ride_quotas")
