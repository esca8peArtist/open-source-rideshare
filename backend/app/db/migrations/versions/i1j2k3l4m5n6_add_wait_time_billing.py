"""add driver_arrived_at and wait_time_fee to rides

Revision ID: i1j2k3l4m5n6
Revises: h1i2j3k4l5m6
Create Date: 2026-04-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'i1j2k3l4m5n6'
down_revision: Union[str, Sequence[str], None] = 'h1i2j3k4l5m6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rides",
        sa.Column("driver_arrived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "rides",
        sa.Column(
            "wait_time_fee",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("rides", "wait_time_fee")
    op.drop_column("rides", "driver_arrived_at")
