"""Add corporate_account_contracts table.

Tracks the service agreement between the platform and a corporate client.
One contract can be active per account at a time; historical contracts are
retained for audit purposes.

Enums created:
  contractstatus — draft / active / expired / terminated

Table created:
  corporate_account_contracts

Revision ID: t0u1v2w3x4y5
Revises:     s9t0u1v2w3x4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "t0u1v2w3x4y5"
down_revision: str = "s9t0u1v2w3x4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # Enum
    # -----------------------------------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'contractstatus') THEN
                CREATE TYPE contractstatus AS ENUM ('draft', 'active', 'expired', 'terminated');
            END IF;
        END
        $$;
        """
    )

    # -----------------------------------------------------------------------
    # corporate_account_contracts
    # -----------------------------------------------------------------------
    op.create_table(
        "corporate_account_contracts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("contract_number", sa.String(50), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "active",
                "expired",
                "terminated",
                name="contractstatus",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'draft'::contractstatus"),
        ),
        sa.Column("contract_start_date", sa.Date(), nullable=False),
        sa.Column("contract_end_date", sa.Date(), nullable=True),
        sa.Column(
            "auto_renews",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("renewal_term_days", sa.Integer(), nullable=True),
        sa.Column(
            "renewal_notice_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("30"),
        ),
        sa.Column("committed_monthly_rides", sa.Integer(), nullable=True),
        sa.Column(
            "committed_monthly_spend_usd",
            sa.Numeric(precision=12, scale=2),
            nullable=True,
        ),
        sa.Column(
            "negotiated_discount_pct",
            sa.Numeric(precision=5, scale=2),
            nullable=True,
        ),
        sa.Column("account_manager_name", sa.String(200), nullable=True),
        sa.Column("account_manager_email", sa.String(200), nullable=True),
        sa.Column("contract_document_url", sa.String(500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("signed_by_name", sa.String(200), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("termination_reason", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("contract_number", name="uq_corp_contracts_number"),
    )

    op.create_index(
        "ix_corp_contracts_account_id",
        "corporate_account_contracts",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_contracts_status",
        "corporate_account_contracts",
        ["status"],
    )
    op.create_index(
        "ix_corp_contracts_account_status",
        "corporate_account_contracts",
        ["account_id", "status"],
    )
    op.create_index(
        "ix_corp_contracts_end_date",
        "corporate_account_contracts",
        ["contract_end_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_corp_contracts_end_date", table_name="corporate_account_contracts")
    op.drop_index(
        "ix_corp_contracts_account_status", table_name="corporate_account_contracts"
    )
    op.drop_index("ix_corp_contracts_status", table_name="corporate_account_contracts")
    op.drop_index(
        "ix_corp_contracts_account_id", table_name="corporate_account_contracts"
    )
    op.drop_table("corporate_account_contracts")
    op.execute("DROP TYPE IF EXISTS contractstatus")
