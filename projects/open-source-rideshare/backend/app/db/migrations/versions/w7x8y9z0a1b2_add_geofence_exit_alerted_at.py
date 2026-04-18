"""add geofence_exit_alerted_at to rides

Revision ID: w7x8y9z0a1b2
Revises: v6w7x8y9z0a1
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "w7x8y9z0a1b2"
down_revision = "v6w7x8y9z0a1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "rides",
        sa.Column("geofence_exit_alerted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("rides", "geofence_exit_alerted_at")
