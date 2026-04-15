"""Add Driver Emergency Assistance Fund tables.

Tables created:
  driver_hardship_fund       — singleton balance record for the fund
  hardship_contributions     — all deposits into the fund
  hardship_applications      — driver emergency assistance applications

Enum types created:
  contributionsource   — driver / platform / donation / other
  applicationtype      — medical / vehicle_repair / natural_disaster / housing / bereavement / other
  applicationstatus    — pending / under_review / approved / denied / disbursed / withdrawn

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f8a9b0c1d2e3"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------------
    contributionsource_enum = sa.Enum(
        "driver", "platform", "donation", "other",
        name="contributionsource",
    )
    contributionsource_enum.create(op.get_bind(), checkfirst=True)

    applicationtype_enum = sa.Enum(
        "medical", "vehicle_repair", "natural_disaster", "housing", "bereavement", "other",
        name="applicationtype",
    )
    applicationtype_enum.create(op.get_bind(), checkfirst=True)

    applicationstatus_enum = sa.Enum(
        "pending", "under_review", "approved", "denied", "disbursed", "withdrawn",
        name="applicationstatus",
    )
    applicationstatus_enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # driver_hardship_fund
    # ------------------------------------------------------------------
    op.create_table(
        "driver_hardship_fund",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "total_balance_usd",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_contributed_usd",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_disbursed_usd",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
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
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # hardship_contributions
    # ------------------------------------------------------------------
    op.create_table(
        "hardship_contributions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.Enum("driver", "platform", "donation", "other", name="contributionsource"), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=True),
        sa.Column("amount_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_hardship_contributions_source",
        "hardship_contributions",
        ["source"],
    )
    op.create_index(
        "ix_hardship_contributions_driver_id",
        "hardship_contributions",
        ["driver_id"],
    )
    op.create_index(
        "ix_hardship_contributions_created_at",
        "hardship_contributions",
        ["created_at"],
    )

    # ------------------------------------------------------------------
    # hardship_applications
    # ------------------------------------------------------------------
    op.create_table(
        "hardship_applications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column(
            "application_type",
            sa.Enum(
                "medical", "vehicle_repair", "natural_disaster",
                "housing", "bereavement", "other",
                name="applicationtype",
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount_requested_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "under_review", "approved", "denied", "disbursed", "withdrawn",
                name="applicationstatus",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("approved_amount_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disbursed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_hardship_applications_driver_id",
        "hardship_applications",
        ["driver_id"],
    )
    op.create_index(
        "ix_hardship_applications_status",
        "hardship_applications",
        ["status"],
    )
    op.create_index(
        "ix_hardship_applications_application_type",
        "hardship_applications",
        ["application_type"],
    )
    op.create_index(
        "ix_hardship_applications_reviewed_by_id",
        "hardship_applications",
        ["reviewed_by_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_hardship_applications_reviewed_by_id", "hardship_applications")
    op.drop_index("ix_hardship_applications_application_type", "hardship_applications")
    op.drop_index("ix_hardship_applications_status", "hardship_applications")
    op.drop_index("ix_hardship_applications_driver_id", "hardship_applications")
    op.drop_table("hardship_applications")

    op.drop_index("ix_hardship_contributions_created_at", "hardship_contributions")
    op.drop_index("ix_hardship_contributions_driver_id", "hardship_contributions")
    op.drop_index("ix_hardship_contributions_source", "hardship_contributions")
    op.drop_table("hardship_contributions")

    op.drop_table("driver_hardship_fund")

    sa.Enum(name="applicationstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="applicationtype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="contributionsource").drop(op.get_bind(), checkfirst=True)
