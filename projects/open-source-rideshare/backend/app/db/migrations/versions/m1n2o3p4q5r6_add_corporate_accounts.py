"""add corporate_accounts and corporate_memberships tables, add corporate_account_id to rides

Revision ID: m1n2o3p4q5r6
Revises: l1m2n3o4p5q6
Create Date: 2026-04-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'm1n2o3p4q5r6'
down_revision: Union[str, Sequence[str], None] = 'l1m2n3o4p5q6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- corporate_accounts -------------------------------------------------
    op.create_table(
        "corporate_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("billing_email", sa.String(200), nullable=False),
        sa.Column("monthly_limit", sa.Float(), nullable=True),
        sa.Column("per_ride_limit", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "current_month_spend", sa.Float(), nullable=False, server_default=sa.text("0.0")
        ),
        sa.Column("current_month", sa.String(7), nullable=False),
        sa.Column("total_spend", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- corporate_memberships -----------------------------------------------
    op.create_table(
        "corporate_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("monthly_limit", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "active",
                "suspended",
                "removed",
                name="corporatemembershipstatus",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "invited_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "account_id", "user_id", name="uq_corporate_membership_account_user"
        ),
    )

    # --- rides: add corporate_account_id column ------------------------------
    op.add_column(
        "rides",
        sa.Column(
            "corporate_account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts.id"),
            nullable=True,
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("rides", "corporate_account_id")
    op.drop_table("corporate_memberships")
    op.drop_table("corporate_accounts")
    op.execute("DROP TYPE IF EXISTS corporatemembershipstatus")
