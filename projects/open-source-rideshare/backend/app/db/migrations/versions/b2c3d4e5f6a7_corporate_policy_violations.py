"""Add corporate_policy_violations table.

Violations are append-only audit records written when an employee's corporate
ride booking breaks the account's ride policy.  Each row captures the
violation type, JSONB context, a snapshot of the policy that was in effect,
and acknowledgement state.

Tables created:
  corporate_policy_violations — one row per violation event.

Revision ID: b2c3d4e5f6a7
Revises:     a1b2c3d4e5f6
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "corporate_policy_violations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("ride_id", sa.Integer(), nullable=True),
        sa.Column("violation_type", sa.String(length=50), nullable=False),
        sa.Column(
            "violation_details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "policy_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "is_acknowledged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("acknowledged_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "acknowledged_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("acknowledgement_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
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
            ["member_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ride_id"],
            ["rides.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["acknowledged_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corp_policy_violation_account_id",
        "corporate_policy_violations",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_policy_violation_member_id",
        "corporate_policy_violations",
        ["member_id"],
    )
    op.create_index(
        "ix_corp_policy_violation_account_created",
        "corporate_policy_violations",
        ["account_id", "created_at"],
    )
    op.create_index(
        "ix_corp_policy_violation_unacked",
        "corporate_policy_violations",
        ["account_id", "is_acknowledged"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_policy_violation_unacked",
        table_name="corporate_policy_violations",
    )
    op.drop_index(
        "ix_corp_policy_violation_account_created",
        table_name="corporate_policy_violations",
    )
    op.drop_index(
        "ix_corp_policy_violation_member_id",
        table_name="corporate_policy_violations",
    )
    op.drop_index(
        "ix_corp_policy_violation_account_id",
        table_name="corporate_policy_violations",
    )
    op.drop_table("corporate_policy_violations")
