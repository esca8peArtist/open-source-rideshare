"""Add corporate_billing_currencies and corporate_invoice_fx_snapshots tables.

Corporate accounts operating internationally can configure a preferred billing
currency.  When invoices are issued in a non-USD currency, an FX rate snapshot
is recorded for audit.

Tables created:
  corporate_billing_currencies     — one record per corporate account
  corporate_invoice_fx_snapshots   — one record per non-USD invoice

Revision ID: a0b1c2d3e4f5
Revises:     z9a0b1c2d3e4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a0b1c2d3e4f5"
down_revision = "z9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------- corporate_billing_currencies
    op.create_table(
        "corporate_billing_currencies",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("billing_currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("auto_convert_invoices", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("preferred_fx_provider", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
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
        sa.UniqueConstraint("account_id", name="uq_corp_billing_currency_account"),
    )
    op.create_index(
        "ix_corp_billing_currency_account_id",
        "corporate_billing_currencies",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_billing_currency_code",
        "corporate_billing_currencies",
        ["billing_currency"],
    )

    # ---------------------------------------- corporate_invoice_fx_snapshots
    op.create_table(
        "corporate_invoice_fx_snapshots",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "invoice_id",
            sa.Integer(),
            sa.ForeignKey("corporate_invoices_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("target_currency", sa.String(3), nullable=False),
        sa.Column("exchange_rate", sa.Numeric(16, 8), nullable=False),
        sa.Column("rate_captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rate_source", sa.String(100), nullable=True),
        sa.Column("original_amount_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("converted_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("invoice_id", name="uq_corp_invoice_fx_snapshot"),
    )
    op.create_index(
        "ix_corp_fx_snapshot_invoice_id",
        "corporate_invoice_fx_snapshots",
        ["invoice_id"],
    )
    op.create_index(
        "ix_corp_fx_snapshot_account_id",
        "corporate_invoice_fx_snapshots",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_fx_snapshot_target_currency",
        "corporate_invoice_fx_snapshots",
        ["target_currency"],
    )


def downgrade() -> None:
    op.drop_table("corporate_invoice_fx_snapshots")
    op.drop_table("corporate_billing_currencies")
