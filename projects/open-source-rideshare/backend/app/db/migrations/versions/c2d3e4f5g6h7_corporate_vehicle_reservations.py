"""Add corporate_vehicle_reservations table.

Employees can reserve company fleet vehicles for self-drive use during
specified time windows.

Tables created:
  corporate_vehicle_reservations — one record per reservation request

Revision ID: c2d3e4f5g6h7
Revises:     b1c2d3e4f5g6
Create Date: 2026-04-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c2d3e4f5g6h7"
down_revision = "b1c2d3e4f5g6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------- reservationstatus enum
    reservationstatus = postgresql.ENUM(
        "pending",
        "confirmed",
        "cancelled",
        "completed",
        "no_show",
        name="reservationstatus",
    )
    reservationstatus.create(op.get_bind())

    # ---------------------------------------- corporate_vehicle_reservations
    op.create_table(
        "corporate_vehicle_reservations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fleet_vehicle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corporate_fleet_vehicles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reserved_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "approved_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "start_time",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "end_time",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(200), nullable=True),
        sa.Column("pickup_location", sa.String(300), nullable=True),
        sa.Column("dropoff_location", sa.String(300), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "trip_purpose_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corporate_trip_purposes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "cost_center_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "confirmed",
                "cancelled",
                "completed",
                "no_show",
                name="reservationstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "cancelled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "cancelled_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cancellation_reason", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "ix_vehicle_reservations_account",
        "corporate_vehicle_reservations",
        ["account_id"],
    )
    op.create_index(
        "ix_vehicle_reservations_vehicle",
        "corporate_vehicle_reservations",
        ["fleet_vehicle_id"],
    )
    op.create_index(
        "ix_vehicle_reservations_member",
        "corporate_vehicle_reservations",
        ["reserved_by_id"],
    )
    op.create_index(
        "ix_vehicle_reservations_status",
        "corporate_vehicle_reservations",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_vehicle_reservations_status", "corporate_vehicle_reservations")
    op.drop_index("ix_vehicle_reservations_member", "corporate_vehicle_reservations")
    op.drop_index("ix_vehicle_reservations_vehicle", "corporate_vehicle_reservations")
    op.drop_index("ix_vehicle_reservations_account", "corporate_vehicle_reservations")
    op.drop_table("corporate_vehicle_reservations")
    sa.Enum(name="reservationstatus").drop(op.get_bind())
