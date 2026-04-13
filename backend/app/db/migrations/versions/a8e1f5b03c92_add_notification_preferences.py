"""add notification_preferences_v2

Revision ID: a8e1f5b03c92
Revises: f1a3c7e92d05
Create Date: 2026-04-13 00:00:00.000000

Adds the notification_preferences_v2 table which stores per-user, per-type,
per-channel opt-in/out preferences.  The absence of a row means the
combination is enabled (opt-out model).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8e1f5b03c92'
down_revision: Union[str, Sequence[str], None] = 'f1a3c7e92d05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_preferences_v2",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("notification_type", sa.String(60), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id",
            "notification_type",
            "channel",
            name="uq_notif_pref_user_type_channel",
        ),
    )


def downgrade() -> None:
    op.drop_table("notification_preferences_v2")
