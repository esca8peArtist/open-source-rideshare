"""Add corporate_generated_expense_reports table.

Stores pre-generated aggregated expense reports for corporate accounts.
Each row captures the totals (by member and by category) for a given
date range so that reports can be retrieved and exported without
re-querying the rides table.

Table created:
  corporate_generated_expense_reports

Revision ID: a1b2c3d4e5f6
Revises:     z9a0b1c2d3e4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "z9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corporate_generated_expense_reports",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "corp_id",
            sa.Integer,
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("total_rides", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "total_amount_usd",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "generated_by_id",
            sa.Integer,
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "by_member",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "by_category",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )

    op.create_index(
        "ix_corp_ger_corp_id",
        "corporate_generated_expense_reports",
        ["corp_id"],
    )
    op.create_index(
        "ix_corp_ger_generated_by_id",
        "corporate_generated_expense_reports",
        ["generated_by_id"],
    )
    op.create_index(
        "ix_corp_ger_generated_at",
        "corporate_generated_expense_reports",
        ["generated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_corp_ger_generated_at", "corporate_generated_expense_reports")
    op.drop_index("ix_corp_ger_generated_by_id", "corporate_generated_expense_reports")
    op.drop_index("ix_corp_ger_corp_id", "corporate_generated_expense_reports")
    op.drop_table("corporate_generated_expense_reports")
