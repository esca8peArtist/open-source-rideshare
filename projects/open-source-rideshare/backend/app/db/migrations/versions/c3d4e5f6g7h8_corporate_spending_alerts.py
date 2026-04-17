"""Add corporate_spending_alerts table.

Tracks when an account or member has crossed a monthly spending threshold
(75 %, 90 %, or 100 % of their limit).  A unique constraint prevents
duplicate alerts for the same threshold within the same calendar period.

Revision ID: c3d4e5f6g7h8
Revises:     b2c3d4e5f6a7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c3d4e5f6g7h8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corporate_spending_alerts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("corporate_accounts_v2.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "member_id",
            sa.Integer,
            sa.ForeignKey("corporate_account_members.id"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "alert_type",
            sa.Enum(
                "warning_75pct",
                "warning_90pct",
                "limit_reached",
                name="alerttype",
            ),
            nullable=False,
        ),
        sa.Column("threshold_pct", sa.Integer, nullable=False),
        sa.Column("current_spend_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("limit_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("period_year", sa.Integer, nullable=False),
        sa.Column("period_month", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "account_id",
            "member_id",
            "alert_type",
            "period_year",
            "period_month",
            name="uq_corp_spend_alert_period",
        ),
    )


def downgrade() -> None:
    op.drop_table("corporate_spending_alerts")
    op.execute("DROP TYPE IF EXISTS alerttype")
