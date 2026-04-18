"""add ends_on to recurring_rides

Revision ID: a1b2c3d4e5f6
Revises: z0a1b2c3d4e5
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "z0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "recurring_rides",
        sa.Column("ends_on", sa.Date(), nullable=True),
    )


def downgrade():
    op.drop_column("recurring_rides", "ends_on")
