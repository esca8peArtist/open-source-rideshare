"""add recurring_ride_skips table

Revision ID: y9z0a1b2c3d4
Revises: x8y9z0a1b2c3
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "y9z0a1b2c3d4"
down_revision = "x8y9z0a1b2c3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "recurring_ride_skips",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recurring_ride_id", sa.Integer(), nullable=False),
        sa.Column("skip_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["recurring_ride_id"], ["recurring_rides.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recurring_ride_id", "skip_date", name="uq_recurring_ride_skip"
        ),
    )
    op.create_index(
        "ix_recurring_ride_skips_recurring_ride_id",
        "recurring_ride_skips",
        ["recurring_ride_id"],
    )


def downgrade():
    op.drop_index(
        "ix_recurring_ride_skips_recurring_ride_id",
        table_name="recurring_ride_skips",
    )
    op.drop_table("recurring_ride_skips")
