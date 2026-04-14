"""add surge_price_locks table

Revision ID: j1k2l3m4n5o6
Revises: i1j2k3l4m5n6
Create Date: 2026-04-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'j1k2l3m4n5o6'
down_revision: Union[str, Sequence[str], None] = 'i1j2k3l4m5n6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "surge_price_locks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rider_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("pickup_lat", sa.Float(), nullable=False),
        sa.Column("pickup_lon", sa.Float(), nullable=False),
        sa.Column("pickup_address", sa.String(500), nullable=True),
        sa.Column("locked_multiplier", sa.Float(), nullable=False),
        sa.Column(
            "locked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ride_id",
            sa.Integer(),
            sa.ForeignKey("rides.id"),
            nullable=True,
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_surge_price_locks_ride_id", "surge_price_locks", ["ride_id"])


def downgrade() -> None:
    op.drop_index("ix_surge_price_locks_ride_id", table_name="surge_price_locks")
    op.drop_table("surge_price_locks")
