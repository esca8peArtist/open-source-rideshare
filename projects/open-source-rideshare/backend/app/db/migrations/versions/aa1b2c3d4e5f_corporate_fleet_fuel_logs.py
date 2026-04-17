"""Add corporate_fleet_fuel_logs table.

Fleet managers and drivers log fuel fill-ups and EV charging events for
company vehicles.  Over time the logs build up a complete fuel-cost and
mileage history that powers efficiency analytics.

Enums created:
  fleetfueltype — gasoline / diesel / electric / hybrid / hydrogen / other

Table created:
  corporate_fleet_fuel_logs — one record per fuel fill-up or energy charge event.

Revision ID: aa1b2c3d4e5f
Revises:     z9a0b1c2d3e4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "aa1b2c3d4e5f"
down_revision = "z9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------- fleetfueltype enum
    op.execute(
        "CREATE TYPE fleetfueltype AS ENUM "
        "('gasoline', 'diesel', 'electric', 'hybrid', 'hydrogen', 'other')"
    )

    # ----------------------------- corporate_fleet_fuel_logs
    op.create_table(
        "corporate_fleet_fuel_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "fleet_vehicle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corporate_fleet_vehicles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
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
        sa.Column("fill_date", sa.Date, nullable=False),
        sa.Column("odometer_miles", sa.Integer, nullable=True),
        sa.Column("gallons_added", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("kwh_added", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("cost_per_unit_usd", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("total_cost_usd", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("station_name", sa.String(200), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "logged_by_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
    )

    # Indexes
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
    op.drop_index("ix_fleet_fuel_log_fuel_type", "corporate_fleet_fuel_logs")
    op.drop_index("ix_fleet_fuel_log_fill_date", "corporate_fleet_fuel_logs")
    op.drop_index("ix_fleet_fuel_log_vehicle_id", "corporate_fleet_fuel_logs")
    op.drop_index("ix_fleet_fuel_log_account_id", "corporate_fleet_fuel_logs")
    op.drop_table("corporate_fleet_fuel_logs")
    op.execute("DROP TYPE IF EXISTS fleetfueltype")
