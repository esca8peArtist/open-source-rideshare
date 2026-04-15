"""Add driver_shifts table for shift / hours tracking.

Tables created:
  driver_shifts   — per-shift records for driver clock-in / clock-out

Indexes added on driver_id and status for efficient active-shift lookups
and admin filtering.

Revision ID: z1a2b3c4d5e6
Revises: y1z2a3b4c5d6
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "z1a2b3c4d5e6"
down_revision = "y1z2a3b4c5d6"
branch_labels = None
depends_on = None

SHIFT_STATUS_ENUM = "shiftstatusenum"


def upgrade() -> None:
    # Create the ShiftStatus enum type
    shift_status_enum = sa.Enum(
        "active", "completed", "auto_ended",
        name=SHIFT_STATUS_ENUM,
    )
    shift_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "driver_shifts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "driver_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "completed", "auto_ended", name=SHIFT_STATUS_ENUM),
            nullable=False,
            server_default="active",
        ),
        sa.Column("rides_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_minutes", sa.Float(), nullable=True),
        sa.Column("admin_note", sa.String(500), nullable=True),
        sa.Column(
            "ended_by_admin_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index("ix_driver_shifts_driver_id", "driver_shifts", ["driver_id"])
    op.create_index("ix_driver_shifts_status", "driver_shifts", ["status"])
    op.create_index(
        "ix_driver_shifts_driver_status",
        "driver_shifts",
        ["driver_id", "status"],
    )
    op.create_index("ix_driver_shifts_started_at", "driver_shifts", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_driver_shifts_started_at", table_name="driver_shifts")
    op.drop_index("ix_driver_shifts_driver_status", table_name="driver_shifts")
    op.drop_index("ix_driver_shifts_status", table_name="driver_shifts")
    op.drop_index("ix_driver_shifts_driver_id", table_name="driver_shifts")
    op.drop_table("driver_shifts")

    shift_status_enum = sa.Enum(name=SHIFT_STATUS_ENUM)
    shift_status_enum.drop(op.get_bind(), checkfirst=True)
