"""Tests for the Corporate Travel Itinerary service layer.

Covers:
  - ItineraryStatus enum values
  - create_itinerary (async, mocked DB)
  - get_itinerary (async, mocked DB)
  - update_itinerary (async, mocked DB)
  - cancel_itinerary (async, mocked DB)
  - complete_itinerary (async, mocked DB)
  - list_itineraries (async, mocked DB — two execute() calls)
  - add_ride_to_itinerary (async, mocked DB)
  - remove_ride_from_itinerary (async, mocked DB)
  - list_itinerary_rides (async, mocked DB)
  - get_itinerary_summary (async, mocked DB)
  - list_all_itineraries_platform (async, mocked DB — two execute() calls)
  - Pydantic schema validation (ItineraryCreate, ItineraryUpdate,
    ItineraryResponse, ItinerarySummaryResponse)

No live database is used. All DB interactions are mocked with AsyncMock /
MagicMock, following the pattern established in test_cancellation_policies.py.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

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

_UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(_UTC)


def _make_itinerary(
    itinerary_id: int = 1,
    account_id: int = 10,
    created_by_id: int = 5,
    title: str = "Q2 Sales Conference",
    description: str | None = "Annual Q2 conference",
    start_date: date | None = None,
    end_date: date | None = None,
    cost_center_id: int | None = None,
    trip_purpose_id: int | None = None,
    status: str = "draft",
    is_active: bool = True,
) -> MagicMock:
    """Build a CorporateTravelItinerary ORM mock."""
    obj = MagicMock(spec=CorporateTravelItinerary)
    obj.id = itinerary_id
    obj.account_id = account_id
    obj.created_by_id = created_by_id
    obj.title = title
    obj.description = description
    obj.start_date = start_date
    obj.end_date = end_date
    obj.cost_center_id = cost_center_id
    obj.trip_purpose_id = trip_purpose_id
    obj.status = status
    obj.is_active = is_active
    obj.created_at = _now()
    obj.updated_at = _now()
    return obj


def _make_ride_assoc(
    assoc_id: int = 1,
    itinerary_id: int = 1,
    ride_id: int | None = 100,
    added_by_id: int | None = 5,
    notes: str | None = None,
) -> MagicMock:
    """Build a CorporateItineraryRide ORM mock."""
    obj = MagicMock(spec=CorporateItineraryRide)
    obj.id = assoc_id
    obj.itinerary_id = itinerary_id
    obj.ride_id = ride_id
    obj.added_by_id = added_by_id
    obj.notes = notes
    obj.added_at = _now()
    return obj


def _scalar_result(value) -> MagicMock:
    """MagicMock result whose .scalar_one_or_none() returns value."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalar_one_result(value) -> MagicMock:
    """MagicMock result whose .scalar_one() returns value."""
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


def _scalars_all_result(items: list) -> MagicMock:
    """MagicMock result whose .scalars().all() returns items."""
    r = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    r.scalars.return_value = scalars_mock
    return r


def _db_with_itinerary(itinerary: MagicMock | None) -> AsyncMock:
    """DB mock that returns the given itinerary from the first execute call."""
    db = AsyncMock()
    result = _scalar_result(itinerary)
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


