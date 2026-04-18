"""Tests for trip share view notification.

When a rider's shared trip link is first viewed by anyone, the rider receives
a push notification.

Coverage
--------
NotificationType and template:
  1.  NotificationType.TRIP_SHARE_VIEWED exists in enum
  2.  trip_share_viewed template returns push channel
  3.  trip_share_viewed template body is non-empty
  4.  TRIP_SHARE_VIEWED is registered in TEMPLATES

Service — mark_first_view:
  5.  Returns rider_id on first call for an active link
  6.  Returns None on subsequent calls (already viewed)
  7.  Returns None for an unknown token
  8.  Returns None for a revoked (inactive) link
  9.  Sets first_viewed_at timestamp on first view

Router — GET /api/v1/trip-share/{token}:
  10. 200 on valid token (unchanged behaviour)
  11. first_viewed_at is set after a public view
  12. Second view does not reset first_viewed_at (idempotent)
  13. 404 for unknown token (no notification triggered)
  14. 410 for revoked token (no notification triggered)

notify_trip_share_viewed dispatcher:
  15. Sends notification to the correct rider_id
  16. Uses TRIP_SHARE_VIEWED type
  17. Passes ride_id to the notification
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.trip_share import TripShareView
from app.services.notification_templates import trip_share_viewed, TEMPLATES
from app.services.notifications import NotificationChannel, NotificationType
from app.services.trip_share import (
    _links,
    _reset_store,
    create_trip_share_link,
    mark_first_view,
    revoke_trip_share_link,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_store():
    _reset_store()
    yield
    _reset_store()


def _make_user(user_id: int = 1, role: str = "rider") -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.role = MagicMock()
    user.role.value = role
    user.is_active = True
    return user


# ---------------------------------------------------------------------------
# 1–4: NotificationType and template
# ---------------------------------------------------------------------------


class TestTripShareViewedNotificationType:
    def test_enum_value_exists(self):
        assert NotificationType.TRIP_SHARE_VIEWED == "trip_share_viewed"

    def test_registered_in_templates(self):
        assert NotificationType.TRIP_SHARE_VIEWED in TEMPLATES


class TestTripShareViewedTemplate:
    def test_returns_push_channel(self):
        _, _, channels = trip_share_viewed()
        assert NotificationChannel.PUSH in channels

    def test_body_is_non_empty(self):
        _, body, _ = trip_share_viewed()
        assert len(body) > 0

    def test_title_is_non_empty(self):
        title, _, _ = trip_share_viewed()
        assert len(title) > 0


# ---------------------------------------------------------------------------
# 5–9: mark_first_view service function
# ---------------------------------------------------------------------------


class TestMarkFirstView:
    def test_returns_rider_id_on_first_view(self):
        record = create_trip_share_link(rider_id=42, ride_id=7)
        result = mark_first_view(record["token"])
        assert result == 42

    def test_returns_none_on_second_view(self):
        record = create_trip_share_link(rider_id=42, ride_id=7)
        mark_first_view(record["token"])
        result = mark_first_view(record["token"])
        assert result is None

    def test_returns_none_for_unknown_token(self):
        result = mark_first_view("does-not-exist")
        assert result is None

    def test_returns_none_for_revoked_link(self):
        record = create_trip_share_link(rider_id=42, ride_id=7)
        revoke_trip_share_link(rider_id=42, ride_id=7)
        result = mark_first_view(record["token"])
        assert result is None

    def test_sets_first_viewed_at_timestamp(self):
        record = create_trip_share_link(rider_id=42, ride_id=7)
        assert record["first_viewed_at"] is None
        mark_first_view(record["token"])
        # Inspect the store directly
        link = next(r for r in _links.values() if r["token"] == record["token"])
        assert link["first_viewed_at"] is not None
        assert isinstance(link["first_viewed_at"], datetime)

    def test_first_viewed_at_not_overwritten_on_second_view(self):
        record = create_trip_share_link(rider_id=42, ride_id=7)
        mark_first_view(record["token"])
        link = next(r for r in _links.values() if r["token"] == record["token"])
        first_ts = link["first_viewed_at"]
        mark_first_view(record["token"])
        assert link["first_viewed_at"] == first_ts


# ---------------------------------------------------------------------------
# 10–14: Router integration tests (TestClient)
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import require_rider, get_current_user
    from app.db.database import get_db

    rider = _make_user(user_id=10)

    async def mock_db():
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(one_or_none=MagicMock(return_value=None)))
        yield db

    app.dependency_overrides[require_rider] = lambda: rider
    app.dependency_overrides[get_current_user] = lambda: rider
    app.dependency_overrides[get_db] = mock_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestTripShareViewRouter:
    def test_public_get_200_for_valid_token(self, client):
        post_resp = client.post("/api/v1/riders/me/rides/42/share-link")
        token = post_resp.json()["token"]
        resp = client.get(f"/api/v1/trip-share/{token}")
        assert resp.status_code == 200

    def test_first_view_sets_first_viewed_at(self, client):
        post_resp = client.post("/api/v1/riders/me/rides/42/share-link")
        token = post_resp.json()["token"]
        # Before view
        link = next(r for r in _links.values() if r["token"] == token)
        assert link["first_viewed_at"] is None
        # View it
        client.get(f"/api/v1/trip-share/{token}")
        assert link["first_viewed_at"] is not None

    def test_second_view_does_not_reset_first_viewed_at(self, client):
        post_resp = client.post("/api/v1/riders/me/rides/42/share-link")
        token = post_resp.json()["token"]
        client.get(f"/api/v1/trip-share/{token}")
        link = next(r for r in _links.values() if r["token"] == token)
        first_ts = link["first_viewed_at"]
        client.get(f"/api/v1/trip-share/{token}")
        assert link["first_viewed_at"] == first_ts

    def test_404_for_unknown_token_no_crash(self, client):
        resp = client.get("/api/v1/trip-share/unknown-token-xyz")
        assert resp.status_code == 404

    def test_410_for_revoked_token_no_crash(self, client):
        post_resp = client.post("/api/v1/riders/me/rides/42/share-link")
        token = post_resp.json()["token"]
        client.delete("/api/v1/riders/me/rides/42/share-link")
        resp = client.get(f"/api/v1/trip-share/{token}")
        assert resp.status_code == 410


# ---------------------------------------------------------------------------
# 15–17: notify_trip_share_viewed dispatcher tests
# ---------------------------------------------------------------------------


class TestNotifyTripShareViewed:
    @pytest.mark.asyncio
    async def test_sends_notification_to_correct_rider(self):
        from app.services.notification_events import notify_trip_share_viewed

        db = AsyncMock()
        captured_user_ids = []

        async def mock_send(user_id, type, ride_id, db, phone, email, **kwargs):
            captured_user_ids.append(user_id)

        with patch("app.services.notification_events.send_ride_notification", side_effect=mock_send):
            with patch("app.services.notification_events._get_user_contact", new=AsyncMock(return_value=(None, None))):
                await notify_trip_share_viewed(db=db, rider_id=55, ride_id=99)

        assert captured_user_ids == [55]

    @pytest.mark.asyncio
    async def test_uses_trip_share_viewed_type(self):
        from app.services.notification_events import notify_trip_share_viewed

        db = AsyncMock()
        captured_types = []

        async def mock_send(user_id, type, ride_id, db, phone, email, **kwargs):
            captured_types.append(type)

        with patch("app.services.notification_events.send_ride_notification", side_effect=mock_send):
            with patch("app.services.notification_events._get_user_contact", new=AsyncMock(return_value=(None, None))):
                await notify_trip_share_viewed(db=db, rider_id=55, ride_id=99)

        assert captured_types == [NotificationType.TRIP_SHARE_VIEWED]

    @pytest.mark.asyncio
    async def test_passes_ride_id(self):
        from app.services.notification_events import notify_trip_share_viewed

        db = AsyncMock()
        captured_ride_ids = []

        async def mock_send(user_id, type, ride_id, db, phone, email, **kwargs):
            captured_ride_ids.append(ride_id)

        with patch("app.services.notification_events.send_ride_notification", side_effect=mock_send):
            with patch("app.services.notification_events._get_user_contact", new=AsyncMock(return_value=(None, None))):
                await notify_trip_share_viewed(db=db, rider_id=55, ride_id=99)

        assert captured_ride_ids == [99]
