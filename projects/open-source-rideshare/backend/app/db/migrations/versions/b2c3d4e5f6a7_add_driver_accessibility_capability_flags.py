"""add driver accessibility capability flags

Adds hearing_impairment_capable and sign_language_capable boolean columns to
the driver_profiles table so drivers can declare their ability to accommodate
riders with hearing impairments.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "driver_profiles",
        sa.Column(
            "hearing_impairment_capable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "driver_profiles",
        sa.Column(
            "sign_language_capable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade():
    op.drop_column("driver_profiles", "sign_language_capable")
    op.drop_column("driver_profiles", "hearing_impairment_capable")
