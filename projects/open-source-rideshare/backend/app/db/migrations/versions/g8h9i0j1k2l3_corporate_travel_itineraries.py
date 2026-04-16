"""Add corporate travel itineraries tables.

Employees create named business trips that group multiple rides for
consolidated expense reporting.

Tables created:
  corporate_travel_itineraries
  corporate_itinerary_rides

Revision ID: g8h9i0j1k2l3
Revises:     f7g8h9i0j1k2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "g8h9i0j1k2l3"
down_revision = "f7g8h9i0j1k2"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "corporate_travel_itineraries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("cost_center_id", sa.Integer(), nullable=True),
        sa.Column("trip_purpose_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
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
            ["cost_center_id"],
            ["corporate_cost_centers.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["trip_purpose_id"],
            ["corporate_trip_purposes.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corp_itinerary_account_id",
        "corporate_travel_itineraries",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_itinerary_created_by",
        "corporate_travel_itineraries",
        ["created_by_id"],
    )
    op.create_index(
        "ix_corp_itinerary_status",
        "corporate_travel_itineraries",
        ["account_id", "status"],
    )
    op.create_index(
        "ix_corp_itinerary_active",
        "corporate_travel_itineraries",
        ["account_id", "is_active"],
    )

    op.create_table(
        "corporate_itinerary_rides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("itinerary_id", sa.Integer(), nullable=False),
        sa.Column("ride_id", sa.Integer(), nullable=True),
        sa.Column("added_by_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["itinerary_id"],
            ["corporate_travel_itineraries.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ride_id"],
            ["rides.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["added_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("itinerary_id", "ride_id", name="uq_itinerary_ride"),
    )

    op.create_index(
        "ix_itinerary_ride_itinerary",
        "corporate_itinerary_rides",
        ["itinerary_id"],
    )
    op.create_index(
        "ix_itinerary_ride_ride",
        "corporate_itinerary_rides",
        ["ride_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_itinerary_ride_ride", table_name="corporate_itinerary_rides")
    op.drop_index(
        "ix_itinerary_ride_itinerary", table_name="corporate_itinerary_rides"
    )
    op.drop_table("corporate_itinerary_rides")

    op.drop_index(
        "ix_corp_itinerary_active", table_name="corporate_travel_itineraries"
    )
    op.drop_index(
        "ix_corp_itinerary_status", table_name="corporate_travel_itineraries"
    )
    op.drop_index(
        "ix_corp_itinerary_created_by", table_name="corporate_travel_itineraries"
    )
    op.drop_index(
        "ix_corp_itinerary_account_id", table_name="corporate_travel_itineraries"
    )
    op.drop_table("corporate_travel_itineraries")
