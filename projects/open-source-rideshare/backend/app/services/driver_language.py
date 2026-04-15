"""Driver Language Skills & Rider Language Preference service layer.

Public functions:
  set_driver_language          — add or update a language on a driver's profile
  remove_driver_language       — remove a language from a driver's profile
  get_driver_languages         — list all languages registered by a driver
  set_rider_language_preference — set or update a rider's preferred language
  get_rider_language_preference — get a rider's current language preference
  clear_rider_language_preference — remove a rider's language preference
  get_language_coverage_stats  — admin: platform-wide language coverage
  get_drivers_by_language      — list driver IDs who speak a given language
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_language import (
    DriverLanguage,
    LanguageProficiency,
    RiderLanguagePreference,
)
from app.schemas.driver_language import LanguageStatEntry


# ---------------------------------------------------------------------------
# Driver language management
# ---------------------------------------------------------------------------


async def set_driver_language(
    db: AsyncSession,
    driver_id: int,
    language_code: str,
    language_name: str,
    proficiency: LanguageProficiency = LanguageProficiency.CONVERSATIONAL,
    is_primary: bool = False,
) -> DriverLanguage:
    """Add or update a language on a driver's profile.

    If ``is_primary`` is True, any previously marked primary language is
    cleared first so there is at most one primary language per driver.

    Upserts by (driver_id, language_code) — safe to call repeatedly.
    """
    # If flagging as primary, clear the existing primary first
    if is_primary:
        existing_primary_result = await db.execute(
            select(DriverLanguage).where(
                DriverLanguage.driver_id == driver_id,
                DriverLanguage.is_primary.is_(True),
            )
        )
        old_primary = existing_primary_result.scalar_one_or_none()
        if old_primary is not None and old_primary.language_code != language_code:
            old_primary.is_primary = False

    # Upsert
    result = await db.execute(
        select(DriverLanguage).where(
            DriverLanguage.driver_id == driver_id,
            DriverLanguage.language_code == language_code,
        )
    )
    lang = result.scalar_one_or_none()

    if lang is not None:
        lang.language_name = language_name
        lang.proficiency = proficiency
        lang.is_primary = is_primary
    else:
        lang = DriverLanguage(
            driver_id=driver_id,
            language_code=language_code,
            language_name=language_name,
            proficiency=proficiency,
            is_primary=is_primary,
        )
        db.add(lang)

    await db.flush()
    return lang


async def remove_driver_language(
    db: AsyncSession,
    driver_id: int,
    language_code: str,
) -> None:
    """Remove a language from a driver's profile.

    Raises 404 if the driver has not registered that language.
    """
    result = await db.execute(
        select(DriverLanguage).where(
            DriverLanguage.driver_id == driver_id,
            DriverLanguage.language_code == language_code,
        )
    )
    lang = result.scalar_one_or_none()
    if lang is None:
        raise HTTPException(
            status_code=404,
            detail=f"Language '{language_code}' not found on driver profile",
        )
    await db.delete(lang)
    await db.flush()


async def get_driver_languages(
    db: AsyncSession,
    driver_id: int,
) -> list[DriverLanguage]:
    """Return all languages registered by a driver, primary first then alphabetical."""
    result = await db.execute(
        select(DriverLanguage)
        .where(DriverLanguage.driver_id == driver_id)
        .order_by(DriverLanguage.is_primary.desc(), DriverLanguage.language_code)
    )
    return list(result.scalars().all())


async def get_drivers_by_language(
    db: AsyncSession,
    language_code: str,
    min_proficiency: Optional[LanguageProficiency] = None,
) -> list[int]:
    """Return driver_ids who speak a given language.

    Optionally filter to a minimum proficiency level.  Proficiency order:
      basic < conversational < fluent < native
    """
    _ORDER = [
        LanguageProficiency.BASIC,
        LanguageProficiency.CONVERSATIONAL,
        LanguageProficiency.FLUENT,
        LanguageProficiency.NATIVE,
    ]
    stmt = select(DriverLanguage.driver_id).where(
        DriverLanguage.language_code == language_code
    )
    if min_proficiency is not None:
        min_index = _ORDER.index(min_proficiency)
        allowed = _ORDER[min_index:]
        stmt = stmt.where(DriverLanguage.proficiency.in_(allowed))

    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Rider language preference
# ---------------------------------------------------------------------------


async def set_rider_language_preference(
    db: AsyncSession,
    rider_id: int,
    language_code: str,
    language_name: str,
) -> RiderLanguagePreference:
    """Set or update the rider's preferred driver language (upsert)."""
    result = await db.execute(
        select(RiderLanguagePreference).where(
            RiderLanguagePreference.rider_id == rider_id
        )
    )
    pref = result.scalar_one_or_none()

    if pref is not None:
        pref.language_code = language_code
        pref.language_name = language_name
    else:
        pref = RiderLanguagePreference(
            rider_id=rider_id,
            language_code=language_code,
            language_name=language_name,
        )
        db.add(pref)

    await db.flush()
    return pref


