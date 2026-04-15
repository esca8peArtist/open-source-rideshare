"""Add community safety alerts.

Community-powered hazard reporting — drivers and riders can report road
conditions, construction, weather, and safety concerns.  Approved alerts are
surfaced to nearby drivers and riders in real time.  Distinct from the SOS
system (emergency-only) and driver incident reporting (post-ride): safety
alerts are proactive, community-generated, and geographically browsable.

Cooperative differentiator: Uber and Lyft have no mechanism for members to
share safety data with each other.  This gives the cooperative a live,
crowdsourced safety layer built and maintained by its own members.

Tables created:
  safety_alerts        — alert definitions (reporter-managed)
  safety_alert_upvotes — per-user confirmation votes (unique per user per alert)

Enum types created:
  reporterroleenum     — driver / rider
  alerttypeenum        — road_hazard / construction / weather / traffic /
                         dangerous_area / other
  alertseverityenum    — low / medium / high / critical
  moderationstatusenum — pending / auto_approved / approved / rejected

Revision ID: m1n2o3p4q5r6
Revises: l1m2n3o4p5q6
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "m1n2o3p4q5r6"
down_revision: str = "l1m2n3o4p5q6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- Enum types ----
    reporter_role_enum = postgresql.ENUM(
        "driver", "rider",
        name="reporterroleenum",
        create_type=True,
    )
    reporter_role_enum.create(op.get_bind(), checkfirst=True)

    alert_type_enum = postgresql.ENUM(
        "road_hazard", "construction", "weather", "traffic",
        "dangerous_area", "other",
        name="alerttypeenum",
        create_type=True,
    )
    alert_type_enum.create(op.get_bind(), checkfirst=True)

    alert_severity_enum = postgresql.ENUM(
        "low", "medium", "high", "critical",
        name="alertseverityenum",
        create_type=True,
    )
    alert_severity_enum.create(op.get_bind(), checkfirst=True)

    moderation_status_enum = postgresql.ENUM(
        "pending", "auto_approved", "approved", "rejected",
        name="moderationstatusenum",
        create_type=True,
    )
    moderation_status_enum.create(op.get_bind(), checkfirst=True)

    # ---- safety_alerts table ----
    op.create_table(
        "safety_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "reporter_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "reporter_role",
            sa.Enum("driver", "rider", name="reporterroleenum"),
            nullable=False,
        ),
        sa.Column(
            "alert_type",
            sa.Enum(
                "road_hazard", "construction", "weather", "traffic",
                "dangerous_area", "other",
                name="alerttypeenum",
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum("low", "medium", "high", "critical", name="alertseverityenum"),
            nullable=False,
            server_default="medium",
        ),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column(
            "radius_meters",
            sa.Float(),
            nullable=False,
            server_default="100.0",
            comment="Approximate area affected in metres.",
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "moderation_status",
            sa.Enum(
                "pending", "auto_approved", "approved", "rejected",
                name="moderationstatusenum",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "moderated_by",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("moderated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("moderation_note", sa.String(500), nullable=True),
        sa.Column(
            "upvote_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
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

    # Indexes on safety_alerts
    op.create_index("ix_safety_alerts_reporter_id", "safety_alerts", ["reporter_id"])
    op.create_index(
        "ix_safety_alerts_moderation_status",
        "safety_alerts",
        ["moderation_status", "is_active"],
    )
    op.create_index(
        "ix_safety_alerts_location",
        "safety_alerts",
        ["latitude", "longitude"],
        comment="Bounding-box pre-filter for nearby queries.",
    )
    op.create_index(
        "ix_safety_alerts_expires_at",
        "safety_alerts",
        ["expires_at"],
        comment="For efficient expiry cleanup.",
    )
    op.create_index(
        "ix_safety_alerts_type_active",
        "safety_alerts",
        ["alert_type", "is_active"],
    )

    # ---- safety_alert_upvotes table ----
    op.create_table(
        "safety_alert_upvotes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "alert_id",
            sa.Integer(),
            sa.ForeignKey("safety_alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "voter_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_safety_alert_upvotes_alert_id",
        "safety_alert_upvotes",
        ["alert_id"],
    )
    op.create_index(
        "ix_safety_alert_upvotes_voter_id",
        "safety_alert_upvotes",
        ["voter_id"],
    )
    op.create_unique_constraint(
        "uq_safety_alert_upvote",
        "safety_alert_upvotes",
        ["alert_id", "voter_id"],
    )


def downgrade() -> None:
    op.drop_table("safety_alert_upvotes")
    op.drop_table("safety_alerts")

    op.execute("DROP TYPE IF EXISTS moderationstatusenum")
    op.execute("DROP TYPE IF EXISTS alertseverityenum")
    op.execute("DROP TYPE IF EXISTS alerttypeenum")
    op.execute("DROP TYPE IF EXISTS reporterroleenum")
