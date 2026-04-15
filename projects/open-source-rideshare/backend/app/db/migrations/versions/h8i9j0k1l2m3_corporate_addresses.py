"""Add corporate_addresses table.

Enterprise accounts maintain a shared library of named locations — offices, client
sites, airports, hotels — that employees browse and select when booking rides.  Each
address can auto-tag rides with a default cost center and trip purpose, reducing
manual entry for common corporate destinations.

Tables created:
  corporate_addresses  — one row per named location per account

Revision ID: h8i9j0k1l2m3
Revises:     g7h8i9j0k1l2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

revision = "h8i9j0k1l2m3"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "corporate_addresses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Display name and street address components
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address_line_1", sa.String(500), nullable=False),
        sa.Column("address_line_2", sa.String(200), nullable=True),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("state", sa.String(100), nullable=False),
        sa.Column("zip_code", sa.String(20), nullable=True),
        sa.Column("country", sa.String(2), nullable=False, server_default="US"),
        # Geocoded coordinates
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        # Driver/rider instructions
        sa.Column("notes", sa.Text(), nullable=True),
        # Usage flags
        sa.Column(
            "is_pickup_point", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "is_dropoff_point", sa.Boolean(), nullable=False, server_default="true"
        ),
        # Optional auto-tagging defaults
        sa.Column(
            "default_cost_center_id",
            sa.Integer(),
            sa.ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "default_trip_purpose_id",
            sa.Integer(),
            sa.ForeignKey("corporate_trip_purposes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Lifecycle
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
    )

    op.create_index(
        "ix_corporate_addresses_account_id",
        "corporate_addresses",
        ["account_id"],
    )
    op.create_index(
        "ix_corporate_addresses_account_active",
        "corporate_addresses",
        ["account_id", "is_active"],
    )
    op.create_index(
        "ix_corporate_addresses_default_cost_center_id",
        "corporate_addresses",
        ["default_cost_center_id"],
    )
    op.create_index(
        "ix_corporate_addresses_default_trip_purpose_id",
        "corporate_addresses",
        ["default_trip_purpose_id"],
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    op.drop_index(
        "ix_corporate_addresses_default_trip_purpose_id",
        table_name="corporate_addresses",
    )
    op.drop_index(
        "ix_corporate_addresses_default_cost_center_id",
        table_name="corporate_addresses",
    )
    op.drop_index(
        "ix_corporate_addresses_account_active",
        table_name="corporate_addresses",
    )
    op.drop_index(
        "ix_corporate_addresses_account_id",
        table_name="corporate_addresses",
    )
    op.drop_table("corporate_addresses")
