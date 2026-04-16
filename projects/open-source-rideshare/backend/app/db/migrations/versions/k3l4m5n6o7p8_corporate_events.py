"""Add corporate_events and corporate_event_attendees tables.

Enterprise coordinators organize company events (team offsites, conferences,
client dinners, holiday parties), invite employees, and link rides for
consolidated billing.

Tables created:
  corporate_events
  corporate_event_attendees

Revision ID: k3l4m5n6o7p8
Revises:     i0j1k2l3m4n5
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "k3l4m5n6o7p8"
down_revision = "i0j1k2l3m4n5"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "corporate_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("organizer_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("event_location_name", sa.String(length=200), nullable=False),
        sa.Column("event_address_line1", sa.String(length=200), nullable=True),
        sa.Column("event_city", sa.String(length=100), nullable=True),
        sa.Column("event_state", sa.String(length=100), nullable=True),
        sa.Column(
            "event_country",
            sa.String(length=10),
            nullable=True,
            server_default=sa.text("'US'"),
        ),
        sa.Column("event_latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("event_longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("corporate_address_id", sa.Integer(), nullable=True),
        sa.Column("event_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("budget_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("max_attendees", sa.Integer(), nullable=True),
        sa.Column(
            "auto_approve_rides",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
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
            ["organizer_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["corporate_address_id"],
            ["corporate_addresses.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corp_event_account_id",
        "corporate_events",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_event_account_status",
        "corporate_events",
        ["account_id", "status"],
    )
    op.create_index(
        "ix_corp_event_account_datetime",
        "corporate_events",
        ["account_id", "event_datetime"],
    )
    op.create_index(
        "ix_corp_event_created_by",
        "corporate_events",
        ["created_by_id"],
    )

    op.create_table(
        "corporate_event_attendees",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=True),
        sa.Column("ride_id", sa.Integer(), nullable=True),
        sa.Column("invited_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'invited'"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
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
            ["event_id"],
            ["corporate_events.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ride_id"],
            ["rides.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "member_id", name="uq_event_attendee"),
    )

    op.create_index(
        "ix_corp_event_attendee_event",
        "corporate_event_attendees",
        ["event_id"],
    )
    op.create_index(
        "ix_corp_event_attendee_member",
        "corporate_event_attendees",
        ["member_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_event_attendee_member",
        table_name="corporate_event_attendees",
    )
    op.drop_index(
        "ix_corp_event_attendee_event",
        table_name="corporate_event_attendees",
    )
    op.drop_table("corporate_event_attendees")

    op.drop_index(
        "ix_corp_event_created_by",
        table_name="corporate_events",
    )
    op.drop_index(
        "ix_corp_event_account_datetime",
        table_name="corporate_events",
    )
    op.drop_index(
        "ix_corp_event_account_status",
        table_name="corporate_events",
    )
    op.drop_index(
        "ix_corp_event_account_id",
        table_name="corporate_events",
    )
    op.drop_table("corporate_events")
