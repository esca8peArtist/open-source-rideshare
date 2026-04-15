"""Add corporate_blackout_periods table.

Admins define named date ranges when corporate bookings are restricted.
Supports one-time ranges, annually-recurring windows, and weekly recurring
time blocks.

Tables created:
  corporate_blackout_periods — per-account booking restriction windows with
                               recurrence, affected_days JSONB, override
                               policy, and soft-delete support.

Revision ID: y2z3a4b5c6d7
Revises:     x2y3z4a5b6c7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "y2z3a4b5c6d7"
down_revision: str = "x2y3z4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the BlackoutRecurrence enum type
    blackout_recurrence = postgresql.ENUM(
        "none", "annual", "weekly",
        name="blackoutrecurrence",
        create_type=True,
    )
    blackout_recurrence.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "corporate_blackout_periods",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("corporate_account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("start_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recurrence",
            sa.Enum(
                "none", "annual", "weekly",
                name="blackoutrecurrence",
                create_type=False,
            ),
            nullable=False,
            server_default="none",
        ),
        sa.Column("affected_days", postgresql.JSONB(), nullable=True),
        sa.Column(
            "override_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "override_requires_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("reason", sa.Text(), nullable=True),
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
            ["corporate_account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corp_blackout_periods_account_id",
        "corporate_blackout_periods",
        ["corporate_account_id"],
    )
    op.create_index(
        "ix_corp_blackout_periods_is_active",
        "corporate_blackout_periods",
        ["is_active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_blackout_periods_is_active",
        table_name="corporate_blackout_periods",
    )
    op.drop_index(
        "ix_corp_blackout_periods_account_id",
        table_name="corporate_blackout_periods",
    )
    op.drop_table("corporate_blackout_periods")
    op.execute("DROP TYPE IF EXISTS blackoutrecurrence")
