"""add driver_escalations table

Adds the driver_escalations table for the accountability escalation system.
Tracks progressive warning/suspension state per driver (3-strike system).

Revision ID: n8o9p0q1r2s3
Revises: m7n8o9p0q1r2
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "n8o9p0q1r2s3"
down_revision = "m7n8o9p0q1r2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "driver_escalations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("escalation_level", sa.String(20), nullable=False, server_default="none"),
        sa.Column("last_trigger_type", sa.String(50), nullable=True),
        sa.Column("last_warning_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_reset_note", sa.Text(), nullable=True),
        sa.Column("reset_by", sa.Integer(), nullable=True),
        sa.Column("last_reset_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["reset_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("driver_id", name="uq_driver_escalation_driver_id"),
    )
    op.create_index(
        "ix_driver_escalation_driver_id", "driver_escalations", ["driver_id"], unique=True
    )
    op.create_index(
        "ix_driver_escalation_level", "driver_escalations", ["escalation_level"]
    )


def downgrade():
    op.drop_index("ix_driver_escalation_level", table_name="driver_escalations")
    op.drop_index("ix_driver_escalation_driver_id", table_name="driver_escalations")
    op.drop_table("driver_escalations")
