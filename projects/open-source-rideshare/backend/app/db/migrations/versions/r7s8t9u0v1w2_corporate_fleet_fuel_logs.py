"""Corporate Fleet Fuel & Mileage Tracking.

Fleet managers and drivers log fuel fill-ups and energy charges for company
vehicles.  Over time the logs build a complete fuel-cost and mileage history
that powers efficiency analytics (MPG, cost-per-mile).

Tables created:
  corporate_fleet_fuel_logs — one record per fuel fill-up or energy charge event.

Revision ID: r7s8t9u0v1w2
Revises:     q6r7s8t9u0v1
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "r7s8t9u0v1w2"
down_revision: str = "q6r7s8t9u0v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the FuelType enum.
    op.execute(
        """
        CREATE TYPE fleetfueltype AS ENUM (
            'gasoline', 'diesel', 'electric', 'hybrid', 'hydrogen', 'other'
        )
        """
    )

    op.create_table(
        "corporate_fleet_fuel_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "fleet_vehicle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "corporate_fleet_vehicles.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey(
                "corporate_accounts_v2.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "fuel_type",
            sa.Enum(
                "gasoline",
                "diesel",
                "electric",
                "hybrid",
                "hydrogen",
                "other",
                name="fleetfueltype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("fill_date", sa.Date(), nullable=False),
        sa.Column("odometer_miles", sa.Integer(), nullable=True),
        sa.Column("gallons_added", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("kwh_added", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column(
            "cost_per_unit_usd", sa.Numeric(precision=8, scale=4), nullable=True
        ),
        sa.Column(
            "total_cost_usd", sa.Numeric(precision=10, scale=2), nullable=True
        ),
        sa.Column("station_name", sa.String(200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "logged_by_id",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_fleet_fuel_log_account_id",
        "corporate_fleet_fuel_logs",
        ["account_id"],
    )
    op.create_index(
        "ix_fleet_fuel_log_vehicle_id",
        "corporate_fleet_fuel_logs",
        ["fleet_vehicle_id"],
    )
    op.create_index(
        "ix_fleet_fuel_log_fill_date",
        "corporate_fleet_fuel_logs",
        ["fill_date"],
    )
    op.create_index(
        "ix_fleet_fuel_log_fuel_type",
        "corporate_fleet_fuel_logs",
        ["fuel_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fleet_fuel_log_fuel_type",
        table_name="corporate_fleet_fuel_logs",
    )
    op.drop_index(
        "ix_fleet_fuel_log_fill_date",
        table_name="corporate_fleet_fuel_logs",
    )
    op.drop_index(
        "ix_fleet_fuel_log_vehicle_id",
        table_name="corporate_fleet_fuel_logs",
    )
    op.drop_index(
        "ix_fleet_fuel_log_account_id",
        table_name="corporate_fleet_fuel_logs",
    )
    op.drop_table("corporate_fleet_fuel_logs")
    op.execute("DROP TYPE IF EXISTS fleetfueltype")
