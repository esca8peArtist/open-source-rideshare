"""Tests for the Driver Language Skills & Rider Language Preferences feature.

Service layer (async, mocked DB):
  1.  set_driver_language — creates new entry when none exists
  2.  set_driver_language — updates existing entry (upsert)
  3.  set_driver_language — setting is_primary clears previous primary
  4.  set_driver_language — setting is_primary on same code keeps it primary
  5.  remove_driver_language — removes existing entry
  6.  remove_driver_language — raises 404 for unknown language_code
  7.  get_driver_languages — returns all languages for a driver
  8.  get_driver_languages — returns empty list for driver with no languages
  9.  get_drivers_by_language — returns all drivers for a language code
  10. get_drivers_by_language — filters by minimum proficiency
  11. get_drivers_by_language — returns empty list for unknown language
  12. set_rider_language_preference — creates new preference
  13. set_rider_language_preference — updates existing preference (upsert)
  14. get_rider_language_preference — returns existing preference
  15. get_rider_language_preference — returns None for rider with no preference
  16. clear_rider_language_preference — removes existing preference
  17. clear_rider_language_preference — raises 404 when no preference set
  18. get_language_coverage_stats — returns correct counts and top languages

Schema validation:
  19. SetDriverLanguageRequest — valid language_code accepted
  20. SetDriverLanguageRequest — language_code normalised to lowercase
  21. SetDriverLanguageRequest — empty language_code rejected
  22. SetDriverLanguageRequest — language_code > 10 chars rejected
  23. SetDriverLanguageRequest — language_code with invalid chars rejected
  24. SetDriverLanguageRequest — proficiency defaults to conversational
  25. SetDriverLanguageRequest — is_primary defaults to False
  26. DriverLanguageResponse — from_attributes works correctly
  27. DriverLanguageListResponse — total matches languages list length
  28. SetRiderLanguagePreferenceRequest — valid request accepted
  29. RiderLanguagePreferenceResponse — from_attributes works correctly
  30. LanguageCoverageStats — top_languages can be empty list

API layer (unit-level, service functions patched):
  31. GET /drivers/{id}/languages — returns language list
  32. GET /drivers/me/languages — returns authenticated driver's languages
  33. POST /drivers/me/languages — upserts language and returns response
  34. DELETE /drivers/me/languages/{code} — removes language, returns 204
  35. GET /riders/me/language-preference — returns preference when set
  36. GET /riders/me/language-preference — returns 404 when not set
  37. PUT /riders/me/language-preference — sets preference and returns it
  38. DELETE /riders/me/language-preference — clears preference, returns 204
  39. GET /admin/language-coverage-stats — returns stats
  40. GET /admin/drivers/{id}/languages — admin view of any driver's languages
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.driver_language import DriverLanguage, LanguageProficiency, RiderLanguagePreference
from app.schemas.driver_language import (
    DriverLanguageListResponse,
    DriverLanguageResponse,
    LanguageCoverageStats,
    LanguageStatEntry,
    RiderLanguagePreferenceResponse,
    SetDriverLanguageRequest,
    SetRiderLanguagePreferenceRequest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lang(
    driver_id: int = 1,
    language_code: str = "es",
    language_name: str = "Spanish",
    proficiency: LanguageProficiency = LanguageProficiency.FLUENT,
    is_primary: bool = False,
    lang_id: int = 10,
) -> DriverLanguage:
    lang = MagicMock(spec=DriverLanguage)
    lang.id = lang_id
    lang.driver_id = driver_id
    lang.language_code = language_code
    lang.language_name = language_name
    lang.proficiency = proficiency
    lang.is_primary = is_primary
    return lang


def _make_pref(
    rider_id: int = 2,
    language_code: str = "es",
    language_name: str = "Spanish",
    pref_id: int = 20,
) -> RiderLanguagePreference:
    pref = MagicMock(spec=RiderLanguagePreference)
    pref.id = pref_id
    pref.rider_id = rider_id
    pref.language_code = language_code
    pref.language_name = language_name
    return pref


# ---------------------------------------------------------------------------
# Service layer tests
# ---------------------------------------------------------------------------


def _scalar_result(value):
    """Mock execute result with scalar_one_or_none returning value."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalars_result(values):
    """Mock execute result with scalars().all() returning values."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = values
    return r


def _scalars_list_result(values):
    """Mock execute result with scalars().all() returning values (alias)."""
    return _scalars_result(values)


@pytest.mark.asyncio
async def test_set_driver_language_creates_new():
    """1. set_driver_language creates new entry when none exists."""
    from app.services.driver_language import set_driver_language

    db = AsyncMock()
    db.flush = AsyncMock()
    # is_primary=True: first execute = primary lookup (None), second = upsert lookup (None)
    db.execute = AsyncMock(side_effect=[_scalar_result(None), _scalar_result(None)])

    await set_driver_language(db, driver_id=1, language_code="fr",
                               language_name="French",
                               proficiency=LanguageProficiency.NATIVE,
                               is_primary=True)
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_set_driver_language_upserts_existing():
    """2. set_driver_language updates existing entry when language already exists."""
    from app.services.driver_language import set_driver_language

    existing = _make_lang(language_code="es", proficiency=LanguageProficiency.BASIC)
    db = AsyncMock()
    db.flush = AsyncMock()
    # is_primary=False: only one execute (upsert lookup)
    db.execute = AsyncMock(return_value=_scalar_result(existing))

    lang = await set_driver_language(db, driver_id=1, language_code="es",
                                      language_name="Spanish",
                                      proficiency=LanguageProficiency.FLUENT,
                                      is_primary=False)

    assert lang.proficiency == LanguageProficiency.FLUENT
    assert lang.language_name == "Spanish"


@pytest.mark.asyncio
async def test_set_driver_language_clears_previous_primary():
    """3. set_driver_language clears previous primary when is_primary=True for a different code."""
    from app.services.driver_language import set_driver_language

    old_primary = _make_lang(language_code="en", is_primary=True)
    db = AsyncMock()
    db.flush = AsyncMock()
    # is_primary=True: first=old primary found, second=no existing entry for "fr"
    db.execute = AsyncMock(side_effect=[_scalar_result(old_primary), _scalar_result(None)])

    await set_driver_language(db, driver_id=1, language_code="fr",
                               language_name="French",
                               proficiency=LanguageProficiency.NATIVE,
                               is_primary=True)

    assert old_primary.is_primary is False


@pytest.mark.asyncio
async def test_set_driver_language_same_code_stays_primary():
    """4. set_driver_language keeps existing row primary when updating the same language."""
    from app.services.driver_language import set_driver_language

    existing_primary = _make_lang(language_code="en", is_primary=True)
    db = AsyncMock()
    db.flush = AsyncMock()
    # is_primary=True, same code: first=existing primary (same code, not cleared), second=same row
    db.execute = AsyncMock(side_effect=[
        _scalar_result(existing_primary),  # old primary lookup
        _scalar_result(existing_primary),  # upsert lookup finds same row
    ])

    lang = await set_driver_language(db, driver_id=1, language_code="en",
                                      language_name="English",
                                      proficiency=LanguageProficiency.NATIVE,
                                      is_primary=True)

    assert lang.is_primary is True


@pytest.mark.asyncio
async def test_remove_driver_language_removes_existing():
    """5. remove_driver_language removes an existing language."""
    from app.services.driver_language import remove_driver_language

    existing = _make_lang(language_code="de")
    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(existing))

    await remove_driver_language(db, driver_id=1, language_code="de")
    db.delete.assert_called_once_with(existing)


@pytest.mark.asyncio
async def test_remove_driver_language_raises_404_for_unknown():
    """6. remove_driver_language raises 404 for unknown language code."""
    from fastapi import HTTPException
    from app.services.driver_language import remove_driver_language

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(None))

    with pytest.raises(HTTPException) as exc_info:
        await remove_driver_language(db, driver_id=1, language_code="zz")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_driver_languages_returns_all():
    """7. get_driver_languages returns all languages for a driver."""
    from app.services.driver_language import get_driver_languages

    langs = [_make_lang(language_code="en"), _make_lang(language_code="fr")]
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalars_result(langs))

    result = await get_driver_languages(db, driver_id=1)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_get_driver_languages_empty_for_new_driver():
    """8. get_driver_languages returns empty list for driver with no languages."""
    from app.services.driver_language import get_driver_languages

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalars_result([]))

    result = await get_driver_languages(db, driver_id=999)
    assert result == []


@pytest.mark.asyncio
async def test_get_drivers_by_language_returns_all():
    """9. get_drivers_by_language returns all drivers for a language code."""
    from app.services.driver_language import get_drivers_by_language

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalars_result([1, 3, 7]))

    result = await get_drivers_by_language(db, language_code="es")
    assert result == [1, 3, 7]


@pytest.mark.asyncio
async def test_get_drivers_by_language_filters_proficiency():
    """10. get_drivers_by_language filters by minimum proficiency."""
    from app.services.driver_language import get_drivers_by_language

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalars_result([5, 8]))

    result = await get_drivers_by_language(
        db, language_code="zh", min_proficiency=LanguageProficiency.FLUENT
    )
    assert result == [5, 8]


@pytest.mark.asyncio
async def test_get_drivers_by_language_empty_for_unknown():
    """11. get_drivers_by_language returns empty list for unknown language."""
    from app.services.driver_language import get_drivers_by_language

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalars_result([]))

    result = await get_drivers_by_language(db, language_code="xx")
    assert result == []


@pytest.mark.asyncio
async def test_set_rider_language_preference_creates_new():
    """12. set_rider_language_preference creates new preference."""
    from app.services.driver_language import set_rider_language_preference

    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(None))

    await set_rider_language_preference(db, rider_id=2, language_code="ar",
                                         language_name="Arabic")
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_set_rider_language_preference_updates_existing():
    """13. set_rider_language_preference updates existing preference (upsert)."""
    from app.services.driver_language import set_rider_language_preference

    existing = _make_pref(language_code="es")
    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(existing))

    pref = await set_rider_language_preference(db, rider_id=2, language_code="fr",
                                                language_name="French")

    assert pref.language_code == "fr"
    assert pref.language_name == "French"


@pytest.mark.asyncio
async def test_get_rider_language_preference_returns_existing():
    """14. get_rider_language_preference returns existing preference."""
    from app.services.driver_language import get_rider_language_preference

    existing = _make_pref()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(existing))

    result = await get_rider_language_preference(db, rider_id=2)
    assert result is not None
    assert result.language_code == "es"


@pytest.mark.asyncio
async def test_get_rider_language_preference_returns_none_when_not_set():
    """15. get_rider_language_preference returns None for rider with no preference."""
    from app.services.driver_language import get_rider_language_preference

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(None))

    result = await get_rider_language_preference(db, rider_id=999)
    assert result is None


@pytest.mark.asyncio
async def test_clear_rider_language_preference_removes_existing():
    """16. clear_rider_language_preference removes existing preference."""
    from app.services.driver_language import clear_rider_language_preference

    existing = _make_pref()
    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(existing))

    await clear_rider_language_preference(db, rider_id=2)
    db.delete.assert_called_once_with(existing)


@pytest.mark.asyncio
async def test_clear_rider_language_preference_raises_404_when_not_set():
    """17. clear_rider_language_preference raises 404 when no preference set."""
    from fastapi import HTTPException
    from app.services.driver_language import clear_rider_language_preference

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(None))

    with pytest.raises(HTTPException) as exc_info:
        await clear_rider_language_preference(db, rider_id=999)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_language_coverage_stats_returns_correct_structure():
    """18. get_language_coverage_stats returns correct counts and top languages."""
    from app.services.driver_language import get_language_coverage_stats

    db = AsyncMock()

    # total entries
    total_mock = MagicMock()
    total_mock.scalar.return_value = 42

    # distinct languages
    distinct_mock = MagicMock()
    distinct_mock.scalar.return_value = 5

    # per-language rows (empty for simplicity)
    per_lang_mock = MagicMock()
    per_lang_mock.__iter__ = MagicMock(return_value=iter([]))

    # fluent rows
    fluent_mock = MagicMock()
    fluent_mock.__iter__ = MagicMock(return_value=iter([]))

    # rider prefs
    pref_mock = MagicMock()
    pref_mock.scalar.return_value = 12

    db.execute.side_effect = [
        total_mock,
        distinct_mock,
        per_lang_mock,
        fluent_mock,
        pref_mock,
    ]

    result = await get_language_coverage_stats(db)

    assert result["total_driver_language_entries"] == 42
    assert result["distinct_languages"] == 5
    assert result["rider_preferences_set"] == 12
    assert result["top_languages"] == []


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_schema_valid_language_code():
    """19. SetDriverLanguageRequest — valid language_code accepted."""
    req = SetDriverLanguageRequest(language_code="es", language_name="Spanish")
    assert req.language_code == "es"


def test_schema_language_code_normalised_to_lowercase():
    """20. SetDriverLanguageRequest — language_code normalised to lowercase."""
    req = SetDriverLanguageRequest(language_code="ZH", language_name="Chinese")
    assert req.language_code == "zh"


def test_schema_empty_language_code_rejected():
    """21. SetDriverLanguageRequest — empty language_code rejected."""
    with pytest.raises(ValidationError):
        SetDriverLanguageRequest(language_code="", language_name="Unknown")


def test_schema_language_code_too_long_rejected():
    """22. SetDriverLanguageRequest — language_code > 10 chars rejected."""
    with pytest.raises(ValidationError):
        SetDriverLanguageRequest(language_code="x" * 11, language_name="Test")


def test_schema_language_code_invalid_chars_rejected():
    """23. SetDriverLanguageRequest — language_code with invalid chars rejected."""
    with pytest.raises(ValidationError):
        SetDriverLanguageRequest(language_code="en!", language_name="English!")


def test_schema_proficiency_defaults_to_conversational():
    """24. SetDriverLanguageRequest — proficiency defaults to conversational."""
    req = SetDriverLanguageRequest(language_code="en", language_name="English")
    assert req.proficiency == LanguageProficiency.CONVERSATIONAL


def test_schema_is_primary_defaults_to_false():
    """25. SetDriverLanguageRequest — is_primary defaults to False."""
    req = SetDriverLanguageRequest(language_code="en", language_name="English")
    assert req.is_primary is False


def test_driver_language_response_from_attributes():
    """26. DriverLanguageResponse — from_attributes works correctly."""
    lang = _make_lang(lang_id=5, language_code="pt", language_name="Portuguese",
                      proficiency=LanguageProficiency.NATIVE, is_primary=True)
    resp = DriverLanguageResponse.model_validate(lang)
    assert resp.id == 5
    assert resp.language_code == "pt"
    assert resp.proficiency == LanguageProficiency.NATIVE
    assert resp.is_primary is True


def test_driver_language_list_total_matches_length():
    """27. DriverLanguageListResponse — total matches languages list length."""
    lang = _make_lang()
    resp = DriverLanguageResponse.model_validate(lang)
    listing = DriverLanguageListResponse(driver_id=1, languages=[resp, resp], total=2)
    assert listing.total == len(listing.languages)


def test_rider_language_preference_schema_valid():
    """28. SetRiderLanguagePreferenceRequest — valid request accepted."""
    req = SetRiderLanguagePreferenceRequest(language_code="ar", language_name="Arabic")
    assert req.language_code == "ar"


def test_rider_language_preference_response_from_attributes():
    """29. RiderLanguagePreferenceResponse — from_attributes works correctly."""
    pref = _make_pref(rider_id=3, language_code="ja", language_name="Japanese")
    resp = RiderLanguagePreferenceResponse.model_validate(pref)
    assert resp.rider_id == 3
    assert resp.language_code == "ja"


def test_language_coverage_stats_empty_top_languages():
    """30. LanguageCoverageStats — top_languages can be empty list."""
    stats = LanguageCoverageStats(
        total_driver_language_entries=0,
        distinct_languages=0,
        top_languages=[],
        rider_preferences_set=0,
    )
    assert stats.top_languages == []


# ---------------------------------------------------------------------------
# API layer tests — call handler functions directly (bypass HTTP auth)
# ---------------------------------------------------------------------------


def _mock_user(user_id: int = 1):
    user = MagicMock()
    user.id = user_id
    user.is_admin = False
    return user


@pytest.mark.asyncio
async def test_api_list_driver_languages_public():
    """31. GET /drivers/{id}/languages — returns language list."""
    from app.api.v1.driver_languages import list_driver_languages_public

    lang = _make_lang(driver_id=1)
    with patch(
        "app.api.v1.driver_languages.get_driver_languages",
        new=AsyncMock(return_value=[lang]),
    ):
        db = AsyncMock()
        result = await list_driver_languages_public(driver_id=1, db=db)

    assert result.total == 1
    assert result.driver_id == 1


@pytest.mark.asyncio
async def test_api_my_languages():
    """32. GET /drivers/me/languages — returns authenticated driver's languages."""
    from app.api.v1.driver_languages import my_languages

    lang = _make_lang(driver_id=7)
    user = _mock_user(user_id=7)
    with patch(
        "app.api.v1.driver_languages.get_driver_languages",
        new=AsyncMock(return_value=[lang]),
    ):
        db = AsyncMock()
        result = await my_languages(user=user, db=db)

    assert result.driver_id == 7
    assert result.total == 1


