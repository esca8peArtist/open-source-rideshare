"""Corporate Fleet Maintenance Scheduling.

Fleet managers schedule preventive maintenance and log completed service
records for company vehicles.

Tables created:
  corporate_fleet_maintenance_records — one record per scheduled or completed maintenance event

Revision ID: u0v1w2x3y4z5
Revises:     t9u0v1w2x3y4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "u0v1w2x3y4z5"
down_revision: str = "t9u0v1w2x3y4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Maintenance type enum
    op.execute(
        "CREATE TYPE fleetmaintenancetype AS ENUM ("
        "'oil_change', 'tire_rotation', 'brake_inspection', 'air_filter', "
        "'transmission_service', 'battery_replacement', 'coolant_flush', "
        "'spark_plugs', 'wheel_alignment', 'state_inspection', 'recall_repair', 'other'"
        ")"
    )

    # Maintenance status enum
    op.execute(
        "CREATE TYPE fleetmaintenancestatus AS ENUM ("
        "'scheduled', 'in_progress', 'completed', 'cancelled', 'overdue'"
        ")"
    )

    # Maintenance records table
    op.create_table(
        "corporate_fleet_maintenance_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("fleet_vehicle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "maintenance_type",
            sa.Enum(
                "oil_change",
                "tire_rotation",
                "brake_inspection",
                "air_filter",
                "transmission_service",
                "battery_replacement",
                "coolant_flush",
                "spark_plugs",
                "wheel_alignment",
                "state_inspection",
                "recall_repair",
                "other",
                name="fleetmaintenancetype",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "scheduled",
                "in_progress",
                "completed",
                "cancelled",
                "overdue",
                name="fleetmaintenancestatus",
            ),
            nullable=False,
            server_default="scheduled",
        ),
        sa.Column("scheduled_date", sa.Date(), nullable=True),
        sa.Column("completed_date", sa.Date(), nullable=True),
        sa.Column("odometer_at_service", sa.Integer(), nullable=True),
        sa.Column("next_service_odometer", sa.Integer(), nullable=True),
        sa.Column("next_service_date", sa.Date(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("vendor_name", sa.String(200), nullable=True),
        sa.Column("technician_name", sa.String(200), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["fleet_vehicle_id"],
            ["corporate_fleet_vehicles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_fleet_maintenance_account_id",
        "corporate_fleet_maintenance_records",
        ["account_id"],
    )
    op.create_index(
        "ix_fleet_maintenance_vehicle_id",
        "corporate_fleet_maintenance_records",
        ["fleet_vehicle_id"],
    )
    op.create_index(
        "ix_fleet_maintenance_status",
        "corporate_fleet_maintenance_records",
        ["status"],
    )
    op.create_index(
        "ix_fleet_maintenance_type",
        "corporate_fleet_maintenance_records",
        ["maintenance_type"],
    )
    op.create_index(
        "ix_fleet_maintenance_scheduled_date",
        "corporate_fleet_maintenance_records",
        ["scheduled_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fleet_maintenance_scheduled_date",
        table_name="corporate_fleet_maintenance_records",
    )
    op.drop_index(
        "ix_fleet_maintenance_type",
        table_name="corporate_fleet_maintenance_records",
    )
    op.drop_index(
        "ix_fleet_maintenance_status",
        table_name="corporate_fleet_maintenance_records",
    )
    op.drop_index(
        "ix_fleet_maintenance_vehicle_id",
        table_name="corporate_fleet_maintenance_records",
    )
    op.drop_index(
        "ix_fleet_maintenance_account_id",
        table_name="corporate_fleet_maintenance_records",
    )
    op.drop_table("corporate_fleet_maintenance_records")

    op.execute("DROP TYPE fleetmaintenancestatus")
    op.execute("DROP TYPE fleetmaintenancetype")
