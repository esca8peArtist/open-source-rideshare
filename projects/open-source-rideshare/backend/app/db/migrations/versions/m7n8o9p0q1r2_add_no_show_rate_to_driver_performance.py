"""add no-show rate columns to driver_performance_snapshots

Adds:
- total_no_shows  (INTEGER, default 0)  — count of rides cancelled as DRIVER_NO_SHOW
- no_show_rate    (FLOAT,   default 0)  — no_shows / rides_accepted (0.0–1.0)

Revision ID: m7n8o9p0q1r2
Revises: l6m7n8o9p0q1
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa

revision = "m7n8o9p0q1r2"
down_revision = "l6m7n8o9p0q1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "driver_performance_snapshots",
        sa.Column("total_no_shows", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "driver_performance_snapshots",
        sa.Column("no_show_rate", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("driver_performance_snapshots", "no_show_rate")
    op.drop_column("driver_performance_snapshots", "total_no_shows")
