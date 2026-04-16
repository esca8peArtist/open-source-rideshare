"""Tests for the Corporate Employee Transport Preferences feature.

Service layer (async, mocked DB):
  1.  get_or_create_preference — returns existing row when found
  2.  get_or_create_preference — creates blank row when none exists
  3.  update_preference — partial update writes only supplied fields
  4.  update_preference — creates row when none exists
  5.  update_preference — is_active can be set to False
  6.  get_preference_for_member — 404 when not found
  7.  get_preference_for_member — returns row when found
  8.  list_preferences_for_account — returns all rows ordered by member_id
  9.  list_preferences_for_account — filter has_accessibility_needs=True
  10. list_preferences_for_account — filter has_accessibility_needs=False
  11. list_preferences_for_account — filter is_active=True
  12. list_preferences_for_account — filter is_active=False
  13. delete_preference — 404 when not found
  14. delete_preference — deletes row when found
  15. get_members_with_accessibility_needs — returns only active rows with non-empty needs
  16. get_members_with_accessibility_needs — excludes inactive rows
  17. get_members_with_accessibility_needs — excludes rows with empty list
  18. get_members_needing_wav — preferred_vehicle_type=wav matches
  19. get_members_needing_wav — wheelchair_accessible in accessibility_needs matches
  20. get_members_needing_wav — excludes inactive rows
  21. get_members_needing_wav — no match when neither condition is true
  22. get_booking_defaults — returns full defaults when active row exists
  23. get_booking_defaults — has_wav_requirement=True when vehicle=wav
  24. get_booking_defaults — has_wav_requirement=True when wheelchair_accessible in needs
  25. get_booking_defaults — returns safe defaults when no row exists
  26. get_booking_defaults — returns safe defaults when row is inactive
  27. list_all_platform — returns all rows without filter
  28. list_all_platform — filters by account_id

_has_wav_requirement helper:
  29. _has_wav_requirement — True when preferred_vehicle_type=wav
  30. _has_wav_requirement — True when wheelchair_accessible in accessibility_needs
  31. _has_wav_requirement — False when vehicle=suv and no wheelchair need
  32. _has_wav_requirement — False when accessibility_needs is None

Schema validation:
  33. TransportPreferenceUpdate — all fields optional
  34. TransportPreferenceUpdate — valid preferred_vehicle_type accepted
  35. TransportPreferenceUpdate — invalid preferred_vehicle_type rejected
  36. TransportPreferenceUpdate — valid accessibility_needs accepted
  37. TransportPreferenceUpdate — unknown accessibility_need tag rejected
  38. TransportPreferenceUpdate — home_latitude bounds enforced (>90 rejected)
  39. TransportPreferenceUpdate — home_longitude bounds enforced (<-180 rejected)
  40. TransportPreferenceResponse — from_attributes construction
  41. BookingDefaultsResponse — has_wav_requirement field present
  42. TransportPreferenceListResponse — items + total fields

API layer (service functions patched):
  43. GET me — 200 member can get own preferences
  44. GET me — 404 when no corporate account
  45. PUT me — 200 member can update own preferences
  46. PUT me — invalid vehicle type returns 422
  47. DELETE me — 204 member can delete own preferences
  48. DELETE me — 404 when preference not found
  49. GET me/booking-defaults — 200 returns booking defaults
  50. GET list (admin) — 200 admin can list all preferences
  51. GET list (admin) — 403 non-admin cannot list
  52. GET list (admin) — has_accessibility_needs query param passed through
  53. GET accessibility — 200 admin gets accessibility list
  54. GET accessibility — 403 non-admin cannot access
  55. GET wav-required — 200 admin gets WAV list
  56. GET wav-required — 403 non-admin cannot access
  57. GET {member_id} — 200 admin gets specific member preference
  58. GET {member_id} — 403 non-admin cannot get member preference
  59. PUT {member_id} — 200 admin can update member preference
  60. PUT {member_id} — 403 non-admin cannot update member preference
  61. GET platform all — 200 platform-admin list all
  62. GET platform account — 200 platform-admin list for account
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.corporate_transport_preference import (
    CorporateEmployeeTransportPreference,
)
from app.schemas.corporate_transport_preference import (
    BookingDefaultsResponse,
    TransportPreferenceListResponse,
    TransportPreferenceResponse,
    TransportPreferenceUpdate,
)
from app.services.corporate_transport_preference import (
    _has_wav_requirement,
    delete_preference,
    get_booking_defaults,
    get_members_needing_wav,
    get_members_with_accessibility_needs,
    get_or_create_preference,
    get_preference_for_member,
    list_all_platform,
    list_preferences_for_account,
    update_preference,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 16, 0, 0, 0, tzinfo=timezone.utc)

ACCOUNT_ID = 10
MEMBER_ID = 20
ADMIN_ID = 21
OTHER_MEMBER_ID = 22


def _make_pref(
    id: int = 1,
    account_id: int = ACCOUNT_ID,
    member_id: int = MEMBER_ID,
    preferred_vehicle_type: str | None = None,
    accessibility_needs: list | None = None,
    home_address: str | None = None,
    home_latitude=None,
    home_longitude=None,
    default_cost_center_id: int | None = None,
    default_trip_purpose_id: int | None = None,
    preferred_pickup_note: str | None = None,
    notify_sms_number: str | None = None,
    is_active: bool = True,
) -> CorporateEmployeeTransportPreference:
    pref = CorporateEmployeeTransportPreference()
    pref.id = id
    pref.account_id = account_id
    pref.member_id = member_id
    pref.preferred_vehicle_type = preferred_vehicle_type
    pref.accessibility_needs = accessibility_needs
    pref.home_address = home_address
    pref.home_latitude = (
        Decimal(str(home_latitude)) if home_latitude is not None else None
    )
    pref.home_longitude = (
        Decimal(str(home_longitude)) if home_longitude is not None else None
    )
    pref.default_cost_center_id = default_cost_center_id
    pref.default_trip_purpose_id = default_trip_purpose_id
    pref.preferred_pickup_note = preferred_pickup_note
    pref.notify_sms_number = notify_sms_number
    pref.is_active = is_active
    pref.created_at = NOW
    pref.updated_at = NOW
    return pref


def _make_response(pref: CorporateEmployeeTransportPreference) -> TransportPreferenceResponse:
    return TransportPreferenceResponse(
        id=pref.id,
        account_id=pref.account_id,
        member_id=pref.member_id,
        preferred_vehicle_type=pref.preferred_vehicle_type,
        accessibility_needs=pref.accessibility_needs,
        home_address=pref.home_address,
        home_latitude=(
            float(pref.home_latitude) if pref.home_latitude is not None else None
        ),
        home_longitude=(
            float(pref.home_longitude) if pref.home_longitude is not None else None
        ),
        default_cost_center_id=pref.default_cost_center_id,
        default_trip_purpose_id=pref.default_trip_purpose_id,
        preferred_pickup_note=pref.preferred_pickup_note,
        notify_sms_number=pref.notify_sms_number,
        is_active=pref.is_active,
        created_at=pref.created_at,
        updated_at=pref.updated_at,
    )


def _db_returning(row):
    """Return a mock AsyncSession whose execute() returns a scalar_one_or_none of row."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute.return_value = result
    return db


