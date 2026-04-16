"""corporate_service_zones

Corporate accounts define named circular geographic zones that gate or restrict
employee ride bookings.  Zone types: allowed, restricted, approval_required.

Revision ID: n6o7p8q9r0s1
Revises: m5n6o7p8q9r0
Create Date: 2026-04-16 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "n6o7p8q9r0s1"
down_revision = "m5n6o7p8q9r0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enums
    zonetype_enum = postgresql.ENUM(
        "allowed", "restricted", "approval_required",
        name="zonetype",
        create_type=True,
    )
    zonetype_enum.create(op.get_bind(), checkfirst=True)

    zoneappliesto_enum = postgresql.ENUM(
        "pickup", "dropoff", "both",
        name="zoneappliesto",
        create_type=True,
    )
    zoneappliesto_enum.create(op.get_bind(), checkfirst=True)

    # Create corporate_service_zones table
    op.create_table(
        "corporate_service_zones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "zone_type",
            sa.Enum(
                "allowed", "restricted", "approval_required",
                name="zonetype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("center_latitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("center_longitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("radius_km", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column(
            "applies_to",
            sa.Enum("pickup", "dropoff", "both", name="zoneappliesto", create_type=False),
            nullable=False,
        ),
        sa.Column("group_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
            "account_id", "name", name="uq_corp_service_zone_account_name"
        ),
    )

    # Indexes
    op.create_index(
        "ix_corp_service_zone_account_id",
        "corporate_service_zones",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_service_zone_is_active",
        "corporate_service_zones",
        ["is_active"],
    )
    op.create_index(
        "ix_corp_service_zone_zone_type",
        "corporate_service_zones",
        ["zone_type"],
    )
    op.create_index(
        "ix_corp_service_zone_applies_to",
        "corporate_service_zones",
        ["applies_to"],
    )


def downgrade() -> None:
    op.drop_index("ix_corp_service_zone_applies_to", table_name="corporate_service_zones")
    op.drop_index("ix_corp_service_zone_zone_type", table_name="corporate_service_zones")
    op.drop_index("ix_corp_service_zone_is_active", table_name="corporate_service_zones")
    op.drop_index("ix_corp_service_zone_account_id", table_name="corporate_service_zones")
    op.drop_table("corporate_service_zones")

    op.execute("DROP TYPE IF EXISTS zoneappliesto")
    op.execute("DROP TYPE IF EXISTS zonetype")
