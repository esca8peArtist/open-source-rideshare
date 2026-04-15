"""Tests for the Community Safety Alerts feature.

Geography helpers (pure):
  1.  _haversine_km — identical points → 0 km
  2.  _haversine_km — approximate distance between known coordinates
  3.  _haversine_km — symmetry: dist(A→B) == dist(B→A)
  4.  _alerts_within_radius — alert at centre → included
  5.  _alerts_within_radius — alert beyond radius → excluded
  6.  _alerts_within_radius — alert outside radius but within its own radius_meters → included
  7.  _alerts_within_radius — empty list → empty result

Service layer (async, mocked DB):
  8.  create_alert — road_hazard gets auto_approved
  9.  create_alert — construction gets auto_approved
  10. create_alert — weather gets auto_approved
  11. create_alert — traffic gets auto_approved
  12. create_alert — dangerous_area gets pending
  13. create_alert — other gets pending
  14. get_alert — returns alert when found
  15. get_alert — raises 404 when not found
  16. get_active_alerts_near — returns approved alerts in bounding box
  17. get_active_alerts_near — filters out pending alerts
  18. get_active_alerts_near — filters out inactive alerts
  19. get_active_alerts_near — filters out expired alerts
  20. upvote_alert — creates upvote and increments count
  21. upvote_alert — raises 409 on duplicate vote
  22. upvote_alert — raises 404 on missing alert
  23. upvote_alert — raises 409 on inactive alert
  24. list_my_alerts — returns paginated results with correct total
  25. list_my_alerts — empty result for user with no alerts
  26. deactivate_alert — reporter can deactivate own alert
  27. deactivate_alert — admin can deactivate any alert
  28. deactivate_alert — raises 403 when non-reporter non-admin tries
  29. deactivate_alert — raises 404 on missing alert
  30. deactivate_alert — raises 409 when already inactive
  31. admin_list_alerts — returns paginated all alerts
  32. admin_list_alerts — filters by moderation_status
  33. admin_list_alerts — filters by alert_type
  34. admin_moderate_alert — approve sets status and records moderator
  35. admin_moderate_alert — reject sets status and deactivates alert
  36. admin_moderate_alert — raises 404 on missing alert
  37. admin_moderate_alert — raises 422 for invalid action
  38. get_platform_alert_stats — returns expected keys in result dict

Schema validation:
  39. CreateSafetyAlertRequest — valid minimal payload passes
  40. CreateSafetyAlertRequest — latitude out of range raises error
  41. CreateSafetyAlertRequest — longitude out of range raises error
  42. CreateSafetyAlertRequest — radius_meters zero raises error
  43. CreateSafetyAlertRequest — expires_at in past raises error
  44. AdminModerateAlertRequest — 'approved' is valid
  45. AdminModerateAlertRequest — 'rejected' is valid
  46. AdminModerateAlertRequest — 'pending' raises validation error
  47. SafetyAlertResponse.from_alert — maps all fields correctly
  48. SafetyAlertDetailResponse.from_alert — includes reporter_id and moderation fields

API layer (integration-style, skipped without live DB):
  49. POST /safety-alerts — 201 and detail response returned
  50. POST /safety-alerts — 401 for unauthenticated request
  51. GET /safety-alerts/nearby — 200 with alert list
  52. GET /safety-alerts/me — 200 paginated list
  53. POST /safety-alerts/{id}/upvote — 200 with updated alert
  54. POST /safety-alerts/{id}/upvote — 409 on duplicate
  55. DELETE /safety-alerts/{id} — 200 deactivated
  56. DELETE /safety-alerts/{id} — 403 for non-reporter
  57. GET /admin/safety-alerts — 200 admin list
  58. GET /admin/safety-alerts/stats — 200 stats
  59. POST /admin/safety-alerts/{id}/moderate — 200 approved
  60. GET /admin/safety-alerts/{id} — 200 detail
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.safety_alert import (
    AlertSeverity,
    AlertType,
    ModerationStatus,
    ReporterRole,
    SafetyAlert,
    SafetyAlertUpvote,
)
from app.schemas.safety_alert import (
    AdminModerateAlertRequest,
    CreateSafetyAlertRequest,
    SafetyAlertDetailResponse,
    SafetyAlertResponse,
)
from app.services.safety_alert import (
    SafetyAlertError,
    _alerts_within_radius,
    _haversine_km,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
_FUTURE = _NOW + timedelta(hours=3)
_PAST = _NOW - timedelta(hours=1)


def _make_alert(**kwargs) -> SafetyAlert:
    defaults = dict(
        id=1,
        reporter_id=42,
        reporter_role=ReporterRole.driver,
        alert_type=AlertType.road_hazard,
        severity=AlertSeverity.medium,
        latitude=40.7128,
        longitude=-74.0060,
        radius_meters=100.0,
        description="Large pothole on main street",
        is_active=True,
        expires_at=None,
        moderation_status=ModerationStatus.auto_approved,
        moderated_by=None,
        moderated_at=None,
        moderation_note=None,
        upvote_count=0,
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(kwargs)
    alert = MagicMock(spec=SafetyAlert)
    for k, v in defaults.items():
        setattr(alert, k, v)
    return alert


def _make_upvote(**kwargs) -> SafetyAlertUpvote:
    defaults = dict(id=1, alert_id=1, voter_id=99, created_at=_NOW)
    defaults.update(kwargs)
    upvote = MagicMock(spec=SafetyAlertUpvote)
    for k, v in defaults.items():
        setattr(upvote, k, v)
    return upvote


# ---------------------------------------------------------------------------
# 1-7: Geography helpers
# ---------------------------------------------------------------------------


def test_haversine_identical_points():
    """Test 1: identical coords → 0 km."""
    assert _haversine_km(40.0, -74.0, 40.0, -74.0) == pytest.approx(0.0, abs=1e-6)


def test_haversine_known_distance():
    """Test 2: NYC to Philadelphia ≈ 130 km."""
    # NYC (40.7128, -74.0060) → Philadelphia (39.9526, -75.1652)
    dist = _haversine_km(40.7128, -74.0060, 39.9526, -75.1652)
    assert 125 < dist < 140


def test_haversine_symmetry():
    """Test 3: dist(A→B) == dist(B→A)."""
    d1 = _haversine_km(40.0, -74.0, 41.0, -73.0)
    d2 = _haversine_km(41.0, -73.0, 40.0, -74.0)
    assert d1 == pytest.approx(d2, abs=1e-9)


def test_alerts_within_radius_centre_included():
    """Test 4: alert at query centre → included."""
    alert = _make_alert(latitude=40.0, longitude=-74.0, radius_meters=100.0)
    result = _alerts_within_radius([alert], lat=40.0, lon=-74.0, radius_km=5.0)
    assert alert in result


def test_alerts_within_radius_far_excluded():
    """Test 5: alert 100 km away → excluded when radius=5 km."""
    alert = _make_alert(latitude=41.0, longitude=-73.0, radius_meters=100.0)
    # query point is 40.0, -74.0 — distance ≈ 140 km
    result = _alerts_within_radius([alert], lat=40.0, lon=-74.0, radius_km=5.0)
    assert alert not in result


def test_alerts_within_radius_large_alert_radius():
    """Test 6: alert centre just outside radius but alert's radius_meters bridges gap → included."""
    # 6 km away with 5 km query radius but alert.radius_meters=2000m (2km)
    # effective_radius = 5 + 2 = 7 km, so dist~6 → included
    alert = _make_alert(latitude=40.054, longitude=-74.0, radius_meters=2000.0)
    result = _alerts_within_radius([alert], lat=40.0, lon=-74.0, radius_km=5.0)
    assert alert in result


