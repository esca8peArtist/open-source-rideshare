"""Create corporate_scheduled_reports table.

Enterprise admins configure automated periodic delivery of spending and usage
reports to a list of email recipients.  Supports daily, weekly, and monthly
delivery cadences.

Tables created:
  corporate_scheduled_reports — one row per configured report schedule.

Enums created:
  reportfrequency         — daily / weekly / monthly
  scheduledreporttype     — spending_overview / monthly_trend / employee_breakdown /
                             ride_patterns / invoice_summary / expense_report_summary

Revision ID: k2l3m4n5o6p7
Revises:     j0k1l2m3n4o5
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "k2l3m4n5o6p7"
down_revision: str = "j0k1l2m3n4o5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enums
    reportfrequency = postgresql.ENUM(
        "daily", "weekly", "monthly",
        name="reportfrequency",
    )
    reportfrequency.create(op.get_bind(), checkfirst=True)

    scheduledreporttype = postgresql.ENUM(
        "spending_overview",
        "monthly_trend",
        "employee_breakdown",
        "ride_patterns",
        "invoice_summary",
        "expense_report_summary",
        name="scheduledreporttype",
    )
    scheduledreporttype.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "corporate_scheduled_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "report_type",
            sa.Enum(
                "spending_overview",
                "monthly_trend",
                "employee_breakdown",
                "ride_patterns",
                "invoice_summary",
                "expense_report_summary",
                name="scheduledreporttype",
            ),
            nullable=False,
        ),
        sa.Column(
            "frequency",
            sa.Enum("daily", "weekly", "monthly", name="reportfrequency"),
            nullable=False,
        ),
        sa.Column("day_of_week", sa.Integer(), nullable=True),
        sa.Column("day_of_month", sa.Integer(), nullable=True),
        sa.Column("recipients", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corp_sched_reports_account_id",
        "corporate_scheduled_reports",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_sched_reports_is_active",
        "corporate_scheduled_reports",
        ["is_active"],
    )
    op.create_index(
        "ix_corp_sched_reports_next_due_at",
        "corporate_scheduled_reports",
        ["next_due_at"],
    )
    op.create_index(
        "ix_corp_sched_reports_account_active",
        "corporate_scheduled_reports",
        ["account_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_corp_sched_reports_account_active",
                  table_name="corporate_scheduled_reports")
    op.drop_index("ix_corp_sched_reports_next_due_at",
                  table_name="corporate_scheduled_reports")
    op.drop_index("ix_corp_sched_reports_is_active",
                  table_name="corporate_scheduled_reports")
    op.drop_index("ix_corp_sched_reports_account_id",
                  table_name="corporate_scheduled_reports")
    op.drop_table("corporate_scheduled_reports")

    sa.Enum(name="scheduledreporttype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="reportfrequency").drop(op.get_bind(), checkfirst=True)
