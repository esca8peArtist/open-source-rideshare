"""add surge pricing zones table

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "surge_pricing_zones",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),

        # Geographic definition
        sa.Column("polygon", sa.JSON(), nullable=True),
        sa.Column("center_lat", sa.Float(), nullable=True),
        sa.Column("center_lon", sa.Float(), nullable=True),
        sa.Column("radius_km", sa.Float(), nullable=True),

        # Pricing
        sa.Column("multiplier", sa.Float(), nullable=False, server_default=sa.text("1.0")),

        # Activation
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),

        # Time-of-day and day-of-week constraints
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("days_of_week", sa.JSON(), nullable=True),

        # Audit timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "idx_surge_pricing_zones_is_active",
        "surge_pricing_zones",
        ["is_active"],
    )
    op.create_index(
        "idx_surge_pricing_zones_name",
        "surge_pricing_zones",
        ["name"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_surge_pricing_zones_name", table_name="surge_pricing_zones")
    op.drop_index("idx_surge_pricing_zones_is_active", table_name="surge_pricing_zones")
    op.drop_table("surge_pricing_zones")