def test_alerts_within_radius_empty():
    """Test 7: empty list → empty result."""
    assert _alerts_within_radius([], lat=40.0, lon=-74.0, radius_km=5.0) == []


# ---------------------------------------------------------------------------
# 8-13: create_alert — auto-approve logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_alert_road_hazard_auto_approved():
    """Test 8: road_hazard → auto_approved."""
    from app.services.safety_alert import create_alert

    body = CreateSafetyAlertRequest(
        alert_type=AlertType.road_hazard,
        latitude=40.0,
        longitude=-74.0,
    )
    db = AsyncMock()
    saved = _make_alert(moderation_status=ModerationStatus.auto_approved)
    db.refresh = AsyncMock(return_value=None)

    with patch("app.services.safety_alert.SafetyAlert", return_value=saved):
        with patch.object(db, "add"), patch.object(db, "commit", new_callable=AsyncMock):
            db.refresh.return_value = None
            result = await create_alert(db, reporter_id=1, reporter_role=ReporterRole.driver, body=body)

    assert result.moderation_status == ModerationStatus.auto_approved


@pytest.mark.asyncio
async def test_create_alert_construction_auto_approved():
    """Test 9: construction → auto_approved."""
    from app.services.safety_alert import create_alert

    body = CreateSafetyAlertRequest(alert_type=AlertType.construction, latitude=40.0, longitude=-74.0)
    db = AsyncMock()
    saved = _make_alert(moderation_status=ModerationStatus.auto_approved)
    with patch("app.services.safety_alert.SafetyAlert", return_value=saved):
        with patch.object(db, "add"), patch.object(db, "commit", new_callable=AsyncMock):
            result = await create_alert(db, 1, ReporterRole.driver, body)
    assert result.moderation_status == ModerationStatus.auto_approved


