"""add surge waitlist entries table

Revision ID: f1g2h3i4j5k6
Revises: f1a3c7e92d05
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'f1g2h3i4j5k6'
down_revision: Union[str, Sequence[str], None] = 'f1a3c7e92d05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "surge_waitlist_entries",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("rider_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),

        # Pickup location
        sa.Column("origin_lat", sa.Float(), nullable=False),
        sa.Column("origin_lon", sa.Float(), nullable=False),

        # Optional destination
        sa.Column("destination_lat", sa.Float(), nullable=True),
        sa.Column("destination_lon", sa.Float(), nullable=True),

        # Threshold and preferences
        sa.Column("max_multiplier", sa.Float(), nullable=False, server_default=sa.text("1.5")),
        sa.Column("vehicle_preference", sa.String(50), nullable=True),

        # Lifecycle
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'")),

        # Notification channels
        sa.Column("notify_via_push", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notify_via_sms", sa.Boolean(), nullable=False, server_default=sa.text("false")),

        # Timestamps
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "idx_surge_waitlist_entries_rider_id",
        "surge_waitlist_entries",
        ["rider_id"],
    )
    op.create_index(
        "idx_surge_waitlist_entries_status",
        "surge_waitlist_entries",
        ["status"],
    )
    op.create_index(
        "idx_surge_waitlist_entries_expires_at",
        "surge_waitlist_entries",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_surge_waitlist_entries_expires_at", table_name="surge_waitlist_entries")
    op.drop_index("idx_surge_waitlist_entries_status", table_name="surge_waitlist_entries")
    op.drop_index("idx_surge_waitlist_entries_rider_id", table_name="surge_waitlist_entries")
    op.drop_table("surge_waitlist_entries")
