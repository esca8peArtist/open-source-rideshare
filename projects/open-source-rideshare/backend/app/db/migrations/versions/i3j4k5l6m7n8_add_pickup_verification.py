"""add pickup verification fields to rides

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-04-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'i3j4k5l6m7n8'
down_revision: Union[str, Sequence[str], None] = 'h2i3j4k5l6m7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rides",
        sa.Column("pickup_verification_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "rides",
        sa.Column("driver_photo_confirmed", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "rides",
        sa.Column("plate_confirmed", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rides", "plate_confirmed")
    op.drop_column("rides", "driver_photo_confirmed")
    op.drop_column("rides", "pickup_verification_at")
