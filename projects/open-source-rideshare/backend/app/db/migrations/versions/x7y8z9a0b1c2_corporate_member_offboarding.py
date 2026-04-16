"""Add corporate_member_offboardings table.

Tracks the structured offboarding workflow for employees leaving a corporate
account.  Ten cleanup steps are tracked in a JSONB column (steps_completed).

Table created:
  corporate_member_offboardings — one record per offboarding instance

Revision ID: x7y8z9a0b1c2
Revises:     w6x7y8z9a0b1
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "x7y8z9a0b1c2"
down_revision = "w6x7y8z9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------- offboardingstatus enum
    op.execute(
        "CREATE TYPE offboardingstatus AS ENUM "
        "('pending', 'in_progress', 'completed', 'cancelled')"
    )

    # --------------------------------- corporate_member_offboardings
    op.create_table(
        "corporate_member_offboardings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("member_email", sa.String(255), nullable=False),
        sa.Column("member_name", sa.String(255), nullable=False),
        sa.Column(
            "initiated_by_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "in_progress",
                "completed",
                "cancelled",
                name="offboardingstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("last_day", sa.Date, nullable=True),
        sa.Column(
            "steps_completed",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "cancelled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "cancelled_by_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
        ),
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
    )

    op.create_index(
        "ix_corp_offboarding_account_id",
        "corporate_member_offboardings",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_offboarding_member_id",
        "corporate_member_offboardings",
        ["member_id"],
    )
    op.create_index(
        "ix_corp_offboarding_member_email",
        "corporate_member_offboardings",
        ["member_email"],
    )
    op.create_index(
        "ix_corp_offboarding_status",
        "corporate_member_offboardings",
        ["status"],
    )
    op.create_index(
        "ix_corp_offboarding_created_at",
        "corporate_member_offboardings",
        ["created_at"],
    )
    op.create_index(
        "ix_corp_offboarding_account_status",
        "corporate_member_offboardings",
        ["account_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_offboarding_account_status",
        table_name="corporate_member_offboardings",
    )
    op.drop_index(
        "ix_corp_offboarding_created_at",
        table_name="corporate_member_offboardings",
    )
    op.drop_index(
        "ix_corp_offboarding_status",
        table_name="corporate_member_offboardings",
    )
    op.drop_index(
        "ix_corp_offboarding_member_email",
        table_name="corporate_member_offboardings",
    )
    op.drop_index(
        "ix_corp_offboarding_member_id",
        table_name="corporate_member_offboardings",
    )
    op.drop_index(
        "ix_corp_offboarding_account_id",
        table_name="corporate_member_offboardings",
    )
    op.drop_table("corporate_member_offboardings")
    op.execute("DROP TYPE IF EXISTS offboardingstatus")
