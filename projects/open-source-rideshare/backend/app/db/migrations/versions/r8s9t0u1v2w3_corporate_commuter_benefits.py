"""Corporate commuter benefits.

Companies configure a monthly ride subsidy program giving employees a
per-employee monthly credit for qualifying commute rides.

Tables created:
  corporate_commuter_programs   — one program per corporate account.
  corporate_commuter_allotments — monthly per-employee allotment records.

Revision ID: r8s9t0u1v2w3
Revises:     q7r8s9t0u1v2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "r8s9t0u1v2w3"
down_revision: str = "q7r8s9t0u1v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # corporate_commuter_programs
    # ------------------------------------------------------------------
    op.create_table(
        "corporate_commuter_programs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("monthly_allowance_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "rollover_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("max_rollover_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "eligible_trip_purpose_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "eligible_group_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
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
        sa.UniqueConstraint(
            "account_id",
            name="uq_corp_commuter_program_account_id",
        ),
    )

    op.create_index(
        "ix_corp_commuter_program_account_id",
        "corporate_commuter_programs",
        ["account_id"],
    )

    # ------------------------------------------------------------------
    # corporate_commuter_allotments
    # ------------------------------------------------------------------
    op.create_table(
        "corporate_commuter_allotments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("program_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column("allotted_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "used_usd",
            sa.Numeric(10, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "rolled_over_usd",
            sa.Numeric(10, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["corporate_commuter_programs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["corporate_account_members.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "program_id",
            "member_id",
            "period_year",
            "period_month",
            name="uq_corp_commuter_allotment_program_member_period",
        ),
    )

    op.create_index(
        "ix_corp_commuter_allotment_program_id",
        "corporate_commuter_allotments",
        ["program_id"],
    )
    op.create_index(
        "ix_corp_commuter_allotment_member_id",
        "corporate_commuter_allotments",
        ["member_id"],
    )
    op.create_index(
        "ix_corp_commuter_allotment_period",
        "corporate_commuter_allotments",
        ["program_id", "period_year", "period_month"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_commuter_allotment_period",
        table_name="corporate_commuter_allotments",
    )
    op.drop_index(
        "ix_corp_commuter_allotment_member_id",
        table_name="corporate_commuter_allotments",
    )
    op.drop_index(
        "ix_corp_commuter_allotment_program_id",
        table_name="corporate_commuter_allotments",
    )
    op.drop_table("corporate_commuter_allotments")

    op.drop_index(
        "ix_corp_commuter_program_account_id",
        table_name="corporate_commuter_programs",
    )
    op.drop_table("corporate_commuter_programs")
