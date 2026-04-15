"""Corporate employee groups.

Enterprise admins create named groups of employees that cross org-chart
boundaries.  One employee can belong to many groups; groups do not have to
correspond to org structure.

Tables created:
  corporate_employee_groups    — one named group per corporate account.
  corporate_group_memberships  — many-to-many join: group ↔ account member.

Revision ID: q7r8s9t0u1v2
Revises:     p7q8r9s0t1u2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "q7r8s9t0u1v2"
down_revision: str = "p7q8r9s0t1u2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # corporate_employee_groups
    # ------------------------------------------------------------------
    op.create_table(
        "corporate_employee_groups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("color", sa.String(7), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "account_id",
            "name",
            name="uq_corp_employee_group_account_name",
        ),
    )

    op.create_index(
        "ix_corp_employee_group_account_id",
        "corporate_employee_groups",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_employee_group_account_active",
        "corporate_employee_groups",
        ["account_id", "is_active"],
        postgresql_where=sa.text("is_active = true"),
    )

    # ------------------------------------------------------------------
    # corporate_group_memberships
    # ------------------------------------------------------------------
    op.create_table(
        "corporate_group_memberships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("added_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["corporate_employee_groups.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["corporate_account_members.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["added_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "group_id",
            "member_id",
            name="uq_corp_group_membership_group_member",
        ),
    )

    op.create_index(
        "ix_corp_group_membership_group_id",
        "corporate_group_memberships",
        ["group_id"],
    )
    op.create_index(
        "ix_corp_group_membership_member_id",
        "corporate_group_memberships",
        ["member_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_group_membership_member_id",
        table_name="corporate_group_memberships",
    )
    op.drop_index(
        "ix_corp_group_membership_group_id",
        table_name="corporate_group_memberships",
    )
    op.drop_table("corporate_group_memberships")

    op.drop_index(
        "ix_corp_employee_group_account_active",
        table_name="corporate_employee_groups",
    )
    op.drop_index(
        "ix_corp_employee_group_account_id",
        table_name="corporate_employee_groups",
    )
    op.drop_table("corporate_employee_groups")
