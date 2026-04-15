"""Add corporate_delegates table.

Enterprise assistants (executive assistants, office managers) can be granted the
ability to book rides on behalf of other employees (principals/executives).
Corporate admins manage delegations with configurable per-ride spend caps, optional
expiry dates, and history-view permissions.

Tables created:
  corporate_delegates  — one row per (account, principal, delegate) delegation

Revision ID: g7h8i9j0k1l2
Revises:     f6g7h8i9j0k1
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

revision = "g7h8i9j0k1l2"
down_revision = "f6g7h8i9j0k1"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "corporate_delegates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "principal_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column(
            "delegate_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column("can_book_rides", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("can_view_history", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("max_per_ride_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "account_id", "principal_id", "delegate_id", name="uq_corp_delegate"
        ),
    )
    op.create_index(
        "ix_corporate_delegates_account_id",
        "corporate_delegates",
        ["account_id"],
    )
    op.create_index(
        "ix_corporate_delegates_delegate_id",
        "corporate_delegates",
        ["delegate_id"],
    )
    op.create_index(
        "ix_corporate_delegates_principal_id",
        "corporate_delegates",
        ["principal_id"],
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    op.drop_index("ix_corporate_delegates_principal_id", table_name="corporate_delegates")
    op.drop_index("ix_corporate_delegates_delegate_id", table_name="corporate_delegates")
    op.drop_index("ix_corporate_delegates_account_id", table_name="corporate_delegates")
    op.drop_table("corporate_delegates")
