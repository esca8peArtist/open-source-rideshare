"""add surge_pricing_events table

Records fare previews where surge pricing was active, for admin analytics.
Tracks zone surges, demand surges, and combined events with multiplier history.

Revision ID: o9p0q1r2s3t4
Revises: n8o9p0q1r2s3
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "o9p0q1r2s3t4"
down_revision = "n8o9p0q1r2s3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "surge_pricing_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("geohash", sa.String(12), nullable=False),
        sa.Column("surge_zone_id", sa.String(36), nullable=True),
        sa.Column("surge_zone_name", sa.String(200), nullable=True),
        sa.Column("zone_multiplier", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("demand_multiplier", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("demand_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("supply_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("combined_multiplier", sa.Float(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_surge_events_event_type", "surge_pricing_events", ["event_type"])
    op.create_index("ix_surge_events_geohash", "surge_pricing_events", ["geohash"])
    op.create_index("ix_surge_events_zone_id", "surge_pricing_events", ["surge_zone_id"])
    op.create_index("ix_surge_events_recorded_at", "surge_pricing_events", ["recorded_at"])


def downgrade():
    op.drop_index("ix_surge_events_recorded_at", table_name="surge_pricing_events")
    op.drop_index("ix_surge_events_zone_id", table_name="surge_pricing_events")
    op.drop_index("ix_surge_events_geohash", table_name="surge_pricing_events")
    op.drop_index("ix_surge_events_event_type", table_name="surge_pricing_events")
    op.drop_table("surge_pricing_events")
