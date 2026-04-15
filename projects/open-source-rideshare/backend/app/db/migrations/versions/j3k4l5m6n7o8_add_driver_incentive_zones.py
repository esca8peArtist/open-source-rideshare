"""Add driver incentive zones (boost zones).

Cooperative-transparent boost zones: admins create time-limited geographic
windows with earnings bonuses for drivers.  Every zone requires a human-readable
``reason`` so drivers and the community understand the incentive rationale.

Tables created:
  driver_incentive_zones    — zone definitions (admin-managed)
  driver_zone_completions   — immutable per-ride bonus records (idempotent)

Enum types created:
  incentivebonustype   — multiplier / flat

Revision ID: j3k4l5m6n7o8
Revises: i2j3k4l5m6n7
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic
revision: str = "j3k4l5m6n7o8"
down_revision: str = "i2j3k4l5m6n7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum type
    incentivebonustype = postgresql.ENUM(
        "multiplier", "flat", name="incentivebonustype", create_type=False
    )
    incentivebonustype.create(op.get_bind(), checkfirst=True)

    # driver_incentive_zones
    op.create_table(
        "driver_incentive_zones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("polygon", sa.JSON(), nullable=True),
        sa.Column("center_lat", sa.Float(), nullable=True),
        sa.Column("center_lon", sa.Float(), nullable=True),
        sa.Column("radius_km", sa.Float(), nullable=True),
        sa.Column(
            "bonus_type",
            sa.Enum("multiplier", "flat", name="incentivebonustype"),
            nullable=False,
        ),
        sa.Column("bonus_multiplier", sa.Numeric(5, 3), nullable=True),
        sa.Column("bonus_flat_cents", sa.Integer(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_total_completions", sa.Integer(), nullable=True),
        sa.Column("max_completions_per_driver", sa.Integer(), nullable=True),
        sa.Column("min_driver_rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
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
    op.create_index(
        "ix_driver_incentive_zones_is_active",
        "driver_incentive_zones",
        ["is_active"],
    )
    op.create_index(
        "ix_driver_incentive_zones_starts_at",
        "driver_incentive_zones",
        ["starts_at"],
    )
    op.create_index(
        "ix_driver_incentive_zones_ends_at",
        "driver_incentive_zones",
        ["ends_at"],
    )

    # driver_zone_completions
    op.create_table(
        "driver_zone_completions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "zone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("driver_incentive_zones.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "driver_profile_id",
            sa.Integer(),
            sa.ForeignKey("driver_profiles.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("ride_id", sa.Integer(), nullable=False, index=True),
        sa.Column("bonus_amount_cents", sa.Integer(), nullable=False),
        sa.Column(
            "bonus_type",
            sa.Enum("multiplier", "flat", name="incentivebonustype"),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "zone_id",
            "ride_id",
            name="uq_driver_zone_completions_zone_ride",
        ),
    )


def downgrade() -> None:
    op.drop_table("driver_zone_completions")
    op.drop_table("driver_incentive_zones")
    op.execute("DROP TYPE IF EXISTS incentivebonustype")
