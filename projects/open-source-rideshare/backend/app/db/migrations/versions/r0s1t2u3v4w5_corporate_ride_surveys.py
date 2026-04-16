"""Add corporate_ride_surveys and corporate_ride_survey_responses tables.

Enterprise admins create named ride satisfaction surveys with configurable
questions.  Employees submit responses after corporate rides.  Admins view
aggregated per-question analytics.

Tables created:
  corporate_ride_surveys           — named surveys per corporate account
  corporate_ride_survey_responses  — employee responses to surveys

Revision ID: r0s1t2u3v4w5
Revises:     q9r0s1t2u3v4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "r0s1t2u3v4w5"
down_revision = "q9r0s1t2u3v4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. corporate_ride_surveys table
    # ------------------------------------------------------------------
    op.create_table(
        "corporate_ride_surveys",
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
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("questions", postgresql.JSON(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
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

    # Unique constraint: title must be unique within an account.
    op.create_unique_constraint(
        "uq_corp_ride_survey_account_title",
        "corporate_ride_surveys",
        ["account_id", "title"],
    )

    # Indexes on surveys.
    op.create_index(
        "ix_corp_ride_survey_account_id",
        "corporate_ride_surveys",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_ride_survey_account_active",
        "corporate_ride_surveys",
        ["account_id", "is_active"],
    )

    # ------------------------------------------------------------------
    # 2. corporate_ride_survey_responses table
    # ------------------------------------------------------------------
    op.create_table(
        "corporate_ride_survey_responses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "survey_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corporate_ride_surveys.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            sa.Integer(),
            sa.ForeignKey("corporate_account_members.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ride_id",
            sa.Integer(),
            sa.ForeignKey("rides.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("responses", postgresql.JSON(), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Unique constraint: one response per (survey, member).
    op.create_unique_constraint(
        "uq_corp_ride_survey_response_survey_member",
        "corporate_ride_survey_responses",
        ["survey_id", "member_id"],
    )

    # Indexes on responses.
    op.create_index(
        "ix_corp_ride_survey_resp_survey_id",
        "corporate_ride_survey_responses",
        ["survey_id"],
    )
    op.create_index(
        "ix_corp_ride_survey_resp_member_id",
        "corporate_ride_survey_responses",
        ["member_id"],
    )
    op.create_index(
        "ix_corp_ride_survey_resp_account_id",
        "corporate_ride_survey_responses",
        ["account_id"],
    )


def downgrade() -> None:
    # Drop responses table first (has FK to surveys).
    op.drop_index(
        "ix_corp_ride_survey_resp_account_id",
        table_name="corporate_ride_survey_responses",
    )
    op.drop_index(
        "ix_corp_ride_survey_resp_member_id",
        table_name="corporate_ride_survey_responses",
    )
    op.drop_index(
        "ix_corp_ride_survey_resp_survey_id",
        table_name="corporate_ride_survey_responses",
    )
    op.drop_constraint(
        "uq_corp_ride_survey_response_survey_member",
        "corporate_ride_survey_responses",
        type_="unique",
    )
    op.drop_table("corporate_ride_survey_responses")

    # Drop surveys table.
    op.drop_index(
        "ix_corp_ride_survey_account_active",
        table_name="corporate_ride_surveys",
    )
    op.drop_index(
        "ix_corp_ride_survey_account_id",
        table_name="corporate_ride_surveys",
    )
    op.drop_constraint(
        "uq_corp_ride_survey_account_title",
        "corporate_ride_surveys",
        type_="unique",
    )
    op.drop_table("corporate_ride_surveys")
