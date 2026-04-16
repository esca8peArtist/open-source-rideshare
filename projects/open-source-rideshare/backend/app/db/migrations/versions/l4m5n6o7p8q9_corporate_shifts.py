"""Add corporate_shifts and corporate_shift_assignments tables.

Companies with shift workers (healthcare, manufacturing, security) need
coordinated transportation to/from shift start and end times.  Admins define
named shifts with timing and work location; employees are assigned with their
personal pickup addresses.

Tables created:
  corporate_shifts
  corporate_shift_assignments

Revision ID: l4m5n6o7p8q9
Revises:     k3l4m5n6o7p8
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "l4m5n6o7p8q9"
down_revision = "k3l4m5n6o7p8"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "corporate_shifts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("work_location_name", sa.String(length=200), nullable=False),
        sa.Column("work_address_line1", sa.String(length=200), nullable=True),
        sa.Column("work_address_line2", sa.String(length=200), nullable=True),
        sa.Column("work_city", sa.String(length=100), nullable=True),
        sa.Column("work_state", sa.String(length=100), nullable=True),
        sa.Column("work_country", sa.String(length=100), nullable=True),
        sa.Column("work_postal_code", sa.String(length=20), nullable=True),
        sa.Column("work_latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("work_longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("shift_start_time", sa.Time(), nullable=False),
        sa.Column("shift_end_time", sa.Time(), nullable=False),
        sa.Column(
            "days_of_week",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
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
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "name", name="uq_corp_shift_account_name"),
    )

    op.create_index(
        "ix_corp_shift_account_id",
        "corporate_shifts",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_shift_is_active",
        "corporate_shifts",
        ["is_active"],
    )

    op.create_table(
        "corporate_shift_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shift_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("pickup_address_line1", sa.String(length=200), nullable=True),
        sa.Column("pickup_address_line2", sa.String(length=200), nullable=True),
        sa.Column("pickup_city", sa.String(length=100), nullable=True),
        sa.Column("pickup_state", sa.String(length=100), nullable=True),
        sa.Column("pickup_country", sa.String(length=100), nullable=True),
        sa.Column("pickup_postal_code", sa.String(length=20), nullable=True),
        sa.Column("pickup_latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("pickup_longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column(
            "auto_request_rides",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "advance_booking_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("60"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("assigned_by_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            ["shift_id"],
            ["corporate_shifts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["corporate_account_members.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "shift_id", "member_id", name="uq_corp_shift_assignment"
        ),
    )

    op.create_index(
        "ix_corp_shift_assignment_shift_id",
        "corporate_shift_assignments",
        ["shift_id"],
    )
    op.create_index(
        "ix_corp_shift_assignment_member_id",
        "corporate_shift_assignments",
        ["member_id"],
    )
    op.create_index(
        "ix_corp_shift_assignment_is_active",
        "corporate_shift_assignments",
        ["is_active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_shift_assignment_is_active",
        table_name="corporate_shift_assignments",
    )
    op.drop_index(
        "ix_corp_shift_assignment_member_id",
        table_name="corporate_shift_assignments",
    )
    op.drop_index(
        "ix_corp_shift_assignment_shift_id",
        table_name="corporate_shift_assignments",
    )
    op.drop_table("corporate_shift_assignments")

    op.drop_index(
        "ix_corp_shift_is_active",
        table_name="corporate_shifts",
    )
    op.drop_index(
        "ix_corp_shift_account_id",
        table_name="corporate_shifts",
    )
    op.drop_table("corporate_shifts")