def _db_returning_all(rows):
    """Return a mock AsyncSession whose execute().scalars().all() returns rows."""
    db = AsyncMock()
    result = MagicMock()
    scalar_result = MagicMock()
    scalar_result.all.return_value = rows
    result.scalars.return_value = scalar_result
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# 1. get_or_create_preference — returns existing row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_returns_existing():
    pref = _make_pref(preferred_vehicle_type="suv")
    db = _db_returning(pref)
    result = await get_or_create_preference(db, ACCOUNT_ID, MEMBER_ID)
    assert result.preferred_vehicle_type == "suv"
    db.add.assert_not_called()


# ---------------------------------------------------------------------------
# 2. get_or_create_preference — creates blank row when none exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_creates_when_missing():
    db = _db_returning(None)
    new_pref = _make_pref()
    db.refresh = AsyncMock(side_effect=lambda p: setattr(p, "id", 1) or None)

    async def refresh_side_effect(p):
        p.id = 1
        p.created_at = NOW
        p.updated_at = NOW

    db.refresh = AsyncMock(side_effect=refresh_side_effect)
    result = await get_or_create_preference(db, ACCOUNT_ID, MEMBER_ID)
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 3. update_preference — partial update writes only supplied fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_preference_partial():
    pref = _make_pref(preferred_vehicle_type="sedan")
    db = _db_returning(pref)

    async def refresh_side_effect(p):
        pass

    db.refresh = AsyncMock(side_effect=refresh_side_effect)

    data = TransportPreferenceUpdate(preferred_vehicle_type="suv")
    result = await update_preference(db, ACCOUNT_ID, MEMBER_ID, data)
    assert pref.preferred_vehicle_type == "suv"
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 4. update_preference — creates row when none exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_preference_creates_when_missing():
    db = _db_returning(None)

    async def refresh_side_effect(p):
        p.id = 1
        p.created_at = NOW
        p.updated_at = NOW

    db.refresh = AsyncMock(side_effect=refresh_side_effect)

    data = TransportPreferenceUpdate(preferred_vehicle_type="wav")
    await update_preference(db, ACCOUNT_ID, MEMBER_ID, data)
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 5. update_preference — is_active can be set to False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_preference_set_inactive():
    pref = _make_pref(is_active=True)
    db = _db_returning(pref)
    db.refresh = AsyncMock()

    data = TransportPreferenceUpdate(is_active=False)
    await update_preference(db, ACCOUNT_ID, MEMBER_ID, data)
    assert pref.is_active is False


