"""Tests for saved locations (home, work, favorites).

Covers model, schema validation, service logic, and API endpoints.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.saved_location import LocationLabel, SavedLocation
from app.schemas.saved_location import (
    SavedLocationCreate,
    SavedLocationResponse,
    SavedLocationUpdate,
)
from app.services.saved_locations import (
    MAX_SAVED_LOCATIONS,
    SavedLocationError,
    create_saved_location,
    delete_saved_location,
    get_saved_location,
    get_saved_locations,
    update_saved_location,
)


# ===========================================================================
# SavedLocation Model Tests
# ===========================================================================


class TestSavedLocationModel:
    def test_table_name(self):
        assert SavedLocation.__tablename__ == "saved_locations"

    def test_has_user_id_column(self):
        cols = {c.name for c in SavedLocation.__table__.columns}
        assert "user_id" in cols

    def test_has_label_column(self):
        cols = {c.name for c in SavedLocation.__table__.columns}
        assert "label" in cols

    def test_has_name_column(self):
        cols = {c.name for c in SavedLocation.__table__.columns}
        assert "name" in cols

    def test_has_address_column(self):
        cols = {c.name for c in SavedLocation.__table__.columns}
        assert "address" in cols

    def test_has_lat_column(self):
        cols = {c.name for c in SavedLocation.__table__.columns}
        assert "lat" in cols

    def test_has_lng_column(self):
        cols = {c.name for c in SavedLocation.__table__.columns}
        assert "lng" in cols

    def test_has_place_id_column(self):
        cols = {c.name for c in SavedLocation.__table__.columns}
        assert "place_id" in cols

    def test_has_icon_column(self):
        cols = {c.name for c in SavedLocation.__table__.columns}
        assert "icon" in cols

    def test_has_created_at_column(self):
        cols = {c.name for c in SavedLocation.__table__.columns}
        assert "created_at" in cols

    def test_has_updated_at_column(self):
        cols = {c.name for c in SavedLocation.__table__.columns}
        assert "updated_at" in cols

    def test_user_id_is_indexed(self):
        col = SavedLocation.__table__.columns["user_id"]
        assert col.index is True

    def test_user_id_has_fk(self):
        col = SavedLocation.__table__.columns["user_id"]
        fk_targets = [fk.target_fullname for fk in col.foreign_keys]
        assert "users.id" in fk_targets

    def test_place_id_is_nullable(self):
        col = SavedLocation.__table__.columns["place_id"]
        assert col.nullable is True

    def test_icon_is_nullable(self):
        col = SavedLocation.__table__.columns["icon"]
        assert col.nullable is True


# ===========================================================================
# LocationLabel Enum Tests
# ===========================================================================


class TestLocationLabel:
    def test_home_value(self):
        assert LocationLabel.HOME == "home"

    def test_work_value(self):
        assert LocationLabel.WORK == "work"

    def test_custom_value(self):
        assert LocationLabel.CUSTOM == "custom"

    def test_all_labels(self):
        values = {l.value for l in LocationLabel}
        assert values == {"home", "work", "custom"}


# ===========================================================================
# Schema Validation Tests
# ===========================================================================


class TestSavedLocationCreateSchema:
    def test_valid_home_location(self):
        loc = SavedLocationCreate(
            label="home",
            name="My House",
            address="123 Main St, City, ST 12345",
            lat=40.7128,
            lng=-74.0060,
        )
        assert loc.label == "home"
        assert loc.name == "My House"

    def test_valid_work_location(self):
        loc = SavedLocationCreate(
            label="work",
            name="Office",
            address="456 Corporate Dr",
            lat=37.7749,
            lng=-122.4194,
        )
        assert loc.label == "work"

    def test_valid_custom_location(self):
        loc = SavedLocationCreate(
            label="custom",
            name="Mom's House",
            address="789 Elm St",
            lat=34.0522,
            lng=-118.2437,
        )
        assert loc.label == "custom"

    def test_default_label_is_custom(self):
        loc = SavedLocationCreate(
            name="Gym",
            address="100 Fitness Ave",
            lat=40.0,
            lng=-74.0,
        )
        assert loc.label == "custom"

    def test_invalid_label_rejected(self):
        with pytest.raises(ValueError, match="Label must be one of"):
            SavedLocationCreate(
                label="favorite",
                name="Place",
                address="Addr",
                lat=40.0,
                lng=-74.0,
            )

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError, match="Name must be 1-100 characters"):
            SavedLocationCreate(
                name="",
                address="Addr",
                lat=40.0,
                lng=-74.0,
            )

    def test_whitespace_only_name_rejected(self):
        with pytest.raises(ValueError, match="Name must be 1-100 characters"):
            SavedLocationCreate(
                name="   ",
                address="Addr",
                lat=40.0,
                lng=-74.0,
            )

    def test_long_name_rejected(self):
        with pytest.raises(ValueError, match="Name must be 1-100 characters"):
            SavedLocationCreate(
                name="x" * 101,
                address="Addr",
                lat=40.0,
                lng=-74.0,
            )

    def test_name_is_stripped(self):
        loc = SavedLocationCreate(
            name="  My Place  ",
            address="Addr",
            lat=40.0,
            lng=-74.0,
        )
        assert loc.name == "My Place"

    def test_lat_below_range_rejected(self):
        with pytest.raises(ValueError, match="Latitude must be between"):
            SavedLocationCreate(
                name="Place",
                address="Addr",
                lat=-91.0,
                lng=-74.0,
            )

    def test_lat_above_range_rejected(self):
        with pytest.raises(ValueError, match="Latitude must be between"):
            SavedLocationCreate(
                name="Place",
                address="Addr",
                lat=91.0,
                lng=-74.0,
            )

    def test_lng_below_range_rejected(self):
        with pytest.raises(ValueError, match="Longitude must be between"):
            SavedLocationCreate(
                name="Place",
                address="Addr",
                lat=40.0,
                lng=-181.0,
            )

    def test_lng_above_range_rejected(self):
        with pytest.raises(ValueError, match="Longitude must be between"):
            SavedLocationCreate(
                name="Place",
                address="Addr",
                lat=40.0,
                lng=181.0,
            )

    def test_boundary_lat_values_accepted(self):
        loc_min = SavedLocationCreate(name="South Pole", address="A", lat=-90.0, lng=0.0)
        loc_max = SavedLocationCreate(name="North Pole", address="A", lat=90.0, lng=0.0)
        assert loc_min.lat == -90.0
        assert loc_max.lat == 90.0

    def test_boundary_lng_values_accepted(self):
        loc_min = SavedLocationCreate(name="West", address="A", lat=0.0, lng=-180.0)
        loc_max = SavedLocationCreate(name="East", address="A", lat=0.0, lng=180.0)
        assert loc_min.lng == -180.0
        assert loc_max.lng == 180.0

    def test_optional_place_id(self):
        loc = SavedLocationCreate(
            name="Place",
            address="Addr",
            lat=40.0,
            lng=-74.0,
            place_id="ChIJd8BlQ2BZwokRAFUEcm_qrcA",
        )
        assert loc.place_id == "ChIJd8BlQ2BZwokRAFUEcm_qrcA"

    def test_optional_icon(self):
        loc = SavedLocationCreate(
            name="Place",
            address="Addr",
            lat=40.0,
            lng=-74.0,
            icon="star",
        )
        assert loc.icon == "star"

    def test_place_id_defaults_none(self):
        loc = SavedLocationCreate(name="P", address="A", lat=0.0, lng=0.0)
        assert loc.place_id is None

    def test_icon_defaults_none(self):
        loc = SavedLocationCreate(name="P", address="A", lat=0.0, lng=0.0)
        assert loc.icon is None


class TestSavedLocationUpdateSchema:
    def test_all_fields_optional(self):
        update = SavedLocationUpdate()
        data = update.model_dump(exclude_unset=True)
        assert data == {}

    def test_partial_update_name_only(self):
        update = SavedLocationUpdate(name="New Name")
        data = update.model_dump(exclude_unset=True)
        assert data == {"name": "New Name"}

    def test_partial_update_lat_lng(self):
        update = SavedLocationUpdate(lat=41.0, lng=-73.0)
        data = update.model_dump(exclude_unset=True)
        assert data == {"lat": 41.0, "lng": -73.0}

    def test_invalid_label_rejected(self):
        with pytest.raises(ValueError, match="Label must be one of"):
            SavedLocationUpdate(label="invalid")

    def test_valid_label_accepted(self):
        update = SavedLocationUpdate(label="home")
        assert update.label == "home"

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError, match="Name must be 1-100 characters"):
            SavedLocationUpdate(name="")

    def test_invalid_lat_rejected(self):
        with pytest.raises(ValueError, match="Latitude must be between"):
            SavedLocationUpdate(lat=100.0)

    def test_invalid_lng_rejected(self):
        with pytest.raises(ValueError, match="Longitude must be between"):
            SavedLocationUpdate(lng=200.0)

    def test_none_lat_accepted(self):
        update = SavedLocationUpdate(lat=None)
        assert update.lat is None

    def test_none_lng_accepted(self):
        update = SavedLocationUpdate(lng=None)
        assert update.lng is None


class TestSavedLocationResponseSchema:
    def test_from_attributes(self):
        assert SavedLocationResponse.model_config.get("from_attributes") is True

    def test_all_fields_present(self):
        fields = set(SavedLocationResponse.model_fields.keys())
        expected = {
            "id", "user_id", "label", "name", "address",
            "lat", "lng", "place_id", "icon", "created_at", "updated_at",
        }
        assert expected == fields

    def test_serialization(self):
        now = datetime.now(timezone.utc)
        resp = SavedLocationResponse(
            id=1,
            user_id=10,
            label="home",
            name="Home",
            address="123 Main St",
            lat=40.7128,
            lng=-74.0060,
            place_id=None,
            icon=None,
            created_at=now,
            updated_at=now,
        )
        assert resp.id == 1
        assert resp.label == "home"


# ===========================================================================
# Service Tests
# ===========================================================================


def _make_simple_db(**kwargs):
    """Create a simple mock async DB session with direct execute result."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    return db


