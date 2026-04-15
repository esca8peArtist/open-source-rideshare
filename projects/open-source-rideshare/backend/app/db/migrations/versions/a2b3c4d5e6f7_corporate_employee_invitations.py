"""Add corporate_employee_invitations table.

Corporate account admins issue email-based invitation tokens to onboard
employees.  The invitee accepts the token to become a BusinessAccountMember
without additional admin intervention.

Tables created:
  corporate_employee_invitations — invitation tokens with lifecycle state,
                                   expiry window, role, and audit fields.

Enums created:
  invitationstatus  — pending / accepted / revoked / expired
  invitationrole    — admin / member

Revision ID: a2b3c4d5e6f7
Revises:     z2a3b4c5d6e7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

revision = "a2b3c4d5e6f7"
down_revision = "z2a3b4c5d6e7"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # Enums
    invitationstatus = postgresql.ENUM(
        "pending", "accepted", "revoked", "expired",
        name="invitationstatus",
        create_type=False,
    )
    invitationstatus.create(op.get_bind(), checkfirst=True)

    invitationrole = postgresql.ENUM(
        "admin", "member",
        name="invitationrole",
        create_type=False,
    )
    invitationrole.create(op.get_bind(), checkfirst=True)

    # Table
    op.create_table(
        "corporate_employee_invitations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "token",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column(
            "invited_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "role",
            postgresql.ENUM(
                "admin", "member", name="invitationrole", create_type=False
            ),
            nullable=False,
            server_default="member",
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending", "accepted", "revoked", "expired",
                name="invitationstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "accepted_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revoked_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Indexes
    op.create_index(
        "ix_corp_emp_inv_account_id",
        "corporate_employee_invitations",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_emp_inv_email",
        "corporate_employee_invitations",
        ["email"],
    )
    op.create_index(
        "ix_corp_emp_inv_invited_by_id",
        "corporate_employee_invitations",
        ["invited_by_id"],
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    op.drop_index("ix_corp_emp_inv_invited_by_id", "corporate_employee_invitations")
    op.drop_index("ix_corp_emp_inv_email", "corporate_employee_invitations")
    op.drop_index("ix_corp_emp_inv_account_id", "corporate_employee_invitations")
    op.drop_table("corporate_employee_invitations")

    op.execute("DROP TYPE IF EXISTS invitationstatus")
    op.execute("DROP TYPE IF EXISTS invitationrole")
