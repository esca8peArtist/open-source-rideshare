"""add cooperative member dividend / profit-sharing tables

Revision ID: w1x2y3z4a5b6
Revises: v1w2x3y4z5a6
Create Date: 2026-04-15

Creates two tables:
  cooperative_dividends      — quarterly profit-sharing distributions
  driver_dividend_shares     — per-driver allocations within each distribution
"""

from alembic import op
import sqlalchemy as sa

revision = "w1x2y3z4a5b6"
down_revision = "v1w2x3y4z5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cooperative_dividends",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("quarter", sa.Integer, nullable=False),
        sa.Column(
            "total_platform_surplus_usd",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_qualifying_rides",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "per_ride_payout_usd",
            sa.Numeric(10, 4),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "distributed",
                "cancelled",
                name="dividendstatus",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "approved_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("cancellation_reason", sa.Text, nullable=True),
        sa.Column(
            "declared_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("distributed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("year", "quarter", name="uq_cooperative_dividend_period"),
    )
    op.create_index(
        "ix_cooperative_dividends_status",
        "cooperative_dividends",
        ["status"],
    )
    op.create_index(
        "ix_cooperative_dividends_year_quarter",
        "cooperative_dividends",
        ["year", "quarter"],
    )

    op.create_table(
        "driver_dividend_shares",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "dividend_id",
            sa.Integer,
            sa.ForeignKey("cooperative_dividends.id"),
            nullable=False,
        ),
        sa.Column(
            "driver_id",
            sa.Integer,
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "driver_profile_id",
            sa.Integer,
            sa.ForeignKey("driver_profiles.id"),
            nullable=False,
        ),
        sa.Column(
            "qualifying_rides",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "share_pct",
            sa.Numeric(7, 4),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "amount_usd",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "paid",
                "cancelled",
                name="dividendsharestatus",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_driver_dividend_shares_dividend_id",
        "driver_dividend_shares",
        ["dividend_id"],
    )
    op.create_index(
        "ix_driver_dividend_shares_driver_id",
        "driver_dividend_shares",
        ["driver_id"],
    )
    op.create_index(
        "ix_driver_dividend_shares_driver_profile_id",
        "driver_dividend_shares",
        ["driver_profile_id"],
    )
    op.create_index(
        "ix_driver_dividend_shares_status",
        "driver_dividend_shares",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_driver_dividend_shares_status", table_name="driver_dividend_shares")
    op.drop_index("ix_driver_dividend_shares_driver_profile_id", table_name="driver_dividend_shares")
    op.drop_index("ix_driver_dividend_shares_driver_id", table_name="driver_dividend_shares")
    op.drop_index("ix_driver_dividend_shares_dividend_id", table_name="driver_dividend_shares")
    op.drop_table("driver_dividend_shares")

    op.drop_index("ix_cooperative_dividends_year_quarter", table_name="cooperative_dividends")
    op.drop_index("ix_cooperative_dividends_status", table_name="cooperative_dividends")
    op.drop_table("cooperative_dividends")

    op.execute("DROP TYPE IF EXISTS dividendsharestatus")
    op.execute("DROP TYPE IF EXISTS dividendstatus")
