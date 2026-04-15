"""Add corporate_account_suspensions table.

Platform admins can suspend corporate accounts for billing, compliance, or
policy violations.  This migration adds the suspensionreason enum and the
suspension events table.

Tables created:
  corporate_account_suspensions — one row per suspension event; is_active
                                  flags the current state.

Revision ID: v2w3x4y5z6a7
Revises:     u1v2w3x4y5z6
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v2w3x4y5z6a7"
down_revision: str = "u1v2w3x4y5z6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    suspensionreason = postgresql.ENUM(
        "billing_overdue",
        "policy_violation",
        "fraud_investigation",
        "voluntary_pause",
        "compliance_failure",
        "non_payment",
        "other",
        name="suspensionreason",
    )
    suspensionreason.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "corporate_account_suspensions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "suspended_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reason",
            sa.Enum(
                "billing_overdue",
                "policy_violation",
                "fraud_investigation",
                "voluntary_pause",
                "compliance_failure",
                "non_payment",
                "other",
                name="suspensionreason",
            ),
            nullable=False,
        ),
        sa.Column("suspension_note", sa.Text(), nullable=True),
        sa.Column(
            "suspended_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reinstated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reinstated_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reinstatement_note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_index(
        "ix_corp_suspensions_account_id",
        "corporate_account_suspensions",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_suspensions_is_active",
        "corporate_account_suspensions",
        ["is_active"],
    )
    op.create_index(
        "ix_corp_suspensions_account_is_active",
        "corporate_account_suspensions",
        ["account_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_suspensions_account_is_active",
        table_name="corporate_account_suspensions",
    )
    op.drop_index(
        "ix_corp_suspensions_is_active",
        table_name="corporate_account_suspensions",
    )
    op.drop_index(
        "ix_corp_suspensions_account_id",
        table_name="corporate_account_suspensions",
    )
    op.drop_table("corporate_account_suspensions")

    sa.Enum(name="suspensionreason").drop(op.get_bind(), checkfirst=True)
