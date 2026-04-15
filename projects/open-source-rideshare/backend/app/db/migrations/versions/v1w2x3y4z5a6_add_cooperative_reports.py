"""add cooperative reports

Revision ID: v1w2x3y4z5a6
Revises: u1v2w3x4y5z6
Create Date: 2026-04-15

Creates one table:
  cooperative_reports — quarterly transparency reports, one row per (year, quarter)
"""

from alembic import op
import sqlalchemy as sa

revision = "v1w2x3y4z5a6"
down_revision = "u1v2w3x4y5z6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cooperative_reports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("quarter", sa.Integer, nullable=False),
        sa.Column("total_rides", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_cancelled_rides", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_fare_collected_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("total_platform_fees_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("total_driver_earnings_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("total_tips_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("platform_fee_rate_pct", sa.Float, nullable=False, server_default="0"),
        sa.Column("driver_take_rate_pct", sa.Float, nullable=False, server_default="0"),
        sa.Column("active_drivers", sa.Integer, nullable=False, server_default="0"),
        sa.Column("active_riders", sa.Integer, nullable=False, server_default="0"),
        sa.Column("new_drivers", sa.Integer, nullable=False, server_default="0"),
        sa.Column("new_riders", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.UniqueConstraint("year", "quarter", name="uq_cooperative_report_period"),
    )
    op.create_index("ix_cooperative_reports_year_quarter", "cooperative_reports", ["year", "quarter"])


def downgrade() -> None:
    op.drop_index("ix_cooperative_reports_year_quarter", table_name="cooperative_reports")
    op.drop_table("cooperative_reports")
