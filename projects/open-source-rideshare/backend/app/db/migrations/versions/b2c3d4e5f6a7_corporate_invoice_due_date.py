"""Add due_date and payment_terms_days to corporate_invoices_v2.

Businesses need to know when invoices are due and track overdue invoices.
payment_terms_days stores the net-payment window (e.g. 30 = Net-30).
due_date is auto-populated on finalization when payment_terms_days is set,
or can be set manually.

Revision ID: b2c3d4e5f6a7
Revises:     a1b2c3d4e5f6
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "corporate_invoices_v2",
        sa.Column("payment_terms_days", sa.Integer, nullable=True),
    )
    op.add_column(
        "corporate_invoices_v2",
        sa.Column("due_date", sa.Date, nullable=True),
    )
    op.create_index(
        "ix_corp_inv_due_date",
        "corporate_invoices_v2",
        ["due_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_corp_inv_due_date", "corporate_invoices_v2")
    op.drop_column("corporate_invoices_v2", "due_date")
    op.drop_column("corporate_invoices_v2", "payment_terms_days")