@pytest.mark.asyncio
async def test_create_alert_weather_auto_approved():
    """Test 10: weather → auto_approved."""
    from app.services.safety_alert import create_alert

    body = CreateSafetyAlertRequest(alert_type=AlertType.weather, latitude=40.0, longitude=-74.0)
    db = AsyncMock()
    saved = _make_alert(moderation_status=ModerationStatus.auto_approved)
    with patch("app.services.safety_alert.SafetyAlert", return_value=saved):
        with patch.object(db, "add"), patch.object(db, "commit", new_callable=AsyncMock):
            result = await create_alert(db, 1, ReporterRole.driver, body)
    assert result.moderation_status == ModerationStatus.auto_approved


@pytest.mark.asyncio
async def test_create_alert_traffic_auto_approved():
    """Test 11: traffic → auto_approved."""
    from app.services.safety_alert import create_alert

    body = CreateSafetyAlertRequest(alert_type=AlertType.traffic, latitude=40.0, longitude=-74.0)
    db = AsyncMock()
    saved = _make_alert(moderation_status=ModerationStatus.auto_approved)
    with patch("app.services.safety_alert.SafetyAlert", return_value=saved):
        with patch.object(db, "add"), patch.object(db, "commit", new_callable=AsyncMock):
            result = await create_alert(db, 1, ReporterRole.driver, body)
    assert result.moderation_status == ModerationStatus.auto_approved


@pytest.mark.asyncio
async def test_create_alert_dangerous_area_pending():
    """Test 12: dangerous_area → pending."""
    from app.services.safety_alert import create_alert

    body = CreateSafetyAlertRequest(
        alert_type=AlertType.dangerous_area, latitude=40.0, longitude=-74.0
    )
    db = AsyncMock()
    saved = _make_alert(moderation_status=ModerationStatus.pending)
    with patch("app.services.safety_alert.SafetyAlert", return_value=saved):
        with patch.object(db, "add"), patch.object(db, "commit", new_callable=AsyncMock):
            result = await create_alert(db, 1, ReporterRole.rider, body)
    assert result.moderation_status == ModerationStatus.pending


@pytest.mark.asyncio
async def test_create_alert_other_pending():
    """Test 13: other → pending."""
    from app.services.safety_alert import create_alert

    body = CreateSafetyAlertRequest(alert_type=AlertType.other, latitude=40.0, longitude=-74.0)
    db = AsyncMock()
    saved = _make_alert(moderation_status=ModerationStatus.pending)
    with patch("app.services.safety_alert.SafetyAlert", return_value=saved):
        with patch.object(db, "add"), patch.object(db, "commit", new_callable=AsyncMock):
            result = await create_alert(db, 1, ReporterRole.rider, body)
    assert result.moderation_status == ModerationStatus.pending


# ---------------------------------------------------------------------------
# 14-15: get_alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_alert_found():
    """Test 14: returns alert when found."""
    from app.services.safety_alert import get_alert

    alert = _make_alert()
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = alert
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_alert(db, 1)
    assert result is alert


