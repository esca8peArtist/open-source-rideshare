"""Corporate Service Zone model.

Corporate accounts define named geographic zones that control where employees
may book rides to or from.  A zone is a circle defined by a centre point and a
radius.  Each zone carries a ``zone_type`` that dictates the booking behaviour
when a ride's pickup or dropoff point falls inside it:

  - ``allowed``            – rides within this zone are explicitly permitted
                             (useful for allow-listing when the default is to
                             block everything outside configured zones)
  - ``restricted``         – rides whose pickup or dropoff falls in this zone
                             are blocked outright
  - ``approval_required``  – rides touching this zone require admin approval
                             before they can proceed

``applies_to`` controls whether the zone is evaluated against the pickup
location, the dropoff location, or both.

Optionally ``group_ids`` scopes the zone to specific employee groups; if
NULL the zone applies to every member of the account.

Table:
  corporate_service_zones — one row per named zone per account.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ZoneType(str, Enum):
    """Controls how a ride is affected when a location falls within the zone."""

    allowed = "allowed"
    restricted = "restricted"
    approval_required = "approval_required"


class ZoneAppliesTo(str, Enum):
    """Which ride endpoint(s) the zone is evaluated against."""

    pickup = "pickup"
    dropoff = "dropoff"
    both = "both"


class CorporateServiceZone(Base):
    """A circular geographic zone that restricts or gates corporate ride bookings.

    Admins define zones to enforce geographic constraints on their account —
    for example, restricting rides to/from certain neighbourhoods, requiring
    approval for airport trips, or explicitly allow-listing HQ and known client
    offices.

    Distance checks use the Haversine formula computed in the service layer
    (no PostGIS dependency required).

    Attributes:
        id: Integer primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        created_by_id: FK to users (SET NULL on deletion).
        name: Human-readable zone name, unique per account.
        description: Optional longer description of the zone's purpose.
        zone_type: One of ``allowed``, ``restricted``, ``approval_required``.
        center_latitude: Latitude of the zone centre.
        center_longitude: Longitude of the zone centre.
        radius_km: Radius of the circle in kilometres (must be > 0).
        applies_to: Whether the zone applies to pickup, dropoff, or both.
        group_ids: Optional JSON array of employee group IDs this zone applies
            to.  NULL means the zone applies to all account members.
        is_active: When False the zone is ignored by the eligibility checker.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_service_zones"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "name", name="uq_corp_service_zone_account_name"
        ),
        Index("ix_corp_service_zone_account_id", "account_id"),
        Index("ix_corp_service_zone_is_active", "is_active"),
        Index("ix_corp_service_zone_zone_type", "zone_type"),
        Index("ix_corp_service_zone_applies_to", "applies_to"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    zone_type: Mapped[ZoneType] = mapped_column(
        SAEnum(ZoneType, name="zonetype", create_type=True),
        nullable=False,
    )

    center_latitude: Mapped[sa.Numeric] = mapped_column(
        Numeric(9, 6), nullable=False
    )

    center_longitude: Mapped[sa.Numeric] = mapped_column(
        Numeric(9, 6), nullable=False
    )

    radius_km: Mapped[sa.Numeric] = mapped_column(
        Numeric(8, 3), nullable=False
    )

    applies_to: Mapped[ZoneAppliesTo] = mapped_column(
        SAEnum(ZoneAppliesTo, name="zoneappliesto", create_type=True),
        nullable=False,
        default=ZoneAppliesTo.both,
    )

    # Optional: JSON array of employee_group IDs.  NULL = applies to everyone.
    group_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ---- Relationships ----

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="raise")
