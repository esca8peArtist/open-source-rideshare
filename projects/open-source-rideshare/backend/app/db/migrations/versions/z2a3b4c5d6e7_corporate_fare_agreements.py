"""Add corporate_fare_agreements table.

Corporate accounts negotiate custom pricing arrangements with the platform.
This migration creates the table that stores those agreements — surge caps,
flat discounts, and per-mile / per-minute rate overrides.

Tables created:
  corporate_fare_agreements — per-account negotiated pricing contracts with
                              rate type, value, vehicle-type scoping, and
                              optional validity window.

Revision ID: z2a3b4c5d6e7
Revises:     y2z3a4b5c6d7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "z2a3b4c5d6e7"
down_revision: str = "y2z3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the FareAgreementRateType enum
    fare_rate_type = postgresql.ENUM(
        "surge_cap",
        "flat_discount_pct",
        "per_mile_rate_usd",
        "per_minute_rate_usd",
        name="fareagreementratetype",
        create_type=True,
    )
    fare_rate_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "corporate_fare_agreements",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("corporate_account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "rate_type",
            sa.Enum(
                "surge_cap",
                "flat_discount_pct",
                "per_mile_rate_usd",
                "per_minute_rate_usd",
                name="fareagreementratetype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("value", sa.Numeric(10, 4), nullable=False),
        sa.Column("applies_to_vehicle_types", postgresql.JSONB(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
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
            ["corporate_account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corp_fare_agreements_account_id",
        "corporate_fare_agreements",
        ["corporate_account_id"],
    )
    op.create_index(
        "ix_corp_fare_agreements_is_active",
        "corporate_fare_agreements",
        ["is_active"],
    )
    op.create_index(
        "ix_corp_fare_agreements_rate_type",
        "corporate_fare_agreements",
        ["rate_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_fare_agreements_rate_type",
        table_name="corporate_fare_agreements",
    )
    op.drop_index(
        "ix_corp_fare_agreements_is_active",
        table_name="corporate_fare_agreements",
    )
    op.drop_index(
        "ix_corp_fare_agreements_account_id",
        table_name="corporate_fare_agreements",
    )
    op.drop_table("corporate_fare_agreements")
    op.execute("DROP TYPE IF EXISTS fareagreementratetype")
