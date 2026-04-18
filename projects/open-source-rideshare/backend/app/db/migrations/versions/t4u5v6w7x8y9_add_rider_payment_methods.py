"""add rider_payment_methods table

Revision ID: t4u5v6w7x8y9
Revises: s3t4u5v6w7x8
Create Date: 2026-04-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 't4u5v6w7x8y9'
down_revision: Union[str, Sequence[str], None] = 's3t4u5v6w7x8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rider_payment_methods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "stripe_payment_method_id",
            sa.String(255),
            nullable=False,
            unique=True,
        ),
        sa.Column("card_brand", sa.String(50), nullable=False),
        sa.Column("card_last4", sa.String(4), nullable=False),
        sa.Column("card_exp_month", sa.Integer(), nullable=False),
        sa.Column("card_exp_year", sa.Integer(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("rider_payment_methods")
