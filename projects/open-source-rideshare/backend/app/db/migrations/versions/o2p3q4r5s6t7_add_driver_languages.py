"""Add driver_languages and rider_language_preferences tables.

Drivers register which languages they speak (with proficiency level).
Riders can set a preferred language for matching — surfaced by the matching
engine as a soft preference (non-blocking).

Cooperative differentiator: language-matched rides for non-English-speaking
communities — genuine accessibility, not just a checkbox.

Tables created:
  driver_languages                — one row per (driver_id, language_code)
  rider_language_preferences      — one row per rider

Indexes added:
  ix_driver_languages_driver_id      — efficient lookup by driver
  ix_driver_languages_language_code  — query all drivers who speak a language
  ix_rider_language_preferences_rider_id — lookup by rider (unique)

Revision ID: o2p3q4r5s6t7
Revises: n1o2p3q4r5s6
Create Date: 2026-04-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o2p3q4r5s6t7"
down_revision: str = "n1o2p3q4r5s6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enum: language proficiency
    language_proficiency_enum = sa.Enum(
        "basic", "conversational", "fluent", "native",
        name="languageproficiency",
    )
    language_proficiency_enum.create(op.get_bind(), checkfirst=True)

    # Table: driver_languages
    op.create_table(
        "driver_languages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("language_code", sa.String(length=10), nullable=False),
        sa.Column("language_name", sa.String(length=100), nullable=False),
        sa.Column(
            "proficiency",
            language_proficiency_enum,
            nullable=False,
            server_default="conversational",
        ),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("driver_id", "language_code", name="uq_driver_language"),
    )
    op.create_index(
        "ix_driver_languages_driver_id",
        "driver_languages",
        ["driver_id"],
    )
    op.create_index(
        "ix_driver_languages_language_code",
        "driver_languages",
        ["language_code"],
    )

    # Table: rider_language_preferences
    op.create_table(
        "rider_language_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "rider_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("language_code", sa.String(length=10), nullable=False),
        sa.Column("language_name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rider_language_preferences_rider_id",
        "rider_language_preferences",
        ["rider_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_rider_language_preferences_rider_id",
        table_name="rider_language_preferences",
    )
    op.drop_table("rider_language_preferences")
    op.drop_index(
        "ix_driver_languages_language_code",
        table_name="driver_languages",
    )
    op.drop_index(
        "ix_driver_languages_driver_id",
        table_name="driver_languages",
    )
    op.drop_table("driver_languages")
    sa.Enum(name="languageproficiency").drop(op.get_bind(), checkfirst=True)
