"""Add corporate_ride_templates table.

Corporate admins define named, reusable booking configurations — saved routes
with pre-filled pickup/dropoff addresses, preferred vehicle type, and default
cost centre / trip purpose.  Employees browse templates and get pre-filled
booking data when making a new ride request.

Tables created:
  corporate_ride_templates

Revision ID: m5n6o7p8q9r0
Revises:     l4m5n6o7p8q9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "m5n6o7p8q9r0"
down_revision = "l4m5n6o7p8q9"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "corporate_ride_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Pickup
        sa.Column("pickup_location_name", sa.String(200), nullable=False),
        sa.Column("pickup_address_line1", sa.String(200), nullable=True),
        sa.Column("pickup_address_line2", sa.String(200), nullable=True),
        sa.Column("pickup_city", sa.String(100), nullable=True),
        sa.Column("pickup_state", sa.String(100), nullable=True),
        sa.Column("pickup_country", sa.String(100), nullable=True),
        sa.Column("pickup_postal_code", sa.String(20), nullable=True),
        sa.Column("pickup_latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("pickup_longitude", sa.Numeric(9, 6), nullable=True),
        # Dropoff
        sa.Column("dropoff_location_name", sa.String(200), nullable=False),
        sa.Column("dropoff_address_line1", sa.String(200), nullable=True),
        sa.Column("dropoff_address_line2", sa.String(200), nullable=True),
        sa.Column("dropoff_city", sa.String(100), nullable=True),
        sa.Column("dropoff_state", sa.String(100), nullable=True),
        sa.Column("dropoff_country", sa.String(100), nullable=True),
        sa.Column("dropoff_postal_code", sa.String(20), nullable=True),
        sa.Column("dropoff_latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("dropoff_longitude", sa.Numeric(9, 6), nullable=True),
        # Booking defaults
        sa.Column("vehicle_type", sa.String(50), nullable=True),
        sa.Column("default_cost_center_id", sa.Integer(), nullable=True),
        sa.Column("default_trip_purpose_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
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
        # Constraints
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
            ["default_cost_center_id"],
            ["corporate_cost_centers.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["default_trip_purpose_id"],
            ["corporate_trip_purposes.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "name", name="uq_corp_ride_template_account_name"
        ),
    )

    # Indexes
    op.create_index(
        "ix_corp_ride_template_account_id",
        "corporate_ride_templates",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_ride_template_is_active",
        "corporate_ride_templates",
        ["is_active"],
    )
    op.create_index(
        "ix_corp_ride_template_use_count",
        "corporate_ride_templates",
        ["use_count"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_ride_template_use_count", table_name="corporate_ride_templates"
    )
    op.drop_index(
        "ix_corp_ride_template_is_active", table_name="corporate_ride_templates"
    )
    op.drop_index(
        "ix_corp_ride_template_account_id", table_name="corporate_ride_templates"
    )
    op.drop_table("corporate_ride_templates")
