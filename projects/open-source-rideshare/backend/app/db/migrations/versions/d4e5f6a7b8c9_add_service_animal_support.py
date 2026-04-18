"""add service animal support

Adds has_service_animal to ride_preferences (rider flag) and
service_animal_friendly to driver_profiles (driver capability flag).

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ride_preferences",
        sa.Column(
            "has_service_animal",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "driver_profiles",
        sa.Column(
            "service_animal_friendly",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade():
    op.drop_column("ride_preferences", "has_service_animal")
    op.drop_column("driver_profiles", "service_animal_friendly")