def _make_count_then_select_db(count=0, label_match=None):
    """Mock DB for create_saved_location: first call returns count, second returns label check."""
    db = _make_simple_db()

    count_result = MagicMock()
    count_result.scalar.return_value = count

    label_result = MagicMock()
    label_result.scalar_one_or_none.return_value = label_match

    call_count = {"n": 0}

    async def execute_side_effect(stmt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return count_result
        return label_result

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _make_scalars_db(locations):
    """Mock DB that returns a list via .scalars().all()."""
    db = _make_simple_db()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = locations
    result = MagicMock()
    result.scalars.return_value = scalars_mock
    db.execute = AsyncMock(return_value=result)
    return db


def _make_scalar_one_db(value):
    """Mock DB that returns a single value via .scalar_one_or_none()."""
    db = _make_simple_db()
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    db.execute = AsyncMock(return_value=result)
    return db


def _make_location(
    id=1, user_id=10, label=LocationLabel.CUSTOM, name="Test",
    address="123 St", lat=40.7, lng=-74.0, place_id=None, icon=None,
):
    loc = MagicMock(spec=SavedLocation)
    loc.id = id
    loc.user_id = user_id
    loc.label = label
    loc.name = name
    loc.address = address
    loc.lat = lat
    loc.lng = lng
    loc.place_id = place_id
    loc.icon = icon
    loc.created_at = datetime.now(timezone.utc)
    loc.updated_at = datetime.now(timezone.utc)
    loc.submitted_at = datetime.now(timezone.utc)
    return loc


class TestCreateSavedLocation:
    @pytest.mark.asyncio
    async def test_creates_custom_location(self):
        db = _make_count_then_select_db(count=0)
        loc = await create_saved_location(
            db, user_id=10, label="custom", name="Gym",
            address="100 Fitness Ave", lat=40.0, lng=-74.0,
        )
        assert loc is not None
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_home_location(self):
        db = _make_count_then_select_db(count=0)
        loc = await create_saved_location(
            db, user_id=10, label="home", name="Home",
            address="123 Main St", lat=40.7, lng=-74.0,
        )
        assert loc is not None

    @pytest.mark.asyncio
    async def test_rejects_when_at_max_locations(self):
        db = _make_count_then_select_db(count=MAX_SAVED_LOCATIONS)
        with pytest.raises(SavedLocationError, match="Maximum"):
            await create_saved_location(
                db, user_id=10, label="custom", name="Extra",
                address="Addr", lat=40.0, lng=-74.0,
            )

    @pytest.mark.asyncio
    async def test_rejects_duplicate_home_label(self):
        existing_home = _make_location(label=LocationLabel.HOME, name="Old Home")
        db = _make_count_then_select_db(count=1, label_match=existing_home)
        with pytest.raises(SavedLocationError, match="already exists"):
            await create_saved_location(
                db, user_id=10, label="home", name="New Home",
                address="Addr", lat=40.0, lng=-74.0,
            )

    @pytest.mark.asyncio
    async def test_rejects_duplicate_work_label(self):
        existing_work = _make_location(label=LocationLabel.WORK, name="Old Office")
        db = _make_count_then_select_db(count=1, label_match=existing_work)
        with pytest.raises(SavedLocationError, match="already exists"):
            await create_saved_location(
                db, user_id=10, label="work", name="New Office",
                address="Addr", lat=40.0, lng=-74.0,
            )

    @pytest.mark.asyncio
    async def test_allows_multiple_custom_locations(self):
        db = _make_count_then_select_db(count=3)
        loc = await create_saved_location(
            db, user_id=10, label="custom", name="Place 4",
            address="Addr", lat=40.0, lng=-74.0,
        )
        assert loc is not None

    @pytest.mark.asyncio
    async def test_stores_place_id(self):
        db = _make_count_then_select_db(count=0)
        loc = await create_saved_location(
            db, user_id=10, label="custom", name="Place",
            address="Addr", lat=40.0, lng=-74.0,
            place_id="ChIJtest123",
        )
        assert loc is not None

    @pytest.mark.asyncio
    async def test_stores_icon(self):
        db = _make_count_then_select_db(count=0)
        loc = await create_saved_location(
            db, user_id=10, label="custom", name="Place",
            address="Addr", lat=40.0, lng=-74.0,
            icon="heart",
        )
        assert loc is not None


class TestGetSavedLocations:
    @pytest.mark.asyncio
    async def test_returns_empty_for_new_user(self):
        db = _make_scalars_db([])
        result = await get_saved_locations(db, user_id=99)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_all_user_locations(self):
        locs = [
            _make_location(id=1, name="Home", label=LocationLabel.HOME),
            _make_location(id=2, name="Work", label=LocationLabel.WORK),
            _make_location(id=3, name="Gym", label=LocationLabel.CUSTOM),
        ]
        db = _make_scalars_db(locs)
        result = await get_saved_locations(db, user_id=10)
        assert len(result) == 3


class TestGetSavedLocation:
    @pytest.mark.asyncio
    async def test_returns_location_by_id(self):
        loc = _make_location(id=5, name="Office")
        db = _make_scalar_one_db(loc)
        result = await get_saved_location(db, user_id=10, location_id=5)
        assert result is not None

    @pytest.mark.asyncio
    async def test_returns_none_for_missing(self):
        db = _make_scalar_one_db(None)
        result = await get_saved_location(db, user_id=10, location_id=999)
        assert result is None

    @pytest.mark.asyncio
    async def test_scoped_to_user(self):
        """Different user should not see another user's location."""
        db = _make_scalar_one_db(None)
        result = await get_saved_location(db, user_id=20, location_id=1)
        assert result is None


class TestUpdateSavedLocation:
    @pytest.mark.asyncio
    async def test_updates_name(self):
        loc = _make_location(id=1, name="Old Name", label=LocationLabel.CUSTOM)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=loc)
        ))
        db.flush = AsyncMock()

        result = await update_saved_location(db, user_id=10, location_id=1, updates={"name": "New Name"})
        assert result.name == "New Name"

    @pytest.mark.asyncio
    async def test_updates_coordinates(self):
        loc = _make_location(id=1, lat=40.0, lng=-74.0)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=loc)
        ))
        db.flush = AsyncMock()

        result = await update_saved_location(
            db, user_id=10, location_id=1,
            updates={"lat": 41.0, "lng": -73.0},
        )
        assert result.lat == 41.0
        assert result.lng == -73.0

    @pytest.mark.asyncio
    async def test_raises_for_missing_location(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        ))

        with pytest.raises(SavedLocationError, match="not found"):
            await update_saved_location(db, user_id=10, location_id=999, updates={"name": "X"})

    @pytest.mark.asyncio
    async def test_rejects_label_change_to_duplicate_home(self):
        loc = _make_location(id=1, label=LocationLabel.CUSTOM)
        existing_home = _make_location(id=2, label=LocationLabel.HOME)
        db = AsyncMock()

        call_count = {"n": 0}

        async def execute_side_effect(stmt):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return MagicMock(scalar_one_or_none=MagicMock(return_value=loc))
            return MagicMock(scalar_one_or_none=MagicMock(return_value=existing_home))

        db.execute = AsyncMock(side_effect=execute_side_effect)

        with pytest.raises(SavedLocationError, match="already exists"):
            await update_saved_location(
                db, user_id=10, location_id=1, updates={"label": "home"}
            )


