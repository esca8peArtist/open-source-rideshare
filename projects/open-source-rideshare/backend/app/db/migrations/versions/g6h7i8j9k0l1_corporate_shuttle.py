"""Add corporate shuttle routes and seat booking tables.

Enterprise accounts define fixed shuttle routes, attach recurring schedules to
each route, and employees book seats on specific run dates.

Tables created:
  corporate_shuttle_routes    — named fixed routes per account
  corporate_shuttle_schedules — recurring schedules attached to routes
  corporate_shuttle_bookings  — seat reservations per member per schedule+date

Revision ID: g6h7i8j9k0l1
Revises:     f5g6h7i8j9k0
Create Date: 2026-04-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "g6h7i8j9k0l1"
down_revision = "f5g6h7i8j9k0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- enums ----
    shuttlebookingstatus = postgresql.ENUM(
        "pending",
        "confirmed",
        "cancelled",
        "no_show",
        "completed",
        name="shuttlebookingstatus",
        create_type=False,
    )
    shuttlebookingstatus.create(op.get_bind(), checkfirst=True)

    # ---------------------------------------- corporate_shuttle_routes
    op.create_table(
        "corporate_shuttle_routes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("origin_name", sa.String(200), nullable=False),
        sa.Column("origin_address", sa.String(500), nullable=False),
        sa.Column("origin_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("origin_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("destination_name", sa.String(200), nullable=False),
        sa.Column("destination_address", sa.String(500), nullable=False),
        sa.Column("destination_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("destination_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("route_stops", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("default_capacity", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "name", name="uq_shuttle_route_account_name"
        ),
    )
    op.create_index(
        "ix_shuttle_route_account_id",
        "corporate_shuttle_routes",
        ["account_id"],
    )
    op.create_index(
        "ix_shuttle_route_is_active",
        "corporate_shuttle_routes",
        ["is_active"],
    )
    op.create_index(
        "ix_shuttle_route_created_at",
        "corporate_shuttle_routes",
        ["created_at"],
        postgresql_ops={"created_at": "DESC"},
    )

    # ---------------------------------------- corporate_shuttle_schedules
    op.create_table(
        "corporate_shuttle_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("schedule_name", sa.String(200), nullable=False),
        sa.Column("days_of_week", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("departure_time", sa.String(5), nullable=False),
        sa.Column("estimated_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("seat_capacity", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
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
            ["route_id"],
            ["corporate_shuttle_routes.id"],
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_shuttle_schedule_route_id",
        "corporate_shuttle_schedules",
        ["route_id"],
    )
    op.create_index(
        "ix_shuttle_schedule_account_id",
        "corporate_shuttle_schedules",
        ["account_id"],
    )
    op.create_index(
        "ix_shuttle_schedule_is_active",
        "corporate_shuttle_schedules",
        ["is_active"],
    )

    # ---------------------------------------- corporate_shuttle_bookings
    op.create_table(
        "corporate_shuttle_bookings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=True),
        sa.Column("booking_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "confirmed",
                "cancelled",
                "no_show",
                "completed",
                name="shuttlebookingstatus",
            ),
            nullable=False,
            server_default="confirmed",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_id", sa.Integer(), nullable=True),
        sa.Column("cancellation_reason", sa.String(500), nullable=True),
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
            ["schedule_id"],
            ["corporate_shuttle_schedules.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "schedule_id",
            "member_id",
            "booking_date",
            name="uq_shuttle_booking_schedule_member_date",
        ),
    )
    op.create_index(
        "ix_shuttle_booking_schedule_date",
        "corporate_shuttle_bookings",
        ["schedule_id", "booking_date"],
    )
    op.create_index(
        "ix_shuttle_booking_account_id",
        "corporate_shuttle_bookings",
        ["account_id"],
    )
    op.create_index(
        "ix_shuttle_booking_member_id",
        "corporate_shuttle_bookings",
        ["member_id"],
    )
    op.create_index(
        "ix_shuttle_booking_status",
        "corporate_shuttle_bookings",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("corporate_shuttle_bookings")
    op.drop_table("corporate_shuttle_schedules")
    op.drop_table("corporate_shuttle_routes")

    op.execute("DROP TYPE IF EXISTS shuttlebookingstatus")