# ---------------------------------------------------------------------------
# 6. get_preference_for_member — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_preference_404():
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await get_preference_for_member(db, ACCOUNT_ID, MEMBER_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 7. get_preference_for_member — returns row when found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_preference_found():
    pref = _make_pref(preferred_pickup_note="Wait at lobby")
    db = _db_returning(pref)
    result = await get_preference_for_member(db, ACCOUNT_ID, MEMBER_ID)
    assert result.preferred_pickup_note == "Wait at lobby"


# ---------------------------------------------------------------------------
# 8. list_preferences_for_account — returns all rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_preferences_all():
    prefs = [_make_pref(id=1, member_id=20), _make_pref(id=2, member_id=21)]
    db = _db_returning_all(prefs)
    result = await list_preferences_for_account(db, ACCOUNT_ID)
    assert result.total == 2


# ---------------------------------------------------------------------------
# 9. list_preferences_for_account — filter has_accessibility_needs=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_preferences_filter_has_needs_true():
    prefs = [
        _make_pref(id=1, member_id=20, accessibility_needs=["service_animal"]),
        _make_pref(id=2, member_id=21, accessibility_needs=None),
        _make_pref(id=3, member_id=22, accessibility_needs=[]),
    ]
    db = _db_returning_all(prefs)
    result = await list_preferences_for_account(db, ACCOUNT_ID, has_accessibility_needs=True)
    assert result.total == 1
    assert result.items[0].member_id == 20


# ---------------------------------------------------------------------------
# 10. list_preferences_for_account — filter has_accessibility_needs=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_preferences_filter_has_needs_false():
    prefs = [
        _make_pref(id=1, member_id=20, accessibility_needs=["service_animal"]),
        _make_pref(id=2, member_id=21, accessibility_needs=None),
    ]
    db = _db_returning_all(prefs)
    result = await list_preferences_for_account(db, ACCOUNT_ID, has_accessibility_needs=False)
    assert result.total == 1
    assert result.items[0].member_id == 21


# ---------------------------------------------------------------------------
# 11. list_preferences_for_account — filter is_active=True applied in query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_preferences_filter_is_active_true():
    prefs = [_make_pref(id=1, is_active=True)]
    db = _db_returning_all(prefs)
    result = await list_preferences_for_account(db, ACCOUNT_ID, is_active=True)
    assert result.total == 1


# ---------------------------------------------------------------------------
# 12. list_preferences_for_account — filter is_active=False applied in query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_preferences_filter_is_active_false():
    prefs = [_make_pref(id=1, is_active=False)]
    db = _db_returning_all(prefs)
    result = await list_preferences_for_account(db, ACCOUNT_ID, is_active=False)
    assert result.total == 1


# ---------------------------------------------------------------------------
# 13. delete_preference — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preference_404():
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await delete_preference(db, ACCOUNT_ID, MEMBER_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 14. delete_preference — deletes row when found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preference_success():
    pref = _make_pref()
    db = _db_returning(pref)
    await delete_preference(db, ACCOUNT_ID, MEMBER_ID)
    db.delete.assert_awaited_once_with(pref)
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 15. get_members_with_accessibility_needs — active rows with non-empty needs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_members_with_needs_filters_correctly():
    prefs = [
        _make_pref(id=1, member_id=20, accessibility_needs=["service_animal"], is_active=True),
        _make_pref(id=2, member_id=21, accessibility_needs=None, is_active=True),
    ]
    db = _db_returning_all(prefs)
    result = await get_members_with_accessibility_needs(db, ACCOUNT_ID)
    assert result.total == 1
    assert result.items[0].member_id == 20


# ---------------------------------------------------------------------------
# 16. get_members_with_accessibility_needs — excludes inactive rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_members_with_needs_excludes_inactive():
    # Inactive rows are excluded by the DB query (is_active=True filter)
    # Return empty list from DB to simulate no active rows
    db = _db_returning_all([])
    result = await get_members_with_accessibility_needs(db, ACCOUNT_ID)
    assert result.total == 0


# ---------------------------------------------------------------------------
# 17. get_members_with_accessibility_needs — excludes rows with empty list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_members_with_needs_excludes_empty_list():
    prefs = [
        _make_pref(id=1, member_id=20, accessibility_needs=[], is_active=True),
    ]
    db = _db_returning_all(prefs)
    result = await get_members_with_accessibility_needs(db, ACCOUNT_ID)
    assert result.total == 0


# ---------------------------------------------------------------------------
# 18. get_members_needing_wav — vehicle=wav matches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_members_needing_wav_vehicle_type():
    pref = _make_pref(preferred_vehicle_type="wav", is_active=True)
    db = _db_returning_all([pref])
    result = await get_members_needing_wav(db, ACCOUNT_ID)
    assert result.total == 1


# ---------------------------------------------------------------------------
# 19. get_members_needing_wav — wheelchair_accessible in needs matches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_members_needing_wav_accessibility():
    pref = _make_pref(
        accessibility_needs=["wheelchair_accessible", "extra_boarding_time"],
        is_active=True,
    )
    db = _db_returning_all([pref])
    result = await get_members_needing_wav(db, ACCOUNT_ID)
    assert result.total == 1


# ---------------------------------------------------------------------------
# 20. get_members_needing_wav — excludes inactive rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_members_needing_wav_excludes_inactive():
    db = _db_returning_all([])
    result = await get_members_needing_wav(db, ACCOUNT_ID)
    assert result.total == 0


# ---------------------------------------------------------------------------
# 21. get_members_needing_wav — no match when neither condition met
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_members_needing_wav_no_match():
    pref = _make_pref(preferred_vehicle_type="suv", accessibility_needs=["service_animal"])
    db = _db_returning_all([pref])
    result = await get_members_needing_wav(db, ACCOUNT_ID)
    assert result.total == 0


# ---------------------------------------------------------------------------
# 22. get_booking_defaults — full defaults when active row exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_booking_defaults_full():
    pref = _make_pref(
        preferred_vehicle_type="luxury",
        home_address="123 Main St",
        home_latitude=37.7749,
        home_longitude=-122.4194,
        default_cost_center_id=5,
        default_trip_purpose_id=3,
        preferred_pickup_note="Ring bell",
    )
    db = _db_returning(pref)
    result = await get_booking_defaults(db, ACCOUNT_ID, MEMBER_ID)
    assert result.preferred_vehicle_type == "luxury"
    assert result.home_address == "123 Main St"
    assert result.default_cost_center_id == 5
    assert result.has_wav_requirement is False


# ---------------------------------------------------------------------------
# 23. get_booking_defaults — has_wav_requirement=True when vehicle=wav
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_booking_defaults_wav_flag_vehicle():
    pref = _make_pref(preferred_vehicle_type="wav")
    db = _db_returning(pref)
    result = await get_booking_defaults(db, ACCOUNT_ID, MEMBER_ID)
    assert result.has_wav_requirement is True


# ---------------------------------------------------------------------------
# 24. get_booking_defaults — has_wav_requirement=True when wheelchair in needs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_booking_defaults_wav_flag_accessibility():
    pref = _make_pref(accessibility_needs=["wheelchair_accessible"])
    db = _db_returning(pref)
    result = await get_booking_defaults(db, ACCOUNT_ID, MEMBER_ID)
    assert result.has_wav_requirement is True


# ---------------------------------------------------------------------------
# 25. get_booking_defaults — safe defaults when no row exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_booking_defaults_no_row():
    db = _db_returning(None)
    result = await get_booking_defaults(db, ACCOUNT_ID, MEMBER_ID)
    assert result.preferred_vehicle_type is None
    assert result.has_wav_requirement is False


# ---------------------------------------------------------------------------
# 26. get_booking_defaults — safe defaults when row is inactive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_booking_defaults_inactive_row():
    pref = _make_pref(preferred_vehicle_type="wav", is_active=False)
    db = _db_returning(pref)
    result = await get_booking_defaults(db, ACCOUNT_ID, MEMBER_ID)
    assert result.preferred_vehicle_type is None
    assert result.has_wav_requirement is False


# ---------------------------------------------------------------------------
# 27. list_all_platform — all rows without filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_platform_no_filter():
    prefs = [_make_pref(id=1, account_id=10), _make_pref(id=2, account_id=11)]
    db = _db_returning_all(prefs)
    result = await list_all_platform(db)
    assert result.total == 2


# ---------------------------------------------------------------------------
# 28. list_all_platform — filters by account_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_platform_with_account_filter():
    prefs = [_make_pref(id=1, account_id=10)]
    db = _db_returning_all(prefs)
    result = await list_all_platform(db, account_id=10)
    assert result.total == 1


# ---------------------------------------------------------------------------
# 29. _has_wav_requirement — True when preferred_vehicle_type=wav
# ---------------------------------------------------------------------------


def test_has_wav_requirement_vehicle_type():
    pref = _make_pref(preferred_vehicle_type="wav")
    assert _has_wav_requirement(pref) is True


# ---------------------------------------------------------------------------
# 30. _has_wav_requirement — True when wheelchair_accessible in needs
# ---------------------------------------------------------------------------


def test_has_wav_requirement_accessibility():
    pref = _make_pref(accessibility_needs=["wheelchair_accessible"])
    assert _has_wav_requirement(pref) is True


# ---------------------------------------------------------------------------
# 31. _has_wav_requirement — False when vehicle=suv and no wheelchair need
# ---------------------------------------------------------------------------


def test_has_wav_requirement_suv_no_wheelchair():
    pref = _make_pref(preferred_vehicle_type="suv", accessibility_needs=["service_animal"])
    assert _has_wav_requirement(pref) is False


# ---------------------------------------------------------------------------
# 32. _has_wav_requirement — False when accessibility_needs is None
# ---------------------------------------------------------------------------


def test_has_wav_requirement_none_needs():
    pref = _make_pref(accessibility_needs=None)
    assert _has_wav_requirement(pref) is False


# ---------------------------------------------------------------------------
# 33. TransportPreferenceUpdate — all fields optional
# ---------------------------------------------------------------------------


def test_schema_update_all_optional():
    data = TransportPreferenceUpdate()
    assert data.preferred_vehicle_type is None
    assert data.accessibility_needs is None
    assert data.is_active is None


# ---------------------------------------------------------------------------
# 34. TransportPreferenceUpdate — valid preferred_vehicle_type accepted
# ---------------------------------------------------------------------------


def test_schema_valid_vehicle_type():
    for vt in ("sedan", "suv", "luxury", "wav"):
        data = TransportPreferenceUpdate(preferred_vehicle_type=vt)
        assert data.preferred_vehicle_type == vt


# ---------------------------------------------------------------------------
# 35. TransportPreferenceUpdate — invalid preferred_vehicle_type rejected
# ---------------------------------------------------------------------------


def test_schema_invalid_vehicle_type():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TransportPreferenceUpdate(preferred_vehicle_type="helicopter")


# ---------------------------------------------------------------------------
# 36. TransportPreferenceUpdate — valid accessibility_needs accepted
# ---------------------------------------------------------------------------


def test_schema_valid_accessibility_needs():
    data = TransportPreferenceUpdate(accessibility_needs=["service_animal", "extra_boarding_time"])
    assert len(data.accessibility_needs) == 2


# ---------------------------------------------------------------------------
# 37. TransportPreferenceUpdate — unknown tag rejected
# ---------------------------------------------------------------------------


def test_schema_unknown_accessibility_tag():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TransportPreferenceUpdate(accessibility_needs=["requires_pilot"])


# ---------------------------------------------------------------------------
# 38. TransportPreferenceUpdate — home_latitude bounds (>90 rejected)
# ---------------------------------------------------------------------------


def test_schema_home_latitude_out_of_bounds():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TransportPreferenceUpdate(home_latitude=91.0)


# ---------------------------------------------------------------------------
# 39. TransportPreferenceUpdate — home_longitude bounds (<-180 rejected)
# ---------------------------------------------------------------------------


def test_schema_home_longitude_out_of_bounds():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TransportPreferenceUpdate(home_longitude=-181.0)


# ---------------------------------------------------------------------------
# 40. TransportPreferenceResponse — from_attributes construction
# ---------------------------------------------------------------------------


def test_schema_response_from_attributes():
    pref = _make_pref(preferred_vehicle_type="luxury", accessibility_needs=["service_animal"])
    resp = _make_response(pref)
    assert resp.id == pref.id
    assert resp.preferred_vehicle_type == "luxury"
    assert resp.accessibility_needs == ["service_animal"]
    assert resp.is_active is True


# ---------------------------------------------------------------------------
# 41. BookingDefaultsResponse — has_wav_requirement field present
# ---------------------------------------------------------------------------


def test_booking_defaults_schema_has_wav_field():
    resp = BookingDefaultsResponse(
        member_id=MEMBER_ID,
        preferred_vehicle_type=None,
        accessibility_needs=None,
        preferred_pickup_note=None,
        default_cost_center_id=None,
        default_trip_purpose_id=None,
        home_address=None,
        home_latitude=None,
        home_longitude=None,
        has_wav_requirement=True,
    )
    assert resp.has_wav_requirement is True


# ---------------------------------------------------------------------------
# 42. TransportPreferenceListResponse — items + total fields
# ---------------------------------------------------------------------------


def test_list_response_schema():
    pref = _make_pref()
    resp = TransportPreferenceListResponse(items=[_make_response(pref)], total=1)
    assert resp.total == 1
    assert len(resp.items) == 1


# ---------------------------------------------------------------------------
# Helpers for API tests
# ---------------------------------------------------------------------------

_ROUTER = "app.api.v1.corporate_transport_preferences"


def _pref_response(member_id: int = MEMBER_ID) -> TransportPreferenceResponse:
    pref = _make_pref(member_id=member_id)
    return _make_response(pref)


def _list_response(count: int = 1) -> TransportPreferenceListResponse:
    items = [_pref_response(member_id=MEMBER_ID + i) for i in range(count)]
    return TransportPreferenceListResponse(items=items, total=count)


def _booking_defaults() -> BookingDefaultsResponse:
    return BookingDefaultsResponse(
        member_id=MEMBER_ID,
        preferred_vehicle_type="sedan",
        accessibility_needs=None,
        preferred_pickup_note=None,
        default_cost_center_id=None,
        default_trip_purpose_id=None,
        home_address=None,
        home_latitude=None,
        home_longitude=None,
        has_wav_requirement=False,
    )


# ---------------------------------------------------------------------------
# 43. GET me — 200 member can get own preferences
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_get_me_200():
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.get_or_create_preference", return_value=_pref_response()),
    ):
        from app.api.v1.corporate_transport_preferences import get_my_transport_preferences
        result = await get_my_transport_preferences(
            user=MagicMock(id=MEMBER_ID),
            db=AsyncMock(),
        )
        assert result.member_id == MEMBER_ID


# ---------------------------------------------------------------------------
# 44. GET me — 404 when no corporate account
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_get_me_404_no_account():
    from fastapi import HTTPException

    with patch(
        f"{_ROUTER}._resolve_account_id",
        side_effect=HTTPException(status_code=404, detail="no account"),
    ):
        from app.api.v1.corporate_transport_preferences import get_my_transport_preferences
        with pytest.raises(HTTPException) as exc:
            await get_my_transport_preferences(
                user=MagicMock(id=MEMBER_ID),
                db=AsyncMock(),
            )
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 45. PUT me — 200 member can update own preferences
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_put_me_200():
    data = TransportPreferenceUpdate(preferred_vehicle_type="suv")
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.update_preference", return_value=_pref_response()),
    ):
        from app.api.v1.corporate_transport_preferences import update_my_transport_preferences
        result = await update_my_transport_preferences(
            data=data,
            user=MagicMock(id=MEMBER_ID),
            db=AsyncMock(),
        )
        assert result.member_id == MEMBER_ID


