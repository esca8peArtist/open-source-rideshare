"""Tests for trip share links.

POST   /api/v1/riders/me/rides/{ride_id}/share-link
GET    /api/v1/riders/me/rides/{ride_id}/share-link
DELETE /api/v1/riders/me/rides/{ride_id}/share-link
GET    /api/v1/trip-share/{token}

Coverage
--------
Schemas: TripShareLinkResponse, TripShareView
  - all required fields present
  - share_url follows expected pattern

Service: create_trip_share_link
  - creates a new record with uuid4 token
  - token is unique per call
  - expires_at is ~24 h from now
  - auto-revokes existing active link for same rider+ride
  - multiple riders are independent (no cross-rider revocation)

Service: get_active_link_for_ride
  - returns active link when one exists
  - returns None when no link exists
  - returns None when link is expired
  - returns None when link is revoked

Service: revoke_trip_share_link
  - sets is_active=False on active link
  - raises LookupError when no active link exists

Service: get_trip_share_view
  - returns view dict with all expected fields for valid token
  - raises LookupError for unknown token
  - raises ValueError("expired") when link is expired
  - raises ValueError("expired") when link is revoked

Router: POST /riders/me/rides/{ride_id}/share-link
  - 201 with TripShareLinkResponse
  - share_url contains token
  - second POST auto-revokes first and returns new token

Router: GET /riders/me/rides/{ride_id}/share-link
  - 200 when active link exists
  - 404 when no active link

Router: DELETE /riders/me/rides/{ride_id}/share-link
  - 204 on success
  - 404 when no active link

Router: GET /api/v1/trip-share/{token}
  - 200 with TripShareView for valid token
  - 404 for unknown token
  - 410 for expired token
  - 410 for revoked token

Store: _reset_store
  - clears all links and resets id counter
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.schemas.trip_share import AdminTripShareEntry, AdminTripShareListResponse, TripShareLinkResponse, TripShareView
from app.services.trip_share import (
    _links,
    _reset_store,
    admin_revoke_by_token,
    create_trip_share_link,
    get_active_link_for_ride,
    get_link_by_token,
    get_trip_share_view,
    list_trip_share_links,
    revoke_trip_share_link,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_id: int = 1, role: str = "rider") -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.role = MagicMock()
    user.role.value = role
    user.is_active = True
    return user


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_store():
    _reset_store()
    yield
    _reset_store()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestTripShareSchemas:
    def test_link_response_has_required_fields(self):
        now = datetime.now(tz=timezone.utc)
        obj = TripShareLinkResponse(
            token="abc-token",
            share_url="/api/v1/trip-share/abc-token",
            expires_at=now + timedelta(hours=24),
            is_active=True,
            created_at=now,
        )
        assert obj.token == "abc-token"
        assert obj.share_url == "/api/v1/trip-share/abc-token"
        assert obj.is_active is True

    def test_trip_share_view_has_required_fields(self):
        now = datetime.now(tz=timezone.utc)
        obj = TripShareView(
            token="tok",
            ride_id=1,
            status="IN_PROGRESS",
            driver_first_name="Alex",
            vehicle_make="Toyota",
            vehicle_model="Camry",
            vehicle_color="Silver",
            vehicle_plate="XYZ123",
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            driver_lat=37.7749,
            driver_lng=-122.4194,
            eta_minutes=8,
            expires_at=now + timedelta(hours=24),
        )
        assert obj.driver_first_name == "Alex"
        assert obj.vehicle_make == "Toyota"
        assert obj.eta_minutes == 8

    def test_trip_share_view_nullable_fields(self):
        now = datetime.now(tz=timezone.utc)
        obj = TripShareView(
            token="tok",
            ride_id=1,
            status="IN_PROGRESS",
            driver_first_name="Alex",
            vehicle_make="Toyota",
            vehicle_model="Camry",
            vehicle_color="Silver",
            vehicle_plate="XYZ123",
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            driver_lat=None,
            driver_lng=None,
            eta_minutes=None,
            expires_at=now,
        )
        assert obj.driver_lat is None
        assert obj.eta_minutes is None


# ---------------------------------------------------------------------------
# Service: create_trip_share_link
# ---------------------------------------------------------------------------


class TestCreateTripShareLink:
    def test_creates_record(self):
        record = create_trip_share_link(rider_id=1, ride_id=10)
        assert record["rider_id"] == 1
        assert record["ride_id"] == 10
        assert record["is_active"] is True

    def test_token_is_uuid_string(self):
        import uuid
        record = create_trip_share_link(rider_id=1, ride_id=10)
        # Should not raise
        uuid.UUID(record["token"])

    def test_share_url_contains_token(self):
        record = create_trip_share_link(rider_id=1, ride_id=10)
        assert record["token"] in record["share_url"]
        assert record["share_url"].startswith("/api/v1/trip-share/")

    def test_expires_in_approximately_24_hours(self):
        now = datetime.now(tz=timezone.utc)
        record = create_trip_share_link(rider_id=1, ride_id=10)
        delta = record["expires_at"] - now
        assert timedelta(hours=23, minutes=59) < delta <= timedelta(hours=24, seconds=5)

    def test_tokens_are_unique_across_calls(self):
        r1 = create_trip_share_link(rider_id=1, ride_id=10)
        r2 = create_trip_share_link(rider_id=1, ride_id=11)
        assert r1["token"] != r2["token"]

    def test_auto_revokes_existing_active_link(self):
        r1 = create_trip_share_link(rider_id=1, ride_id=10)
        r2 = create_trip_share_link(rider_id=1, ride_id=10)
        # Original link should be revoked
        old = _links[r1["id"]]
        assert old["is_active"] is False
        # New link should be active
        assert r2["is_active"] is True

    def test_multiple_riders_are_independent(self):
        r1 = create_trip_share_link(rider_id=1, ride_id=10)
        r2 = create_trip_share_link(rider_id=2, ride_id=10)
        # Rider 1's link should not be revoked by rider 2
        assert _links[r1["id"]]["is_active"] is True
        assert _links[r2["id"]]["is_active"] is True

    def test_id_increments(self):
        r1 = create_trip_share_link(rider_id=1, ride_id=10)
        r2 = create_trip_share_link(rider_id=1, ride_id=11)
        assert r2["id"] == r1["id"] + 1


# ---------------------------------------------------------------------------
# Service: get_active_link_for_ride
# ---------------------------------------------------------------------------


class TestGetActiveLinkForRide:
    def test_returns_active_link(self):
        create_trip_share_link(rider_id=1, ride_id=10)
        result = get_active_link_for_ride(rider_id=1, ride_id=10)
        assert result is not None
        assert result["rider_id"] == 1

    def test_returns_none_when_no_link(self):
        result = get_active_link_for_ride(rider_id=1, ride_id=99)
        assert result is None

    def test_returns_none_when_revoked(self):
        create_trip_share_link(rider_id=1, ride_id=10)
        revoke_trip_share_link(rider_id=1, ride_id=10)
        result = get_active_link_for_ride(rider_id=1, ride_id=10)
        assert result is None

    def test_returns_none_when_expired(self):
        create_trip_share_link(rider_id=1, ride_id=10)
        # Manually expire the link
        for record in _links.values():
            record["expires_at"] = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
        result = get_active_link_for_ride(rider_id=1, ride_id=10)
        assert result is None

    def test_does_not_return_other_riders_link(self):
        create_trip_share_link(rider_id=2, ride_id=10)
        result = get_active_link_for_ride(rider_id=1, ride_id=10)
        assert result is None


# ---------------------------------------------------------------------------
# Service: revoke_trip_share_link
# ---------------------------------------------------------------------------


class TestRevokeTripShareLink:
    def test_sets_is_active_false(self):
        create_trip_share_link(rider_id=1, ride_id=10)
        revoke_trip_share_link(rider_id=1, ride_id=10)
        for record in _links.values():
            assert record["is_active"] is False

    def test_raises_lookup_error_when_no_active_link(self):
        with pytest.raises(LookupError):
            revoke_trip_share_link(rider_id=1, ride_id=10)

    def test_raises_lookup_error_after_already_revoked(self):
        create_trip_share_link(rider_id=1, ride_id=10)
        revoke_trip_share_link(rider_id=1, ride_id=10)
        with pytest.raises(LookupError):
            revoke_trip_share_link(rider_id=1, ride_id=10)


# ---------------------------------------------------------------------------
# Service: get_trip_share_view
# ---------------------------------------------------------------------------


class TestGetTripShareView:
    def test_returns_view_for_valid_token(self):
        record = create_trip_share_link(rider_id=1, ride_id=10)
        view = get_trip_share_view(record["token"])
        assert view["token"] == record["token"]
        assert view["ride_id"] == 10
        assert view["status"] == "IN_PROGRESS"
        assert view["driver_first_name"] == "Alex"
        assert view["vehicle_make"] == "Toyota"
        assert view["vehicle_model"] == "Camry"
        assert view["vehicle_color"] == "Silver"
        assert view["vehicle_plate"] == "XYZ123"
        assert view["pickup_address"] == "123 Main St"
        assert view["dropoff_address"] == "456 Oak Ave"
        assert view["driver_lat"] == 37.7749
        assert view["driver_lng"] == -122.4194
        assert view["eta_minutes"] == 8

    def test_raises_lookup_error_for_unknown_token(self):
        with pytest.raises(LookupError):
            get_trip_share_view("nonexistent-token")

    def test_raises_value_error_when_expired(self):
        record = create_trip_share_link(rider_id=1, ride_id=10)
        # Expire the link
        for r in _links.values():
            r["expires_at"] = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
        with pytest.raises(ValueError, match="expired"):
            get_trip_share_view(record["token"])

    def test_raises_value_error_when_revoked(self):
        record = create_trip_share_link(rider_id=1, ride_id=10)
        revoke_trip_share_link(rider_id=1, ride_id=10)
        with pytest.raises(ValueError, match="expired"):
            get_trip_share_view(record["token"])

    def test_view_contains_expires_at(self):
        record = create_trip_share_link(rider_id=1, ride_id=10)
        view = get_trip_share_view(record["token"])
        assert "expires_at" in view


# ---------------------------------------------------------------------------
# Router tests (via TestClient)
# ---------------------------------------------------------------------------


@pytest.fixture()
def rider_user():
    return _make_user(user_id=10, role="rider")


@pytest.fixture()
def client(rider_user):
    from unittest.mock import AsyncMock, MagicMock
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import require_rider, get_current_user
    from app.db.database import get_db

    async def mock_db():
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock())
        yield db

    app.dependency_overrides[require_rider] = lambda: rider_user
    app.dependency_overrides[get_current_user] = lambda: rider_user
    app.dependency_overrides[get_db] = mock_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestTripShareRouter:
    def test_post_creates_share_link_201(self, client):
        resp = client.post("/api/v1/riders/me/rides/42/share-link")
        assert resp.status_code == 201
        data = resp.json()
        assert "token" in data
        assert data["is_active"] is True
        assert data["share_url"].startswith("/api/v1/trip-share/")

    def test_post_share_url_contains_token(self, client):
        resp = client.post("/api/v1/riders/me/rides/42/share-link")
        data = resp.json()
        assert data["token"] in data["share_url"]

    def test_post_second_time_revokes_first(self, client):
        r1 = client.post("/api/v1/riders/me/rides/42/share-link")
        r2 = client.post("/api/v1/riders/me/rides/42/share-link")
        assert r1.status_code == 201
        assert r2.status_code == 201
        token1 = r1.json()["token"]
        token2 = r2.json()["token"]
        assert token1 != token2
        # First token should now be revoked (410)
        resp = client.get(f"/api/v1/trip-share/{token1}")
        assert resp.status_code == 410

    def test_get_share_link_200_when_active(self, client):
        client.post("/api/v1/riders/me/rides/42/share-link")
        resp = client.get("/api/v1/riders/me/rides/42/share-link")
        assert resp.status_code == 200
        assert "token" in resp.json()

    def test_get_share_link_404_when_none(self, client):
        resp = client.get("/api/v1/riders/me/rides/99/share-link")
        assert resp.status_code == 404

    def test_delete_share_link_204(self, client):
        client.post("/api/v1/riders/me/rides/42/share-link")
        resp = client.delete("/api/v1/riders/me/rides/42/share-link")
        assert resp.status_code == 204

    def test_delete_share_link_404_when_none(self, client):
        resp = client.delete("/api/v1/riders/me/rides/99/share-link")
        assert resp.status_code == 404

    def test_delete_then_get_returns_404(self, client):
        client.post("/api/v1/riders/me/rides/42/share-link")
        client.delete("/api/v1/riders/me/rides/42/share-link")
        resp = client.get("/api/v1/riders/me/rides/42/share-link")
        assert resp.status_code == 404

    def test_public_get_200_for_valid_token(self, client):
        post_resp = client.post("/api/v1/riders/me/rides/42/share-link")
        token = post_resp.json()["token"]
        resp = client.get(f"/api/v1/trip-share/{token}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["token"] == token
        assert data["status"] == "IN_PROGRESS"
        assert data["driver_first_name"] == "Alex"
        assert data["vehicle_make"] == "Toyota"
        assert data["eta_minutes"] == 8

    def test_public_get_404_for_unknown_token(self, client):
        resp = client.get("/api/v1/trip-share/does-not-exist")
        assert resp.status_code == 404

    def test_public_get_410_for_revoked_token(self, client):
        post_resp = client.post("/api/v1/riders/me/rides/42/share-link")
        token = post_resp.json()["token"]
        client.delete("/api/v1/riders/me/rides/42/share-link")
        resp = client.get(f"/api/v1/trip-share/{token}")
        assert resp.status_code == 410
        assert "expired" in resp.json()["detail"].lower() or "revoked" in resp.json()["detail"].lower()

    def test_public_get_410_for_expired_token(self, client):
        post_resp = client.post("/api/v1/riders/me/rides/42/share-link")
        token = post_resp.json()["token"]
        # Expire the link manually
        for record in _links.values():
            record["expires_at"] = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
        resp = client.get(f"/api/v1/trip-share/{token}")
        assert resp.status_code == 410

    def test_public_endpoint_requires_no_auth(self):
        """Public endpoint should be accessible without any JWT auth override."""
        from unittest.mock import AsyncMock, MagicMock
        from fastapi.testclient import TestClient
        from app.main import app

        # Create a link via the authed client first
        rider = _make_user(user_id=10, role="rider")
        from app.api.deps import require_rider, get_current_user
        from app.db.database import get_db

        async def mock_db():
            db = AsyncMock()
            db.execute = AsyncMock(return_value=MagicMock())
            yield db

        app.dependency_overrides[require_rider] = lambda: rider
        app.dependency_overrides[get_current_user] = lambda: rider
        app.dependency_overrides[get_db] = mock_db
        with TestClient(app) as authed:
            post_resp = authed.post("/api/v1/riders/me/rides/42/share-link")
        app.dependency_overrides.clear()

        token = post_resp.json()["token"]
        # Now hit the public endpoint with only the DB mock — no user auth overrides
        app.dependency_overrides[get_db] = mock_db
        with TestClient(app) as public:
            resp = public.get(f"/api/v1/trip-share/{token}")
        app.dependency_overrides.clear()
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Store reset tests
# ---------------------------------------------------------------------------


class TestStoreReset:
    def test_reset_clears_links(self):
        create_trip_share_link(rider_id=1, ride_id=10)
        assert len(_links) == 1
        _reset_store()
        assert len(_links) == 0

    def test_reset_resets_id_counter(self):
        create_trip_share_link(rider_id=1, ride_id=10)
        _reset_store()
        r = create_trip_share_link(rider_id=1, ride_id=10)
        assert r["id"] == 1

    def test_reset_between_tests_provides_isolation(self):
        # After autouse fixture runs _reset_store, store should be empty
        assert len(_links) == 0


# ---------------------------------------------------------------------------
# Schema tests — admin
# ---------------------------------------------------------------------------


class TestAdminTripShareSchemas:
    def test_entry_has_required_fields(self):
        now = datetime.now(tz=timezone.utc)
        entry = AdminTripShareEntry(
            id=1,
            token="tok",
            share_url="/api/v1/trip-share/tok",
            rider_id=5,
            ride_id=10,
            is_active=True,
            expires_at=now + timedelta(hours=24),
            created_at=now,
        )
        assert entry.rider_id == 5
        assert entry.ride_id == 10
        assert entry.is_active is True

    def test_list_response_shape(self):
        now = datetime.now(tz=timezone.utc)
        entry = AdminTripShareEntry(
            id=1, token="t", share_url="/s", rider_id=1, ride_id=2,
            is_active=True, expires_at=now, created_at=now,
        )
        resp = AdminTripShareListResponse(total=1, skip=0, limit=50, items=[entry])
        assert resp.total == 1
        assert len(resp.items) == 1


# ---------------------------------------------------------------------------
# Service: list_trip_share_links
# ---------------------------------------------------------------------------


class TestListTripShareLinks:
    def test_returns_empty_when_no_links(self):
        assert list_trip_share_links() == []

    def test_returns_all_links(self):
        create_trip_share_link(rider_id=1, ride_id=10)
        create_trip_share_link(rider_id=2, ride_id=20)
        result = list_trip_share_links()
        assert len(result) == 2

    def test_newest_first_ordering(self):
        create_trip_share_link(rider_id=1, ride_id=10)
        create_trip_share_link(rider_id=1, ride_id=11)
        result = list_trip_share_links()
        assert result[0]["ride_id"] == 11
        assert result[1]["ride_id"] == 10

    def test_filter_by_rider_id(self):
        create_trip_share_link(rider_id=1, ride_id=10)
        create_trip_share_link(rider_id=2, ride_id=20)
        result = list_trip_share_links(rider_id=1)
        assert len(result) == 1
        assert result[0]["rider_id"] == 1

    def test_filter_by_is_active_true(self):
        create_trip_share_link(rider_id=1, ride_id=10)
        create_trip_share_link(rider_id=1, ride_id=11)
        revoke_trip_share_link(rider_id=1, ride_id=10)
        result = list_trip_share_links(is_active=True)
        assert len(result) == 1
        assert result[0]["ride_id"] == 11

    def test_filter_by_is_active_false(self):
        create_trip_share_link(rider_id=1, ride_id=10)
        revoke_trip_share_link(rider_id=1, ride_id=10)
        create_trip_share_link(rider_id=1, ride_id=11)
        result = list_trip_share_links(is_active=False)
        assert len(result) == 1
        assert result[0]["is_active"] is False

    def test_pagination_skip_and_limit(self):
        for i in range(5):
            create_trip_share_link(rider_id=1, ride_id=i)
        result = list_trip_share_links(skip=2, limit=2)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Service: get_link_by_token
# ---------------------------------------------------------------------------


class TestGetLinkByToken:
    def test_returns_record_for_known_token(self):
        record = create_trip_share_link(rider_id=1, ride_id=10)
        found = get_link_by_token(record["token"])
        assert found["id"] == record["id"]

    def test_raises_lookup_error_for_unknown_token(self):
        with pytest.raises(LookupError):
            get_link_by_token("no-such-token")


# ---------------------------------------------------------------------------
# Service: admin_revoke_by_token
# ---------------------------------------------------------------------------


class TestAdminRevokeByToken:
    def test_sets_is_active_false(self):
        record = create_trip_share_link(rider_id=1, ride_id=10)
        admin_revoke_by_token(record["token"])
        assert _links[record["id"]]["is_active"] is False

    def test_can_revoke_any_riders_link(self):
        r1 = create_trip_share_link(rider_id=99, ride_id=10)
        admin_revoke_by_token(r1["token"])
        assert _links[r1["id"]]["is_active"] is False

    def test_raises_lookup_error_for_unknown_token(self):
        with pytest.raises(LookupError):
            admin_revoke_by_token("bad-token")


# ---------------------------------------------------------------------------
# Router: admin endpoints
# ---------------------------------------------------------------------------


def _make_admin(user_id: int = 99) -> MagicMock:
    admin = MagicMock()
    admin.id = user_id
    admin.role = MagicMock()
    admin.role.value = "admin"
    admin.is_active = True
    admin.is_admin = True
    return admin


@pytest.fixture()
def admin_client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import require_admin, get_current_user

    admin = _make_admin()
    app.dependency_overrides[require_admin] = lambda: admin
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def rider_client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import require_rider, get_current_user

    rider = _make_user(user_id=10, role="rider")
    app.dependency_overrides[require_rider] = lambda: rider
    app.dependency_overrides[get_current_user] = lambda: rider
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestAdminListTripShares:
    def test_returns_200_and_empty_list(self, admin_client):
        resp = admin_client.get("/api/v1/admin/trip-shares")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_returns_all_links(self, admin_client):
        create_trip_share_link(rider_id=10, ride_id=10)
        create_trip_share_link(rider_id=10, ride_id=20)
        resp = admin_client.get("/api/v1/admin/trip-shares")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    def test_filter_by_rider_id(self, admin_client):
        create_trip_share_link(rider_id=10, ride_id=10)
        create_trip_share_link(rider_id=99, ride_id=20)
        resp = admin_client.get("/api/v1/admin/trip-shares?rider_id=10")
        data = resp.json()
        assert data["total"] == 1
        for item in data["items"]:
            assert item["rider_id"] == 10

    def test_filter_by_is_active_false(self, admin_client):
        r = create_trip_share_link(rider_id=10, ride_id=10)
        revoke_trip_share_link(rider_id=10, ride_id=10)
        resp = admin_client.get("/api/v1/admin/trip-shares?is_active=false")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["is_active"] is False

    def test_response_includes_rider_and_ride_id(self, admin_client):
        create_trip_share_link(rider_id=10, ride_id=42)
        resp = admin_client.get("/api/v1/admin/trip-shares")
        item = resp.json()["items"][0]
        assert "rider_id" in item
        assert item["ride_id"] == 42

    def test_admin_list_requires_admin(self, client):
        """Non-admin (rider) cannot access the admin list endpoint."""
        resp = client.get("/api/v1/admin/trip-shares")
        assert resp.status_code == 403

class TestAdminRevokeTripShare:
    def test_revoke_returns_204(self, admin_client):
        record = create_trip_share_link(rider_id=10, ride_id=10)
        token = record["token"]
        resp = admin_client.delete(f"/api/v1/admin/trip-shares/{token}")
        assert resp.status_code == 204

    def test_revoked_link_returns_410_publicly(self, admin_client):
        record = create_trip_share_link(rider_id=10, ride_id=10)
        token = record["token"]
        admin_client.delete(f"/api/v1/admin/trip-shares/{token}")
        # Public endpoint check using the same client (no auth required)
        resp = admin_client.get(f"/api/v1/trip-share/{token}")
        assert resp.status_code == 410

    def test_revoke_unknown_token_returns_404(self, admin_client):
        resp = admin_client.delete("/api/v1/admin/trip-shares/no-such-token")
        assert resp.status_code == 404

    def test_admin_revoke_requires_admin(self, client):
        """Non-admin (rider) cannot revoke a trip share via the admin endpoint."""
        record = create_trip_share_link(rider_id=10, ride_id=10)
        resp = client.delete(f"/api/v1/admin/trip-shares/{record['token']}")
        assert resp.status_code == 403

