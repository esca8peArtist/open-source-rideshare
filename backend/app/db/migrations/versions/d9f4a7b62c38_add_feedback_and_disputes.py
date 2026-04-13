"""add ride_feedback and disputes tables

Revision ID: d9f4a7b62c38
Revises: c8e3f4a51b29
Create Date: 2026-04-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9f4a7b62c38'
down_revision: Union[str, Sequence[str], None] = 'c8e3f4a51b29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ride_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ride_id", sa.Integer(), sa.ForeignKey("rides.id"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("categories", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # Prevent duplicate feedback from same user on same ride
    op.create_index(
        "ix_ride_feedback_user_ride",
        "ride_feedback",
        ["ride_id", "user_id"],
        unique=True,
    )

    op.create_table(
        "disputes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ride_id", sa.Integer(), sa.ForeignKey("rides.id"), nullable=False, index=True),
        sa.Column("filed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column(
            "dispute_type",
            sa.Enum(
                "fare", "route", "driver_behavior", "rider_behavior",
                "safety_concern", "property_damage", "lost_item",
                "cancellation_fee", "other",
                name="disputetype",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "open", "under_review", "resolved_rider_favor",
                "resolved_driver_favor", "resolved_partial", "dismissed",
                name="disputestatus",
            ),
            nullable=False,
            server_default="open",
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("refund_amount", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("disputes")
    op.execute("DROP TYPE IF EXISTS disputestatus")
    op.execute("DROP TYPE IF EXISTS disputetype")
    op.drop_index("ix_ride_feedback_user_ride", table_name="ride_feedback")
    op.drop_table("ride_feedback")
