"""Tests for the Corporate Trip Purpose Codes feature.

Service tests (async, mocked DB):
  1.  create_purpose — success (code normalised to uppercase)
  2.  create_purpose — duplicate code within account → 409
  3.  create_purpose — cross-account isolation: same code allowed in different account
  4.  get_purpose — success
  5.  get_purpose — wrong account → None
  6.  list_purposes — active only (default)
  7.  list_purposes — include_inactive=True returns all
  8.  update_purpose — success (label, is_active, requires_notes)
  9.  update_purpose — not found → 404
  10. deactivate_purpose — success
  11. deactivate_purpose — not found → 404
  12. set_ride_purpose — happy path
  13. set_ride_purpose — ride not found → 404
  14. set_ride_purpose — wrong user → 403
  15. set_ride_purpose — ride has no corporate account → 422
  16. set_ride_purpose — purpose from different account → 422
  17. set_ride_purpose — inactive purpose → 422
  18. set_ride_purpose — requires_notes but no notes → 422
  19. set_ride_purpose — clear tag (purpose_id=None)
  20. get_purpose_spend_analytics — spend grouped by purpose
  21. get_purpose_spend_analytics — untagged bucket
  22. get_purpose_spend_analytics — date filtering applied
  23. list_ride_purposes_for_account — tagged ride returns purpose
  24. list_ride_purposes_for_account — untagged ride returns None
  25. list_ride_purposes_for_account — ride from different account returns None

Schema tests (sync):
  26. CorporateTripPurposeCreate — valid
  27. CorporateTripPurposeCreate — code too long → ValidationError
  28. CorporateTripPurposeUpdate — all fields optional
  29. SetRideTripPurposeRequest — trip_purpose_id nullable
  30. TripPurposeSpendResponse — serialises items list
  31. TripPurposeAnalyticsRequest — dates are optional

API layer tests (asyncio, service patched):
  32. POST /corporate/accounts/me/trip-purposes — 201
  33. GET  /corporate/accounts/me/trip-purposes — 200
  34. GET  /corporate/accounts/me/trip-purposes/{id} — 200
  35. GET  /corporate/accounts/me/trip-purposes/{id} — 404 when not found
  36. PATCH /corporate/accounts/me/trip-purposes/{id} — 200
  37. DELETE /corporate/accounts/me/trip-purposes/{id} — 200
  38. POST /corporate/accounts/me/trip-purposes/analytics — 200
  39. PUT  /rides/{ride_id}/trip-purpose — 200
  40. GET  /admin/corporate/accounts/{id}/trip-purposes — 200
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_trip_purpose import CorporateTripPurpose
from app.models.ride import Ride, RideStatus
from app.schemas.corporate_trip_purpose import (
    CorporateTripPurposeCreate,
    CorporateTripPurposeResponse,
    CorporateTripPurposeUpdate,
    SetRideTripPurposeRequest,
    TripPurposeAnalyticsRequest,
    TripPurposeSpendItem,
    TripPurposeSpendResponse,
)
from app.services.corporate_trip_purpose import (
    create_purpose,
    deactivate_purpose,
    get_purpose,
    get_purpose_spend_analytics,
    list_purposes,
    list_ride_purposes_for_account,
    set_ride_purpose,
    update_purpose,
)


# ---------------------------------------------------------------------------
# Shared constants and helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 10
OTHER_ACCOUNT_ID = 20
USER_ID = 1
ADMIN_ID = 2
PURPOSE_ID = 50
RIDE_ID = 99


def _make_member(
    account_id: int = ACCOUNT_ID,
    user_id: int = USER_ID,
    role: MemberRole = MemberRole.MEMBER,
    is_active: bool = True,
) -> MagicMock:
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = account_id
    m.user_id = user_id
    m.role = role
    m.is_active = is_active
    return m


def _make_admin_member(
    account_id: int = ACCOUNT_ID, user_id: int = ADMIN_ID
) -> MagicMock:
    return _make_member(account_id=account_id, user_id=user_id, role=MemberRole.ADMIN)


def _scalar_result(value) -> MagicMock:
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    res.scalar.return_value = value
    return res


def _all_result(rows: list) -> MagicMock:
    res = MagicMock()
    res.all.return_value = rows
    res.scalars.return_value.all.return_value = rows
    return res


def _make_purpose(
    purpose_id: int = PURPOSE_ID,
    account_id: int = ACCOUNT_ID,
    code: str = "CLIENT_MEETING",
    label: str = "Client Meeting",
    is_active: bool = True,
    requires_notes: bool = False,
) -> MagicMock:
    p = MagicMock(spec=CorporateTripPurpose)
    p.id = purpose_id
    p.account_id = account_id
    p.code = code
    p.label = label
    p.is_active = is_active
    p.requires_notes = requires_notes
    p.created_at = NOW
    p.updated_at = NOW
    return p


def _make_ride(
    ride_id: int = RIDE_ID,
    rider_id: int = USER_ID,
    corporate_account_id: int | None = ACCOUNT_ID,
    trip_purpose_id: int | None = None,
    trip_notes: str | None = None,
) -> MagicMock:
    r = MagicMock(spec=Ride)
    r.id = ride_id
    r.rider_id = rider_id
    r.corporate_account_id = corporate_account_id
    r.trip_purpose_id = trip_purpose_id
    r.trip_notes = trip_notes
    r.status = RideStatus.COMPLETED
    return r


# ---------------------------------------------------------------------------
# 1. create_purpose — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_purpose_success():
    db = AsyncMock()

    # First execute: no existing purpose (duplicate check)
    db.execute.return_value = _scalar_result(None)
    db.add = MagicMock()
    db.flush = AsyncMock()

    data = CorporateTripPurposeCreate(code="client_meeting", label="Client Meeting")

    result, err = await create_purpose(db, ACCOUNT_ID, data)

    assert err is None
    assert result is not None
    assert result.code == "CLIENT_MEETING"  # normalised to uppercase
    assert result.label == "Client Meeting"
    assert result.account_id == ACCOUNT_ID
    db.add.assert_called_once()
    db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# 2. create_purpose — duplicate code within account → 409
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_purpose_duplicate_code():
    db = AsyncMock()
    existing = _make_purpose()
    db.execute.return_value = _scalar_result(existing)

    data = CorporateTripPurposeCreate(code="CLIENT_MEETING", label="Client Meeting")
    result, err = await create_purpose(db, ACCOUNT_ID, data)

    assert result is None
    assert err is not None
    assert err.status_code == 409


# ---------------------------------------------------------------------------
# 3. create_purpose — cross-account isolation: same code allowed in different account
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_purpose_cross_account_isolation():
    db = AsyncMock()

    # No duplicate in OTHER_ACCOUNT_ID
    db.execute.return_value = _scalar_result(None)
    db.add = MagicMock()
    db.flush = AsyncMock()

    data = CorporateTripPurposeCreate(code="CLIENT_MEETING", label="Client Meeting")

    result, err = await create_purpose(db, OTHER_ACCOUNT_ID, data)

    assert err is None
    assert result is not None
    assert result.account_id == OTHER_ACCOUNT_ID


# ---------------------------------------------------------------------------
# 4. get_purpose — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_purpose_success():
    db = AsyncMock()
    purpose = _make_purpose()
    db.execute.return_value = _scalar_result(purpose)

    result = await get_purpose(db, ACCOUNT_ID, PURPOSE_ID)
    assert result is purpose


# ---------------------------------------------------------------------------
# 5. get_purpose — wrong account → None
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_purpose_wrong_account():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    result = await get_purpose(db, OTHER_ACCOUNT_ID, PURPOSE_ID)
    assert result is None


# ---------------------------------------------------------------------------
# 6. list_purposes — active only (default)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_purposes_active_only():
    db = AsyncMock()
    active_purpose = _make_purpose(is_active=True)
    db.execute.return_value = _all_result([active_purpose])

    results = await list_purposes(db, ACCOUNT_ID, include_inactive=False)
    assert len(results) == 1
    assert results[0].is_active is True


# ---------------------------------------------------------------------------
# 7. list_purposes — include_inactive=True returns all
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_purposes_include_inactive():
    db = AsyncMock()
    active = _make_purpose(purpose_id=1, is_active=True)
    inactive = _make_purpose(purpose_id=2, is_active=False)
    db.execute.return_value = _all_result([active, inactive])

    results = await list_purposes(db, ACCOUNT_ID, include_inactive=True)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# 8. update_purpose — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_purpose_success():
    db = AsyncMock()
    purpose = _make_purpose()
    db.execute.return_value = _scalar_result(purpose)
    db.flush = AsyncMock()

    data = CorporateTripPurposeUpdate(label="Updated Label", requires_notes=True)
    result, err = await update_purpose(db, ACCOUNT_ID, PURPOSE_ID, data)

    assert err is None
    assert result is purpose
    assert purpose.label == "Updated Label"
    assert purpose.requires_notes is True
    db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# 9. update_purpose — not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_purpose_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    data = CorporateTripPurposeUpdate(label="New Label")
    result, err = await update_purpose(db, ACCOUNT_ID, 9999, data)

    assert result is None
    assert err is not None
    assert err.status_code == 404


# ---------------------------------------------------------------------------
# 10. deactivate_purpose — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deactivate_purpose_success():
    db = AsyncMock()
    purpose = _make_purpose(is_active=True)
    db.execute.return_value = _scalar_result(purpose)
    db.flush = AsyncMock()

    result, err = await deactivate_purpose(db, ACCOUNT_ID, PURPOSE_ID)

    assert err is None
    assert result is purpose
    assert purpose.is_active is False
    db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# 11. deactivate_purpose — not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deactivate_purpose_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    result, err = await deactivate_purpose(db, ACCOUNT_ID, 9999)

    assert result is None
    assert err is not None
    assert err.status_code == 404


# ---------------------------------------------------------------------------
# 12. set_ride_purpose — happy path
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_set_ride_purpose_success():
    db = AsyncMock()
    ride = _make_ride()
    purpose = _make_purpose()

    db.execute.side_effect = [
        _scalar_result(ride),    # fetch ride
        _scalar_result(purpose), # get_purpose
    ]
    db.flush = AsyncMock()

    result, err = await set_ride_purpose(
        db, RIDE_ID, USER_ID, PURPOSE_ID, notes="Meeting notes"
    )

    assert err is None
    assert result is ride
    assert ride.trip_purpose_id == PURPOSE_ID
    assert ride.trip_notes == "Meeting notes"
    db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# 13. set_ride_purpose — ride not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_set_ride_purpose_ride_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    result, err = await set_ride_purpose(db, 9999, USER_ID, PURPOSE_ID, notes=None)

    assert result is None
    assert err is not None
    assert err.status_code == 404


# ---------------------------------------------------------------------------
# 14. set_ride_purpose — wrong user → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_set_ride_purpose_wrong_user():
    db = AsyncMock()
    ride = _make_ride(rider_id=999)  # belongs to user 999
    db.execute.return_value = _scalar_result(ride)

    result, err = await set_ride_purpose(db, RIDE_ID, USER_ID, PURPOSE_ID, notes=None)

    assert result is None
    assert err is not None
    assert err.status_code == 403


# ---------------------------------------------------------------------------
# 15. set_ride_purpose — ride has no corporate account → 422
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_set_ride_purpose_no_corporate_account():
    db = AsyncMock()
    ride = _make_ride(corporate_account_id=None)
    db.execute.return_value = _scalar_result(ride)

    result, err = await set_ride_purpose(db, RIDE_ID, USER_ID, PURPOSE_ID, notes=None)

    assert result is None
    assert err is not None
    assert err.status_code == 422


# ---------------------------------------------------------------------------
# 16. set_ride_purpose — purpose from different account → 422
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_set_ride_purpose_purpose_wrong_account():
    db = AsyncMock()
    ride = _make_ride(corporate_account_id=ACCOUNT_ID)

    # get_purpose returns None (purpose doesn't belong to ride's account)
    db.execute.side_effect = [
        _scalar_result(ride),
        _scalar_result(None),  # purpose not found for this account
    ]

    result, err = await set_ride_purpose(db, RIDE_ID, USER_ID, PURPOSE_ID, notes=None)

    assert result is None
    assert err is not None
    assert err.status_code == 422


# ---------------------------------------------------------------------------
# 17. set_ride_purpose — inactive purpose → 422
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_set_ride_purpose_inactive_purpose():
    db = AsyncMock()
    ride = _make_ride()
    purpose = _make_purpose(is_active=False)

    db.execute.side_effect = [
        _scalar_result(ride),
        _scalar_result(purpose),
    ]

    result, err = await set_ride_purpose(db, RIDE_ID, USER_ID, PURPOSE_ID, notes=None)

    assert result is None
    assert err is not None
    assert err.status_code == 422


# ---------------------------------------------------------------------------
# 18. set_ride_purpose — requires_notes but notes empty → 422
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_set_ride_purpose_requires_notes_missing():
    db = AsyncMock()
    ride = _make_ride()
    purpose = _make_purpose(requires_notes=True)

    db.execute.side_effect = [
        _scalar_result(ride),
        _scalar_result(purpose),
    ]

    result, err = await set_ride_purpose(db, RIDE_ID, USER_ID, PURPOSE_ID, notes=None)

    assert result is None
    assert err is not None
    assert err.status_code == 422


# ---------------------------------------------------------------------------
# 19. set_ride_purpose — clear tag (purpose_id=None)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_set_ride_purpose_clear_tag():
    db = AsyncMock()
    ride = _make_ride(trip_purpose_id=PURPOSE_ID, trip_notes="old notes")
    db.execute.return_value = _scalar_result(ride)
    db.flush = AsyncMock()

    result, err = await set_ride_purpose(db, RIDE_ID, USER_ID, None, notes=None)

    assert err is None
    assert result is ride
    assert ride.trip_purpose_id is None
    assert ride.trip_notes is None
    db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# 20. get_purpose_spend_analytics — spend grouped by purpose
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_purpose_spend_analytics_with_tagged_rides():
    db = AsyncMock()

    # Simulate one tagged group and one purpose metadata lookup
    tagged_row = MagicMock()
    tagged_row.purpose_id = PURPOSE_ID
    tagged_row.ride_count = 3
    tagged_row.total_spend = Decimal("150.00")

    purpose = _make_purpose()

    agg_mock = MagicMock()
    agg_mock.all.return_value = [tagged_row]
    purpose_mock = MagicMock()
    purpose_mock.scalars.return_value.all.return_value = [purpose]
    db.execute.side_effect = [agg_mock, purpose_mock]

    result = await get_purpose_spend_analytics(db, ACCOUNT_ID)

    assert result.account_id == ACCOUNT_ID
    assert result.untagged_ride_count == 0
    assert result.untagged_total_usd == Decimal("0")
    assert len(result.items) == 1
    assert result.items[0].purpose_id == PURPOSE_ID
    assert result.items[0].ride_count == 3


# ---------------------------------------------------------------------------
# 21. get_purpose_spend_analytics — untagged bucket
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_purpose_spend_analytics_untagged_bucket():
    db = AsyncMock()

    untagged_row = MagicMock()
    untagged_row.purpose_id = None
    untagged_row.ride_count = 5
    untagged_row.total_spend = Decimal("200.00")

    agg_mock = MagicMock()
    agg_mock.all.return_value = [untagged_row]
    db.execute.return_value = agg_mock

    result = await get_purpose_spend_analytics(db, ACCOUNT_ID)

    assert result.untagged_ride_count == 5
    assert result.untagged_total_usd == Decimal("200.00")
    assert len(result.items) == 0


# ---------------------------------------------------------------------------
# 22. get_purpose_spend_analytics — date filtering
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_purpose_spend_analytics_date_filtering():
    """Date filters are passed down; we verify the function accepts them."""
    db = AsyncMock()
    agg_mock = MagicMock()
    agg_mock.all.return_value = []
    db.execute.return_value = agg_mock

    result = await get_purpose_spend_analytics(
        db,
        ACCOUNT_ID,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 31),
    )
    assert result.account_id == ACCOUNT_ID
    assert db.execute.call_count == 1  # no tagged rows → only one DB call


# ---------------------------------------------------------------------------
# 23. list_ride_purposes_for_account — tagged ride returns purpose
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_ride_purposes_for_account_tagged():
    db = AsyncMock()
    ride = _make_ride(trip_purpose_id=PURPOSE_ID)
    purpose = _make_purpose()

    db.execute.side_effect = [
        _scalar_result(ride),    # fetch ride
        _scalar_result(purpose), # get_purpose
    ]

    result = await list_ride_purposes_for_account(db, RIDE_ID, ACCOUNT_ID)
    assert result is purpose


# ---------------------------------------------------------------------------
# 24. list_ride_purposes_for_account — untagged ride returns None
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_ride_purposes_for_account_untagged():
    db = AsyncMock()
    ride = _make_ride(trip_purpose_id=None)
    db.execute.return_value = _scalar_result(ride)

    result = await list_ride_purposes_for_account(db, RIDE_ID, ACCOUNT_ID)
    assert result is None


# ---------------------------------------------------------------------------
# 25. list_ride_purposes_for_account — ride from different account returns None
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_ride_purposes_for_account_wrong_account():
    db = AsyncMock()
    # Ride not found for this account scope
    db.execute.return_value = _scalar_result(None)

    result = await list_ride_purposes_for_account(db, RIDE_ID, OTHER_ACCOUNT_ID)
    assert result is None


# ---------------------------------------------------------------------------
# Schema tests (sync)
# ---------------------------------------------------------------------------


def test_trip_purpose_create_valid():
    """26. CorporateTripPurposeCreate — valid."""
    data = CorporateTripPurposeCreate(code="CONFERENCE", label="Conference Travel")
    assert data.code == "CONFERENCE"
    assert data.label == "Conference Travel"
    assert data.requires_notes is False


def test_trip_purpose_create_code_too_long():
    """27. CorporateTripPurposeCreate — code too long → ValidationError."""
    with pytest.raises(ValidationError):
        CorporateTripPurposeCreate(code="x" * 51, label="Too Long Code")


def test_trip_purpose_update_all_optional():
    """28. CorporateTripPurposeUpdate — all fields optional."""
    data = CorporateTripPurposeUpdate()
    assert data.label is None
    assert data.is_active is None
    assert data.requires_notes is None


def test_set_ride_trip_purpose_request_nullable():
    """29. SetRideTripPurposeRequest — trip_purpose_id nullable."""
    clear = SetRideTripPurposeRequest(trip_purpose_id=None)
    assert clear.trip_purpose_id is None

    assign = SetRideTripPurposeRequest(trip_purpose_id=42, trip_notes="Client meeting")
    assert assign.trip_purpose_id == 42
    assert assign.trip_notes == "Client meeting"


def test_trip_purpose_spend_response_serialises_items():
    """30. TripPurposeSpendResponse — serialises items list."""
    item = TripPurposeSpendItem(
        purpose_id=1,
        code="CONFERENCE",
        label="Conference Travel",
        ride_count=5,
        total_usd=Decimal("250.00"),
        avg_usd=Decimal("50.00"),
    )
    resp = TripPurposeSpendResponse(
        account_id=ACCOUNT_ID,
        items=[item],
        untagged_ride_count=2,
        untagged_total_usd=Decimal("80.00"),
    )
    assert len(resp.items) == 1
    assert resp.items[0].code == "CONFERENCE"
    assert resp.untagged_ride_count == 2


def test_trip_purpose_analytics_request_optional_dates():
    """31. TripPurposeAnalyticsRequest — dates are optional."""
    req = TripPurposeAnalyticsRequest()
    assert req.start_date is None
    assert req.end_date is None

    req_with_dates = TripPurposeAnalyticsRequest(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 31),
    )
    assert req_with_dates.start_date == date(2026, 1, 1)


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

_ROUTER = "app.api.v1.corporate_trip_purpose"


def _mock_user(user_id: int = USER_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


def _mock_purpose_response() -> CorporateTripPurposeResponse:
    return CorporateTripPurposeResponse(
        id=PURPOSE_ID,
        account_id=ACCOUNT_ID,
        code="CLIENT_MEETING",
        label="Client Meeting",
        is_active=True,
        requires_notes=False,
        created_at=NOW,
        updated_at=NOW,
    )


def _mock_purpose_orm() -> MagicMock:
    return _make_purpose()


@pytest.mark.asyncio
async def test_api_create_purpose():
    """32. POST /corporate/accounts/me/trip-purposes — 201."""
    from app.api.v1.corporate_trip_purpose import create_my_purpose

    user = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    data = CorporateTripPurposeCreate(code="AIRPORT_TRANSFER", label="Airport Transfer")
    purpose_orm = _mock_purpose_orm()

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=_make_admin_member())), \
         patch(f"{_ROUTER}.create_purpose", new=AsyncMock(return_value=(purpose_orm, None))):
        result = await create_my_purpose(data=data, user=user, db=db)

    assert result.id == PURPOSE_ID
    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_api_list_purposes():
    """33. GET /corporate/accounts/me/trip-purposes — 200."""
    from app.api.v1.corporate_trip_purpose import list_my_purposes

    user = _mock_user()
    db = AsyncMock()
    purposes = [_mock_purpose_orm(), _mock_purpose_orm()]

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.list_purposes", new=AsyncMock(return_value=purposes)):
        result = await list_my_purposes(include_inactive=False, user=user, db=db)

    assert len(result) == 2


@pytest.mark.asyncio
async def test_api_get_purpose_found():
    """34. GET /corporate/accounts/me/trip-purposes/{id} — 200."""
    from app.api.v1.corporate_trip_purpose import get_my_purpose

    user = _mock_user()
    db = AsyncMock()
    purpose_orm = _mock_purpose_orm()

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.get_purpose", new=AsyncMock(return_value=purpose_orm)):
        result = await get_my_purpose(purpose_id=PURPOSE_ID, user=user, db=db)

    assert result.id == PURPOSE_ID


@pytest.mark.asyncio
async def test_api_get_purpose_not_found():
    """35. GET /corporate/accounts/me/trip-purposes/{id} — 404 when not found."""
    from app.api.v1.corporate_trip_purpose import get_my_purpose

    user = _mock_user()
    db = AsyncMock()

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.get_purpose", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc_info:
            await get_my_purpose(purpose_id=9999, user=user, db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_api_update_purpose():
    """36. PATCH /corporate/accounts/me/trip-purposes/{id} — 200."""
    from app.api.v1.corporate_trip_purpose import update_my_purpose

    user = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    data = CorporateTripPurposeUpdate(label="Updated Label")
    purpose_orm = _mock_purpose_orm()
    purpose_orm.label = "Updated Label"

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=_make_admin_member())), \
         patch(f"{_ROUTER}.update_purpose", new=AsyncMock(return_value=(purpose_orm, None))):
        result = await update_my_purpose(purpose_id=PURPOSE_ID, data=data, user=user, db=db)

    assert result.label == "Updated Label"


@pytest.mark.asyncio
async def test_api_deactivate_purpose():
    """37. DELETE /corporate/accounts/me/trip-purposes/{id} — 200."""
    from app.api.v1.corporate_trip_purpose import deactivate_my_purpose

    user = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    purpose_orm = _mock_purpose_orm()
    purpose_orm.is_active = False

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=_make_admin_member())), \
         patch(f"{_ROUTER}.deactivate_purpose", new=AsyncMock(return_value=(purpose_orm, None))):
        result = await deactivate_my_purpose(purpose_id=PURPOSE_ID, user=user, db=db)

    assert result.is_active is False


@pytest.mark.asyncio
async def test_api_purpose_analytics():
    """38. POST /corporate/accounts/me/trip-purposes/analytics — 200."""
    from app.api.v1.corporate_trip_purpose import get_my_purpose_analytics

    user = _mock_user()
    db = AsyncMock()
    analytics_response = TripPurposeSpendResponse(
        account_id=ACCOUNT_ID,
        items=[],
        untagged_ride_count=0,
        untagged_total_usd=Decimal("0"),
    )

    with patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)), \
         patch(f"{_ROUTER}.get_purpose_spend_analytics", new=AsyncMock(return_value=analytics_response)):
        result = await get_my_purpose_analytics(
            body=TripPurposeAnalyticsRequest(), user=user, db=db
        )

    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_api_set_ride_trip_purpose():
    """39. PUT /rides/{ride_id}/trip-purpose — 200."""
    from app.api.v1.corporate_trip_purpose import set_ride_trip_purpose

    user = _mock_user()
    db = AsyncMock()
    ride_orm = _make_ride(trip_purpose_id=PURPOSE_ID, trip_notes="Meeting notes")
    body = SetRideTripPurposeRequest(trip_purpose_id=PURPOSE_ID, trip_notes="Meeting notes")

    with patch(f"{_ROUTER}.set_ride_purpose", new=AsyncMock(return_value=(ride_orm, None))):
        result = await set_ride_trip_purpose(ride_id=RIDE_ID, body=body, user=user, db=db)

    assert result["ride_id"] == RIDE_ID
    assert result["trip_purpose_id"] == PURPOSE_ID


@pytest.mark.asyncio
async def test_api_admin_list_purposes():
    """40. GET /admin/corporate/accounts/{id}/trip-purposes — 200."""
    from app.api.v1.corporate_trip_purpose import admin_list_purposes

    admin = _mock_user(user_id=ADMIN_ID)
    db = AsyncMock()
    purposes = [_mock_purpose_orm()]

    with patch(f"{_ROUTER}.list_purposes", new=AsyncMock(return_value=purposes)):
        result = await admin_list_purposes(account_id=ACCOUNT_ID, _admin=admin, db=db)

    assert len(result) == 1
    assert result[0].account_id == ACCOUNT_ID
