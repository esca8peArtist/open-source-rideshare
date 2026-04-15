"""add vehicle maintenance logs

Revision ID: t1u2v3w4x5y6
Revises: s1t2u3v4w5x6
Create Date: 2026-04-15

Creates one table:
  vehicle_maintenance_logs  — maintenance history per vehicle, with
                              next-service scheduling for upcoming alerts
"""

from alembic import op
import sqlalchemy as sa

revision = "t1u2v3w4x5y6"
down_revision = "s1t2u3v4w5x6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    maintenance_type_enum = sa.Enum(
        "oil_change",
        "tire_rotation",
        "tire_replacement",
        "brake_inspection",
        "brake_replacement",
        "air_filter",
        "cabin_filter",
        "battery_replacement",
        "coolant_flush",
        "transmission_service",
        "spark_plugs",
        "belt_replacement",
        "wiper_blades",
        "annual_inspection",
        "other",
        name="maintenancetype",
    )

    op.create_table(
        "vehicle_maintenance_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("driver_profile_id", sa.Integer(), nullable=False),
        sa.Column("maintenance_type", maintenance_type_enum, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("service_provider", sa.String(200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("date_serviced", sa.Date(), nullable=False),
        sa.Column("mileage_at_service", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(8, 2), nullable=True),
        sa.Column("next_service_date", sa.Date(), nullable=True),
        sa.Column("next_service_mileage", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["driver_profile_id"], ["driver_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vehicle_maintenance_logs_vehicle_id",
        "vehicle_maintenance_logs",
        ["vehicle_id"],
    )
    op.create_index(
        "ix_vehicle_maintenance_logs_driver_profile_id",
        "vehicle_maintenance_logs",
        ["driver_profile_id"],
    )
    op.create_index(
        "ix_vehicle_maintenance_logs_next_service_date",
        "vehicle_maintenance_logs",
        ["next_service_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vehicle_maintenance_logs_next_service_date",
        table_name="vehicle_maintenance_logs",
    )
    op.drop_index(
        "ix_vehicle_maintenance_logs_driver_profile_id",
        table_name="vehicle_maintenance_logs",
    )
    op.drop_index(
        "ix_vehicle_maintenance_logs_vehicle_id",
        table_name="vehicle_maintenance_logs",
    )
    op.drop_table("vehicle_maintenance_logs")
    op.execute("DROP TYPE IF EXISTS maintenancetype")
