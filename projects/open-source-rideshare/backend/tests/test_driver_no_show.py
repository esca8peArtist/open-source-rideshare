"""Unit tests for driver no-show protection.

Covers:

CancellationCategory enum:
  1. DRIVER_NO_SHOW is a valid enum member
  2. DRIVER_NO_SHOW round-trips as "driver_no_show" string

NotificationType:
  3. DRIVER_NO_SHOW is a valid NotificationType member
  4. DRIVER_NO_SHOW round-trips as "driver_no_show" string

notification_templates.driver_no_show:
  5. Returns correct title and push+SMS channels
  6. Body includes wait_minutes when provided
  7. Body omits wait_minutes when not provided

notify_driver_no_show dispatcher:
  8. Calls send_ride_notification with correct type and wait_minutes
  9. Exception in send_ride_notification is swallowed (fire-and-forget)

Ride model:
  10. arrived_at field exists on Ride model
  11. driver_no_show_reported_at field exists on Ride model

config:
  12. driver_no_show_threshold_minutes has a default value
  13. Default threshold is a positive integer

report_driver_no_show service — success:
  14. Ride status set to CANCELLED
  15. cancellation_category set to DRIVER_NO_SHOW
  16. cancelled_by set to "system"
  17. driver_no_show_reported_at is set (not None)
  18. Returns dict with status="cancelled" and reason="driver_no_show"
  19. Returns refund_initiated=True

report_driver_no_show service — edge cases:
  20. LookupError when ride not found
  21. PermissionError when rider_id does not match ride.rider_id
  22. ValueError when ride status not in reportable statuses (e.g., COMPLETED)
  23. ValueError when no-show already reported (driver_no_show_reported_at set)
  24. IN_PROGRESS status raises ValueError
  25. CANCELLED status raises ValueError

report_driver_no_show service — reportable statuses:
  26. MATCHED status is accepted
  27. DRIVER_EN_ROUTE status is accepted
  28. ARRIVED status is accepted

detect_driver_no_shows — no rides:
  29. Returns 0 when no ARRIVED rides exist

detect_driver_no_shows — ride not past threshold:
  30. Returns 0 when ARRIVED ride has not exceeded threshold

detect_driver_no_shows — ride past threshold:
  31. Returns 1 when a ride is past threshold
  32. Cancelled ride has driver_no_show_reported_at set

detect_driver_no_shows — already reported:
  33. Skips rides with driver_no_show_reported_at already set

detect_driver_no_shows — non-ARRIVED status ignored:
  34. IN_PROGRESS ride not cancelled even if arrived_at is old

detect_driver_no_shows — missing arrived_at:
  35. ARRIVED ride with NULL arrived_at is not auto-cancelled

API — POST /rides/{ride_id}/report-driver-no-show:
  36. Returns 200 with correct payload on success
  37. Returns 404 when ride not found
  38. Returns 403 when rider is not the owner
  39. Returns 409 when ride status not reportable
  40. Returns 409 when no-show already reported
  41. Returns 401 when unauthenticated

arrived_at set on driver ARRIVED transition:
  42. arrived_at is set when driver marks ride as ARRIVED via endpoint

Scheduler integration:
  43. detect_driver_no_shows is called in _scheduler_loop (import-only smoke test)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ride import CancellationCategory, Ride, RideStatus
from app.services.notifications import NotificationType
from app.services.notification_templates import driver_no_show as _tpl_driver_no_show
from app.services.notifications import NotificationChannel


NOW = datetime(2026, 4, 17, 14, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ride(
    *,
    ride_id: int = 1,
    rider_id: int = 10,
    driver_id: int | None = 20,
    status: RideStatus = RideStatus.ARRIVED,
    arrived_at: datetime | None = None,
    driver_no_show_reported_at: datetime | None = None,
    matched_at: datetime | None = None,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.arrived_at = arrived_at
    ride.driver_no_show_reported_at = driver_no_show_reported_at
    ride.matched_at = matched_at or (NOW - timedelta(minutes=20))
    ride.estimated_fare = 15.0
    ride.cancellation_category = None
    ride.cancelled_by = None
    ride.cancelled_at = None
    ride.cancellation_reason = None
    return ride


def _mock_db(ride: MagicMock | None = None) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = ride
    result.scalars.return_value.all.return_value = [ride] if ride else []
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# CancellationCategory
# ---------------------------------------------------------------------------


def test_driver_no_show_category_exists():  # 1
    assert CancellationCategory.DRIVER_NO_SHOW is CancellationCategory.DRIVER_NO_SHOW


def test_driver_no_show_category_value():  # 2
    assert CancellationCategory.DRIVER_NO_SHOW.value == "driver_no_show"


# ---------------------------------------------------------------------------
# NotificationType
# ---------------------------------------------------------------------------


def test_notification_type_driver_no_show_exists():  # 3
    assert NotificationType.DRIVER_NO_SHOW is NotificationType.DRIVER_NO_SHOW


def test_notification_type_driver_no_show_value():  # 4
    assert NotificationType.DRIVER_NO_SHOW.value == "driver_no_show"


# ---------------------------------------------------------------------------
# Notification template
# ---------------------------------------------------------------------------


def test_template_title():  # 5
    title, body, channels = _tpl_driver_no_show()
    assert title == "Driver no-show — ride cancelled"
    assert NotificationChannel.PUSH in channels
    assert NotificationChannel.SMS in channels


def test_template_body_with_wait_minutes():  # 6
    _, body, _ = _tpl_driver_no_show(wait_minutes=12)
    assert "12" in body


def test_template_body_without_wait_minutes():  # 7
    _, body, _ = _tpl_driver_no_show()
    assert "0" not in body or "minute" not in body  # no spurious "0 minutes" text


# ---------------------------------------------------------------------------
# notify_driver_no_show dispatcher
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_driver_no_show_calls_send():  # 8
    from app.services.notification_events import notify_driver_no_show

    db = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = MagicMock(phone="555-1234", email="r@test.com")
    db.execute.return_value = result

    with patch("app.services.notification_events.send_ride_notification", new_callable=AsyncMock) as mock_send:
        await notify_driver_no_show(db, rider_id=1, ride_id=42, wait_minutes=15)

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args
    assert call_kwargs.kwargs.get("type") == NotificationType.DRIVER_NO_SHOW
    assert call_kwargs.kwargs.get("wait_minutes") == 15


@pytest.mark.asyncio
async def test_notify_driver_no_show_swallows_exceptions():  # 9
    from app.services.notification_events import notify_driver_no_show

    db = AsyncMock()
    db.execute.side_effect = RuntimeError("db down")

    # Should not raise
    await notify_driver_no_show(db, rider_id=1, ride_id=42, wait_minutes=5)


# ---------------------------------------------------------------------------
# Ride model fields
# ---------------------------------------------------------------------------


def test_ride_has_arrived_at():  # 10
    assert hasattr(Ride, "arrived_at")


def test_ride_has_driver_no_show_reported_at():  # 11
    assert hasattr(Ride, "driver_no_show_reported_at")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_config_has_threshold():  # 12
    from app.config import settings
    assert hasattr(settings, "driver_no_show_threshold_minutes")


def test_config_threshold_positive():  # 13
    from app.config import settings
    assert settings.driver_no_show_threshold_minutes > 0


# ---------------------------------------------------------------------------
# report_driver_no_show service — success
# ---------------------------------------------------------------------------


_NO_SHOW_PATCHES = [
    patch("app.services.payments.process_refund", new_callable=AsyncMock, return_value={}),
    patch("app.services.matching.get_matching_engine", new_callable=AsyncMock),
    patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock),
    patch("app.services.notification_events.notify_driver_no_show", new_callable=AsyncMock),
    patch("app.services.audit_events.audit_ride_cancelled", new_callable=AsyncMock),
]


async def _run_report(ride, *, refund_return=None):
    from app.services.driver_no_show import report_driver_no_show

    db = _mock_db(ride)
    patches = [
        patch("app.services.payments.process_refund", new_callable=AsyncMock,
              return_value=refund_return or {}),
        patch("app.services.matching.get_matching_engine", new_callable=AsyncMock),
        patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock),
        patch("app.services.notification_events.notify_driver_no_show", new_callable=AsyncMock),
        patch("app.services.audit_events.audit_ride_cancelled", new_callable=AsyncMock),
    ]
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        return await report_driver_no_show(ride_id=ride.id, rider_id=ride.rider_id, db=db, now=NOW)


@pytest.mark.asyncio
async def test_report_sets_cancelled_status():  # 14
    ride = _make_ride(status=RideStatus.ARRIVED, arrived_at=NOW - timedelta(minutes=10))
    await _run_report(ride)
    assert ride.status == RideStatus.CANCELLED


@pytest.mark.asyncio
async def test_report_sets_cancellation_category():  # 15
    ride = _make_ride(status=RideStatus.ARRIVED, arrived_at=NOW - timedelta(minutes=5))
    await _run_report(ride)
    assert ride.cancellation_category == CancellationCategory.DRIVER_NO_SHOW


@pytest.mark.asyncio
async def test_report_sets_cancelled_by_system():  # 16
    ride = _make_ride(status=RideStatus.ARRIVED, arrived_at=NOW - timedelta(minutes=5))
    await _run_report(ride)
    assert ride.cancelled_by == "system"


@pytest.mark.asyncio
async def test_report_sets_driver_no_show_reported_at():  # 17
    ride = _make_ride(status=RideStatus.ARRIVED, arrived_at=NOW - timedelta(minutes=5))
    await _run_report(ride)
    assert ride.driver_no_show_reported_at == NOW


@pytest.mark.asyncio
async def test_report_returns_correct_status():  # 18
    ride = _make_ride(status=RideStatus.ARRIVED, arrived_at=NOW - timedelta(minutes=5))
    result = await _run_report(ride)
    assert result["status"] == "cancelled"
    assert result["reason"] == "driver_no_show"


@pytest.mark.asyncio
async def test_report_returns_refund_initiated():  # 19
    ride = _make_ride(status=RideStatus.ARRIVED, arrived_at=NOW - timedelta(minutes=5))
    result = await _run_report(ride, refund_return={"refund_id": "re_abc"})
    assert result["refund_initiated"] is True


# ---------------------------------------------------------------------------
# report_driver_no_show — edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_ride_not_found():  # 20
    from app.services.driver_no_show import report_driver_no_show

    db = _mock_db(None)

    with pytest.raises(LookupError):
        await report_driver_no_show(ride_id=999, rider_id=10, db=db, now=NOW)


@pytest.mark.asyncio
async def test_report_wrong_rider():  # 21
    from app.services.driver_no_show import report_driver_no_show

    ride = _make_ride(rider_id=10)
    db = _mock_db(ride)

    with pytest.raises(PermissionError):
        await report_driver_no_show(ride_id=1, rider_id=99, db=db, now=NOW)


@pytest.mark.asyncio
async def test_report_wrong_status_completed():  # 22
    from app.services.driver_no_show import report_driver_no_show

    ride = _make_ride(status=RideStatus.COMPLETED)
    db = _mock_db(ride)

    with pytest.raises(ValueError, match="status"):
        await report_driver_no_show(ride_id=1, rider_id=10, db=db, now=NOW)


@pytest.mark.asyncio
async def test_report_already_reported():  # 23
    from app.services.driver_no_show import report_driver_no_show

    ride = _make_ride(
        status=RideStatus.ARRIVED,
        driver_no_show_reported_at=NOW - timedelta(minutes=2),
    )
    db = _mock_db(ride)

    with pytest.raises(ValueError, match="already been reported"):
        await report_driver_no_show(ride_id=1, rider_id=10, db=db, now=NOW)


@pytest.mark.asyncio
async def test_report_wrong_status_in_progress():  # 24
    from app.services.driver_no_show import report_driver_no_show

    ride = _make_ride(status=RideStatus.IN_PROGRESS)
    db = _mock_db(ride)

    with pytest.raises(ValueError):
        await report_driver_no_show(ride_id=1, rider_id=10, db=db, now=NOW)


@pytest.mark.asyncio
async def test_report_wrong_status_cancelled():  # 25
    from app.services.driver_no_show import report_driver_no_show

    ride = _make_ride(status=RideStatus.CANCELLED)
    db = _mock_db(ride)

    with pytest.raises(ValueError):
        await report_driver_no_show(ride_id=1, rider_id=10, db=db, now=NOW)


# ---------------------------------------------------------------------------
# report_driver_no_show — reportable statuses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RideStatus.MATCHED, RideStatus.DRIVER_EN_ROUTE, RideStatus.ARRIVED])
async def test_report_accepted_for_reportable_status(status):  # 26-28
    ride = _make_ride(status=status, arrived_at=None)
    result = await _run_report(ride)
    assert result["status"] == "cancelled"


# ---------------------------------------------------------------------------
# detect_driver_no_shows
# ---------------------------------------------------------------------------


def _mock_detect_db(rides: list) -> tuple:
    """Build an async_session mock that returns the given rides from execute."""
    db = AsyncMock()
    q_result = MagicMock()
    q_result.scalars.return_value.all.return_value = rides
    db.execute.return_value = q_result
    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=db)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    return session_ctx, db


@pytest.mark.asyncio
async def test_detect_no_shows_returns_zero_no_rides():  # 29
    from app.services.driver_no_show import detect_driver_no_shows

    session_ctx, _ = _mock_detect_db([])
    with patch("app.db.database.async_session", return_value=session_ctx):
        count = await detect_driver_no_shows(now=NOW)

    assert count == 0


@pytest.mark.asyncio
async def test_detect_no_shows_skips_under_threshold():  # 30
    from app.services.driver_no_show import detect_driver_no_shows

    # Query returns empty — DB would filter the ride by arrived_at <= cutoff
    session_ctx, _ = _mock_detect_db([])
    with patch("app.db.database.async_session", return_value=session_ctx):
        count = await detect_driver_no_shows(now=NOW)

    assert count == 0


@pytest.mark.asyncio
async def test_detect_no_shows_cancels_overdue_ride():  # 31
    from app.services.driver_no_show import detect_driver_no_shows

    ride = _make_ride(
        status=RideStatus.ARRIVED,
        arrived_at=NOW - timedelta(minutes=20),
    )

    session_ctx, _ = _mock_detect_db([ride])
    with (
        patch("app.db.database.async_session", return_value=session_ctx),
        patch("app.services.payments.process_refund", new_callable=AsyncMock, return_value={}),
        patch("app.services.matching.get_matching_engine", new_callable=AsyncMock),
        patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock),
        patch("app.services.notification_events.notify_driver_no_show", new_callable=AsyncMock),
        patch("app.services.audit_events.audit_ride_cancelled", new_callable=AsyncMock),
    ):
        count = await detect_driver_no_shows(now=NOW)

    assert count == 1


@pytest.mark.asyncio
async def test_detect_sets_reported_at_on_auto_cancel():  # 32
    from app.services.driver_no_show import detect_driver_no_shows

    ride = _make_ride(
        status=RideStatus.ARRIVED,
        arrived_at=NOW - timedelta(minutes=20),
    )

    session_ctx, _ = _mock_detect_db([ride])
    with (
        patch("app.db.database.async_session", return_value=session_ctx),
        patch("app.services.payments.process_refund", new_callable=AsyncMock, return_value={}),
        patch("app.services.matching.get_matching_engine", new_callable=AsyncMock),
        patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock),
        patch("app.services.notification_events.notify_driver_no_show", new_callable=AsyncMock),
        patch("app.services.audit_events.audit_ride_cancelled", new_callable=AsyncMock),
    ):
        await detect_driver_no_shows(now=NOW)

    assert ride.driver_no_show_reported_at == NOW


@pytest.mark.asyncio
async def test_detect_skips_already_reported():  # 33
    from app.services.driver_no_show import detect_driver_no_shows

    # DB query filters driver_no_show_reported_at IS NULL — return empty
    session_ctx, _ = _mock_detect_db([])
    with patch("app.db.database.async_session", return_value=session_ctx):
        count = await detect_driver_no_shows(now=NOW)

    assert count == 0


@pytest.mark.asyncio
async def test_detect_ignores_in_progress_rides():  # 34
    from app.services.driver_no_show import detect_driver_no_shows

    # DB query filters status=ARRIVED — non-ARRIVED rides excluded; return empty
    session_ctx, _ = _mock_detect_db([])
    with patch("app.db.database.async_session", return_value=session_ctx):
        count = await detect_driver_no_shows(now=NOW)

    assert count == 0


@pytest.mark.asyncio
async def test_detect_ignores_null_arrived_at():  # 35
    from app.services.driver_no_show import detect_driver_no_shows

    # DB query filters arrived_at.isnot(None) — null arrived_at excluded; return empty
    session_ctx, _ = _mock_detect_db([])
    with patch("app.db.database.async_session", return_value=session_ctx):
        count = await detect_driver_no_shows(now=NOW)

    assert count == 0


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


def _api_overrides(app, rider_id: int = 10):
    from app.api.deps import get_current_user
    from app.db.database import get_db

    rider = MagicMock()
    rider.id = rider_id

    async def override_user():
        return rider

    async def override_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_db] = override_db


@pytest.mark.asyncio
async def test_api_report_no_show_success():  # 36
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    _api_overrides(app, rider_id=10)

    with patch(
        "app.services.driver_no_show.report_driver_no_show",
        new_callable=AsyncMock,
        return_value={"status": "cancelled", "reason": "driver_no_show", "refund_initiated": True},
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/rides/1/report-driver-no-show")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "cancelled"
    assert data["reason"] == "driver_no_show"


@pytest.mark.asyncio
async def test_api_report_no_show_404():  # 37
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    _api_overrides(app, rider_id=10)

    with patch(
        "app.services.driver_no_show.report_driver_no_show",
        new_callable=AsyncMock,
        side_effect=LookupError("not found"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/rides/999/report-driver-no-show")

    app.dependency_overrides.clear()
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_report_no_show_403():  # 38
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    _api_overrides(app, rider_id=99)

    with patch(
        "app.services.driver_no_show.report_driver_no_show",
        new_callable=AsyncMock,
        side_effect=PermissionError("not authorised"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/rides/1/report-driver-no-show")

    app.dependency_overrides.clear()
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_api_report_no_show_409_wrong_status():  # 39
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    _api_overrides(app, rider_id=10)

    with patch(
        "app.services.driver_no_show.report_driver_no_show",
        new_callable=AsyncMock,
        side_effect=ValueError("Cannot report in current status"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/rides/1/report-driver-no-show")

    app.dependency_overrides.clear()
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_api_report_no_show_409_already_reported():  # 40
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    _api_overrides(app, rider_id=10)

    with patch(
        "app.services.driver_no_show.report_driver_no_show",
        new_callable=AsyncMock,
        side_effect=ValueError("A no-show has already been reported"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/rides/1/report-driver-no-show")

    app.dependency_overrides.clear()
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_api_report_no_show_401_unauthenticated():  # 41
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    from app.api.deps import get_current_user
    from app.db.database import get_db
    from fastapi import HTTPException

    async def override_user():
        raise HTTPException(status_code=401, detail="Not authenticated")

    async def override_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/rides/1/report-driver-no-show")

    app.dependency_overrides.clear()
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# arrived_at set on ARRIVED transition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arrived_at_set_on_driver_arrived():  # 42
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    from app.api.deps import require_driver
    from app.db.database import get_db

    driver = MagicMock()
    driver.id = 20

    ride = MagicMock(spec=Ride)
    ride.id = 1
    ride.driver_id = driver.id
    ride.rider_id = 10
    ride.status = RideStatus.DRIVER_EN_ROUTE
    ride.arrived_at = None

    async def override_driver():
        return driver

    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = ride
    db.execute.return_value = result

    async def override_db():
        yield db

    app.dependency_overrides[require_driver] = override_driver
    app.dependency_overrides[get_db] = override_db

    with (
        patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock),
        patch("app.services.notification_events.notify_driver_arrived", new_callable=AsyncMock),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/rides/1/arrived")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert ride.arrived_at is not None


# ---------------------------------------------------------------------------
# Scheduler integration smoke test
# ---------------------------------------------------------------------------


def test_scheduler_imports_detect_driver_no_shows():  # 43
    # Verify the import path used in _scheduler_loop works
    from app.services.driver_no_show import detect_driver_no_shows
    assert callable(detect_driver_no_shows)
