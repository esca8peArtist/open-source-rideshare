"""add driver destination filter table

Revision ID: g1h2i3j4k5l6
Revises: f1g2h3i4j5k6
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'g1h2i3j4k5l6'
down_revision: Union[str, Sequence[str], None] = 'f1g2h3i4j5k6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "driver_destination_filters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "driver_id",
            sa.Integer(),
            sa.ForeignKey("driver_profiles.id"),
            nullable=False,
            unique=True,
        ),

        # Target destination coordinates
        sa.Column("destination_lat", sa.Float(), nullable=False),
        sa.Column("destination_lon", sa.Float(), nullable=False),

        # Acceptable dropoff radius (km)
        sa.Column(
            "radius_km",
            sa.Float(),
            nullable=False,
            server_default=sa.text("5.0"),
        ),

        # Lifecycle
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),

        # Optional auto-expiry
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),

        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "idx_driver_destination_filters_driver_id",
        "driver_destination_filters",
        ["driver_id"],
    )
    op.create_index(
        "idx_driver_destination_filters_is_active",
        "driver_destination_filters",
        ["is_active"],
    )
    op.create_unique_constraint(
        "uq_driver_destination_filters_driver_id",
        "driver_destination_filters",
        ["driver_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_driver_destination_filters_driver_id",
        "driver_destination_filters",
        type_="unique",
    )
    op.drop_index("idx_driver_destination_filters_is_active", table_name="driver_destination_filters")
    op.drop_index("idx_driver_destination_filters_driver_id", table_name="driver_destination_filters")
    op.drop_table("driver_destination_filters")
