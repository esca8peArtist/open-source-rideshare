"""add rider_ratings table

Revision ID: f1a3c7e92d05
Revises: e2f5a9c81d47
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a3c7e92d05'
down_revision: Union[str, Sequence[str], None] = 'e2f5a9c81d47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rider_ratings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ride_id", sa.Integer(), sa.ForeignKey("rides.id"), nullable=False, index=True),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("rider_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ride_id", "driver_id", name="uq_rider_rating_ride_driver"),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_rider_rating_range"),
    )
    op.create_index("ix_rider_ratings_rider_id_created_at", "rider_ratings", ["rider_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_rider_ratings_rider_id_created_at", table_name="rider_ratings")
    op.drop_table("rider_ratings")
