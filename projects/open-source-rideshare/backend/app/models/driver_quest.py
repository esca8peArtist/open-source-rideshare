"""Driver bonus and quest programs.

Admins create time-limited bonus challenges for drivers. Drivers view active
quests, track their progress, and claim bonuses when they complete a challenge.
This is the industry-standard mechanism for stimulating driver supply during
peak periods or geographic coverage gaps.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
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


class QuestType(str, enum.Enum):
    ride_count = "ride_count"
    earnings_target = "earnings_target"
    acceptance_rate = "acceptance_rate"
    peak_hours_rides = "peak_hours_rides"


class QuestProgressStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    claimed = "claimed"
    expired = "expired"
    ineligible = "ineligible"


class DriverQuest(Base):
    """A bonus challenge definition created by an admin."""

    __tablename__ = "driver_quests"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    quest_type: Mapped[QuestType] = mapped_column(Enum(QuestType))

    # Target the driver must reach to complete the quest.
    # Interpretation depends on quest_type:
    #   ride_count       — number of rides
    #   earnings_target  — amount in cents
    #   acceptance_rate  — percentage (0-100)
    #   peak_hours_rides — number of rides during peak hours
    target_value: Mapped[float] = mapped_column(Numeric(12, 2))

    # Payout in cents when the driver claims a completed quest.
    bonus_amount_cents: Mapped[int] = mapped_column(Integer)

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Optional eligibility filter — driver rating must be >= this value.
    min_rating: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)

    # Optional geographic restriction — null means all zones.
    zone_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_areas.id"), nullable=True, index=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    zone = relationship("ServiceArea", backref="quests")
    progress_records = relationship("DriverQuestProgress", back_populates="quest")


class DriverQuestProgress(Base):
    """Per-driver tracking record for a single quest."""

    __tablename__ = "driver_quest_progress"

    id: Mapped[int] = mapped_column(primary_key=True)

    quest_id: Mapped[int] = mapped_column(
        ForeignKey("driver_quests.id"), index=True
    )
    driver_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), index=True
    )

    current_value: Mapped[float] = mapped_column(Numeric(12, 2), default=0)

    status: Mapped[QuestProgressStatus] = mapped_column(
        Enum(QuestProgressStatus), default=QuestProgressStatus.active
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    bonus_paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "quest_id",
            "driver_profile_id",
            name="uq_driver_quest_progress_quest_driver",
        ),
    )

    quest = relationship("DriverQuest", back_populates="progress_records")
    driver_profile = relationship("DriverProfile", backref="quest_progress")
