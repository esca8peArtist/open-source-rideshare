"""Add corporate_account_tags table.

Platform admins label corporate accounts with short slugified tags
(e.g. ``vip``, ``at-risk``, ``healthcare``, ``government``) for internal
classification and cross-account filtering.  Tags are ad-hoc strings with
no separate registry.

Tables created:
  corporate_account_tags — one row per (account, tag) pair.

Revision ID: z5a6b7c8d9e0
Revises:     y4z5a6b7c8d9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "z5a6b7c8d9e0"
down_revision = "y4z5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. corporate_account_tags table
    # ------------------------------------------------------------------
    op.create_table(
        "corporate_account_tags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tag", sa.String(50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------
    # 2. Unique constraint + indexes
    # ------------------------------------------------------------------
    op.create_unique_constraint(
        "uq_corp_tag_account_tag",
        "corporate_account_tags",
        ["account_id", "tag"],
    )
    op.create_index("ix_corp_tag_account_id", "corporate_account_tags", ["account_id"])
    op.create_index("ix_corp_tag_tag", "corporate_account_tags", ["tag"])
    op.create_index("ix_corp_tag_created_by_id", "corporate_account_tags", ["created_by_id"])


def downgrade() -> None:
    op.drop_index("ix_corp_tag_created_by_id", table_name="corporate_account_tags")
    op.drop_index("ix_corp_tag_tag", table_name="corporate_account_tags")
    op.drop_index("ix_corp_tag_account_id", table_name="corporate_account_tags")
    op.drop_constraint("uq_corp_tag_account_tag", "corporate_account_tags", type_="unique")
    op.drop_table("corporate_account_tags")
