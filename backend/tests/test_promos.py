"""Tests for promo code and referral system."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.models.promo import PromoCode, PromoRedemption, PromoType, generate_referral_code
from app.models.ride import Ride, RideStatus
from app.models.user import User
from app.services.promos import (
    _calculate_discount,
    create_referral_promo,
    get_referral_promo_for_user,
    redeem_promo,
    validate_promo,
)

from tests.conftest import auth_header


# --- Model / helper tests ---


class TestGenerateReferralCode:
    def test_generates_8_char_uppercase(self):
        code = generate_referral_code()
        assert len(code) == 8
        assert code == code.upper()

    def test_generates_unique_codes(self):
        codes = {generate_referral_code() for _ in range(100)}
        assert len(codes) >= 95  # Probabilistically unique


# --- Service tests ---


class TestCalculateDiscount:
    def test_flat_discount(self):
        promo = PromoCode(
            id=1, code="FLAT5", promo_type=PromoType.FLAT, value=5.0,
            max_discount=None, minimum_fare=0, max_uses=None, max_uses_per_user=1,
            total_uses=0, is_active=True, first_ride_only=False, is_referral=False,
        )
        assert _calculate_discount(promo, 20.0) == 5.0

    def test_flat_discount_capped_at_fare(self):
        promo = PromoCode(
            id=1, code="FLAT50", promo_type=PromoType.FLAT, value=50.0,
            max_discount=None, minimum_fare=0, max_uses=None, max_uses_per_user=1,
            total_uses=0, is_active=True, first_ride_only=False, is_referral=False,
        )
        assert _calculate_discount(promo, 20.0) == 20.0

    def test_percent_discount(self):
        promo = PromoCode(
            id=1, code="PCT20", promo_type=PromoType.PERCENT, value=20.0,
            max_discount=None, minimum_fare=0, max_uses=None, max_uses_per_user=1,
            total_uses=0, is_active=True, first_ride_only=False, is_referral=False,
        )
        assert _calculate_discount(promo, 25.0) == 5.0  # 20% of 25

    def test_percent_discount_with_max(self):
        promo = PromoCode(
            id=1, code="PCT50", promo_type=PromoType.PERCENT, value=50.0,
            max_discount=10.0, minimum_fare=0, max_uses=None, max_uses_per_user=1,
            total_uses=0, is_active=True, first_ride_only=False, is_referral=False,
        )
        assert _calculate_discount(promo, 100.0) == 10.0  # 50% = 50, capped at 10


@pytest.mark.anyio
class TestValidatePromo:
    async def test_invalid_code(self, db):
        result = await validate_promo("NONEXISTENT", user_id=1, fare=20.0, db=db)
        assert not result.valid
        assert "Invalid" in result.reason

    async def test_inactive_code(self, db):
        promo = PromoCode(
            code="INACTIVE", promo_type=PromoType.FLAT, value=5.0,
            is_active=False, max_uses_per_user=1, total_uses=0,
            first_ride_only=False, is_referral=False,
        )
        db.add(promo)
        await db.flush()

        result = await validate_promo("INACTIVE", user_id=1, fare=20.0, db=db)
        assert not result.valid
        assert "no longer active" in result.reason

    async def test_expired_code(self, db):
        promo = PromoCode(
            code="EXPIRED", promo_type=PromoType.FLAT, value=5.0,
            is_active=True, max_uses_per_user=1, total_uses=0,
            first_ride_only=False, is_referral=False,
            expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        db.add(promo)
        await db.flush()

        result = await validate_promo("EXPIRED", user_id=1, fare=20.0, db=db)
        assert not result.valid
        assert "expired" in result.reason

    async def test_max_uses_reached(self, db):
        promo = PromoCode(
            code="MAXED", promo_type=PromoType.FLAT, value=5.0,
            is_active=True, max_uses=2, max_uses_per_user=10, total_uses=2,
            first_ride_only=False, is_referral=False,
        )
        db.add(promo)
        await db.flush()

        result = await validate_promo("MAXED", user_id=1, fare=20.0, db=db)
        assert not result.valid
        assert "usage limit" in result.reason

    async def test_per_user_limit(self, db, rider):
        promo = PromoCode(
            code="ONCE", promo_type=PromoType.FLAT, value=5.0,
            is_active=True, max_uses_per_user=1, total_uses=0,
            first_ride_only=False, is_referral=False,
        )
        db.add(promo)
        await db.flush()

        # Add a previous redemption
        redemption = PromoRedemption(
            promo_code_id=promo.id, user_id=rider.id,
            ride_id=None, discount_amount=5.0,
        )
        db.add(redemption)
        await db.flush()

        result = await validate_promo("ONCE", user_id=rider.id, fare=20.0, db=db)
        assert not result.valid
        assert "already used" in result.reason

    async def test_minimum_fare_not_met(self, db):
        promo = PromoCode(
            code="MIN15", promo_type=PromoType.FLAT, value=5.0,
            is_active=True, max_uses_per_user=1, total_uses=0,
            minimum_fare=15.0, first_ride_only=False, is_referral=False,
        )
        db.add(promo)
        await db.flush()

        result = await validate_promo("MIN15", user_id=1, fare=10.0, db=db)
        assert not result.valid
        assert "Minimum fare" in result.reason

    async def test_first_ride_only_with_completed_rides(self, db, rider):
        promo = PromoCode(
            code="FIRST", promo_type=PromoType.FLAT, value=5.0,
            is_active=True, max_uses_per_user=1, total_uses=0,
            first_ride_only=True, is_referral=False,
        )
        db.add(promo)

        # Add a completed ride for this rider
        from geoalchemy2.functions import ST_MakePoint
        ride = Ride(
            rider_id=rider.id, status=RideStatus.COMPLETED,
            pickup_location=ST_MakePoint(-73.9857, 40.7484, 4326),
            dropoff_location=ST_MakePoint(-73.9712, 40.7831, 4326),
            pickup_address="A", dropoff_address="B",
            estimated_fare=20.0, actual_fare=20.0,
        )
        db.add(ride)
        await db.flush()

        result = await validate_promo("FIRST", user_id=rider.id, fare=20.0, db=db)
        assert not result.valid
        assert "first rides only" in result.reason

    async def test_valid_flat_code(self, db):
        promo = PromoCode(
            code="VALID5", promo_type=PromoType.FLAT, value=5.0,
            is_active=True, max_uses_per_user=1, total_uses=0,
            first_ride_only=False, is_referral=False,
        )
        db.add(promo)
        await db.flush()

        result = await validate_promo("VALID5", user_id=999, fare=20.0, db=db)
        assert result.valid
        assert result.discount == 5.0
        assert result.promo_code_id == promo.id

    async def test_valid_percent_code(self, db):
        promo = PromoCode(
            code="PCT25", promo_type=PromoType.PERCENT, value=25.0,
            is_active=True, max_uses_per_user=1, total_uses=0,
            first_ride_only=False, is_referral=False,
        )
        db.add(promo)
        await db.flush()

        result = await validate_promo("PCT25", user_id=999, fare=20.0, db=db)
        assert result.valid
        assert result.discount == 5.0  # 25% of 20

    async def test_code_case_insensitive(self, db):
        promo = PromoCode(
            code="CASETEST", promo_type=PromoType.FLAT, value=3.0,
            is_active=True, max_uses_per_user=1, total_uses=0,
            first_ride_only=False, is_referral=False,
        )
        db.add(promo)
        await db.flush()

        result = await validate_promo("casetest", user_id=999, fare=20.0, db=db)
        assert result.valid


@pytest.mark.anyio
class TestRedeemPromo:
    async def test_redeem_increments_usage(self, db):
        promo = PromoCode(
            code="REDEEM1", promo_type=PromoType.FLAT, value=5.0,
            is_active=True, max_uses_per_user=1, total_uses=0,
            first_ride_only=False, is_referral=False,
        )
        db.add(promo)
        await db.flush()

        redemption = await redeem_promo(promo.id, user_id=1, ride_id=1, discount_amount=5.0, db=db)
        assert redemption.discount_amount == 5.0
        assert promo.total_uses == 1


@pytest.mark.anyio
class TestReferralPromo:
    async def test_create_and_retrieve_referral(self, db):
        promo = await create_referral_promo(42, "TESTREF1", db)
        assert promo.code == "TESTREF1"
        assert promo.is_referral
        assert promo.first_ride_only
        assert promo.value == 5.0

        found = await get_referral_promo_for_user(42, db)
        assert found is not None
        assert found.code == "TESTREF1"

    async def test_no_referral_found(self, db):
        found = await get_referral_promo_for_user(9999, db)
        assert found is None


# --- API endpoint tests ---


@pytest.mark.anyio
class TestPromoAdminEndpoints:
    async def test_create_promo_code(self, client: AsyncClient, admin_token):
        resp = await client.post(
            "/api/v1/promos/admin",
            json={
                "code": "LAUNCH10",
                "description": "Launch promo",
                "promo_type": "flat",
                "value": 10.0,
                "max_uses": 100,
                "max_uses_per_user": 1,
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["code"] == "LAUNCH10"
        assert data["promo_type"] == "flat"
        assert data["value"] == 10.0
        assert data["is_active"] is True

    async def test_create_duplicate_code_fails(self, client: AsyncClient, admin_token):
        await client.post(
            "/api/v1/promos/admin",
            json={"code": "DUP1", "promo_type": "flat", "value": 5.0},
            headers=auth_header(admin_token),
        )
        resp = await client.post(
            "/api/v1/promos/admin",
            json={"code": "DUP1", "promo_type": "flat", "value": 5.0},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 409

    async def test_list_promo_codes(self, client: AsyncClient, admin_token):
        # Create a couple
        await client.post(
            "/api/v1/promos/admin",
            json={"code": "LIST1", "promo_type": "flat", "value": 5.0},
            headers=auth_header(admin_token),
        )
        await client.post(
            "/api/v1/promos/admin",
            json={"code": "LIST2", "promo_type": "percent", "value": 20.0},
            headers=auth_header(admin_token),
        )

        resp = await client.get("/api/v1/promos/admin", headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        codes = {p["code"] for p in data}
        assert "LIST1" in codes
        assert "LIST2" in codes

    async def test_get_promo_code_by_id(self, client: AsyncClient, admin_token):
        create_resp = await client.post(
            "/api/v1/promos/admin",
            json={"code": "GETME", "promo_type": "flat", "value": 7.0},
            headers=auth_header(admin_token),
        )
        promo_id = create_resp.json()["id"]

        resp = await client.get(
            f"/api/v1/promos/admin/{promo_id}", headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == "GETME"

    async def test_get_nonexistent_promo_returns_404(self, client: AsyncClient, admin_token):
        resp = await client.get("/api/v1/promos/admin/99999", headers=auth_header(admin_token))
        assert resp.status_code == 404

    async def test_update_promo_code(self, client: AsyncClient, admin_token):
        create_resp = await client.post(
            "/api/v1/promos/admin",
            json={"code": "UPDME", "promo_type": "flat", "value": 5.0},
            headers=auth_header(admin_token),
        )
        promo_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/promos/admin/{promo_id}",
            json={"description": "Updated!", "is_active": False},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "Updated!"
        assert data["is_active"] is False

    async def test_deactivate_promo_code(self, client: AsyncClient, admin_token):
        create_resp = await client.post(
            "/api/v1/promos/admin",
            json={"code": "DEACT", "promo_type": "flat", "value": 5.0},
            headers=auth_header(admin_token),
        )
        promo_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/api/v1/promos/admin/{promo_id}", headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deactivated"

    async def test_non_admin_cannot_create(self, client: AsyncClient, rider_token):
        resp = await client.post(
            "/api/v1/promos/admin",
            json={"code": "NOPE", "promo_type": "flat", "value": 5.0},
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_list_redemptions(self, client: AsyncClient, admin_token, db, rider):
        # Create a promo and a redemption
        promo = PromoCode(
            code="REDEMPT", promo_type=PromoType.FLAT, value=5.0,
            is_active=True, max_uses_per_user=1, total_uses=1,
            first_ride_only=False, is_referral=False,
        )
        db.add(promo)
        await db.flush()

        redemption = PromoRedemption(
            promo_code_id=promo.id, user_id=rider.id,
            ride_id=None, discount_amount=5.0,
        )
        db.add(redemption)
        await db.flush()

        resp = await client.get(
            f"/api/v1/promos/admin/{promo.id}/redemptions",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["discount_amount"] == 5.0


@pytest.mark.anyio
class TestPromoValidateEndpoint:
    async def test_validate_valid_code(self, client: AsyncClient, rider_token, db):
        promo = PromoCode(
            code="APITEST", promo_type=PromoType.FLAT, value=3.0,
            is_active=True, max_uses_per_user=1, total_uses=0,
            first_ride_only=False, is_referral=False,
        )
        db.add(promo)
        await db.flush()

        resp = await client.post(
            "/api/v1/promos/validate",
            json={"code": "APITEST"},
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["code"] == "APITEST"
        assert data["promo_type"] == "flat"

    async def test_validate_invalid_code(self, client: AsyncClient, rider_token):
        resp = await client.post(
            "/api/v1/promos/validate",
            json={"code": "DOESNTEXIST"},
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False


@pytest.mark.anyio
class TestReferralEndpoint:
    async def test_no_referral_code(self, client: AsyncClient, rider_token):
        resp = await client.get(
            "/api/v1/promos/my-referral",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_referral_code"] is False

    async def test_has_referral_code(self, client: AsyncClient, rider_token, db, rider):
        await create_referral_promo(rider.id, "MYREF123", db)
        await db.flush()

        resp = await client.get(
            "/api/v1/promos/my-referral",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_referral_code"] is True
        assert data["referral_code"] == "MYREF123"


@pytest.mark.anyio
class TestRideRequestWithPromo:
    async def test_ride_request_with_valid_promo(self, client: AsyncClient, rider_token, db):
        promo = PromoCode(
            code="RIDE5", promo_type=PromoType.FLAT, value=5.0,
            is_active=True, max_uses_per_user=1, total_uses=0,
            first_ride_only=False, is_referral=False,
        )
        db.add(promo)
        await db.flush()

        with patch("app.api.v1.rides.get_route", new_callable=AsyncMock) as mock_route:
            mock_route.return_value = {"distance_km": 10.0, "duration_min": 15.0}

            resp = await client.post(
                "/api/v1/rides/request",
                json={
                    "pickup": {"lat": 40.7484, "lng": -73.9857},
                    "dropoff": {"lat": 40.7831, "lng": -73.9712},
                    "pickup_address": "Penn Station",
                    "dropoff_address": "Central Park",
                    "promo_code": "RIDE5",
                },
                headers=auth_header(rider_token),
            )
        assert resp.status_code == 201
        data = resp.json()
        # Fare should have $5 discount applied
        # Base fare calculation: 2.50 + (10 * 1.50) + (15 * 0.25) = 2.50 + 15 + 3.75 = 21.25
        # With promo: 21.25 - 5.00 = 16.25
        assert data["estimated_fare"] == 16.25

    async def test_ride_request_with_invalid_promo_uses_full_fare(self, client: AsyncClient, rider_token):
        with patch("app.api.v1.rides.get_route", new_callable=AsyncMock) as mock_route:
            mock_route.return_value = {"distance_km": 10.0, "duration_min": 15.0}

            resp = await client.post(
                "/api/v1/rides/request",
                json={
                    "pickup": {"lat": 40.7484, "lng": -73.9857},
                    "dropoff": {"lat": 40.7831, "lng": -73.9712},
                    "pickup_address": "Penn Station",
                    "dropoff_address": "Central Park",
                    "promo_code": "INVALID",
                },
                headers=auth_header(rider_token),
            )
        assert resp.status_code == 201
        data = resp.json()
        # Full fare with no discount
        assert data["estimated_fare"] == 21.25

    async def test_ride_request_without_promo(self, client: AsyncClient, rider_token):
        with patch("app.api.v1.rides.get_route", new_callable=AsyncMock) as mock_route:
            mock_route.return_value = {"distance_km": 10.0, "duration_min": 15.0}

            resp = await client.post(
                "/api/v1/rides/request",
                json={
                    "pickup": {"lat": 40.7484, "lng": -73.9857},
                    "dropoff": {"lat": 40.7831, "lng": -73.9712},
                    "pickup_address": "Penn Station",
                    "dropoff_address": "Central Park",
                },
                headers=auth_header(rider_token),
            )
        assert resp.status_code == 201
        assert resp.json()["estimated_fare"] == 21.25


@pytest.mark.anyio
class TestFareEstimateWithPromo:
    async def test_estimate_with_valid_promo(self, client: AsyncClient, rider_token, db):
        promo = PromoCode(
            code="EST10", promo_type=PromoType.PERCENT, value=10.0,
            is_active=True, max_uses_per_user=1, total_uses=0,
            first_ride_only=False, is_referral=False,
        )
        db.add(promo)
        await db.flush()

        with patch("app.api.v1.rides.get_route", new_callable=AsyncMock) as mock_route:
            mock_route.return_value = {"distance_km": 10.0, "duration_min": 15.0}

            resp = await client.post(
                "/api/v1/rides/estimate",
                json={
                    "pickup": {"lat": 40.7484, "lng": -73.9857},
                    "dropoff": {"lat": 40.7831, "lng": -73.9712},
                    "promo_code": "EST10",
                },
                headers=auth_header(rider_token),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["estimated_fare"] == 21.25  # Pre-discount fare
        assert data["promo_discount"] == 2.12   # 10% of 21.25 = 2.125 → 2.12
        assert data["promo_code"] == "EST10"
        assert data["final_fare"] == 19.13      # 21.25 - 2.12

    async def test_estimate_without_promo(self, client: AsyncClient, rider_token):
        with patch("app.api.v1.rides.get_route", new_callable=AsyncMock) as mock_route:
            mock_route.return_value = {"distance_km": 10.0, "duration_min": 15.0}

            resp = await client.post(
                "/api/v1/rides/estimate",
                json={
                    "pickup": {"lat": 40.7484, "lng": -73.9857},
                    "dropoff": {"lat": 40.7831, "lng": -73.9712},
                },
                headers=auth_header(rider_token),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["promo_discount"] == 0.0
        assert data["promo_code"] is None


@pytest.mark.anyio
class TestRegistrationWithReferral:
    async def test_register_generates_referral_code(self, client: AsyncClient, db):
        with patch("app.api.v1.auth.create_referral_promo", new_callable=AsyncMock):
            resp = await client.post(
                "/api/v1/auth/register",
                json={
                    "phone": "+15559990001",
                    "name": "New User",
                    "password": "securepass",
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
