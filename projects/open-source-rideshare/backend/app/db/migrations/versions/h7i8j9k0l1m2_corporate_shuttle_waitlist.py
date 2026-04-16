"""Add corporate shuttle waitlist table.

When a shuttle schedule run is at full capacity employees can join a waitlist.
The first waiting member is automatically promoted to a confirmed booking when
an existing booking is cancelled.

Table created:
  corporate_shuttle_waitlists  — queued seat requests per member per schedule+date

Revision ID: h7i8j9k0l1m2
Revises:     g6h7i8j9k0l1
Create Date: 2026-04-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "h7i8j9k0l1m2"
down_revision = "g6h7i8j9k0l1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- enum ----
    waitliststatus = postgresql.ENUM(
        "waiting",
        "promoted",
        "expired",
        "cancelled",
        name="waitliststatus",
        create_type=False,
    )
    waitliststatus.create(op.get_bind(), checkfirst=True)

    # ---------------------------------------- corporate_shuttle_waitlists
    op.create_table(
        "corporate_shuttle_waitlists",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=True),
        sa.Column("booking_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "waiting",
                "promoted",
                "expired",
                "cancelled",
                name="waitliststatus",
            ),
            nullable=False,
            server_default="waiting",
        ),
        sa.Column("queue_position", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "promoted_booking_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"],
            ["corporate_shuttle_schedules.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["promoted_booking_id"],
            ["corporate_shuttle_bookings.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "schedule_id",
            "member_id",
            "booking_date",
            name="uq_waitlist_schedule_member_date",
        ),
    )
    op.create_index(
        "ix_waitlist_schedule_date",
        "corporate_shuttle_waitlists",
        ["schedule_id", "booking_date"],
    )
    op.create_index(
        "ix_waitlist_account_id",
        "corporate_shuttle_waitlists",
        ["account_id"],
    )
    op.create_index(
        "ix_waitlist_member_id",
        "corporate_shuttle_waitlists",
        ["member_id"],
    )
    op.create_index(
        "ix_waitlist_status",
        "corporate_shuttle_waitlists",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("corporate_shuttle_waitlists")
    op.execute("DROP TYPE IF EXISTS waitliststatus")