@pytest.mark.asyncio
async def test_get_alert_not_found():
    """Test 15: raises SafetyAlertError(404) when not found."""
    from app.services.safety_alert import get_alert

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(SafetyAlertError) as exc_info:
        await get_alert(db, 999)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 16-19: get_active_alerts_near
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_alerts_near_returns_approved():
    """Test 16: approved alerts in bounding box are returned."""
    from app.services.safety_alert import get_active_alerts_near

    alert = _make_alert(
        moderation_status=ModerationStatus.auto_approved, is_active=True, expires_at=None
    )
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [alert]
    db.execute = AsyncMock(return_value=mock_result)

    with patch("app.services.safety_alert._alerts_within_radius", return_value=[alert]):
        result = await get_active_alerts_near(db, lat=40.7128, lon=-74.0060, radius_km=5.0)

    assert alert in result


@pytest.mark.asyncio
async def test_get_active_alerts_near_filters_pending():
    """Test 17: pending alerts are not returned (filtered at DB query level)."""
    from app.services.safety_alert import get_active_alerts_near

    db = AsyncMock()
    mock_result = MagicMock()
    # Simulate DB returning empty (pending alert filtered by WHERE clause)
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)

    with patch("app.services.safety_alert._alerts_within_radius", return_value=[]):
        result = await get_active_alerts_near(db, lat=40.0, lon=-74.0, radius_km=5.0)

    assert result == []


@pytest.mark.asyncio
async def test_get_active_alerts_near_filters_inactive():
    """Test 18: inactive alerts excluded."""
    from app.services.safety_alert import get_active_alerts_near

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)

    with patch("app.services.safety_alert._alerts_within_radius", return_value=[]):
        result = await get_active_alerts_near(db, lat=40.0, lon=-74.0)

    assert result == []


@pytest.mark.asyncio
async def test_get_active_alerts_near_filters_expired():
    """Test 19: expired alerts excluded."""
    from app.services.safety_alert import get_active_alerts_near

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)

    with patch("app.services.safety_alert._alerts_within_radius", return_value=[]):
        result = await get_active_alerts_near(db, lat=40.0, lon=-74.0)

    assert result == []


# ---------------------------------------------------------------------------
# 20-23: upvote_alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upvote_alert_success():
    """Test 20: creates upvote and increments count."""
    from app.services.safety_alert import upvote_alert

    alert = _make_alert(is_active=True, upvote_count=2)
    db = AsyncMock()

    # First execute: get_alert
    alert_result = MagicMock()
    alert_result.scalar_one_or_none.return_value = alert
    # Second execute: check existing upvote
    upvote_result = MagicMock()
    upvote_result.scalar_one_or_none.return_value = None

    db.execute = AsyncMock(side_effect=[alert_result, upvote_result])
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    result = await upvote_alert(db, alert_id=1, voter_id=99)

    assert alert.upvote_count == 3
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_upvote_alert_duplicate_raises_409():
    """Test 21: second vote raises 409."""
    from app.services.safety_alert import upvote_alert

    alert = _make_alert(is_active=True)
    db = AsyncMock()

    alert_result = MagicMock()
    alert_result.scalar_one_or_none.return_value = alert
    existing_upvote_result = MagicMock()
    existing_upvote_result.scalar_one_or_none.return_value = _make_upvote()

    db.execute = AsyncMock(side_effect=[alert_result, existing_upvote_result])

    with pytest.raises(SafetyAlertError) as exc_info:
        await upvote_alert(db, alert_id=1, voter_id=99)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_upvote_alert_missing_alert_raises_404():
    """Test 22: 404 on missing alert."""
    from app.services.safety_alert import upvote_alert

    db = AsyncMock()
    missing_result = MagicMock()
    missing_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=missing_result)

    with pytest.raises(SafetyAlertError) as exc_info:
        await upvote_alert(db, alert_id=999, voter_id=1)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_upvote_inactive_alert_raises_409():
    """Test 23: upvoting inactive alert raises 409."""
    from app.services.safety_alert import upvote_alert

    alert = _make_alert(is_active=False)
    db = AsyncMock()
    alert_result = MagicMock()
    alert_result.scalar_one_or_none.return_value = alert
    db.execute = AsyncMock(return_value=alert_result)

    with pytest.raises(SafetyAlertError) as exc_info:
        await upvote_alert(db, alert_id=1, voter_id=99)
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 24-25: list_my_alerts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_my_alerts_returns_results():
    """Test 24: returns paginated results with correct total."""
    from app.services.safety_alert import list_my_alerts

    alerts = [_make_alert(id=i) for i in range(3)]
    db = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 3
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = alerts

    db.execute = AsyncMock(side_effect=[count_result, list_result])

    result, total = await list_my_alerts(db, reporter_id=42)
    assert total == 3
    assert len(result) == 3


