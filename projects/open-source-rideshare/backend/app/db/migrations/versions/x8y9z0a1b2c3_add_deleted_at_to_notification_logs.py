"""add deleted_at to notification_logs

Revision ID: x8y9z0a1b2c3
Revises: w7x8y9z0a1b2
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "x8y9z0a1b2c3"
down_revision = "w7x8y9z0a1b2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "notification_logs",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("notification_logs", "deleted_at")
