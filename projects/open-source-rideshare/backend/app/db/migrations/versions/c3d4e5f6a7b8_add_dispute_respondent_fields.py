"""add dispute respondent fields

Adds respondent_response (Text, nullable) and respondent_responded_at
(DateTime with timezone, nullable) to the disputes table so the non-filing
ride participant can submit their side of a dispute.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "disputes",
        sa.Column("respondent_response", sa.Text(), nullable=True),
    )
    op.add_column(
        "disputes",
        sa.Column(
            "respondent_responded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("disputes", "respondent_responded_at")
    op.drop_column("disputes", "respondent_response")