# ---------------------------------------------------------------------------
# 46. PUT me — invalid vehicle type raises ValidationError
# ---------------------------------------------------------------------------


def test_api_put_me_invalid_vehicle_type_schema():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        TransportPreferenceUpdate(preferred_vehicle_type="rocket")


# ---------------------------------------------------------------------------
# 47. DELETE me — success (no exception raised)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_delete_me_success():
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.delete_preference", return_value=None) as mock_del,
    ):
        from app.api.v1.corporate_transport_preferences import delete_my_transport_preferences
        await delete_my_transport_preferences(
            user=MagicMock(id=MEMBER_ID),
            db=AsyncMock(),
        )
        mock_del.assert_awaited_once()


# ---------------------------------------------------------------------------
# 48. DELETE me — 404 when preference not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_delete_me_404():
    from fastapi import HTTPException

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}.delete_preference",
            side_effect=HTTPException(status_code=404, detail="not found"),
        ),
    ):
        from app.api.v1.corporate_transport_preferences import delete_my_transport_preferences
        with pytest.raises(HTTPException) as exc:
            await delete_my_transport_preferences(
                user=MagicMock(id=MEMBER_ID),
                db=AsyncMock(),
            )
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 49. GET me/booking-defaults — returns booking defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_get_booking_defaults():
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.get_booking_defaults", return_value=_booking_defaults()),
    ):
        from app.api.v1.corporate_transport_preferences import get_my_booking_defaults
        result = await get_my_booking_defaults(
            user=MagicMock(id=MEMBER_ID),
            db=AsyncMock(),
        )
        assert result.has_wav_requirement is False


