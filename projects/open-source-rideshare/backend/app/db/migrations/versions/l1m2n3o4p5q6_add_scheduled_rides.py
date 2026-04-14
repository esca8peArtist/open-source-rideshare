"""add scheduled_rides table

Revision ID: l1m2n3o4p5q6
Revises: k1l2m3n4o5p6
Create Date: 2026-04-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'l1m2n3o4p5q6'
down_revision: Union[str, Sequence[str], None] = 'k1l2m3n4o5p6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scheduled_rides",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Participants
        sa.Column(
            "rider_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "driver_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
            index=True,
        ),
        # Route
        sa.Column("pickup_lat", sa.Float(), nullable=False),
        sa.Column("pickup_lon", sa.Float(), nullable=False),
        sa.Column("pickup_address", sa.String(500), nullable=False),
        sa.Column("dropoff_lat", sa.Float(), nullable=False),
        sa.Column("dropoff_lon", sa.Float(), nullable=False),
        sa.Column("dropoff_address", sa.String(500), nullable=False),
        # Schedule
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("estimated_fare", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        # Status
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "driver_assigned",
                "in_progress",
                "completed",
                "cancelled",
                name="scheduledridestatus",
            ),
            nullable=False,
            server_default="pending",
            index=True,
        ),
        # Cancellation metadata
        sa.Column(
            "cancelled_by",
            sa.Enum("rider", "driver", "admin", name="cancelledby"),
            nullable=True,
        ),
        sa.Column("cancellation_reason", sa.String(500), nullable=True),
        sa.Column("decline_count", sa.Integer(), nullable=False, server_default="0"),
        # Link to the dispatched ride
        sa.Column(
            "ride_id",
            sa.Integer(),
            sa.ForeignKey("rides.id"),
            nullable=True,
            index=True,
        ),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("scheduled_rides")
    op.execute("DROP TYPE IF EXISTS scheduledridestatus")
    op.execute("DROP TYPE IF EXISTS cancelledby")
