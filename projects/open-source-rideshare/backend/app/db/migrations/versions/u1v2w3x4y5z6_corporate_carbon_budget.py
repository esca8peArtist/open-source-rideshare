"""Add corporate_carbon_budgets table.

Corporate accounts can now set a monthly CO2 budget and track their
environmental footprint across all employee rides.  ESG reporting
surfaces this data for platform sustainability disclosures.

Table created:
  corporate_carbon_budgets — one row per corporate account (unique on account_id).

No new enum types: tracking_enabled and alert_threshold_pct use bool/int.

Revision ID: u1v2w3x4y5z6
Revises:     t0u1v2w3x4y5
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "u1v2w3x4y5z6"
down_revision: str = "t0u1v2w3x4y5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # corporate_carbon_budgets
    # -----------------------------------------------------------------------
    op.create_table(
        "corporate_carbon_budgets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "monthly_budget_co2_kg",
            sa.Numeric(precision=10, scale=2),
            nullable=True,
        ),
        sa.Column(
            "offset_budget_usd",
            sa.Numeric(precision=10, scale=2),
            nullable=True,
        ),
        sa.Column(
            "tracking_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "alert_threshold_pct",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("80"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.UniqueConstraint(
            "account_id",
            name="uq_corporate_carbon_budgets_account",
        ),
    )

    op.create_index(
        "ix_corporate_carbon_budgets_account_id",
        "corporate_carbon_budgets",
        ["account_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corporate_carbon_budgets_account_id",
        table_name="corporate_carbon_budgets",
    )
    op.drop_table("corporate_carbon_budgets")
