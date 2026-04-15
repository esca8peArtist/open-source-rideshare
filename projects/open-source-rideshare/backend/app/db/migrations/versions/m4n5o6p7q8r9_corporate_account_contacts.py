"""Corporate account contacts.

Enterprise accounts need to register non-billing operational contacts for
account issues, travel policy questions, employee onboarding, and legal/
compliance matters.

Tables created:
  corporate_account_contacts — one row per operational contact.

Enums created:
  contactrole — primary / travel_coordinator / it_admin / hr / legal / other

Revision ID: m4n5o6p7q8r9
Revises:     l3m4n5o6p7q8
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "m4n5o6p7q8r9"
down_revision: str = "l3m4n5o6p7q8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum
    contactrole = postgresql.ENUM(
        "primary",
        "travel_coordinator",
        "it_admin",
        "hr",
        "legal",
        "other",
        name="contactrole",
    )
    contactrole.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "corporate_account_contacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("title", sa.String(150), nullable=True),
        sa.Column(
            "contact_role",
            sa.Enum(
                "primary",
                "travel_coordinator",
                "it_admin",
                "hr",
                "legal",
                "other",
                name="contactrole",
            ),
            nullable=False,
            server_default="other",
        ),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("added_by_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["added_by_id"],
            ["users.id"],
        ),
        sa.UniqueConstraint(
            "account_id", "email", name="uq_account_contact_email"
        ),
    )

    op.create_index(
        "ix_corp_account_contacts_account_id",
        "corporate_account_contacts",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_account_contacts_role",
        "corporate_account_contacts",
        ["contact_role"],
    )
    # Partial index — at most one primary per account
    op.create_index(
        "ix_corp_account_contacts_primary",
        "corporate_account_contacts",
        ["account_id", "is_primary"],
        postgresql_where=sa.text("is_primary = true"),
    )
    op.create_index(
        "ix_corp_account_contacts_active",
        "corporate_account_contacts",
        ["account_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_account_contacts_active",
        table_name="corporate_account_contacts",
    )
    op.drop_index(
        "ix_corp_account_contacts_primary",
        table_name="corporate_account_contacts",
    )
    op.drop_index(
        "ix_corp_account_contacts_role",
        table_name="corporate_account_contacts",
    )
    op.drop_index(
        "ix_corp_account_contacts_account_id",
        table_name="corporate_account_contacts",
    )
    op.drop_table("corporate_account_contacts")
    sa.Enum(name="contactrole").drop(op.get_bind(), checkfirst=True)
