"""Add corporate_ride_approvals table.

Employees can request pre-booking approval from their corporate account admin
before charging a ride to the company account.  Each approved request carries
a unique code that is verified at booking time.

Approval lifecycle:
  pending → approved → used
  pending → denied
  pending → cancelled (by requester)
  approved → expired (if not used before expires_at)

Table created:
  corporate_ride_approvals — one row per approval request

Revision ID: r2s3t4u5v6w7
Revises:     q2r3s4t5u6v7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "r2s3t4u5v6w7"
down_revision: str = "q2r3s4t5u6v7"
branch_labels = None
depends_on = None

_STATUS_ENUM = "approvalstatus"
_STATUS_VALUES = ("pending", "approved", "denied", "expired", "cancelled", "used")


def upgrade() -> None:
    # Create the enum type
    op.execute(
        f"CREATE TYPE {_STATUS_ENUM} AS ENUM ("
        + ", ".join(f"'{v}'" for v in _STATUS_VALUES)
        + ")"
    )

    op.create_table(
        "corporate_ride_approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("requester_user_id", sa.Integer(), nullable=False),
        sa.Column("approved_by_user_id", sa.Integer(), nullable=True),
        # Request details
        sa.Column("purpose", sa.String(200), nullable=True),
        sa.Column("destination_description", sa.String(300), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(10, 2), nullable=True),
        # Approval state
        sa.Column(
            "status",
            sa.Enum(*_STATUS_VALUES, name=_STATUS_ENUM, create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("approval_code", sa.String(64), nullable=False),
        sa.Column("max_cost_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        # Review
        sa.Column("review_note", sa.String(300), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        # Usage
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        # Timestamps
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Constraints
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["requester_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("approval_code", name="uq_corp_ride_approval_code"),
    )

    # Indexes for common query patterns
    op.create_index(
        "ix_corp_ride_approvals_account_id",
        "corporate_ride_approvals",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_ride_approvals_requester",
        "corporate_ride_approvals",
        ["requester_user_id"],
    )
    op.create_index(
        "ix_corp_ride_approvals_status",
        "corporate_ride_approvals",
        ["status"],
    )
    op.create_index(
        "ix_corp_ride_approvals_code",
        "corporate_ride_approvals",
        ["approval_code"],
    )


def downgrade() -> None:
    op.drop_index("ix_corp_ride_approvals_code", table_name="corporate_ride_approvals")
    op.drop_index(
        "ix_corp_ride_approvals_status", table_name="corporate_ride_approvals"
    )
    op.drop_index(
        "ix_corp_ride_approvals_requester", table_name="corporate_ride_approvals"
    )
    op.drop_index(
        "ix_corp_ride_approvals_account_id", table_name="corporate_ride_approvals"
    )
    op.drop_table("corporate_ride_approvals")
    op.execute(f"DROP TYPE {_STATUS_ENUM}")
