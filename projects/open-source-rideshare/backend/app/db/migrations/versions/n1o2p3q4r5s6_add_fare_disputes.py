"""add fare_disputes table

Revision ID: n1o2p3q4r5s6
Revises: m1n2o3p4q5r6
Create Date: 2026-04-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'n1o2p3q4r5s6'
down_revision: Union[str, Sequence[str], None] = 'm1n2o3p4q5r6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fare_disputes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ride_id", sa.Integer(), nullable=False),
        sa.Column("rider_id", sa.Integer(), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "overcharge",
                "incorrect_route",
                "incomplete_ride",
                "unauthorized_charge",
                "wait_time_fee",
                "surge_pricing",
                "other",
                name="disputecategory",
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("disputed_amount", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "under_review",
                "approved",
                "partial",
                "denied",
                "withdrawn",
                name="disputestatus",
            ),
            nullable=False,
        ),
        sa.Column("reviewed_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column("refund_amount", sa.Float(), nullable=True),
        sa.Column("stripe_refund_id", sa.String(length=255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_admin_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fare_disputes_ride_id", "fare_disputes", ["ride_id"])
    op.create_index("ix_fare_disputes_rider_id", "fare_disputes", ["rider_id"])
    op.create_index("ix_fare_disputes_status", "fare_disputes", ["status"])
    op.create_index("ix_fare_disputes_created_at", "fare_disputes", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_fare_disputes_created_at", table_name="fare_disputes")
    op.drop_index("ix_fare_disputes_status", table_name="fare_disputes")
    op.drop_index("ix_fare_disputes_rider_id", table_name="fare_disputes")
    op.drop_index("ix_fare_disputes_ride_id", table_name="fare_disputes")
    op.drop_table("fare_disputes")
    op.execute("DROP TYPE IF EXISTS disputecategory")
    op.execute("DROP TYPE IF EXISTS disputestatus")