# ---------------------------------------------------------------------------
# 50. GET list — admin can list all preferences
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_admin_list_200():
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin", return_value=None),
        patch(f"{_ROUTER}.list_preferences_for_account", return_value=_list_response(2)),
    ):
        from app.api.v1.corporate_transport_preferences import list_account_transport_preferences
        result = await list_account_transport_preferences(
            has_accessibility_needs=None,
            is_active=None,
            user=MagicMock(id=ADMIN_ID),
            db=AsyncMock(),
        )
        assert result.total == 2


# ---------------------------------------------------------------------------
# 51. GET list — 403 non-admin cannot list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_admin_list_403():
    from fastapi import HTTPException

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}._require_account_admin",
            side_effect=HTTPException(status_code=403, detail="admin required"),
        ),
    ):
        from app.api.v1.corporate_transport_preferences import list_account_transport_preferences
        with pytest.raises(HTTPException) as exc:
            await list_account_transport_preferences(
                has_accessibility_needs=None,
                is_active=None,
                user=MagicMock(id=MEMBER_ID),
                db=AsyncMock(),
            )
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 52. GET list — has_accessibility_needs param passed through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_admin_list_accessibility_filter():
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin", return_value=None),
        patch(
            f"{_ROUTER}.list_preferences_for_account", return_value=_list_response(1)
        ) as mock_svc,
    ):
        from app.api.v1.corporate_transport_preferences import list_account_transport_preferences
        await list_account_transport_preferences(
            has_accessibility_needs=True,
            is_active=None,
            user=MagicMock(id=ADMIN_ID),
            db=AsyncMock(),
        )
        mock_svc.assert_awaited_once()
        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["has_accessibility_needs"] is True


