"""Add corporate_ride_policies table.

Companies can define a ride policy that governs what kinds of rides employees
may charge to the corporate account: vehicle type restrictions, per-ride cost
caps, per-employee monthly limits, trip purpose requirements, and
business-hours-only restrictions.

No policy means all rides are permitted (safe default).

Table created:
  corporate_ride_policies — one row per account (unique on account_id)

Revision ID: q2r3s4t5u6v7
Revises:     p2q3r4s5t6u7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "q2r3s4t5u6v7"
down_revision: str = "p2q3r4s5t6u7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corporate_ride_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "allowed_vehicle_categories",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("max_per_ride_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("max_per_member_monthly_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "require_purpose",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "approved_purposes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "business_hours_only",
            sa.Boolean(),
            nullable=False,
            server_default="false",
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", name="uq_corp_ride_policy_account"),
    )
    op.create_index(
        "ix_corporate_ride_policies_account_id",
        "corporate_ride_policies",
        ["account_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corporate_ride_policies_account_id",
        table_name="corporate_ride_policies",
    )
    op.drop_table("corporate_ride_policies")
