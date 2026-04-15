"""Add corporate business accounts tables.

Tables created:
  corporate_accounts_v2   — company-level billing accounts with status and budget
  corporate_account_members — employee memberships with role-based access
  corporate_invoices      — periodic billing invoices per account

Indexes added on account_id, user_id, status, and role for efficient querying.

Revision ID: d5e6f7g8h9i0
Revises: a2b3c4d5e6f7
Create Date: 2026-04-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d5e6f7g8h9i0"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------------
    account_status_enum = sa.Enum(
        "pending", "active", "suspended", "cancelled",
        name="corporateaccountstatus",
    )
    account_status_enum.create(op.get_bind(), checkfirst=True)

    member_role_enum = sa.Enum(
        "admin", "member",
        name="memberrole",
    )
    member_role_enum.create(op.get_bind(), checkfirst=True)

    invoice_status_enum = sa.Enum(
        "draft", "issued", "paid", "overdue",
        name="invoicestatus",
    )
    invoice_status_enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # corporate_accounts_v2
    # ------------------------------------------------------------------
    op.create_table(
        "corporate_accounts_v2",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("tax_id", sa.String(100), nullable=True),
        sa.Column("billing_email", sa.String(254), nullable=False),
        sa.Column("billing_address", sa.String(500), nullable=True),
        sa.Column("status", account_status_enum, nullable=False, server_default="pending"),
        sa.Column("monthly_budget_limit", sa.Numeric(12, 2), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corporate_accounts_v2_status",
        "corporate_accounts_v2",
        ["status"],
    )

    # ------------------------------------------------------------------
    # corporate_account_members
    # ------------------------------------------------------------------
    op.create_table(
        "corporate_account_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", member_role_enum, nullable=False, server_default="member"),
        sa.Column("monthly_spend_limit", sa.Numeric(12, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["corporate_accounts_v2.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "user_id", name="uq_corp_member_account_user"),
    )

    op.create_index(
        "ix_corporate_account_members_account_id",
        "corporate_account_members",
        ["account_id"],
    )
    op.create_index(
        "ix_corporate_account_members_user_id",
        "corporate_account_members",
        ["user_id"],
    )
    op.create_index(
        "ix_corporate_account_members_role",
        "corporate_account_members",
        ["role"],
    )

    # ------------------------------------------------------------------
    # corporate_invoices
    # ------------------------------------------------------------------
    op.create_table(
        "corporate_invoices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("billing_period_start", sa.Date(), nullable=False),
        sa.Column("billing_period_end", sa.Date(), nullable=False),
        sa.Column("total_rides", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "total_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column("status", invoice_status_enum, nullable=False, server_default="draft"),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["corporate_accounts_v2.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corporate_invoices_account_id",
        "corporate_invoices",
        ["account_id"],
    )
    op.create_index(
        "ix_corporate_invoices_status",
        "corporate_invoices",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_corporate_invoices_status", "corporate_invoices")
    op.drop_index("ix_corporate_invoices_account_id", "corporate_invoices")
    op.drop_table("corporate_invoices")

    op.drop_index("ix_corporate_account_members_role", "corporate_account_members")
    op.drop_index("ix_corporate_account_members_user_id", "corporate_account_members")
    op.drop_index("ix_corporate_account_members_account_id", "corporate_account_members")
    op.drop_table("corporate_account_members")

    op.drop_index("ix_corporate_accounts_v2_status", "corporate_accounts_v2")
    op.drop_table("corporate_accounts_v2")

    sa.Enum(name="invoicestatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="memberrole").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="corporateaccountstatus").drop(op.get_bind(), checkfirst=True)