@pytest.mark.asyncio
async def test_api_upsert_my_language():
    """33. POST /drivers/me/languages — upserts language and returns response."""
    from app.api.v1.driver_languages import upsert_my_language

    lang = _make_lang(driver_id=7, language_code="fr", language_name="French")
    user = _mock_user(user_id=7)
    body = SetDriverLanguageRequest(
        language_code="fr",
        language_name="French",
        proficiency=LanguageProficiency.FLUENT,
        is_primary=False,
    )
    with patch(
        "app.api.v1.driver_languages.set_driver_language",
        new=AsyncMock(return_value=lang),
    ):
        db = AsyncMock()
        result = await upsert_my_language(body=body, user=user, db=db)

    assert result.language_code == "fr"
    assert result.language_name == "French"


@pytest.mark.asyncio
async def test_api_delete_my_language():
    """34. DELETE /drivers/me/languages/{code} — removes language, returns None (204)."""
    from app.api.v1.driver_languages import delete_my_language

    user = _mock_user(user_id=7)
    with patch(
        "app.api.v1.driver_languages.remove_driver_language",
        new=AsyncMock(return_value=None),
    ):
        db = AsyncMock()
        result = await delete_my_language(language_code="fr", user=user, db=db)

    assert result is None


@pytest.mark.asyncio
async def test_api_get_rider_language_preference_when_set():
    """35. GET /riders/me/language-preference — returns preference when set."""
    from app.api.v1.driver_languages import my_language_preference

    pref = _make_pref(rider_id=2)
    user = _mock_user(user_id=2)
    with patch(
        "app.api.v1.driver_languages.get_rider_language_preference",
        new=AsyncMock(return_value=pref),
    ):
        db = AsyncMock()
        result = await my_language_preference(user=user, db=db)

    assert result.language_code == "es"
    assert result.rider_id == 2


