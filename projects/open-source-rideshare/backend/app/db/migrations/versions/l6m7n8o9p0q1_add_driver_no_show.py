"""add driver no-show columns and enum value

Adds:
- arrived_at column on rides (set when driver marks ARRIVED)
- driver_no_show_reported_at column on rides (set on manual or auto no-show)
- driver_no_show value to CancellationCategory enum

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa

revision = "l6m7n8o9p0q1"
down_revision = "k5l6m7n8o9p0"
branch_labels = None
depends_on = None


def upgrade():
    # Add new enum value — PostgreSQL requires ALTER TYPE; SQLite ignores this
    op.execute("ALTER TYPE cancellationcategory ADD VALUE IF NOT EXISTS 'driver_no_show'")

    # arrived_at: timestamp set when driver marks the ride ARRIVED
    op.add_column(
        "rides",
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True),
    )

    # driver_no_show_reported_at: set on manual rider report or automated detection
    op.add_column(
        "rides",
        sa.Column("driver_no_show_reported_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("rides", "driver_no_show_reported_at")
    op.drop_column("rides", "arrived_at")
    # Enum value removal is not supported in PostgreSQL without table recreation;
    # leave the value in place on downgrade.
