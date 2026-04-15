"""add driver quest programs

Revision ID: b1c2d3e4f5g6
Revises: a1b2c3d4e5f6
Create Date: 2026-04-15

Creates two tables:
  driver_quests          — admin-defined bonus challenge definitions
  driver_quest_progress  — per-driver progress tracking for each quest
"""

from alembic import op
import sqlalchemy as sa

revision = "b1c2d3e4f5g6"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "driver_quests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "quest_type",
            sa.Enum(
                "ride_count",
                "earnings_target",
                "acceptance_rate",
                "peak_hours_rides",
                name="questtype",
            ),
            nullable=False,
        ),
        sa.Column("target_value", sa.Numeric(12, 2), nullable=False),
        sa.Column("bonus_amount_cents", sa.Integer, nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("min_rating", sa.Numeric(3, 2), nullable=True),
        sa.Column(
            "zone_id",
            sa.Integer,
            sa.ForeignKey("service_areas.id"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_driver_quests_zone_id",
        "driver_quests",
        ["zone_id"],
    )
    op.create_index(
        "ix_driver_quests_is_active",
        "driver_quests",
        ["is_active"],
    )
    op.create_index(
        "ix_driver_quests_end_time",
        "driver_quests",
        ["end_time"],
    )

    op.create_table(
        "driver_quest_progress",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "quest_id",
            sa.Integer,
            sa.ForeignKey("driver_quests.id"),
            nullable=False,
        ),
        sa.Column(
            "driver_profile_id",
            sa.Integer,
            sa.ForeignKey("driver_profiles.id"),
            nullable=False,
        ),
        sa.Column(
            "current_value",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "completed",
                "claimed",
                "expired",
                "ineligible",
                name="questprogressstatus",
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bonus_paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "quest_id",
            "driver_profile_id",
            name="uq_driver_quest_progress_quest_driver",
        ),
    )
    op.create_index(
        "ix_driver_quest_progress_quest_id",
        "driver_quest_progress",
        ["quest_id"],
    )
    op.create_index(
        "ix_driver_quest_progress_driver_profile_id",
        "driver_quest_progress",
        ["driver_profile_id"],
    )
    op.create_index(
        "ix_driver_quest_progress_status",
        "driver_quest_progress",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_driver_quest_progress_status",
        table_name="driver_quest_progress",
    )
    op.drop_index(
        "ix_driver_quest_progress_driver_profile_id",
        table_name="driver_quest_progress",
    )
    op.drop_index(
        "ix_driver_quest_progress_quest_id",
        table_name="driver_quest_progress",
    )
    op.drop_table("driver_quest_progress")

    op.drop_index("ix_driver_quests_end_time", table_name="driver_quests")
    op.drop_index("ix_driver_quests_is_active", table_name="driver_quests")
    op.drop_index("ix_driver_quests_zone_id", table_name="driver_quests")
    op.drop_table("driver_quests")

    op.execute("DROP TYPE IF EXISTS questprogressstatus")
    op.execute("DROP TYPE IF EXISTS questtype")
