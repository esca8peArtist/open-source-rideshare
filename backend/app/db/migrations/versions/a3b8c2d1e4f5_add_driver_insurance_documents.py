"""add driver_insurance_documents and insurance_expiry_alerts tables

Revision ID: a3b8c2d1e4f5
Revises: f1a3c7e92d05
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3b8c2d1e4f5'
down_revision: Union[str, Sequence[str], None] = 'f1a3c7e92d05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "driver_insurance_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "driver_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "document_type",
            sa.Enum(
                "liability",
                "comprehensive",
                "commercial",
                "personal_injury_protection",
                name="insurancedocumenttype",
            ),
            nullable=False,
        ),
        sa.Column("insurance_provider", sa.String(200), nullable=False),
        sa.Column("policy_number", sa.String(100), nullable=False),
        sa.Column("coverage_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("policy_start_date", sa.Date(), nullable=False),
        sa.Column("policy_end_date", sa.Date(), nullable=False),
        sa.Column("document_url", sa.String(500), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending_upload",
                "pending_review",
                "approved",
                "rejected",
                "expired",
                name="insurancedocumentstatus",
            ),
            nullable=False,
            index=True,
        ),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("verified_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
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
        "ix_driver_insurance_status_expiry",
        "driver_insurance_documents",
        ["status", "policy_end_date"],
    )

    op.create_table(
        "insurance_expiry_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "driver_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("driver_insurance_documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "alert_type",
            sa.Enum(
                "30_day",
                "7_day",
                "1_day",
                "expired",
                name="insurancealerttype",
            ),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("insurance_expiry_alerts")
    op.drop_index(
        "ix_driver_insurance_status_expiry",
        table_name="driver_insurance_documents",
    )
    op.drop_table("driver_insurance_documents")
    op.execute("DROP TYPE IF EXISTS insurancealerttype")
    op.execute("DROP TYPE IF EXISTS insurancedocumentstatus")
    op.execute("DROP TYPE IF EXISTS insurancedocumenttype")
