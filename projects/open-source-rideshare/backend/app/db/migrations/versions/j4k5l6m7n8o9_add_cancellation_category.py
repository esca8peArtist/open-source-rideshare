"""add cancellation_category and cancelled_by to rides

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa

revision = "j4k5l6m7n8o9"
down_revision = "i3j4k5l6m7n8"
branch_labels = None
depends_on = None

cancellation_category_enum = sa.Enum(
    "wrong_pickup",
    "wait_too_long",
    "found_other_ride",
    "plans_changed",
    "driver_not_acceptable",
    "price_too_high",
    "safety_concern",
    "other",
    "vehicle_issue",
    "rider_no_show",
    "unable_to_locate",
    "emergency",
    "driver_other",
    name="cancellationcategory",
)


def upgrade():
    cancellation_category_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "rides",
        sa.Column("cancellation_category", cancellation_category_enum, nullable=True),
    )
    op.add_column(
        "rides",
        sa.Column("cancelled_by", sa.String(10), nullable=True),
    )


def downgrade():
    op.drop_column("rides", "cancelled_by")
    op.drop_column("rides", "cancellation_category")
    cancellation_category_enum.drop(op.get_bind(), checkfirst=True)
