"""Add corporate_account_hierarchies table.

Enterprise accounts can define parent/child relationships with other corporate
accounts.  Use cases: a university managing department accounts, a corporation
with subsidiaries, or a franchise with location accounts.

Table created:
  corporate_account_hierarchies  — parent→child links between corporate accounts

Revision ID: v5w6x7y8z9a0
Revises:     u4v5w6x7y8z9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "v5w6x7y8z9a0"
down_revision = "u4v5w6x7y8z9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ enum
    hierarchyrelationshiptype = postgresql.ENUM(
        "subsidiary", "division", "franchise", "partner",
        name="hierarchyrelationshiptype",
        create_type=False,
    )
    hierarchyrelationshiptype.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------- corporate_account_hierarchies
    op.create_table(
        "corporate_account_hierarchies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "parent_account_id",
            sa.Integer,
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "child_account_id",
            sa.Integer,
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "relationship_type",
            sa.Enum(
                "subsidiary", "division", "franchise", "partner",
                name="hierarchyrelationshiptype",
            ),
            nullable=False,
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_by_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
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
        sa.UniqueConstraint(
            "parent_account_id",
            "child_account_id",
            name="uq_corp_hierarchy_parent_child",
        ),
    )

    op.create_index(
        "ix_corp_hierarchy_parent_id",
        "corporate_account_hierarchies",
        ["parent_account_id"],
    )
    op.create_index(
        "ix_corp_hierarchy_child_id",
        "corporate_account_hierarchies",
        ["child_account_id"],
    )
    op.create_index(
        "ix_corp_hierarchy_parent_active",
        "corporate_account_hierarchies",
        ["parent_account_id", "is_active"],
    )
    op.create_index(
        "ix_corp_hierarchy_child_active",
        "corporate_account_hierarchies",
        ["child_account_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_hierarchy_child_active",
        table_name="corporate_account_hierarchies",
    )
    op.drop_index(
        "ix_corp_hierarchy_parent_active",
        table_name="corporate_account_hierarchies",
    )
    op.drop_index(
        "ix_corp_hierarchy_child_id",
        table_name="corporate_account_hierarchies",
    )
    op.drop_index(
        "ix_corp_hierarchy_parent_id",
        table_name="corporate_account_hierarchies",
    )
    op.drop_table("corporate_account_hierarchies")
    op.execute("DROP TYPE IF EXISTS hierarchyrelationshiptype")
