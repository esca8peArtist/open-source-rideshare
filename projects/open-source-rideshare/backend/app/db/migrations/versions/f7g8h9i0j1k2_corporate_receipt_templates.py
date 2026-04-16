"""Add corporate receipt templates table.

Finance feature: corporate accounts define a custom receipt template applied
to all ride receipts for their employees.  Finance and admin teams can brand
receipts with company name/logo, add reference prefixes, include footer notes,
toggle driver details/route map visibility, and attach custom line items.

Table created:
  corporate_receipt_templates

Revision ID: f7g8h9i0j1k2
Revises:     e6f7a8b9c0d1
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "f7g8h9i0j1k2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "corporate_receipt_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=True),
        sa.Column("logo_url", sa.String(length=500), nullable=True),
        sa.Column("header_message", sa.Text(), nullable=True),
        sa.Column("footer_message", sa.Text(), nullable=True),
        sa.Column("reference_prefix", sa.String(length=20), nullable=True),
        sa.Column(
            "show_driver_details",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "show_route_map",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "custom_line_items",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            name="uq_corp_receipt_template_account_id",
        ),
    )

    op.create_index(
        "ix_corp_receipt_template_account_id",
        "corporate_receipt_templates",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_receipt_template_is_active",
        "corporate_receipt_templates",
        ["account_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_receipt_template_is_active",
        table_name="corporate_receipt_templates",
    )
    op.drop_index(
        "ix_corp_receipt_template_account_id",
        table_name="corporate_receipt_templates",
    )
    op.drop_table("corporate_receipt_templates")
