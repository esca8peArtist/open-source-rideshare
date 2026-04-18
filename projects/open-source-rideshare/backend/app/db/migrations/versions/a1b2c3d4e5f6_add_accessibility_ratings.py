"""add accessibility_ratings table

Revision ID: a1b2c3d4e5f6
Revises: z0a1b2c3d4e5
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "z0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "accessibility_ratings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ride_id", sa.Integer(), nullable=False),
        sa.Column("rider_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column(
            "accommodation_type",
            sa.Enum(
                "hearing_impairment",
                "visual_impairment",
                "service_animal",
                "communication_preference",
                "general",
                name="accommodationtype",
            ),
            nullable=True,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"]),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ride_id", "rider_id", name="uq_accessibility_rating_ride_rider"),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_accessibility_rating_range"),
    )
    op.create_index("ix_accessibility_ratings_ride_id", "accessibility_ratings", ["ride_id"])
    op.create_index("ix_accessibility_ratings_rider_id", "accessibility_ratings", ["rider_id"])


def downgrade():
    op.drop_index("ix_accessibility_ratings_rider_id", table_name="accessibility_ratings")
    op.drop_index("ix_accessibility_ratings_ride_id", table_name="accessibility_ratings")
    op.drop_table("accessibility_ratings")
    op.execute("DROP TYPE IF EXISTS accommodationtype")
