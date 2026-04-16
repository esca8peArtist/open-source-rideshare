"""Tests for the Corporate Travel Itinerary feature.

Service layer (async, mocked DB):
  1.  create_itinerary — creates with draft status
  2.  create_itinerary — sets created_by_id
  3.  get_itinerary — 404 when not found
  4.  get_itinerary — returns itinerary when found
  5.  update_itinerary — 409 when cancelled
  6.  update_itinerary — partial update only writes supplied fields
  7.  cancel_itinerary — 404 when not found
  8.  cancel_itinerary — 409 when already cancelled
  9.  cancel_itinerary — success sets status to cancelled
  10. complete_itinerary — 409 when cancelled
  11. complete_itinerary — success sets status to completed
  12. list_itineraries — returns paginated list
  13. add_ride_to_itinerary — 409 when itinerary cancelled
  14. add_ride_to_itinerary — 409 when ride already in itinerary
  15. remove_ride_from_itinerary — 404 when association not found
  16. list_itinerary_rides — 404 when itinerary not found
  17. get_itinerary_summary — returns correct counts

Schema validation:
  18. ItineraryCreate — title required
  19. ItineraryCreate — title empty string raises validation error
  20. ItineraryStatus — valid values accepted
  21. ItineraryResponse — from_attributes construction
  22. ItineraryRideResponse — from_attributes construction

API layer (service functions patched):
  23. POST create — 201 member can create
  24. POST create — 404 when no corporate account
  25. GET list — 200 member can list
  26. GET get — 200 member can view
  27. GET get — 404 not found
  28. PUT update — 200 member can update own itinerary
  29. PUT update — 409 when cancelled
  30. POST cancel — 200 admin can cancel
  31. POST cancel — 403 non-admin cannot cancel
  32. POST complete — 200 admin can complete
  33. GET list rides — 200 member can list rides
  34. POST add ride — 200 member can add ride
  35. POST add ride — 409 duplicate ride
  36. DELETE remove ride — 204 admin can remove
  37. DELETE remove ride — 403 non-admin cannot remove
  38. GET summary — 200 member can view summary
  39. GET platform list — 200 platform-admin list
  40. GET platform account list — 200 platform-admin account-specific list
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_travel_itinerary import (
    CorporateItineraryRide,
    CorporateTravelItinerary,
)
from app.schemas.corporate_travel_itinerary import (
    ItineraryCreate,
    ItineraryListResponse,
    ItineraryResponse,
    ItineraryRideCreate,
    ItineraryRideListResponse,
    ItineraryRideResponse,
    ItinerarySummaryResponse,
    ItineraryStatus,
    ItineraryUpdate,
)
from app.services.corporate_travel_itinerary import (
    add_ride_to_itinerary,
    cancel_itinerary,
    complete_itinerary,
    create_itinerary,
    get_itinerary,
    get_itinerary_summary,
    list_all_itineraries_platform,
    list_itineraries,
    list_itinerary_rides,
    remove_ride_from_itinerary,
    update_itinerary,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 10
MEMBER_ID = 3
ADMIN_ID = 2
USER_ID = 1
ITINERARY_ID = 42
RIDE_ID = 99

_SERVICE = "app.services.corporate_travel_itinerary"
_ROUTER = "app.api.v1.corporate_travel_itineraries"

_NOW = datetime(2026, 4, 16, 9, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_itinerary(
    itinerary_id: int = ITINERARY_ID,
    account_id: int = ACCOUNT_ID,
    created_by_id: int | None = MEMBER_ID,
    title: str = "Q2 Sales Conference NYC",
    description: str | None = None,
    start_date=None,
    end_date=None,
    cost_center_id: int | None = None,
    trip_purpose_id: int | None = None,
    status: str = "draft",
    is_active: bool = True,
) -> CorporateTravelItinerary:
    """Build a minimal CorporateTravelItinerary instance for testing."""
    i = CorporateTravelItinerary()
    i.id = itinerary_id
    i.account_id = account_id
    i.created_by_id = created_by_id
    i.title = title
    i.description = description
    i.start_date = start_date
    i.end_date = end_date
    i.cost_center_id = cost_center_id
    i.trip_purpose_id = trip_purpose_id
    i.status = status
    i.is_active = is_active
    i.created_at = _NOW
    i.updated_at = _NOW
    return i


def _make_itinerary_ride(
    assoc_id: int = 1,
    itinerary_id: int = ITINERARY_ID,
    ride_id: int | None = RIDE_ID,
    added_by_id: int | None = MEMBER_ID,
    notes: str | None = None,
) -> CorporateItineraryRide:
    """Build a minimal CorporateItineraryRide instance for testing."""
    r = CorporateItineraryRide()
    r.id = assoc_id
    r.itinerary_id = itinerary_id
    r.ride_id = ride_id
    r.added_by_id = added_by_id
    r.notes = notes
    r.added_at = _NOW
    return r


def _make_itinerary_response(
    itinerary_id: int = ITINERARY_ID,
    account_id: int = ACCOUNT_ID,
    status: str = "draft",
) -> ItineraryResponse:
    return ItineraryResponse(
        id=itinerary_id,
        account_id=account_id,
        created_by_id=MEMBER_ID,
        title="Q2 Sales Conference NYC",
        description=None,
        start_date=None,
        end_date=None,
        cost_center_id=None,
        trip_purpose_id=None,
        status=status,
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_ride_response(
    assoc_id: int = 1,
    itinerary_id: int = ITINERARY_ID,
    ride_id: int | None = RIDE_ID,
) -> ItineraryRideResponse:
    return ItineraryRideResponse(
        id=assoc_id,
        itinerary_id=itinerary_id,
        ride_id=ride_id,
        added_by_id=MEMBER_ID,
        notes=None,
        added_at=_NOW,
    )


def _scalar_result(value) -> MagicMock:
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    return res


def _scalar_one_result(value) -> MagicMock:
    res = MagicMock()
    res.scalar_one.return_value = value
    return res


def _scalars_all_result(values: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = values
    res = MagicMock()
    res.scalars.return_value = scalars
    return res


def _mock_user(user_id: int = USER_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


# ---------------------------------------------------------------------------
# 1. create_itinerary — creates with draft status
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_itinerary_draft_status():
    db = AsyncMock()
    added = []
    db.add = lambda x: added.append(x)

    async def _fake_refresh(obj):
        obj.id = ITINERARY_ID
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _fake_refresh

    data = ItineraryCreate(title="Q2 Sales Conference NYC")
    result = await create_itinerary(db, ACCOUNT_ID, data, member_id=MEMBER_ID)

    assert len(added) == 1
    new_itinerary = added[0]
    assert new_itinerary.status == "draft"
    assert result.id == ITINERARY_ID


# ---------------------------------------------------------------------------
# 2. create_itinerary — sets created_by_id
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_itinerary_sets_created_by_id():
    db = AsyncMock()
    added = []
    db.add = lambda x: added.append(x)

    async def _fake_refresh(obj):
        obj.id = ITINERARY_ID
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _fake_refresh

    data = ItineraryCreate(title="Client Visit")
    await create_itinerary(db, ACCOUNT_ID, data, member_id=MEMBER_ID)

    assert len(added) == 1
    assert added[0].created_by_id == MEMBER_ID
    assert added[0].is_active is True


# ---------------------------------------------------------------------------
# 3. get_itinerary — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_itinerary_404_when_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await get_itinerary(db, ACCOUNT_ID, ITINERARY_ID)
    assert exc.value.status_code == 404
    assert "not found" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 4. get_itinerary — returns itinerary when found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_itinerary_returns_when_found():
    db = AsyncMock()
    existing = _make_itinerary(title="Board Meeting Berlin")
    db.execute.return_value = _scalar_result(existing)

    result = await get_itinerary(db, ACCOUNT_ID, ITINERARY_ID)

    assert result.id == ITINERARY_ID
    assert result.title == "Board Meeting Berlin"
    assert result.account_id == ACCOUNT_ID


# ---------------------------------------------------------------------------
# 5. update_itinerary — 409 when cancelled
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_itinerary_409_when_cancelled():
    db = AsyncMock()
    existing = _make_itinerary(status="cancelled")
    db.execute.return_value = _scalar_result(existing)

    with pytest.raises(HTTPException) as exc:
        await update_itinerary(
            db, ACCOUNT_ID, ITINERARY_ID,
            ItineraryUpdate(title="New Title"),
            member_id=MEMBER_ID,
        )
    assert exc.value.status_code == 409
    assert "cancelled" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 6. update_itinerary — partial update only writes supplied fields
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_itinerary_partial_fields_only():
    db = AsyncMock()
    existing = _make_itinerary(
        title="Old Title",
        description="Old description",
        status="draft",
    )
    db.execute.return_value = _scalar_result(existing)
    db.refresh = AsyncMock()

    data = ItineraryUpdate(title="New Title")
    await update_itinerary(db, ACCOUNT_ID, ITINERARY_ID, data, member_id=MEMBER_ID)

    assert existing.title == "New Title"
    assert existing.description == "Old description"   # unchanged
    assert existing.status == "draft"                  # unchanged


# ---------------------------------------------------------------------------
# 7. cancel_itinerary — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_itinerary_404_when_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await cancel_itinerary(db, ACCOUNT_ID, ITINERARY_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 8. cancel_itinerary — 409 when already cancelled
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_itinerary_409_when_already_cancelled():
    db = AsyncMock()
    existing = _make_itinerary(status="cancelled")
    db.execute.return_value = _scalar_result(existing)

    with pytest.raises(HTTPException) as exc:
        await cancel_itinerary(db, ACCOUNT_ID, ITINERARY_ID)
    assert exc.value.status_code == 409
    assert "already cancelled" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 9. cancel_itinerary — success sets status to cancelled
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_itinerary_success():
    db = AsyncMock()
    existing = _make_itinerary(status="active")
    db.execute.return_value = _scalar_result(existing)
    db.refresh = AsyncMock()

    result = await cancel_itinerary(db, ACCOUNT_ID, ITINERARY_ID)

    assert existing.status == "cancelled"


# ---------------------------------------------------------------------------
# 10. complete_itinerary — 409 when cancelled
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_complete_itinerary_409_when_cancelled():
    db = AsyncMock()
    existing = _make_itinerary(status="cancelled")
    db.execute.return_value = _scalar_result(existing)

    with pytest.raises(HTTPException) as exc:
        await complete_itinerary(db, ACCOUNT_ID, ITINERARY_ID)
    assert exc.value.status_code == 409
    assert "cancelled" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 11. complete_itinerary — success sets status to completed
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_complete_itinerary_success():
    db = AsyncMock()
    existing = _make_itinerary(status="active")
    db.execute.return_value = _scalar_result(existing)
    db.refresh = AsyncMock()

    result = await complete_itinerary(db, ACCOUNT_ID, ITINERARY_ID)

    assert existing.status == "completed"


# ---------------------------------------------------------------------------
# 12. list_itineraries — returns paginated list
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_itineraries_returns_paginated():
    db = AsyncMock()
    items = [_make_itinerary(itinerary_id=1), _make_itinerary(itinerary_id=2)]
    items[1].id = 2

    db.execute.side_effect = [
        _scalar_one_result(2),
        _scalars_all_result(items),
    ]

    result = await list_itineraries(db, ACCOUNT_ID, limit=50, offset=0)

    assert result.total == 2
    assert result.limit == 50
    assert result.offset == 0
    assert len(result.items) == 2


# ---------------------------------------------------------------------------
# 13. add_ride_to_itinerary — 409 when itinerary cancelled
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_add_ride_409_when_itinerary_cancelled():
    db = AsyncMock()
    existing = _make_itinerary(status="cancelled")
    db.execute.return_value = _scalar_result(existing)

    with pytest.raises(HTTPException) as exc:
        await add_ride_to_itinerary(
            db, ACCOUNT_ID, ITINERARY_ID, RIDE_ID, MEMBER_ID
        )
    assert exc.value.status_code == 409
    assert "cancelled" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 14. add_ride_to_itinerary — 409 when ride already in itinerary
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_add_ride_409_duplicate():
    db = AsyncMock()
    existing_itinerary = _make_itinerary(status="active")
    existing_assoc = _make_itinerary_ride()

    db.execute.side_effect = [
        _scalar_result(existing_itinerary),   # fetch itinerary
        _scalar_result(existing_assoc),        # duplicate check
    ]

    with pytest.raises(HTTPException) as exc:
        await add_ride_to_itinerary(
            db, ACCOUNT_ID, ITINERARY_ID, RIDE_ID, MEMBER_ID
        )
    assert exc.value.status_code == 409
    assert "already" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 15. remove_ride_from_itinerary — 404 when association not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_remove_ride_404_when_association_not_found():
    db = AsyncMock()
    existing_itinerary = _make_itinerary(status="active")

    db.execute.side_effect = [
        _scalar_result(existing_itinerary),   # fetch itinerary
        _scalar_result(None),                  # association lookup
    ]

    with pytest.raises(HTTPException) as exc:
        await remove_ride_from_itinerary(db, ACCOUNT_ID, ITINERARY_ID, RIDE_ID)
    assert exc.value.status_code == 404
    assert "association" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 16. list_itinerary_rides — 404 when itinerary not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_itinerary_rides_404_when_itinerary_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await list_itinerary_rides(db, ACCOUNT_ID, ITINERARY_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 17. get_itinerary_summary — returns correct counts
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_itinerary_summary_returns_correct_counts():
    db = AsyncMock()
    existing = _make_itinerary(title="Summit Trip", status="active")
    ride1 = _make_itinerary_ride(assoc_id=1, ride_id=10)
    ride2 = _make_itinerary_ride(assoc_id=2, ride_id=20)

    db.execute.side_effect = [
        _scalar_result(existing),
        _scalars_all_result([ride1, ride2]),
    ]

    result = await get_itinerary_summary(db, ACCOUNT_ID, ITINERARY_ID)

    assert result.itinerary_id == ITINERARY_ID
    assert result.title == "Summit Trip"
    assert result.status == "active"
    assert result.total_rides == 2
    assert set(result.ride_ids) == {10, 20}


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_itinerary_create_title_required():
    """18. ItineraryCreate — title required."""
    with pytest.raises(ValidationError):
        ItineraryCreate()


def test_itinerary_create_empty_title_raises():
    """19. ItineraryCreate — empty title raises validation error."""
    with pytest.raises(ValidationError):
        ItineraryCreate(title="")

    with pytest.raises(ValidationError):
        ItineraryCreate(title="   ")


def test_itinerary_status_valid_values():
    """20. ItineraryStatus — valid values accepted."""
    assert ItineraryStatus.draft == "draft"
    assert ItineraryStatus.active == "active"
    assert ItineraryStatus.completed == "completed"
    assert ItineraryStatus.cancelled == "cancelled"


def test_itinerary_response_from_attributes():
    """21. ItineraryResponse — from_attributes construction."""
    resp = _make_itinerary_response()
    assert resp.id == ITINERARY_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.title == "Q2 Sales Conference NYC"
    assert resp.status == "draft"
    assert resp.is_active is True
    assert isinstance(resp.created_at, datetime)


def test_itinerary_ride_response_from_attributes():
    """22. ItineraryRideResponse — from_attributes construction."""
    resp = _make_ride_response()
    assert resp.id == 1
    assert resp.itinerary_id == ITINERARY_ID
    assert resp.ride_id == RIDE_ID
    assert resp.added_by_id == MEMBER_ID
    assert isinstance(resp.added_at, datetime)


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_create_itinerary_201():
    """23. POST create — 201 member can create."""
    from app.api.v1.corporate_travel_itineraries import create_my_itinerary

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    data = ItineraryCreate(title="Q2 Sales Conference NYC")
    mock_resp = _make_itinerary_response()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.create_itinerary",
            new=AsyncMock(return_value=mock_resp),
        ),
    ):
        result = await create_my_itinerary(data=data, user=user, db=db)

    assert result.id == ITINERARY_ID
    assert result.status == "draft"


@pytest.mark.asyncio
async def test_api_create_itinerary_404_no_account():
    """24. POST create — 404 when no corporate account."""
    from app.api.v1.corporate_travel_itineraries import create_my_itinerary

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    data = ItineraryCreate(title="Trip")

    with patch(
        f"{_ROUTER}._resolve_account_id",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="No account")),
    ):
        with pytest.raises(HTTPException) as exc:
            await create_my_itinerary(data=data, user=user, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_list_itineraries_200():
    """25. GET list — 200 member can list."""
    from app.api.v1.corporate_travel_itineraries import list_my_itineraries

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    mock_resp = ItineraryListResponse(
        total=1,
        limit=50,
        offset=0,
        items=[_make_itinerary_response()],
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.list_itineraries",
            new=AsyncMock(return_value=mock_resp),
        ),
    ):
        result = await list_my_itineraries(
            status=None, created_by_id=None, limit=50, offset=0,
            user=user, db=db,
        )

    assert result.total == 1
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_api_get_itinerary_200():
    """26. GET get — 200 member can view."""
    from app.api.v1.corporate_travel_itineraries import get_my_itinerary

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    mock_resp = _make_itinerary_response()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.get_itinerary",
            new=AsyncMock(return_value=mock_resp),
        ),
    ):
        result = await get_my_itinerary(itinerary_id=ITINERARY_ID, user=user, db=db)

    assert result.id == ITINERARY_ID


@pytest.mark.asyncio
async def test_api_get_itinerary_404():
    """27. GET get — 404 not found."""
    from app.api.v1.corporate_travel_itineraries import get_my_itinerary

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.get_itinerary",
            new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await get_my_itinerary(itinerary_id=ITINERARY_ID, user=user, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_update_itinerary_200():
    """28. PUT update — 200 member can update own itinerary."""
    from app.api.v1.corporate_travel_itineraries import update_my_itinerary

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    data = ItineraryUpdate(title="Updated Title")
    mock_resp = _make_itinerary_response()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.update_itinerary",
            new=AsyncMock(return_value=mock_resp),
        ),
    ):
        result = await update_my_itinerary(
            itinerary_id=ITINERARY_ID, data=data, user=user, db=db
        )

    assert result.id == ITINERARY_ID


@pytest.mark.asyncio
async def test_api_update_itinerary_409_cancelled():
    """29. PUT update — 409 when cancelled."""
    from app.api.v1.corporate_travel_itineraries import update_my_itinerary

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    data = ItineraryUpdate(title="New Title")

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.update_itinerary",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=409, detail="Cannot update a cancelled itinerary."
                )
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await update_my_itinerary(
                itinerary_id=ITINERARY_ID, data=data, user=user, db=db
            )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_api_cancel_itinerary_200():
    """30. POST cancel — 200 admin can cancel."""
    from app.api.v1.corporate_travel_itineraries import cancel_my_itinerary

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_resp = _make_itinerary_response(status="cancelled")

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(
            f"{_ROUTER}.cancel_itinerary",
            new=AsyncMock(return_value=mock_resp),
        ),
    ):
        result = await cancel_my_itinerary(
            itinerary_id=ITINERARY_ID, user=user, db=db
        )

    assert result.status == "cancelled"


@pytest.mark.asyncio
async def test_api_cancel_itinerary_403_non_admin():
    """31. POST cancel — 403 non-admin cannot cancel."""
    from app.api.v1.corporate_travel_itineraries import cancel_my_itinerary

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}._require_account_admin",
            new=AsyncMock(
                side_effect=HTTPException(status_code=403, detail="Forbidden")
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await cancel_my_itinerary(itinerary_id=ITINERARY_ID, user=user, db=db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_complete_itinerary_200():
    """32. POST complete — 200 admin can complete."""
    from app.api.v1.corporate_travel_itineraries import complete_my_itinerary

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_resp = _make_itinerary_response(status="completed")

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(
            f"{_ROUTER}.complete_itinerary",
            new=AsyncMock(return_value=mock_resp),
        ),
    ):
        result = await complete_my_itinerary(
            itinerary_id=ITINERARY_ID, user=user, db=db
        )

    assert result.status == "completed"


@pytest.mark.asyncio
async def test_api_list_rides_200():
    """33. GET list rides — 200 member can list rides."""
    from app.api.v1.corporate_travel_itineraries import list_my_itinerary_rides

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    mock_resp = ItineraryRideListResponse(
        total=1,
        limit=50,
        offset=0,
        items=[_make_ride_response()],
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.list_itinerary_rides",
            new=AsyncMock(return_value=mock_resp),
        ),
    ):
        result = await list_my_itinerary_rides(
            itinerary_id=ITINERARY_ID, limit=50, offset=0, user=user, db=db
        )

    assert result.total == 1
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_api_add_ride_200():
    """34. POST add ride — 200 member can add ride."""
    from app.api.v1.corporate_travel_itineraries import add_ride_to_my_itinerary

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    data = ItineraryRideCreate(ride_id=RIDE_ID)
    mock_resp = _make_ride_response()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.add_ride_to_itinerary",
            new=AsyncMock(return_value=mock_resp),
        ),
    ):
        result = await add_ride_to_my_itinerary(
            itinerary_id=ITINERARY_ID, data=data, user=user, db=db
        )

    assert result.ride_id == RIDE_ID


@pytest.mark.asyncio
async def test_api_add_ride_409_duplicate():
    """35. POST add ride — 409 duplicate ride."""
    from app.api.v1.corporate_travel_itineraries import add_ride_to_my_itinerary

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    data = ItineraryRideCreate(ride_id=RIDE_ID)

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.add_ride_to_itinerary",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=409, detail="Ride is already in this itinerary."
                )
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await add_ride_to_my_itinerary(
                itinerary_id=ITINERARY_ID, data=data, user=user, db=db
            )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_api_remove_ride_204():
    """36. DELETE remove ride — 204 admin can remove."""
    from app.api.v1.corporate_travel_itineraries import remove_ride_from_my_itinerary

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(
            f"{_ROUTER}.remove_ride_from_itinerary",
            new=AsyncMock(return_value=None),
        ),
    ):
        result = await remove_ride_from_my_itinerary(
            itinerary_id=ITINERARY_ID, ride_id=RIDE_ID, user=user, db=db
        )

    assert result is None


@pytest.mark.asyncio
async def test_api_remove_ride_403_non_admin():
    """37. DELETE remove ride — 403 non-admin cannot remove."""
    from app.api.v1.corporate_travel_itineraries import remove_ride_from_my_itinerary

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}._require_account_admin",
            new=AsyncMock(
                side_effect=HTTPException(status_code=403, detail="Forbidden")
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await remove_ride_from_my_itinerary(
                itinerary_id=ITINERARY_ID, ride_id=RIDE_ID, user=user, db=db
            )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_get_summary_200():
    """38. GET summary — 200 member can view summary."""
    from app.api.v1.corporate_travel_itineraries import get_my_itinerary_summary

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    mock_resp = ItinerarySummaryResponse(
        itinerary_id=ITINERARY_ID,
        title="Q2 Sales Conference NYC",
        status="active",
        total_rides=3,
        ride_ids=[10, 20, 30],
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.get_itinerary_summary",
            new=AsyncMock(return_value=mock_resp),
        ),
    ):
        result = await get_my_itinerary_summary(
            itinerary_id=ITINERARY_ID, user=user, db=db
        )

    assert result.itinerary_id == ITINERARY_ID
    assert result.total_rides == 3
    assert result.ride_ids == [10, 20, 30]


@pytest.mark.asyncio
async def test_api_platform_list_all_200():
    """39. GET platform list — 200 platform-admin list."""
    from app.api.v1.corporate_travel_itineraries import admin_list_all_itineraries

    admin = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_resp = ItineraryListResponse(
        total=2,
        limit=50,
        offset=0,
        items=[
            _make_itinerary_response(itinerary_id=1, account_id=10),
            _make_itinerary_response(itinerary_id=2, account_id=11),
        ],
    )

    with patch(
        f"{_ROUTER}.list_all_itineraries_platform",
        new=AsyncMock(return_value=mock_resp),
    ):
        result = await admin_list_all_itineraries(
            limit=50, offset=0, _admin=admin, db=db
        )

    assert result.total == 2
    assert len(result.items) == 2


@pytest.mark.asyncio
async def test_api_platform_account_list_200():
    """40. GET platform account list — 200 platform-admin account-specific list."""
    from app.api.v1.corporate_travel_itineraries import admin_list_account_itineraries

    admin = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_resp = ItineraryListResponse(
        total=1,
        limit=50,
        offset=0,
        items=[_make_itinerary_response()],
    )

    with patch(
        f"{_ROUTER}.list_itineraries",
        new=AsyncMock(return_value=mock_resp),
    ):
        result = await admin_list_account_itineraries(
            account_id=ACCOUNT_ID, status=None, limit=50, offset=0,
            _admin=admin, db=db,
        )

    assert result.total == 1
    assert result.items[0].account_id == ACCOUNT_ID
