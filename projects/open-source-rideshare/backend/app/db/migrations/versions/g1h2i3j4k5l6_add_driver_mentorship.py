"""Add Driver Mentorship Program tables.

Tables created:
  driver_mentorships    — one mentorship record per mentee (pending/active/completed/cancelled)
  mentorship_earnings   — per-ride commission earned by mentors

Enum types created:
  mentorshipstatus  — pending / active / completed / cancelled

Revision ID: g1h2i3j4k5l6
Revises: f8a9b0c1d2e3
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "g1h2i3j4k5l6"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------------
    mentorshipstatus_enum = sa.Enum(
        "pending", "active", "completed", "cancelled",
        name="mentorshipstatus",
    )
    mentorshipstatus_enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # driver_mentorships
    # ------------------------------------------------------------------
    op.create_table(
        "driver_mentorships",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("mentee_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("mentor_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "active", "completed", "cancelled", name="mentorshipstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("commission_rate", sa.Float, nullable=False, server_default="0.02"),
        sa.Column("commission_days", sa.Integer, nullable=False, server_default="90"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("cancel_reason", sa.String(500), nullable=True),
        sa.Column("admin_note", sa.Text, nullable=True),
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("mentee_id", name="uq_mentorship_active_mentee"),
    )
    op.create_index("ix_driver_mentorships_mentee_id", "driver_mentorships", ["mentee_id"])
    op.create_index("ix_driver_mentorships_mentor_id", "driver_mentorships", ["mentor_id"])
    op.create_index("ix_driver_mentorships_status", "driver_mentorships", ["status"])

    # ------------------------------------------------------------------
    # mentorship_earnings
    # ------------------------------------------------------------------
    op.create_table(
        "mentorship_earnings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "mentorship_id",
            sa.Integer,
            sa.ForeignKey("driver_mentorships.id"),
            nullable=False,
        ),
        sa.Column(
            "ride_id",
            sa.Integer,
            sa.ForeignKey("rides.id"),
            nullable=False,
        ),
        sa.Column("mentee_earnings", sa.Float, nullable=False),
        sa.Column("commission_amount", sa.Float, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "mentorship_id", "ride_id", name="uq_mentorship_earning_ride"
        ),
    )
    op.create_index(
        "ix_mentorship_earnings_mentorship_id", "mentorship_earnings", ["mentorship_id"]
    )
    op.create_index(
        "ix_mentorship_earnings_ride_id", "mentorship_earnings", ["ride_id"]
    )
    op.create_index(
        "ix_mentorship_earnings_created_at", "mentorship_earnings", ["created_at"]
    )


def downgrade() -> None:
    op.drop_table("mentorship_earnings")
    op.drop_table("driver_mentorships")
    sa.Enum(name="mentorshipstatus").drop(op.get_bind(), checkfirst=True)
