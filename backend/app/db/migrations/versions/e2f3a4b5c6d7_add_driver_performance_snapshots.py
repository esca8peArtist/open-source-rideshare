"""add driver_performance_snapshots and driver_performance_alerts tables

Revision ID: e2f3a4b5c6d7
Revises: f1a3c7e92d05
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "f1a3c7e92d05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "driver_performance_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        # Volume
        sa.Column("total_rides_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_rides_offered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_rides_accepted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "total_rides_cancelled_by_driver", sa.Integer(), nullable=False, server_default="0"
        ),
        # Rates
        sa.Column("acceptance_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("completion_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cancellation_rate", sa.Float(), nullable=False, server_default="0"),
        # Timing
        sa.Column(
            "average_pickup_time_minutes", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column("on_time_rate", sa.Float(), nullable=False, server_default="0"),
        # Quality
        sa.Column("average_rider_rating", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_rider_ratings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_complaints", sa.Integer(), nullable=False, server_default="0"),
        # Score
        sa.Column("performance_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("score_tier", sa.String(20), nullable=False, server_default="bronze"),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("driver_id", "period_start", name="uq_driver_period"),
    )
    op.create_index(
        "ix_driver_performance_driver_id", "driver_performance_snapshots", ["driver_id"]
    )
    op.create_index(
        "ix_driver_performance_period", "driver_performance_snapshots", ["period_start"]
    )

    op.create_table(
        "driver_performance_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "snapshot_id",
            sa.Integer(),
            sa.ForeignKey("driver_performance_snapshots.id"),
            nullable=False,
        ),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("threshold_value", sa.Float(), nullable=False),
        sa.Column("actual_value", sa.Float(), nullable=False),
        sa.Column("is_resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_driver_performance_alerts_driver_id", "driver_performance_alerts", ["driver_id"]
    )
    op.create_index(
        "ix_driver_performance_alerts_snapshot_id",
        "driver_performance_alerts",
        ["snapshot_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_driver_performance_alerts_snapshot_id", table_name="driver_performance_alerts")
    op.drop_index("ix_driver_performance_alerts_driver_id", table_name="driver_performance_alerts")
    op.drop_table("driver_performance_alerts")
    op.drop_index("ix_driver_performance_period", table_name="driver_performance_snapshots")
    op.drop_index("ix_driver_performance_driver_id", table_name="driver_performance_snapshots")
    op.drop_table("driver_performance_snapshots")