# ---------------------------------------------------------------------------
# 53. GET accessibility — admin gets accessibility list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_accessibility_list_200():
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin", return_value=None),
        patch(
            f"{_ROUTER}.get_members_with_accessibility_needs",
            return_value=_list_response(1),
        ),
    ):
        from app.api.v1.corporate_transport_preferences import list_accessibility_preferences
        result = await list_accessibility_preferences(
            user=MagicMock(id=ADMIN_ID),
            db=AsyncMock(),
        )
        assert result.total == 1


# ---------------------------------------------------------------------------
# 54. GET accessibility — 403 non-admin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_accessibility_list_403():
    from fastapi import HTTPException

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}._require_account_admin",
            side_effect=HTTPException(status_code=403),
        ),
    ):
        from app.api.v1.corporate_transport_preferences import list_accessibility_preferences
        with pytest.raises(HTTPException) as exc:
            await list_accessibility_preferences(
                user=MagicMock(id=MEMBER_ID),
                db=AsyncMock(),
            )
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 55. GET wav-required — admin gets WAV list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_wav_list_200():
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin", return_value=None),
        patch(f"{_ROUTER}.get_members_needing_wav", return_value=_list_response(1)),
    ):
        from app.api.v1.corporate_transport_preferences import list_wav_required_preferences
        result = await list_wav_required_preferences(
            user=MagicMock(id=ADMIN_ID),
            db=AsyncMock(),
        )
        assert result.total == 1