@pytest.mark.asyncio
async def test_api_get_rider_language_preference_not_set():
    """36. GET /riders/me/language-preference — raises 404 when not set."""
    from fastapi import HTTPException
    from app.api.v1.driver_languages import my_language_preference

    user = _mock_user(user_id=2)
    with patch(
        "app.api.v1.driver_languages.get_rider_language_preference",
        new=AsyncMock(return_value=None),
    ):
        db = AsyncMock()
        with pytest.raises(HTTPException) as exc_info:
            await my_language_preference(user=user, db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_api_set_rider_language_preference():
    """37. PUT /riders/me/language-preference — sets preference and returns it."""
    from app.api.v1.driver_languages import set_my_language_preference

    pref = _make_pref(rider_id=2, language_code="fr", language_name="French")
    user = _mock_user(user_id=2)
    body = SetRiderLanguagePreferenceRequest(language_code="fr", language_name="French")
    with patch(
        "app.api.v1.driver_languages.set_rider_language_preference",
        new=AsyncMock(return_value=pref),
    ):
        db = AsyncMock()
        result = await set_my_language_preference(body=body, user=user, db=db)

    assert result.language_code == "fr"
    assert result.rider_id == 2


@pytest.mark.asyncio
async def test_api_clear_rider_language_preference():
    """38. DELETE /riders/me/language-preference — clears preference, returns None (204)."""
    from app.api.v1.driver_languages import clear_my_language_preference

    user = _mock_user(user_id=2)
    with patch(
        "app.api.v1.driver_languages.clear_rider_language_preference",
        new=AsyncMock(return_value=None),
    ):
        db = AsyncMock()
        result = await clear_my_language_preference(user=user, db=db)

    assert result is None


@pytest.mark.asyncio
async def test_api_admin_language_coverage_stats():
    """39. GET /admin/language-coverage-stats — returns stats."""
    from app.api.v1.driver_languages import admin_language_stats
    from app.schemas.driver_language import LanguageCoverageStats

    stats_data = {
        "total_driver_language_entries": 100,
        "distinct_languages": 8,
        "top_languages": [],
        "rider_preferences_set": 25,
    }
    with patch(
        "app.api.v1.driver_languages.get_language_coverage_stats",
        new=AsyncMock(return_value=stats_data),
    ):
        db = AsyncMock()
        result = await admin_language_stats(db=db)

    assert result.total_driver_language_entries == 100
    assert result.distinct_languages == 8
    assert result.rider_preferences_set == 25


@pytest.mark.asyncio
async def test_api_admin_driver_languages():
    """40. GET /admin/drivers/{id}/languages — admin view of any driver's languages."""
    from app.api.v1.driver_languages import admin_driver_languages

    lang = _make_lang(driver_id=5)
    with patch(
        "app.api.v1.driver_languages.get_driver_languages",
        new=AsyncMock(return_value=[lang]),
    ):
        db = AsyncMock()
        result = await admin_driver_languages(driver_id=5, db=db)

    assert result.driver_id == 5
    assert result.total == 1
