"""Add driver_locations table for real-time driver GPS tracking.

One row per driver (unique on driver_id) — upserted on each location push.
Riders track their assigned driver during active rides; admins monitor all
active drivers on the platform.

Tables created:
  driver_locations  — current GPS position per driver

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = "b5c6d7e8f9a0"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "driver_locations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("ride_id", sa.Integer(), nullable=True),
        sa.Column("latitude", sa.Float(precision=8), nullable=False),
        sa.Column("longitude", sa.Float(precision=8), nullable=False),
        sa.Column("accuracy_meters", sa.Float(), nullable=True),
        sa.Column("heading", sa.Float(), nullable=True),
        sa.Column("speed_kmh", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ride_id"],
            ["rides.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("driver_id", name="uq_driver_locations_driver_id"),
    )
    op.create_index(
        "ix_driver_locations_driver_id", "driver_locations", ["driver_id"]
    )
    op.create_index(
        "ix_driver_locations_ride_id", "driver_locations", ["ride_id"]
    )
    op.create_index(
        "ix_driver_locations_updated_at", "driver_locations", ["updated_at"]
    )
    op.create_index(
        "ix_driver_locations_is_active", "driver_locations", ["is_active"]
    )


def downgrade() -> None:
    op.drop_index("ix_driver_locations_is_active", table_name="driver_locations")
    op.drop_index("ix_driver_locations_updated_at", table_name="driver_locations")
    op.drop_index("ix_driver_locations_ride_id", table_name="driver_locations")
    op.drop_index("ix_driver_locations_driver_id", table_name="driver_locations")
    op.drop_table("driver_locations")
