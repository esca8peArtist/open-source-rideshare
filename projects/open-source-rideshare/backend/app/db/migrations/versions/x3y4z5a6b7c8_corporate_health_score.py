"""Add corporate_account_health_scores table.

Corporate accounts now expose a computed risk/health score that aggregates
payment history, policy compliance, credit balance, open disputes, contract
status, and suspension history into a 0–100 composite score.  Scores are
cached as immutable snapshots to preserve historical trend data.

Tables created:
  corporate_account_health_scores — one row per computation event; most recent
                                    row per account is the current health score.

Revision ID: x3y4z5a6b7c8
Revises:     w3x4y5z6a7b8
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "x3y4z5a6b7c8"
down_revision: str = "w3x4y5z6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the HealthRiskLevel enum
    health_risk_level_enum = postgresql.ENUM(
        "excellent",
        "good",
        "fair",
        "poor",
        "critical",
        name="healthrisklevel",
    )
    health_risk_level_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "corporate_account_health_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=False),
        sa.Column(
            "risk_level",
            sa.Enum(
                "excellent",
                "good",
                "fair",
                "poor",
                "critical",
                name="healthrisklevel",
            ),
            nullable=False,
        ),
        sa.Column("payment_score", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("compliance_score", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("credit_score", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("dispute_score", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("contract_score", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("suspension_score", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("score_details", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("computed_by_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "overall_score >= 0 AND overall_score <= 100",
            name="ck_health_overall_range",
        ),
        sa.CheckConstraint(
            "payment_score >= 0 AND payment_score <= 100",
            name="ck_health_payment_range",
        ),
        sa.CheckConstraint(
            "compliance_score >= 0 AND compliance_score <= 100",
            name="ck_health_compliance_range",
        ),
        sa.CheckConstraint(
            "credit_score >= 0 AND credit_score <= 100",
            name="ck_health_credit_range",
        ),
        sa.CheckConstraint(
            "dispute_score >= 0 AND dispute_score <= 100",
            name="ck_health_dispute_range",
        ),
        sa.CheckConstraint(
            "contract_score >= 0 AND contract_score <= 100",
            name="ck_health_contract_range",
        ),
        sa.CheckConstraint(
            "suspension_score >= 0 AND suspension_score <= 100",
            name="ck_health_suspension_range",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["computed_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corp_health_account_id",
        "corporate_account_health_scores",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_health_computed_at",
        "corporate_account_health_scores",
        ["computed_at"],
    )
    op.create_index(
        "ix_corp_health_risk_level",
        "corporate_account_health_scores",
        ["risk_level"],
    )
    op.create_index(
        "ix_corp_health_account_computed",
        "corporate_account_health_scores",
        ["account_id", "computed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_corp_health_account_computed", table_name="corporate_account_health_scores")
    op.drop_index("ix_corp_health_risk_level", table_name="corporate_account_health_scores")
    op.drop_index("ix_corp_health_computed_at", table_name="corporate_account_health_scores")
    op.drop_index("ix_corp_health_account_id", table_name="corporate_account_health_scores")
    op.drop_table("corporate_account_health_scores")
    op.execute("DROP TYPE IF EXISTS healthrisklevel")