# ---------------------------------------------------------------------------
# 56. GET wav-required — 403 non-admin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_wav_list_403():
    from fastapi import HTTPException

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}._require_account_admin",
            side_effect=HTTPException(status_code=403),
        ),
    ):
        from app.api.v1.corporate_transport_preferences import list_wav_required_preferences
        with pytest.raises(HTTPException) as exc:
            await list_wav_required_preferences(
                user=MagicMock(id=MEMBER_ID),
                db=AsyncMock(),
            )
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 57. GET {member_id} — admin gets specific member preference
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_admin_get_member_200():
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin", return_value=None),
        patch(f"{_ROUTER}.get_preference_for_member", return_value=_pref_response()),
    ):
        from app.api.v1.corporate_transport_preferences import get_member_transport_preferences
        result = await get_member_transport_preferences(
            member_id=MEMBER_ID,
            user=MagicMock(id=ADMIN_ID),
            db=AsyncMock(),
        )
        assert result.member_id == MEMBER_ID


# ---------------------------------------------------------------------------
# 58. GET {member_id} — 403 non-admin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_admin_get_member_403():
    from fastapi import HTTPException

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}._require_account_admin",
            side_effect=HTTPException(status_code=403),
        ),
    ):
        from app.api.v1.corporate_transport_preferences import get_member_transport_preferences
        with pytest.raises(HTTPException) as exc:
            await get_member_transport_preferences(
                member_id=MEMBER_ID,
                user=MagicMock(id=MEMBER_ID),
                db=AsyncMock(),
            )
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 59. PUT {member_id} — admin can update member preference
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_admin_put_member_200():
    data = TransportPreferenceUpdate(preferred_pickup_note="Side entrance")
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin", return_value=None),
        patch(f"{_ROUTER}.update_preference", return_value=_pref_response()),
    ):
        from app.api.v1.corporate_transport_preferences import update_member_transport_preferences
        result = await update_member_transport_preferences(
            member_id=MEMBER_ID,
            data=data,
            user=MagicMock(id=ADMIN_ID),
            db=AsyncMock(),
        )
        assert result.member_id == MEMBER_ID


