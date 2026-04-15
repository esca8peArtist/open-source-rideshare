"""Create corporate_credit_accounts and corporate_credit_transactions tables.

Enterprise accounts can pre-load a credit balance drawn down per ride.
All movements are recorded in an append-only ledger.

Tables created:
  corporate_credit_accounts       — one row per account; tracks balance + totals.
  corporate_credit_transactions   — append-only ledger of all credit movements.

Enums created:
  credittransactiontype — deposit / deduction / refund / adjustment

Revision ID: l3m4n5o6p7q8
Revises:     k2l3m4n5o6p7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "l3m4n5o6p7q8"
down_revision: str = "k2l3m4n5o6p7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum
    credittransactiontype = postgresql.ENUM(
        "deposit", "deduction", "refund", "adjustment",
        name="credittransactiontype",
    )
    credittransactiontype.create(op.get_bind(), checkfirst=True)

    # corporate_credit_accounts
    op.create_table(
        "corporate_credit_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "balance_usd",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "total_deposited_usd",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "total_spent_usd",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "total_refunded_usd",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column("low_balance_threshold_usd", sa.Numeric(10, 2), nullable=True),
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
        sa.UniqueConstraint("account_id", name="uq_corp_credit_account"),
    )

    op.create_index(
        "ix_corp_credit_accts_account_id",
        "corporate_credit_accounts",
        ["account_id"],
        unique=True,
    )
    op.create_index(
        "ix_corp_credit_accts_low_balance",
        "corporate_credit_accounts",
        ["balance_usd", "low_balance_threshold_usd"],
    )

    # corporate_credit_transactions
    op.create_table(
        "corporate_credit_transactions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("credit_account_id", sa.Integer(), nullable=False),
        sa.Column(
            "transaction_type",
            sa.Enum(
                "deposit", "deduction", "refund", "adjustment",
                name="credittransactiontype",
            ),
            nullable=False,
        ),
        sa.Column("amount_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("balance_after_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("reference_id", sa.Text(), nullable=True),
        sa.Column("reference_type", sa.Text(), nullable=True),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
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
            ["credit_account_id"],
            ["corporate_credit_accounts.id"],
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
        "ix_corp_credit_txns_account_id",
        "corporate_credit_transactions",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_credit_txns_credit_account_id",
        "corporate_credit_transactions",
        ["credit_account_id"],
    )
    op.create_index(
        "ix_corp_credit_txns_type",
        "corporate_credit_transactions",
        ["transaction_type"],
    )
    op.create_index(
        "ix_corp_credit_txns_account_created",
        "corporate_credit_transactions",
        ["account_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_corp_credit_txns_account_created",
                  table_name="corporate_credit_transactions")
    op.drop_index("ix_corp_credit_txns_type",
                  table_name="corporate_credit_transactions")
    op.drop_index("ix_corp_credit_txns_credit_account_id",
                  table_name="corporate_credit_transactions")
    op.drop_index("ix_corp_credit_txns_account_id",
                  table_name="corporate_credit_transactions")
    op.drop_table("corporate_credit_transactions")

    op.drop_index("ix_corp_credit_accts_low_balance",
                  table_name="corporate_credit_accounts")
    op.drop_index("ix_corp_credit_accts_account_id",
                  table_name="corporate_credit_accounts")
    op.drop_table("corporate_credit_accounts")

    sa.Enum(name="credittransactiontype").drop(op.get_bind(), checkfirst=True)
