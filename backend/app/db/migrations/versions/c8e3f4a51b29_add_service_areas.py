"""add service areas table for geofencing

Revision ID: c8e3f4a51b29
Revises: b5c4d9e20f17
Create Date: 2026-04-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry


revision: str = 'c8e3f4a51b29'
down_revision: Union[str, Sequence[str], None] = 'b5c4d9e20f17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "service_areas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("boundary", Geometry(geometry_type="POLYGON", srid=4326), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # Spatial index on boundary for fast ST_Contains queries
    op.create_index("idx_service_areas_boundary", "service_areas", ["boundary"], postgresql_using="gist")


def downgrade() -> None:
    op.drop_index("idx_service_areas_boundary", table_name="service_areas")
    op.drop_table("service_areas")
