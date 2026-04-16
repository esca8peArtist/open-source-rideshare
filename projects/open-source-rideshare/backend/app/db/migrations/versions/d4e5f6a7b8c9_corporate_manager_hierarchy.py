"""Add corporate manager relationships table.

Adds a table supporting employee→manager reporting relationships within a
corporate account.  Supports two relationship types (direct / dotted_line)
with soft-delete and cycle-prevention at the service layer.

Table created:
  corporate_manager_relationships

Revision ID: d4e5f6a7b8c9
Revises:     c3d4e5f6a7b8
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "corporate_manager_relationships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("employee_member_id", sa.Integer(), nullable=False),
        sa.Column("manager_member_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "relationship_type",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'direct'"),
        ),
        sa.Column("notes", sa.String(length=300), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
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
        sa.CheckConstraint(
            "employee_member_id != manager_member_id",
            name="ck_corp_mgr_rel_no_self_report",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["employee_member_id"],
            ["corporate_account_members.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["manager_member_id"],
            ["corporate_account_members.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "employee_member_id",
            "manager_member_id",
            name="uq_corp_mgr_rel_employee_manager",
        ),
    )

    op.create_index(
        "ix_corp_mgr_rel_account_id",
        "corporate_manager_relationships",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_mgr_rel_employee_member_id",
        "corporate_manager_relationships",
        ["employee_member_id"],
    )
    op.create_index(
        "ix_corp_mgr_rel_manager_member_id",
        "corporate_manager_relationships",
        ["manager_member_id"],
    )
    op.create_index(
        "ix_corp_mgr_rel_account_active",
        "corporate_manager_relationships",
        ["account_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_mgr_rel_account_active",
        table_name="corporate_manager_relationships",
    )
    op.drop_index(
        "ix_corp_mgr_rel_manager_member_id",
        table_name="corporate_manager_relationships",
    )
    op.drop_index(
        "ix_corp_mgr_rel_employee_member_id",
        table_name="corporate_manager_relationships",
    )
    op.drop_index(
        "ix_corp_mgr_rel_account_id",
        table_name="corporate_manager_relationships",
    )
    op.drop_table("corporate_manager_relationships")
