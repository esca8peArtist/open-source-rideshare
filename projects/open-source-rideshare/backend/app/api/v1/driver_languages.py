"""Driver Language Skills & Rider Language Preference endpoints.

Public endpoints:
  GET  /drivers/{driver_id}/languages           — any driver's language profile

Authenticated driver endpoints:
  GET    /drivers/me/languages                  — my registered languages
  POST   /drivers/me/languages                  — add or update a language
  DELETE /drivers/me/languages/{language_code}  — remove a language

Authenticated rider endpoints:
  GET    /riders/me/language-preference         — my preferred driver language
  PUT    /riders/me/language-preference         — set or update preference
  DELETE /riders/me/language-preference         — clear preference

Admin endpoints:
  GET  /admin/language-coverage-stats           — platform language statistics
  GET  /admin/drivers/{driver_id}/languages     — any driver's languages (admin view)

Cooperative differentiator: enables language-matched rides for non-English-speaking
communities — a genuine accessibility commitment that Uber/Lyft have never made.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.driver_language import LanguageProficiency
from app.models.user import User
from app.schemas.driver_language import (
    DriverLanguageListResponse,
    DriverLanguageResponse,
    LanguageCoverageStats,
    RemoveDriverLanguageRequest,
    RiderLanguagePreferenceResponse,
    SetDriverLanguageRequest,
    SetRiderLanguagePreferenceRequest,
)
from app.services.driver_language import (
    clear_rider_language_preference,
    get_driver_languages,
    get_language_coverage_stats,
    get_rider_language_preference,
    remove_driver_language,
    set_driver_language,
    set_rider_language_preference,
)

router = APIRouter(tags=["driver-languages"])


# ---------------------------------------------------------------------------
# Public: any driver's language profile
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/{driver_id}/languages",
    response_model=DriverLanguageListResponse,
    summary="List a driver's registered languages",
)
async def list_driver_languages_public(
    driver_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Return all languages registered by a driver.

    Shown to riders during matching — lets them confirm whether their
    preferred language driver is available before booking.
    """
    langs = await get_driver_languages(db, driver_id)
    responses = [DriverLanguageResponse.model_validate(lang) for lang in langs]
    return DriverLanguageListResponse(
        driver_id=driver_id,
        languages=responses,
        total=len(responses),
    )


# ---------------------------------------------------------------------------
# Driver: manage own languages
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/languages",
    response_model=DriverLanguageListResponse,
    summary="View my registered languages",
)
async def my_languages(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all languages the authenticated driver has registered."""
    langs = await get_driver_languages(db, user.id)
    responses = [DriverLanguageResponse.model_validate(lang) for lang in langs]
    return DriverLanguageListResponse(
        driver_id=user.id,
        languages=responses,
        total=len(responses),
    )


@router.post(
    "/drivers/me/languages",
    response_model=DriverLanguageResponse,
    status_code=status.HTTP_200_OK,
    summary="Add or update a language on my profile",
)
async def upsert_my_language(
    body: SetDriverLanguageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a new language or update the proficiency for an existing one.

    If ``is_primary`` is True, any previous primary language is automatically
    demoted — a driver has at most one primary language.
    """
    lang = await set_driver_language(
        db,
        driver_id=user.id,
        language_code=body.language_code,
        language_name=body.language_name,
        proficiency=body.proficiency,
        is_primary=body.is_primary,
    )
    return DriverLanguageResponse.model_validate(lang)


@router.delete(
    "/drivers/me/languages/{language_code}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a language from my profile",
)
async def delete_my_language(
    language_code: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a language from the authenticated driver's profile.

    Returns 404 if the language is not registered.
    """
    await remove_driver_language(db, driver_id=user.id, language_code=language_code)


# ---------------------------------------------------------------------------
# Rider: language preference
# ---------------------------------------------------------------------------


@router.get(
    "/riders/me/language-preference",
    response_model=RiderLanguagePreferenceResponse,
    summary="Get my driver language preference",
)
async def my_language_preference(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated rider's current language preference.

    Returns 404 if no preference has been set.
    """
    from fastapi import HTTPException
    pref = await get_rider_language_preference(db, user.id)
    if pref is None:
        raise HTTPException(status_code=404, detail="No language preference set")
    return RiderLanguagePreferenceResponse.model_validate(pref)


@router.put(
    "/riders/me/language-preference",
    response_model=RiderLanguagePreferenceResponse,
    status_code=status.HTTP_200_OK,
    summary="Set or update my driver language preference",
)
async def set_my_language_preference(
    body: SetRiderLanguagePreferenceRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set or update the rider's preferred driver language.

    This is a soft preference — the matching engine will surface
    language-compatible drivers first but will not block a ride if none
    are available.
    """
    pref = await set_rider_language_preference(
        db,
        rider_id=user.id,
        language_code=body.language_code,
        language_name=body.language_name,
    )
    return RiderLanguagePreferenceResponse.model_validate(pref)


@router.delete(
    "/riders/me/language-preference",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear my driver language preference",
)
async def clear_my_language_preference(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove the rider's language preference.

    Returns 404 if no preference is currently set.
    """
    await clear_rider_language_preference(db, rider_id=user.id)


# ---------------------------------------------------------------------------
# Admin: language coverage statistics
# ---------------------------------------------------------------------------


@router.get(
    "/admin/language-coverage-stats",
    response_model=LanguageCoverageStats,
    summary="Platform-wide driver language coverage statistics",
    dependencies=[Depends(require_admin)],
)
async def admin_language_stats(
    db: AsyncSession = Depends(get_db),
):
    """Admin: platform-wide language coverage statistics.

    Shows which languages drivers speak, how many drivers per language,
    and how many fluent/native speakers are available — useful for cooperative
    diversity reporting and targeting outreach to underserved communities.
    """
    stats = await get_language_coverage_stats(db)
    return LanguageCoverageStats(**stats)


@router.get(
    "/admin/drivers/{driver_id}/languages",
    response_model=DriverLanguageListResponse,
    summary="Admin: view any driver's language profile",
    dependencies=[Depends(require_admin)],
)
async def admin_driver_languages(
    driver_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Admin: return all languages registered by any driver."""
    langs = await get_driver_languages(db, driver_id)
    responses = [DriverLanguageResponse.model_validate(lang) for lang in langs]
    return DriverLanguageListResponse(
        driver_id=driver_id,
        languages=responses,
        total=len(responses),
    )
