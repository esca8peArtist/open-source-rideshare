"""add user_blocklist table

Revision ID: o1p2q3r4s5t6
Revises: n1o2p3q4r5s6
Create Date: 2026-04-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'o1p2q3r4s5t6'
down_revision: Union[str, Sequence[str], None] = 'n1o2p3q4r5s6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_blocklist",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("blocker_id", sa.Integer(), nullable=False),
        sa.Column("blocked_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["blocker_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blocked_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("blocker_id", "blocked_id", name="uq_user_blocklist_pair"),
    )
    op.create_index("ix_user_blocklist_blocker_id", "user_blocklist", ["blocker_id"])
    op.create_index("ix_user_blocklist_blocked_id", "user_blocklist", ["blocked_id"])


def downgrade() -> None:
    op.drop_index("ix_user_blocklist_blocked_id", table_name="user_blocklist")
    op.drop_index("ix_user_blocklist_blocker_id", table_name="user_blocklist")
    op.drop_table("user_blocklist")
