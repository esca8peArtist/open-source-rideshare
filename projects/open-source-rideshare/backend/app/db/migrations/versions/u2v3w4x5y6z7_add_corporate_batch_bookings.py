"""Add corporate_batch_bookings and corporate_batch_ride_requests tables.

Companies can create a batch booking (DRAFT), add individual ride requests,
then submit the batch for fulfilment.  This enables event shuttles, offsites,
and airport pickups for multiple passengers in one coordinated operation.

Tables created:
  corporate_batch_bookings       — one row per batch booking
  corporate_batch_ride_requests  — one row per ride request within a batch

Revision ID: u2v3w4x5y6z7
Revises:     t2u3v4w5x6y7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "u2v3w4x5y6z7"
down_revision: str = "t2u3v4w5x6y7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum types
    batch_booking_status = sa.Enum(
        "draft",
        "submitted",
        "cancelled",
        name="batchbookingstatus",
    )
    batch_booking_status.create(op.get_bind())

    batch_ride_quest_status = sa.Enum(
        "pending",
        "removed",
        name="batchridequeststatus",
    )
    batch_ride_quest_status.create(op.get_bind())

    # corporate_batch_bookings
    op.create_table(
        "corporate_batch_bookings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "submitted", "cancelled", name="batchbookingstatus"),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.String(300), nullable=True),
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
            ["created_by_user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corp_batch_bookings_account_id",
        "corporate_batch_bookings",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_batch_bookings_status",
        "corporate_batch_bookings",
        ["status"],
    )

    # corporate_batch_ride_requests
    op.create_table(
        "corporate_batch_ride_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("passenger_name", sa.String(150), nullable=False),
        sa.Column("passenger_email", sa.String(200), nullable=True),
        sa.Column("passenger_phone", sa.String(20), nullable=True),
        sa.Column("pickup_address", sa.String(300), nullable=False),
        sa.Column("pickup_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("pickup_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("dropoff_address", sa.String(300), nullable=False),
        sa.Column("dropoff_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("dropoff_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("requested_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.String(300), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "removed", name="batchridequeststatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["corporate_batch_bookings.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corp_batch_requests_batch_id",
        "corporate_batch_ride_requests",
        ["batch_id"],
    )
    op.create_index(
        "ix_corp_batch_requests_account_id",
        "corporate_batch_ride_requests",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_batch_requests_status",
        "corporate_batch_ride_requests",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_corp_batch_requests_status", table_name="corporate_batch_ride_requests")
    op.drop_index("ix_corp_batch_requests_account_id", table_name="corporate_batch_ride_requests")
    op.drop_index("ix_corp_batch_requests_batch_id", table_name="corporate_batch_ride_requests")
    op.drop_table("corporate_batch_ride_requests")

    op.drop_index("ix_corp_batch_bookings_status", table_name="corporate_batch_bookings")
    op.drop_index("ix_corp_batch_bookings_account_id", table_name="corporate_batch_bookings")
    op.drop_table("corporate_batch_bookings")

    sa.Enum(name="batchridequeststatus").drop(op.get_bind())
    sa.Enum(name="batchbookingstatus").drop(op.get_bind())
