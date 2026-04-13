"""add lost_item_reports table

Revision ID: a1b2c3d4e5f6
Revises: f1a3c7e92d05
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f1a3c7e92d05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lost_item_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
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
        sa.Column("ride_id", sa.Integer(), sa.ForeignKey("rides.id"), nullable=True),
        sa.Column("reporter_type", sa.String(10), nullable=False),
        sa.Column("reporter_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "electronics", "clothing", "documents", "keys", "bag", "jewelry", "other",
                name="lostitemcategory",
            ),
            nullable=False,
        ),
        sa.Column("color", sa.String(100), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "reported", "matched", "claimed", "returned", "donated", "discarded",
                name="lostitemstatus",
            ),
            nullable=False,
            server_default="reported",
        ),
        sa.Column(
            "matched_report_id",
            sa.Integer(),
            sa.ForeignKey("lost_item_reports.id"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("contact_phone", sa.String(30), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
    )
    op.create_index("ix_lost_item_reports_reporter_id", "lost_item_reports", ["reporter_id"])
    op.create_index("ix_lost_item_reports_ride_id", "lost_item_reports", ["ride_id"])
    op.create_index("ix_lost_item_reports_status", "lost_item_reports", ["status"])
    op.create_index("ix_lost_item_reports_created_at", "lost_item_reports", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_lost_item_reports_created_at", table_name="lost_item_reports")
    op.drop_index("ix_lost_item_reports_status", table_name="lost_item_reports")
    op.drop_index("ix_lost_item_reports_ride_id", table_name="lost_item_reports")
    op.drop_index("ix_lost_item_reports_reporter_id", table_name="lost_item_reports")
    op.drop_table("lost_item_reports")
    op.execute("DROP TYPE IF EXISTS lostitemstatus")
    op.execute("DROP TYPE IF EXISTS lostitemcategory")
