"""Add driver_certifications table for cooperative recognition badges.

Drivers earn badges for quality, safety, and community contribution.
Riders see a driver's badges when matched — a cooperative differentiator
over Uber/Lyft which have no peer recognition system.

Tables created:
  driver_certifications  — one row per driver+badge_type (unique constraint)

Indexes added:
  ix_driver_certifications_driver_id  — efficient lookup by driver
  ix_driver_certifications_is_active  — filter active badges

Revision ID: n1o2p3q4r5s6
Revises: z1a2b3c4d5e6
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n1o2p3q4r5s6"
down_revision: str = "z1a2b3c4d5e6"
branch_labels = None
depends_on = None

BADGE_TYPE_ENUM = "badgetype"


def upgrade() -> None:
    badge_type_enum = sa.Enum(
        "safe_driver",
        "five_star",
        "accessibility_specialist",
        "pet_friendly",
        "long_distance_expert",
        "mentor",
        "eco_driver",
        "veteran",
        name=BADGE_TYPE_ENUM,
    )
    badge_type_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "driver_certifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "driver_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "badge_type",
            sa.Enum(
                "safe_driver",
                "five_star",
                "accessibility_specialist",
                "pet_friendly",
                "long_distance_expert",
                "mentor",
                "eco_driver",
                "veteran",
                name=BADGE_TYPE_ENUM,
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "awarded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "awarded_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revoked_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("driver_id", "badge_type", name="uq_driver_certification"),
    )

    op.create_index(
        "ix_driver_certifications_driver_id",
        "driver_certifications",
        ["driver_id"],
    )
    op.create_index(
        "ix_driver_certifications_is_active",
        "driver_certifications",
        ["is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_driver_certifications_is_active", table_name="driver_certifications")
    op.drop_index("ix_driver_certifications_driver_id", table_name="driver_certifications")
    op.drop_table("driver_certifications")

    badge_type_enum = sa.Enum(name=BADGE_TYPE_ENUM)
    badge_type_enum.drop(op.get_bind(), checkfirst=True)
