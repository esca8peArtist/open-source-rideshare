"""Corporate Fleet Toll & Transponder Management.

Fleet managers track toll transponders assigned to fleet vehicles and log
individual toll charges for cost analytics.

Tables created:
  corporate_fleet_toll_transponders — one record per transponder per vehicle
  corporate_fleet_toll_charges      — one record per individual toll charge

Revision ID: t9u0v1w2x3y4
Revises:     s8t9u0v1w2x3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "t9u0v1w2x3y4"
down_revision: str = "s8t9u0v1w2x3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Transponder provider enum
    op.execute(
        "CREATE TYPE transponderprovider AS ENUM ("
        "'ezpass', 'fastrak', 'sunpass', 'peach_pass', "
        "'ipass', 'ktag', 'pikepass', 'nc_quick_pass', 'other'"
        ")"
    )

    # Transponders table
    op.create_table(
        "corporate_fleet_toll_transponders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("fleet_vehicle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transponder_number", sa.String(100), nullable=False),
        sa.Column(
            "provider",
            sa.Enum(
                "ezpass",
                "fastrak",
                "sunpass",
                "peach_pass",
                "ipass",
                "ktag",
                "pikepass",
                "nc_quick_pass",
                "other",
                name="transponderprovider",
            ),
            nullable=False,
        ),
        sa.Column("assigned_date", sa.Date(), nullable=False),
        sa.Column("removed_date", sa.Date(), nullable=True),
        sa.Column("monthly_plan_cost_usd", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("toll_account_number", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("assigned_by_id", sa.Integer(), nullable=True),
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
            ["fleet_vehicle_id"],
            ["corporate_fleet_vehicles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "account_id",
            "transponder_number",
            name="uq_fleet_toll_transponder_account_number",
        ),
    )
    op.create_index(
        "ix_fleet_toll_transponder_account_id",
        "corporate_fleet_toll_transponders",
        ["account_id"],
    )
    op.create_index(
        "ix_fleet_toll_transponder_vehicle_id",
        "corporate_fleet_toll_transponders",
        ["fleet_vehicle_id"],
    )
    op.create_index(
        "ix_fleet_toll_transponder_is_active",
        "corporate_fleet_toll_transponders",
        ["is_active"],
    )

    # Toll charges table
    op.create_table(
        "corporate_fleet_toll_charges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("fleet_vehicle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transponder_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("charge_date", sa.Date(), nullable=False),
        sa.Column("plaza_name", sa.String(200), nullable=True),
        sa.Column("amount_usd", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("entry_location", sa.String(200), nullable=True),
        sa.Column("exit_location", sa.String(200), nullable=True),
        sa.Column("trip_purpose", sa.String(200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("logged_by_id", sa.Integer(), nullable=True),
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
            ["fleet_vehicle_id"],
            ["corporate_fleet_vehicles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transponder_id"],
            ["corporate_fleet_toll_transponders.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["logged_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_fleet_toll_charge_account_id",
        "corporate_fleet_toll_charges",
        ["account_id"],
    )
    op.create_index(
        "ix_fleet_toll_charge_vehicle_id",
        "corporate_fleet_toll_charges",
        ["fleet_vehicle_id"],
    )
    op.create_index(
        "ix_fleet_toll_charge_date",
        "corporate_fleet_toll_charges",
        ["charge_date"],
    )
    op.create_index(
        "ix_fleet_toll_charge_transponder_id",
        "corporate_fleet_toll_charges",
        ["transponder_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_fleet_toll_charge_transponder_id", table_name="corporate_fleet_toll_charges")
    op.drop_index("ix_fleet_toll_charge_date", table_name="corporate_fleet_toll_charges")
    op.drop_index("ix_fleet_toll_charge_vehicle_id", table_name="corporate_fleet_toll_charges")
    op.drop_index("ix_fleet_toll_charge_account_id", table_name="corporate_fleet_toll_charges")
    op.drop_table("corporate_fleet_toll_charges")

    op.drop_index("ix_fleet_toll_transponder_is_active", table_name="corporate_fleet_toll_transponders")
    op.drop_index("ix_fleet_toll_transponder_vehicle_id", table_name="corporate_fleet_toll_transponders")
    op.drop_index("ix_fleet_toll_transponder_account_id", table_name="corporate_fleet_toll_transponders")
    op.drop_table("corporate_fleet_toll_transponders")

    op.execute("DROP TYPE transponderprovider")
