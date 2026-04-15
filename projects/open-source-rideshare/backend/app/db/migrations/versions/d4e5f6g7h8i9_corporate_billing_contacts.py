"""Add corporate_billing_contacts table.

Enterprise accounts can designate billing contacts who receive invoices and
financial notifications.  Contacts do not need to be platform users.

Tables created:
  corporate_billing_contacts — designated billing contacts per corporate account

Revision ID: d4e5f6g7h8i9
Revises:     c3d4e5f6g7h8
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

revision = "d4e5f6g7h8i9"
down_revision = "c3d4e5f6g7h8"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "corporate_billing_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("role", sa.String(100), nullable=True),
        sa.Column(
            "receives_invoices",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "receives_budget_alerts",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "receives_monthly_summary",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "added_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
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
        sa.UniqueConstraint(
            "account_id", "email", name="uq_billing_contact_account_email"
        ),
    )
    op.create_index(
        "ix_corporate_billing_contacts_account_id",
        "corporate_billing_contacts",
        ["account_id"],
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    op.drop_index(
        "ix_corporate_billing_contacts_account_id",
        table_name="corporate_billing_contacts",
    )
    op.drop_table("corporate_billing_contacts")
