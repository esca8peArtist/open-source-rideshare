"""add driver payouts

Revision ID: r1s2t3u4v5w6
Revises: q1r2s3t4u5v6
Create Date: 2026-04-15

Creates the driver_disbursements table which tracks payout records
for individual drivers covering a specific earning period.

Monetary fields are stored as NUMERIC(10, 2) for exact decimal precision.
"""

from alembic import op
import sqlalchemy as sa

revision = "r1s2t3u4v5w6"
down_revision = "q1r2s3t4u5v6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    payout_status_enum = sa.Enum(
        "pending", "processing", "completed", "failed",
        name="driverpayoutstatus",
    )
    payout_method_enum = sa.Enum(
        "stripe_transfer", "bank_transfer", "manual",
        name="driverpayoutmethod",
    )

    op.create_table(
        "driver_disbursements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("amount_usd", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("platform_fee_usd", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("net_payout_usd", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("status", payout_status_enum, nullable=False, server_default="pending"),
        sa.Column("method", payout_method_enum, nullable=False, server_default="stripe_transfer"),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_reason", sa.Text(), nullable=True),
        sa.Column("stripe_transfer_id", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_driver_disbursements_driver_id", "driver_disbursements", ["driver_id"])
    op.create_index("ix_driver_disbursements_status", "driver_disbursements", ["status"])
    op.create_index("ix_driver_disbursements_period_start", "driver_disbursements", ["period_start"])


def downgrade() -> None:
    op.drop_table("driver_disbursements")
    op.execute("DROP TYPE IF EXISTS driverpayoutstatus")
    op.execute("DROP TYPE IF EXISTS driverpayoutmethod")
