"""Add corporate_trip_purposes table and trip purpose columns to rides.

Companies can define purpose codes (e.g. "CLIENT_MEETING", "CONFERENCE")
that employees use to tag their corporate rides.  Analytics can break down
spend by purpose code.

Tables created:
  corporate_trip_purposes — admin-defined purpose codes per account

Columns added to rides:
  trip_purpose_id — nullable FK to corporate_trip_purposes.id
  trip_notes      — nullable VARCHAR(500) free-text notes for the tagged purpose

Revision ID: v2w3x4y5z6a7
Revises:     u2v3w4x5y6z7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "v2w3x4y5z6a7"
down_revision: str = "u2v3w4x5y6z7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # corporate_trip_purposes
    op.create_table(
        "corporate_trip_purposes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("requires_notes", sa.Boolean(), nullable=False, server_default=sa.text("false")),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "code", name="uq_corp_trip_purpose_account_code"
        ),
    )

    op.create_index(
        "ix_corp_trip_purposes_account_id",
        "corporate_trip_purposes",
        ["account_id"],
    )

    # Add trip purpose columns to rides
    op.add_column(
        "rides",
        sa.Column(
            "trip_purpose_id",
            sa.Integer(),
            sa.ForeignKey("corporate_trip_purposes.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "rides",
        sa.Column("trip_notes", sa.String(500), nullable=True),
    )
    op.create_index(
        "ix_rides_trip_purpose_id",
        "rides",
        ["trip_purpose_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_rides_trip_purpose_id", table_name="rides")
    op.drop_column("rides", "trip_notes")
    op.drop_column("rides", "trip_purpose_id")

    op.drop_index("ix_corp_trip_purposes_account_id", table_name="corporate_trip_purposes")
    op.drop_table("corporate_trip_purposes")
