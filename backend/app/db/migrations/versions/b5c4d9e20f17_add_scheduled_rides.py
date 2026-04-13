"""add scheduled rides support

Revision ID: b5c4d9e20f17
Revises: a3f2e8b91d04
Create Date: 2026-04-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b5c4d9e20f17'
down_revision: Union[str, Sequence[str], None] = 'a3f2e8b91d04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add scheduled_for column to rides
    op.add_column(
        "rides",
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
    )

    # Add 'scheduled' to the ridestatus enum
    # PostgreSQL requires ALTER TYPE to add a new enum value
    op.execute("ALTER TYPE ridestatus ADD VALUE IF NOT EXISTS 'scheduled' BEFORE 'requested'")


def downgrade() -> None:
    op.drop_column("rides", "scheduled_for")
    # Note: PostgreSQL does not support removing enum values.
    # The 'scheduled' value will remain in the enum type.
