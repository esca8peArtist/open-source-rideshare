"""Add corporate_department_ride_policies table.

Per-department ride policy overrides — the middle tier in the three-layer
corporate ride policy hierarchy (account → department → member).

Tables created:
  corporate_department_ride_policies

Revision ID: i0j1k2l3m4n5
Revises:     h9i0j1k2l3m4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "i0j1k2l3m4n5"
down_revision = "h9i0j1k2l3m4"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "corporate_department_ride_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.Column("set_by_id", sa.Integer(), nullable=True),
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
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
            ["department_id"],
            ["corporate_departments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["set_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "department_id",
            name="uq_corp_dept_ride_policy_department",
        ),
    )

    op.create_index(
        "ix_corp_dept_ride_policy_account_id",
        "corporate_department_ride_policies",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_dept_ride_policy_department_id",
        "corporate_department_ride_policies",
        ["department_id"],
    )
    op.create_index(
        "ix_corp_dept_ride_policy_account_active",
        "corporate_department_ride_policies",
        ["account_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_dept_ride_policy_account_active",
        table_name="corporate_department_ride_policies",
    )
    op.drop_index(
        "ix_corp_dept_ride_policy_department_id",
        table_name="corporate_department_ride_policies",
    )
    op.drop_index(
        "ix_corp_dept_ride_policy_account_id",
        table_name="corporate_department_ride_policies",
    )
    op.drop_table("corporate_department_ride_policies")
