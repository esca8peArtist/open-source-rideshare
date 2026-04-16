"""Corporate Fuel Card Management.

Fleet managers register company fuel cards, assign them to fleet vehicles
and/or drivers, set per-card monthly spending limits, and record fuel
transactions against each card.

Tables created:
  corporate_fuel_cards             — one row per company fuel card
  corporate_fuel_card_transactions — append-only transaction ledger

Revision ID: m2n3o4p5q6r7
Revises:     l1m2n3o4p5q6
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "m2n3o4p5q6r7"
down_revision: str = "l1m2n3o4p5q6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE cardnetwork AS ENUM (
            'visa',
            'mastercard',
            'fleet_card',
            'wex',
            'voyager',
            'other'
        )
        """
    )

    op.execute(
        """
        CREATE TYPE fueltype AS ENUM (
            'regular',
            'premium',
            'diesel',
            'electric',
            'other'
        )
        """
    )

    op.create_table(
        "corporate_fuel_cards",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("card_last_four", sa.String(4), nullable=False),
        sa.Column(
            "card_network",
            sa.Enum(
                "visa",
                "mastercard",
                "fleet_card",
                "wex",
                "voyager",
                "other",
                name="cardnetwork",
            ),
            nullable=False,
            server_default="other",
        ),
        sa.Column("nickname", sa.String(100), nullable=False),
        sa.Column("assigned_vehicle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_driver_id", sa.Integer(), nullable=True),
        sa.Column("monthly_limit_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("issued_by_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_vehicle_id"],
            ["corporate_fleet_vehicles.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_driver_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["issued_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )

    op.create_index(
        "ix_corp_fuel_card_account_id",
        "corporate_fuel_cards",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_fuel_card_is_active",
        "corporate_fuel_cards",
        ["account_id", "is_active"],
    )
    op.create_index(
        "ix_corp_fuel_card_vehicle_id",
        "corporate_fuel_cards",
        ["assigned_vehicle_id"],
    )
    op.create_index(
        "ix_corp_fuel_card_driver_id",
        "corporate_fuel_cards",
        ["assigned_driver_id"],
    )

    op.create_table(
        "corporate_fuel_card_transactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("fuel_card_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("merchant_name", sa.String(200), nullable=False),
        sa.Column(
            "fuel_type",
            sa.Enum(
                "regular",
                "premium",
                "diesel",
                "electric",
                "other",
                name="fueltype",
            ),
            nullable=False,
            server_default="other",
        ),
        sa.Column("gallons", sa.Numeric(8, 3), nullable=True),
        sa.Column("amount_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("odometer_miles", sa.Integer(), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("recorded_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["fuel_card_id"],
            ["corporate_fuel_cards.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )

    op.create_index(
        "ix_corp_fuel_txn_account_id",
        "corporate_fuel_card_transactions",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_fuel_txn_card_id",
        "corporate_fuel_card_transactions",
        ["fuel_card_id"],
    )
    op.create_index(
        "ix_corp_fuel_txn_date",
        "corporate_fuel_card_transactions",
        ["fuel_card_id", "transaction_date"],
    )
    op.create_index(
        "ix_corp_fuel_txn_acct_date",
        "corporate_fuel_card_transactions",
        ["account_id", "transaction_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_fuel_txn_acct_date",
        table_name="corporate_fuel_card_transactions",
    )
    op.drop_index(
        "ix_corp_fuel_txn_date",
        table_name="corporate_fuel_card_transactions",
    )
    op.drop_index(
        "ix_corp_fuel_txn_card_id",
        table_name="corporate_fuel_card_transactions",
    )
    op.drop_index(
        "ix_corp_fuel_txn_account_id",
        table_name="corporate_fuel_card_transactions",
    )
    op.drop_table("corporate_fuel_card_transactions")

    op.drop_index("ix_corp_fuel_card_driver_id", table_name="corporate_fuel_cards")
    op.drop_index("ix_corp_fuel_card_vehicle_id", table_name="corporate_fuel_cards")
    op.drop_index("ix_corp_fuel_card_is_active", table_name="corporate_fuel_cards")
    op.drop_index("ix_corp_fuel_card_account_id", table_name="corporate_fuel_cards")
    op.drop_table("corporate_fuel_cards")

    op.execute("DROP TYPE IF EXISTS fueltype")
    op.execute("DROP TYPE IF EXISTS cardnetwork")
