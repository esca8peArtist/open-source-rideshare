"""Tests for GET /drivers/{driver_id}/public-profile.

Coverage:
1.  Service returns None for unknown driver_id
2.  Service returns None for unapproved driver
3.  Service returns DriverPublicProfile for approved driver
4.  Returned profile contains correct vehicle fields
5.  Returned profile contains correct rating_avg and total_trips
6.  Returned profile contains is_approved=True
7.  member_since maps to DriverProfile.created_at
8.  PII fields absent from returned schema (license_plate, license_number, insurance)
9.  Endpoint returns 404 for unknown driver
10. Endpoint returns 404 for unapproved driver
11. Endpoint returns 200 for approved driver
12. Endpoint requires no auth (no Authorization header needed)
13. Full response shape contains all expected fields
14. vehicle_type / make / model / year / color present in response
15. No PII (license_plate, user_id, etc.) in endpoint response
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.driver_public_profile import DriverPublicProfile
from app.services.driver_public_profile import get_driver_public_profile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


def _make_profile(
    driver_id: int = 42,
    vehicle_type: str = "sedan",
    vehicle_make: str = "Toyota",
    vehicle_model: str = "Camry",
    vehicle_year: int = 2022,
    vehicle_color: str = "Silver",
    rating_avg: float = 4.85,
    total_trips: int = 312,
    is_approved: bool = True,
    created_at: datetime = _NOW,
) -> MagicMock:
    """Create a mock DriverProfile ORM row."""
    p = MagicMock()
    p.id = driver_id
    p.vehicle_type = vehicle_type
    p.vehicle_make = vehicle_make
    p.vehicle_model = vehicle_model
    p.vehicle_year = vehicle_year
    p.vehicle_color = vehicle_color
    p.rating_avg = rating_avg
    p.total_trips = total_trips
    p.is_approved = is_approved
    p.created_at = created_at
    return p


def _make_db(profile: MagicMock | None) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db.execute = AsyncMock(return_value=result)
    return db


# ---------------------------------------------------------------------------
# 1. Service: unknown driver
# ---------------------------------------------------------------------------


class TestServiceUnknownDriver:
    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_driver(self):
        db = _make_db(None)
        result = await get_driver_public_profile(db, driver_id=999)
        assert result is None


# ---------------------------------------------------------------------------
# 2. Service: unapproved driver (DB query filters is_approved=True)
# ---------------------------------------------------------------------------


class TestServiceUnapprovedDriver:
    @pytest.mark.asyncio
    async def test_returns_none_for_unapproved_driver(self):
        # Service filters is_approved in the WHERE clause; the DB returns None.
        db = _make_db(None)
        result = await get_driver_public_profile(db, driver_id=10)
        assert result is None


# ---------------------------------------------------------------------------
# 3. Service: approved driver
# ---------------------------------------------------------------------------


class TestServiceApprovedDriver:
    @pytest.mark.asyncio
    async def test_returns_profile_for_approved_driver(self):
        db = _make_db(_make_profile())
        result = await get_driver_public_profile(db, driver_id=42)
        assert result is not None
        assert isinstance(result, DriverPublicProfile)

    @pytest.mark.asyncio
    async def test_vehicle_fields_correct(self):
        mock_p = _make_profile(
            vehicle_type="suv",
            vehicle_make="Honda",
            vehicle_model="CR-V",
            vehicle_year=2021,
            vehicle_color="Blue",
        )
        db = _make_db(mock_p)
        result = await get_driver_public_profile(db, driver_id=42)
        assert result.vehicle_type == "suv"
        assert result.vehicle_make == "Honda"
        assert result.vehicle_model == "CR-V"
        assert result.vehicle_year == 2021
        assert result.vehicle_color == "Blue"

    @pytest.mark.asyncio
    async def test_rating_and_trips_correct(self):
        mock_p = _make_profile(rating_avg=4.72, total_trips=850)
        db = _make_db(mock_p)
        result = await get_driver_public_profile(db, driver_id=42)
        assert result.rating_avg == 4.72
        assert result.total_trips == 850

    @pytest.mark.asyncio
    async def test_is_approved_true(self):
        db = _make_db(_make_profile(is_approved=True))
        result = await get_driver_public_profile(db, driver_id=42)
        assert result.is_approved is True

    @pytest.mark.asyncio
    async def test_member_since_maps_to_created_at(self):
        mock_p = _make_profile(created_at=_NOW)
        db = _make_db(mock_p)
        result = await get_driver_public_profile(db, driver_id=42)
        assert result.member_since == _NOW

    @pytest.mark.asyncio
    async def test_pii_fields_absent_from_schema(self):
        db = _make_db(_make_profile())
        result = await get_driver_public_profile(db, driver_id=42)
        result_dict = result.model_dump()
        for pii_field in ("license_plate", "license_number", "insurance_policy", "user_id"):
            assert pii_field not in result_dict, f"PII field present: {pii_field}"


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


class TestEndpoint404:
    def test_unknown_driver_returns_404(self):
        with patch(
            "app.api.v1.driver_public_profile.get_driver_public_profile",
            new=AsyncMock(return_value=None),
        ):
            with TestClient(app) as client:
                resp = client.get("/api/v1/drivers/999/public-profile")
        assert resp.status_code == 404

    def test_unapproved_driver_returns_404(self):
        with patch(
            "app.api.v1.driver_public_profile.get_driver_public_profile",
            new=AsyncMock(return_value=None),
        ):
            with TestClient(app) as client:
                resp = client.get("/api/v1/drivers/5/public-profile")
        assert resp.status_code == 404


class TestEndpoint200:
    def _mock_profile(self) -> DriverPublicProfile:
        return DriverPublicProfile(
            driver_id=42,
            vehicle_type="sedan",
            vehicle_make="Toyota",
            vehicle_model="Camry",
            vehicle_year=2022,
            vehicle_color="Silver",
            rating_avg=4.85,
            total_trips=312,
            is_approved=True,
            member_since=_NOW,
        )

    def test_approved_driver_returns_200(self):
        with patch(
            "app.api.v1.driver_public_profile.get_driver_public_profile",
            new=AsyncMock(return_value=self._mock_profile()),
        ):
            with TestClient(app) as client:
                resp = client.get("/api/v1/drivers/42/public-profile")
        assert resp.status_code == 200

    def test_no_auth_required(self):
        with patch(
            "app.api.v1.driver_public_profile.get_driver_public_profile",
            new=AsyncMock(return_value=self._mock_profile()),
        ):
            with TestClient(app) as client:
                # Explicitly no Authorization header
                resp = client.get("/api/v1/drivers/42/public-profile")
        assert resp.status_code == 200

    def test_response_shape_has_all_fields(self):
        with patch(
            "app.api.v1.driver_public_profile.get_driver_public_profile",
            new=AsyncMock(return_value=self._mock_profile()),
        ):
            with TestClient(app) as client:
                resp = client.get("/api/v1/drivers/42/public-profile")
        data = resp.json()
        for field in (
            "driver_id",
            "vehicle_type",
            "vehicle_make",
            "vehicle_model",
            "vehicle_year",
            "vehicle_color",
            "rating_avg",
            "total_trips",
            "is_approved",
            "member_since",
        ):
            assert field in data, f"Missing field: {field}"

    def test_response_vehicle_fields_correct(self):
        with patch(
            "app.api.v1.driver_public_profile.get_driver_public_profile",
            new=AsyncMock(return_value=self._mock_profile()),
        ):
            with TestClient(app) as client:
                resp = client.get("/api/v1/drivers/42/public-profile")
        data = resp.json()
        assert data["vehicle_make"] == "Toyota"
        assert data["vehicle_model"] == "Camry"
        assert data["vehicle_year"] == 2022
        assert data["vehicle_color"] == "Silver"

    def test_no_pii_in_response(self):
        with patch(
            "app.api.v1.driver_public_profile.get_driver_public_profile",
            new=AsyncMock(return_value=self._mock_profile()),
        ):
            with TestClient(app) as client:
                resp = client.get("/api/v1/drivers/42/public-profile")
        data = resp.json()
        for pii_field in (
            "license_plate",
            "license_number",
            "insurance_policy",
            "user_id",
            "is_online",
            "current_location",
        ):
            assert pii_field not in data, f"PII field present in response: {pii_field}"