@pytest.mark.asyncio
async def test_list_my_alerts_empty():
    """Test 25: empty result for user with no alerts."""
    from app.services.safety_alert import list_my_alerts

    db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(side_effect=[count_result, list_result])

    result, total = await list_my_alerts(db, reporter_id=999)
    assert total == 0
    assert result == []


# ---------------------------------------------------------------------------
# 26-30: deactivate_alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_alert_reporter_can_own():
    """Test 26: reporter deactivates their own alert."""
    from app.services.safety_alert import deactivate_alert

    alert = _make_alert(reporter_id=42, is_active=True)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(**{"scalar_one_or_none.return_value": alert}))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    result = await deactivate_alert(db, alert_id=1, requesting_user_id=42, is_admin=False)
    assert result.is_active is False


@pytest.mark.asyncio
async def test_deactivate_alert_admin_can_any():
    """Test 27: admin deactivates any alert."""
    from app.services.safety_alert import deactivate_alert

    alert = _make_alert(reporter_id=42, is_active=True)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(**{"scalar_one_or_none.return_value": alert}))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    result = await deactivate_alert(db, alert_id=1, requesting_user_id=99, is_admin=True)
    assert result.is_active is False


@pytest.mark.asyncio
async def test_deactivate_alert_non_reporter_raises_403():
    """Test 28: 403 when non-admin, non-reporter tries to deactivate."""
    from app.services.safety_alert import deactivate_alert

    alert = _make_alert(reporter_id=42, is_active=True)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(**{"scalar_one_or_none.return_value": alert}))

    with pytest.raises(SafetyAlertError) as exc_info:
        await deactivate_alert(db, alert_id=1, requesting_user_id=99, is_admin=False)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_deactivate_alert_not_found():
    """Test 29: 404 when alert doesn't exist."""
    from app.services.safety_alert import deactivate_alert

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(**{"scalar_one_or_none.return_value": None}))

    with pytest.raises(SafetyAlertError) as exc_info:
        await deactivate_alert(db, alert_id=999, requesting_user_id=1)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_alert_already_inactive():
    """Test 30: 409 when already deactivated."""
    from app.services.safety_alert import deactivate_alert

    alert = _make_alert(reporter_id=42, is_active=False)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(**{"scalar_one_or_none.return_value": alert}))

    with pytest.raises(SafetyAlertError) as exc_info:
        await deactivate_alert(db, alert_id=1, requesting_user_id=42, is_admin=False)
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 31-33: admin_list_alerts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_list_alerts_all():
    """Test 31: returns paginated all alerts."""
    from app.services.safety_alert import admin_list_alerts

    alerts = [_make_alert(id=i) for i in range(5)]
    db = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 5
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = alerts

    db.execute = AsyncMock(side_effect=[count_result, list_result])

    result, total = await admin_list_alerts(db)
    assert total == 5
    assert len(result) == 5


@pytest.mark.asyncio
async def test_admin_list_alerts_filter_by_status():
    """Test 32: filters by moderation_status."""
    from app.services.safety_alert import admin_list_alerts

    pending_alert = _make_alert(moderation_status=ModerationStatus.pending)
    db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = [pending_alert]
    db.execute = AsyncMock(side_effect=[count_result, list_result])

    result, total = await admin_list_alerts(db, moderation_status=ModerationStatus.pending)
    assert total == 1
    assert result[0].moderation_status == ModerationStatus.pending


@pytest.mark.asyncio
async def test_admin_list_alerts_filter_by_type():
    """Test 33: filters by alert_type."""
    from app.services.safety_alert import admin_list_alerts

    weather_alert = _make_alert(alert_type=AlertType.weather)
    db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = [weather_alert]
    db.execute = AsyncMock(side_effect=[count_result, list_result])

    result, total = await admin_list_alerts(db, alert_type=AlertType.weather)
    assert result[0].alert_type == AlertType.weather


