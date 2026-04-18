"""add visual impairment support

Adds visual_impairment to ride_preferences (rider flag) and
visual_assistance_capable to driver_profiles (driver capability flag).

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ride_preferences",
        sa.Column(
            "visual_impairment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "driver_profiles",
        sa.Column(
            "visual_assistance_capable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade():
    op.drop_column("ride_preferences", "visual_impairment")
    op.drop_column("driver_profiles", "visual_assistance_capable")
