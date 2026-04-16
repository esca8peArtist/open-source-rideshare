"""Add corporate_vehicle_maintenance_logs table.

Fleet managers track service history for company vehicles — oil changes,
inspections, tire rotations, brake services, and other maintenance events.
Each record supports scheduled (future) and completed (historical) entries
with optional next-due date/odometer alerts.

Tables created:
  corporate_vehicle_maintenance_logs — one record per maintenance event

Revision ID: d3e4f5g6h7i8
Revises:     c2d3e4f5g6h7
Create Date: 2026-04-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "d3e4f5g6h7i8"
down_revision = "c2d3e4f5g6h7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------- maintenancetype enum
    maintenancetype = postgresql.ENUM(
        "oil_change",
        "tire_rotation",
        "brake_service",
        "inspection",
        "battery",
        "fluid_check",
        "filter_change",
        "wiper_replacement",
        "other",
        name="maintenancetype",
    )
    maintenancetype.create(op.get_bind())

    # ---------------------------------------- corporate_vehicle_maintenance_logs
    op.create_table(
        "corporate_vehicle_maintenance_logs",
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
            "maintenance_type",
            sa.Enum(
                "oil_change",
                "tire_rotation",
                "brake_service",
                "inspection",
                "battery",
                "fluid_check",
                "filter_change",
                "wiper_replacement",
                "other",
                name="maintenancetype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "scheduled_date",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("odometer_miles", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("vendor_name", sa.String(200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "is_completed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "next_due_date",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("next_due_odometer", sa.Integer(), nullable=True),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "completed_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        "ix_veh_maint_log_account_id",
        "corporate_vehicle_maintenance_logs",
        ["account_id"],
    )
    op.create_index(
        "ix_veh_maint_log_vehicle_id",
        "corporate_vehicle_maintenance_logs",
        ["fleet_vehicle_id"],
    )
    op.create_index(
        "ix_veh_maint_log_scheduled_date",
        "corporate_vehicle_maintenance_logs",
        ["scheduled_date"],
    )
    op.create_index(
        "ix_veh_maint_log_next_due_date",
        "corporate_vehicle_maintenance_logs",
        ["next_due_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_veh_maint_log_next_due_date", "corporate_vehicle_maintenance_logs"
    )
    op.drop_index(
        "ix_veh_maint_log_scheduled_date", "corporate_vehicle_maintenance_logs"
    )
    op.drop_index(
        "ix_veh_maint_log_vehicle_id", "corporate_vehicle_maintenance_logs"
    )
    op.drop_index(
        "ix_veh_maint_log_account_id", "corporate_vehicle_maintenance_logs"
    )
    op.drop_table("corporate_vehicle_maintenance_logs")
    sa.Enum(name="maintenancetype").drop(op.get_bind())
