"""Add corporate_recurring_rides and corporate_recurring_ride_bookings tables.

Employees configure personal recurring ride schedules (daily commute,
weekly airport transfer, monthly off-site meeting).  Booking records
track each scheduling attempt.

Tables created:
  corporate_recurring_rides         — named recurring-ride schedules
  corporate_recurring_ride_bookings — per-instance booking attempt log

Revision ID: u4v5w6x7y8z9
Revises:     s1t2u3v4w5x6
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "u4v5w6x7y8z9"
down_revision = "s1t2u3v4w5x6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ enums
    recurrencetype = postgresql.ENUM(
        "daily", "weekly", "monthly",
        name="recurrencetype",
        create_type=False,
    )
    recurrencetype.create(op.get_bind(), checkfirst=True)

    recurringridebookingstatus = postgresql.ENUM(
        "pending", "booked", "failed", "skipped",
        name="recurringrridebookingstatus",
        create_type=False,
    )
    recurringridebookingstatus.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------- corporate_recurring_rides
    op.create_table(
        "corporate_recurring_rides",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("pickup_address", sa.String(500), nullable=False),
        sa.Column("pickup_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("pickup_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("dropoff_address", sa.String(500), nullable=False),
        sa.Column("dropoff_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("dropoff_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("vehicle_type", sa.String(50), nullable=True),
        sa.Column(
            "recurrence_type",
            sa.Enum("daily", "weekly", "monthly", name="recurrencetype"),
            nullable=False,
        ),
        sa.Column(
            "days_of_week",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("day_of_month", sa.Integer, nullable=True),
        sa.Column("scheduled_time", sa.String(5), nullable=False),
        sa.Column("advance_booking_minutes", sa.Integer, nullable=False, server_default="60"),
        sa.Column(
            "cost_center_id",
            sa.Integer,
            sa.ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "trip_purpose_id",
            sa.Integer,
            sa.ForeignKey("corporate_trip_purposes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_corp_recurring_ride_account_id",
        "corporate_recurring_rides",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_recurring_ride_member_id",
        "corporate_recurring_rides",
        ["member_id"],
    )
    op.create_index(
        "ix_corp_recurring_ride_account_member",
        "corporate_recurring_rides",
        ["account_id", "member_id"],
    )
    op.create_index(
        "ix_corp_recurring_ride_account_active",
        "corporate_recurring_rides",
        ["account_id", "is_active"],
    )

    # ---------------------------------------- corporate_recurring_ride_bookings
    op.create_table(
        "corporate_recurring_ride_bookings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "recurring_ride_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corporate_recurring_rides.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ride_id",
            sa.Integer,
            sa.ForeignKey("rides.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "booked", "failed", "skipped",
                name="recurringrridebookingstatus",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("failure_reason", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_corp_rrb_recurring_ride_id",
        "corporate_recurring_ride_bookings",
        ["recurring_ride_id"],
    )
    op.create_index(
        "ix_corp_rrb_account_id",
        "corporate_recurring_ride_bookings",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_rrb_account_scheduled",
        "corporate_recurring_ride_bookings",
        ["account_id", "scheduled_for"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_rrb_account_scheduled",
        table_name="corporate_recurring_ride_bookings",
    )
    op.drop_index(
        "ix_corp_rrb_account_id",
        table_name="corporate_recurring_ride_bookings",
    )
    op.drop_index(
        "ix_corp_rrb_recurring_ride_id",
        table_name="corporate_recurring_ride_bookings",
    )
    op.drop_table("corporate_recurring_ride_bookings")

    op.drop_index(
        "ix_corp_recurring_ride_account_active",
        table_name="corporate_recurring_rides",
    )
    op.drop_index(
        "ix_corp_recurring_ride_account_member",
        table_name="corporate_recurring_rides",
    )
    op.drop_index(
        "ix_corp_recurring_ride_member_id",
        table_name="corporate_recurring_rides",
    )
    op.drop_index(
        "ix_corp_recurring_ride_account_id",
        table_name="corporate_recurring_rides",
    )
    op.drop_table("corporate_recurring_rides")

    op.execute("DROP TYPE IF EXISTS recurringrridebookingstatus")
    op.execute("DROP TYPE IF EXISTS recurrencetype")
