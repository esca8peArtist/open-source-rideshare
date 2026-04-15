"""Add platform announcements.

Persistent cooperative news/update feed with per-user view and acknowledgment
tracking. Distinct from bulk_notifications (fire-and-forget): announcements are
browsable, audience-filtered, and support mandatory acknowledgment for critical
policy or regulatory notices.

Tables created:
  platform_announcements — persistent news/updates with audience + priority
  announcement_views     — per-user view and acknowledgment records

Enum types created:
  announcementaudience   — all / drivers / riders / members
  announcementpriority   — low / normal / high / critical

Revision ID: l1m2n3o4p5q6
Revises: k3l4m5n6o7p8
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "l1m2n3o4p5q6"
down_revision: str = "k3l4m5n6o7p8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum types
    audience_enum = postgresql.ENUM(
        "all", "drivers", "riders", "members",
        name="announcementaudience",
        create_type=True,
    )
    audience_enum.create(op.get_bind(), checkfirst=True)

    priority_enum = postgresql.ENUM(
        "low", "normal", "high", "critical",
        name="announcementpriority",
        create_type=True,
    )
    priority_enum.create(op.get_bind(), checkfirst=True)

    # platform_announcements table
    op.create_table(
        "platform_announcements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "audience",
            sa.Enum("all", "drivers", "riders", "members", name="announcementaudience"),
            nullable=False,
            server_default="all",
        ),
        sa.Column(
            "priority",
            sa.Enum("low", "normal", "high", "critical", name="announcementpriority"),
            nullable=False,
            server_default="normal",
        ),
        sa.Column("requires_acknowledgment", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
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
        "ix_announcement_audience_published",
        "platform_announcements",
        ["audience", "published_at"],
    )
    op.create_index(
        "ix_announcement_priority_active",
        "platform_announcements",
        ["priority", "is_active"],
    )
    op.create_index(
        "ix_platform_announcements_published_at",
        "platform_announcements",
        ["published_at"],
    )

    # announcement_views table
    op.create_table(
        "announcement_views",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "announcement_id",
            sa.Integer(),
            sa.ForeignKey("platform_announcements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "viewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_announcement_views_announcement_id",
        "announcement_views",
        ["announcement_id"],
    )
    op.create_index(
        "ix_announcement_views_user_id",
        "announcement_views",
        ["user_id"],
    )
    op.create_index(
        "ix_ann_view_user_acked",
        "announcement_views",
        ["user_id", "acknowledged_at"],
    )
    op.create_unique_constraint(
        "uq_announcement_view_user",
        "announcement_views",
        ["announcement_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_table("announcement_views")
    op.drop_table("platform_announcements")

    op.execute("DROP TYPE IF EXISTS announcementpriority")
    op.execute("DROP TYPE IF EXISTS announcementaudience")
