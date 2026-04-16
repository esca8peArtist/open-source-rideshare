"""Corporate Fleet Insurance Tracking.

Fleet managers track insurance policies for company vehicles — liability,
collision, comprehensive coverage — with expiry date alerts.

Tables created:
  corporate_fleet_insurance_policies — one record per insurance policy per vehicle

Revision ID: o4p5q6r7s8t9
Revises:     n3o4p5q6r7s8
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "o4p5q6r7s8t9"
down_revision: str = "n3o4p5q6r7s8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE insurancetype AS ENUM (
            'liability',
            'collision',
            'comprehensive',
            'commercial_auto',
            'uninsured_motorist',
            'other'
        )
        """
    )

    op.create_table(
        "corporate_fleet_insurance_policies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "fleet_vehicle_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("policy_number", sa.String(100), nullable=False),
        sa.Column(
            "insurance_type",
            sa.Enum(
                "liability",
                "collision",
                "comprehensive",
                "commercial_auto",
                "uninsured_motorist",
                "other",
                name="insurancetype",
            ),
            nullable=False,
        ),
        sa.Column("provider_name", sa.String(200), nullable=False),
        sa.Column("coverage_amount_usd", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("deductible_usd", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("premium_annual_usd", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("policy_start_date", sa.Date(), nullable=False),
        sa.Column("policy_end_date", sa.Date(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["fleet_vehicle_id"],
            ["corporate_fleet_vehicles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "account_id",
            "policy_number",
            name="uq_fleet_insurance_account_policy_number",
        ),
    )

    op.create_index(
        "ix_fleet_insurance_account_id",
        "corporate_fleet_insurance_policies",
        ["account_id"],
    )
    op.create_index(
        "ix_fleet_insurance_vehicle_id",
        "corporate_fleet_insurance_policies",
        ["fleet_vehicle_id"],
    )
    op.create_index(
        "ix_fleet_insurance_end_date",
        "corporate_fleet_insurance_policies",
        ["policy_end_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fleet_insurance_end_date",
        table_name="corporate_fleet_insurance_policies",
    )
    op.drop_index(
        "ix_fleet_insurance_vehicle_id",
        table_name="corporate_fleet_insurance_policies",
    )
    op.drop_index(
        "ix_fleet_insurance_account_id",
        table_name="corporate_fleet_insurance_policies",
    )
    op.drop_table("corporate_fleet_insurance_policies")
    op.execute("DROP TYPE IF EXISTS insurancetype")