async def get_rider_language_preference(
    db: AsyncSession,
    rider_id: int,
) -> Optional[RiderLanguagePreference]:
    """Return the rider's current language preference, or None if not set."""
    result = await db.execute(
        select(RiderLanguagePreference).where(
            RiderLanguagePreference.rider_id == rider_id
        )
    )
    return result.scalar_one_or_none()


async def clear_rider_language_preference(
    db: AsyncSession,
    rider_id: int,
) -> None:
    """Remove the rider's language preference.

    Raises 404 if no preference is currently set.
    """
    result = await db.execute(
        select(RiderLanguagePreference).where(
            RiderLanguagePreference.rider_id == rider_id
        )
    )
    pref = result.scalar_one_or_none()
    if pref is None:
        raise HTTPException(
            status_code=404,
            detail="No language preference set for this rider",
        )
    await db.delete(pref)
    await db.flush()


# ---------------------------------------------------------------------------
# Admin statistics
# ---------------------------------------------------------------------------


async def get_language_coverage_stats(db: AsyncSession) -> dict:
    """Return platform-wide language coverage statistics for the admin dashboard."""
    # Total entries
    total_row = await db.execute(select(func.count()).select_from(DriverLanguage))
    total_entries = total_row.scalar() or 0

    # Distinct language codes
    distinct_row = await db.execute(
        select(func.count(func.distinct(DriverLanguage.language_code)))
    )
    distinct_langs = distinct_row.scalar() or 0

    # Per-language: driver count and fluent/native count
    per_lang_rows = await db.execute(
        select(
            DriverLanguage.language_code,
            DriverLanguage.language_name,
            func.count().label("driver_count"),
        )
        .group_by(DriverLanguage.language_code, DriverLanguage.language_name)
        .order_by(func.count().desc())
        .limit(20)
    )
    per_lang = {
        row.language_code: {
            "language_code": row.language_code,
            "language_name": row.language_name,
            "driver_count": row.driver_count,
            "fluent_or_native_count": 0,
        }
        for row in per_lang_rows
    }

    # Fluent/native counts
    fluent_rows = await db.execute(
        select(
            DriverLanguage.language_code,
            func.count().label("cnt"),
        )
        .where(
            DriverLanguage.proficiency.in_(
                [LanguageProficiency.FLUENT, LanguageProficiency.NATIVE]
            )
        )
        .group_by(DriverLanguage.language_code)
    )
    for row in fluent_rows:
        if row.language_code in per_lang:
            per_lang[row.language_code]["fluent_or_native_count"] = row.cnt

    # Rider preferences set
    pref_row = await db.execute(
        select(func.count()).select_from(RiderLanguagePreference)
    )
    rider_prefs = pref_row.scalar() or 0

    return {
        "total_driver_language_entries": total_entries,
        "distinct_languages": distinct_langs,
        "top_languages": [
            LanguageStatEntry(**entry) for entry in per_lang.values()
        ],
        "rider_preferences_set": rider_prefs,
    }
