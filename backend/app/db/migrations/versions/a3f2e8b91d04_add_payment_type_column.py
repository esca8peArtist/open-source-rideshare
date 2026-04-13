"""add payment_type column to payments

Revision ID: a3f2e8b91d04
Revises: 6111d81c26cd
Create Date: 2026-04-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3f2e8b91d04'
down_revision: Union[str, Sequence[str], None] = '6111d81c26cd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the enum type
    payment_type_enum = sa.Enum("ride_fare", "cancellation_fee", name="paymenttype")
    payment_type_enum.create(op.get_bind(), checkfirst=True)

    # Add payment_type column with default
    op.add_column(
        "payments",
        sa.Column(
            "payment_type",
            payment_type_enum,
            nullable=False,
            server_default="ride_fare",
        ),
    )

    # Drop the old unique constraint on ride_id alone
    op.drop_constraint("uq_payments_ride_id", "payments", type_="unique")

    # Add composite unique constraint (ride_id, payment_type)
    op.create_unique_constraint(
        "uq_payment_ride_type", "payments", ["ride_id", "payment_type"],
    )


def downgrade() -> None:
    # Drop composite unique constraint
    op.drop_constraint("uq_payment_ride_type", "payments", type_="unique")

    # Re-add simple unique constraint on ride_id
    op.create_unique_constraint("uq_payments_ride_id", "payments", ["ride_id"])

    # Drop payment_type column
    op.drop_column("payments", "payment_type")

    # Drop the enum type
    op.execute("DROP TYPE IF EXISTS paymenttype")
