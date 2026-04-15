"""Add corporate_departments and corporate_department_members tables.

Companies can organise their employees into named departments with optional
monthly budgets and cost center associations.

Tables created:
  corporate_departments        — named organisational units within an account
  corporate_department_members — junction: employee ↔ department + head flag

Revision ID: b2c3d4e5f6g7
Revises:     a2b3c4d5e6f7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

revision = "b2c3d4e5f6g7"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "corporate_departments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "cost_center_id",
            sa.Integer(),
            sa.ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("monthly_budget", sa.Numeric(12, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("account_id", "code", name="uq_corp_dept_account_code"),
    )
    op.create_index(
        "ix_corporate_departments_account_id",
        "corporate_departments",
        ["account_id"],
    )
    op.create_index(
        "ix_corporate_departments_cost_center_id",
        "corporate_departments",
        ["cost_center_id"],
    )

    op.create_table(
        "corporate_department_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "department_id",
            sa.Integer(),
            sa.ForeignKey("corporate_departments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "is_department_head",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "added_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("department_id", "user_id", name="uq_corp_dept_member"),
    )
    op.create_index(
        "ix_corporate_department_members_department_id",
        "corporate_department_members",
        ["department_id"],
    )
    op.create_index(
        "ix_corporate_department_members_user_id",
        "corporate_department_members",
        ["user_id"],
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    op.drop_index(
        "ix_corporate_department_members_user_id",
        table_name="corporate_department_members",
    )
    op.drop_index(
        "ix_corporate_department_members_department_id",
        table_name="corporate_department_members",
    )
    op.drop_table("corporate_department_members")

    op.drop_index(
        "ix_corporate_departments_cost_center_id",
        table_name="corporate_departments",
    )
    op.drop_index(
        "ix_corporate_departments_account_id",
        table_name="corporate_departments",
    )
    op.drop_table("corporate_departments")