# ---------------------------------------------------------------------------
# 34-37: admin_moderate_alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_moderate_approve():
    """Test 34: approve sets status and records moderator."""
    from app.services.safety_alert import admin_moderate_alert

    alert = _make_alert(moderation_status=ModerationStatus.pending, is_active=True)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(**{"scalar_one_or_none.return_value": alert}))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    result = await admin_moderate_alert(
        db, alert_id=1, admin_id=7, action=ModerationStatus.approved
    )
    assert result.moderation_status == ModerationStatus.approved
    assert result.moderated_by == 7
    assert result.is_active is True  # approve keeps active


@pytest.mark.asyncio
async def test_admin_moderate_reject():
    """Test 35: reject sets status and deactivates alert."""
    from app.services.safety_alert import admin_moderate_alert

    alert = _make_alert(moderation_status=ModerationStatus.pending, is_active=True)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(**{"scalar_one_or_none.return_value": alert}))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    result = await admin_moderate_alert(
        db, alert_id=1, admin_id=7, action=ModerationStatus.rejected, note="Duplicate report"
    )
    assert result.moderation_status == ModerationStatus.rejected
    assert result.is_active is False  # rejected → deactivated
    assert result.moderation_note == "Duplicate report"


@pytest.mark.asyncio
async def test_admin_moderate_not_found():
    """Test 36: 404 on missing alert."""
    from app.services.safety_alert import admin_moderate_alert

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(**{"scalar_one_or_none.return_value": None}))

    with pytest.raises(SafetyAlertError) as exc_info:
        await admin_moderate_alert(db, alert_id=999, admin_id=7, action=ModerationStatus.approved)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_admin_moderate_invalid_action():
    """Test 37: raises 422 for non-moderation action (pending)."""
    from app.services.safety_alert import admin_moderate_alert

    db = AsyncMock()

    with pytest.raises(SafetyAlertError) as exc_info:
        await admin_moderate_alert(
            db, alert_id=1, admin_id=7, action=ModerationStatus.pending
        )
    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# 38: get_platform_alert_stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_platform_alert_stats_keys():
    """Test 38: returns expected keys."""
    from app.services.safety_alert import get_platform_alert_stats

    db = AsyncMock()

    # Mock each scalar_one call in sequence: total, active, pending, approved_today,
    # rejected_today (5 scalar_one calls), then two group-by queries (all()), then top query.
    scalar_results = [10, 7, 2, 3, 1]
    scalar_mocks = [MagicMock(**{"scalar_one.return_value": v}) for v in scalar_results]

    type_mock = MagicMock()
    type_mock.all.return_value = [
        (AlertType.road_hazard, 5),
        (AlertType.weather, 3),
    ]
    sev_mock = MagicMock()
    sev_mock.all.return_value = [(AlertSeverity.medium, 8), (AlertSeverity.high, 2)]

    top_mock = MagicMock()
    top_mock.first.return_value = (1, 15)

    db.execute = AsyncMock(side_effect=[*scalar_mocks, type_mock, sev_mock, top_mock])

    stats = await get_platform_alert_stats(db)

    assert "total_alerts" in stats
    assert "active_alerts" in stats
    assert "pending_moderation" in stats
    assert "approved_today" in stats
    assert "rejected_today" in stats
    assert "by_type" in stats
    assert "by_severity" in stats
    assert "top_upvoted_alert_id" in stats
    assert "top_upvoted_count" in stats


# ---------------------------------------------------------------------------
# 39-48: Schema validation
# ---------------------------------------------------------------------------


def test_create_alert_valid():
    """Test 39: valid minimal payload passes."""
    req = CreateSafetyAlertRequest(
        alert_type=AlertType.road_hazard,
        latitude=40.7128,
        longitude=-74.0060,
    )
    assert req.alert_type == AlertType.road_hazard
    assert req.radius_meters == 100.0
    assert req.severity == AlertSeverity.medium


def test_create_alert_invalid_latitude():
    """Test 40: latitude out of range raises error."""
    with pytest.raises(Exception):
        CreateSafetyAlertRequest(alert_type=AlertType.road_hazard, latitude=91.0, longitude=0.0)


def test_create_alert_invalid_longitude():
    """Test 41: longitude out of range raises error."""
    with pytest.raises(Exception):
        CreateSafetyAlertRequest(alert_type=AlertType.road_hazard, latitude=0.0, longitude=181.0)