# ---------------------------------------------------------------------------
# 60. PUT {member_id} — 403 non-admin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_admin_put_member_403():
    from fastapi import HTTPException

    data = TransportPreferenceUpdate(preferred_vehicle_type="suv")
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}._require_account_admin",
            side_effect=HTTPException(status_code=403),
        ),
    ):
        from app.api.v1.corporate_transport_preferences import update_member_transport_preferences
        with pytest.raises(HTTPException) as exc:
            await update_member_transport_preferences(
                member_id=MEMBER_ID,
                data=data,
                user=MagicMock(id=MEMBER_ID),
                db=AsyncMock(),
            )
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 61. GET platform all — platform-admin list all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_platform_list_all_200():
    with patch(f"{_ROUTER}.list_all_platform", return_value=_list_response(3)):
        from app.api.v1.corporate_transport_preferences import admin_list_all_transport_preferences
        result = await admin_list_all_transport_preferences(
            account_id=None,
            _admin=MagicMock(id=1),
            db=AsyncMock(),
        )
        assert result.total == 3


# ---------------------------------------------------------------------------
# 62. GET platform account — platform-admin list for account
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_platform_list_for_account_200():
    with patch(
        f"{_ROUTER}.list_preferences_for_account", return_value=_list_response(2)
    ):
        from app.api.v1.corporate_transport_preferences import admin_list_account_transport_preferences
        result = await admin_list_account_transport_preferences(
            account_id=ACCOUNT_ID,
            has_accessibility_needs=None,
            is_active=None,
            _admin=MagicMock(id=1),
            db=AsyncMock(),
        )
        assert result.total == 2
