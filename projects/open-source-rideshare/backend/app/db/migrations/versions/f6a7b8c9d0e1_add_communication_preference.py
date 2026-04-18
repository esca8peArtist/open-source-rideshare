"""add communication_preference to ride_preferences

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None

_ENUM_NAME = "communicationpreference"
_ENUM_VALUES = ("no_preference", "text", "app", "verbal")


def upgrade():
    communication_enum = sa.Enum(*_ENUM_VALUES, name=_ENUM_NAME)
    communication_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "ride_preferences",
        sa.Column(
            "communication_preference",
            sa.Enum(*_ENUM_VALUES, name=_ENUM_NAME),
            nullable=False,
            server_default="no_preference",
        ),
    )


def downgrade():
    op.drop_column("ride_preferences", "communication_preference")
    sa.Enum(name=_ENUM_NAME).drop(op.get_bind(), checkfirst=True)
