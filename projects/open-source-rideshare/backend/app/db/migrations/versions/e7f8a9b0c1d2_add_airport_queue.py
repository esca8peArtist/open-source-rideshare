"""Add airport queue management tables.

Tables created:
  airport_zones         — admin-configured airport staging / pickup zones
  airport_queue_entries — FIFO queue of drivers waiting per zone

Enum types created:
  queueentrystatus  — waiting / dispatched / left / expired

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------------
    queueentrystatus_enum = sa.Enum(
        "waiting", "dispatched", "left", "expired",
        name="queueentrystatus",
    )
    queueentrystatus_enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # airport_zones
    # ------------------------------------------------------------------
    op.create_table(
        "airport_zones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("airport_code", sa.String(10), nullable=False),
        sa.Column("terminal", sa.String(60), nullable=True),
        sa.Column("address", sa.String(255), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("max_queue_size", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("ttl_minutes", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_airport_zones_id", "airport_zones", ["id"])
    op.create_index("ix_airport_zones_airport_code", "airport_zones", ["airport_code"])
    op.create_index("ix_airport_zones_is_active", "airport_zones", ["is_active"])

    # ------------------------------------------------------------------
    # airport_queue_entries
    # ------------------------------------------------------------------
    op.create_table(
        "airport_queue_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("zone_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            queueentrystatus_enum,
            nullable=False,
            server_default="waiting",
        ),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["zone_id"], ["airport_zones.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("zone_id", "driver_id", name="uq_airport_queue_zone_driver"),
    )
    op.create_index("ix_airport_queue_entries_id", "airport_queue_entries", ["id"])
    op.create_index(
        "ix_airport_queue_zone_status",
        "airport_queue_entries",
        ["zone_id", "status"],
    )
    op.create_index(
        "ix_airport_queue_driver_status",
        "airport_queue_entries",
        ["driver_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_airport_queue_driver_status", "airport_queue_entries")
    op.drop_index("ix_airport_queue_zone_status", "airport_queue_entries")
    op.drop_index("ix_airport_queue_entries_id", "airport_queue_entries")
    op.drop_table("airport_queue_entries")

    op.drop_index("ix_airport_zones_is_active", "airport_zones")
    op.drop_index("ix_airport_zones_airport_code", "airport_zones")
    op.drop_index("ix_airport_zones_id", "airport_zones")
    op.drop_table("airport_zones")

    sa.Enum(name="queueentrystatus").drop(op.get_bind(), checkfirst=True)
