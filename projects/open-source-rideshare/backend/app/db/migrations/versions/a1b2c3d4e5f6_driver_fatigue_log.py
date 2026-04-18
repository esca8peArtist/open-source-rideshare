"""add driver_fatigue_logs table

Revision ID: a1b2c3d4e5f6
Revises: z0a1b2c3d4e5
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "z0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "driver_fatigue_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("ride_id", sa.Integer(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum("RIDE_STARTED", "RIDE_ENDED", name="fatigueeventtype"),
            nullable=False,
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_driver_fatigue_logs_driver_id",
        "driver_fatigue_logs",
        ["driver_id"],
    )


def downgrade():
    op.drop_index(
        "ix_driver_fatigue_logs_driver_id",
        table_name="driver_fatigue_logs",
    )
    op.drop_table("driver_fatigue_logs")
    op.execute("DROP TYPE IF EXISTS fatigueeventtype")
