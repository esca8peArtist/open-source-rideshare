"""Add corporate_invoices_v2 table.

Monthly invoices aggregate completed rides billed to a corporate account
within a billing period.  Admins can generate, finalize, mark as paid, or
void invoices.

Tables created:
  corporate_invoices_v2 — one row per invoice per account

Revision ID: t2u3v4w5x6y7
Revises:     s2t3u4v5w6x7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "t2u3v4w5x6y7"
down_revision: str = "s2t3u4v5w6x7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the corp_invoice_status_v2 enum type
    corp_invoice_status_v2 = sa.Enum(
        "draft",
        "finalized",
        "paid",
        "void",
        name="corp_invoice_status_v2",
    )
    corp_invoice_status_v2.create(op.get_bind())

    op.create_table(
        "corporate_invoices_v2",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("invoice_number", sa.String(30), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "finalized", "paid", "void", name="corp_invoice_status_v2"),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("total_rides", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "subtotal_usd",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invoice_number", name="uq_corp_invoice_number"),
    )

    op.create_index(
        "ix_corp_invoices_account_id",
        "corporate_invoices_v2",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_invoices_status",
        "corporate_invoices_v2",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_corp_invoices_status", table_name="corporate_invoices_v2")
    op.drop_index("ix_corp_invoices_account_id", table_name="corporate_invoices_v2")
    op.drop_table("corporate_invoices_v2")

    # Drop the enum type
    sa.Enum(name="corp_invoice_status_v2").drop(op.get_bind())
