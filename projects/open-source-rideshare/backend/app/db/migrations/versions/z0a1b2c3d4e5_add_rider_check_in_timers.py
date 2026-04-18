"""add rider_check_in_timers table

Revision ID: z0a1b2c3d4e5
Revises: y9z0a1b2c3d4
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "z0a1b2c3d4e5"
down_revision = "y9z0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rider_check_in_timers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rider_id", sa.Integer(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "confirmed", "expired", "cancelled", name="checkintimerstatus"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rider_check_in_timers_rider_id",
        "rider_check_in_timers",
        ["rider_id"],
    )


def downgrade():
    op.drop_index(
        "ix_rider_check_in_timers_rider_id",
        table_name="rider_check_in_timers",
    )
    op.drop_table("rider_check_in_timers")
    op.execute("DROP TYPE IF EXISTS checkintimerstatus")