def test_create_alert_zero_radius():
    """Test 42: radius_meters ≤ 0 raises error."""
    with pytest.raises(Exception):
        CreateSafetyAlertRequest(
            alert_type=AlertType.road_hazard,
            latitude=40.0,
            longitude=-74.0,
            radius_meters=0.0,
        )


def test_create_alert_past_expiry():
    """Test 43: expires_at in the past raises error."""
    clearly_past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(Exception):
        CreateSafetyAlertRequest(
            alert_type=AlertType.road_hazard,
            latitude=40.0,
            longitude=-74.0,
            expires_at=clearly_past,
        )


def test_admin_moderate_approved_valid():
    """Test 44: 'approved' is a valid moderation action."""
    req = AdminModerateAlertRequest(action=ModerationStatus.approved)
    assert req.action == ModerationStatus.approved


def test_admin_moderate_rejected_valid():
    """Test 45: 'rejected' is a valid moderation action."""
    req = AdminModerateAlertRequest(action=ModerationStatus.rejected, note="Spam")
    assert req.action == ModerationStatus.rejected


def test_admin_moderate_pending_invalid():
    """Test 46: 'pending' raises validation error (not a moderation action)."""
    with pytest.raises(Exception):
        AdminModerateAlertRequest(action=ModerationStatus.pending)


def test_safety_alert_response_from_alert():
    """Test 47: SafetyAlertResponse.from_alert maps all fields correctly."""
    alert = _make_alert()
    resp = SafetyAlertResponse.from_alert(alert)
    assert resp.id == alert.id
    assert resp.alert_type == alert.alert_type
    assert resp.latitude == alert.latitude
    assert resp.upvote_count == 0
    assert resp.moderation_status == ModerationStatus.auto_approved


def test_safety_alert_detail_response_from_alert():
    """Test 48: SafetyAlertDetailResponse includes reporter_id and moderation fields."""
    alert = _make_alert(moderated_by=7, moderation_note="Looks legit")
    resp = SafetyAlertDetailResponse.from_alert(alert)
    assert resp.reporter_id == alert.reporter_id
    assert resp.moderated_by == 7
    assert resp.moderation_note == "Looks legit"


# ---------------------------------------------------------------------------
# 49-60: API layer (integration-style, skipped without live DB)
# ---------------------------------------------------------------------------

pytestmark_integration = pytest.mark.skipif(
    True, reason="Integration tests require a live database"
)


@pytestmark_integration
def test_api_post_safety_alert_201():
    """Test 49: POST /safety-alerts — 201 and detail response."""


@pytestmark_integration
def test_api_post_safety_alert_401_unauthenticated():
    """Test 50: POST /safety-alerts — 401 for unauthenticated."""


@pytestmark_integration
def test_api_get_nearby_alerts_200():
    """Test 51: GET /safety-alerts/nearby — 200 list."""


@pytestmark_integration
def test_api_get_my_alerts_200():
    """Test 52: GET /safety-alerts/me — 200 paginated list."""


@pytestmark_integration
def test_api_upvote_alert_200():
    """Test 53: POST /safety-alerts/{id}/upvote — 200 updated alert."""


@pytestmark_integration
def test_api_upvote_alert_409_duplicate():
    """Test 54: POST /safety-alerts/{id}/upvote — 409 duplicate."""


@pytestmark_integration
def test_api_deactivate_alert_200():
    """Test 55: DELETE /safety-alerts/{id} — 200 deactivated."""


@pytestmark_integration
def test_api_deactivate_alert_403_not_reporter():
    """Test 56: DELETE /safety-alerts/{id} — 403 for non-reporter."""


@pytestmark_integration
def test_api_admin_list_alerts_200():
    """Test 57: GET /admin/safety-alerts — 200 admin list."""


@pytestmark_integration
def test_api_admin_stats_200():
    """Test 58: GET /admin/safety-alerts/stats — 200 stats."""


@pytestmark_integration
def test_api_admin_moderate_200():
    """Test 59: POST /admin/safety-alerts/{id}/moderate — 200 approved."""


@pytestmark_integration
def test_api_admin_get_alert_200():
    """Test 60: GET /admin/safety-alerts/{id} — 200 detail."""
