"""add rider_favorite_drivers table

Revision ID: q1r2s3t4u5v6
Revises: p0q1r2s3t4u5
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "q1r2s3t4u5v6"
down_revision = "p0q1r2s3t4u5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rider_favorite_drivers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rider_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "driver_profile_id",
            sa.Integer(),
            sa.ForeignKey("driver_profiles.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rider_id", "driver_profile_id", name="uq_rider_favorite_driver"),
    )
    op.create_index("ix_rider_favorite_drivers_rider_id", "rider_favorite_drivers", ["rider_id"])
    op.create_index(
        "ix_rider_favorite_drivers_driver_profile_id",
        "rider_favorite_drivers",
        ["driver_profile_id"],
    )


def downgrade():
    op.drop_index("ix_rider_favorite_drivers_driver_profile_id", table_name="rider_favorite_drivers")
    op.drop_index("ix_rider_favorite_drivers_rider_id", table_name="rider_favorite_drivers")
    op.drop_table("rider_favorite_drivers")
