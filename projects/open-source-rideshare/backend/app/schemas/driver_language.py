"""Pydantic schemas for Driver Language Skills & Rider Language Preferences."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.models.driver_language import LanguageProficiency

# ---------------------------------------------------------------------------
# Common validation
# ---------------------------------------------------------------------------

_VALID_CODE_CHARS = set("abcdefghijklmnopqrstuvwxyz-")


def _normalise_code(v: str) -> str:
    v = v.strip().lower()
    if not v:
        raise ValueError("language_code must not be empty")
    if len(v) > 10:
        raise ValueError("language_code must be 10 characters or fewer")
    if not all(c in _VALID_CODE_CHARS for c in v):
        raise ValueError("language_code must be lowercase letters and hyphens only")
    return v


# ---------------------------------------------------------------------------
# Driver language schemas
# ---------------------------------------------------------------------------


class SetDriverLanguageRequest(BaseModel):
    """Add or update a language on the driver's profile."""

    language_code: str = Field(
        ...,
        description="ISO 639-1 code (e.g. 'en', 'es', 'zh')",
        max_length=10,
    )
    language_name: str = Field(
        ...,
        description="Human-readable name (e.g. 'English', 'Spanish')",
        max_length=100,
    )
    proficiency: LanguageProficiency = Field(
        LanguageProficiency.CONVERSATIONAL,
        description="Self-reported proficiency level",
    )
    is_primary: bool = Field(
        False,
        description="Mark as primary language (auto-clears previous primary)",
    )

    @field_validator("language_code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalise_code(v)


class DriverLanguageResponse(BaseModel):
    """A single driver language entry."""

    id: int
    driver_id: int
    language_code: str
    language_name: str
    proficiency: LanguageProficiency
    is_primary: bool

    model_config = {"from_attributes": True}


class DriverLanguageListResponse(BaseModel):
    """All languages registered by a driver."""

    driver_id: int
    languages: list[DriverLanguageResponse]
    total: int


class RemoveDriverLanguageRequest(BaseModel):
    """Remove a language from a driver's profile."""

    language_code: str = Field(..., max_length=10)

    @field_validator("language_code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalise_code(v)


# ---------------------------------------------------------------------------
# Rider language preference schemas
# ---------------------------------------------------------------------------


class SetRiderLanguagePreferenceRequest(BaseModel):
    """Set or update the rider's preferred driver language."""

    language_code: str = Field(..., max_length=10)
    language_name: str = Field(..., max_length=100)

    @field_validator("language_code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalise_code(v)


class RiderLanguagePreferenceResponse(BaseModel):
    """The rider's current language preference."""

    rider_id: int
    language_code: str
    language_name: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Admin stats schema
# ---------------------------------------------------------------------------


class LanguageStatEntry(BaseModel):
    """Coverage statistics for a single language."""

    language_code: str
    language_name: str
    driver_count: int
    fluent_or_native_count: int  # proficiency in (fluent, native)


class LanguageCoverageStats(BaseModel):
    """Platform-wide language coverage for the admin dashboard."""

    total_driver_language_entries: int
    distinct_languages: int
    top_languages: list[LanguageStatEntry]
    rider_preferences_set: int
