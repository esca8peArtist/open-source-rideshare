"""Add corporate_account_notes table.

Platform admins can annotate corporate accounts with CRM-style freeform notes.
Each note has a type label (general/billing/support/compliance/sales/technical),
a pin flag (pinned notes sort first in list responses), and an internal flag
that controls whether account members can view the note.

Tables created:
  corporate_account_notes — one row per note.

Revision ID: y4z5a6b7c8d9
Revises:     x3y4z5a6b7c8
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "y4z5a6b7c8d9"
down_revision = "x3y4z5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. NoteType enum
    # ------------------------------------------------------------------
    notetype = postgresql.ENUM(
        "general",
        "billing",
        "support",
        "compliance",
        "sales",
        "technical",
        name="notetype",
    )
    notetype.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # 2. corporate_account_notes table
    # ------------------------------------------------------------------
    op.create_table(
        "corporate_account_notes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "note_type",
            postgresql.ENUM(
                "general",
                "billing",
                "support",
                "compliance",
                "sales",
                "technical",
                name="notetype",
                create_type=False,
            ),
            nullable=False,
            server_default="general",
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_internal", sa.Boolean(), nullable=False, server_default="true"),
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

    # ------------------------------------------------------------------
    # 3. Indexes
    # ------------------------------------------------------------------
    op.create_index("ix_corp_note_account_id", "corporate_account_notes", ["account_id"])
    op.create_index("ix_corp_note_author_id", "corporate_account_notes", ["author_id"])
    op.create_index(
        "ix_corp_note_account_pinned",
        "corporate_account_notes",
        ["account_id", "is_pinned"],
    )
    op.create_index("ix_corp_note_created_at", "corporate_account_notes", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_corp_note_created_at", table_name="corporate_account_notes")
    op.drop_index("ix_corp_note_account_pinned", table_name="corporate_account_notes")
    op.drop_index("ix_corp_note_author_id", table_name="corporate_account_notes")
    op.drop_index("ix_corp_note_account_id", table_name="corporate_account_notes")
    op.drop_table("corporate_account_notes")

    op.execute("DROP TYPE IF EXISTS notetype")
