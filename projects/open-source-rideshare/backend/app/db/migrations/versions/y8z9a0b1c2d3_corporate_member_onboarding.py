"""Add corporate_member_onboardings table.

Tracks the structured onboarding checklist for new employees joining a
corporate account.  Ten setup steps are tracked in a JSONB column
(steps_completed).

Table created:
  corporate_member_onboardings — one record per onboarding instance

Revision ID: y8z9a0b1c2d3
Revises:     x7y8z9a0b1c2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "y8z9a0b1c2d3"
down_revision = "x7y8z9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------- onboardingstatus enum
    op.execute(
        "CREATE TYPE onboardingstatus AS ENUM "
        "('pending', 'in_progress', 'completed')"
    )

    # --------------------------------- corporate_member_onboardings
    op.create_table(
        "corporate_member_onboardings",
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
            "invitation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corporate_employee_invitations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_id",
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
                name="onboardingstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
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
        "ix_corp_onboarding_account_id",
        "corporate_member_onboardings",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_onboarding_member_id",
        "corporate_member_onboardings",
        ["member_id"],
    )
    op.create_index(
        "ix_corp_onboarding_member_email",
        "corporate_member_onboardings",
        ["member_email"],
    )
    op.create_index(
        "ix_corp_onboarding_status",
        "corporate_member_onboardings",
        ["status"],
    )
    op.create_index(
        "ix_corp_onboarding_created_at",
        "corporate_member_onboardings",
        ["created_at"],
    )
    op.create_index(
        "ix_corp_onboarding_account_status",
        "corporate_member_onboardings",
        ["account_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_onboarding_account_status",
        table_name="corporate_member_onboardings",
    )
    op.drop_index(
        "ix_corp_onboarding_created_at",
        table_name="corporate_member_onboardings",
    )
    op.drop_index(
        "ix_corp_onboarding_status",
        table_name="corporate_member_onboardings",
    )
    op.drop_index(
        "ix_corp_onboarding_member_email",
        table_name="corporate_member_onboardings",
    )
    op.drop_index(
        "ix_corp_onboarding_member_id",
        table_name="corporate_member_onboardings",
    )
    op.drop_index(
        "ix_corp_onboarding_account_id",
        table_name="corporate_member_onboardings",
    )
    op.drop_table("corporate_member_onboardings")
    op.execute("DROP TYPE IF EXISTS onboardingstatus")
