"""Add corporate_sla_policies and corporate_sla_ride_records tables.

Enterprise corporate accounts define SLA policies with contractual quality
targets for rides.  Each ride is evaluated against the active policy and the
result is stored as an immutable snapshot for compliance reporting.

Tables created:
  corporate_sla_policies      — named SLA policies per corporate account
  corporate_sla_ride_records  — per-ride SLA evaluation snapshots

Revision ID: s1t2u3v4w5x6
Revises:     r0s1t2u3v4w5
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "s1t2u3v4w5x6"
down_revision = "r0s1t2u3v4w5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. corporate_sla_policies table
    # ------------------------------------------------------------------
    op.create_table(
        "corporate_sla_policies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("max_wait_time_minutes", sa.Integer(), nullable=True),
        sa.Column("min_driver_rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("on_time_window_minutes", sa.Integer(), nullable=True),
        sa.Column("target_completion_rate_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
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

    # Indexes on policies.
    op.create_index(
        "ix_corp_sla_policy_account_id",
        "corporate_sla_policies",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_sla_policy_account_active",
        "corporate_sla_policies",
        ["account_id", "is_active"],
    )
    op.create_index(
        "ix_corp_sla_policy_account_created",
        "corporate_sla_policies",
        ["account_id", "created_at"],
    )

    # ------------------------------------------------------------------
    # 2. corporate_sla_ride_records table
    # ------------------------------------------------------------------
    op.create_table(
        "corporate_sla_ride_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "policy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corporate_sla_policies.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "ride_id",
            sa.Integer(),
            sa.ForeignKey("rides.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "member_id",
            sa.Integer(),
            sa.ForeignKey("corporate_account_members.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("wait_time_minutes", sa.Numeric(8, 2), nullable=True),
        sa.Column("driver_rating_at_time", sa.Numeric(3, 2), nullable=True),
        sa.Column(
            "was_scheduled_ride",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("scheduled_pickup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_pickup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("arrival_delta_minutes", sa.Numeric(8, 2), nullable=True),
        sa.Column("wait_time_met", sa.Boolean(), nullable=True),
        sa.Column("driver_rating_met", sa.Boolean(), nullable=True),
        sa.Column("on_time_met", sa.Boolean(), nullable=True),
        sa.Column(
            "overall_sla_met",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Indexes on ride records.
    op.create_index(
        "ix_corp_sla_record_account_id",
        "corporate_sla_ride_records",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_sla_record_account_policy",
        "corporate_sla_ride_records",
        ["account_id", "policy_id"],
    )
    op.create_index(
        "ix_corp_sla_record_account_met",
        "corporate_sla_ride_records",
        ["account_id", "overall_sla_met"],
    )
    op.create_index(
        "ix_corp_sla_record_account_eval",
        "corporate_sla_ride_records",
        ["account_id", "evaluated_at"],
    )


def downgrade() -> None:
    # Drop ride records table first (has FK to policies).
    op.drop_index(
        "ix_corp_sla_record_account_eval",
        table_name="corporate_sla_ride_records",
    )
    op.drop_index(
        "ix_corp_sla_record_account_met",
        table_name="corporate_sla_ride_records",
    )
    op.drop_index(
        "ix_corp_sla_record_account_policy",
        table_name="corporate_sla_ride_records",
    )
    op.drop_index(
        "ix_corp_sla_record_account_id",
        table_name="corporate_sla_ride_records",
    )
    op.drop_table("corporate_sla_ride_records")

    # Drop policies table.
    op.drop_index(
        "ix_corp_sla_policy_account_created",
        table_name="corporate_sla_policies",
    )
    op.drop_index(
        "ix_corp_sla_policy_account_active",
        table_name="corporate_sla_policies",
    )
    op.drop_index(
        "ix_corp_sla_policy_account_id",
        table_name="corporate_sla_policies",
    )
    op.drop_table("corporate_sla_policies")
