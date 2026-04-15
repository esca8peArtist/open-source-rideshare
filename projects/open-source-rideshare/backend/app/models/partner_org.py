"""Community Partner Organization models.

Cooperative rideshare platforms can partner with community organizations
(hospitals, social service agencies, transit authorities, NGOs) to fund rides
for their clients — bridging the last-mile gap for people who cannot easily
pay for transport themselves.

Example use cases
-----------------
  - Hospital issues $200 credit to a patient for post-discharge follow-up rides
  - Social services agency pre-pays transport for job-training program participants
  - Transit authority subsidises first/last mile connections to transit hubs

Design
------
PartnerOrganization — the org account.  One designated user (partner_admin_user_id)
    can log in with their normal credentials and view their org's credit activity.

PartnerCreditGrant — a credit issued to one specific rider for a stated purpose.
    Has a dollar ceiling, optional per-ride cap, and optional expiry.
    Status: active → exhausted (all funds used) / expired / revoked.

PartnerCreditUsage — records how much of a grant was applied to one ride.
    Created when the ride completes and a grant was active.

Tables
------
partner_organizations
partner_credit_grants
partner_credit_usages
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PartnerOrgType(str, enum.Enum):
    healthcare = "healthcare"
    social_services = "social_services"
    education = "education"
    transit_authority = "transit_authority"
    nonprofit = "nonprofit"
    government = "government"
    other = "other"


class PartnerOrgStatus(str, enum.Enum):
    pending = "pending"       # submitted; awaiting admin approval
    active = "active"         # approved and can issue credits
    suspended = "suspended"   # temporarily disabled
    terminated = "terminated" # permanently closed


class PartnerCreditStatus(str, enum.Enum):
    active = "active"         # grant is usable
    exhausted = "exhausted"   # all funds consumed
    expired = "expired"       # expiry_date passed without full use
    revoked = "revoked"       # admin or partner cancelled the grant


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class PartnerOrganization(Base):
    """A community organization registered as a rideshare partner.

    The platform admin approves the account.  The `partner_admin_user_id`
    identifies a normal platform user who is designated as the org's point of
    contact — they can view their org's data via the /partner/me/ endpoints.
    """

    __tablename__ = "partner_organizations"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    org_type: Mapped[PartnerOrgType] = mapped_column(
        SAEnum(PartnerOrgType, name="partnerorgtype"),
        nullable=False,
    )
    status: Mapped[PartnerOrgStatus] = mapped_column(
        SAEnum(PartnerOrgStatus, name="partnerorgstatus"),
        nullable=False,
        default=PartnerOrgStatus.pending,
        server_default="pending",
    )

    # Contact information
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # The platform user who manages this org's credit activity
    partner_admin_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Optional billing controls
    monthly_credit_limit_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
        comment="Max USD the org may issue in any calendar month; NULL = no limit",
    )

    # Notes
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    credit_grants: Mapped[list[PartnerCreditGrant]] = relationship(
        "PartnerCreditGrant",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    partner_admin: Mapped["User | None"] = relationship(  # type: ignore[name-defined]
        "User",
        foreign_keys=[partner_admin_user_id],
    )


class PartnerCreditGrant(Base):
    """A credit granted by a partner org to one specific rider.

    The rider can use up to `amount_usd` across one or more rides.
    Each ride may use at most `per_ride_cap_usd` of the grant (if set).
    Remaining balance is tracked via the relationship to PartnerCreditUsage.
    """

    __tablename__ = "partner_credit_grants"

    id: Mapped[int] = mapped_column(primary_key=True)

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("partner_organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    rider_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    issued_by_admin_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[PartnerCreditStatus] = mapped_column(
        SAEnum(PartnerCreditStatus, name="partnercreditstatus"),
        nullable=False,
        default=PartnerCreditStatus.active,
        server_default="active",
    )

    # Credit configuration
    amount_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Total grant amount in USD",
    )
    amount_used_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
        comment="Cumulative amount consumed by ride usages",
    )
    per_ride_cap_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Maximum credit applied per single ride; NULL = no per-ride cap",
    )

    # Metadata
    purpose: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Human-readable reason (e.g. 'Post-discharge follow-up visits')",
    )
    expiry_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="Date after which the grant cannot be used; NULL = never expires",
    )

    # Revocation
    revoked_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    organization: Mapped[PartnerOrganization] = relationship(
        "PartnerOrganization",
        back_populates="credit_grants",
    )
    usages: Mapped[list[PartnerCreditUsage]] = relationship(
        "PartnerCreditUsage",
        back_populates="grant",
        cascade="all, delete-orphan",
    )
    rider: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User",
        foreign_keys=[rider_id],
    )

    @property
    def amount_remaining_usd(self) -> Decimal:
        return self.amount_usd - self.amount_used_usd


class PartnerCreditUsage(Base):
    """Records how much of a credit grant was applied to one completed ride.

    Created after the ride completes and a grant contribution was calculated.
    Immutable once created — corrections are handled by the admin via notes,
    not by editing records.
    """

    __tablename__ = "partner_credit_usages"

    id: Mapped[int] = mapped_column(primary_key=True)

    grant_id: Mapped[int] = mapped_column(
        ForeignKey("partner_credit_grants.id", ondelete="CASCADE"),
        nullable=False,
    )
    ride_id: Mapped[int] = mapped_column(
        ForeignKey("rides.id", ondelete="RESTRICT"),
        nullable=False,
    )

    amount_applied_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Amount of the grant deducted for this ride",
    )

    # Note: one grant can have at most one usage record per ride
    __table_args__ = (
        UniqueConstraint("grant_id", "ride_id", name="uq_partner_credit_usage_grant_ride"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    grant: Mapped[PartnerCreditGrant] = relationship(
        "PartnerCreditGrant",
        back_populates="usages",
    )
