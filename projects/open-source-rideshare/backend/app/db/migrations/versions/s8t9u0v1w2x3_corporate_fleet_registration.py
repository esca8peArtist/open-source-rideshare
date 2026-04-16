"""Corporate Fleet Vehicle Registration Tracking.

Fleet managers track state/jurisdiction registration records for company
vehicles with expiry date alerts.

Tables created:
  corporate_fleet_vehicle_registrations — one record per registration per vehicle

Revision ID: s8t9u0v1w2x3
Revises:     r7s8t9u0v1w2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "s8t9u0v1w2x3"
down_revision: str = "r7s8t9u0v1w2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corporate_fleet_vehicle_registrations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "fleet_vehicle_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("registration_number", sa.String(100), nullable=False),
        sa.Column("registration_state", sa.String(100), nullable=False),
        sa.Column("registration_date", sa.Date(), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=False),
        sa.Column("annual_fee_usd", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("registered_owner_name", sa.String(200), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
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
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "account_id",
            "registration_number",
            name="uq_fleet_registration_account_reg_number",
        ),
    )

    op.create_index(
        "ix_fleet_registration_account_id",
        "corporate_fleet_vehicle_registrations",
        ["account_id"],
    )
    op.create_index(
        "ix_fleet_registration_vehicle_id",
        "corporate_fleet_vehicle_registrations",
        ["fleet_vehicle_id"],
    )
    op.create_index(
        "ix_fleet_registration_expiration_date",
        "corporate_fleet_vehicle_registrations",
        ["expiration_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fleet_registration_expiration_date",
        table_name="corporate_fleet_vehicle_registrations",
    )
    op.drop_index(
        "ix_fleet_registration_vehicle_id",
        table_name="corporate_fleet_vehicle_registrations",
    )
    op.drop_index(
        "ix_fleet_registration_account_id",
        table_name="corporate_fleet_vehicle_registrations",
    )
    op.drop_table("corporate_fleet_vehicle_registrations")
