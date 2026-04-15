"""Add corporate_billing_settings and corporate_payment_methods tables.

Corporate accounts configure how they are billed: billing address, tax ID,
PO number requirements, auto-pay preference, billing cycle, invoice email
recipients.  Payment instruments (cards, ACH, wire) are stored as separate
rows linked to the billing settings record.

Tables created:
  corporate_billing_settings  — one per corporate account (unique on account_id).
  corporate_payment_methods   — one or more payment instruments per account.

Enums created:
  billingcycle        — weekly / biweekly / monthly
  paymentmethodtype   — credit_card / debit_card / ach_bank_account / wire_transfer

Revision ID: s9t0u1v2w3x4
Revises:     r8s9t0u1v2w3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "s9t0u1v2w3x4"
down_revision: str = "r8s9t0u1v2w3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # Enums
    # -----------------------------------------------------------------------
    billing_cycle_enum = postgresql.ENUM(
        "weekly",
        "biweekly",
        "monthly",
        name="billingcycle",
        create_type=True,
    )
    billing_cycle_enum.create(op.get_bind(), checkfirst=True)

    payment_method_type_enum = postgresql.ENUM(
        "credit_card",
        "debit_card",
        "ach_bank_account",
        "wire_transfer",
        name="paymentmethodtype",
        create_type=True,
    )
    payment_method_type_enum.create(op.get_bind(), checkfirst=True)

    # -----------------------------------------------------------------------
    # corporate_billing_settings
    # -----------------------------------------------------------------------
    op.create_table(
        "corporate_billing_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("billing_company_name", sa.String(200), nullable=True),
        sa.Column("billing_address_line1", sa.String(200), nullable=True),
        sa.Column("billing_address_line2", sa.String(200), nullable=True),
        sa.Column("billing_city", sa.String(100), nullable=True),
        sa.Column("billing_state", sa.String(100), nullable=True),
        sa.Column("billing_postal_code", sa.String(20), nullable=True),
        sa.Column("billing_country", sa.String(2), nullable=True),
        sa.Column("tax_id", sa.String(50), nullable=True),
        sa.Column(
            "po_number_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("default_po_number", sa.String(100), nullable=True),
        sa.Column("invoice_memo_template", sa.Text(), nullable=True),
        sa.Column(
            "auto_pay_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "billing_cycle",
            sa.Enum(
                "weekly",
                "biweekly",
                "monthly",
                name="billingcycle",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'monthly'::billingcycle"),
        ),
        sa.Column("invoice_emails", postgresql.JSONB(), nullable=True),
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
            ["updated_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", name="uq_corp_billing_settings_account_id"),
    )

    op.create_index(
        "ix_corp_billing_settings_account_id",
        "corporate_billing_settings",
        ["account_id"],
    )

    # -----------------------------------------------------------------------
    # corporate_payment_methods
    # -----------------------------------------------------------------------
    op.create_table(
        "corporate_payment_methods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("billing_settings_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "payment_type",
            sa.Enum(
                "credit_card",
                "debit_card",
                "ach_bank_account",
                "wire_transfer",
                name="paymentmethodtype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("last_four", sa.String(4), nullable=True),
        sa.Column("cardholder_name", sa.String(200), nullable=True),
        sa.Column("bank_name", sa.String(200), nullable=True),
        sa.Column("external_payment_method_id", sa.String(200), nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
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
            ["billing_settings_id"],
            ["corporate_billing_settings.id"],
            ondelete="CASCADE",
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
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corp_payment_methods_billing_settings_id",
        "corporate_payment_methods",
        ["billing_settings_id"],
    )
    op.create_index(
        "ix_corp_payment_methods_account_id",
        "corporate_payment_methods",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_payment_methods_is_default",
        "corporate_payment_methods",
        ["account_id", "is_default"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_payment_methods_is_default",
        table_name="corporate_payment_methods",
    )
    op.drop_index(
        "ix_corp_payment_methods_account_id",
        table_name="corporate_payment_methods",
    )
    op.drop_index(
        "ix_corp_payment_methods_billing_settings_id",
        table_name="corporate_payment_methods",
    )
    op.drop_table("corporate_payment_methods")

    op.drop_index(
        "ix_corp_billing_settings_account_id",
        table_name="corporate_billing_settings",
    )
    op.drop_table("corporate_billing_settings")

    op.execute("DROP TYPE IF EXISTS paymentmethodtype")
    op.execute("DROP TYPE IF EXISTS billingcycle")
