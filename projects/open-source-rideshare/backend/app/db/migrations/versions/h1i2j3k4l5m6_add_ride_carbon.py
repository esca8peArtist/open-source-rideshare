"""Add ride carbon footprint tables.

Green Rides feature: per-ride CO2 tracking and voluntary offset payments.

Tables created:
  ride_carbon_records — one row per ride: emission class, distance, CO2 grams,
                        optional carbon offset payment

Enum types created:
  vehicleemissionclass — petrol / diesel / hybrid / electric / unknown

Revision ID: h1i2j3k4l5m6
Revises: g1h2i3j4k5l6
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic
revision: str = "h1i2j3k4l5m6"
down_revision: str = "g1h2i3j4k5l6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Enum type -----------------------------------------------------------
    vehicleemissionclass = sa.Enum(
        "petrol",
        "diesel",
        "hybrid",
        "electric",
        "unknown",
        name="vehicleemissionclass",
    )
    vehicleemissionclass.create(op.get_bind(), checkfirst=True)

    # --- ride_carbon_records table -------------------------------------------
    op.create_table(
        "ride_carbon_records",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "ride_id",
            sa.Integer(),
            sa.ForeignKey("rides.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "emission_class",
            sa.Enum(
                "petrol",
                "diesel",
                "hybrid",
                "electric",
                "unknown",
                name="vehicleemissionclass",
                create_type=False,
            ),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("distance_km", sa.Float(), nullable=False),
        sa.Column("co2_grams", sa.Integer(), nullable=False),
        sa.Column("offset_cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "offset_paid",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "offset_amount_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("offset_paid_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Unique constraint: one carbon record per ride
    op.create_unique_constraint(
        "uq_ride_carbon_ride_id", "ride_carbon_records", ["ride_id"]
    )

    # Indexes
    op.create_index(
        "ix_ride_carbon_records_ride_id",
        "ride_carbon_records",
        ["ride_id"],
        unique=True,
    )
    op.create_index(
        "ix_ride_carbon_records_emission_class",
        "ride_carbon_records",
        ["emission_class"],
    )
    op.create_index(
        "ix_ride_carbon_records_offset_paid",
        "ride_carbon_records",
        ["offset_paid"],
    )


def downgrade() -> None:
    op.drop_index("ix_ride_carbon_records_offset_paid", table_name="ride_carbon_records")
    op.drop_index("ix_ride_carbon_records_emission_class", table_name="ride_carbon_records")
    op.drop_index("ix_ride_carbon_records_ride_id", table_name="ride_carbon_records")
    op.drop_constraint("uq_ride_carbon_ride_id", "ride_carbon_records", type_="unique")
    op.drop_table("ride_carbon_records")
    sa.Enum(name="vehicleemissionclass").drop(op.get_bind(), checkfirst=True)