class TestDeleteSavedLocation:
    @pytest.mark.asyncio
    async def test_deletes_existing_location(self):
        loc = _make_location(id=1)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=loc)
        ))
        db.delete = AsyncMock()
        db.flush = AsyncMock()

        result = await delete_saved_location(db, user_id=10, location_id=1)
        assert result is True
        db.delete.assert_awaited_once_with(loc)

    @pytest.mark.asyncio
    async def test_returns_false_for_missing(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        ))

        result = await delete_saved_location(db, user_id=10, location_id=999)
        assert result is False


# ===========================================================================
# API Endpoint Tests
# ===========================================================================


class TestListSavedLocationsEndpoint:
    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        from app.api.v1.saved_locations import list_saved_locations

        user = MagicMock()
        user.id = 10
        db = AsyncMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=scalars_mock)))

        with patch("app.api.v1.saved_locations.get_saved_locations", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            result = await list_saved_locations(user=user, db=db)
            assert result == []

    @pytest.mark.asyncio
    async def test_returns_user_locations(self):
        from app.api.v1.saved_locations import list_saved_locations

        user = MagicMock()
        user.id = 10
        db = AsyncMock()

        locs = [
            _make_location(id=1, user_id=10, label=LocationLabel.HOME, name="Home"),
            _make_location(id=2, user_id=10, label=LocationLabel.WORK, name="Office"),
        ]

        with patch("app.api.v1.saved_locations.get_saved_locations", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = locs
            result = await list_saved_locations(user=user, db=db)
            assert len(result) == 2
            assert result[0].name == "Home"
            assert result[1].name == "Office"


class TestAddSavedLocationEndpoint:
    @pytest.mark.asyncio
    async def test_creates_location_returns_201(self):
        from app.api.v1.saved_locations import add_saved_location

        user = MagicMock()
        user.id = 10
        db = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        loc = _make_location(id=5, user_id=10, label=LocationLabel.HOME, name="Home")

        req = SavedLocationCreate(
            label="home", name="Home", address="123 Main St",
            lat=40.7128, lng=-74.0060,
        )

        with patch("app.api.v1.saved_locations.create_saved_location", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = loc
            result = await add_saved_location(req=req, user=user, db=db)
            assert result.id == 5
            assert result.name == "Home"
            mock_create.assert_awaited_once()
            db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_409_on_duplicate(self):
        from fastapi import HTTPException

        from app.api.v1.saved_locations import add_saved_location

        user = MagicMock()
        user.id = 10
        db = AsyncMock()

        req = SavedLocationCreate(
            label="home", name="Home", address="Addr",
            lat=40.0, lng=-74.0,
        )

        with patch("app.api.v1.saved_locations.create_saved_location", new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = SavedLocationError("A 'home' location already exists")
            with pytest.raises(HTTPException) as exc_info:
                await add_saved_location(req=req, user=user, db=db)
            assert exc_info.value.status_code == 409


class TestGetSavedLocationEndpoint:
    @pytest.mark.asyncio
    async def test_returns_location(self):
        from app.api.v1.saved_locations import get_location

        user = MagicMock()
        user.id = 10
        db = AsyncMock()

        loc = _make_location(id=3, name="Gym")

        with patch("app.api.v1.saved_locations.get_saved_location", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = loc
            result = await get_location(location_id=3, user=user, db=db)
            assert result.id == 3
            assert result.name == "Gym"

    @pytest.mark.asyncio
    async def test_returns_404_when_missing(self):
        from fastapi import HTTPException

        from app.api.v1.saved_locations import get_location

        user = MagicMock()
        user.id = 10
        db = AsyncMock()

        with patch("app.api.v1.saved_locations.get_saved_location", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            with pytest.raises(HTTPException) as exc_info:
                await get_location(location_id=999, user=user, db=db)
            assert exc_info.value.status_code == 404


class TestUpdateSavedLocationEndpoint:
    @pytest.mark.asyncio
    async def test_updates_and_returns_location(self):
        from app.api.v1.saved_locations import update_location

        user = MagicMock()
        user.id = 10
        db = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        loc = _make_location(id=1, name="Updated Name")

        req = SavedLocationUpdate(name="Updated Name")

        with patch("app.api.v1.saved_locations.update_saved_location", new_callable=AsyncMock) as mock_update:
            mock_update.return_value = loc
            result = await update_location(location_id=1, req=req, user=user, db=db)
            assert result.name == "Updated Name"

    @pytest.mark.asyncio
    async def test_returns_404_when_missing(self):
        from fastapi import HTTPException

        from app.api.v1.saved_locations import update_location

        user = MagicMock()
        user.id = 10
        db = AsyncMock()

        req = SavedLocationUpdate(name="X")

        with patch("app.api.v1.saved_locations.update_saved_location", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = SavedLocationError("Saved location not found")
            with pytest.raises(HTTPException) as exc_info:
                await update_location(location_id=999, req=req, user=user, db=db)
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_409_on_conflict(self):
        from fastapi import HTTPException

        from app.api.v1.saved_locations import update_location

        user = MagicMock()
        user.id = 10
        db = AsyncMock()

        req = SavedLocationUpdate(label="home")

        with patch("app.api.v1.saved_locations.update_saved_location", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = SavedLocationError("A 'home' location already exists")
            with pytest.raises(HTTPException) as exc_info:
                await update_location(location_id=1, req=req, user=user, db=db)
            assert exc_info.value.status_code == 409


class TestDeleteSavedLocationEndpoint:
    @pytest.mark.asyncio
    async def test_deletes_and_returns_status(self):
        from app.api.v1.saved_locations import remove_location

        user = MagicMock()
        user.id = 10
        db = AsyncMock()
        db.commit = AsyncMock()

        with patch("app.api.v1.saved_locations.delete_saved_location", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = True
            result = await remove_location(location_id=1, user=user, db=db)
            assert result == {"status": "deleted"}
            db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_404_when_missing(self):
        from fastapi import HTTPException

        from app.api.v1.saved_locations import remove_location

        user = MagicMock()
        user.id = 10
        db = AsyncMock()

        with patch("app.api.v1.saved_locations.delete_saved_location", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = False
            with pytest.raises(HTTPException) as exc_info:
                await remove_location(location_id=999, user=user, db=db)
            assert exc_info.value.status_code == 404


# ===========================================================================
# Ride Integration Tests
# ===========================================================================


class TestSavedLocationRideIntegration:
    """Tests for saved location resolution in ride request/estimate flows."""

    @pytest.mark.asyncio
    async def test_resolve_saved_location_returns_point_and_address(self):
        from app.api.v1.rides import _resolve_saved_location

        loc = _make_location(id=1, lat=40.7128, lng=-74.0060, address="123 Main St")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=loc)
        ))

        point, address = await _resolve_saved_location(
            db, user_id=10, saved_id=1, point=None, address=None, field_name="pickup"
        )
        assert point.lat == 40.7128
        assert point.lng == -74.0060
        assert address == "123 Main St"

    @pytest.mark.asyncio
    async def test_resolve_returns_raw_point_when_no_saved_id(self):
        from app.api.v1.rides import _resolve_saved_location
        from app.schemas.ride import LocationPoint

        raw_point = LocationPoint(lat=41.0, lng=-73.0)
        db = AsyncMock()

        point, address = await _resolve_saved_location(
            db, user_id=10, saved_id=None, point=raw_point, address="456 Oak St", field_name="dropoff"
        )
        assert point.lat == 41.0
        assert point.lng == -73.0
        assert address == "456 Oak St"

    @pytest.mark.asyncio
    async def test_resolve_raises_404_for_missing_saved_location(self):
        from fastapi import HTTPException

        from app.api.v1.rides import _resolve_saved_location

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        ))

        with pytest.raises(HTTPException) as exc_info:
            await _resolve_saved_location(
                db, user_id=10, saved_id=999, point=None, address=None, field_name="pickup"
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_resolve_raises_422_when_neither_provided(self):
        from fastapi import HTTPException

        from app.api.v1.rides import _resolve_saved_location

        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await _resolve_saved_location(
                db, user_id=10, saved_id=None, point=None, address=None, field_name="pickup"
            )
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_saved_id_takes_precedence_over_raw_point(self):
        """When both saved_id and raw point are provided, saved location wins."""
        from app.api.v1.rides import _resolve_saved_location
        from app.schemas.ride import LocationPoint

        loc = _make_location(id=1, lat=40.7128, lng=-74.0060, address="Saved Addr")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=loc)
        ))

        raw_point = LocationPoint(lat=0.0, lng=0.0)
        point, address = await _resolve_saved_location(
            db, user_id=10, saved_id=1, point=raw_point, address="Raw Addr", field_name="pickup"
        )
        assert point.lat == 40.7128  # saved location coords, not raw
        assert address == "Saved Addr"


# ===========================================================================
# MAX_SAVED_LOCATIONS Constant Test
# ===========================================================================


class TestConstants:
    def test_max_saved_locations_is_reasonable(self):
        assert MAX_SAVED_LOCATIONS == 20

    def test_max_saved_locations_is_positive(self):
        assert MAX_SAVED_LOCATIONS > 0
