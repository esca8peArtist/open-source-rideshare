"""Add corporate_cost_centers table and cost_center_id to rides.

Companies can create named cost centers (departments, projects, teams) and
tag corporate rides to them for per-department expense tracking.

Tables / columns created:
  corporate_cost_centers — one row per named cost center within an account
  rides.cost_center_id   — nullable FK to corporate_cost_centers

Revision ID: s2t3u4v5w6x7
Revises:     r2s3t4u5v6w7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "s2t3u4v5w6x7"
down_revision: str = "r2s3t4u5v6w7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create corporate_cost_centers table
    # ------------------------------------------------------------------
    op.create_table(
        "corporate_cost_centers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("description", sa.String(300), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("monthly_budget", sa.Numeric(12, 2), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "code", name="uq_corp_cost_center_account_code"
        ),
    )

    op.create_index(
        "ix_corp_cost_centers_account_id",
        "corporate_cost_centers",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_cost_centers_is_active",
        "corporate_cost_centers",
        ["is_active"],
    )

    # ------------------------------------------------------------------
    # 2. Add nullable cost_center_id FK to rides
    # ------------------------------------------------------------------
    op.add_column(
        "rides",
        sa.Column("cost_center_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_rides_cost_center_id",
        "rides",
        "corporate_cost_centers",
        ["cost_center_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_rides_cost_center_id",
        "rides",
        ["cost_center_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_rides_cost_center_id", table_name="rides")
    op.drop_constraint("fk_rides_cost_center_id", "rides", type_="foreignkey")
    op.drop_column("rides", "cost_center_id")

    op.drop_index("ix_corp_cost_centers_is_active", table_name="corporate_cost_centers")
    op.drop_index("ix_corp_cost_centers_account_id", table_name="corporate_cost_centers")
    op.drop_table("corporate_cost_centers")
