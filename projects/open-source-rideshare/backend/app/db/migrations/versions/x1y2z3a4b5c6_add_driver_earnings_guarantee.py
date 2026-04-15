"""Add driver earnings guarantee tables.

Tables created:
  earnings_guarantee_policies  — platform policy: per-ride floor + eligibility threshold
  weekly_guarantee_records     — per-driver per-week shortfall calculation and payout records

Revision ID: x1y2z3a4b5c6
Revises: w1x2y3z4a5b6
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "x1y2z3a4b5c6"
down_revision = "w1x2y3z4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # earnings_guarantee_policies
    # ------------------------------------------------------------------
    op.create_table(
        "earnings_guarantee_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("minimum_per_ride_usd", sa.Numeric(8, 2), nullable=False),
        sa.Column("minimum_rides_to_qualify", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_earnings_guarantee_policies_is_active",
        "earnings_guarantee_policies",
        ["is_active"],
    )

    # ------------------------------------------------------------------
    # weekly_guarantee_records
    # ------------------------------------------------------------------
    guarantee_status_enum = sa.Enum(
        "ineligible", "waived", "pending", "paid",
        name="guaranteestatus",
    )
    guarantee_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "weekly_guarantee_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("driver_profile_id", sa.Integer(), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("rides_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gross_earnings_usd", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("guaranteed_earnings_usd", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("shortfall_usd", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column(
            "status",
            guarantee_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["driver_profile_id"], ["driver_profiles.id"]),
        sa.ForeignKeyConstraint(["policy_id"], ["earnings_guarantee_policies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("driver_id", "week_start", name="uq_weekly_guarantee_driver_week"),
    )
    op.create_index(
        "ix_weekly_guarantee_records_driver_id",
        "weekly_guarantee_records",
        ["driver_id"],
    )
    op.create_index(
        "ix_weekly_guarantee_records_week_start",
        "weekly_guarantee_records",
        ["week_start"],
    )
    op.create_index(
        "ix_weekly_guarantee_records_policy_id",
        "weekly_guarantee_records",
        ["policy_id"],
    )
    op.create_index(
        "ix_weekly_guarantee_records_status",
        "weekly_guarantee_records",
        ["status"],
    )
    op.create_index(
        "ix_weekly_guarantee_records_driver_profile_id",
        "weekly_guarantee_records",
        ["driver_profile_id"],
    )


def downgrade() -> None:
    op.drop_table("weekly_guarantee_records")
    sa.Enum(name="guaranteestatus").drop(op.get_bind(), checkfirst=True)
    op.drop_table("earnings_guarantee_policies")
