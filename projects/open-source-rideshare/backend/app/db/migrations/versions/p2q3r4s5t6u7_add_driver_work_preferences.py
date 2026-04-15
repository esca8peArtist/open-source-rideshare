"""Add driver_work_preferences table.

Drivers can specify what kinds of rides they accept and prefer: pool rides,
pet passengers, extra luggage, trip distance ranges, and long-distance
preference.

Cooperative differentiator: drivers have real agency over their workload.
Uber/Lyft's algorithmic dispatch ignores driver preferences — this platform
respects them.

Table created:
  driver_work_preferences — one row per driver (unique on driver_id)

Revision ID: p2q3r4s5t6u7
Revises:     o2p3q4r5s6t7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "p2q3r4s5t6u7"
down_revision: str = "o2p3q4r5s6t7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "driver_work_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column(
            "accept_pool_rides",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "accept_pet_riders",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "accept_extra_luggage",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column("min_trip_distance_km", sa.Float(), nullable=True),
        sa.Column("max_trip_distance_km", sa.Float(), nullable=True),
        sa.Column(
            "prefer_long_distance",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "prefer_language_matched",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("notes", sa.String(200), nullable=True),
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
            ["driver_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "driver_id", name="uq_driver_work_preferences_driver_id"
        ),
    )
    op.create_index(
        "ix_driver_work_preferences_driver_id",
        "driver_work_preferences",
        ["driver_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_driver_work_preferences_driver_id",
        table_name="driver_work_preferences",
    )
    op.drop_table("driver_work_preferences")
