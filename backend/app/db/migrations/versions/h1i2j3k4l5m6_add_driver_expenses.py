"""add driver expenses table

Revision ID: h1i2j3k4l5m6
Revises: g1h2i3j4k5l6
Create Date: 2026-04-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'h1i2j3k4l5m6'
down_revision: Union[str, Sequence[str], None] = 'g1h2i3j4k5l6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "driver_expenses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "driver_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "category",
            sa.Enum(
                "mileage",
                "fuel",
                "vehicle_maintenance",
                "phone",
                "tolls",
                "insurance",
                "other",
                name="expensecategory",
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column(
            "is_deductible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_driver_expenses_driver_id",
        "driver_expenses",
        ["driver_id"],
    )
    op.create_index(
        "idx_driver_expenses_expense_date",
        "driver_expenses",
        ["expense_date"],
    )
    op.create_index(
        "idx_driver_expenses_driver_date",
        "driver_expenses",
        ["driver_id", "expense_date"],
    )


def downgrade() -> None:
    op.drop_index("idx_driver_expenses_driver_date", table_name="driver_expenses")
    op.drop_index("idx_driver_expenses_expense_date", table_name="driver_expenses")
    op.drop_index("idx_driver_expenses_driver_id", table_name="driver_expenses")
    op.drop_table("driver_expenses")
    op.execute("DROP TYPE IF EXISTS expensecategory")
