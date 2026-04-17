"""add rider_cancellation_stats table

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa

revision = "k5l6m7n8o9p0"
down_revision = "j4k5l6m7n8o9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rider_cancellation_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rider_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("total_rides_requested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cancellations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancellations_in_grace_period", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancellations_with_fee", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancellation_rate", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("last_cancel_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_cancel_category",
            sa.Enum(
                "wrong_pickup", "wait_too_long", "found_other_ride", "plans_changed",
                "driver_not_acceptable", "price_too_high", "safety_concern", "other",
                "vehicle_issue", "rider_no_show", "unable_to_locate", "emergency", "driver_other",
                name="cancellationcategory",
            ),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rider_id", name="uq_rider_cancel_stats_rider"),
    )
    op.create_index("ix_rider_cancellation_stats_rider_id", "rider_cancellation_stats", ["rider_id"])


def downgrade():
    op.drop_index("ix_rider_cancellation_stats_rider_id", table_name="rider_cancellation_stats")
    op.drop_table("rider_cancellation_stats")
