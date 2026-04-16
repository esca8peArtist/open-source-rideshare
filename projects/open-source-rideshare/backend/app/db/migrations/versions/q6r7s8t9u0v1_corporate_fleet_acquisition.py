"""Corporate Fleet Vehicle Acquisition and Disposal Tracking.

Fleet managers record how vehicles entered the fleet (purchased, leased,
financed, donated) and how vehicles leave it (sold, scrapped, lease returned, etc.).

Tables created:
  corporate_fleet_vehicle_acquisitions — financial acquisition record per vehicle
  corporate_fleet_vehicle_disposals    — disposal record for retired vehicles

Revision ID: q6r7s8t9u0v1
Revises:     p5q6r7s8t9u0
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "q6r7s8t9u0v1"
down_revision: str = "p5q6r7s8t9u0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE acquisitiontype AS ENUM (
            'purchased',
            'leased',
            'financed',
            'donated',
            'other'
        )
        """
    )

    op.execute(
        """
        CREATE TYPE disposalreason AS ENUM (
            'sold',
            'traded_in',
            'scrapped',
            'donated',
            'lease_returned',
            'stolen_written_off',
            'other'
        )
        """
    )

    op.create_table(
        "corporate_fleet_vehicle_acquisitions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "fleet_vehicle_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "acquisition_type",
            sa.Enum(
                "purchased",
                "leased",
                "financed",
                "donated",
                "other",
                name="acquisitiontype",
            ),
            nullable=False,
        ),
        sa.Column("vendor_name", sa.String(200), nullable=True),
        sa.Column("acquisition_date", sa.Date(), nullable=False),
        sa.Column("acquisition_cost_usd", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("lease_start_date", sa.Date(), nullable=True),
        sa.Column("lease_end_date", sa.Date(), nullable=True),
        sa.Column("monthly_lease_payment_usd", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("lease_mileage_allowance_annual", sa.Integer(), nullable=True),
        sa.Column("financed_amount_usd", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("loan_term_months", sa.Integer(), nullable=True),
        sa.Column("monthly_loan_payment_usd", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            ["fleet_vehicle_id"],
            ["corporate_fleet_vehicles.id"],
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
    )

    op.create_index(
        "ix_fleet_acquisition_account_id",
        "corporate_fleet_vehicle_acquisitions",
        ["account_id"],
    )
    op.create_index(
        "ix_fleet_acquisition_vehicle_id",
        "corporate_fleet_vehicle_acquisitions",
        ["fleet_vehicle_id"],
    )
    op.create_index(
        "ix_fleet_acquisition_type",
        "corporate_fleet_vehicle_acquisitions",
        ["acquisition_type"],
    )
    op.create_index(
        "ix_fleet_acquisition_is_active",
        "corporate_fleet_vehicle_acquisitions",
        ["is_active"],
    )

    op.create_table(
        "corporate_fleet_vehicle_disposals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "fleet_vehicle_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "disposal_reason",
            sa.Enum(
                "sold",
                "traded_in",
                "scrapped",
                "donated",
                "lease_returned",
                "stolen_written_off",
                "other",
                name="disposalreason",
            ),
            nullable=False,
        ),
        sa.Column("disposal_date", sa.Date(), nullable=False),
        sa.Column("sale_price_usd", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("buyer_name", sa.String(200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("disposed_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["fleet_vehicle_id"],
            ["corporate_fleet_vehicles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["disposed_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )

    op.create_index(
        "ix_fleet_disposal_account_id",
        "corporate_fleet_vehicle_disposals",
        ["account_id"],
    )
    op.create_index(
        "ix_fleet_disposal_vehicle_id",
        "corporate_fleet_vehicle_disposals",
        ["fleet_vehicle_id"],
    )
    op.create_index(
        "ix_fleet_disposal_reason",
        "corporate_fleet_vehicle_disposals",
        ["disposal_reason"],
    )
    op.create_index(
        "ix_fleet_disposal_date",
        "corporate_fleet_vehicle_disposals",
        ["disposal_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fleet_disposal_date",
        table_name="corporate_fleet_vehicle_disposals",
    )
    op.drop_index(
        "ix_fleet_disposal_reason",
        table_name="corporate_fleet_vehicle_disposals",
    )
    op.drop_index(
        "ix_fleet_disposal_vehicle_id",
        table_name="corporate_fleet_vehicle_disposals",
    )
    op.drop_index(
        "ix_fleet_disposal_account_id",
        table_name="corporate_fleet_vehicle_disposals",
    )
    op.drop_table("corporate_fleet_vehicle_disposals")

    op.drop_index(
        "ix_fleet_acquisition_is_active",
        table_name="corporate_fleet_vehicle_acquisitions",
    )
    op.drop_index(
        "ix_fleet_acquisition_type",
        table_name="corporate_fleet_vehicle_acquisitions",
    )
    op.drop_index(
        "ix_fleet_acquisition_vehicle_id",
        table_name="corporate_fleet_vehicle_acquisitions",
    )
    op.drop_index(
        "ix_fleet_acquisition_account_id",
        table_name="corporate_fleet_vehicle_acquisitions",
    )
    op.drop_table("corporate_fleet_vehicle_acquisitions")

    op.execute("DROP TYPE IF EXISTS disposalreason")
    op.execute("DROP TYPE IF EXISTS acquisitiontype")
