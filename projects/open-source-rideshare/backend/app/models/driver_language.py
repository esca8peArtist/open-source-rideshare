"""Driver Language Skills & Rider Language Preference models.

Drivers register which languages they speak and their proficiency level.
Riders can set a preferred language so the matching engine surfaces
language-compatible drivers first.

Unlike Uber/Lyft (which have no structured language matching), this gives
non-English-speaking communities meaningful access to drivers who speak
their language — a cooperative accessibility commitment.
"""

from __future__ import annotations

import enum

from sqlalchemy import Boolean, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class LanguageProficiency(str, enum.Enum):
    BASIC = "basic"                  # can handle simple directions and greetings
    CONVERSATIONAL = "conversational"  # comfortable everyday conversation
    FLUENT = "fluent"                # near-native; can discuss complex topics
    NATIVE = "native"                # mother tongue


class DriverLanguage(Base):
    """A language a driver speaks, with self-reported proficiency level."""

    __tablename__ = "driver_languages"
    __table_args__ = (
        UniqueConstraint("driver_id", "language_code", name="uq_driver_language"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # ISO 639-1 two-letter code (e.g. "en", "es", "zh", "ar") stored lowercase
    language_code: Mapped[str] = mapped_column(String(10), index=True)
    # Human-readable name stored for display without repeated lookup
    language_name: Mapped[str] = mapped_column(String(100))
    proficiency: Mapped[LanguageProficiency] = mapped_column(
        Enum(LanguageProficiency), default=LanguageProficiency.CONVERSATIONAL
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    driver = relationship("User", foreign_keys=[driver_id], backref="languages")


class RiderLanguagePreference(Base):
    """A rider's preferred language for driver matching.

    Soft preference only — matching proceeds without it if no matching driver
    is available. One row per rider (upsert on update).
    """

    __tablename__ = "rider_language_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    rider_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, index=True
    )
    language_code: Mapped[str] = mapped_column(String(10))
    language_name: Mapped[str] = mapped_column(String(100))

    rider = relationship("User", foreign_keys=[rider_id], backref="language_preference")
