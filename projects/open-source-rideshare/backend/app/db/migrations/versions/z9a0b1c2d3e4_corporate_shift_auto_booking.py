"""Add corporate_shift_auto_bookings table.

When a shift assignment has ``auto_request_rides = True``, the platform
generates pending auto-booking records for upcoming shift dates.  Admins
process these records to create actual Ride records.

Enums created:
  shiftautobookingstatus    — pending / booked / failed / skipped / cancelled
  shiftautobookingdirection — to_work / from_work

Table created:
  corporate_shift_auto_bookings — one record per (assignment, date, direction)

Revision ID: z9a0b1c2d3e4
Revises:     y8z9a0b1c2d3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "z9a0b1c2d3e4"
down_revision = "y8z9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------- shiftautobookingstatus enum
    op.execute(
        "CREATE TYPE shiftautobookingstatus AS ENUM "
        "('pending', 'booked', 'failed', 'skipped', 'cancelled')"
    )

    # --------------------------------------- shiftautobookingdirection enum
    op.execute(
        "CREATE TYPE shiftautobookingdirection AS ENUM "
        "('to_work', 'from_work')"
    )

    # ----------------------------- corporate_shift_auto_bookings
    op.create_table(
        "corporate_shift_auto_bookings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "shift_id",
            sa.Integer,
            sa.ForeignKey("corporate_shifts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assignment_id",
            sa.Integer,
            sa.ForeignKey("corporate_shift_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            sa.Integer,
            sa.ForeignKey("corporate_account_members.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("shift_date", sa.Date, nullable=False),
        sa.Column(
            "ride_direction",
            sa.Enum(
                "to_work",
                "from_work",
                name="shiftautobookingdirection",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "scheduled_for",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "booked",
                "failed",
                "skipped",
                "cancelled",
                name="shiftautobookingstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "ride_id",
            sa.Integer,
            sa.ForeignKey("rides.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("failure_reason", sa.Text, nullable=True),
        sa.Column("booked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "assignment_id",
            "shift_date",
            "ride_direction",
            name="uq_corp_shift_auto_booking",
        ),
    )

    # Indexes
    op.create_index(
        "ix_corp_sab_shift_id",
        "corporate_shift_auto_bookings",
        ["shift_id"],
    )
    op.create_index(
        "ix_corp_sab_assignment_id",
        "corporate_shift_auto_bookings",
        ["assignment_id"],
    )
    op.create_index(
        "ix_corp_sab_member_id",
        "corporate_shift_auto_bookings",
        ["member_id"],
    )
    op.create_index(
        "ix_corp_sab_account_id",
        "corporate_shift_auto_bookings",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_sab_account_status",
        "corporate_shift_auto_bookings",
        ["account_id", "status"],
    )
    op.create_index(
        "ix_corp_sab_scheduled_for",
        "corporate_shift_auto_bookings",
        ["scheduled_for"],
    )


def downgrade() -> None:
    op.drop_index("ix_corp_sab_scheduled_for", "corporate_shift_auto_bookings")
    op.drop_index("ix_corp_sab_account_status", "corporate_shift_auto_bookings")
    op.drop_index("ix_corp_sab_account_id", "corporate_shift_auto_bookings")
    op.drop_index("ix_corp_sab_member_id", "corporate_shift_auto_bookings")
    op.drop_index("ix_corp_sab_assignment_id", "corporate_shift_auto_bookings")
    op.drop_index("ix_corp_sab_shift_id", "corporate_shift_auto_bookings")
    op.drop_table("corporate_shift_auto_bookings")
    op.execute("DROP TYPE IF EXISTS shiftautobookingstatus")
    op.execute("DROP TYPE IF EXISTS shiftautobookingdirection")
