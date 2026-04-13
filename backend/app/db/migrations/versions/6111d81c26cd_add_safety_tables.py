"""add safety tables

Revision ID: 6111d81c26cd
Revises: d7cb1904c75e
Create Date: 2026-04-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6111d81c26cd'
down_revision: Union[str, Sequence[str], None] = 'd7cb1904c75e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sos_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("ride_id", sa.Integer(), sa.ForeignKey("rides.id"), nullable=True, index=True),
        sa.Column(
            "status",
            sa.Enum("active", "resolved", "false_alarm", name="sosstatus"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "trip_share_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ride_id", sa.Integer(), sa.ForeignKey("rides.id"), nullable=False, index=True),
        sa.Column("token", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "emergency_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("relationship_label", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("emergency_contacts")
    op.drop_table("trip_share_tokens")
    op.drop_table("sos_alerts")
    op.execute("DROP TYPE IF EXISTS sosstatus")
