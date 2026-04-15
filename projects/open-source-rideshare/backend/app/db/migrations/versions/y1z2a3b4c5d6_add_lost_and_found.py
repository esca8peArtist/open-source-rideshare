"""Add lost and found tables (separate lost/found model design).

Tables created:
  laf_lost_item_reports   — rider-submitted lost item reports
  laf_found_item_reports  — driver-submitted found item reports

Indexes added on rider_id, driver_id, status, category, and ride_id
for efficient querying on the most common filter patterns.

Revision ID: y1z2a3b4c5d6
Revises: x1y2z3a4b5c6
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "y1z2a3b4c5d6"
down_revision = "x1y2z3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------------
    item_category_enum = sa.Enum(
        "electronics", "clothing", "documents", "bags", "jewelry", "keys", "other",
        name="itemcategory",
    )
    item_category_enum.create(op.get_bind(), checkfirst=True)

    contact_preference_enum = sa.Enum(
        "app_message", "phone", "email",
        name="contactpreference",
    )
    contact_preference_enum.create(op.get_bind(), checkfirst=True)

    lost_item_status_enum = sa.Enum(
        "open", "matched", "returned", "closed_no_match",
        name="lostitemstatus",
    )
    lost_item_status_enum.create(op.get_bind(), checkfirst=True)

    found_item_status_enum = sa.Enum(
        "pending_match", "matched", "returned_to_owner", "discarded",
        name="founditemstatus",
    )
    found_item_status_enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # laf_lost_item_reports
    # ------------------------------------------------------------------
    op.create_table(
        "laf_lost_item_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rider_id", sa.Integer(), nullable=False),
        sa.Column("ride_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", item_category_enum, nullable=False),
        sa.Column("date_lost", sa.Date(), nullable=False),
        sa.Column("contact_preference", contact_preference_enum, nullable=False),
        sa.Column(
            "status",
            lost_item_status_enum,
            nullable=False,
            server_default="open",
        ),
        sa.Column("matched_found_report_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_laf_lost_item_reports_rider_id", "laf_lost_item_reports", ["rider_id"])
    op.create_index("ix_laf_lost_item_reports_status", "laf_lost_item_reports", ["status"])
    op.create_index("ix_laf_lost_item_reports_category", "laf_lost_item_reports", ["category"])
    op.create_index("ix_laf_lost_item_reports_ride_id", "laf_lost_item_reports", ["ride_id"])

    # ------------------------------------------------------------------
    # laf_found_item_reports
    # ------------------------------------------------------------------
    op.create_table(
        "laf_found_item_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("ride_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", item_category_enum, nullable=False),
        sa.Column("date_found", sa.Date(), nullable=False),
        sa.Column("storage_location", sa.String(255), nullable=False),
        sa.Column(
            "status",
            found_item_status_enum,
            nullable=False,
            server_default="pending_match",
        ),
        sa.Column("matched_lost_report_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"]),
        sa.ForeignKeyConstraint(["matched_lost_report_id"], ["laf_lost_item_reports.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_laf_found_item_reports_driver_id", "laf_found_item_reports", ["driver_id"])
    op.create_index("ix_laf_found_item_reports_status", "laf_found_item_reports", ["status"])
    op.create_index("ix_laf_found_item_reports_category", "laf_found_item_reports", ["category"])
    op.create_index("ix_laf_found_item_reports_ride_id", "laf_found_item_reports", ["ride_id"])

    # ------------------------------------------------------------------
    # Add FK from laf_lost_item_reports -> laf_found_item_reports now that the
    # laf_found_item_reports table exists.
    # ------------------------------------------------------------------
    op.create_foreign_key(
        "fk_laf_lost_item_reports_matched_found_report_id",
        "laf_lost_item_reports",
        "laf_found_item_reports",
        ["matched_found_report_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_laf_lost_item_reports_matched_found_report_id",
        "laf_lost_item_reports",
        type_="foreignkey",
    )
    op.drop_table("laf_found_item_reports")
    op.drop_table("laf_lost_item_reports")

    sa.Enum(name="founditemstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="lostitemstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="contactpreference").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="itemcategory").drop(op.get_bind(), checkfirst=True)
