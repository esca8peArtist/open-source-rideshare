"""Add driver_rating_appeals table.

Table created:
  driver_rating_appeals — one row per driver appeal of a ride_feedback rating.

Each row links a driver (users.id) and a feedback record (ride_feedback.id).
The feedback_id column has a unique constraint so only one appeal can exist per
rating. The status enum drives the admin review workflow:
  pending → approved (rating nullified) | rejected (rating stands).

Revision ID: b3c4d5e6f7g8
Revises: a2b3c4d5e6f7
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b3c4d5e6f7g8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "driver_rating_appeals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "feedback_id",
            sa.Integer(),
            sa.ForeignKey("ride_feedback.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", name="appealstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("rating_nullified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("feedback_id", name="uq_appeal_per_feedback"),
    )

    op.create_index("ix_driver_rating_appeals_driver_id", "driver_rating_appeals", ["driver_id"])
    op.create_index("ix_driver_rating_appeals_feedback_id", "driver_rating_appeals", ["feedback_id"])
    op.create_index("ix_driver_rating_appeals_status", "driver_rating_appeals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_driver_rating_appeals_status", table_name="driver_rating_appeals")
    op.drop_index("ix_driver_rating_appeals_feedback_id", table_name="driver_rating_appeals")
    op.drop_index("ix_driver_rating_appeals_driver_id", table_name="driver_rating_appeals")
    op.drop_table("driver_rating_appeals")
    op.execute("DROP TYPE IF EXISTS appealstatus")
