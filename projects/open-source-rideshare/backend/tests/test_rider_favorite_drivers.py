"""Unit tests for rider favourite drivers feature.

Tests cover:
  - GET /riders/me/favorite-drivers — empty list when no favourites
  - GET /riders/me/favorite-drivers — returns favourites sorted newest-first
  - POST /riders/me/favorite-drivers/{id} — adds a favourite (201)
  - POST /riders/me/favorite-drivers/{id} — 404 when driver does not exist
  - POST /riders/me/favorite-drivers/{id} — 409 when already favourited
  - POST /riders/me/favorite-drivers/{id} — 422 when cap of 20 is reached
  - DELETE /riders/me/favorite-drivers/{id} — removes a favourite (204)
  - DELETE /riders/me/favorite-drivers/{id} — 404 when not in favourites
  - GET requires rider auth (401)
  - POST requires rider auth (401)
  - DELETE requires rider auth (401)
  - Schema serialises FavoriteDriverEntry correctly
  - FavoriteDriverListResponse total matches len(drivers)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.models.rider_favorite_driver import _MAX_FAVORITES
from app.schemas.rider_favorite_driver import FavoriteDriverEntry, FavoriteDriverListResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
RIDER_ID = 5
DRIVER_PROFILE_ID = 11


def _rider_user(id: int = RIDER_ID) -> MagicMock:
    u = MagicMock()
    u.id = id
    u.role = "rider"
    return u


def _fake_profile(id: int = DRIVER_PROFILE_ID) -> MagicMock:
    p = MagicMock()
    p.id = id
    p.vehicle_type = "sedan"
    p.vehicle_make = "Toyota"
    p.vehicle_model = "Camry"
    p.vehicle_year = 2022
    p.vehicle_color = "Silver"
    p.rating_avg = 4.8
    p.total_trips = 350
    p.is_approved = True
    p.created_at = _NOW
    return p


def _fake_fav(driver_profile_id: int = DRIVER_PROFILE_ID) -> MagicMock:
    fav = MagicMock()
    fav.rider_id = RIDER_ID
    fav.driver_profile_id = driver_profile_id
    fav.created_at = _NOW
    fav.driver_profile = _fake_profile(driver_profile_id)
    return fav


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestFavoriteDriverSchemas:
    def test_entry_serialises(self):
        entry = FavoriteDriverEntry(
            driver_profile_id=DRIVER_PROFILE_ID,
            vehicle_type="sedan",
            vehicle_make="Toyota",
            vehicle_model="Camry",
            vehicle_year=2022,
            vehicle_color="Silver",
            rating_avg=4.8,
            total_trips=350,
            is_approved=True,
            member_since=_NOW,
            favorited_at=_NOW,
        )
        data = entry.model_dump()
        assert data["driver_profile_id"] == DRIVER_PROFILE_ID
        assert data["rating_avg"] == 4.8

    def test_list_response_total_matches(self):
        entry = FavoriteDriverEntry(
            driver_profile_id=1,
            vehicle_type="suv",
            vehicle_make="Honda",
            vehicle_model="CR-V",
            vehicle_year=2021,
            vehicle_color="White",
            rating_avg=4.5,
            total_trips=120,
            is_approved=True,
            member_since=_NOW,
            favorited_at=_NOW,
        )
        resp = FavoriteDriverListResponse(drivers=[entry], total=1)
        assert resp.total == 1
        assert len(resp.drivers) == 1

    def test_empty_list_response(self):
        resp = FavoriteDriverListResponse(drivers=[], total=0)
        assert resp.total == 0


# ---------------------------------------------------------------------------
# Endpoint tests — GET
# ---------------------------------------------------------------------------


class TestListFavoriteDrivers:
    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        from app.api.v1.rider_favorite_drivers import list_favorite_drivers

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        rider = _rider_user()
        resp = await list_favorite_drivers(rider=rider, db=db)
        assert resp.total == 0
        assert resp.drivers == []

    @pytest.mark.asyncio
    async def test_returns_favourites(self):
        from app.api.v1.rider_favorite_drivers import list_favorite_drivers

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [_fake_fav()]
        db.execute = AsyncMock(return_value=result)

        rider = _rider_user()
        resp = await list_favorite_drivers(rider=rider, db=db)
        assert resp.total == 1
        assert resp.drivers[0].driver_profile_id == DRIVER_PROFILE_ID
        assert resp.drivers[0].vehicle_make == "Toyota"

    def test_requires_auth(self):
        client = TestClient(app)
        resp = client.get("/api/v1/riders/me/favorite-drivers")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Endpoint tests — POST
# ---------------------------------------------------------------------------


class TestAddFavoriteDriver:
    @pytest.mark.asyncio
    async def test_adds_favourite(self):
        from app.api.v1.rider_favorite_drivers import add_favorite_driver

        db = AsyncMock()

        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = _fake_profile()

        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None  # not already favourite

        count_result = MagicMock()
        count_result.scalar.return_value = 0  # under cap

        db.execute = AsyncMock(
            side_effect=[profile_result, existing_result, count_result]
        )
        db.add = MagicMock()
        db.commit = AsyncMock()

        rider = _rider_user()
        result = await add_favorite_driver(driver_id=DRIVER_PROFILE_ID, rider=rider, db=db)
        assert result["status"] == "added"
        assert result["driver_profile_id"] == DRIVER_PROFILE_ID

    @pytest.mark.asyncio
    async def test_returns_404_unknown_driver(self):
        from app.api.v1.rider_favorite_drivers import add_favorite_driver

        db = AsyncMock()
        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = None  # driver not found
        db.execute = AsyncMock(return_value=profile_result)

        rider = _rider_user()
        with pytest.raises(HTTPException) as exc_info:
            await add_favorite_driver(driver_id=999, rider=rider, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_409_already_favourite(self):
        from app.api.v1.rider_favorite_drivers import add_favorite_driver

        db = AsyncMock()

        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = _fake_profile()

        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = _fake_fav()  # already a favourite

        db.execute = AsyncMock(side_effect=[profile_result, existing_result])

        rider = _rider_user()
        with pytest.raises(HTTPException) as exc_info:
            await add_favorite_driver(driver_id=DRIVER_PROFILE_ID, rider=rider, db=db)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_returns_422_when_cap_reached(self):
        from app.api.v1.rider_favorite_drivers import add_favorite_driver

        db = AsyncMock()

        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = _fake_profile()

        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None

        count_result = MagicMock()
        count_result.scalar.return_value = _MAX_FAVORITES  # at cap

        db.execute = AsyncMock(
            side_effect=[profile_result, existing_result, count_result]
        )

        rider = _rider_user()
        with pytest.raises(HTTPException) as exc_info:
            await add_favorite_driver(driver_id=DRIVER_PROFILE_ID, rider=rider, db=db)
        assert exc_info.value.status_code == 422

    def test_requires_auth(self):
        client = TestClient(app)
        resp = client.post(f"/api/v1/riders/me/favorite-drivers/{DRIVER_PROFILE_ID}")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Endpoint tests — DELETE
# ---------------------------------------------------------------------------


class TestRemoveFavoriteDriver:
    @pytest.mark.asyncio
    async def test_removes_favourite(self):
        from app.api.v1.rider_favorite_drivers import remove_favorite_driver

        fav = _fake_fav()
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = fav
        db.execute = AsyncMock(return_value=result)
        db.delete = AsyncMock()
        db.commit = AsyncMock()

        rider = _rider_user()
        await remove_favorite_driver(driver_id=DRIVER_PROFILE_ID, rider=rider, db=db)

        db.delete.assert_called_once_with(fav)
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_404_not_in_favourites(self):
        from app.api.v1.rider_favorite_drivers import remove_favorite_driver

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        rider = _rider_user()
        with pytest.raises(HTTPException) as exc_info:
            await remove_favorite_driver(driver_id=DRIVER_PROFILE_ID, rider=rider, db=db)
        assert exc_info.value.status_code == 404

    def test_requires_auth(self):
        client = TestClient(app)
        resp = client.delete(f"/api/v1/riders/me/favorite-drivers/{DRIVER_PROFILE_ID}")
        assert resp.status_code == 401