def _db_sequence(*side_effects) -> AsyncMock:
    """DB mock whose execute() returns each MagicMock result in turn."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(side_effects))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


# ===========================================================================
# TestItineraryStatusEnum
# ===========================================================================


class TestItineraryStatusEnum:
    def test_draft_value(self):
        assert ItineraryStatus.draft.value == "draft"

    def test_active_value(self):
        assert ItineraryStatus.active.value == "active"

    def test_completed_value(self):
        assert ItineraryStatus.completed.value == "completed"

    def test_cancelled_value(self):
        assert ItineraryStatus.cancelled.value == "cancelled"

    def test_is_str_enum(self):
        assert isinstance(ItineraryStatus.draft, str)

    def test_four_members(self):
        assert len(ItineraryStatus) == 4

    def test_draft_from_string(self):
        assert ItineraryStatus("draft") == ItineraryStatus.draft

    def test_cancelled_from_string(self):
        assert ItineraryStatus("cancelled") == ItineraryStatus.cancelled


# ===========================================================================
# TestCreateItinerary
# ===========================================================================


class TestCreateItinerary:
    @pytest.mark.asyncio
    async def test_success_returns_response(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        mock_obj = _make_itinerary(status="draft", is_active=True)

        async def _refresh(obj):
            obj.id = 1
            obj.account_id = 10
            obj.created_by_id = 5
            obj.title = "Q2 Sales Conference"
            obj.description = None
            obj.start_date = None
            obj.end_date = None
            obj.cost_center_id = None
            obj.trip_purpose_id = None
            obj.status = "draft"
            obj.is_active = True
            obj.created_at = mock_obj.created_at
            obj.updated_at = mock_obj.updated_at

        db.refresh = _refresh

        data = ItineraryCreate(title="Q2 Sales Conference")
        result = await create_itinerary(db, account_id=10, data=data, member_id=5)

        assert result.status == "draft"
        assert result.is_active is True

    @pytest.mark.asyncio
    async def test_db_add_called(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        mock_obj = _make_itinerary(status="draft", is_active=True)

        async def _refresh(obj):
            for attr in ("id", "account_id", "created_by_id", "title",
                         "description", "start_date", "end_date",
                         "cost_center_id", "trip_purpose_id", "status",
                         "is_active", "created_at", "updated_at"):
                setattr(obj, attr, getattr(mock_obj, attr))

        db.refresh = _refresh

        data = ItineraryCreate(title="Trip")
        await create_itinerary(db, account_id=10, data=data, member_id=5)

        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_commit_called(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        mock_obj = _make_itinerary(status="draft")

        async def _refresh(obj):
            for attr in ("id", "account_id", "created_by_id", "title",
                         "description", "start_date", "end_date",
                         "cost_center_id", "trip_purpose_id", "status",
                         "is_active", "created_at", "updated_at"):
                setattr(obj, attr, getattr(mock_obj, attr))

        db.refresh = _refresh

        data = ItineraryCreate(title="Trip")
        await create_itinerary(db, account_id=10, data=data, member_id=5)

        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_created_by_id_set(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        mock_obj = _make_itinerary(created_by_id=99, status="draft")

        async def _refresh(obj):
            for attr in ("id", "account_id", "created_by_id", "title",
                         "description", "start_date", "end_date",
                         "cost_center_id", "trip_purpose_id", "status",
                         "is_active", "created_at", "updated_at"):
                setattr(obj, attr, getattr(mock_obj, attr))

        db.refresh = _refresh

        data = ItineraryCreate(title="Trip")
        result = await create_itinerary(db, account_id=10, data=data, member_id=99)

        assert result.created_by_id == 99

    @pytest.mark.asyncio
    async def test_with_optional_fields(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        start = date(2026, 6, 1)
        end = date(2026, 6, 5)
        mock_obj = _make_itinerary(
            title="Trip",
            description="desc",
            start_date=start,
            end_date=end,
            cost_center_id=7,
            trip_purpose_id=3,
            status="draft",
        )

        async def _refresh(obj):
            for attr in ("id", "account_id", "created_by_id", "title",
                         "description", "start_date", "end_date",
                         "cost_center_id", "trip_purpose_id", "status",
                         "is_active", "created_at", "updated_at"):
                setattr(obj, attr, getattr(mock_obj, attr))

        db.refresh = _refresh

        data = ItineraryCreate(
            title="Trip",
            description="desc",
            start_date=start,
            end_date=end,
            cost_center_id=7,
            trip_purpose_id=3,
        )
        result = await create_itinerary(db, account_id=10, data=data, member_id=5)

        assert result.description == "desc"
        assert result.cost_center_id == 7
        assert result.trip_purpose_id == 3


# ===========================================================================
# TestGetItinerary
# ===========================================================================


class TestGetItinerary:
    @pytest.mark.asyncio
    async def test_found_returns_response(self):
        mock_obj = _make_itinerary(itinerary_id=1, status="active")
        db = _db_with_itinerary(mock_obj)

        result = await get_itinerary(db, account_id=10, itinerary_id=1)

        assert result.id == 1
        assert result.status == "active"
        assert result.title == "Q2 Sales Conference"

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        db = _db_with_itinerary(None)

        with pytest.raises(HTTPException) as exc_info:
            await get_itinerary(db, account_id=10, itinerary_id=999)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_correct_account_id(self):
        mock_obj = _make_itinerary(account_id=42)
        db = _db_with_itinerary(mock_obj)

        result = await get_itinerary(db, account_id=42, itinerary_id=1)

        assert result.account_id == 42

    @pytest.mark.asyncio
    async def test_404_detail_message(self):
        db = _db_with_itinerary(None)

        with pytest.raises(HTTPException) as exc_info:
            await get_itinerary(db, account_id=10, itinerary_id=999)

        assert "not found" in exc_info.value.detail.lower()


# ===========================================================================
# TestUpdateItinerary
# ===========================================================================


class TestUpdateItinerary:
    @pytest.mark.asyncio
    async def test_success_updates_title(self):
        mock_obj = _make_itinerary(title="Old Title", status="active")
        db = _db_with_itinerary(mock_obj)

        async def _refresh(obj):
            obj.title = "New Title"

        db.refresh = _refresh

        data = ItineraryUpdate(title="New Title")
        result = await update_itinerary(
            db, account_id=10, itinerary_id=1, data=data, member_id=5
        )

        assert result.title == "New Title"

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        db = _db_with_itinerary(None)

        data = ItineraryUpdate(title="New Title")
        with pytest.raises(HTTPException) as exc_info:
            await update_itinerary(
                db, account_id=10, itinerary_id=999, data=data, member_id=5
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cancelled_raises_409(self):
        mock_obj = _make_itinerary(status="cancelled")
        db = _db_with_itinerary(mock_obj)

        data = ItineraryUpdate(title="New Title")
        with pytest.raises(HTTPException) as exc_info:
            await update_itinerary(
                db, account_id=10, itinerary_id=1, data=data, member_id=5
            )

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_db_commit_called_on_success(self):
        mock_obj = _make_itinerary(status="draft")
        db = _db_with_itinerary(mock_obj)

        data = ItineraryUpdate(description="Updated desc")
        await update_itinerary(
            db, account_id=10, itinerary_id=1, data=data, member_id=5
        )

        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_partial_update_only_sets_supplied_fields(self):
        # Use a plain dict-backed object so we can verify which fields changed.
        class _FakeItinerary:
            id = 1
            account_id = 10
            created_by_id = 5
            title = "Original"
            description = "keep me"
            start_date = None
            end_date = None
            cost_center_id = None
            trip_purpose_id = None
            status = "draft"
            is_active = True
            created_at = _now()
            updated_at = _now()
            touched: list = []

            def __setattr__(self, name, value):
                if name != "touched":
                    object.__getattribute__(self, "touched").append(name)
                object.__setattr__(self, name, value)

        fake = _FakeItinerary()

        db = AsyncMock()
        result = _scalar_result(fake)
        db.execute = AsyncMock(return_value=result)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        data = ItineraryUpdate(title="Changed")
        await update_itinerary(
            db, account_id=10, itinerary_id=1, data=data, member_id=5
        )

        # Only "title" should have been written; "description" must not be touched
        assert "title" in fake.touched
        assert "description" not in fake.touched

    @pytest.mark.asyncio
    async def test_update_status_to_active(self):
        mock_obj = _make_itinerary(status="draft")
        db = _db_with_itinerary(mock_obj)

        async def _refresh(obj):
            obj.status = "active"

        db.refresh = _refresh

        data = ItineraryUpdate(status=ItineraryStatus.active)
        result = await update_itinerary(
            db, account_id=10, itinerary_id=1, data=data, member_id=5
        )

        assert result.status == "active"


# ===========================================================================
# TestCancelItinerary
# ===========================================================================


class TestCancelItinerary:
    @pytest.mark.asyncio
    async def test_success_sets_status_cancelled(self):
        mock_obj = _make_itinerary(status="active")
        db = _db_with_itinerary(mock_obj)

        async def _refresh(obj):
            obj.status = "cancelled"

        db.refresh = _refresh

        result = await cancel_itinerary(db, account_id=10, itinerary_id=1)

        assert result.status == "cancelled"

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        db = _db_with_itinerary(None)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_itinerary(db, account_id=10, itinerary_id=999)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_already_cancelled_raises_409(self):
        mock_obj = _make_itinerary(status="cancelled")
        db = _db_with_itinerary(mock_obj)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_itinerary(db, account_id=10, itinerary_id=1)

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_status_attribute_set_to_cancelled(self):
        mock_obj = _make_itinerary(status="draft")
        db = _db_with_itinerary(mock_obj)

        await cancel_itinerary(db, account_id=10, itinerary_id=1)

        assert mock_obj.status == "cancelled"

    @pytest.mark.asyncio
    async def test_commit_called_on_success(self):
        mock_obj = _make_itinerary(status="active")
        db = _db_with_itinerary(mock_obj)

        await cancel_itinerary(db, account_id=10, itinerary_id=1)

        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_draft_itinerary_can_be_cancelled(self):
        mock_obj = _make_itinerary(status="draft")
        db = _db_with_itinerary(mock_obj)

        async def _refresh(obj):
            obj.status = "cancelled"

        db.refresh = _refresh

        result = await cancel_itinerary(db, account_id=10, itinerary_id=1)

        assert result.status == "cancelled"


# ===========================================================================
# TestCompleteItinerary
# ===========================================================================


class TestCompleteItinerary:
    @pytest.mark.asyncio
    async def test_success_sets_status_completed(self):
        mock_obj = _make_itinerary(status="active")
        db = _db_with_itinerary(mock_obj)

        async def _refresh(obj):
            obj.status = "completed"

        db.refresh = _refresh

        result = await complete_itinerary(db, account_id=10, itinerary_id=1)

        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        db = _db_with_itinerary(None)

        with pytest.raises(HTTPException) as exc_info:
            await complete_itinerary(db, account_id=10, itinerary_id=999)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cancelled_raises_409(self):
        mock_obj = _make_itinerary(status="cancelled")
        db = _db_with_itinerary(mock_obj)

        with pytest.raises(HTTPException) as exc_info:
            await complete_itinerary(db, account_id=10, itinerary_id=1)

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_status_attribute_set_to_completed(self):
        mock_obj = _make_itinerary(status="active")
        db = _db_with_itinerary(mock_obj)

        await complete_itinerary(db, account_id=10, itinerary_id=1)

        assert mock_obj.status == "completed"

    @pytest.mark.asyncio
    async def test_commit_called_on_success(self):
        mock_obj = _make_itinerary(status="draft")
        db = _db_with_itinerary(mock_obj)

        await complete_itinerary(db, account_id=10, itinerary_id=1)

        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_draft_itinerary_can_be_completed(self):
        mock_obj = _make_itinerary(status="draft")
        db = _db_with_itinerary(mock_obj)

        async def _refresh(obj):
            obj.status = "completed"

        db.refresh = _refresh

        result = await complete_itinerary(db, account_id=10, itinerary_id=1)

        assert result.status == "completed"


# ===========================================================================
# TestListItineraries
# ===========================================================================


class TestListItineraries:
    @pytest.mark.asyncio
    async def test_returns_list_response(self):
        mock_obj = _make_itinerary(status="draft")

        count_result = _scalar_one_result(1)
        data_result = _scalars_all_result([mock_obj])

        db = _db_sequence(count_result, data_result)

        result = await list_itineraries(db, account_id=10)

        assert isinstance(result, ItineraryListResponse)
        assert result.total == 1
        assert len(result.items) == 1

    @pytest.mark.asyncio
    async def test_empty_list(self):
        count_result = _scalar_one_result(0)
        data_result = _scalars_all_result([])

        db = _db_sequence(count_result, data_result)

        result = await list_itineraries(db, account_id=10)

        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_pagination_params_reflected(self):
        count_result = _scalar_one_result(20)
        data_result = _scalars_all_result([])

        db = _db_sequence(count_result, data_result)

        result = await list_itineraries(db, account_id=10, limit=5, offset=10)

        assert result.limit == 5
        assert result.offset == 10

    @pytest.mark.asyncio
    async def test_status_filter_passes_through(self):
        mock_obj = _make_itinerary(status="active")

        count_result = _scalar_one_result(1)
        data_result = _scalars_all_result([mock_obj])

        db = _db_sequence(count_result, data_result)

        result = await list_itineraries(db, account_id=10, status="active")

        assert result.items[0].status == "active"

    @pytest.mark.asyncio
    async def test_created_by_id_filter(self):
        mock_obj = _make_itinerary(created_by_id=7)

        count_result = _scalar_one_result(1)
        data_result = _scalars_all_result([mock_obj])

        db = _db_sequence(count_result, data_result)

        result = await list_itineraries(db, account_id=10, created_by_id=7)

        assert result.items[0].created_by_id == 7

    @pytest.mark.asyncio
    async def test_multiple_items_in_response(self):
        items = [_make_itinerary(itinerary_id=i) for i in range(1, 4)]

        count_result = _scalar_one_result(3)
        data_result = _scalars_all_result(items)

        db = _db_sequence(count_result, data_result)

        result = await list_itineraries(db, account_id=10)

        assert result.total == 3
        assert len(result.items) == 3

    @pytest.mark.asyncio
    async def test_two_execute_calls_made(self):
        count_result = _scalar_one_result(0)
        data_result = _scalars_all_result([])

        db = _db_sequence(count_result, data_result)

        await list_itineraries(db, account_id=10)

        assert db.execute.await_count == 2


# ===========================================================================
# TestAddRideToItinerary
# ===========================================================================


class TestAddRideToItinerary:
    @pytest.mark.asyncio
    async def test_success_returns_ride_response(self):
        mock_itinerary = _make_itinerary(status="active")
        mock_assoc = _make_ride_assoc(ride_id=100, notes="business trip")

        # First call: fetch itinerary; second call: duplicate check (None)
        itinerary_result = _scalar_result(mock_itinerary)
        duplicate_result = _scalar_result(None)

        db = _db_sequence(itinerary_result, duplicate_result)

        async def _refresh(obj):
            obj.id = mock_assoc.id
            obj.itinerary_id = mock_assoc.itinerary_id
            obj.ride_id = mock_assoc.ride_id
            obj.added_by_id = mock_assoc.added_by_id
            obj.notes = mock_assoc.notes
            obj.added_at = mock_assoc.added_at

        db.refresh = _refresh

        result = await add_ride_to_itinerary(
            db,
            account_id=10,
            itinerary_id=1,
            ride_id=100,
            member_id=5,
            notes="business trip",
        )

        assert result.ride_id == 100
        assert result.notes == "business trip"

    @pytest.mark.asyncio
    async def test_itinerary_not_found_raises_404(self):
        itinerary_result = _scalar_result(None)
        db = _db_sequence(itinerary_result)

        with pytest.raises(HTTPException) as exc_info:
            await add_ride_to_itinerary(
                db, account_id=10, itinerary_id=999, ride_id=100, member_id=5
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cancelled_itinerary_raises_409(self):
        mock_itinerary = _make_itinerary(status="cancelled")
        itinerary_result = _scalar_result(mock_itinerary)

        db = _db_sequence(itinerary_result)

        with pytest.raises(HTTPException) as exc_info:
            await add_ride_to_itinerary(
                db, account_id=10, itinerary_id=1, ride_id=100, member_id=5
            )

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_duplicate_ride_raises_409(self):
        mock_itinerary = _make_itinerary(status="active")
        existing_assoc = _make_ride_assoc(ride_id=100)

        itinerary_result = _scalar_result(mock_itinerary)
        duplicate_result = _scalar_result(existing_assoc)

        db = _db_sequence(itinerary_result, duplicate_result)

        with pytest.raises(HTTPException) as exc_info:
            await add_ride_to_itinerary(
                db, account_id=10, itinerary_id=1, ride_id=100, member_id=5
            )

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_db_add_called_on_success(self):
        mock_itinerary = _make_itinerary(status="draft")
        mock_assoc = _make_ride_assoc()

        itinerary_result = _scalar_result(mock_itinerary)
        duplicate_result = _scalar_result(None)

        db = _db_sequence(itinerary_result, duplicate_result)

        async def _refresh(obj):
            obj.id = mock_assoc.id
            obj.itinerary_id = mock_assoc.itinerary_id
            obj.ride_id = mock_assoc.ride_id
            obj.added_by_id = mock_assoc.added_by_id
            obj.notes = mock_assoc.notes
            obj.added_at = mock_assoc.added_at

        db.refresh = _refresh

        await add_ride_to_itinerary(
            db, account_id=10, itinerary_id=1, ride_id=100, member_id=5
        )

        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancelled_409_detail_message(self):
        mock_itinerary = _make_itinerary(status="cancelled")
        db = _db_sequence(_scalar_result(mock_itinerary))

        with pytest.raises(HTTPException) as exc_info:
            await add_ride_to_itinerary(
                db, account_id=10, itinerary_id=1, ride_id=100, member_id=5
            )

        assert "cancelled" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_with_no_notes(self):
        mock_itinerary = _make_itinerary(status="active")
        mock_assoc = _make_ride_assoc(notes=None)

        itinerary_result = _scalar_result(mock_itinerary)
        duplicate_result = _scalar_result(None)

        db = _db_sequence(itinerary_result, duplicate_result)

        async def _refresh(obj):
            obj.id = mock_assoc.id
            obj.itinerary_id = mock_assoc.itinerary_id
            obj.ride_id = mock_assoc.ride_id
            obj.added_by_id = mock_assoc.added_by_id
            obj.notes = None
            obj.added_at = mock_assoc.added_at

        db.refresh = _refresh

        result = await add_ride_to_itinerary(
            db, account_id=10, itinerary_id=1, ride_id=200, member_id=5
        )

        assert result.notes is None


# ===========================================================================
# TestRemoveRideFromItinerary
# ===========================================================================


class TestRemoveRideFromItinerary:
    @pytest.mark.asyncio
    async def test_success_calls_delete_and_commit(self):
        mock_itinerary = _make_itinerary()
        mock_assoc = _make_ride_assoc(ride_id=100)

        itinerary_result = _scalar_result(mock_itinerary)
        assoc_result = _scalar_result(mock_assoc)

        db = _db_sequence(itinerary_result, assoc_result)

        await remove_ride_from_itinerary(
            db, account_id=10, itinerary_id=1, ride_id=100
        )

        db.delete.assert_awaited_once_with(mock_assoc)
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_itinerary_not_found_raises_404(self):
        itinerary_result = _scalar_result(None)
        db = _db_sequence(itinerary_result)

        with pytest.raises(HTTPException) as exc_info:
            await remove_ride_from_itinerary(
                db, account_id=10, itinerary_id=999, ride_id=100
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_association_not_found_raises_404(self):
        mock_itinerary = _make_itinerary()
        itinerary_result = _scalar_result(mock_itinerary)
        assoc_result = _scalar_result(None)

        db = _db_sequence(itinerary_result, assoc_result)

        with pytest.raises(HTTPException) as exc_info:
            await remove_ride_from_itinerary(
                db, account_id=10, itinerary_id=1, ride_id=999
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_association_not_found_detail_message(self):
        mock_itinerary = _make_itinerary()
        db = _db_sequence(_scalar_result(mock_itinerary), _scalar_result(None))

        with pytest.raises(HTTPException) as exc_info:
            await remove_ride_from_itinerary(
                db, account_id=10, itinerary_id=1, ride_id=999
            )

        assert "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_returns_none_on_success(self):
        mock_itinerary = _make_itinerary()
        mock_assoc = _make_ride_assoc()

        db = _db_sequence(_scalar_result(mock_itinerary), _scalar_result(mock_assoc))

        result = await remove_ride_from_itinerary(
            db, account_id=10, itinerary_id=1, ride_id=100
        )

        assert result is None


# ===========================================================================
# TestListItineraryRides
# ===========================================================================


class TestListItineraryRides:
    @pytest.mark.asyncio
    async def test_success_returns_ride_list_response(self):
        mock_itinerary = _make_itinerary()
        mock_assoc = _make_ride_assoc(ride_id=100)

        # execute calls: (1) fetch itinerary, (2) count, (3) data
        itinerary_result = _scalar_result(mock_itinerary)
        count_result = _scalar_one_result(1)
        data_result = _scalars_all_result([mock_assoc])

        db = _db_sequence(itinerary_result, count_result, data_result)

        result = await list_itinerary_rides(
            db, account_id=10, itinerary_id=1
        )

        assert isinstance(result, ItineraryRideListResponse)
        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].ride_id == 100

    @pytest.mark.asyncio
    async def test_itinerary_not_found_raises_404(self):
        db = _db_sequence(_scalar_result(None))

        with pytest.raises(HTTPException) as exc_info:
            await list_itinerary_rides(db, account_id=10, itinerary_id=999)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_empty_rides(self):
        mock_itinerary = _make_itinerary()

        itinerary_result = _scalar_result(mock_itinerary)
        count_result = _scalar_one_result(0)
        data_result = _scalars_all_result([])

        db = _db_sequence(itinerary_result, count_result, data_result)

        result = await list_itinerary_rides(db, account_id=10, itinerary_id=1)

        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_pagination_params_reflected(self):
        mock_itinerary = _make_itinerary()
        count_result = _scalar_one_result(20)
        data_result = _scalars_all_result([])

        db = _db_sequence(_scalar_result(mock_itinerary), count_result, data_result)

        result = await list_itinerary_rides(
            db, account_id=10, itinerary_id=1, limit=10, offset=5
        )

        assert result.limit == 10
        assert result.offset == 5

    @pytest.mark.asyncio
    async def test_multiple_rides(self):
        mock_itinerary = _make_itinerary()
        assocs = [_make_ride_assoc(assoc_id=i, ride_id=100 + i) for i in range(1, 4)]

        count_result = _scalar_one_result(3)
        data_result = _scalars_all_result(assocs)

        db = _db_sequence(_scalar_result(mock_itinerary), count_result, data_result)

        result = await list_itinerary_rides(db, account_id=10, itinerary_id=1)

        assert result.total == 3
        assert len(result.items) == 3


# ===========================================================================
# TestGetItinerarySummary
# ===========================================================================


class TestGetItinerarySummary:
    @pytest.mark.asyncio
    async def test_success_with_rides(self):
        mock_itinerary = _make_itinerary(itinerary_id=1, title="Sales Trip", status="active")
        assocs = [
            _make_ride_assoc(assoc_id=1, ride_id=101),
            _make_ride_assoc(assoc_id=2, ride_id=102),
        ]

        itinerary_result = _scalar_result(mock_itinerary)
        assoc_data_result = _scalars_all_result(assocs)

        db = _db_sequence(itinerary_result, assoc_data_result)

        result = await get_itinerary_summary(db, account_id=10, itinerary_id=1)

        assert isinstance(result, ItinerarySummaryResponse)
        assert result.itinerary_id == 1
        assert result.title == "Sales Trip"
        assert result.status == "active"
        assert result.total_rides == 2
        assert set(result.ride_ids) == {101, 102}

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        db = _db_sequence(_scalar_result(None))

        with pytest.raises(HTTPException) as exc_info:
            await get_itinerary_summary(db, account_id=10, itinerary_id=999)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_no_rides_returns_zero_count(self):
        mock_itinerary = _make_itinerary(status="draft")
        itinerary_result = _scalar_result(mock_itinerary)
        assoc_data_result = _scalars_all_result([])

        db = _db_sequence(itinerary_result, assoc_data_result)

        result = await get_itinerary_summary(db, account_id=10, itinerary_id=1)

        assert result.total_rides == 0
        assert result.ride_ids == []

    @pytest.mark.asyncio
    async def test_ride_ids_excludes_null_ride_ids(self):
        mock_itinerary = _make_itinerary()
        assoc_with_null_ride = _make_ride_assoc(assoc_id=1, ride_id=None)
        assoc_with_ride = _make_ride_assoc(assoc_id=2, ride_id=200)

        db = _db_sequence(
            _scalar_result(mock_itinerary),
            _scalars_all_result([assoc_with_null_ride, assoc_with_ride]),
        )

        result = await get_itinerary_summary(db, account_id=10, itinerary_id=1)

        assert result.total_rides == 2
        assert 200 in result.ride_ids
        assert None not in result.ride_ids

    @pytest.mark.asyncio
    async def test_ride_ids_is_list(self):
        mock_itinerary = _make_itinerary()
        db = _db_sequence(
            _scalar_result(mock_itinerary),
            _scalars_all_result([]),
        )

        result = await get_itinerary_summary(db, account_id=10, itinerary_id=1)

        assert isinstance(result.ride_ids, list)


# ===========================================================================
# TestListAllItinerariesPlatform
# ===========================================================================


class TestListAllItinerariesPlatform:
    @pytest.mark.asyncio
    async def test_returns_paginated_list(self):
        items = [_make_itinerary(itinerary_id=i, account_id=i * 10) for i in range(1, 4)]

        count_result = _scalar_one_result(3)
        data_result = _scalars_all_result(items)

        db = _db_sequence(count_result, data_result)

        result = await list_all_itineraries_platform(db, limit=50, offset=0)

        assert isinstance(result, ItineraryListResponse)
        assert result.total == 3
        assert len(result.items) == 3

    @pytest.mark.asyncio
    async def test_empty_platform_list(self):
        count_result = _scalar_one_result(0)
        data_result = _scalars_all_result([])

        db = _db_sequence(count_result, data_result)

        result = await list_all_itineraries_platform(db)

        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_pagination_params_reflected(self):
        count_result = _scalar_one_result(100)
        data_result = _scalars_all_result([])

        db = _db_sequence(count_result, data_result)

        result = await list_all_itineraries_platform(db, limit=10, offset=20)

        assert result.limit == 10
        assert result.offset == 20

    @pytest.mark.asyncio
    async def test_two_execute_calls_made(self):
        count_result = _scalar_one_result(0)
        data_result = _scalars_all_result([])

        db = _db_sequence(count_result, data_result)

        await list_all_itineraries_platform(db)

        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_cross_account_items_included(self):
        # Items from different accounts should all appear
        item_a = _make_itinerary(itinerary_id=1, account_id=10)
        item_b = _make_itinerary(itinerary_id=2, account_id=20)

        count_result = _scalar_one_result(2)
        data_result = _scalars_all_result([item_a, item_b])

        db = _db_sequence(count_result, data_result)

        result = await list_all_itineraries_platform(db)

        account_ids = {item.account_id for item in result.items}
        assert 10 in account_ids
        assert 20 in account_ids


# ===========================================================================
# TestItinerarySchemas
# ===========================================================================


class TestItinerarySchemas:
    def test_create_empty_title_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ItineraryCreate(title="")

    def test_create_whitespace_title_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ItineraryCreate(title="   ")

    def test_create_valid_title(self):
        schema = ItineraryCreate(title="Sales Conference")
        assert schema.title == "Sales Conference"

    def test_create_optional_fields_default_none(self):
        schema = ItineraryCreate(title="Trip")
        assert schema.description is None
        assert schema.start_date is None
        assert schema.end_date is None
        assert schema.cost_center_id is None
        assert schema.trip_purpose_id is None

    def test_create_all_fields(self):
        schema = ItineraryCreate(
            title="Trip",
            description="desc",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5),
            cost_center_id=3,
            trip_purpose_id=7,
        )
        assert schema.cost_center_id == 3
        assert schema.trip_purpose_id == 7

    def test_update_all_fields_optional(self):
        schema = ItineraryUpdate()
        assert schema.title is None
        assert schema.description is None
        assert schema.start_date is None
        assert schema.end_date is None
        assert schema.cost_center_id is None
        assert schema.trip_purpose_id is None
        assert schema.status is None
        assert schema.is_active is None

    def test_update_with_status_enum(self):
        schema = ItineraryUpdate(status=ItineraryStatus.active)
        assert schema.status == ItineraryStatus.active

    def test_response_from_attributes(self):
        now = _now()
        mock_obj = _make_itinerary(status="draft")
        mock_obj.created_at = now
        mock_obj.updated_at = now

        resp = ItineraryResponse.model_validate(mock_obj)

        assert resp.id == mock_obj.id
        assert resp.title == mock_obj.title
        assert resp.status == "draft"

    def test_list_response_structure(self):
        now = _now()
        mock_obj = _make_itinerary()
        mock_obj.created_at = now
        mock_obj.updated_at = now

        item = ItineraryResponse.model_validate(mock_obj)
        resp = ItineraryListResponse(total=1, limit=50, offset=0, items=[item])

        assert resp.total == 1
        assert len(resp.items) == 1

    def test_ride_create_with_notes(self):
        schema = ItineraryRideCreate(ride_id=42, notes="business reason")
        assert schema.ride_id == 42
        assert schema.notes == "business reason"

    def test_ride_create_notes_optional(self):
        schema = ItineraryRideCreate(ride_id=42)
        assert schema.notes is None

    def test_summary_response_ride_ids_is_list(self):
        resp = ItinerarySummaryResponse(
            itinerary_id=1,
            title="Trip",
            status="active",
            total_rides=2,
            ride_ids=[100, 200],
        )
        assert isinstance(resp.ride_ids, list)
        assert resp.total_rides == 2

    def test_summary_response_empty_ride_ids(self):
        resp = ItinerarySummaryResponse(
            itinerary_id=1,
            title="Trip",
            status="draft",
            total_rides=0,
            ride_ids=[],
        )
        assert resp.ride_ids == []
        assert resp.total_rides == 0

    def test_itinerary_ride_response_from_attributes(self):
        now = _now()
        mock_assoc = _make_ride_assoc(assoc_id=5, ride_id=101, notes="note")
        mock_assoc.added_at = now

        resp = ItineraryRideResponse.model_validate(mock_assoc)

        assert resp.id == 5
        assert resp.ride_id == 101
        assert resp.notes == "note"

    def test_ride_list_response_structure(self):
        now = _now()
        assoc = _make_ride_assoc()
        assoc.added_at = now

        item = ItineraryRideResponse.model_validate(assoc)
        resp = ItineraryRideListResponse(total=1, limit=50, offset=0, items=[item])

        assert resp.total == 1
        assert len(resp.items) == 1
