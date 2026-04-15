"""Add trusted_contacts and trip_share_records tables.

Tables created:
  trusted_contacts   — riders' registered emergency/trusted contacts
  trip_share_records — log of which contacts were notified for each ride

Revision ID: c4d5e6f7g8h9
Revises: b3c4d5e6f7g8
Create Date: 2026-04-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c4d5e6f7g8h9"
down_revision = "b3c4d5e6f7g8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trusted_contacts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("relationship_label", sa.String(80), nullable=False, server_default=""),
        sa.Column("share_automatically", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
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
    op.create_index("ix_trusted_contacts_user_id", "trusted_contacts", ["user_id"])
    op.create_unique_constraint(
        "uq_trusted_contact_user_phone",
        "trusted_contacts",
        ["user_id", "phone"],
    )

    op.create_table(
        "trip_share_records",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ride_id", sa.Integer, sa.ForeignKey("rides.id"), nullable=False),
        sa.Column(
            "contact_id", sa.Integer, sa.ForeignKey("trusted_contacts.id"), nullable=False
        ),
        sa.Column(
            "shared_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("start_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("complete_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_trip_share_records_ride_id", "trip_share_records", ["ride_id"])
    op.create_index(
        "ix_trip_share_records_contact_id", "trip_share_records", ["contact_id"]
    )
    op.create_unique_constraint(
        "uq_trip_share_ride_contact",
        "trip_share_records",
        ["ride_id", "contact_id"],
    )


def downgrade() -> None:
    op.drop_table("trip_share_records")
    op.drop_table("trusted_contacts")
